#!/usr/bin/env python3
"""Validate registry entries and cross-check their package manifests."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?")
SHA256 = re.compile(r"[0-9a-f]{64}")


def load(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def validate_versions(name: str, entry: dict) -> None:
    versions = entry.get("versions")
    if not isinstance(versions, list) or not versions:
        raise ValueError(f"{name}: versions must contain at least one release")

    seen: set[str] = set()
    for release in versions:
        if not isinstance(release, dict):
            raise ValueError(f"{name}: invalid version entry")
        version = release.get("version")
        if not isinstance(version, str) or not SEMVER.fullmatch(version):
            raise ValueError(f"{name}: invalid release version")
        if version in seen:
            raise ValueError(f"{name}: duplicate release version: {version}")
        seen.add(version)

        expected_archive = (
            "https://github.com/easybar-app/widgets/releases/download/"
            f"{name}-v{version}/{name}-{version}.tar.gz"
        )
        if release.get("archive") != expected_archive:
            raise ValueError(f"{name} {version}: archive URL must be {expected_archive}")
        digest = release.get("sha256")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ValueError(f"{name} {version}: invalid sha256")

    if entry["latest"] not in seen:
        raise ValueError(f"{name}: latest version is missing from versions")


def validate_latest_digest(name: str, entry: dict, widgets_dir: Path) -> None:
    release = next(item for item in entry["versions"] if item["version"] == entry["latest"])
    packager = widgets_dir / "scripts" / "release" / "package.py"
    with tempfile.TemporaryDirectory() as temporary_directory:
        result = subprocess.run(
            [
                sys.executable,
                str(packager),
                "--package",
                name,
                "--version",
                entry["latest"],
                "--output-dir",
                temporary_directory,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise ValueError(f"{name}: failed to reproduce latest archive: {message}")
        archive = Path(temporary_directory) / f"{name}-{entry['latest']}.tar.gz"
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != release["sha256"]:
            raise ValueError(
                f"{name}: latest sha256 does not match deterministic package archive"
            )


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
            if set(source) != {"repository"}:
                raise ValueError(f"{name}: source must only declare its repository")
            validate_versions(name, entry)
            expected_manifest = f"packages/{name}/package.toml"

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
            validate_latest_digest(name, entry, args.widgets_dir)
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
