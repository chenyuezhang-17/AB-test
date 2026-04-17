"""
Lessie Twitter 全自动日更系统
每天9:00自动启动，全天无人值守运行：
1. 扫描今日热词 (S1候选)
2. 分析昨日互动，学习优化
3. 每2小时发1条（2 S1 + 3 S2），共5条
4. 收盘后抓取互动数据
5. 写入学习日志供下次优化
"""
import sys, os, time, json, sqlite3, datetime, subprocess
sys.path.insert(0, '/Users/lessie/cc/AB-test')

from dotenv import load_dotenv
load_dotenv('/Users/lessie/cc/AB-test/.env')

from action.browser_post import post_quote_browser, post_tweet_browser, _is_session_running
from bridge.search import _create_share_link, _build_search_prompt
from db_log import log_action, scrape_engagement
from scanner.trends import scan_trends
from db_log import save_trend_candidates, get_trend_candidates

DB      = '/Users/lessie/cc/AB-test/activity.db'
LOG     = '/tmp/lessie_daily.log'
DAILY_LIMIT = 5
POST_INTERVAL = 0  # no wait between posts

# ─── logging ───────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, 'a') as f:
        f.write(line + '\n')

# ─── session ───────────────────────────────────────────────────────────────

def ensure_browser():
    if not _is_session_running():
        log("Browser session dead — restarting...")
        subprocess.Popen(
            [sys.executable, "-m", "browser.session"],
            cwd="/Users/lessie/cc/AB-test/action",
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        time.sleep(7)
    return True

# ─── learn from yesterday ──────────────────────────────────────────────────

def learn_from_yesterday():
    """Read yesterday's engagement, log insights for prompt tuning."""
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    conn = sqlite3.connect(DB)
    rows = conn.execute("""
        SELECT scene, reply_text, lessie_url, views, likes, retweets, our_tweet_url
        FROM posted_tweets
        WHERE posted_at LIKE ? ORDER BY views DESC
    """, (f"{yesterday}%",)).fetchall()
    conn.close()

    if not rows:
        log("No yesterday data to learn from.")
        return

    log(f"📊 Yesterday ({yesterday}): {len(rows)} posts")
    for r in rows:
        scene, text, url, views, likes, rts, tweet_url = r
        log(f"  [{scene}] 👁{views or 0} ❤{likes or 0} 🔁{rts or 0} → {(text or '')[:60]}")

    # Identify best performer
    best = max(rows, key=lambda r: (r[3] or 0) + (r[4] or 0) * 3 + (r[5] or 0) * 2)
    log(f"  🏆 Best: [{best[0]}] '{(best[1] or '')[:80]}'")

    # Write insight to DB
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS learning_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            total_posts INTEGER,
            best_scene TEXT,
            best_hook TEXT,
            avg_views REAL,
            notes TEXT
        )
    """)
    avg_views = sum(r[3] or 0 for r in rows) / len(rows)
    conn.execute("""
        INSERT INTO learning_log (date, total_posts, best_scene, best_hook, avg_views, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        yesterday, len(rows),
        best[0], (best[1] or '')[:200],
        avg_views,
        json.dumps([{"scene": r[0], "views": r[3], "likes": r[4]} for r in rows])
    ))
    conn.commit()
    conn.close()

# ─── pick best S2 candidates ───────────────────────────────────────────────

AUTHOR_MAX_QUOTES   = 2    # max times we ever quote the same author
AUTHOR_COOLDOWN_DAYS = 7   # must wait this many days before re-quoting

