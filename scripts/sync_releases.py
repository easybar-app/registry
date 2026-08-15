#!/usr/bin/env python3
"""Synchronize published EasyBar widget package releases into the registry."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ROOT / "packages"
DEFAULT_REPOSITORY = "easybar-app/widgets"
SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?")
CHECKSUM = re.compile(r"([0-9a-f]{64})[ \t]+\*?([^\r\n]+)")
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_CHECKSUM_BYTES = 4096

SUPPORTED_MANIFEST_FIELDS = {
    "manifest_version",
    "name",
    "version",
    "minimum_easybar_kit_version",
    "kind",
    "description",
    "license",
    "readme",
    "categories",
    "entrypoint",
    "repository",
    "dependencies",
    "exports",
    "requirements",
    "settings",
}


def load(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def request(url: str, token: str | None, limit: int) -> tuple[bytes, dict[str, str]]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "easybar-registry",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    if token and urllib.parse.urlparse(url).hostname == "api.github.com":
        headers["Authorization"] = f"Bearer {token}"

    with urllib.request.urlopen(
        urllib.request.Request(url, headers=headers),
        timeout=30,
    ) as response:
        data = response.read(limit + 1)

        if len(data) > limit:
            raise ValueError(f"download exceeds {limit} bytes: {url}")

        return data, dict(response.headers.items())


def github_releases(repository: str, token: str | None) -> list[dict]:
    releases: list[dict] = []
    page = 1

    while True:
        url = (
            f"https://api.github.com/repos/{repository}/releases"
            f"?per_page=100&page={page}"
        )
        payload, _ = request(url, token, 8 * 1024 * 1024)
        page_releases = json.loads(payload)

        if not isinstance(page_releases, list):
            raise ValueError("GitHub releases response is not a list")

        releases.extend(page_releases)

        if len(page_releases) < 100:
            return releases

        page += 1


def semver_key(version: str) -> tuple:
    core, separator, prerelease = version.partition("-")
    major, minor, patch = (int(component) for component in core.split("."))

    if not separator:
        return major, minor, patch, 1, ()

    identifiers = tuple(
        (0, int(identifier)) if identifier.isdigit() else (1, identifier)
        for identifier in prerelease.split(".")
    )

    return major, minor, patch, 0, identifiers


def parse_package_tag(tag: str) -> tuple[str, str] | None:
    name, separator, version = tag.rpartition("-v")

    if separator == "" or name == "" or not SEMVER.fullmatch(version):
        return None

    return name, version


def release_has_package_assets(release: dict, name: str, version: str) -> bool:
    archive_name = f"{name}-{version}.tar.gz"
    checksum_name = f"{archive_name}.sha256"

    asset_names = {
        asset.get("name")
        for asset in release.get("assets", [])
        if isinstance(asset, dict)
    }

    return archive_name in asset_names and checksum_name in asset_names


def discover_package_releases(
    releases: list[dict],
) -> dict[str, list[tuple[str, dict]]]:
    discovered: dict[str, list[tuple[str, dict]]] = {}

    for release in releases:
        if release.get("draft"):
            continue

        tag = release.get("tag_name")
        if not isinstance(tag, str):
            continue

        parsed = parse_package_tag(tag)
        if parsed is None:
            continue

        name, version = parsed

        # Ignore releases while their package assets are not complete. This also
        # prevents unrelated GitHub releases that merely resemble package tags
        # from becoming registry entries.
        if not release_has_package_assets(release, name, version):
            continue

        discovered.setdefault(name, []).append((version, release))

    return discovered


def releases_by_version(
    name: str,
    releases: list[tuple[str, dict]],
) -> dict[str, dict]:
    discovered: dict[str, dict] = {}

    for version, release in releases:
        if version in discovered:
            raise ValueError(f"{name}: duplicate published release {version}")

        discovered[version] = release

    return discovered


def release_assets(release: dict, name: str, version: str) -> tuple[str, str]:
    archive_name = f"{name}-{version}.tar.gz"
    checksum_name = f"{archive_name}.sha256"

    assets = {
        asset.get("name"): asset.get("browser_download_url")
        for asset in release.get("assets", [])
        if isinstance(asset, dict)
    }

    archive_url = assets.get(archive_name)
    checksum_url = assets.get(checksum_name)

    if not isinstance(archive_url, str) or not isinstance(checksum_url, str):
        raise ValueError(f"{name} {version}: release assets are incomplete")

    return archive_url, checksum_url


def validate_release_manifest(name: str, version: str, manifest: dict) -> None:
    unsupported = set(manifest) - SUPPORTED_MANIFEST_FIELDS

    if unsupported:
        fields = ", ".join(sorted(unsupported))
        raise ValueError(
            f"{name} {version}: unsupported package manifest fields: {fields}"
        )

    if manifest.get("manifest_version") != 2:
        raise ValueError(
            f"{name} {version}: package manifest_version must be 2")

    if manifest.get("name") != name or manifest.get("version") != version:
        raise ValueError(
            f"{name} {version}: archive manifest identity does not match release"
        )

    if manifest.get("kind") not in {"widget", "library"}:
        raise ValueError(f"{name} {version}: archive manifest kind is invalid")

    if (
        not isinstance(manifest.get("description"), str)
        or not manifest["description"]
    ):
        raise ValueError(
            f"{name} {version}: archive manifest description is invalid")

    categories = manifest.get("categories")
    if (
        not isinstance(categories, list)
        or not categories
        or not all(
            isinstance(category, str) and category
            for category in categories
        )
    ):
        raise ValueError(
            f"{name} {version}: archive manifest categories are invalid")

    minimum = manifest.get("minimum_easybar_kit_version")
    if not isinstance(minimum, str) or not SEMVER.fullmatch(minimum):
        raise ValueError(
            f"{name} {version}: "
            "archive manifest minimum_easybar_kit_version is invalid"
        )


def verified_archive(
    name: str,
    version: str,
    archive_url: str,
    checksum_url: str,
    token: str | None,
) -> tuple[bytes, str]:
    archive, _ = request(archive_url, token, MAX_ARCHIVE_BYTES)
    checksum_data, _ = request(checksum_url, token, MAX_CHECKSUM_BYTES)

    checksum_text = checksum_data.decode("utf-8").strip()
    match = CHECKSUM.fullmatch(checksum_text)
    expected_filename = f"{name}-{version}.tar.gz"

    if match is None or match.group(2) != expected_filename:
        raise ValueError(f"{name} {version}: invalid checksum asset")

    expected_digest = match.group(1)
    actual_digest = hashlib.sha256(archive).hexdigest()

    if actual_digest != expected_digest:
        raise ValueError(f"{name} {version}: archive checksum does not match")

    return archive, actual_digest


def verified_manifest(
    name: str,
    version: str,
    archive_url: str,
    checksum_url: str,
    token: str | None,
) -> tuple[dict, str]:
    archive, actual_digest = verified_archive(
        name,
        version,
        archive_url,
        checksum_url,
        token,
    )

    try:
        with gzip.GzipFile(fileobj=io.BytesIO(archive), mode="rb") as compressed:
            with tarfile.open(fileobj=compressed, mode="r:") as package_archive:
                member = package_archive.getmember("package.toml")

                if not member.isfile() or member.size > 1024 * 1024:
                    raise ValueError(
                        f"{name} {version}: invalid package manifest asset"
                    )

                extracted = package_archive.extractfile(member)

                if extracted is None:
                    raise ValueError(
                        f"{name} {version}: package manifest is unreadable"
                    )

                manifest = tomllib.loads(extracted.read().decode("utf-8"))
    except (
        KeyError,
        OSError,
        tarfile.TarError,
        UnicodeDecodeError,
        tomllib.TOMLDecodeError,
    ) as error:
        raise ValueError(
            f"{name} {version}: invalid package archive: {error}"
        ) from error

    validate_release_manifest(name, version, manifest)
    return manifest, actual_digest


def quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_entry(
    repository: str,
    name: str,
    latest_manifest: dict,
    versions: list[dict[str, str]],
) -> str:
    categories = ", ".join(
        quote(category) for category in latest_manifest["categories"]
    )

    lines = [
        "entry_version = 1",
        f"name = {quote(name)}",
        f"kind = {quote(latest_manifest['kind'])}",
        f"latest = {quote(latest_manifest['version'])}",
        f"description = {quote(latest_manifest['description'])}",
        f"categories = [{categories}]",
        "",
        "[source]",
        f"repository = {quote(f'https://github.com/{repository}')}",
    ]

    for version in versions:
        lines.extend(
            [
                "",
                "[[versions]]",
                f"version = {quote(version['version'])}",
                f"archive = {quote(version['archive'])}",
                f"sha256 = {quote(version['sha256'])}",
            ]
        )

    return "\n".join(lines) + "\n"


def bootstrap_entry(
    repository: str,
    name: str,
    releases: list[tuple[str, dict]],
    token: str | None,
) -> str:
    """Build a new registry entry from all published releases for one package."""

    discovered = releases_by_version(name, releases)

    if not discovered:
        raise ValueError(f"{name}: no published releases found")

    versions: list[dict[str, str]] = []
    manifests: dict[str, dict] = {}
    expected_kind: str | None = None

    for version in sorted(discovered, key=semver_key):
        archive_url, checksum_url = release_assets(
            discovered[version],
            name,
            version,
        )

        manifest, digest = verified_manifest(
            name,
            version,
            archive_url,
            checksum_url,
            token,
        )

        kind = manifest["kind"]

        if expected_kind is None:
            expected_kind = kind
        elif kind != expected_kind:
            raise ValueError(
                f"{name} {version}: package kind changed from {expected_kind}"
            )

        manifests[version] = manifest
        versions.append(
            {
                "version": version,
                "archive": archive_url,
                "sha256": digest,
            }
        )

    latest = versions[-1]["version"]
    latest_manifest = manifests[latest]

    return render_entry(
        repository,
        name,
        latest_manifest,
        versions,
    )


def synchronize_entry(
    repository: str,
    name: str,
    entry: dict,
    releases: list[tuple[str, dict]],
    token: str | None,
) -> str | None:
    """Return replacement entry text when new manifest-v2 releases were discovered."""

    existing_versions = entry.get("versions")

    if not isinstance(existing_versions, list) or not existing_versions:
        raise ValueError(
            f"{name}: registry entry contains no published versions")

    existing_by_version: dict[str, dict[str, str]] = {}

    for existing in existing_versions:
        if not isinstance(existing, dict):
            raise ValueError(
                f"{name}: invalid existing registry version entry")

        version = existing.get("version")
        archive = existing.get("archive")
        digest = existing.get("sha256")

        if not isinstance(version, str) or not SEMVER.fullmatch(version):
            raise ValueError(f"{name}: invalid existing registry version")

        if not isinstance(archive, str) or not isinstance(digest, str):
            raise ValueError(
                f"{name} {version}: incomplete existing registry metadata"
            )

        if version in existing_by_version:
            raise ValueError(
                f"{name}: duplicate existing registry version {version}"
            )

        existing_by_version[version] = {
            "version": version,
            "archive": archive,
            "sha256": digest,
        }

    discovered_by_version = releases_by_version(name, releases)

    missing = set(existing_by_version) - set(discovered_by_version)
    if missing:
        raise ValueError(
            f"{name}: published releases disappeared: "
            + ", ".join(sorted(missing, key=semver_key))
        )

    for version, existing in existing_by_version.items():
        archive_url, checksum_url = release_assets(
            discovered_by_version[version],
            name,
            version,
        )

        if archive_url != existing["archive"]:
            raise ValueError(
                f"{name} {version}: published release archive URL changed"
            )

        _, digest = verified_archive(
            name,
            version,
            archive_url,
            checksum_url,
            token,
        )

        if digest != existing["sha256"]:
            raise ValueError(
                f"{name} {version}: published release checksum changed"
            )

    latest_existing = max(existing_by_version, key=semver_key)

    new_versions = sorted(
        set(discovered_by_version) - set(existing_by_version),
        key=semver_key,
    )

    if not new_versions:
        return None

    if any(
        semver_key(version) <= semver_key(latest_existing)
        for version in new_versions
    ):
        raise ValueError(
            f"{name}: new release history predates registry latest "
            f"{latest_existing}"
        )

    versions = list(existing_by_version.values())
    manifests: dict[str, dict] = {}
    expected_kind = entry.get("kind")

    for version in new_versions:
        archive_url, checksum_url = release_assets(
            discovered_by_version[version],
            name,
            version,
        )

        manifest, digest = verified_manifest(
            name,
            version,
            archive_url,
            checksum_url,
            token,
        )

        if manifest.get("kind") != expected_kind:
            raise ValueError(
                f"{name} {version}: package kind changed from {expected_kind}"
            )

        manifests[version] = manifest
        versions.append(
            {
                "version": version,
                "archive": archive_url,
                "sha256": digest,
            }
        )

    versions.sort(key=lambda item: semver_key(item["version"]))

    latest = versions[-1]["version"]
    latest_manifest = manifests.get(latest)

    if latest_manifest is None:
        raise ValueError(
            f"{name}: synchronized latest release did not use manifest v2"
        )

    return render_entry(
        repository,
        name,
        latest_manifest,
        versions,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")

    try:
        entries: dict[str, tuple[Path, dict]] = {}

        for path in sorted(PACKAGES.glob("*.toml")):
            entry = load(path)
            name = entry.get("name")

            if not isinstance(name, str) or name != path.stem:
                raise ValueError(
                    f"invalid registry entry identity: {path.name}"
                )

            entries[name] = (path, entry)

        published = discover_package_releases(
            github_releases(args.repository, token)
        )

        if not published:
            raise ValueError("no published package releases found")

        changed: list[str] = []

        # Update packages that already exist in the registry.
        for name, (path, entry) in entries.items():
            releases = published.get(name)

            if not releases:
                raise ValueError(
                    f"{name}: no published releases found"
                )

            rendered = synchronize_entry(
                args.repository,
                name,
                entry,
                releases,
                token,
            )

            if rendered is None:
                continue

            changed.append(name)

            if not args.check:
                path.write_text(rendered, encoding="utf-8")

        # Bootstrap packages that have valid published package releases but no
        # registry entry yet.
        new_names = sorted(set(published) - set(entries))

        for name in new_names:
            rendered = bootstrap_entry(
                args.repository,
                name,
                published[name],
                token,
            )

            path = PACKAGES / f"{name}.toml"
            changed.append(name)

            if not args.check:
                path.write_text(rendered, encoding="utf-8")

        if args.check and changed:
            raise ValueError(
                "registry is stale for: " + ", ".join(changed)
            )

    except (
        OSError,
        UnicodeDecodeError,
        urllib.error.URLError,
        json.JSONDecodeError,
        tomllib.TOMLDecodeError,
        ValueError,
    ) as error:
        print(
            f"Registry synchronization failed: {error}",
            file=sys.stderr,
        )
        return 1

    if changed:
        print(
            "Synchronized registry releases for: "
            + ", ".join(changed)
        )
    else:
        print(
            f"Registry releases are current for {len(entries)} packages."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
