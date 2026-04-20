"""
@Leegowlessie 养号自动系统 (Daemon Mode)
每天 10:00 启动，全天分散执行：
1. 关注目标受众账号（多圈层混合）
2. 点赞目标推文（tech + growth + creator + lifestyle）
3. 回复有价值的评论
4. 转发优质内容
5. 发原创推文（6主题轮换）
"""

import sys, os, time, json, sqlite3, datetime, random
sys.path.insert(0, '/Users/lessie/cc/AB-test')

from dotenv import load_dotenv
load_dotenv('/Users/lessie/cc/AB-test/.env')

from warmup.browser import (
    ensure_session, bw, follow_user, like_tweets_on_timeline,
    reply_to_tweet, retweet_tweet, post_original_tweet,
    search_users, get_who_to_follow, search_and_like, read_full_tweet
)
from warmup.content_gen import generate_tweet, get_reply_for_tweet

DB  = '/Users/lessie/cc/AB-test/activity.db'
LOG = '/tmp/leegowlessie_warmup.log'

# ─── Multi-category seed accounts ─────────────────────────────────────────
SEED_ACCOUNTS = [
    # Tech/AI
    "sama", "karpathy", "swyx", "levelsio", "emollick",
    # Growth/Marketing
    "randfish", "dharmesh", "lennysan", "Julian", "agazdecki",
    # Creator/Lifestyle
    "sahilbloom", "dickiebush", "aliabdaal", "jasonfried", "danmartell",
    # Hiring/Careers
    "hunterwalk", "garrytan", "naval", "shreyas", "shl",
]

# ─── Broad search queries (NA filter applied post-fetch) ──────────────────
LIKE_QUERIES = [
    "hiring AI engineer 2026 lang:en",
    "open to work software engineer lang:en",
    "AI startup building team lang:en",
    "machine learning engineer hiring lang:en",
    "growth marketing strategy 2026 lang:en",
    "PLG product led growth lang:en",
    "B2B SaaS marketing lang:en",
    "content marketing strategy lang:en",
    "building in public founder lang:en",
    "newsletter growth strategy lang:en",
    "creator economy tools lang:en",
    "remote work productivity lang:en",
]

REPLY_QUERIES = [
    "looking for cofounder technical lang:en",
    "open to work senior engineer lang:en",
    "AI startup hiring engineers lang:en",
    "growth marketing tips lang:en",
    "SaaS founder advice lang:en",
    "building in public update lang:en",
    "newsletter milestone lang:en",
]

# ─── Non-NA signals — skip accounts/tweets with these in bio/location ─────
NON_NA_BIO_SIGNALS = [
    # South/Southeast Asia
    "india", "bangalore", "bengaluru", "mumbai", "delhi", "hyderabad", "chennai",
    "pune", "kolkata", "pakistan", "sri lanka", "nepal", "bangladesh",
    "singapore", "malaysia", "indonesia", "philippines", "vietnam", "thailand",
    "myanmar", "cambodia", "laos",
    # East Asia
    "china", "beijing", "shanghai", "shenzhen", "guangzhou",
    "japan", "tokyo", "osaka", "korea", "seoul", "taiwan", "taipei",
    "hong kong", "hongkong",
    # Europe
    "uk", "london", "manchester", "united kingdom", "england", "scotland",
    "germany", "berlin", "munich", "france", "paris", "spain", "madrid",
    "italy", "rome", "milan", "netherlands", "amsterdam", "sweden", "stockholm",
    "norway", "denmark", "finland", "switzerland", "zurich", "poland", "warsaw",
    "portugal", "lisbon", "belgium", "brussels", "austria", "vienna",
    # Middle East & Africa
    "dubai", "uae", "abu dhabi", "saudi", "riyadh", "israel", "tel aviv",
    "egypt", "cairo", "nigeria", "lagos", "kenya", "nairobi", "south africa",
    "johannesburg", "cape town", "ghana", "accra",
    # Latin America
    "brazil", "são paulo", "sao paulo", "rio de janeiro", "brasil",
    "mexico", "ciudad de mexico", "argentina", "buenos aires", "colombia",
    "bogota", "chile", "santiago", "peru", "lima",
    # Australia/NZ (not NA)
    "australia", "sydney", "melbourne", "brisbane", "new zealand", "auckland",
]


