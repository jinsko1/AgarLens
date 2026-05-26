#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

STAMP="$(date +%Y%m%d-%H%M%S)"
BUNDLE_ROOT="$PWD/dist/AgarLens_User_Bundle_$STAMP"
ZIP_PATH="$PWD/dist/AgarLens_User_Bundle_$STAMP.zip"

mkdir -p "$BUNDLE_ROOT"
mkdir -p "$BUNDLE_ROOT/runs/detect/train-5/weights"

copy_item() {
  local item="$1"
  if [[ -e "$item" ]]; then
    cp -R "$item" "$BUNDLE_ROOT/"
  fi
}

copy_item "README.md"
copy_item "LICENSE"
copy_item "requirements.txt"
copy_item "growth_analyzer_gui.py"
copy_item "analysis_worker.py"
copy_item "analyze_plates.py"
copy_item "count_colonies.py"
copy_item "count_colonies_yolo.py"
copy_item "setup_mac.command"
copy_item "run_growth_analyzer.command"
copy_item "run_agarlens.sh"
copy_item "run_agarlens.bat"
copy_item "azure.tcl"
copy_item "theme"
copy_item "Sample Colonies Images"
copy_item "images"

if [[ -f "runs/detect/train-5/weights/best.pt" ]]; then
  cp "runs/detect/train-5/weights/best.pt" "$BUNDLE_ROOT/runs/detect/train-5/weights/best.pt"
else
  echo "Warning: YOLO model missing at runs/detect/train-5/weights/best.pt"
fi

chmod +x "$BUNDLE_ROOT/setup_mac.command" "$BUNDLE_ROOT/run_growth_analyzer.command" "$BUNDLE_ROOT/run_agarlens.sh" 2>/dev/null || true

(
  cd "$PWD/dist"
  zip -r -X "$ZIP_PATH" "$(basename "$BUNDLE_ROOT")" -x "*/.DS_Store"
)

echo "Created:"
echo "$ZIP_PATH"
