#!/bin/bash
# Launch a dedicated Chrome instance for @LeegoHere automation.
# Separate profile + port 9222. Does NOT affect your normal Chrome.
# After launch: log into Twitter as @LeegoHere in this window.

PROFILE="$HOME/.leegohere-chrome"
mkdir -p "$PROFILE"

/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --user-data-dir="$PROFILE" \
  --remote-debugging-port=9222 \
  --remote-allow-origins="*" \
  --no-first-run \
  --no-default-browser-check \
  --window-size=1280,900 \
  "https://x.com" "https://app.lessie.ai" &

echo "✓ LeegoHere Chrome started (port 9222, profile: $PROFILE)"
echo "  Log into Twitter as @LeegoHere if not already logged in."
echo "  Log into Lessie in the second tab (needed for CDP share links)."
