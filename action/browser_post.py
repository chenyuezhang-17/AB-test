"""Browser-based tweet posting via CDP — bypasses Twitter API entirely.

Requires Chrome running with --remote-debugging-port=9222 and Twitter logged in.
Start Chrome with: open -a "Google Chrome" --args --remote-debugging-port=9222

Usage:
    from action.browser_post import post_reply_browser, post_tweet_browser
"""

from __future__ import annotations
import asyncio
import json
import sys
import time
from pathlib import Path

# Add browser module path
sys.path.insert(0, str(Path(__file__).parent))

CDP_URL = "http://localhost:9222"
SOCKET_PATH = "/tmp/social-browser.sock"


def _is_session_running() -> bool:
    import os
    pid_file = "/tmp/social-browser.pid"
    if not os.path.exists(pid_file):
        return False
    try:
        pid = int(Path(pid_file).read_text().strip())
        os.kill(pid, 0)
        return os.path.exists(SOCKET_PATH)
    except Exception:
        return False


async def _send(cmd: str, arg: str = "", timeout: int = 30) -> dict:
    reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)
    writer.write(json.dumps({"cmd": cmd, "arg": arg}).encode())
    writer.write_eof()
    await writer.drain()
    chunks = []
    while True:
        chunk = await asyncio.wait_for(reader.read(65536), timeout=timeout)
        if not chunk:
            break
        chunks.append(chunk)
    writer.close()
    return json.loads(b"".join(chunks).decode())


def bw(cmd: str, arg: str = "", timeout: int = 30) -> dict:
    return asyncio.run(_send(cmd, arg, timeout))


def ensure_session() -> bool:
    """Start browser session if not running."""
    if _is_session_running():
        return True
    import subprocess
    proc = subprocess.Popen(
        [sys.executable, "-m", "browser.session"],
        cwd=Path(__file__).parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(20):
        time.sleep(0.5)
        if _is_session_running():
            return True
    return False


def post_tweet_browser(text: str) -> tuple[bool, str]:
    """Post an original tweet via browser. Returns (success, url_or_error)."""
    if not ensure_session():
        return False, "browser session failed to start"

    bw("goto", "https://x.com/home", timeout=20)
    time.sleep(3)

    # Wait for compose box
    for _ in range(8):
        check = bw("eval", "document.querySelector('[data-testid=\"tweetTextarea_0\"][role=\"textbox\"]') ? 'ok' : 'no'")
        if check.get("value") == "ok":
            break
        time.sleep(1)

    # Focus
    focus = bw("eval", "(function(){const el=document.querySelector('[data-testid=\"tweetTextarea_0\"][role=\"textbox\"]'); el.click(); el.focus(); return document.activeElement===el ? 'ok' : 'failed';})()")
    if focus.get("value") != "ok":
        return False, f"focus failed: {focus.get('value')}"

    # Type text
    result = bw("type", text)
    if not result.get("ok"):
        return False, f"type failed: {result.get('error')}"

    time.sleep(1)

    # Click post button
    click = bw("eval", """(function(){
        const btn = document.querySelector('[data-testid="tweetButtonInline"]')
            || document.querySelector('[data-testid="tweetButton"]');
        if (!btn) return 'no button';
        if (btn.getAttribute('aria-disabled') === 'true') return 'disabled';
        btn.click(); return 'clicked';
    })()""")

    if click.get("value") != "clicked":
        return False, f"post click failed: {click.get('value')}"

    time.sleep(3)

    # Grab the URL of the tweet we just posted
    tweet_link = _get_latest_tweet_url()
    return True, tweet_link or "posted"


def _get_latest_reply_url(original_tweet_url: str) -> str | None:
    """Navigate to original tweet and find our most recent reply."""
    try:
        bw("goto", original_tweet_url, timeout=15)
        time.sleep(3)
        result = bw("eval", """(function(){
            const articles = document.querySelectorAll('article[data-testid="tweet"]');
            for (const a of articles) {
                const userEl = a.querySelector('[data-testid="User-Name"]');
                if (!userEl || !userEl.innerText.includes('alliiexia')) continue;
                const links = a.querySelectorAll('a[href*="/status/"]');
                for (const l of links) {
                    const m = l.href.match(/alliiexia\\/status\\/(\\d+)/);
                    if (m) return 'https://x.com/alliiexia/status/' + m[1];
                }
            }
            return null;
        })()""")
        return result.get("value") or None
    except Exception:
        return None


def _get_latest_tweet_url() -> str | None:
    """Navigate to profile and return URL of the most recent tweet."""
    try:
        bw("goto", "https://x.com/alliiexia", timeout=15)
        time.sleep(3)
        result = bw("eval", """(function(){
            const articles = document.querySelectorAll('article[data-testid="tweet"]');
            for (const a of articles) {
                const links = a.querySelectorAll('a[href*="/status/"]');
                for (const l of links) {
                    const m = l.href.match(/alliiexia\\/status\\/(\\d+)/);
                    if (m) return 'https://x.com/alliiexia/status/' + m[1];
                }
            }
            return null;
        })()""")
        return result.get("value") or None
    except Exception:
        return None


def post_reply_browser(tweet_url: str, text: str) -> tuple[bool, str]:
    """Post a reply to a specific tweet via browser. Returns (success, url_or_error)."""
    if not ensure_session():
        return False, "browser session failed to start"

    bw("goto", tweet_url, timeout=20)
    time.sleep(3)

    # Wait for reply textbox
    for _ in range(10):
        check = bw("eval", "document.querySelector('[data-testid=\"tweetTextarea_0\"][role=\"textbox\"]') ? 'ok' : 'no'")
        if check.get("value") == "ok":
            break
        time.sleep(2)

    # Focus reply box
    focus = bw("eval", "(function(){const el=document.querySelector('[data-testid=\"tweetTextarea_0\"][role=\"textbox\"]'); if(!el) return 'not found'; el.click(); el.focus(); return document.activeElement===el ? 'ok' : 'focused';})()")
    if focus.get("value") not in ("ok", "focused"):
        return False, f"reply focus failed: {focus.get('value')}"

    # Type reply text
    result = bw("type", text)
    if not result.get("ok"):
        return False, f"type failed: {result.get('error')}"

    time.sleep(1)

    # Click reply button
    click = bw("eval", """(function(){
        const btn = document.querySelector('[data-testid="tweetButtonInline"]')
            || document.querySelector('[data-testid="tweetButton"]');
        if (!btn) return 'no button';
        if (btn.getAttribute('aria-disabled') === 'true') return 'disabled';
        btn.click(); return 'clicked';
    })()""")

    if click.get("value") != "clicked":
        return False, f"reply click failed: {click.get('value')}"

    time.sleep(3)

    # Grab the URL of the reply we just posted (navigate to replies tab)
    tweet_link = _get_latest_reply_url(tweet_url)
    return True, tweet_link or "posted"
