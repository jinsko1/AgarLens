#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="AgarLens"
PROJECT_DIR="$(pwd)"
DIST_DIR="$PROJECT_DIR/dist"
APP_DIR="$DIST_DIR/$APP_NAME.app"
MACOS_DIR="$APP_DIR/Contents/MacOS"
RESOURCES_DIR="$APP_DIR/Contents/Resources"

rm -rf "$APP_DIR" "$DIST_DIR/${APP_NAME}_Launcher_macOS.zip"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

cat > "$APP_DIR/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>AgarLens</string>
  <key>CFBundleIdentifier</key>
  <string>edu.local.agarlens.launcher</string>
  <key>CFBundleName</key>
  <string>AgarLens</string>
  <key>CFBundleDisplayName</key>
  <string>AgarLens</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>0.1.0</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

cat > "$MACOS_DIR/AgarLens" <<LAUNCHER
#!/bin/zsh
PROJECT_DIR="$PROJECT_DIR"
cd "\$PROJECT_DIR" || exit 1

export YOLO_AUTOINSTALL=false

if [[ -n "\${AGARLENS_PYTHON:-}" ]]; then
  PYTHON_BIN="\$AGARLENS_PYTHON"
elif [[ -x "\$PROJECT_DIR/venv/bin/python" ]]; then
  PYTHON_BIN="\$PROJECT_DIR/venv/bin/python"
elif [[ -x "\$PROJECT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="\$PROJECT_DIR/.venv/bin/python"
else
  PYTHON_BIN="\$(command -v python3)"
fi

if [[ -z "\$PYTHON_BIN" ]]; then
  osascript -e 'display alert "AgarLens could not find Python 3." message "Run setup_mac.command first, or install Python 3."'
  exit 1
fi

exec "\$PYTHON_BIN" "\$PROJECT_DIR/growth_analyzer_gui.py"
LAUNCHER

chmod +x "$MACOS_DIR/AgarLens"
plutil -lint "$APP_DIR/Contents/Info.plist" >/dev/null
ditto -c -k --sequesterRsrc --keepParent "$APP_DIR" "$DIST_DIR/${APP_NAME}_Launcher_macOS.zip"

echo "Created:"
echo "$APP_DIR"
echo "$DIST_DIR/${APP_NAME}_Launcher_macOS.zip"
