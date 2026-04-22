"""Browser actions for @Leegowlessie warmup — uses port 9223 + leegowlessie socket."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import os as _os
_PORT       = _os.environ.get("CHROME_PORT", "9223")
SOCKET_PATH = f"/tmp/leego-browser-{_PORT}.sock"
PID_FILE    = f"/tmp/leego-browser-{_PORT}.pid"
CDP_URL     = f"http://localhost:{_PORT}"
ACCOUNT     = _os.environ.get("TWITTER_ACCOUNT", "Leegowlessie")


# ─── session management ────────────────────────────────────────────────────

def _is_session_running() -> bool:
    import os
    if not Path(PID_FILE).exists():
        return False
    try:
        pid = int(Path(PID_FILE).read_text().strip())
        os.kill(pid, 0)
        return Path(SOCKET_PATH).exists()
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


def _dismiss_leave_dialog():
    """Dismiss Chrome/Twitter 'leave page?' dialog if present."""
    try:
        asyncio.run(_send("eval", """(function(){
            const dialogs = document.querySelectorAll('[role="alertdialog"],[role="dialog"]');
            for (const d of dialogs) {
                const btns = d.querySelectorAll('button');
                for (const b of btns) {
                    const t = (b.innerText || '').toLowerCase();
                    if (t.includes('leave') || t.includes('离开') || t.includes('discard')) {
                        b.click(); return 'dismissed';
                    }
                }
            }
            return 'none';
        })()""", timeout=5))
    except Exception:
        pass


def bw(cmd: str, arg: str = "", timeout: int = 30) -> dict:
    """Send command to browser session, auto-restart session on failure."""
    # Before navigating away, dismiss any leave-page dialog
    if cmd == "goto":
        _dismiss_leave_dialog()
    try:
        return asyncio.run(_send(cmd, arg, timeout))
    except Exception as e:
        # Session may have died — try to restart once
        if cmd in ("scroll_down", "eval", "goto"):
            try:
                if ensure_session():
                    return asyncio.run(_send(cmd, arg, timeout))
            except Exception:
                pass
        return {"ok": False, "error": str(e)}


def _session_healthy() -> bool:
    if not _is_session_running():
        return False
    try:
        r = asyncio.run(_send("ping", "", timeout=5))
        return r.get("ok", False)
    except Exception:
        return False


def ensure_session() -> bool:
    if _session_healthy():
        return True
    import os
    # Clean stale files
    for f in [SOCKET_PATH, PID_FILE]:
        try: os.remove(f)
        except: pass
    subprocess.run(["pkill", "-f", "warmup.session"], capture_output=True)
    time.sleep(1)
    proc = subprocess.Popen(
        [sys.executable, "-m", "warmup.session"],
        cwd=str(Path(__file__).parent.parent),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(20):
        time.sleep(0.5)
        if _session_healthy():
            return True
    return False


# ─── Twitter actions ───────────────────────────────────────────────────────

def follow_user(username: str) -> bool:
    """Follow a Twitter user by username. Returns True on success."""
    bw("goto", f"https://x.com/{username}", timeout=20)
    time.sleep(3)
    result = bw("eval", """(function(){
        const btns = [...document.querySelectorAll('[data-testid$="-follow"]')];
        for (const btn of btns) {
            const label = btn.getAttribute('aria-label') || btn.innerText || '';
            if (label.toLowerCase().includes('follow') && !label.toLowerCase().includes('following')) {
                btn.click(); return 'clicked';
            }
        }
        // Already following?
        const following = document.querySelector('[data-testid$="-unfollow"]');
        if (following) return 'already_following';
        return 'not_found';
    })()""")
    val = result.get("value", "")
    return val in ("clicked", "already_following")


def like_tweet(tweet_url: str) -> bool:
    """Navigate to a tweet and like it."""
    bw("goto", tweet_url, timeout=20)
    time.sleep(2)
    result = bw("eval", """(function(){
        const btn = document.querySelector('[data-testid="like"]');
        if (!btn) return 'not_found';
        const ariaLabel = btn.getAttribute('aria-label') || '';
        if (ariaLabel.toLowerCase().includes('liked')) return 'already_liked';
        btn.click(); return 'liked';
    })()""")
    return result.get("value") in ("liked", "already_liked")


def like_tweets_on_timeline(n: int = 5) -> int:
    """Like up to n tweets from the current page, one at a time with human-like delays."""
    import random
    liked = 0
    for scroll_round in range(4):
        if liked >= n:
            break
        # Find unliked buttons
        result = bw("eval", """(function(){
            const btns = document.querySelectorAll('[data-testid="like"]');
            let indices = [];
            for (let i = 0; i < btns.length; i++) {
                const label = btns[i].getAttribute('aria-label') || '';
                if (!label.toLowerCase().includes('liked')) indices.push(i);
            }
            return JSON.stringify(indices);
        })()""", timeout=20)
        indices = json.loads(result.get("value") or "[]") if result.get("value") else []
        for idx in indices:
            if liked >= n:
                break
            bw("eval", f"""(function(){{
                const btns = document.querySelectorAll('[data-testid="like"]');
                if (btns[{idx}]) btns[{idx}].click();
            }})()""", timeout=10)
            liked += 1
            time.sleep(random.uniform(8, 20))  # human-like gap between likes
        if liked >= n:
            break
        bw("eval", "window.scrollBy(0, 800)", timeout=10)
        time.sleep(random.uniform(3, 6))
    return liked


def reply_to_tweet(tweet_url: str, reply_text: str) -> bool:
    """Reply to a tweet with reply_text."""
    bw("goto", tweet_url, timeout=20)
    time.sleep(4)

    # Click the reply button on the first (main) tweet article
    click_reply = bw("eval", """(function(){
        // Get the main tweet's reply button — first article on the page
        const articles = document.querySelectorAll('article[data-testid="tweet"]');
        if (!articles.length) return 'no_article';
        const main = articles[0];
        const btn = main.querySelector('[data-testid="reply"]');
        if (!btn) return 'no_reply_btn';
        btn.click(); return 'clicked';
    })()""")
    if click_reply.get("value") != "clicked":
        return False
    time.sleep(2)

    # Wait for compose box
    for _ in range(8):
        check = bw("eval",
            "document.querySelector('[data-testid=\"tweetTextarea_0\"][role=\"textbox\"]') ? 'ok' : 'no'",
            timeout=10)
        if check.get("value") == "ok":
            break
        time.sleep(1)

    # Insert text using execCommand — most reliable for Twitter's React compose
    import json as _json
    insert = bw("eval", f"""(function(){{
        const boxes = document.querySelectorAll('[data-testid="tweetTextarea_0"][role="textbox"]');
        // Use the last box — on tweet detail page, last one is the reply compose
        const el = boxes[boxes.length - 1];
        if (!el) return 'not_found';
        el.focus();
        el.click();
        document.execCommand('selectAll');
        document.execCommand('insertText', false, {_json.dumps(reply_text)});
        return el.innerText.trim().length > 0 ? 'ok' : 'empty';
    }})()""", timeout=15)
    if insert.get("value") != "ok":
        return False
    time.sleep(1.5)

    # Click the Reply button (find button with text "Reply" that is not disabled)
    click = bw("eval", """(function(){
        const btns = document.querySelectorAll('button');
        for (const btn of btns) {
            if (btn.innerText.trim() === 'Reply' && btn.getAttribute('aria-disabled') !== 'true') {
                btn.click(); return 'clicked';
            }
        }
        return 'no_active_reply_btn';
    })()""")
    if click.get("value") != "clicked":
        return False

    # Wait for compose box to disappear (reply submitted)
    for _ in range(10):
        time.sleep(1)
        check = bw("eval", """(function(){
            const boxes = document.querySelectorAll('[data-testid="tweetTextarea_0"][role="textbox"]');
            const lastBox = boxes[boxes.length - 1];
            if (!lastBox || lastBox.innerText.trim() === '') return 'submitted';
            return 'still_composing';
        })()""", timeout=10)
        if check.get("value") == "submitted":
            time.sleep(1)
            return True

    return False


def retweet_tweet(tweet_url: str) -> bool:
    """Retweet (simple retweet, not quote) a tweet."""
    bw("goto", tweet_url, timeout=20)
    time.sleep(2)
    rt = bw("eval", """(function(){
        const btn = document.querySelector('[data-testid="retweet"]');
        if (!btn) return 'not_found';
        btn.click(); return 'clicked';
    })()""")
    if rt.get("value") != "clicked":
        return False
    time.sleep(1)
    confirm = bw("eval", """(function(){
        const items = document.querySelectorAll('[role="menuitem"]');
        for (const item of items) {
            if (item.innerText && item.innerText.toLowerCase().includes('repost')) {
                item.click(); return 'clicked';
            }
        }
        return 'not_found';
    })()""")
    return confirm.get("value") == "clicked"


def post_original_tweet(text: str) -> tuple[bool, str]:
    """Post an original tweet. Returns (success, tweet_url)."""
    bw("goto", "https://x.com/home", timeout=20)
    time.sleep(3)
    bw("eval", """(function(){
        const label = document.querySelector('[data-testid="tweetTextarea_0_label"]');
        if (label) label.click();
    })()""")
    time.sleep(1.5)
    for _ in range(10):
        check = bw("eval", "document.querySelector('[data-testid=\"tweetTextarea_0\"][role=\"textbox\"]') ? 'ok' : 'no'")
        if check.get("value") == "ok":
            break
        time.sleep(1)
    focus = bw("eval", """(function(){
        const el = document.querySelector('[data-testid="tweetTextarea_0"][role="textbox"]');
        if (!el) return 'not_found';
        el.click(); el.focus(); return 'ok';
    })()""")
    if focus.get("value") != "ok":
        return False, f"focus failed: {focus.get('value')}"
    bw("type", text, timeout=60)
    time.sleep(1)
    click = bw("eval", """(function(){
        const btn = document.querySelector('[data-testid="tweetButtonInline"]')
                 || document.querySelector('[data-testid="tweetButton"]');
        if (!btn) return 'no_button';
        if (btn.getAttribute('aria-disabled') === 'true') return 'disabled';
        btn.click(); return 'clicked';
    })()""")
    if click.get("value") != "clicked":
        return False, f"click failed: {click.get('value')}"
    time.sleep(3)
    url = _get_latest_tweet_url()
    return True, url or "posted"


def _get_latest_tweet_url() -> str | None:
    try:
        bw("goto", f"https://x.com/{ACCOUNT}", timeout=15)
        time.sleep(3)
        result = bw("eval", f"""(function(){{
            const articles = document.querySelectorAll('article[data-testid="tweet"]');
            for (const a of articles) {{
                const links = a.querySelectorAll('a[href*="/status/"]');
                for (const l of links) {{
                    const m = l.href.match(/{ACCOUNT}\\/status\\/(\\d+)/i);
                    if (m) return 'https://x.com/{ACCOUNT}/status/' + m[1];
                }}
            }}
            return null;
        }})()""")
        return result.get("value") or None
    except Exception:
        return None


def search_users(query: str, limit: int = 20) -> list[str]:
    """Search for user accounts matching query, return list of NA tech usernames."""
    import urllib.parse
    # Append lang:en to restrict to English accounts
    q = query if "lang:en" in query else f"{query} lang:en"
    encoded = urllib.parse.quote(q)
    bw("goto", f"https://x.com/search?q={encoded}&src=typed_query&f=user", timeout=20)
    time.sleep(3)
    usernames = []
    for _ in range(3):
        result = bw("eval", """(function(){
            const cells = document.querySelectorAll('[data-testid="UserCell"]');
            const names = [];
            cells.forEach(function(cell) {
                const links = cell.querySelectorAll('a[href^="/"]');
                for (const link of links) {
                    const m = link.href.match(/x\\.com\\/([^/?]+)$/);
                    if (m && m[1] && !['explore','home','notifications','messages','i'].includes(m[1])) {
                        names.push(m[1]);
                        break;
                    }
                }
            });
            return names;
        })()""")
        new = result.get("value") or []
        for u in new:
            if u not in usernames:
                usernames.append(u)
        if len(usernames) >= limit:
            break
        try:
            bw("scroll_down", "800", timeout=10)
        except Exception:
            pass
        time.sleep(2)
    return usernames[:limit]


TECH_BIO_KEYWORDS = [
    "engineer", "founder", "developer", "researcher", "startup",
    "ai", "ml", "llm", "product", "designer", "vp", "cto", "ceo",
    "building", "software", "data", "vc", "investor", "hacker",
    "open to work", "job", "hiring", "tech",
]

NA_LOCATIONS = [
    "us", "usa", "united states", "canada", "sf", "san francisco",
    "new york", "nyc", "seattle", "austin", "boston", "chicago",
    "los angeles", "la", "toronto", "vancouver", "bay area",
    "silicon valley", "washington", "denver", "miami",
]


def _is_na_tech_account(cell_text: str) -> bool:
    """Return True if cell text contains NA location + tech keywords."""
    t = cell_text.lower()
    has_tech = any(k in t for k in TECH_BIO_KEYWORDS)
    has_na   = any(loc in t for loc in NA_LOCATIONS)
    return has_tech and has_na


def get_who_to_follow(limit: int = 15) -> list[str]:
    """Mine followers from seed accounts — North America + tech bio only."""
    import random as _random
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent.parent))
    from warmup.warmup_auto import SEED_ACCOUNTS

    seed = _random.choice(SEED_ACCOUNTS)
    bw("goto", f"https://x.com/{seed}/followers", timeout=20)
    time.sleep(3)
    tech_kw_js = json.dumps(TECH_BIO_KEYWORDS)
    na_loc_js  = json.dumps(NA_LOCATIONS)
    result = bw("eval", f"""(function(){{
        const techKw = {tech_kw_js};
        const naLoc  = {na_loc_js};
        const cells  = document.querySelectorAll('[data-testid="UserCell"]');
        const out = [];
        cells.forEach(function(cell) {{
            const txt = cell.innerText.toLowerCase();
            const hasTech = techKw.some(function(k){{ return txt.includes(k); }});
            const hasNA   = naLoc.some(function(l){{ return txt.includes(l); }});
            if (!hasTech || !hasNA) return;
            const links = cell.querySelectorAll('a[href^="/"]');
            const skip = ['explore','home','notifications','messages','i','settings','search'];
            for (const link of links) {{
                const m = link.href.match(/x\\.com\\/([^/?#]+)$/);
                if (m && m[1] && !skip.includes(m[1])) {{
                    out.push(m[1]); break;
                }}
            }}
        }});
        return out;
    }})()""")
    return (result.get("value") or [])[:limit]


def read_full_tweet(tweet_url: str) -> str:
    """Navigate to a tweet page and return its full text."""
    bw("goto", tweet_url, timeout=20)
    time.sleep(3)
    result = bw("eval", """(function(){
        const articles = document.querySelectorAll('article[data-testid="tweet"]');
        if (!articles.length) return '';
        const textEl = articles[0].querySelector('[data-testid="tweetText"]');
        return textEl ? textEl.innerText.trim() : '';
    })()""", timeout=10)
    return (result.get("value") or "").strip()


def search_and_like(query: str, n: int = 10) -> int:
    """Search for tweets and like up to n of them."""
    import urllib.parse
    encoded = urllib.parse.quote(query)
    bw("goto", f"https://x.com/search?q={encoded}&src=typed_query&f=live", timeout=20)
    time.sleep(3)
    return like_tweets_on_timeline(n)
