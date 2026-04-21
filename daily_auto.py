"""
Lessie Twitter 全自动日更系统 (Daemon Mode)
每天9:00自动启动，全天分散执行，晚上收盘分析：
1. 早上：读策略记忆 + 扫描热词 + 分析昨日数据
2. 全天：每2小时发1条（随机抖动），KOL互动穿插在帖子间隙
3. 晚上：抓取互动数据 + 运行学习系统更新策略记忆
"""
import sys, os, time, json, sqlite3, datetime, subprocess, random
sys.path.insert(0, '/Users/lessie/cc/AB-test')

from dotenv import load_dotenv
load_dotenv('/Users/lessie/cc/AB-test/.env')

from action.browser_post import post_quote_browser, post_tweet_browser, _is_session_running
from bridge.search import _create_share_link, _build_search_prompt
from db_log import log_action, scrape_engagement
from scanner.trends import scan_trends
from db_log import save_trend_candidates, get_trend_candidates
from learn import load_strategy, load_kol_strategy, update_all_strategies

DB      = '/Users/lessie/cc/AB-test/activity.db'
LOG     = '/tmp/lessie_daily.log'
DAILY_LIMIT = 5

# Strategy context — loaded at startup, refreshed after learning
_strategy_ctx = ""

# ─── logging ───────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, 'a') as f:
        f.write(line + '\n')

# ─── session ───────────────────────────────────────────────────────────────

def ensure_browser():
    """Ensure browser session is running AND WebSocket is alive (real ping)."""
    from action.browser_post import ensure_session
    ok = ensure_session()
    if not ok:
        log("Browser session failed to start")
    return ok

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

# Never quote-repost these — government, law enforcement, political, military
BLOCKED_AUTHOR_KEYWORDS = [
    "fbi", "cia", "nsa", "doj", "dhs", "nypd", "lapd", "police", "sheriff",
    "gov", "government", "senate", "congress", "whitehouse", "potus", "flotus",
    "army", "navy", "airforce", "marines", "military", "pentagon",
    "republican", "democrat", "gop", "trump", "biden", "kamala",
    "federal", "agency", "bureau", "department",
]
BLOCKED_TWEET_KEYWORDS = [
    "fbi", "federal bureau", "#fbijobs", "special agent", "defend the homeland",
    "law enforcement", "police department", "sheriff", "military", "veteran jobs",
    "government job", "apply at", "fbijobs.gov", "usajobs",
]

# Only engage with North America market — skip if tweet mentions non-NA locations
NON_NA_KEYWORDS = [
    # India
    "india", "bangalore", "bengaluru", "mumbai", "delhi", "hyderabad", "pune",
    "chennai", "coimbatore", "kolkata", "ahmedabad", "noida", "gurugram",
    "naukri", "tier-2", "tier 2", "iit", "nit",
    # Other Asia
    "singapore", "jakarta", "manila", "kuala lumpur", "ho chi minh",
    "tokyo", "seoul", "beijing", "shanghai", "shenzhen", "hong kong",
    # Europe (non-remote)
    "london", "berlin", "paris", "amsterdam", "barcelona", "madrid",
    "stockholm", "copenhagen", "dublin", "zurich",
    # Latin America
    "brazil", "argentina", "mexico city", "bogota", "lima",
    # Middle East / Africa
    "dubai", "riyadh", "cairo", "lagos", "nairobi",
    "johannesburg", "sandton", "gauteng", "cape town", "durban", "pretoria",
    "south africa", "nigeria", "kenya", "ghana", "ethiopia",
    # Explicit non-NA indicators
    "latam", "apac", "emea", "mena",
]

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
            "SELECT tweet_id FROM activity_log WHERE detail IN ('suspended', 'deleted', 'failed')"
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
        # Skip political / government / law enforcement accounts and tweets
        author_lower = (author or "").lower()
        text_lower = (text or "").lower()
        if any(kw in author_lower for kw in BLOCKED_AUTHOR_KEYWORDS):
            log(f"  [S2 skip] @{author} — blocked author keyword")
            continue
        if any(kw in text_lower for kw in BLOCKED_TWEET_KEYWORDS):
            log(f"  [S2 skip] @{author} — blocked tweet keyword")
            continue
        # Skip non-North America markets
        if any(kw in text_lower for kw in NON_NA_KEYWORDS):
            log(f"  [S2 skip] @{author} — non-NA market")
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
    share_url, _ = _create_share_link(checkpoint)
    if not share_url:
        log(f"S1 ✗ share link failed, skipping (won't post homepage link)")
        return False
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


