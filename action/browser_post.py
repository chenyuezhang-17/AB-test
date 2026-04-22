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

import os as _os
_PORT = _os.environ.get("CHROME_PORT", "9222")
_ACCOUNT = _os.environ.get("TWITTER_ACCOUNT", "alliiexia")
CDP_URL = f"http://localhost:{_PORT}"
SOCKET_PATH = f"/tmp/leego-browser-{_PORT}.sock"


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


def _session_healthy() -> bool:
    """Check if session is running AND the WebSocket is alive (real ping)."""
    if not _is_session_running():
        return False
    try:
        r = asyncio.run(_send("ping", "", timeout=5))
        return r.get("ok", False)
    except Exception:
        return False


def _restart_session() -> bool:
    """Kill stale session files and start a fresh one."""
    import os, subprocess
    # Clean up stale socket/pid
    for f in [SOCKET_PATH, "/tmp/social-browser.pid"]:
        try: os.remove(f)
        except: pass
    # Kill any zombie session process
    import subprocess as _sp
    _sp.run(["pkill", "-f", "browser.session"], capture_output=True)
    time.sleep(1)
    proc = subprocess.Popen(
        [sys.executable, "-m", "browser.session"],
        cwd=Path(__file__).parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(20):
        time.sleep(0.5)
        if _session_healthy():
            return True
    return False


def ensure_session() -> bool:
    """Ensure session is running and healthy; restart if WebSocket is dead."""
    if _session_healthy():
        return True
    return _restart_session()


def post_tweet_browser(text: str) -> tuple[bool, str]:
    """Post an original tweet via browser. Returns (success, url_or_error)."""
    if not ensure_session():
        return False, "browser session failed to start"

    bw("goto", "https://x.com/home", timeout=20)
    time.sleep(3)

    # Click label to expand compose box, then wait for textarea
    bw("eval", """(function(){
        const label = document.querySelector('[data-testid="tweetTextarea_0_label"]');
        if (label) label.click();
    })()""")
    time.sleep(1.5)

    # Wait for compose box
    for _ in range(10):
        check = bw("eval", "document.querySelector('[data-testid=\"tweetTextarea_0\"][role=\"textbox\"]') ? 'ok' : 'no'")
        if check.get("value") == "ok":
            break
        time.sleep(1)

    # Focus compose box
    focus_s1 = bw("eval", """(function(){
        const el = document.querySelector('[data-testid="tweetTextarea_0"][role="textbox"]');
        if (!el) return 'not_found';
        el.click(); el.focus();
        return 'ok';
    })()""")
    if focus_s1.get("value") not in ("ok",):
        return False, f"focus failed: {focus_s1.get('value')}"

    # Type via CDP Input.insertText (not ClipboardEvent which Twitter intercepts)
    result = bw("type", text, timeout=60)
    if not result.get("ok"):
        insert = bw("eval", f"""(function(){{
            const el = document.querySelector('[data-testid="tweetTextarea_0"][role="textbox"]');
            if (!el) return 'not_found';
            el.focus();
            document.execCommand('insertText', false, {json.dumps(text)});
            return el.innerText.trim() ? 'ok' : 'empty';
        }})()""")
        if insert.get("value") != "ok":
            return False, f"text insert failed: {insert.get('value')}"

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
    """Find our most recent reply by checking our Tweets & Replies tab."""
    try:
        bw("goto", f"https://x.com/{_ACCOUNT}/with_replies", timeout=15)
        time.sleep(4)
        result = bw("eval", f"""(function(){{
            const articles = document.querySelectorAll('article[data-testid="tweet"]');
            for (const a of articles) {{
                const links = a.querySelectorAll('a[href*="/status/"]');
                for (const l of links) {{
                    const m = l.href.match(/{_ACCOUNT}\\/status\\/(\\d+)/);
                    if (m) return 'https://x.com/{_ACCOUNT}/status/' + m[1];
                }}
            }}
            return null;
        }})()""")
        return result.get("value") or None
    except Exception:
        return None


def _get_latest_tweet_url() -> str | None:
    """Navigate to profile and return URL of the most recent (non-pinned) tweet."""
    try:
        bw("goto", f"https://x.com/{_ACCOUNT}", timeout=15)
        time.sleep(3)
        result = bw("eval", f"""(function(){{
            const articles = document.querySelectorAll('article[data-testid="tweet"]');
            const candidates = [];
            for (const a of articles) {{
                const social = a.closest('[data-testid="cellInnerDiv"]');
                if (social && social.innerText.includes('Pinned')) continue;
                const timeEl = a.querySelector('time');
                const dt = timeEl ? timeEl.getAttribute('datetime') : '';
                const links = a.querySelectorAll('a[href*="/status/"]');
                for (const l of links) {{
                    const m = l.href.match(/{_ACCOUNT}\\/status\\/(\\d+)/);
                    if (m) {{ candidates.push({{url: l.href, dt: dt, id: parseInt(m[1])}}); break; }}
                }}
            }}
            if (!candidates.length) return null;
            candidates.sort((a, b) => b.id - a.id);
            return candidates[0].url;
        }})()""")
        return result.get("value") or None
    except Exception:
        return None


def post_quote_browser(tweet_url: str, text: str) -> tuple[bool, str]:
    """Quote-repost via browser using retweet→Quote flow.

    Key insight: insert text and click Post IMMEDIATELY in one JS call.
    Any sleep between insert and click gives React time to re-render and clear the text.
    """
    if not ensure_session():
        return False, "browser session failed to start"

    # Extract author and tweet ID from URL
    import re as _re
    m = _re.search(r'x\.com/([^/]+)/status/(\d+)', tweet_url)
    if not m:
        return False, f"invalid tweet url: {tweet_url}"
    author_handle, tweet_id = m.group(1), m.group(2)

    # Check tweet exists first
    bw("goto", tweet_url, timeout=20)
    time.sleep(2)
    page_check = bw("eval", """(function(){
        const body = document.body.innerText || '';
        if (body.includes("doesn't exist") || body.includes("This account")) return 'deleted';
        return 'ok';
    })()""")
    if page_check.get("value") == "deleted":
        return False, "tweet_deleted"

    # Use search page to find tweet as a card — avoids the inline-reply problem of detail page
    bw("goto", f"https://x.com/search?q=from%3A{author_handle}&src=typed_query&f=live", timeout=20)
    time.sleep(3)

    # Scroll to find the tweet card
    for _scroll in range(8):
        check_card = bw("eval", f"""(function(){{
            const articles = document.querySelectorAll('article[data-testid="tweet"]');
            for (const a of articles) {{
                if (a.querySelector('a[href*="/status/{tweet_id}"]')) return 'found';
            }}
            return 'not_found';
        }})()""")
        if check_card.get("value") == "found":
            break
        bw("eval", "window.scrollBy(0, 800)")
        time.sleep(1.5)

    # Click Retweet on the specific tweet card
    rt_click = bw("eval", f"""(function(){{
        const articles = document.querySelectorAll('article[data-testid="tweet"]');
        for (const a of articles) {{
            if (!a.querySelector('a[href*="/status/{tweet_id}"]')) continue;
            const btn = a.querySelector('[data-testid="retweet"]');
            if (btn) {{ btn.click(); return 'clicked'; }}
        }}
        return 'no retweet btn';
    }})()""")
    if rt_click.get("value") != "clicked":
        return False, f"retweet btn failed: {rt_click.get('value')}"

    time.sleep(1.5)

    # Click Quote from dropdown
    quote_click = bw("eval", """(function(){
        const items = document.querySelectorAll('[role="menuitem"]');
        for (const item of items) {
            if (item.innerText && item.innerText.toLowerCase().includes('quote')) {
                item.click(); return 'clicked';
            }
        }
        return 'no quote option';
    })()""")
    if quote_click.get("value") != "clicked":
        return False, f"quote option failed: {quote_click.get('value')}"

    time.sleep(2)

    # Wait for modal compose textarea (not inline reply box)
    for _ in range(10):
        check = bw("eval", "document.querySelector('[data-testid=\"tweetTextarea_0\"][role=\"textbox\"]') ? 'ok' : 'no'")
        if check.get("value") == "ok":
            break
        time.sleep(1)

    # Use CDP Input.insertText (character-by-character typing) instead of execCommand.
    # execCommand modifies DOM directly but React's reconciliation clears it.
    # CDP Input.insertText generates real keyboard events that React handles natively.
    # This is the same method post_tweet_browser uses (bw("type")) which works reliably.
    full_text = text
    copy_anchor = full_text[:30].replace("\n", " ").strip()

    # Focus the textarea first
    focus = bw("eval", """(function(){
        const el = document.querySelector('[data-testid="tweetTextarea_0"][role="textbox"]');
        if (!el) return 'not_found';
        el.click(); el.focus();
        return 'focused';
    })()""", timeout=10)
    if focus.get("value") != "focused":
        return False, f"could not focus quote textarea: {focus.get('value')}"
    time.sleep(0.5)

    # Type via CDP — slow but reliable (React processes each keystroke)
    bw("type", full_text, timeout=120)
    time.sleep(1)

    # Verify text survived React reconciliation
    verify = bw("eval", f"""(function(){{
        const el = document.querySelector('[data-testid="tweetTextarea_0"][role="textbox"]');
        if (!el) return 'no_el';
        const txt = el.innerText || '';
        return txt.includes({json.dumps(copy_anchor[:20])}) ? 'ok' : 'missing';
    }})()""", timeout=8)
    if verify.get("value") != "ok":
        # Fallback: try execCommand as last resort
        bw("eval", f"""(function(){{
            const el = document.querySelector('[data-testid="tweetTextarea_0"][role="textbox"]');
            if (!el) return;
            el.click(); el.focus();
            document.execCommand('selectAll');
            document.execCommand('insertText', false, {json.dumps(full_text)});
        }})()""", timeout=15)
        time.sleep(0.5)
        verify2 = bw("eval", f"""(function(){{
            const el = document.querySelector('[data-testid="tweetTextarea_0"][role="textbox"]');
            if (!el) return 'no_el';
            const txt = el.innerText || '';
            return txt.includes({json.dumps(copy_anchor[:20])}) ? 'ok' : 'missing';
        }})()""", timeout=8)
        if verify2.get("value") != "ok":
            return False, "text not in textarea after CDP type + execCommand fallback — NOT posting"

    # Click Post
    time.sleep(0.5)
    click = bw("eval", """(function(){
        const btn = document.querySelector('[data-testid="tweetButton"]')
            || document.querySelector('[data-testid="tweetButtonInline"]');
        if (!btn) return 'no_btn';
        if (btn.getAttribute('aria-disabled') === 'true') return 'btn_disabled';
        btn.click(); return 'clicked';
    })()""")

    val = click.get("value", "")
    if val == "btn_disabled":
        time.sleep(1.5)
        retry = bw("eval", """(function(){
            const btn = document.querySelector('[data-testid="tweetButton"]')
                || document.querySelector('[data-testid="tweetButtonInline"]');
            if (!btn) return 'no_btn';
            if (btn.getAttribute('aria-disabled') === 'true') return 'still_disabled';
            btn.click(); return 'clicked';
        })()""")
        if retry.get("value") not in ("clicked",):
            return False, f"post btn still disabled — NOT posting"
    elif val != "clicked":
        return False, f"post btn failed: {val}"

    time.sleep(3)
    tweet_link = _get_latest_tweet_url()
    return True, tweet_link or "posted"


# Keep old name as alias for compatibility
def post_reply_browser(tweet_url: str, text: str) -> tuple[bool, str]:
    return post_quote_browser(tweet_url, text)
