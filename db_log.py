"""Helper to log pipeline activity to activity.db."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "activity.db"


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS trend_candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scanned_at TEXT NOT NULL,
        topic TEXT NOT NULL,
        tweet_hook TEXT,
        search_prompt TEXT,
        source_url TEXT,
        status TEXT DEFAULT 'pending'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL, stage TEXT NOT NULL,
        tweet_id TEXT, author TEXT, tweet_text TEXT,
        intent TEXT, confidence REAL, lessie_url TEXT,
        status TEXT, detail TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS posted_tweets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        posted_at TEXT NOT NULL, our_tweet_id TEXT UNIQUE,
        original_tweet_id TEXT, reply_text TEXT, lessie_url TEXT,
        scene TEXT,
        views INTEGER DEFAULT 0, retweets INTEGER DEFAULT 0,
        likes INTEGER DEFAULT 0, replies INTEGER DEFAULT 0,
        last_synced TEXT
    )""")
    c.commit()
    return c


def save_trend_candidates(trends: list) -> int:
    """Save scanned trend candidates to DB. Returns count saved."""
    now = datetime.now(timezone.utc).isoformat()
    c = _conn()
    saved = 0
    for t in trends:
        topic = t.get("topic", "")
        if not topic:
            continue
        # Skip duplicates from today
        today = now[:10]
        exists = c.execute(
            "SELECT 1 FROM trend_candidates WHERE topic=? AND scanned_at LIKE ?",
            (topic, f"{today}%")
        ).fetchone()
        if exists:
            continue
        c.execute(
            "INSERT INTO trend_candidates (scanned_at, topic, tweet_hook, search_prompt, source_url) VALUES (?,?,?,?,?)",
            (now, topic, t.get("tweet_hook", ""), t.get("search_prompt", ""), t.get("source_url", ""))
        )
        saved += 1
    c.commit()
    c.close()
    return saved


def get_trend_candidates(days: int = 3) -> list:
    """Get recent trend candidates."""
    c = _conn()
    cur = c.execute(
        "SELECT * FROM trend_candidates ORDER BY scanned_at DESC LIMIT 20"
    )
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    c.close()
    return [dict(zip(cols, r)) for r in rows]


def log_action(reply_text: str, lessie_url: str, original_tweet_id: str = "",
               author: str = "", scene: str = "", our_tweet_url: str = ""):
    now = datetime.now(timezone.utc).isoformat()
    c = _conn()
    c.execute(
        "INSERT INTO activity_log (ts, stage, tweet_id, author, tweet_text, lessie_url, status, detail) VALUES (?,?,?,?,?,?,?,?)",
        (now, "action", original_tweet_id, author, reply_text, lessie_url, "posted", scene)
    )
    c.execute(
        "INSERT OR IGNORE INTO posted_tweets (posted_at, original_tweet_id, reply_text, lessie_url, scene, our_tweet_url) VALUES (?,?,?,?,?,?)",
        (now, original_tweet_id, reply_text, lessie_url, scene, our_tweet_url)
    )
    c.commit()
    c.close()
    print(f"[db] logged {scene or 'post'} to activity.db")


