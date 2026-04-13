"""Helper to log pipeline activity to activity.db."""
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
    """Scrape likes/retweets/views for our posted tweets via browser CDP."""
    import asyncio, json, sys
    sys.path.insert(0, "/tmp/2026040801")

    async def _scrape(tweet_url: str) -> dict:
        from browser.session import BrowserController  # type: ignore
        pass

    c = _conn()
    rows = c.execute("SELECT id, our_tweet_url FROM posted_tweets WHERE our_tweet_url IS NOT NULL AND our_tweet_url != ''").fetchall()
    c.close()
    if not rows:
        return

    try:
        import httpx, websockets

        async def get_metrics(tweet_url: str) -> dict:
            # Use CDP to navigate and scrape
            targets = httpx.get("http://localhost:9222/json").json()
            if not targets:
                return {}
            ws_url = targets[0]["webSocketDebuggerUrl"]
            async with websockets.connect(ws_url, max_size=10_000_000) as ws:
                msg_id = [0]

                async def send(method, params=None):
                    msg_id[0] += 1
                    await ws.send(json.dumps({"id": msg_id[0], "method": method, "params": params or {}}))
                    while True:
                        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                        if resp.get("id") == msg_id[0]:
                            return resp.get("result", {})

                await send("Page.navigate", {"url": tweet_url})
                await asyncio.sleep(4)
                result = await send("Runtime.evaluate", {"expression": """(function(){
                    const getText = sel => { const el = document.querySelector(sel); return el ? el.innerText.trim() : '0'; };
                    return JSON.stringify({
                        likes: getText('[data-testid="like"] span[data-testid="app-text-transition-container"]'),
                        retweets: getText('[data-testid="retweet"] span[data-testid="app-text-transition-container"]'),
                        views: getText('[data-testid="tweet"] a[href*="/analytics"] span') || getText('[aria-label*="view"]')
                    });
                })()""", "returnByValue": True})
                val = result.get("result", {}).get("value", "{}")
                return json.loads(val) if val else {}

        now = datetime.now(timezone.utc).isoformat()
        db = _conn()
        for row_id, url in rows:
            try:
                m = asyncio.run(get_metrics(url))
                def parse_num(s):
                    if not s: return 0
                    s = str(s).replace(',', '').strip()
                    if s.endswith('K'): return int(float(s[:-1]) * 1000)
                    if s.endswith('M'): return int(float(s[:-1]) * 1_000_000)
                    try: return int(s)
                    except: return 0
                db.execute(
                    "UPDATE posted_tweets SET views=?, retweets=?, likes=?, last_synced=? WHERE id=?",
                    (parse_num(m.get("views")), parse_num(m.get("retweets")), parse_num(m.get("likes")), now, row_id)
                )
                print(f"[db] engagement synced for {url}: {m}")
            except Exception as e:
                print(f"[db] engagement scrape failed for {url}: {e}")
        db.commit()
        db.close()
    except Exception as e:
        print(f"[db] scrape_engagement failed: {e}")
