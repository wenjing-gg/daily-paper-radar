#!/usr/bin/env bash
# macOS/Linux 的兼容入口。
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
exec "${PYTHON:-python3}" "$SKILL_DIR/scripts/run_daily.py" "$@"
