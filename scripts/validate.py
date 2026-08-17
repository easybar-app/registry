#!/usr/bin/env python3
"""Validate registry entries and cross-check their current package sources."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import total_ordering
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


@total_ordering
@dataclass(frozen=True)
class SemanticVersion:
    """Semantic version ordering used for source-versus-registry comparisons."""

    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: object) -> SemanticVersion | None:
        """Parse a semantic version when the value is valid."""
        if not isinstance(value, str) or not SEMVER.fullmatch(value):
            return None

        core, separator, prerelease = value.partition("-")
        major, minor, patch = (int(component) for component in core.split("."))
        identifiers = tuple(prerelease.split(".")) if separator else ()
        return cls(major, minor, patch, identifiers)

    def __lt__(self, other: object) -> bool:
        """Compare versions using semantic-version precedence."""
        if not isinstance(other, SemanticVersion):
            return NotImplemented

        left_core = (self.major, self.minor, self.patch)
        right_core = (other.major, other.minor, other.patch)
        if left_core != right_core:
            return left_core < right_core
        if not self.prerelease:
            return False
        if not other.prerelease:
            return True

        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            left_number = int(left) if left.isdigit() else None
            right_number = int(right) if right.isdigit() else None
            if left_number is not None and right_number is not None:
                return left_number < right_number
            if left_number is not None:
                return True
            if right_number is not None:
                return False
            return left < right

        return len(self.prerelease) < len(other.prerelease)


def load(path: Path) -> dict:
    """Load a TOML document."""
    with path.open("rb") as handle:
        return tomllib.load(handle)


def validate_versions(name: str, entry: dict) -> None:
    """Validate ordering and uniqueness of registry versions."""
    versions = entry.get("versions")
    if not isinstance(versions, list) or not versions:
        raise ValueError(f"{name}: versions must contain at least one release")

    seen: set[str] = set()
    for release in versions:
        if not isinstance(release, dict):
            raise ValueError(f"{name}: invalid version entry")
        version = release.get("version")
        if SemanticVersion.parse(version) is None:
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


def validate_source_manifest(name: str, entry: dict, package: dict) -> bool:
    """Validate the current source manifest and return whether it equals registry latest."""

    if package.get("manifest_version") != 2:
        raise ValueError(f"{name}: source manifest_version must be 2")
    if package.get("name") != name:
        raise ValueError(f"{name}: source package name does not match registry entry")
    if package.get("kind") != entry.get("kind"):
        raise ValueError(f"{name}: source package kind does not match registry entry")

    minimum = package.get("minimum_easybar_kit_version")
    if SemanticVersion.parse(minimum) is None:
        raise ValueError(f"{name}: invalid minimum_easybar_kit_version")

    source_version = SemanticVersion.parse(package.get("version"))
    registry_version = SemanticVersion.parse(entry.get("latest"))
    if source_version is None:
        raise ValueError(f"{name}: invalid source package version")
    if registry_version is None:
        raise ValueError(f"{name}: invalid registry latest version")
    if source_version < registry_version:
        raise ValueError(
            f"{name}: source version {package['version']} is older than registry latest {entry['latest']}"
        )

    if source_version != registry_version:
        return False

    for registry_key, package_key in (
        ("name", "name"),
        ("kind", "kind"),
        ("latest", "version"),
        ("description", "description"),
        ("categories", "categories"),
    ):
        if entry.get(registry_key) != package.get(package_key):
            raise ValueError(
                f"{name}: registry {registry_key} does not match current package metadata"
            )
    return True


def validate_latest_digest(name: str, entry: dict, widgets_dir: Path) -> None:
    """Validate the latest release archive digest."""
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
    """Run the command-line entry point."""
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
            if SemanticVersion.parse(entry.get("latest")) is None:
                raise ValueError(f"{name}: invalid latest version")
            source = entry.get("source", {})
            if source.get("repository") != "https://github.com/easybar-app/widgets":
                raise ValueError(f"{name}: invalid source repository")
            if set(source) != {"repository"}:
                raise ValueError(f"{name}: source must only declare its repository")
            validate_versions(name, entry)

            manifest_path = args.widgets_dir / "packages" / name / "package.toml"
            package = load(manifest_path)
            source_is_published_latest = validate_source_manifest(name, entry, package)
            if source_is_published_latest:
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
