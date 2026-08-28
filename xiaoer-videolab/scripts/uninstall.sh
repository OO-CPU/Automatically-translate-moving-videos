#!/usr/bin/env bash
# Xiaoer VideoLab — remove the launchd service. (The browser extension must be
# removed by hand from chrome://extensions/.)
set -euo pipefail
LABEL="com.xiaoer.videolab"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
[[ -f "$PLIST" ]] && launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "✓ Uninstalled $LABEL"
echo "  Remove the extension manually at chrome://extensions/"
