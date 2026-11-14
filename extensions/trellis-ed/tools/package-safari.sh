#!/bin/sh
# Run on macOS with the full Xcode app installed and selected.
set -eu
cd "$(dirname "$0")/.."
npm run package
xcrun safari-web-extension-converter dist/safari --project-location dist/safari-xcode --app-name "Trellis Ed" --bundle-identifier edu.gatech.trellis.ed --swift --macos-only --no-open
printf '\nOpen dist/safari-xcode in Xcode, choose your signing team, and build.\n'
