# EasyBar Widget Registry

Official package registry for installable [EasyBar widgets](https://github.com/easybar-app/widgets).
Packages target the shared EasyBarKit runtime, so the same published package can be consumed by the
custom EasyBar frontend or EasyBar Native when its required capabilities are available.

## Layout

```text
registry.toml      Registry identity and schema version
packages/*.toml    Package metadata and published versions
index.json         Generated catalog consumed by clients
```

Each package entry contains its name, kind, latest published version, description, categories,
source, and immutable published versions.

The registry schema and package-manifest schema are independent. Registry entries remain
`entry_version = 1`; current package archives use **manifest version 2** and declare
`minimum_easybar_kit_version`.

## Validation

With the widgets repository checked out beside this repository:

```sh
make check
```

This validates registry metadata, validates the current widgets source manifest contract, verifies
the generated index, checks the reproducible archive checksum whenever source and registry point to
the same release, and runs validator regression tests.

The widgets source tree may be ahead of the registry between merge and publication. That
state is valid: installs still resolve the latest published registry release. A source version older
than the registry is rejected.

## Synchronization

Published releases from `easybar-app/widgets` are synchronized automatically.

The synchronization process treats previously recorded releases as immutable registry history. It
re-verifies their published archive and checksum bytes without parsing their package manifests. Only
newly discovered versions are opened as package manifests, and every new release must use manifest
version 2, declare `minimum_easybar_kit_version`, pass the strict field contract, and match its
published checksum before it can become the latest version. Existing archive URLs and checksums may
not change.

Historical registry records may refer to archives created before the current manifest contract, but
the sync path never interprets those old manifests and the EasyBarKit runtime does not accept them as
a compatibility path. They are retained only as immutable release history.

Only packages already present under `packages/` are synchronized automatically. Adding a new package
to the registry requires explicit review.

Run the same process locally with:

```sh
make sync
make check
```

This repository has no `install-local` target because it publishes metadata rather than executable
products.