def scrape_engagement():
    """Scrape likes/retweets/views for our posted tweets.

    Strategy: navigate to @alliiexia/with_replies (our profile timeline),
    then read engagement for each visible tweet by tweet-ID match.
    This avoids the quote-tweet embedding problem where visiting an individual
    quote-tweet page causes the quoted original's action bar to be read instead
    of our tweet's action bar.
    """
    import sys as _sys, time as _time
    _sys.path.insert(0, str(Path(__file__).parent / "action"))
    try:
        from browser_post import bw, ensure_session
    except ImportError:
        print("[db] scrape_engagement: cannot import browser_post, skipping")
        return

    if not ensure_session():
        print("[db] scrape_engagement: browser session unavailable")
        return

    c = _conn()
    rows = c.execute(
        "SELECT id, our_tweet_url FROM posted_tweets WHERE our_tweet_url IS NOT NULL AND our_tweet_url != ''"
    ).fetchall()
    c.close()
    if not rows:
        return

    # Build set of tweet IDs we need
    # url format: https://x.com/alliiexia/status/TWEET_ID
    id_to_row = {}
    for row_id, url in rows:
        tid = url.rstrip('/').split('/')[-1]
        id_to_row[tid] = (row_id, url)

    def parse_num(s):
        if not s: return 0
        s = str(s).replace(',', '').strip()
        if s.endswith('K') or s.endswith('k'): return int(float(s[:-1]) * 1000)
        if s.endswith('M') or s.endswith('m'): return int(float(s[:-1]) * 1_000_000)
        try: return int(s)
        except: return 0

    # JS to scrape all visible tweets from the timeline at once.
    # Each article in the timeline shows ONE tweet (our tweet) — no embedded quotes
    # in the action bar, because timeline cards don't expand the quoted tweet's buttons.
    PROFILE_SCRAPE_JS = """(function(){
        function parseAria(str) {
            if (!str) return '';
            var m = str.match(/^([\d,]+(?:\\.\\d+)?[KkMm]?)/);
            return m ? m[1] : '';
        }
        var results = {};
        var articles = document.querySelectorAll('article[data-testid="tweet"]');
        articles.forEach(function(art) {
            // Get tweet ID from the permalink link inside the article
            var link = art.querySelector('a[href*="/status/"]');
            if (!link) return;
            var m = link.href.match(/\\/status\\/(\\d+)/);
            if (!m) return;
            var tid = m[1];

            var bar = art.querySelector('[role="group"]');
            if (!bar) return;

            var groupLabel = bar.getAttribute('aria-label') || '';
            var viewsMatch = groupLabel.match(/([\\d,]+(?:\\.\\d+)?[KkMm]?)\\s+view/i);
            var likeBtn = bar.querySelector('[data-testid="like"]');
            var rtBtn   = bar.querySelector('[data-testid="retweet"]');

            results[tid] = {
                likes:    likeBtn ? parseAria(likeBtn.getAttribute('aria-label')) : '',
                retweets: rtBtn   ? parseAria(rtBtn.getAttribute('aria-label'))   : '',
                views:    viewsMatch ? viewsMatch[1] : ''
            };
        });
        return JSON.stringify(results);
    })()"""

    now = datetime.now(timezone.utc).isoformat()
    db = _conn()

    try:
        # Navigate to profile with_replies tab — shows all our posts
        bw("goto", "https://x.com/alliiexia/with_replies", timeout=20)
        _time.sleep(5)

        # Scroll to load more tweets (up to 3 passes)
        found = {}
        for scroll_pass in range(4):
            result = bw("eval", PROFILE_SCRAPE_JS)
            raw = result.get("value", "{}")
            batch = json.loads(raw) if raw else {}
            found.update(batch)

            # Check if we have all the IDs we need
            if all(tid in found for tid in id_to_row):
                break

            # Scroll down to load more
            bw("eval", "window.scrollBy(0, 2000)")
            _time.sleep(3)

        # Write results to DB
        for tid, (row_id, url) in id_to_row.items():
            m = found.get(tid)
            if not m:
                print(f"[db] engagement not found in timeline for {url}")
                continue
            db.execute(
                "UPDATE posted_tweets SET views=?, retweets=?, likes=?, last_synced=? WHERE id=?",
                (parse_num(m.get("views")), parse_num(m.get("retweets")), parse_num(m.get("likes")), now, row_id)
            )
            print(f"[db] engagement synced {url}: likes={m.get('likes')} rt={m.get('retweets')} views={m.get('views')}")

        db.commit()
    except Exception as e:
        print(f"[db] scrape_engagement failed: {e}")
    finally:
        db.close()