def pick_s2_candidates(n=3):
    """Pick n S2 candidates not yet posted, prioritising diversity of intent.

    Rules:
    - Never quote the same tweet twice
    - Max AUTHOR_MAX_QUOTES quotes per author (ever)
    - At least AUTHOR_COOLDOWN_DAYS days between quotes to the same author
    - Skip deleted/suspended tweets
    """
    conn = sqlite3.connect(DB)
    posted_ids = set(
        r[0] for r in conn.execute(
            "SELECT original_tweet_id FROM posted_tweets WHERE original_tweet_id IS NOT NULL"
        ).fetchall()
    )

    # Per-author quote history: author → (count, most_recent_posted_at)
    author_history = {}  # author -> {"count": int, "last": date}
    rows_hist = conn.execute("""
        SELECT al.author, pt.posted_at
        FROM posted_tweets pt
        JOIN activity_log al ON al.tweet_id = pt.original_tweet_id
        WHERE pt.original_tweet_id IS NOT NULL
        ORDER BY pt.posted_at ASC
    """).fetchall()
    for author, posted_at in rows_hist:
        if not author:
            continue
        try:
            d = datetime.date.fromisoformat(posted_at[:10])
        except Exception:
            d = datetime.date.today()
        if author not in author_history:
            author_history[author] = {"count": 0, "last": d}
        author_history[author]["count"] += 1
        author_history[author]["last"] = max(author_history[author]["last"], d)

    suspended = set(
        r[0] for r in conn.execute(
            "SELECT tweet_id FROM activity_log WHERE detail='suspended' OR detail='deleted'"
        ).fetchall()
    )

    rows = conn.execute("""
        SELECT tweet_id, author, tweet_text, intent
        FROM activity_log
        WHERE stage='reasoner' AND status='passed'
        AND tweet_id NOT IN ({bad})
        ORDER BY ts DESC LIMIT 100
    """.format(bad=",".join(f"'{i}'" for i in (posted_ids | suspended)) or "'__none__'")
    ).fetchall()
    conn.close()

    today = datetime.date.today()
    seen_authors = set()
    picks = []
    for row in sorted(rows, key=lambda r: (1 if r[3] == 'hiring' else 0)):
        tweet_id, author, text, intent = row
        if author in seen_authors:
            continue
        if tweet_id in posted_ids or tweet_id in suspended:
            continue
        hist = author_history.get(author)
        if hist:
            if hist["count"] >= AUTHOR_MAX_QUOTES:
                continue   # hit lifetime cap
            if (today - hist["last"]).days < AUTHOR_COOLDOWN_DAYS:
                continue   # too soon to re-engage
        seen_authors.add(author)
        picks.append(row)
        if len(picks) >= n:
            break
    return picks

# ─── pick S1 trend ─────────────────────────────────────────────────────────

def pick_s1_candidates(n=2):
    """Pick n pending trend candidates, prefer high-engagement topics."""
    conn = sqlite3.connect(DB)
    rows = conn.execute("""
        SELECT id, topic, tweet_hook, search_prompt
        FROM trend_candidates
        WHERE status='pending'
        ORDER BY scanned_at DESC LIMIT 20
    """).fetchall()
    conn.close()
    return rows[:n]

def mark_trend_posted(tid):
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE trend_candidates SET status='posted' WHERE id=?", (tid,))
    conn.commit(); conn.close()

# ─── post functions ────────────────────────────────────────────────────────

def post_s1(row):
    tid, topic, hook, search_prompt = row
    checkpoint = search_prompt or f"Find professionals relevant to: {topic}"
    log(f"S1 checkpoint: {checkpoint[:100]}")
    share_url = _create_share_link(checkpoint) or "https://lessie.ai"
    tweet_text = f"{hook}\n\n{share_url}"
    log(f"S1 posting: {tweet_text[:90]}...")
    ensure_browser()
    ok, url = post_tweet_browser(tweet_text)
    if ok:
        log(f"S1 ✓ {url}")
        log_action(reply_text=tweet_text, lessie_url=share_url,
                   scene="Scene 1: Trends",
                   our_tweet_url=url if url.startswith("http") else "")
        mark_trend_posted(tid)
        return True
    else:
        log(f"S1 ✗ {url}")
        return False

def _mark_tweet_dead(tweet_id: str, reason: str = "deleted"):
    """Mark a tweet as deleted/suspended so we never retry it."""
    conn = sqlite3.connect(DB)
    conn.execute(
        "UPDATE activity_log SET detail=? WHERE tweet_id=?", (reason, tweet_id)
    )
    conn.commit(); conn.close()
    log(f"  ↳ marked tweet {tweet_id} as '{reason}'")


