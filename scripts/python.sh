#!/usr/bin/env bash
# Select a supported Python interpreter.
set -euo pipefail

candidates=()
if [ -n "${PYTHON_BIN:-}" ]; then
  candidates+=("${PYTHON_BIN}")
fi
candidates+=(python3 python3.14 python3.13 python3.12 python3.11)

for candidate in "${candidates[@]}"; do
  if command -v "${candidate}" >/dev/null 2>&1 &&
    "${candidate}" -c 'import tomllib' >/dev/null 2>&1; then
    exec "${candidate}" "$@"
  fi
done

echo "Python 3.11 or newer with tomllib is required." >&2
exit 1
