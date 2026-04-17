#!/bin/bash
# Daily runner for Lessie Twitter auto-post.
# Called by launchd at 9:05 AM every day.

LOG="/tmp/lessie_daily.log"
PIDLOG="/tmp/lessie_daily.pid"

echo "==============================" >> "$LOG"
echo "$(date '+%Y-%m-%d %H:%M:%S') Starting daily_auto.py" >> "$LOG"

# Set up environment (nvm node path for claude CLI)
export PATH="$HOME/.nvm/versions/node/v24.14.1/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export HOME="/Users/lessie"

# Load .env
set -a
source /Users/lessie/cc/AB-test/.env 2>/dev/null
set +a

# Ensure Leego Chrome is running (needs to be already logged in)
CHROME_RUNNING=$(pgrep -f "leego-chrome" | head -1)
if [ -z "$CHROME_RUNNING" ]; then
    echo "$(date '+%H:%M:%S') Launching Leego Chrome..." >> "$LOG"
    /Users/lessie/cc/AB-test/scripts/launch_leego_browser.sh >> "$LOG" 2>&1
    sleep 8  # wait for Chrome to start
fi

# Run the daily automation
# Note: LaunchAgent already captures stdout/stderr to $LOG via StandardOutPath.
# Redirect to /dev/null here to avoid double-logging every line.
cd /Users/lessie/cc/AB-test
/usr/bin/python3 /Users/lessie/cc/AB-test/daily_auto.py 2>/dev/null

echo "$(date '+%Y-%m-%d %H:%M:%S') daily_auto.py finished (exit $?)" >> "$LOG"