def _is_non_na(location: str, bio: str) -> bool:
    """Return True if location or bio strongly suggests non-North-America."""
    text = (location + " " + bio).lower()
    return any(sig in text for sig in NON_NA_BIO_SIGNALS)

# ─── Daily limits ──────────────────────────────────────────────────────────
DAILY_FOLLOWS  = 1
DAILY_LIKES    = 25
DAILY_REPLIES  = 4
DAILY_RETWEETS = 2
DAILY_POSTS    = 3


# ─── Logging ───────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, 'a') as f:
        f.write(line + '\n')


# ─── DB helpers ────────────────────────────────────────────────────────────

def _init_db():
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS warmup_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            action TEXT,       -- 'follow','like','reply','retweet','post'
            target TEXT,       -- username or tweet url
            detail TEXT,
            ts TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


def _log_action(action: str, target: str, detail: str = ""):
    conn = sqlite3.connect(DB)
    conn.execute(
        "INSERT INTO warmup_log (date, action, target, detail) VALUES (?,?,?,?)",
        (datetime.date.today().isoformat(), action, target, detail)
    )
    conn.commit(); conn.close()


def _today_count(action: str) -> int:
    today = datetime.date.today().isoformat()
    conn = sqlite3.connect(DB)
    n = conn.execute(
        "SELECT COUNT(*) FROM warmup_log WHERE date=? AND action=?", (today, action)
    ).fetchone()[0]
    conn.close()
    return n


def _already_followed(username: str) -> bool:
    conn = sqlite3.connect(DB)
    n = conn.execute(
        "SELECT COUNT(*) FROM warmup_log WHERE action='follow' AND target=?", (username,)
    ).fetchone()[0]
    conn.close()
    return n > 0


# ─── Task runners ──────────────────────────────────────────────────────────

def _get_user_location_bio(username: str) -> tuple[str, str]:
    """Navigate to user profile and extract location + bio text."""
    try:
        bw("goto", f"https://x.com/{username}", timeout=15)
        time.sleep(2)
        result = bw("eval", """(function(){
            const loc = document.querySelector('[data-testid="UserLocation"]');
            const bio = document.querySelector('[data-testid="UserDescription"]');
            return {
                location: loc ? loc.innerText.trim() : '',
                bio: bio ? bio.innerText.trim() : ''
            };
        })()""", timeout=8)
        data = result.get("value") or {}
        if isinstance(data, dict):
            return data.get("location", ""), data.get("bio", "")
    except Exception:
        pass
    return "", ""


def run_follows():
    done = _today_count("follow")
    if done >= DAILY_FOLLOWS:
        log(f"Follows: already at limit ({done}), skipping")
        return
    needed = DAILY_FOLLOWS - done
    log(f"Follows: need {needed} more (done {done}/{DAILY_FOLLOWS})")

    # Mix: Twitter's "Who to follow" + user search results (North America only)
    queries = [
        "AI engineer startup USA",
        "machine learning engineer San Francisco",
        "tech founder building US",
        "software engineer New York remote",
        "YC founder hiring",
    ]
    candidates = get_who_to_follow(limit=20)
    q = random.choice(queries)
    log(f"  Searching users: '{q}'...")
    candidates += search_users(q, limit=20)
    # deduplicate
    seen = set(); candidates = [u for u in candidates if not (u in seen or seen.add(u))]
    random.shuffle(candidates)

    followed = 0
    for username in candidates:
        if followed >= needed:
            break
        if _already_followed(username):
            continue
        # Check profile location/bio before following
        loc, bio = _get_user_location_bio(username)
        if _is_non_na(loc, bio):
            log(f"  [skip] @{username} — non-NA location: '{loc}'")
            continue
        log(f"  Following @{username} (location: '{loc or 'unknown'}')...")
        ok = follow_user(username)
        if ok:
            _log_action("follow", username)
            followed += 1
            time.sleep(random.uniform(4, 8))  # human-like delay
        else:
            log(f"  ✗ couldn't follow @{username}")
        time.sleep(2)
    log(f"Follows: done {followed} new follows")