S2_REPLY_PROMPT = """You write a single tweet reply for @alliiexia (Leego, a people search tool).

Rules:
- English only
- Sound like a sharp insider who just ran a quick search, not a bot or ad
- Reference something SPECIFIC from the original tweet (role, skill, location, context)
- Be direct and casual — Silicon Valley tone
- Under 200 chars (the share link gets appended separately)
- 1 emoji max, at the end
- DO NOT say "ran a search on this", "talent pool", "relevant", or "check this out"
- DO NOT start with "I" or "Hey"

GOOD examples:
- "pulled ~40 senior ML engineers with LLM infra background, a few from DeepMind/Cohere — some are open to contract 👀"
- "searched this — 60+ full-stack devs in Lagos, mostly React + Node, open to remote roles. solid depth actually"
- "found 30 UX designers with fintech background, contract-ready. a few built checkout flows at top fintechs"

Output: just the reply text, no JSON, no quotes."""


def _generate_s2_reply(tweet_text: str, author: str, intent: str, checkpoint: str):
    """Generate a personalized S2 quote reply using Claude CLI.

    Returns the reply text, or None if generation fails (caller should skip this tweet).
    """
    prompt = (
        f"Original tweet by @{author} ({intent}):\n\"{tweet_text[:400]}\"\n\n"
        f"Search that was run: {checkpoint[:200]}\n\n"
        f"Write the reply:"
    )
    claude_bin = (
        "/Users/lessie/.local/bin/claude"
        if os.path.exists("/Users/lessie/.local/bin/claude")
        else "claude"
    )
    for attempt in range(2):   # retry once on timeout
        try:
            result = subprocess.run(
                [claude_bin, "-p", prompt, "--system-prompt", S2_REPLY_PROMPT, "--model", "haiku"],
                capture_output=True, text=True, timeout=60,
                env={**os.environ, "PATH": "/Users/lessie/.local/bin:" +
                     os.path.expanduser("~/.nvm/versions/node/v24.14.1/bin") + ":" +
                     os.environ.get("PATH", "")}
            )
            text = result.stdout.strip()
            # Reject empty, too long, or generic-looking output
            if not text or len(text) > 220:
                log(f"  [reply gen] bad output (len={len(text)}), skipping tweet")
                return None
            # Reject API errors, auth failures, and generic phrases
            banned = [
                "talent pool", "ran a search on this", "check this out", "relevant talent",
                "failed to authenticate", "api error", "authentication_error",
                "\"type\":\"error\"", "401", "403", "error occurred",
            ]
            if any(b in text.lower() for b in banned):
                log(f"  [reply gen] output looks like error/generic, skipping tweet")
                return None
            log(f"  [reply gen] ✓ '{text[:80]}'")
            return text
        except subprocess.TimeoutExpired:
            log(f"  [reply gen] timeout (attempt {attempt+1}/2)")
        except Exception as e:
            log(f"  [reply gen] error: {e}")
            break
    log("  [reply gen] failed after retries — skipping tweet")
    return None


def post_s2(row):
    """Try to quote-repost one S2 candidate.

    Returns:
        "ok"      — posted successfully
        "deleted" — tweet/account gone, caller should try next candidate immediately
        "error"   — other failure, caller should also try next candidate
    """
    tweet_id, author, tweet_text_raw, intent = row
    tweet_url = f"https://x.com/{author}/status/{tweet_id}"
    checkpoint = _build_search_prompt(tweet_text_raw, author)
    log(f"S2 checkpoint: {checkpoint[:100]}")
    share_url = _create_share_link(checkpoint) or "https://lessie.ai"
    reply_text = _generate_s2_reply(tweet_text_raw, author, intent, checkpoint)
    if reply_text is None:
        log(f"S2 ✗ @{author} — reply generation failed, skipping to next candidate")
        return "error"
    reply = f"{reply_text}\n\n{share_url}"
    log(f"S2 posting @{author} [{intent}]: {reply_text[:100]}")
    ensure_browser()
    ok, result = post_quote_browser(tweet_url, reply)
    if ok:
        log(f"S2 ✓ {result}")
        log_action(reply_text=reply, lessie_url=share_url,
                   original_tweet_id=tweet_id, author=author,
                   scene="Scene 2: Intent",
                   our_tweet_url=result if result.startswith("http") else "")
        return "ok"
    else:
        # Detect "tweet deleted / account suspended" vs transient errors
        err = str(result).lower()
        if "retweet" in err or "no retweet" in err or "none" in err:
            log(f"S2 ✗ @{author} — tweet deleted or account suspended, skipping")
            _mark_tweet_dead(tweet_id, "deleted")
            return "deleted"
        else:
            log(f"S2 ✗ @{author} — {result}, skipping")
            _mark_tweet_dead(tweet_id, "failed")
            return "error"

