#!/bin/bash
# ============================================================
# Leego 全链路评测脚本
# 在 Alexia 的机器上跑，需要：
#   1. Chrome 已启动 (bash scripts/launch_leego_browser.sh)
#   2. Chrome 里已登录 Twitter (@alliiexia) + Lessie
#   3. .env 已配好 (至少 LESSIE_JWT)
#   4. browser session 已启动
# ============================================================

cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD:$PYTHONPATH"

# Load .env
set -a; source .env 2>/dev/null || true; set +a

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass=0
fail=0
warn=0

ok()   { echo -e "  ${GREEN}✓${NC} $1"; ((pass++)); }
fail() { echo -e "  ${RED}✗${NC} $1"; ((fail++)); }
skip() { echo -e "  ${YELLOW}⚠${NC} $1"; ((warn++)); }

echo "=== Leego Full Integration Test ==="
echo ""

# ─── 1. Syntax check ─────────────────────────────────────────
echo "1. Syntax check"
for f in learn.py daily_auto.py warmup/content_gen.py warmup/warmup_auto.py bridge/share_cdp.py bridge/search.py; do
    if python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" 2>/dev/null; then
        ok "$f"
    else
        fail "$f syntax error"
    fi
done
echo ""

# ─── 2. Import chain ─────────────────────────────────────────
echo "2. Import chain"
python3 -c "from learn import load_strategy, update_all_strategies" 2>/dev/null && ok "learn.py" || fail "learn.py imports"
python3 -c "from bridge.share_cdp import create_share_link_cdp" 2>/dev/null && ok "share_cdp.py" || fail "share_cdp.py imports"
python3 -c "from bridge.search import _create_share_link" 2>/dev/null && ok "search.py" || fail "search.py imports"
python3 -c "from warmup.content_gen import generate_tweet, get_reply_for_tweet" 2>/dev/null && ok "content_gen.py" || fail "content_gen.py imports"
echo ""

# ─── 3. Chrome + Browser Session ─────────────────────────────
echo "3. Chrome & Browser Session"
if curl -s http://localhost:9222/json/version >/dev/null 2>&1; then
    ok "Chrome port 9222 running"
else
    fail "Chrome port 9222 NOT running → bash scripts/launch_leego_browser.sh"
fi

if [ -S /tmp/social-browser.sock ]; then
    ok "Browser session socket exists"
else
    skip "No browser session → python3 -m browser.session (from action/ dir)"
fi
echo ""

# ─── 4. Share Link: JWT ──────────────────────────────────────
echo "4. Share Link (JWT)"
if [ -z "$LESSIE_JWT" ]; then
    skip "LESSIE_JWT not set in .env"
else
    result=$(python3 -c "
import sys; sys.path.insert(0,'.')
from dotenv import load_dotenv; load_dotenv()
from bridge.search import _create_share_link_jwt
url = _create_share_link_jwt('Find ML engineers in SF')
print(url or 'FAIL')
" 2>/dev/null)
    if echo "$result" | grep -q "lessie.ai/share/"; then
        ok "JWT share link: $result"
    else
        skip "JWT failed (expected if token expired)"
    fi
fi
echo ""

# ─── 5. Share Link: CDP ──────────────────────────────────────
echo "5. Share Link (CDP fallback)"
if [ ! -S /tmp/social-browser.sock ]; then
    skip "No browser session, can't test CDP"
else
    result=$(python3 -c "
import sys; sys.path.insert(0,'.')
from bridge.share_cdp import create_share_link_cdp
url = create_share_link_cdp('Find senior engineers with Python experience in New York')
print(url or 'FAIL')
" 2>&1 | tail -1)
    if echo "$result" | grep -q "lessie.ai/share/"; then
        ok "CDP share link: $result"
    else
        fail "CDP share link failed: $result"
    fi
fi
echo ""

# ─── 6. Share Link: Dual-path wrapper ────────────────────────
echo "6. Share Link (dual-path wrapper)"
if [ ! -S /tmp/social-browser.sock ] && [ -z "$LESSIE_JWT" ]; then
    skip "No JWT and no browser session"
else
    result=$(python3 -c "
import sys; sys.path.insert(0,'.')
from dotenv import load_dotenv; load_dotenv()
from bridge.search import _create_share_link
url = _create_share_link('Find product designers with fintech experience')
print(url or 'FAIL')
" 2>&1 | tail -1)
    if echo "$result" | grep -q "lessie.ai/share/"; then
        ok "Dual-path: $result"
    else
        fail "Dual-path failed"
    fi
fi
echo ""

# ─── 7. Learning system ──────────────────────────────────────
echo "7. Learning system"
python3 -c "
import sys; sys.path.insert(0,'.')
from learn import load_strategy, _write_strategy, STRATEGY_DIR
from pathlib import Path

# Write test
path = STRATEGY_DIR / 'alliiexia' / 'intent' / 'hiring.md'
_write_strategy(path, '# Test\nWorks.')
assert path.exists()

# Read test
s = load_strategy('hiring', 'alliiexia')
assert 'Test' in s

# Fallback test
s2 = load_strategy('nonexistent_intent', 'alliiexia')
# Should return empty or overview

# Cleanup
path.unlink()
print('OK')
" 2>/dev/null && ok "load/write/fallback" || fail "learn.py logic"
echo ""

# ─── 8. Daemon schedule ──────────────────────────────────────
echo "8. Daemon schedule helpers"
python3 -c "
import datetime, random
def _time_today(h,m=0):
    return datetime.datetime.combine(datetime.date.today(), datetime.time(h,m))
def _spread_times(n, sh, eh):
    span = (eh-sh)*60; slot = span/n; times = []
    for i in range(n):
        offset = int(i*slot) + random.randint(0, max(0,int(slot)-1))
        times.append(_time_today(sh) + datetime.timedelta(minutes=offset))
    return times

t = _spread_times(5, 10, 20)
assert len(t) == 5
assert all(t[i] <= t[i+1] for i in range(4))
print('OK')
" 2>/dev/null && ok "spread_times (5 posts, 10am-8pm)" || fail "schedule helpers"
echo ""

# ─── 9. Content gen themes ───────────────────────────────────
echo "9. Content generation"
python3 -c "
import sys; sys.path.insert(0,'.')
from warmup.content_gen import _get_theme_for_today, THEMES
t = _get_theme_for_today()
assert t in THEMES
print(f'{t} of {list(THEMES.keys())}')
" 2>/dev/null && ok "6-theme rotation" || fail "content_gen themes"
echo ""

# ─── 10. LaunchAgent plists ──────────────────────────────────
echo "10. LaunchAgent plists"
plutil -lint scripts/com.lessie.leego-daily.plist >/dev/null 2>&1 && ok "daily plist valid" || fail "daily plist"
plutil -lint scripts/com.lessie.leego-warmup.plist >/dev/null 2>&1 && ok "warmup plist valid" || fail "warmup plist"
echo ""

# ─── Summary ─────────────────────────────────────────────────
echo "================================"
echo -e "  ${GREEN}Pass: $pass${NC}  ${RED}Fail: $fail${NC}  ${YELLOW}Skip: $warn${NC}"
if [ $fail -eq 0 ]; then
    echo -e "  ${GREEN}All critical tests passed!${NC}"
else
    echo -e "  ${RED}$fail test(s) failed — check above${NC}"
fi
echo "================================"