def _generate_s2_reply(tweet_text: str, author: str, intent: str, checkpoint: str, total_found: int = 0):
    """Generate a personalized S2 quote reply using Claude CLI.

    Returns the reply text, or None if generation fails (caller should skip this tweet).
    """
    # Load intent-specific strategy memory
    strategy = load_strategy(intent=intent, account="alliiexia")
    strategy_block = ""
    if strategy:
        strategy_block = f"\n--- STRATEGY (from past performance) ---\n{strategy[:600]}\n---\n\n"

    count_hint = f"Results found: ~{total_found} people\n\n" if total_found > 0 else ""
    prompt = (
        f"{strategy_block}"
        f"Original tweet by @{author} ({intent}):\n\"{tweet_text[:400]}\"\n\n"
        f"Search that was run: {checkpoint[:200]}\n\n"
        f"{count_hint}"
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

    # Sanity check: if Claude returned a rejection/analysis instead of a real prompt, skip
    CHECKPOINT_REJECT_SIGNALS = [
        "no hiring intent", "no role", "no candidate", "commentary", "not a job",
        "not a hiring", "cannot construct", "no search", "this tweet contains",
    ]
    if len(checkpoint) < 20 or any(s in checkpoint.lower() for s in CHECKPOINT_REJECT_SIGNALS):
        log(f"S2 ✗ @{author} — checkpoint looks invalid (not a real hiring tweet), skipping")
        _mark_tweet_dead(tweet_id, "failed")
        return "error"

    share_url, total_found = _create_share_link(checkpoint)
    if not share_url:
        log(f"S2 ✗ @{author} — share link creation failed, skipping (won't post homepage link)")
        return "error"
    reply_text = _generate_s2_reply(tweet_text_raw, author, intent, checkpoint, total_found=total_found)
    if reply_text is None:
        log(f"S2 ✗ @{author} — reply generation failed, skipping to next candidate")
        return "error"
    reply = f"{reply_text}\n\n{share_url}"
    log(f"S2 posting @{author} [{intent}]: {reply_text[:100]}")
    # CDP stream takes 4-7 min — session WebSocket may have timed out, reconnect before posting
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
        if "tweet_deleted" in err or "retweet" in err or "no retweet" in err or "none" in err:
            log(f"S2 ✗ @{author} — tweet deleted or account suspended, skipping")
            _mark_tweet_dead(tweet_id, "deleted")
            return "deleted"
        else:
            log(f"S2 ✗ @{author} — {result}, skipping")
            _mark_tweet_dead(tweet_id, "failed")
            return "error"

# ─── KOL engagement ────────────────────────────────────────────────────────

# Skip tweets touching politics / news media — off-brand for Leego
POLITICAL_SIGNALS = [
    "trump", "biden", "harris", "democrat", "republican", "gop", "maga",
    "congress", "senate", "election", "impeach", "tariff", "white house",
    "president", "administration", "nato", "ukraine", "gaza", "israel",
    "political", "politician", "vote", "ballot", "legislation", "bill passed",
    "breaking news", "bbc news", "cnn", "fox news", "nbc news", "abc news",
    "reuters", "ap news", "bloomberg news", "insider trading allegation",
]

def _is_political(text: str) -> bool:
    t = text.lower()
    return any(sig in t for sig in POLITICAL_SIGNALS)

# Skip tweets mentioning Lessie AI (self-promotion, awkward to reply as Leego)
LESSIE_SIGNALS = ["lessie", "lessie.ai", "lessie ai", "leego"]
LESSIE_ACCOUNTS = {"lessie_ai", "guosiqiithaqua", "leegowlessie"}

def _is_lessie_related(text: str, author: str = "") -> bool:
    t = text.lower()
    if author.lower() in LESSIE_ACCOUNTS:
        return True
    return any(sig in t for sig in LESSIE_SIGNALS)

# AI image/video generation tool accounts — off-brand for Leego to engage
AI_VISUAL_TOOL_ACCOUNTS = {
    "krea_ai", "runwayml", "heygen_official", "synthesia_io", "pika_labs",
    "luma_ai", "stability_ai", "midjourney", "openai_dall_e", "adobe_firefly",
    "invideo_ai", "descript", "capcut", "kling_ai", "hailuo_ai", "sora",
    "magnific_ai", "topazlabs", "adobepremiere", "canva", "veed_io",
}
AI_VISUAL_TOOL_SIGNALS = [
    "realtime edit", "real-time edit", "text to video", "text-to-video",
    "image generation", "video generation", "ai image", "ai video",
    "diffusion model", "stable diffusion", "midjourney", "dall-e", "dall·e",
    "flux model", "generative image", "generative video", "video ai",
    "ai art", "image editing ai", "inpainting", "outpainting",
    "nano banana", "realtime image",
]

def _is_ai_visual_tool(text: str, author: str = "") -> bool:
    if author.lower() in AI_VISUAL_TOOL_ACCOUNTS:
        return True
    t = text.lower()
    return any(sig in t for sig in AI_VISUAL_TOOL_SIGNALS)

# Multi-pool KOL config — each category has seeds + discovery queries + weight
KOL_POOLS = {
    "tech": {
        "seeds": ["karpathy", "swyx", "levelsio", "emollick", "sama"],
        "queries": ["AI founder", "ML researcher", "startup builder"],
        "weight": 0.30,
    },
    "growth": {
        "seeds": ["randfish", "dharmesh", "Julian", "lennysan", "agazdecki"],
        "queries": ["growth marketing SaaS", "PLG strategy", "B2B growth leader"],
        "weight": 0.25,
    },
    "creator": {
        "seeds": ["sahilbloom", "dickiebush", "aliabdaal", "danmartell", "jasonfried"],
        "queries": ["creator economy", "newsletter growth", "building in public"],
        "weight": 0.20,
    },
    "hiring": {
        "seeds": ["hunterwalk", "garrytan", "naval", "shreyas", "shl"],
        "queries": ["hiring manager startup", "talent acquisition tech", "recruiter AI"],
        "weight": 0.15,
    },
    "lifestyle": {
        "seeds": ["paulg", "patrick_oshag", "andrewchen", "bentossell", "thisiskp_"],
        "queries": ["remote work founder", "founder life balance", "tech career advice"],
        "weight": 0.10,
    },
}

DAILY_KOL_LIKES   = 3    # likes across KOL timeline
DAILY_KOL_REPLIES = 15   # value-add replies to KOL posts


def _discover_kol_accounts():
    """Discover KOL accounts from multi-pool config + dynamic search.

    Weighted sampling: pick categories by weight, use seeds + search.
    Returns list of (username, category) tuples.
    """
    categories = list(KOL_POOLS.keys())
    weights = [KOL_POOLS[c]["weight"] for c in categories]
    picked = set()
    while len(picked) < min(4, len(categories)):
        choice = random.choices(categories, weights=weights, k=1)[0]
        picked.add(choice)

    candidates = []  # (username, category)
    seen = set()

    for cat in picked:
        pool = KOL_POOLS[cat]
        for u in pool["seeds"]:
            if u not in seen:
                seen.add(u)
                candidates.append((u, cat))
        # Dynamic discovery: 1 search query per category
        query = random.choice(pool["queries"])
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
                candidates.append((u, cat))
        log(f"  [kol discover] [{cat}] '{query}' -> {len(found)} found")

    return candidates

KOL_REPLY_PROMPT = """You write short, sharp replies for @alliiexia (Leego, a people search tool).

Rules:
- Sound like a smart insider who fits the conversation, NOT a product pitch
- Add a SPECIFIC observation, data point, or extension of the thought
- Adapt your tone to the topic: tech=analytical, growth=metrics-driven, creator=practical, lifestyle=relatable
- Do NOT mention Leego, search, or any product
- Under 180 chars
- English only, casual tone
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


def _generate_kol_reply(tweet_text: str, author: str, category: str = "tech"):
    """Generate a value-add reply to a KOL tweet. Returns text or None."""
    strategy = load_kol_strategy(category=category, account="alliiexia")
    strategy_block = ""
    if strategy:
        strategy_block = f"\n[STRATEGY ({category})]\n{strategy[:400]}\n[/STRATEGY]"

    prompt = (
        f'Tweet by @{author} (category: {category}):\n"{tweet_text[:350]}"\n\n'
        f'Write a sharp, value-add reply:{strategy_block}'
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
    log("── KOL Engagement ──")
    ensure_browser()

    # Discover KOL accounts from multi-pool (returns (username, category) tuples)
    all_kols = _discover_kol_accounts()
    targets = random.sample(all_kols, min(8, len(all_kols)))
    liked_total = 0
    replied_total = 0

    for username, kol_category in targets:
        if liked_total >= DAILY_KOL_LIKES and replied_total >= DAILY_KOL_REPLIES:
            break

        log(f"  Visiting @{username} [{kol_category}]...")
        _bw_alliiexia("goto", f"https://x.com/{username}", timeout=20)
        time.sleep(3)

        # Skip AI video / video SaaS accounts — not relevant to Lessie's audience
        bio_check = _bw_alliiexia("eval", """(function(){
            const bio = (document.querySelector('[data-testid="UserDescription"]') || {}).innerText || '';
            return bio.toLowerCase();
        })()""", timeout=8)
        bio_text = bio_check.get("value") or ""
        VIDEO_SAAS_SIGNALS = ["video ai", "ai video", "video saas", "video tool", "video platform",
                               "video generation", "video creator", "loom", "descript", "runway",
                               "heygen", "synthesia", "sora", "video editing", "short video"]
        if any(sig in bio_text for sig in VIDEO_SAAS_SIGNALS):
            log(f"  [kol skip] @{username} — AI video/SaaS bio, skipping")
            continue

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

        # Collect tweets from their timeline (only 2025+ tweets)
        result = _bw_alliiexia("eval", """(function(){
            const articles = document.querySelectorAll('article[data-testid="tweet"]');
            const out = [];
            articles.forEach(function(a) {
                const links = a.querySelectorAll('a[href*="/status/"]');
                const textEl = a.querySelector('[data-testid="tweetText"]');
                const userEl = a.querySelector('[data-testid="User-Name"] a');
                const timeEl = a.querySelector('time');
                let uname = '';
                if (userEl) { const m = userEl.href.match(/x\\.com\\/([^/]+)/); if (m) uname = m[1]; }
                // Skip tweets older than 2025
                if (timeEl) {
                    const dt = timeEl.getAttribute('datetime') || '';
                    const year = parseInt(dt.slice(0, 4));
                    if (year < 2025) return;
                }
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

        # Like 1 tweet per KOL visit — skip self and pre-2025 tweets
        likes_here = 0
        if liked_total < DAILY_KOL_LIKES:
            like_res = _bw_alliiexia("eval", """(function(){
                const articles = document.querySelectorAll('article[data-testid="tweet"]');
                for (const article of articles) {
                    // Skip own tweets
                    const userEl = article.querySelector('[data-testid="User-Name"] a');
                    if (userEl) {
                        const m = userEl.href.match(/x\\.com\\/([^/]+)/);
                        if (m && m[1].toLowerCase() === 'alliiexia') continue;
                    }
                    // Skip tweets older than 2025
                    const timeEl = article.querySelector('time');
                    if (timeEl) {
                        const dt = timeEl.getAttribute('datetime') || '';
                        const year = parseInt(dt.slice(0, 4));
                        if (year < 2025) continue;
                    }
                    const btn = article.querySelector('[data-testid="like"]');
                    if (!btn) continue;
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
            # Extract tweet_id from URL and skip if already replied
            _tid_match = __import__('re').search(r'/status/(\d+)', tweet["url"])
            tweet_id_kol = _tid_match.group(1) if _tid_match else None
            if tweet_id_kol:
                _conn_chk = sqlite3.connect(DB)
                _already = _conn_chk.execute(
                    "SELECT 1 FROM posted_tweets WHERE original_tweet_id=?", (tweet_id_kol,)
                ).fetchone()
                _conn_chk.close()
                if _already:
                    log(f"  ↳ already replied to tweet {tweet_id_kol}, skipping")
                    continue
            # Read full tweet text before generating reply
            full_text = _read_full_tweet(tweet["url"])
            if not full_text or len(full_text) < 15:
                log(f"  ✗ couldn't read @{tweet['author']} tweet, skipping")
                continue
            # Skip political / news content
            if _is_political(full_text):
                log(f"  [kol skip] @{tweet['author']} — political/news content, skipping")
                continue
            # Skip Lessie AI related content
            if _is_lessie_related(full_text, tweet.get("author", "")):
                log(f"  [kol skip] @{tweet['author']} — Lessie-related content, skipping")
                continue
            # Skip AI image/video generation tool accounts and content
            if _is_ai_visual_tool(full_text, tweet.get("author", "")):
                log(f"  [kol skip] @{tweet['author']} — AI visual tool content, skipping")
                continue
            log(f"  Generating reply for @{tweet['author']} [{kol_category}]: '{full_text[:80]}'...")
            reply = _generate_kol_reply(full_text, tweet["author"], category=kol_category)
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

                    # CDP click for real focus, then type full text at once
                    import json as _json
                    rect = _bw_alliiexia("eval", """(function(){
                        const boxes = document.querySelectorAll('[data-testid="tweetTextarea_0"][role="textbox"]');
                        const el = boxes[boxes.length - 1];
                        if (!el) return null;
                        const r = el.getBoundingClientRect();
                        return JSON.stringify({x: Math.round(r.left + r.width/2), y: Math.round(r.top + 10)});
                    })()""", timeout=10)
                    coords = _json.loads(rect.get("value") or "null")
                    if coords:
                        _bw_alliiexia("click_xy", f"{coords['x']},{coords['y']}")
                        time.sleep(0.3)
                    _bw_alliiexia("eval", """(function(){
                        const boxes = document.querySelectorAll('[data-testid="tweetTextarea_0"][role="textbox"]');
                        const el = boxes[boxes.length - 1];
                        if (el) { el.click(); el.focus(); }
                    })()""", timeout=5)
                    _bw_alliiexia("type", reply, timeout=60)
                    time.sleep(1)
                    ins = _bw_alliiexia("eval", """(function(){
                        const boxes = document.querySelectorAll('[data-testid="tweetTextarea_0"][role="textbox"]');
                        const el = boxes[boxes.length - 1];
                        return (el && el.innerText.trim().length > 0) ? 'ok' : 'empty';
                    })()""", timeout=8)

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
                                       original_tweet_id=tweet_id_kol or "",
                                       author=tweet.get("author", ""),
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

        time.sleep(random.uniform(5, 10))

    log(f"KOL: liked {liked_total} · replied {replied_total}")


# ─── daemon helpers ────────────────────────────────────────────────────────

def _time_today(hour, minute=0):
    """Create a datetime for today at the given hour:minute."""
    return datetime.datetime.combine(datetime.date.today(),
                                     datetime.time(hour, minute))

def _wait_until(target):
    """Sleep until target datetime, checking every 60s."""
    while datetime.datetime.now() < target:
        remaining = (target - datetime.datetime.now()).total_seconds()
        if remaining <= 0:
            break
        time.sleep(min(remaining, 60))

def _spread_times(n, start_hour, end_hour):
    """Generate n random times spread between start_hour and end_hour."""
    if n <= 0:
        return []
    span_minutes = (end_hour - start_hour) * 60
    if span_minutes <= 0 or n > span_minutes:
        return [_time_today(start_hour, i * 5) for i in range(n)]
    # Divide into n equal slots, pick a random point in each slot
    slot_size = span_minutes / n
    times = []
    for i in range(n):
        slot_start = int(i * slot_size)
        slot_end = int((i + 1) * slot_size)
        offset = random.randint(slot_start, max(slot_start, slot_end - 1))
        times.append(_time_today(start_hour) + datetime.timedelta(minutes=offset))
    return times


# ─── main daemon ──────────────────────────────────────────────────────────

def main():
    global _strategy_ctx
    today = datetime.date.today().isoformat()
    log(f"=== Leego Daily Daemon [{today}] starting ===")

    # ── Phase 1: Morning prep ──
    _strategy_ctx = load_strategy(account="alliiexia")
    if _strategy_ctx:
        log(f"Strategy loaded ({len(_strategy_ctx)} chars)")
    else:
        log("No strategy file yet — running without memory")

    learn_from_yesterday()

    # Scan trends
    conn_check = sqlite3.connect(DB)
    existing_trends = conn_check.execute(
        "SELECT count(*) FROM trend_candidates WHERE scanned_at LIKE ? AND status='pending'",
        (f"{today}%",)
    ).fetchone()[0]
    conn_check.close()
    if existing_trends >= 5:
        log(f"Trends: {existing_trends} pending, skipping re-scan")
    else:
        log("Scanning today's trending topics...")
        try:
            trends = scan_trends()
            saved = save_trend_candidates(trends)
            log(f"Trends: {len(trends)} found, {saved} saved")
        except Exception as e:
            log(f"Trend scan failed: {e}")

    # ── Phase 2: Build post plan ──
    s1_picks = pick_s1_candidates(n=2)
    s2_picks = pick_s2_candidates(n=10)
    s2_queue = list(s2_picks)

    plan = []
    s1 = list(s1_picks)
    s2_plan = s2_queue[:3]
    s2_queue = s2_queue[3:]
    s2 = list(s2_plan)
    while s1 or s2:
        if s2: plan.append(('s2', s2.pop(0)))
        if s1: plan.append(('s1', s1.pop(0)))
    plan = plan[:DAILY_LIMIT]

    log(f"Plan: {len(plan)} posts, {len(s2_queue)} S2 backups")

    # ── Phase 3: Build daily schedule ──
    now = datetime.datetime.now()
    start_hour = max(now.hour + 1, 10)  # earliest: 10am or next hour
    end_hour = 20                        # latest post: 8pm

    if start_hour >= end_hour:
        # Too late — run everything immediately (burst mode fallback)
        log("Late start — posting all now (burst mode)")
        post_times = [now + datetime.timedelta(seconds=i * 30) for i in range(len(plan))]
    else:
        post_times = _spread_times(len(plan), start_hour, end_hour)

    # KOL engagement: 3 sessions spread between posts
    kol_start = max(start_hour, 11)
    kol_end = min(end_hour + 1, 21)
    kol_times = _spread_times(3, kol_start, kol_end) if kol_start < kol_end else []

    # Merge into unified schedule: [(time, type, data), ...]
    events = []
    for i, (stype, row) in enumerate(plan):
        t = post_times[i] if i < len(post_times) else now
        events.append((t, "post", (stype, row)))
    for t in kol_times:
        events.append((t, "kol", None))
    events.sort(key=lambda e: e[0])

    log(f"Schedule: {len(events)} events from {events[0][0].strftime('%H:%M') if events else '?'} "
        f"to {events[-1][0].strftime('%H:%M') if events else '?'}")

    # ── Phase 4: Execute schedule ──
    posted_count = 0
    for target_time, event_type, data in events:
        # Wait until scheduled time
        if target_time > datetime.datetime.now():
            wait_min = (target_time - datetime.datetime.now()).total_seconds() / 60
            log(f"Next: {event_type} at {target_time.strftime('%H:%M')} ({int(wait_min)}min away)")
            _wait_until(target_time)

        if event_type == "post":
            if posted_count >= DAILY_LIMIT:
                continue
            # Re-check daily limit against DB
            conn = sqlite3.connect(DB)
            n_today = conn.execute(
                "SELECT COUNT(*) FROM posted_tweets WHERE posted_at LIKE ? AND scene != 'KOL Engagement'",
                (f"{today}%",)
            ).fetchone()[0]
            conn.close()
            if n_today >= DAILY_LIMIT:
                log("Daily limit reached in DB. Skipping remaining posts.")
                continue

            stype, row = data
            log(f"--- Post {posted_count+1}/{DAILY_LIMIT}: {stype.upper()} ---")
            ensure_browser()

            if stype == 's1':
                # Retry up to 3 times on failure
                for s1_attempt in range(3):
                    ok = post_s1(row)
                    if ok:
                        posted_count += 1
                        break
                    if s1_attempt < 2:
                        log(f"  S1 failed (attempt {s1_attempt+1}/3), retrying in 30s...")
                        time.sleep(30)
                else:
                    log(f"  S1 failed after 3 attempts, skipping")
            else:
                result = post_s2(row)
                if result == "ok":
                    posted_count += 1
                elif s2_queue:
                    backup = s2_queue.pop(0)
                    log(f"  Swapping backup: @{backup[1]}")
                    result2 = post_s2(backup)
                    if result2 == "ok":
                        posted_count += 1

        elif event_type == "kol":
            log("--- KOL Engagement ---")
            try:
                ensure_browser()
                engage_kol()
            except Exception as e:
                log(f"KOL failed: {e}")

    # ── Phase 5: Evening wrap-up ──
    wrap_time = _time_today(21, 0)
    if datetime.datetime.now() < wrap_time:
        log(f"Waiting for wrap-up at 21:00...")
        _wait_until(wrap_time)

    log("Scraping engagement data...")
    try:
        ensure_browser()
        scrape_engagement()
        log("Engagement updated")
    except Exception as e:
        log(f"Engagement scrape failed: {e}")

    log("Updating strategy memory...")
    try:
        update_all_strategies()
        log("Strategy updated")
    except Exception as e:
        log(f"Strategy update failed: {e}")

    log(f"=== Daily daemon [{today}] finished ===")

if __name__ == "__main__":
    main()