# ─── KOL engagement ────────────────────────────────────────────────────────

# Seed KOL accounts — always in the pool, supplemented by dynamic discovery
KOL_SEED_ACCOUNTS = [
    "thisiskp_", "swyx", "levelsio", "bentossell", "naval",
    "shreyas", "paulg", "garrytan", "andrewchen", "emollick",
    "karpathy", "sama", "hunterwalk", "lennysan", "shl",
]

# Search queries to discover new KOL accounts each run
KOL_DISCOVERY_QUERIES = [
    "AI founder", "startup builder", "ML researcher",
    "tech investor", "SaaS founder", "product engineer",
]

DAILY_KOL_LIKES   = 3    # likes across KOL timeline
DAILY_KOL_REPLIES = 15   # value-add replies to KOL posts


def _discover_kol_accounts():
    """Discover KOL accounts dynamically via Twitter user search.

    Runs 2 random search queries, collects usernames from results,
    merges with seed list. Returns a deduplicated list.
    """
    import random as _random
    candidates = list(KOL_SEED_ACCOUNTS)
    seen = set(KOL_SEED_ACCOUNTS)

    queries = _random.sample(KOL_DISCOVERY_QUERIES, 2)
    for query in queries:
        encoded = query.replace(" ", "%20")
        _bw_alliiexia("goto", f"https://x.com/search?q={encoded}&f=user", timeout=20)
        time.sleep(3)
        result = _bw_alliiexia("eval", """(function(){
            const cells = document.querySelectorAll('[data-testid="UserCell"]');
            const out = [];
            cells.forEach(function(c) {
                const links = c.querySelectorAll('a[href^="/"]');
                for (const l of links) {
                    const m = l.href.match(/x\\.com\\/([^/?#]+)$/);
                    if (m) {
                        const u = m[1];
                        const skip = ['home','explore','notifications','messages','search'];
                        if (!skip.includes(u)) { out.push(u); break; }
                    }
                }
            });
            return out.slice(0, 10);
        })()""", timeout=10)
        found = result.get("value") or []
        for u in found:
            if u not in seen:
                seen.add(u)
                candidates.append(u)
        log(f"  [kol discover] '{query}' → {len(found)} accounts found")

    return candidates

KOL_REPLY_PROMPT = """You write short, sharp replies for @alliiexia (Leego, a people search tool).

Rules:
- Sound like a smart tech insider, NOT a product pitch
- Add a SPECIFIC observation, data point, or extension of the thought
- Do NOT mention Leego, search, or any product
- Under 180 chars
- English only, casual Silicon Valley tone
- No hashtags, max 1 emoji
- Don't start with "Great point" or "Totally agree"
- Don't start with "I"

Output: just the reply text, no quotes."""


def _bw_alliiexia(cmd: str, arg: str = "", timeout: int = 30) -> dict:
    """Send command to @alliiexia browser session (port 9222 socket)."""
    import asyncio as _asyncio
    from action.browser_post import _send
    try:
        return _asyncio.run(_send(cmd, arg, timeout))
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _read_full_tweet(tweet_url: str) -> str:
    """Navigate to a tweet page and extract its full text content."""
    _bw_alliiexia("goto", tweet_url, timeout=20)
    time.sleep(3)
    result = _bw_alliiexia("eval", """(function(){
        const articles = document.querySelectorAll('article[data-testid="tweet"]');
        if (!articles.length) return '';
        // First article is the main tweet
        const main = articles[0];
        const textEl = main.querySelector('[data-testid="tweetText"]');
        if (!textEl) return '';
        return textEl.innerText.trim();
    })()""", timeout=10)
    return (result.get("value") or "").strip()


