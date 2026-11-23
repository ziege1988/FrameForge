#!/bin/sh
# Creates a compressed DMG with the app and a link to /Applications (uses only macOS built-in tools).
# Usage: packaging/macos/build_dmg.sh <version> <arch>
set -eu
VERSION="$1"; ARCH="$2"
APP="dist/FrameForge.app"
OUT="dist/FrameForge-${VERSION}-macos-${ARCH}.dmg"
STAGE=$(mktemp -d)
cp -R "$APP" "$STAGE/"
cp LICENSE "$STAGE/LICENSE.txt"
ln -s /Applications "$STAGE/Applications"
# Ad-hoc signature (free). Without a paid Apple Developer ID the app is not notarized.
codesign --force --deep --sign - "$STAGE/FrameForge.app"
hdiutil create -volname "FrameForge ${VERSION}" -srcfolder "$STAGE" -ov -format UDZO "$OUT"
rm -rf "$STAGE"
echo "$OUT"
