#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

STAMP="$(date +%Y%m%d-%H%M%S)"
DIST_DIR="$PWD/dist"
mkdir -p "$DIST_DIR"

COMMON_ITEMS=(
  "README.md"
  "LICENSE"
  "requirements.txt"
  "growth_analyzer_gui.py"
  "analysis_worker.py"
  "analyze_plates.py"
  "count_colonies.py"
  "count_colonies_yolo.py"
  "Sample Colonies Images"
  "images"
)

copy_item() {
  local item="$1"
  local bundle_root="$2"
  if [[ -e "$item" ]]; then
    cp -R "$item" "$bundle_root/"
  fi
}

copy_model() {
  local bundle_root="$1"
  mkdir -p "$bundle_root/runs/detect/train-5/weights"
  if [[ -f "runs/detect/train-5/weights/best.pt" ]]; then
    cp "runs/detect/train-5/weights/best.pt" "$bundle_root/runs/detect/train-5/weights/best.pt"
  else
    echo "Warning: YOLO model missing at runs/detect/train-5/weights/best.pt"
  fi
}

zip_bundle() {
  local bundle_root="$1"
  local zip_path="$2"
  (
    cd "$DIST_DIR"
    zip -r -X "$zip_path" "$(basename "$bundle_root")" -x "*/.DS_Store"
  )
  echo "Created:"
  echo "$zip_path"
}

create_bundle() {
  local platform="$1"
  shift
  local bundle_root="$DIST_DIR/AgarLens_${platform}_$STAMP"
  local zip_path="$DIST_DIR/AgarLens_${platform}_$STAMP.zip"

  mkdir -p "$bundle_root"
  for item in "${COMMON_ITEMS[@]}"; do
    copy_item "$item" "$bundle_root"
  done
  for item in "$@"; do
    copy_item "$item" "$bundle_root"
  done
  copy_model "$bundle_root"

  chmod +x "$bundle_root/"*.command "$bundle_root/"*.sh 2>/dev/null || true
  zip_bundle "$bundle_root" "$zip_path"
}

create_bundle "macOS" \
  "setup_mac.command" \
  "run_growth_analyzer.command" \
  "run_agarlens.sh"

create_bundle "Windows" \
  "setup_windows.bat" \
  "run_agarlens.bat"