def _generate_kol_reply(tweet_text: str, author: str):
    """Generate a value-add reply to a KOL tweet. Returns text or None."""
    prompt = (
        f'Tweet by @{author}:\n"{tweet_text[:350]}"\n\n'
        f'Write a sharp, value-add reply:'
    )
    claude_bin = (
        "/Users/lessie/.local/bin/claude"
        if os.path.exists("/Users/lessie/.local/bin/claude")
        else "claude"
    )
    try:
        result = subprocess.run(
            [claude_bin, "-p", prompt, "--system-prompt", KOL_REPLY_PROMPT, "--model", "haiku"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "PATH": "/Users/lessie/.local/bin:" +
                 os.path.expanduser("~/.nvm/versions/node/v24.14.1/bin") + ":" +
                 os.environ.get("PATH", "")}
        )
        text = result.stdout.strip()
        bad = ["api error", "authentication_error", "\"type\":\"error\"", "failed to authenticate"]
        if text and 10 < len(text) < 200 and not any(b in text.lower() for b in bad):
            return text
    except Exception as e:
        log(f"  [kol reply gen] {e}")
    return None


def engage_kol():
    """Like and reply to KOL content from @alliiexia browser session."""
    import random as _random
    log("── KOL Engagement ──")
    ensure_browser()

    # Discover KOL accounts dynamically (seeds + search results)
    all_kols = _discover_kol_accounts()
    targets = _random.sample(all_kols, min(8, len(all_kols)))
    liked_total = 0
    replied_total = 0

    for username in targets:
        if liked_total >= DAILY_KOL_LIKES and replied_total >= DAILY_KOL_REPLIES:
            break

        log(f"  Visiting @{username}...")
        _bw_alliiexia("goto", f"https://x.com/{username}", timeout=20)
        time.sleep(3)

        # Read follower count from profile page
        follower_res = _bw_alliiexia("eval", """(function(){
            const els = document.querySelectorAll('a[href$="/followers"] span');
            for (const el of els) {
                const txt = el.innerText.replace(/,/g,'').trim();
                const m = txt.match(/^([\\d\\.]+)([KkMm]?)$/);
                if (m) {
                    let n = parseFloat(m[1]);
                    if (m[2].toLowerCase() === 'k') n *= 1000;
                    if (m[2].toLowerCase() === 'm') n *= 1000000;
                    return Math.round(n);
                }
            }
            return 0;
        })()""", timeout=8)
        follower_count = int(follower_res.get("value") or 0)
        is_big_kol = follower_count >= 500000
        if follower_count:
            log(f"  @{username} followers: {follower_count:,}{' (big KOL → will follow after reply)' if is_big_kol else ''}")

        # Collect tweets from their timeline
        result = _bw_alliiexia("eval", """(function(){
            const articles = document.querySelectorAll('article[data-testid="tweet"]');
            const out = [];
            articles.forEach(function(a) {
                const links = a.querySelectorAll('a[href*="/status/"]');
                const textEl = a.querySelector('[data-testid="tweetText"]');
                const userEl = a.querySelector('[data-testid="User-Name"] a');
                let uname = '';
                if (userEl) { const m = userEl.href.match(/x\\.com\\/([^/]+)/); if (m) uname = m[1]; }
                for (const l of links) {
                    const m = l.href.match(/x\\.com\\/[^/]+\\/status\\/(\\d+)/);
                    if (m && uname) {
                        out.push({url: l.href, text: textEl ? textEl.innerText.slice(0,250) : '', author: uname});
                        break;
                    }
                }
            });
            return out.slice(0, 8);
        })()""")
        tweets = result.get("value") or []

        # Like 1 tweet per KOL visit
        likes_here = 0
        if liked_total < DAILY_KOL_LIKES:
            like_res = _bw_alliiexia("eval", """(function(){
                const btns = document.querySelectorAll('[data-testid="like"]');
                for (const btn of btns) {
                    const label = btn.getAttribute('aria-label') || '';
                    if (!label.toLowerCase().includes('liked')) { btn.click(); return 1; }
                }
                return 0;
            })()""", timeout=15)
            likes_here = int(like_res.get("value") or 0)
            liked_total += likes_here
            if likes_here:
                log(f"  ✓ liked 1 tweet from @{username}")

        # Reply to up to 2 tweets per KOL visit
        replies_per_kol = 0
        for tweet in tweets[:3]:
            if replied_total >= DAILY_KOL_REPLIES:
                break
            if replies_per_kol >= 2:
                break
            if not tweet.get("url"):
                continue
            # Read full tweet text before generating reply
            full_text = _read_full_tweet(tweet["url"])
            if not full_text or len(full_text) < 15:
                log(f"  ✗ couldn't read @{tweet['author']} tweet, skipping")
                continue
            log(f"  Generating reply for @{tweet['author']}: '{full_text[:80]}'...")
            reply = _generate_kol_reply(full_text, tweet["author"])
            if reply:
                log(f"  Reply: '{reply[:90]}'")
                # Already on tweet page — click reply button
                click = _bw_alliiexia("eval", """(function(){
                    const articles = document.querySelectorAll('article[data-testid="tweet"]');
                    if (!articles.length) return 'no_article';
                    const btn = articles[0].querySelector('[data-testid="reply"]');
                    if (!btn) return 'no_btn';
                    btn.click(); return 'clicked';
                })()""")

                if click.get("value") == "clicked":
                    time.sleep(2)
                    for _ in range(8):
                        chk = _bw_alliiexia("eval",
                            "document.querySelector('[data-testid=\"tweetTextarea_0\"][role=\"textbox\"]') ? 'ok' : 'no'",
                            timeout=8)
                        if chk.get("value") == "ok":
                            break
                        time.sleep(1)

                    import json as _json
                    ins = _bw_alliiexia("eval", f"""(function(){{
                        const boxes = document.querySelectorAll('[data-testid="tweetTextarea_0"][role="textbox"]');
                        const el = boxes[boxes.length - 1];
                        if (!el) return 'not_found';
                        el.focus(); el.click();
                        document.execCommand('selectAll');
                        document.execCommand('insertText', false, {_json.dumps(reply)});
                        return el.innerText.trim().length > 0 ? 'ok' : 'empty';
                    }})()""", timeout=15)

                    if ins.get("value") == "ok":
                        time.sleep(1.5)
                        submit = _bw_alliiexia("eval", """(function(){
                            const btns = document.querySelectorAll('button');
                            for (const btn of btns) {
                                if (btn.innerText.trim() === 'Reply' && btn.getAttribute('aria-disabled') !== 'true') {
                                    btn.click(); return 'clicked';
                                }
                            }
                            return 'no_btn';
                        })()""")
                        if submit.get("value") == "clicked":
                            time.sleep(3)
                            log(f"  ✓ replied to @{tweet['author']}")
                            log_action(reply_text=reply, lessie_url="",
                                       scene="KOL Engagement", our_tweet_url="")
                            replied_total += 1
                            replies_per_kol += 1
                            # Follow big KOLs (500k+ followers) after replying
                            if is_big_kol:
                                follow_res = _bw_alliiexia("eval", """(function(){
                                    const btns = document.querySelectorAll('[data-testid$="-follow"]');
                                    for (const btn of btns) {
                                        const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                                        if (label.includes('follow') && !label.includes('following') && !label.includes('unfollow')) {
                                            btn.click(); return 'followed';
                                        }
                                    }
                                    return 'already_following';
                                })()""", timeout=10)
                                if follow_res.get("value") == "followed":
                                    log(f"  ✓ followed @{tweet['author']} (500k+ KOL)")
                        else:
                            log(f"  ✗ submit failed: {submit.get('value')}")
                    else:
                        log(f"  ✗ text insert failed: {ins.get('value')}")
                else:
                    log(f"  ✗ reply btn: {click.get('value')}")
            else:
                log("  ✗ reply generation failed, skipping")

        time.sleep(_random.uniform(5, 10))

    log(f"KOL: liked {liked_total} · replied {replied_total}")


