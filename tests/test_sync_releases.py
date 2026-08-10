from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


SYNC_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sync_releases.py"
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


def release(version: str) -> dict:
    base = (
        "https://github.com/easybar-app/widgets/releases/download/"
        f"demo-v{version}/"
    )
    archive_name = f"demo-{version}.tar.gz"
    return {
        "tag_name": f"demo-v{version}",
        "assets": [
            {"name": archive_name, "browser_download_url": base + archive_name},
            {
                "name": archive_name + ".sha256",
                "browser_download_url": base + archive_name + ".sha256",
            },
        ],
    }


class ReleaseManifestValidationTests(unittest.TestCase):
    def test_manifest_v2_is_required(self) -> None:
        package = manifest()
        package["manifest_version"] = 1
        with self.assertRaisesRegex(ValueError, "manifest_version must be 2"):
            registry_sync.validate_release_manifest("demo", "1.2.4", package)

    def test_old_easybar_field_is_rejected(self) -> None:
        package = manifest()
        package["minimum_easybar_version"] = "0.49.0"
        with self.assertRaisesRegex(ValueError, "unsupported package manifest fields"):
            registry_sync.validate_release_manifest("demo", "1.2.4", package)

    def test_minimum_easybar_kit_version_is_required(self) -> None:
        package = manifest()
        del package["minimum_easybar_kit_version"]
        with self.assertRaisesRegex(ValueError, "minimum_easybar_kit_version"):
            registry_sync.validate_release_manifest("demo", "1.2.4", package)


class SynchronizeEntryTests(unittest.TestCase):
    def test_existing_historical_release_is_verified_without_manifest_parsing(self) -> None:
        releases = [("1.2.3", release("1.2.3"))]
        with (
            patch.object(
                registry_sync, "verified_archive", return_value=(b"archive", "a" * 64)
            ) as verify_archive,
            patch.object(registry_sync, "verified_manifest") as verify_manifest,
        ):
            self.assertIsNone(
                registry_sync.synchronize_entry(
                    "easybar-app/widgets", "demo", entry(), releases, None
                )
            )
        verify_archive.assert_called_once()
        verify_manifest.assert_not_called()

    def test_new_release_must_pass_v2_verification(self) -> None:
        releases = [
            ("1.2.3", release("1.2.3")),
            ("1.2.4", release("1.2.4")),
        ]
        with (
            patch.object(
                registry_sync, "verified_archive", return_value=(b"archive", "a" * 64)
            ),
            patch.object(
                registry_sync,
                "verified_manifest",
                return_value=(manifest(), "b" * 64),
            ) as verify,
        ):
            rendered = registry_sync.synchronize_entry(
                "easybar-app/widgets", "demo", entry(), releases, None
            )

        self.assertIsNotNone(rendered)
        assert rendered is not None
        self.assertIn('latest = "1.2.4"', rendered)
        self.assertIn('version = "1.2.3"', rendered)
        self.assertIn('version = "1.2.4"', rendered)
        verify.assert_called_once()

    def test_new_historical_release_is_rejected(self) -> None:
        releases = [
            ("1.2.2", release("1.2.2")),
            ("1.2.3", release("1.2.3")),
        ]
        with patch.object(
            registry_sync, "verified_archive", return_value=(b"archive", "a" * 64)
        ):
            with self.assertRaisesRegex(ValueError, "predates registry latest"):
                registry_sync.synchronize_entry(
                    "easybar-app/widgets", "demo", entry(), releases, None
                )


if __name__ == "__main__":
    unittest.main()
