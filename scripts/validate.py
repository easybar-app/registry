#!/usr/bin/env python3
"""Validate registry entries and cross-check their package manifests."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?")


def load(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--widgets-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        registry = load(ROOT / "registry.toml")
        if registry.get("registry_version") != 1 or registry.get("entries") != "packages":
            raise ValueError("invalid registry.toml")

        entries: dict[str, dict] = {}
        for path in sorted((ROOT / "packages").glob("*.toml")):
            entry = load(path)
            name = entry.get("name")
            if entry.get("entry_version") != 1:
                raise ValueError(f"{path.name}: entry_version must be 1")
            if not isinstance(name, str) or path.stem != name:
                raise ValueError(f"{path.name}: filename and package name must match")
            if name in entries:
                raise ValueError(f"duplicate registry package: {name}")
            if entry.get("kind") not in {"widget", "library"}:
                raise ValueError(f"{name}: invalid kind")
            if not isinstance(entry.get("latest"), str) or not SEMVER.fullmatch(entry["latest"]):
                raise ValueError(f"{name}: invalid latest version")
            source = entry.get("source", {})
            if source.get("repository") != "https://github.com/easybar-app/widgets":
                raise ValueError(f"{name}: invalid source repository")
            if not isinstance(source.get("ref"), str) or not source["ref"]:
                raise ValueError(f"{name}: missing source ref")
            expected_manifest = f"packages/{name}/package.toml"
            if source.get("manifest") != expected_manifest:
                raise ValueError(f"{name}: source manifest must be {expected_manifest}")

            manifest_path = args.widgets_dir / expected_manifest
            package = load(manifest_path)
            for registry_key, package_key in (
                ("name", "name"),
                ("kind", "kind"),
                ("latest", "version"),
                ("description", "description"),
                ("categories", "categories"),
            ):
                if entry.get(registry_key) != package.get(package_key):
                    raise ValueError(f"{name}: registry {registry_key} does not match package metadata")
            entries[name] = entry

        if not entries:
            raise ValueError("registry contains no package entries")
    except (OSError, tomllib.TOMLDecodeError, ValueError) as error:
        print(f"Registry validation failed: {error}", file=sys.stderr)
        return 1

    print(f"Validated {len(entries)} registry entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
