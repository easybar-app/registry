from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


VALIDATE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate.py"
SPEC = importlib.util.spec_from_file_location("registry_validate", VALIDATE_PATH)
assert SPEC is not None and SPEC.loader is not None
registry_validate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = registry_validate
SPEC.loader.exec_module(registry_validate)


def registry_entry(latest: str = "1.2.3") -> dict:
    return {
        "name": "demo",
        "kind": "widget",
        "latest": latest,
        "description": "Demo package",
        "categories": ["utilities"],
    }


def source_manifest(version: str = "1.2.3") -> dict:
    return {
        "manifest_version": 2,
        "name": "demo",
        "version": version,
        "kind": "widget",
        "description": "Demo package",
        "categories": ["utilities"],
        "minimum_easybar_kit_version": "0.50.0",
    }


class SourceManifestValidationTests(unittest.TestCase):
    def test_equal_source_is_published_latest(self) -> None:
        self.assertTrue(
            registry_validate.validate_source_manifest(
                "demo", registry_entry(), source_manifest()
            )
        )

    def test_source_may_be_ahead_of_registry(self) -> None:
        self.assertFalse(
            registry_validate.validate_source_manifest(
                "demo", registry_entry(), source_manifest("1.2.4")
            )
        )

    def test_source_cannot_be_behind_registry(self) -> None:
        with self.assertRaisesRegex(ValueError, "older than registry latest"):
            registry_validate.validate_source_manifest(
                "demo", registry_entry(), source_manifest("1.2.2")
            )

    def test_source_must_use_manifest_version_two(self) -> None:
        package = source_manifest()
        package["manifest_version"] = 3
        with self.assertRaisesRegex(ValueError, "manifest_version must be 2"):
            registry_validate.validate_source_manifest("demo", registry_entry(), package)

    def test_source_requires_minimum_easybar_kit_version(self) -> None:
        package = source_manifest()
        del package["minimum_easybar_kit_version"]
        with self.assertRaisesRegex(ValueError, "minimum_easybar_kit_version"):
            registry_validate.validate_source_manifest("demo", registry_entry(), package)


if __name__ == "__main__":
    unittest.main()
