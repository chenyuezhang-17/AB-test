#!/bin/bash
# Daily runner for @Leegowlessie warmup.
# Called by launchd at 10:00 AM every day.

LOG="/tmp/leegowlessie_warmup.log"

echo "==============================" >> "$LOG"
echo "$(date '+%Y-%m-%d %H:%M:%S') Starting warmup_auto.py" >> "$LOG"

export PATH="/Users/lessie/.local/bin:$HOME/.nvm/versions/node/v24.14.1/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export HOME="/Users/lessie"

set -a
source /Users/lessie/cc/AB-test/.env 2>/dev/null
set +a

# Ensure Leegowlessie Chrome is running (port 9223)
if ! curl -s http://localhost:9223/json/version > /dev/null 2>&1; then
    echo "$(date '+%H:%M:%S') Launching Leegowlessie Chrome..." >> "$LOG"
    /Users/lessie/cc/AB-test/scripts/launch_leegowlessie_browser.sh >> "$LOG" 2>&1
    sleep 8
fi

cd /Users/lessie/cc/AB-test
/usr/bin/python3 /Users/lessie/cc/AB-test/warmup/warmup_auto.py 2>/dev/null

echo "$(date '+%Y-%m-%d %H:%M:%S') warmup_auto.py finished (exit $?)" >> "$LOG"
