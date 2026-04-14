"""
Today's posting schedule — runs in background, one post per hour.
Plan: S2 → S1 → S2 → S1 → S2, then scrape engagement.
"""
import sys, time, sqlite3, datetime, requests, json
sys.path.insert(0, '/Users/lessie/cc/AB-test')

from dotenv import load_dotenv
load_dotenv('/Users/lessie/cc/AB-test/.env')

from action.browser_post import post_quote_browser, post_tweet_browser, ensure_session
from bridge.search import _create_share_link, _build_search_prompt
from db_log import log_action, scrape_engagement

INTERVAL = 3600  # 1 hour between posts

PLAN = [
    # (scene, type, id_or_tweetid, author)
    ("Scene 2: Intent", "s2", "2042281081357898101", "Remote_JobsNG"),
    ("Scene 1: Trends",  "s1", 7,                   ""),
    ("Scene 2: Intent", "s2", "2042491466510217536", "sshheekaarr1"),
    ("Scene 1: Trends",  "s1", 10,                  ""),
    ("Scene 2: Intent", "s2", "2041297399646405070", "JobFound5"),
]

DB = '/Users/lessie/cc/AB-test/activity.db'

def get_trend(trend_id):
    conn = sqlite3.connect(DB)
    r = conn.execute("SELECT topic, tweet_hook, search_prompt FROM trend_candidates WHERE id=?", (trend_id,)).fetchone()
    conn.close()
    return r

def mark_trend_posted(trend_id):
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE trend_candidates SET status='posted' WHERE id=?", (trend_id,))
    conn.commit()
    conn.close()

def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def safe_session():
    """Ensure session alive, restart if dead."""
    from action.browser_post import bw, _is_session_running
    import subprocess, pathlib
    if not _is_session_running():
        log("Session dead — restarting...")
        subprocess.Popen(
            [sys.executable, "-m", "browser.session"],
            cwd="/Users/lessie/cc/AB-test/action",
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        time.sleep(6)
    try:
        bw("eval", "1", timeout=5)
    except Exception:
        log("Session ping failed, forcing restart...")
        ensure_session()
        time.sleep(4)

def post_s1(trend_id):
    row = get_trend(trend_id)
    if not row:
        log(f"S1 trend {trend_id} not found")
        return
    topic, hook, search_prompt = row
    checkpoint = search_prompt or f"Find professionals relevant to: {topic}"
    log(f"S1 generating share link for trend #{trend_id}...")
    share_url = _create_share_link(checkpoint) or "https://lessie.ai"
    tweet_text = f"{hook}\n\n{share_url}"
    log(f"S1 posting: {tweet_text[:80]}...")
    ok, url = post_tweet_browser(tweet_text)
    if ok:
        log(f"S1 ✓ posted → {url}")
        log_action(reply_text=tweet_text, lessie_url=share_url, scene="Scene 1: Trends",
                   our_tweet_url=url if url.startswith("http") else "")
        mark_trend_posted(trend_id)
    else:
        log(f"S1 ✗ failed: {url}")


def post_s2(tweet_id, author):
    tweet_url = f"https://x.com/{author}/status/{tweet_id}"
    # Get original tweet text for better checkpoint
    conn = sqlite3.connect(DB)
    row = conn.execute("SELECT tweet_text FROM activity_log WHERE tweet_id=? LIMIT 1", (tweet_id,)).fetchone()
    conn.close()
    tweet_text = row[0] if row else ""
    checkpoint = _build_search_prompt(tweet_text, author) if tweet_text else f"{author} hiring"
    log(f"S2 checkpoint: {checkpoint[:100]}")
    log(f"S2 generating share link for @{author}...")
    share_url = _create_share_link(checkpoint) or "https://lessie.ai"
    reply = f"ran a search on this — here's a relevant talent pool that might help 👀\n\n{share_url}"
    log(f"S2 quote-reposting @{author}...")
    ok, url = post_quote_browser(tweet_url, reply)
    if ok:
        log(f"S2 ✓ posted → {url}")
        log_action(reply_text=reply, lessie_url=share_url, original_tweet_id=tweet_id,
                   author=author, scene="Scene 2: Intent",
                   our_tweet_url=url if url.startswith("http") else "")
    else:
        log(f"S2 ✗ failed: {url}")

if __name__ == "__main__":
    log("=== Today's schedule starting ===")
    log(f"Plan: {len(PLAN)} posts, 1 every {INTERVAL//60} min")
    ensure_session()

    for i, (scene, stype, target, author) in enumerate(PLAN):
        if i > 0:
            log(f"Waiting {INTERVAL//60} min until next post...")
            time.sleep(INTERVAL)

        log(f"--- Post {i+1}/{len(PLAN)}: {scene} ---")
        safe_session()
        if stype == "s1":
            post_s1(int(target))
        else:
            post_s2(target, author)

    log("=== All posts done. Scraping engagement... ===")
    try:
        scrape_engagement()
        log("Engagement data updated.")
    except Exception as e:
        log(f"Engagement scrape failed: {e}")

    log("=== Done for today ===")
