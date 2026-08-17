#!/usr/bin/env python3
"""Build the machine-readable registry index from TOML entries."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "index.json"


def main() -> int:
    """Run the command-line entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    packages = []
    for path in sorted((ROOT / "packages").glob("*.toml")):
        with path.open("rb") as handle:
            packages.append(tomllib.load(handle))
    rendered = json.dumps(
        {"registry_version": 1, "packages": packages},
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"

    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print("index.json is stale; run make generate", file=sys.stderr)
            return 1
        print("index.json is current.")
        return 0

    OUTPUT.write_text(rendered, encoding="utf-8")
    print(
        f"Generated {OUTPUT.relative_to(ROOT)} with {len(packages)} packages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
