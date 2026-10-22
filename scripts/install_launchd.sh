#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
exec "${PYTHON:-python3}" "$SKILL_DIR/scripts/install_launchd.py" "$@"
