#!/bin/bash
# Builds Virten Studio.app and VirtenStudio-<version>.dmg on a Mac (Apple Silicon or Intel).
#
#   1. Install Python 3.12 from python.org (one time).
#   2. Copy the whole Virten Studio folder to the Mac (e.g. via Google Drive).
#   3. In Terminal:  cd /path/to/the/unpacked/folder && bash packaging/build_mac.sh
#
# The .dmg appears in dist/ and, if sync is set up, in your sync folder so other Macs get the update.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PY="${PYTHON:-python3.12}"
command -v "$PY" >/dev/null || PY=python3

echo "== Creating build environment"
"$PY" -m venv .venv-mac
source .venv-mac/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller -c packaging/constraints.txt

echo "== Checking the app starts and its models load"
python - <<'EOF'
import sys
sys.path.insert(0, ".")
from autostyle import vision, features, looks
print("accelerator:", vision.accelerator()[1])
print("looks:", len(looks.list_looks()), "features:", len(features.FEATURE_NAMES))
import numpy as np
print("clip ok:", vision.clip_embed([np.zeros((224, 224, 3), np.uint8)]).shape)
EOF

echo "== Making the app icon"
ICONSET="$(mktemp -d)/VirtenStudio.iconset"
mkdir -p "$ICONSET"
for s in 16 32 64 128 256 512; do
  sips -z $s $s autostyle/icon.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2)); sips -z $d $d autostyle/icon.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o packaging/icon.icns

echo "== Building Virten Studio.app"
rm -rf build dist
pyinstaller --noconfirm packaging/autostyle.spec
# (OpenCV inside the .app is handled by the runtime hook packaging/rth_cv2_mac.py.)

echo "== Licence check"
python packaging/check_bundle.py "dist/Virten Studio.app"

echo "== Self-testing the built app"
if ! "dist/Virten Studio.app/Contents/MacOS/Virten Studio" --selftest; then
  echo "The built app failed its self-test:"
  cat "$HOME/Library/Application Support/Virten Studio/selftest.txt"
  exit 1
fi
tail -n 7 "$HOME/Library/Application Support/Virten Studio/selftest.txt"

VERSION="$(python -c 'import sys; sys.path.insert(0, "."); from autostyle import __version__; print(__version__)')"
DMG="dist/VirtenStudio-${VERSION}.dmg"
echo "== Making ${DMG}"
STAGE="$(mktemp -d)"
cp -R "dist/Virten Studio.app" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "Virten Studio ${VERSION}" -srcfolder "$STAGE" -ov -format UDZO "$DMG"

python packaging/publish.py "$DMG" mac || true
# Keep a copy next to the build kit (e.g. in Google Drive) so other Macs can install without building.
cp "$DMG" "$ROOT/.." 2>/dev/null || true
echo
echo "Done: ${ROOT}/${DMG}"
echo "Open it and drag Virten Studio into Applications. If macOS says it can't verify the app (it isn't"
echo "signed with an Apple developer certificate): System Settings > Privacy & Security > Open Anyway,"
echo "or run:  xattr -cr \"/Applications/Virten Studio.app\""