def run_likes():
    done = _today_count("like")
    if done >= DAILY_LIKES:
        log(f"Likes: already at limit ({done}), skipping")
        return
    needed = DAILY_LIKES - done
    log(f"Likes: need {needed} more (done {done}/{DAILY_LIKES})")

    liked_total = 0
    queries = random.sample(LIKE_QUERIES, min(3, len(LIKE_QUERIES)))
    per_query = max(1, needed // len(queries) + 1)

    for query in queries:
        if liked_total >= needed:
            break
        log(f"  Liking tweets for: '{query}'")
        n = search_and_like(query, n=per_query)
        if n > 0:
            _log_action("like", query, f"liked {n}")
            liked_total += n
            log(f"  ✓ liked {n} tweets")
        time.sleep(random.uniform(5, 10))

    log(f"Likes: done ~{liked_total} likes total today")


def _collect_reply_candidates(n: int = 15) -> list[dict]:
    """Collect tweet candidates from home timeline + search, verify they load."""
    candidates = []

    # 1. Home timeline — most reliable (tweets are fresh and valid)
    bw("goto", "https://x.com/home", timeout=20)
    time.sleep(3)
    bw("eval", "window.scrollBy(0, 400)", timeout=10)
    time.sleep(2)
    result = bw("eval", """(function(){
        const articles = document.querySelectorAll('article[data-testid="tweet"]');
        const out = [];
        articles.forEach(function(a) {
            const links = a.querySelectorAll('a[href*="/status/"]');
            const textEl = a.querySelector('[data-testid="tweetText"]');
            const userEl = a.querySelector('[data-testid="User-Name"] a');
            let username = '';
            if (userEl) {
                const m = userEl.href.match(/x\\.com\\/([^/]+)/);
                if (m) username = m[1];
            }
            for (const l of links) {
                const m = l.href.match(/x\\.com\\/[^/]+\\/status\\/(\\d+)/);
                if (m && username && username !== 'Leegowlessie') {
                    out.push({url: l.href, text: textEl ? textEl.innerText.slice(0,200) : '', author: username});
                    break;
                }
            }
        });
        return out;
    })()""")
    candidates += result.get("value") or []

    # 2. One search query as supplement
    import urllib.parse
    query = random.choice(REPLY_QUERIES)
    encoded = urllib.parse.quote(query)
    bw("goto", f"https://x.com/search?q={encoded}&src=typed_query&f=live", timeout=20)
    time.sleep(3)
    result2 = bw("eval", """(function(){
        const articles = document.querySelectorAll('article[data-testid="tweet"]');
        const out = [];
        articles.forEach(function(a) {
            const links = a.querySelectorAll('a[href*="/status/"]');
            const textEl = a.querySelector('[data-testid="tweetText"]');
            const userEl = a.querySelector('[data-testid="User-Name"] a');
            let username = '';
            if (userEl) {
                const m = userEl.href.match(/x\\.com\\/([^/]+)/);
                if (m) username = m[1];
            }
            for (const l of links) {
                const m = l.href.match(/x\\.com\\/[^/]+\\/status\\/(\\d+)/);
                if (m && username && username !== 'Leegowlessie') {
                    out.push({url: l.href, text: textEl ? textEl.innerText.slice(0,200) : '', author: username});
                    break;
                }
            }
        });
        return out;
    })()""")
    candidates += result2.get("value") or []

    # Deduplicate by URL + filter non-NA by tweet text signals
    seen = set()
    deduped = []
    for c in candidates:
        if not c.get("url") or c["url"] in seen or not c.get("text"):
            continue
        seen.add(c["url"])
        # Quick non-NA text check (bio location not fetched here for speed)
        tweet_text = c.get("text", "").lower()
        if _is_non_na("", tweet_text):
            continue
        deduped.append(c)

    return deduped[:n]


def run_replies():
    done = _today_count("reply")
    if done >= DAILY_REPLIES:
        log(f"Replies: already at limit ({done}), skipping")
        return
    needed = DAILY_REPLIES - done
    log(f"Replies: need {needed} more")

    tweets = _collect_reply_candidates(n=15)
    log(f"  Found {len(tweets)} reply candidates")

    replied = 0
    for tweet in tweets:
        if replied >= needed:
            break
        url    = tweet.get("url", "")
        text   = tweet.get("text", "")
        author = tweet.get("author", "")
        if not url or not text:
            continue

        # Navigate to tweet page and read full text
        full_text = read_full_tweet(url)
        if not full_text or len(full_text) < 15:
            log(f"  ✗ @{author} tweet not accessible or empty, skipping")
            continue

        # Check reply button exists
        check = bw("eval", "document.querySelector('[data-testid=\"reply\"]') ? 'ok' : 'no'", timeout=8)
        if check.get("value") != "ok":
            log(f"  ✗ @{author} no reply button, skipping")
            continue

        log(f"  Generating reply for @{author}: '{full_text[:80]}'...")
        reply = get_reply_for_tweet(full_text, author)
        if not reply:
            log("  ✗ reply generation failed, skipping")
            continue
        log(f"  Reply: '{reply[:90]}'")

        # Already on tweet page from read_full_tweet — pass url for fallback nav
        ok = reply_to_tweet(url, reply)
        if ok:
            _log_action("reply", url, reply[:100])
            replied += 1
            log(f"  ✓ replied to @{author}")
        else:
            log(f"  ✗ reply click failed for @{author}")
        time.sleep(random.uniform(8, 15))

    log(f"Replies: done {replied} replies")


# Big accounts — retweet risk (high follower count = spam signal). Like/reply OK.
RETWEET_BLOCKED_ACCOUNTS = {
    "elonmusk", "realdonaldtrump", "cz_binance", "sama", "naval", "paulg",
    "karpathy", "garrytan", "ycombinator", "openai", "google", "microsoft",
    "spacex", "tesla", "meta", "amazon", "apple", "netflix",
}

def run_retweets():
    done = _today_count("retweet")
    if done >= DAILY_RETWEETS:
        log(f"Retweets: already at limit ({done}), skipping")
        return
    needed = DAILY_RETWEETS - done
    log(f"Retweets: need {needed} more")

    # Browse home timeline for RT candidates
    bw("goto", "https://x.com/home", timeout=20)
    time.sleep(3)
    bw("eval", "window.scrollBy(0, 600)", timeout=10)
    time.sleep(2)

    result = bw("eval", """(function(){
        const articles = document.querySelectorAll('article[data-testid="tweet"]');
        const out = [];
        articles.forEach(function(a) {
            const links = a.querySelectorAll('a[href*="/status/"]');
            const userEl = a.querySelector('[data-testid="User-Name"] a');
            let username = '';
            if (userEl) {
                const m = userEl.href.match(/x\\.com\\/([^/]+)/);
                if (m) username = m[1];
            }
            for (const l of links) {
                const m = l.href.match(/x\\.com\\/[^/]+\\/status\\/(\\d+)/);
                if (m && username && username !== 'Leegowlessie') {
                    out.push({ url: l.href, author: username });
                    break;
                }
            }
        });
        return out.slice(0, 15);
    })()""")

    tweets = result.get("value") or []
    retweeted = 0
    for tweet in random.sample(tweets, min(needed * 3, len(tweets))):
        if retweeted >= needed:
            break
        url = tweet.get("url", "")
        author = tweet.get("author", "")
        if not url:
            continue
        if author.lower() in RETWEET_BLOCKED_ACCOUNTS:
            log(f"  [rt skip] @{author} — big account, skip retweet (like/reply OK)")
            continue
        log(f"  Retweeting @{author}: {url}")
        ok = retweet_tweet(url)
        if ok:
            _log_action("retweet", url, f"@{author}")
            retweeted += 1
            log(f"  ✓ retweeted")
        else:
            log(f"  ✗ retweet failed")
        time.sleep(random.uniform(5, 10))

    log(f"Retweets: done {retweeted}")


def run_original_post():
    done = _today_count("post")
    if done >= DAILY_POSTS:
        log(f"Post: already posted today ({done}), skipping")
        return
    log("Generating original tweet...")
    text = generate_tweet()
    if not text:
        log("✗ content generation failed, skipping post")
        return
    log(f"  Tweet: '{text}'")
    ok, url = post_original_tweet(text)
    if ok:
        _log_action("post", url, text[:200])
        log(f"✓ posted: {url}")
    else:
        log(f"✗ post failed: {url}")


# ─── Daemon helpers ────────────────────────────────────────────────────────

def _time_today(hour, minute=0):
    return datetime.datetime.combine(datetime.date.today(),
                                     datetime.time(hour, minute))

def _wait_until(target):
    while datetime.datetime.now() < target:
        remaining = (target - datetime.datetime.now()).total_seconds()
        if remaining <= 0:
            break
        time.sleep(min(remaining, 60))

def _reset():
    """Kill and restart browser session between tasks."""
    import subprocess as _sp
    _sp.run(["pkill", "-f", "warmup.session"], capture_output=True)
    time.sleep(2)
    for f in ["/tmp/leegowlessie-browser.sock", "/tmp/leegowlessie-browser.pid"]:
        try: os.remove(f)
        except: pass
    if not ensure_session():
        log("  Failed to restart session")
        return False
    log("  Session restarted")
    return True


# ─── Main daemon ──────────────────────────────────────────────────────────

def main():
    today = datetime.date.today().isoformat()
    log(f"=== Leegowlessie Warmup Daemon [{today}] starting ===")

    _init_db()

    if not ensure_session():
        log("Browser session failed. Is Leegowlessie Chrome on port 9223?")
        log("  Run: scripts/launch_leegowlessie_browser.sh")
        return

    log("Browser session ready")

    # Build schedule: spread 5 tasks across 10:00-18:00 with jitter
    now = datetime.datetime.now()
    start_hour = max(now.hour + 1, 10)
    end_hour = 18

    tasks = [
        ("follows", run_follows),
        ("likes", run_likes),
        ("replies", run_replies),
        ("retweets", run_retweets),
        ("post", run_original_post),
    ]

    if start_hour >= end_hour:
        # Late start — run all now
        log("Late start — running all tasks now")
        task_times = [now + datetime.timedelta(seconds=i * 30) for i in range(len(tasks))]
    else:
        # Spread across the day
        span = (end_hour - start_hour) * 60
        slot = span / len(tasks)
        task_times = []
        for i in range(len(tasks)):
            offset = int(i * slot) + random.randint(0, max(0, int(slot) - 1))
            task_times.append(_time_today(start_hour) + datetime.timedelta(minutes=offset))

    # Execute schedule
    for (task_name, task_fn), target_time in zip(tasks, task_times):
        if target_time > datetime.datetime.now():
            wait_min = (target_time - datetime.datetime.now()).total_seconds() / 60
            log(f"Next: {task_name} at {target_time.strftime('%H:%M')} ({int(wait_min)}min away)")
            _wait_until(target_time)

        log(f"── {task_name.title()} ──")
        try:
            task_fn()
        except Exception as e:
            log(f"  {task_name} failed: {e}")

        time.sleep(5)
        _reset()

    # Summary
    conn = sqlite3.connect(DB)
    summary = conn.execute(
        "SELECT action, COUNT(*) FROM warmup_log WHERE date=? GROUP BY action",
        (today,)
    ).fetchall()
    conn.close()
    log(f"=== Done [{today}] ===")
    for action, cnt in summary:
        log(f"  {action}: {cnt}")


if __name__ == "__main__":
    main()
