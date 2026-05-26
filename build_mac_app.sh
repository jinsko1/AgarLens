#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

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

export PYINSTALLER_CONFIG_DIR="$PWD/.pyinstaller"
export MPLCONFIGDIR="$PWD/.matplotlib"
mkdir -p "$PYINSTALLER_CONFIG_DIR" "$MPLCONFIGDIR"

"$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --windowed \
  --name AgarLens \
  --add-data "runs/detect/train-5/weights/best.pt:runs/detect/train-5/weights" \
  --collect-data ultralytics \
  growth_analyzer_gui.py

echo "Built dist/AgarLens.app"
