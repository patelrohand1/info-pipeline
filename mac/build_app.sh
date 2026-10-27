#!/bin/bash
# Builds "Reading Triage.app" in ~/Applications. It runs this checkout's .venv, so rebuild if you move the folder.
#   bash mac/build_app.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Applications/Reading Triage.app"
BUILD="$REPO/mac/build"
PY="$REPO/.venv/bin/python"

[ -x "$PY" ] || { echo "No .venv found. Run the setup command in README.md first."; exit 1; }
"$PY" -c "import webview" 2>/dev/null || { echo "pywebview missing: uv pip install -r requirements.txt"; exit 1; }

# Icon: 1024px PNG -> .iconset -> .icns
mkdir -p "$BUILD"
"$PY" "$REPO/mac/make_icon.py" "$BUILD/AppIcon.png"
ICONSET="$BUILD/AppIcon.iconset"
rm -rf "$ICONSET" && mkdir "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$BUILD/AppIcon.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$BUILD/AppIcon.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$BUILD/AppIcon.icns"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BUILD/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/MacOS/Reading Triage" <<EOF
#!/bin/bash
cd "$REPO"
exec "$PY" "$REPO/mac/desktop.py"
EOF
chmod +x "$APP/Contents/MacOS/Reading Triage"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Reading Triage</string>
  <key>CFBundleDisplayName</key><string>Reading Triage</string>
  <key>CFBundleIdentifier</key><string>com.rohan.readingtriage</string>
  <key>CFBundleExecutable</key><string>Reading Triage</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF

# Make Finder/Dock pick up the new icon.
touch "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" 2>/dev/null || true
echo "Built $APP"
echo "Open it from Launchpad/Spotlight (\"Reading Triage\"), or drag it to the Dock."
