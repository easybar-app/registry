# EasyBar Widget Registry

The official discovery index for installable EasyBar widgets and Lua libraries.

## Features

- Package names, descriptions, categories, and published versions
- Immutable release archive URLs and SHA-256 checksums
- Automatic synchronization from official widget releases
- Generated `index.json` consumed by EasyBar and EasyBar Native
- Validation against the current package source and registry contract

Browse the registry through the [Widget Store](https://easybar.dev/widget-store/catalog/) or from a
frontend CLI:

```sh
easybar widgets search
easybar-native widgets search
```

## Requirements for contributors

- Python 3.11 or newer
- Node.js with `npx` for formatting checks
- The [widgets repository](https://github.com/easybar-app/widgets) as a sibling checkout, or
  `WIDGETS_DIR` pointing to one

Run the complete validation suite with:

```sh
make check
```

## Documentation

- [Widget Store overview](https://easybar.dev/widget-store/overview/)
- [Install and manage packages](https://easybar.dev/widget-store/manage/)
- [Create and contribute packages](https://easybar.dev/widget-store/create-and-contribute/)
- [Package Store internals](https://easybar.dev/internals/package-store/)

## License

Licensed under the [Apache License 2.0](./LICENSE).
