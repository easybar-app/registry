# EasyBar Widget Registry

This repository is the official discovery index for installable [EasyBar widgets](https://github.com/easybar-app/widgets). It contains metadata only; widget and library source remains in its owning repository.

## Layout

```text
registry.toml      Registry identity and schema version
packages/*.toml    Searchable package entries and immutable release metadata
index.json         Generated machine-readable catalog consumed by clients
```

Each registry entry mirrors the package name, kind, latest version, description, and categories from the package's `package.toml`. The `source` table identifies its project page. Every `versions` entry points to an immutable GitHub release archive and pins its SHA-256 digest. Installers must verify that digest before extracting package content.

## Validation

With the official widgets repository checked out beside this repository:

```sh
make check
```

The check validates every entry, cross-checks it against package metadata, reproduces each latest archive to verify its digest, and ensures `index.json` is current.

## Release synchronization

The `Sync widget releases` workflow runs twice per hour and can also be started manually from
GitHub Actions. It discovers published releases from `easybar-app/widgets`, downloads each package
archive and checksum, verifies their SHA-256 digest, reads the packaged manifest, updates immutable
version entries, regenerates `index.json`, validates the result, and commits only when the registry
changed.

Existing versions are immutable. If a previously recorded archive or checksum changes, or a
published historical release disappears, synchronization fails instead of rewriting trusted
metadata.

Synchronization only updates packages that already have a file below `packages/`. Adding a package
to the official registry remains an explicit review decision; publishing a new version of an
already registered package is automatic and requires no cross-repository secret.

Run the same reconciliation locally with:

```sh
make sync
make check
```
