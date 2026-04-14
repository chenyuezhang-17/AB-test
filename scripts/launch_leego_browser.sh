#!/bin/bash
# Launch a dedicated Chrome instance for Leego automation.
# Completely isolated from your main Chrome (separate user data dir).
# After launch: log into Twitter as @alliiexia in this window.

LEEGO_PROFILE="$HOME/.leego-chrome"
mkdir -p "$LEEGO_PROFILE"

/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --user-data-dir="$LEEGO_PROFILE" \
  --remote-debugging-port=9222 \
  --no-first-run \
  --no-default-browser-check \
  --window-size=1280,900 \
  "https://x.com" &

echo "✓ Leego Chrome started (profile: $LEEGO_PROFILE)"
echo "  Log into Twitter as @alliiexia if not already logged in."
