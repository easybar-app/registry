# EasyBar Widget Registry

Official package registry for installable [EasyBar widgets](https://github.com/easybar-app/widgets).

## Layout

```text
registry.toml      Registry identity and schema version
packages/*.toml    Package metadata and published versions
index.json         Generated catalog consumed by clients
```

Each package entry contains its name, kind, latest version, description, categories, source, and published versions.

Published versions reference immutable release archives and include their SHA-256 digest for verification.

## Validation

With the widgets repository checked out beside this repository:

```sh
make check
```

This validates registry metadata, verifies published package archives and checksums, and ensures `index.json` is up to date.

## Synchronization

Published releases from `easybar-app/widgets` are synchronized automatically.

The synchronization process verifies release archives, updates version metadata, regenerates `index.json`, validates the registry, and commits changes when necessary.

Existing published versions are immutable. Changes to previously recorded archives or checksums cause synchronization to fail.

Only packages already present under `packages/` are synchronized automatically. Adding a new package to the registry requires explicit review.

Run the same process locally with:

```sh
make sync
make check
```
