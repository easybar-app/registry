from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SYNC_PATH = Path(__file__).resolve(
).parents[1] / "scripts" / "sync_releases.py"
SPEC = importlib.util.spec_from_file_location("registry_sync", SYNC_PATH)
assert SPEC is not None and SPEC.loader is not None
registry_sync = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = registry_sync
SPEC.loader.exec_module(registry_sync)


def manifest(version: str = "1.2.4") -> dict:
    return {
        "manifest_version": 2,
        "name": "demo",
        "version": version,
        "minimum_easybar_kit_version": "0.50.0",
        "kind": "widget",
        "description": "Demo package",
        "categories": ["utilities"],
    }


def entry() -> dict:
    return {
        "name": "demo",
        "kind": "widget",
        "latest": "1.2.3",
        "description": "Old metadata",
        "categories": ["utilities"],
        "versions": [
            {
                "version": "1.2.3",
                "archive": (
                    "https://github.com/easybar-app/widgets/releases/download/"
                    "demo-v1.2.3/demo-1.2.3.tar.gz"
                ),
                "sha256": "a" * 64,
            }
        ],
    }


def release(
    version: str,
    name: str = "demo",
    complete: bool = True,
) -> dict:
    base = (
        "https://github.com/easybar-app/widgets/releases/download/"
        f"{name}-v{version}/"
    )
    archive_name = f"{name}-{version}.tar.gz"

    assets = [
        {
            "name": archive_name,
            "browser_download_url": base + archive_name,
        }
    ]

    if complete:
        assets.append(
            {
                "name": archive_name + ".sha256",
                "browser_download_url": base + archive_name + ".sha256",
            }
        )

    return {
        "tag_name": f"{name}-v{version}",
        "assets": assets,
    }


class RegistryMetadataValidationTests(unittest.TestCase):
    def test_unknown_historical_manifest_fields_are_ignored(self) -> None:
        package = manifest()
        package["minimum_easybar_version"] = "0.49.0"

        registry_sync.validate_registry_metadata(
            "demo",
            "1.2.4",
            package,
        )

    def test_manifest_identity_must_match_release(self) -> None:
        package = manifest()
        package["version"] = "9.9.9"

        with self.assertRaisesRegex(
            ValueError,
            "identity does not match",
        ):
            registry_sync.validate_registry_metadata(
                "demo",
                "1.2.4",
                package,
            )

    def test_registry_metadata_fields_are_required(self) -> None:
        package = manifest()
        package["categories"] = []

        with self.assertRaisesRegex(
            ValueError,
            "categories are invalid",
        ):
            registry_sync.validate_registry_metadata(
                "demo",
                "1.2.4",
                package,
            )


class PackageDiscoveryTests(unittest.TestCase):
    def test_only_current_packages_with_complete_assets_are_discovered(
        self,
    ) -> None:
        releases = [
            release("1.2.4"),
            release("0.1.0", name="retired"),
            release("1.2.5", complete=False),
        ]

        discovered = registry_sync.discover_package_releases(
            releases,
            {"demo"},
        )

        self.assertEqual(
            [
                (version, item["tag_name"])
                for version, item in discovered["demo"]
            ],
            [("1.2.4", "demo-v1.2.4")],
        )
        self.assertNotIn("retired", discovered)

    def test_current_source_packages_are_loaded_from_widgets_tree(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            package_dir = root / "packages" / "demo"
            package_dir.mkdir(parents=True)

            (package_dir / "package.toml").write_text(
                'name = "demo"\nversion = "1.2.4"\n',
                encoding="utf-8",
            )

            packages = registry_sync.load_current_packages(root)

        self.assertEqual(set(packages), {"demo"})


class BootstrapEntryTests(unittest.TestCase):
    def test_bootstrap_verifies_history_but_reads_only_latest_manifest(
        self,
    ) -> None:
        releases = [
            ("1.0.0", release("1.0.0")),
            ("1.1.0", release("1.1.0")),
        ]

        def verify_archive(
            name: str,
            version: str,
            archive_url: str,
            checksum_url: str,
            token: str | None,
        ) -> tuple[bytes, str]:
            del name, archive_url, checksum_url, token

            return (
                version.encode(),
                ("a" if version == "1.0.0" else "b") * 64,
            )

        with (
            patch.object(
                registry_sync,
                "verified_archive",
                side_effect=verify_archive,
            ) as verify,
            patch.object(
                registry_sync,
                "manifest_from_archive",
                return_value=manifest("1.1.0"),
            ) as read_manifest,
        ):
            rendered = registry_sync.bootstrap_entry(
                "easybar-app/widgets",
                "demo",
                releases,
                None,
            )

        self.assertIn('latest = "1.1.0"', rendered)
        self.assertIn('version = "1.0.0"', rendered)
        self.assertIn('version = "1.1.0"', rendered)
        self.assertEqual(verify.call_count, 2)

        read_manifest.assert_called_once_with(
            "demo",
            "1.1.0",
            b"1.1.0",
        )


class SynchronizeEntryTests(unittest.TestCase):
    def test_existing_historical_release_is_verified_without_manifest_parsing(
        self,
    ) -> None:
        releases = [
            ("1.2.3", release("1.2.3")),
        ]

        with (
            patch.object(
                registry_sync,
                "verified_archive",
                return_value=(b"archive", "a" * 64),
            ) as verify_archive,
            patch.object(
                registry_sync,
                "manifest_from_archive",
            ) as read_manifest,
        ):
            self.assertIsNone(
                registry_sync.synchronize_entry(
                    "easybar-app/widgets",
                    "demo",
                    entry(),
                    releases,
                    None,
                )
            )

        verify_archive.assert_called_once()
        read_manifest.assert_not_called()

    def test_new_release_uses_latest_manifest_for_registry_metadata(
        self,
    ) -> None:
        releases = [
            ("1.2.3", release("1.2.3")),
            ("1.2.4", release("1.2.4")),
        ]

        def verify_archive(
            name: str,
            version: str,
            archive_url: str,
            checksum_url: str,
            token: str | None,
        ) -> tuple[bytes, str]:
            del name, archive_url, checksum_url, token

            if version == "1.2.3":
                return b"old", "a" * 64

            return b"new", "b" * 64

        with (
            patch.object(
                registry_sync,
                "verified_archive",
                side_effect=verify_archive,
            ),
            patch.object(
                registry_sync,
                "manifest_from_archive",
                return_value=manifest(),
            ) as read_manifest,
        ):
            rendered = registry_sync.synchronize_entry(
                "easybar-app/widgets",
                "demo",
                entry(),
                releases,
                None,
            )

        self.assertIsNotNone(rendered)
        assert rendered is not None

        self.assertIn('latest = "1.2.4"', rendered)
        self.assertIn('version = "1.2.3"', rendered)
        self.assertIn('version = "1.2.4"', rendered)

        read_manifest.assert_called_once_with(
            "demo",
            "1.2.4",
            b"new",
        )

    def test_unregistered_older_release_is_ignored(self) -> None:
        releases = [
            ("1.2.2", release("1.2.2")),
            ("1.2.3", release("1.2.3")),
        ]

        with (
            patch.object(
                registry_sync,
                "verified_archive",
                return_value=(b"archive", "a" * 64),
            ),
            patch.object(
                registry_sync,
                "manifest_from_archive",
            ) as read_manifest,
        ):
            rendered = registry_sync.synchronize_entry(
                "easybar-app/widgets",
                "demo",
                entry(),
                releases,
                None,
            )

        self.assertIsNone(rendered)
        read_manifest.assert_not_called()


if __name__ == "__main__":
    unittest.main()
