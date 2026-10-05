#!/usr/bin/env bash
# macOS / Linux equivalent of start_chrome_debug.ps1
set -euo pipefail
PROFILE_DIR="${1:-$HOME/.research-blog-agent/chrome-profile}"
PORT="${PORT:-9222}"
if [[ "$(uname)" == "Darwin" ]]; then
  CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
else
  CHROME="$(command -v google-chrome || command -v google-chrome-stable || command -v chromium)"
fi
mkdir -p "$PROFILE_DIR"
"$CHROME" --remote-debugging-port="$PORT" --user-data-dir="$PROFILE_DIR" https://chatgpt.com/ >/dev/null 2>&1 &
echo "Chrome started on port $PORT with profile $PROFILE_DIR"
