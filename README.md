# EasyBar Widget Registry

This repository is the official discovery index for installable [EasyBar widgets](https://github.com/easybar-app/widgets). It contains metadata only; widget and library source remains in its owning repository.

## Layout

```text
registry.toml      Registry identity and schema version
packages/*.toml    Searchable package entries and source-manifest pointers
index.json         Generated machine-readable catalog consumed by clients
```

Each registry entry mirrors the package name, kind, latest version, description, and categories from the package's `package.toml`. The `source` table identifies the source repository, ref, and manifest path. During initial development the official entries track `main`; released entries should be changed to immutable tags before the package manager treats them as stable artifacts.

## Validation

With the official widgets repository checked out beside this repository:

```sh
make check
```

The check validates every entry, cross-checks it against package metadata, and ensures `index.json` is current.
