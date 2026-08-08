#!/usr/bin/env python3
"""Synchronize registered packages with verified GitHub release assets."""

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


def load(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def request(url: str, token: str | None, limit: int) -> tuple[bytes, dict[str, str]]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "easybar-widget-registry",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token and urllib.parse.urlparse(url).hostname == "api.github.com":
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(
        urllib.request.Request(url, headers=headers), timeout=30
    ) as response:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError(f"download exceeds {limit} bytes: {url}")
        return data, dict(response.headers.items())


def github_releases(repository: str, token: str | None) -> list[dict]:
    releases: list[dict] = []
    page = 1
    while True:
        url = f"https://api.github.com/repos/{repository}/releases?per_page=100&page={page}"
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


def verified_manifest(
    name: str,
    version: str,
    archive_url: str,
    checksum_url: str,
    token: str | None,
) -> tuple[dict, str]:
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

    try:
        with gzip.GzipFile(fileobj=io.BytesIO(archive), mode="rb") as compressed:
            with tarfile.open(fileobj=compressed, mode="r:") as package_archive:
                member = package_archive.getmember("package.toml")
                if not member.isfile() or member.size > 1024 * 1024:
                    raise ValueError(f"{name} {version}: invalid package manifest asset")
                extracted = package_archive.extractfile(member)
                if extracted is None:
                    raise ValueError(f"{name} {version}: package manifest is unreadable")
                manifest = tomllib.loads(extracted.read().decode("utf-8"))
    except (KeyError, OSError, tarfile.TarError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"{name} {version}: invalid package archive: {error}") from error

    if manifest.get("name") != name or manifest.get("version") != version:
        raise ValueError(f"{name} {version}: archive manifest identity does not match release")
    if manifest.get("kind") not in {"widget", "library"}:
        raise ValueError(f"{name} {version}: archive manifest kind is invalid")
    if not isinstance(manifest.get("description"), str) or not manifest["description"]:
        raise ValueError(f"{name} {version}: archive manifest description is invalid")
    categories = manifest.get("categories")
    if not isinstance(categories, list) or not categories or not all(
        isinstance(category, str) and category for category in categories
    ):
        raise ValueError(f"{name} {version}: archive manifest categories are invalid")
    return manifest, actual_digest


def quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_entry(
    repository: str,
    name: str,
    latest_manifest: dict,
    versions: list[dict[str, str]],
) -> str:
    categories = ", ".join(quote(category) for category in latest_manifest["categories"])
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
                raise ValueError(f"invalid registry entry identity: {path.name}")
            entries[name] = (path, entry)
        if not entries:
            raise ValueError("registry contains no packages to synchronize")

        discovered: dict[str, list[tuple[str, dict]]] = {name: [] for name in entries}
        for release in github_releases(args.repository, token):
            if release.get("draft"):
                continue
            tag = release.get("tag_name")
            if not isinstance(tag, str):
                continue
            for name in entries:
                prefix = f"{name}-v"
                if tag.startswith(prefix):
                    version = tag[len(prefix) :]
                    if SEMVER.fullmatch(version):
                        discovered[name].append((version, release))
                    break

        changed: list[str] = []
        for name, (path, entry) in entries.items():
            releases = discovered[name]
            if not releases:
                raise ValueError(f"{name}: no published releases found")
            existing_versions = {
                release.get("version"): release for release in entry.get("versions", [])
            }
            versions: list[dict[str, str]] = []
            manifests: dict[str, dict] = {}
            seen: set[str] = set()
            for version, release in sorted(
                releases, key=lambda item: semver_key(item[0])
            ):
                if version in seen:
                    raise ValueError(f"{name}: duplicate published release {version}")
                seen.add(version)
                archive_url, checksum_url = release_assets(release, name, version)
                manifest, digest = verified_manifest(
                    name, version, archive_url, checksum_url, token
                )
                existing = existing_versions.get(version)
                if existing is not None and (
                    existing.get("archive") != archive_url
                    or existing.get("sha256") != digest
                ):
                    raise ValueError(
                        f"{name} {version}: published release metadata is immutable"
                    )
                manifests[version] = manifest
                versions.append(
                    {"version": version, "archive": archive_url, "sha256": digest}
                )

            missing = set(existing_versions) - seen
            if missing:
                raise ValueError(
                    f"{name}: published releases disappeared: {', '.join(sorted(missing))}"
                )

            latest = versions[-1]["version"]
            rendered = render_entry(args.repository, name, manifests[latest], versions)
            current = path.read_text(encoding="utf-8")
            if current != rendered:
                changed.append(name)
                if not args.check:
                    path.write_text(rendered, encoding="utf-8")

        if args.check and changed:
            raise ValueError("registry is stale for: " + ", ".join(changed))
    except (
        OSError,
        UnicodeDecodeError,
        urllib.error.URLError,
        json.JSONDecodeError,
        tomllib.TOMLDecodeError,
        ValueError,
    ) as error:
        print(f"Registry synchronization failed: {error}", file=sys.stderr)
        return 1

    if changed:
        print("Synchronized registry releases for: " + ", ".join(changed))
    else:
        print(f"Registry releases are current for {len(entries)} packages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
