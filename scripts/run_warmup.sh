#!/bin/bash
# Hourly runner for warmup. Script checks PT time internally — skips if outside window.

LOCK="/tmp/leego-warmup.lock"
LOG="/tmp/leegowlessie_warmup.log"

# Skip if already running
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK")" 2>/dev/null; then
    exit 0
fi
echo $$ > "$LOCK"
trap "rm -f $LOCK" EXIT

echo "==============================" >> "$LOG"
echo "$(date '+%Y-%m-%d %H:%M:%S') Starting warmup_auto.py" >> "$LOG"

export PATH="/Users/lessie/.local/bin:$HOME/.nvm/versions/node/v24.14.1/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export HOME="/Users/lessie"

set -a
source /Users/lessie/cc/AB-test/.env 2>/dev/null
set +a

# Bypass proxy for localhost CDP connections
export ALL_PROXY=""
export HTTP_PROXY=""
export HTTPS_PROXY=""
export NO_PROXY="*"
export no_proxy="*"

# Ensure Chrome is running — auto-launch if not
PORT="${CHROME_PORT:-9222}"
if ! curl -s "http://localhost:${PORT}/json/version" > /dev/null 2>&1; then
    echo "$(date '+%H:%M:%S') Chrome not running, launching..." >> "$LOG"
    bash /Users/lessie/cc/AB-test/scripts/launch_leegohere_browser.sh >> "$LOG" 2>&1
    sleep 8
    if ! curl -s "http://localhost:${PORT}/json/version" > /dev/null 2>&1; then
        echo "$(date '+%H:%M:%S') Chrome still not running, giving up" >> "$LOG"
        exit 1
    fi
fi

cd /Users/lessie/cc/AB-test
caffeinate -i /opt/homebrew/bin/python3 /Users/lessie/cc/AB-test/warmup/warmup_auto.py >> "$LOG" 2>&1

echo "$(date '+%Y-%m-%d %H:%M:%S') warmup_auto.py finished (exit $?)" >> "$LOG"
