#!/usr/bin/env bash
# Xiaoer VideoLab — one-shot updater.
#
# Pulls the latest code from GitHub, updates the yt-dlp engine to the newest
# nightly (so fast-moving sites like Bilibili keep working), and reinstalls the
# background service — preserving whatever VIDEOLAB_* settings you installed with
# (filename prefix, cookies browser, max height, …).
#
#   ./scripts/update.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.xiaoer.videolab"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
NIGHTLY="$HOME/.local/bin/yt-dlp-nightly"

echo "→ [1/4] Preserving your current settings…"
# Re-read the VIDEOLAB_* env baked into the installed plist so reinstall keeps them.
if [[ -f "$PLIST" ]]; then
  for var in VIDEOLAB_PORT VIDEOLAB_DOWNLOADS VIDEOLAB_PREFIX \
             VIDEOLAB_MAX_HEIGHT VIDEOLAB_COOKIES_BROWSER VIDEOLAB_APP_NAME; do
    val="$(/usr/libexec/PlistBuddy -c "Print :EnvironmentVariables:$var" "$PLIST" 2>/dev/null || true)"
    if [[ -n "$val" ]]; then
      export "$var=$val"
      echo "    $var=$val"
    fi
  done
else
  echo "    (no existing install found — fresh install)"
fi

echo "→ [2/4] Pulling latest code from GitHub…"
git -C "$PROJECT_DIR" pull --ff-only || echo "    ⚠ git pull skipped (offline or local changes) — continuing"

echo "→ [3/4] Updating the yt-dlp engine to the newest nightly…"
mkdir -p "$HOME/.local/bin"
if [[ -x "$NIGHTLY" ]]; then
  "$NIGHTLY" --update-to nightly || echo "    ⚠ self-update failed — keeping current nightly"
else
  echo "    Installing the nightly binary for the first time…"
  curl -fL -o "$NIGHTLY" \
    https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/latest/download/yt-dlp_macos
  chmod +x "$NIGHTLY"
fi
export VIDEOLAB_YT_DLP="$NIGHTLY"
echo "    yt-dlp: $("$NIGHTLY" --version)"

echo "→ [4/4] Reinstalling + restarting the service…"
bash "$PROJECT_DIR/scripts/install.sh"
