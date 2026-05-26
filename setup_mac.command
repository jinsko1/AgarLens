#!/bin/zsh
set -e

cd "$(dirname "$0")"

echo ""
echo "AgarLens setup"
echo "=============="
echo ""

if [ -n "$AGARLENS_PYTHON" ]; then
  PYTHON_BIN="$AGARLENS_PYTHON"
else
  PYTHON_BIN="$(command -v python3)"
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "Python 3 was not found."
  echo "Install Python 3, then run this setup file again."
  echo ""
  read -k 1 "?Press any key to close..."
  exit 1
fi

echo "Using Python:"
"$PYTHON_BIN" --version
echo ""

if [ ! -d "$PWD/venv" ]; then
  echo "Creating local virtual environment..."
  "$PYTHON_BIN" -m venv "$PWD/venv"
else
  echo "Using existing local virtual environment."
fi

echo ""
echo "Installing AgarLens dependencies..."
"$PWD/venv/bin/python" -m pip install --upgrade pip
"$PWD/venv/bin/python" -m pip install -r requirements.txt

echo ""
if [ -f "$PWD/runs/detect/train-5/weights/best.pt" ]; then
  echo "YOLO model found:"
  echo "$PWD/runs/detect/train-5/weights/best.pt"
else
  echo "YOLO model was not found at:"
  echo "$PWD/runs/detect/train-5/weights/best.pt"
  echo ""
  echo "The app can still open, but the colony counter needs best.pt in that location."
fi

echo ""
echo "Setup complete."
echo "Next time, double-click run_growth_analyzer.command to start AgarLens."
echo ""
read -k 1 "?Press any key to close..."
