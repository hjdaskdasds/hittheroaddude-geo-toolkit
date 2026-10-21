#!/usr/bin/env bash
set -euo pipefail
TOOLKIT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$TOOLKIT_ROOT/publish_check.py" "$@"
