#!/bin/bash
# Launch a dedicated Chrome instance for @Leegowlessie automation.
# Separate profile + port 9223 (alliiexia uses 9222).
# After launch: log into Twitter as @Leegowlessie in this window.

PROFILE="$HOME/.leegowlessie-chrome"
mkdir -p "$PROFILE"

/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --user-data-dir="$PROFILE" \
  --remote-debugging-port=9223 \
  --no-first-run \
  --no-default-browser-check \
  --window-size=1280,900 \
  "https://x.com" &

echo "✓ Leegowlessie Chrome started (port 9223, profile: $PROFILE)"
echo "  Log into Twitter as @Leegowlessie if not already logged in."
