#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
export YOLO_AUTOINSTALL=false

if [[ -n "${AGARLENS_PYTHON:-}" ]]; then
  PYTHON_BIN="$AGARLENS_PYTHON"
elif [[ -x "$PWD/venv/bin/python" ]]; then
  PYTHON_BIN="$PWD/venv/bin/python"
elif [[ -x "$PWD/.venv/bin/python" ]]; then
  PYTHON_BIN="$PWD/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi

if [[ -z "$PYTHON_BIN" ]]; then
  echo "python3 was not found. Install Python 3 or set AGARLENS_PYTHON."
  exit 1
fi

exec "$PYTHON_BIN" "$PWD/growth_analyzer_gui.py"