# ─── main daily loop ───────────────────────────────────────────────────────

def main():
    today = datetime.date.today().isoformat()
    log(f"=== Lessie Daily Auto [{today}] starting ===")

    # 1. Learn from yesterday
    learn_from_yesterday()

    # 2. Scan fresh trends (S1 pool) — skip if we already have today's trends
    conn_check = sqlite3.connect(DB)
    existing_trends = conn_check.execute(
        "SELECT count(*) FROM trend_candidates WHERE scanned_at LIKE ? AND status='pending'",
        (f"{today}%",)
    ).fetchone()[0]
    conn_check.close()

    if existing_trends >= 5:
        log(f"Trends: {existing_trends} pending already scanned today, skipping re-scan")
    else:
        log("Scanning today's trending topics...")
        try:
            trends = scan_trends()
            saved = save_trend_candidates(trends)
            log(f"Trends: {len(trends)} found, {saved} saved")
        except Exception as e:
            log(f"Trend scan failed: {e}")

    # 3. Build today's post plan (2 S1 + 3 S2, interleaved)
    # Fetch extra S2 backups (up to 10) so we can auto-retry on deleted tweets
    s1_picks = pick_s1_candidates(n=2)
    s2_picks = pick_s2_candidates(n=10)   # extra buffer
    s2_queue = list(s2_picks)             # mutable backup pool

    log(f"Candidates: {len(s1_picks)} S1, {len(s2_queue)} S2 in pool (target 3)")

    if not s1_picks and not s2_queue:
        log("No candidates available today. Exiting.")
        return

    # Interleave: S2, S1, S2, S1, S2 (use first 3 S2 + 2 S1 for plan)
    plan = []
    s1 = list(s1_picks)
    s2_plan = s2_queue[:3]; s2_queue = s2_queue[3:]  # reserve rest as backups
    s2 = list(s2_plan)
    while s1 or s2:
        if s2: plan.append(('s2', s2.pop(0)))
        if s1: plan.append(('s1', s1.pop(0)))
    plan = plan[:DAILY_LIMIT]

    # 4. Post on schedule
    posted_count = 0
    sleep_before_next = False   # True after every successful post
    i = 0
    while i < len(plan) and posted_count < DAILY_LIMIT:
        stype, row = plan[i]

        # Only sleep between successful posts (not after a failed/skipped one)
        if sleep_before_next:
            log(f"⏳ Waiting {POST_INTERVAL//60} min until next post...")
            time.sleep(POST_INTERVAL)
            sleep_before_next = False

        # Re-check daily limit against DB (in case of external posts)
        # Exclude KOL Engagement entries — those don't count toward the daily post limit
        conn = sqlite3.connect(DB)
        n_today = conn.execute(
            "SELECT COUNT(*) FROM posted_tweets WHERE posted_at LIKE ? AND scene != 'KOL Engagement'",
            (f"{today}%",)
        ).fetchone()[0]
        conn.close()
        if n_today >= DAILY_LIMIT:
            log("Daily limit reached. Stopping.")
            break

        log(f"--- Post {posted_count+1}/{DAILY_LIMIT}: {stype.upper()} ---")

        if stype == 's1':
            success = post_s1(row)
            posted_count += 1   # S1 always counts (even if it failed, don't retry)
            sleep_before_next = True
            i += 1
        else:
            result = post_s2(row)
            if result == "ok":
                posted_count += 1
                sleep_before_next = True
                i += 1
            else:
                # Tweet gone — swap in next backup immediately, no sleep
                if s2_queue:
                    backup = s2_queue.pop(0)
                    log(f"  ↳ Swapping in backup: @{backup[1]} [{backup[3]}]")
                    plan[i] = ('s2', backup)
                    # i stays the same → retry this slot with the new candidate
                else:
                    log("  ↳ No more S2 backups available, skipping slot")
                    i += 1

    # 5. Engage with KOL content (likes + replies)
    try:
        engage_kol()
    except Exception as e:
        log(f"KOL engagement failed: {e}")

    # 6. Scrape engagement
    log("Scraping engagement data...")
    try:
        scrape_engagement()
        log("Engagement updated ✓")
    except Exception as e:
        log(f"Engagement scrape failed: {e}")

    log(f"=== Daily auto complete [{today}] ===")

if __name__ == "__main__":
    main()
