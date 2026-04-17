"""Leego Learning System — per-intent persistent strategy memory.

Architecture:
  strategy/
    alliiexia/
      _overview.md              ← account-level strategy
      intent/
        hiring.md               ← what works for hiring tweets
        cofounder.md            ← what works for cofounder-seeking tweets
        expert.md               ← consultant/advisor requests
        ...                     ← one file per intent type
      kol/
        _overview.md            ← KOL engagement overall
        tech.md / growth.md ... ← per-category KOL strategy
    leegowlessie/
      _overview.md              ← warmup account strategy
      content.md                ← original tweet strategy
      engagement.md             ← like/reply/retweet strategy

Usage:
  from learn import load_strategy, update_all_strategies

  # Load strategy for a specific intent (falls back to account overview)
  ctx = load_strategy(intent="hiring", account="alliiexia")

  # End-of-day: analyze performance and rewrite all strategy files
  update_all_strategies()
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import datetime
from pathlib import Path

DB = Path(__file__).parent / "activity.db"
STRATEGY_DIR = Path(__file__).parent / "strategy"

# ─── Intent → file mapping ────────────────────────────────────────────────

INTENT_FILES = {
    "hiring":                "hiring.md",
    "looking_for_cofounder": "cofounder.md",
    "looking_for_expert":    "expert.md",
    "looking_for_kol":       "kol_search.md",
    "looking_for_investor":  "investor.md",
    "looking_for_partner":   "partner.md",
    "talent_scouting":       "talent_scouting.md",
    "recommendation":        "recommendation.md",
    "looking_for_service":   "service.md",
}

MIN_POSTS_FOR_STRATEGY = 2  # need at least N posts to generate intent strategy


# ─── Load ──────────────────────────────────────────────────────────────────

def load_strategy(intent: str = "", account: str = "alliiexia") -> str:
    """Load strategy for a specific intent + account.

    Priority:
      1. intent-specific file (e.g. strategy/alliiexia/intent/hiring.md)
      2. account overview   (e.g. strategy/alliiexia/_overview.md)
      3. empty string (no strategy yet)
    """
    base = STRATEGY_DIR / account

    # Intent-specific
    if intent and intent in INTENT_FILES:
        path = base / "intent" / INTENT_FILES[intent]
        if path.exists():
            return path.read_text()

    # Account overview
    overview = base / "_overview.md"
    if overview.exists():
        return overview.read_text()

    return ""


def load_kol_strategy(category: str = "", account: str = "alliiexia") -> str:
    """Load KOL engagement strategy for a category (tech/growth/creator/etc)."""
    base = STRATEGY_DIR / account / "kol"
    if category:
        path = base / f"{category}.md"
        if path.exists():
            return path.read_text()
    overview = base / "_overview.md"
    if overview.exists():
        return overview.read_text()
    return ""


def load_warmup_strategy(topic: str = "") -> str:
    """Load warmup account strategy."""
    base = STRATEGY_DIR / "leegowlessie"
    if topic:
        path = base / f"{topic}.md"
        if path.exists():
            return path.read_text()
    overview = base / "_overview.md"
    if overview.exists():
        return overview.read_text()
    return ""


# ─── Data collection ───────────────────────────────────────────────────────

def _get_recent_posts(days: int = 7) -> list[dict]:
    """Get posted tweets with intent info from JOIN."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT pt.posted_at, pt.original_tweet_id, pt.reply_text,
               pt.lessie_url, pt.scene,
               pt.views, pt.likes, pt.retweets, pt.replies,
               al.intent, al.author, al.tweet_text AS original_text
        FROM posted_tweets pt
        LEFT JOIN activity_log al
          ON al.tweet_id = pt.original_tweet_id AND al.stage = 'reasoner'
        WHERE pt.posted_at > ?
        ORDER BY pt.posted_at DESC
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_warmup_stats(days: int = 7) -> list[dict]:
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT date, action, COUNT(*) as cnt, GROUP_CONCAT(detail, ' | ') as details
        FROM warmup_log WHERE date > ?
        GROUP BY date, action ORDER BY date DESC
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Claude strategy generation ────────────────────────────────────────────

def _claude(prompt: str, system: str, max_len: int = 2000) -> str | None:
    """Call Claude CLI, return text output or None."""
    claude_bin = (
        "/Users/lessie/.local/bin/claude"
        if os.path.exists("/Users/lessie/.local/bin/claude")
        else "claude"
    )
    try:
        result = subprocess.run(
            [claude_bin, "-p", prompt, "--system-prompt", system,
             "--model", "haiku", "--output-format", "text"],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "PATH": "/Users/lessie/.local/bin:" +
                 os.path.expanduser("~/.nvm/versions/node/v24.14.1/bin") + ":" +
                 os.environ.get("PATH", "")}
        )
        text = result.stdout.strip()
        bad = ["api error", "authentication_error", "failed to authenticate",
               "traceback", '"type":"error"']
        if text and len(text) > 50 and not any(b in text.lower() for b in bad):
            return text[:max_len]
    except Exception as e:
        print(f"[learn] Claude error: {e}")
    return None


STRATEGY_SYSTEM = """You are a Twitter growth strategist analyzing account performance data.
Write a concise strategy memo based on the data provided.
Be specific and data-driven — reference actual numbers and tweet text.
Output markdown. Keep it under 400 words.
Focus on ACTIONABLE guidance that directly improves the next tweet/reply."""


# ─── Update logic ──────────────────────────────────────────────────────────

def _write_strategy(path: Path, content: str):
    """Write strategy file with timestamp header."""
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"<!-- Updated: {datetime.datetime.now().isoformat(timespec='minutes')} -->\n"
        f"<!-- Auto-generated by learn.py — overwritten on each analysis cycle -->\n\n"
    )
    path.write_text(header + content)
    print(f"[learn] wrote {path.relative_to(STRATEGY_DIR)}")


def _format_posts(posts: list[dict], limit: int = 10) -> str:
    """Format posts for Claude prompt — compact, engagement-focused."""
    lines = []
    for p in posts[:limit]:
        v, l, rt = p.get("views") or 0, p.get("likes") or 0, p.get("retweets") or 0
        score = v + l * 3 + rt * 2
        text = (p.get("reply_text") or "")[:120].replace("\n", " ")
        author = p.get("author") or ""
        lines.append(f"  [{score:>4} pts] @{author}: {text}")
    return "\n".join(lines) or "  (no data)"


def _update_intent_strategy(intent: str, posts: list[dict]):
    """Generate and write strategy for one intent type."""
    if len(posts) < MIN_POSTS_FOR_STRATEGY:
        return

    # Sort by engagement score
    for p in posts:
        v, l, rt = p.get("views") or 0, p.get("likes") or 0, p.get("retweets") or 0
        p["_score"] = v + l * 3 + rt * 2
    posts.sort(key=lambda p: p["_score"], reverse=True)

    prompt = f"""Analyze @alliiexia's "{intent}" tweet replies (last 7 days).

## Posts (sorted by engagement score):
{_format_posts(posts, 15)}

## Task:
1. **What worked** — which reply styles, hooks, specificity level got most engagement?
2. **What didn't work** — what underperformed and why?
3. **Reply template** — write 2-3 template patterns for this intent type
4. **Tone guidance** — specific dos and don'ts for "{intent}" replies
5. **Avoid** — phrases or patterns that hurt engagement"""

    text = _claude(prompt, STRATEGY_SYSTEM)
    if text:
        path = STRATEGY_DIR / "alliiexia" / "intent" / INTENT_FILES[intent]
        _write_strategy(path, f"# Strategy: {intent}\n\n{text}")


def _update_account_overview(posts: list[dict]):
    """Generate account-level overview for @alliiexia."""
    # Group by scene
    by_scene = {}
    for p in posts:
        scene = p.get("scene") or "unknown"
        by_scene.setdefault(scene, []).append(p)

    scene_summary = []
    for scene, ps in by_scene.items():
        views = [p.get("views") or 0 for p in ps]
        avg_v = sum(views) / len(views) if views else 0
        likes = sum(p.get("likes") or 0 for p in ps)
        scene_summary.append(f"  {scene}: {len(ps)} posts, avg {avg_v:.0f} views, {likes} total likes")

    # Group by intent
    by_intent = {}
    for p in posts:
        intent = p.get("intent") or "unknown"
        by_intent.setdefault(intent, []).append(p)

    intent_summary = []
    for intent, ps in by_intent.items():
        views = [p.get("views") or 0 for p in ps]
        avg_v = sum(views) / len(views) if views else 0
        intent_summary.append(f"  {intent}: {len(ps)} posts, avg {avg_v:.0f} views")

    prompt = f"""Analyze @alliiexia overall performance (last 7 days, {len(posts)} posts).

## By Scene:
{chr(10).join(scene_summary)}

## By Intent:
{chr(10).join(intent_summary)}

## Top 5 posts:
{_format_posts(sorted(posts, key=lambda p: (p.get('views') or 0) + (p.get('likes') or 0) * 3, reverse=True), 5)}

## Bottom 5 posts:
{_format_posts(sorted(posts, key=lambda p: (p.get('views') or 0) + (p.get('likes') or 0) * 3)[:5], 5)}

## Task:
1. **Overall health** — is engagement growing, flat, or declining?
2. **Best performing intent type** and why
3. **Content strategy** — what to focus on this week
4. **Posting rhythm** — any time-of-day patterns?
5. **Top risk** — the #1 thing that could hurt growth"""

    text = _claude(prompt, STRATEGY_SYSTEM)
    if text:
        _write_strategy(STRATEGY_DIR / "alliiexia" / "_overview.md",
                        f"# @alliiexia Strategy Overview\n\n{text}")


def _update_kol_strategy(posts: list[dict]):
    """Generate KOL engagement strategy from KOL-tagged posts."""
    kol_posts = [p for p in posts if p.get("scene") == "KOL Engagement"]
    if len(kol_posts) < MIN_POSTS_FOR_STRATEGY:
        return

    prompt = f"""Analyze @alliiexia's KOL engagement performance (last 7 days).

## KOL replies ({len(kol_posts)} total):
{_format_posts(kol_posts, 10)}

## Task:
1. **Which KOL types responded well** — tech, growth, creator, marketing?
2. **Reply tone that works** — data-add vs opinion vs question?
3. **Which categories to expand into** — growth, marketing, creator economy, lifestyle?
4. **Avoid** — reply patterns that got no engagement
5. **Category mix** — recommended % split across tech/growth/marketing/creator/lifestyle"""

    text = _claude(prompt, STRATEGY_SYSTEM)
    if text:
        _write_strategy(STRATEGY_DIR / "alliiexia" / "kol" / "_overview.md",
                        f"# KOL Engagement Strategy\n\n{text}")


def _update_warmup_strategy(warmup_stats: list[dict], posts: list[dict]):
    """Generate strategy for @Leegowlessie warmup account."""
    # Filter warmup account posts (original tweets)
    warmup_posts = [p for p in posts if "warmup" in (p.get("scene") or "").lower()]

    stats_text = "\n".join(
        f"  {s['date']} {s['action']}: {s['cnt']}"
        for s in warmup_stats[:20]
    ) or "  (no warmup data)"

    prompt = f"""Analyze @Leegowlessie warmup account (養号 account, last 7 days).

## Daily activity:
{stats_text}

## Original tweets posted:
{_format_posts(warmup_posts, 5) if warmup_posts else '  (no tweet data with engagement)'}

## Task:
1. **Activity balance** — are follows/likes/replies/posts well-distributed?
2. **Content themes** — what original tweet topics to focus on?
3. **Engagement quality** — are replies adding value or generic?
4. **Growth trajectory** — what to prioritize this week?
5. **Theme expansion** — suggest topics beyond tech (growth, marketing, creator economy, lifestyle)"""

    text = _claude(prompt, STRATEGY_SYSTEM)
    if text:
        _write_strategy(STRATEGY_DIR / "leegowlessie" / "_overview.md",
                        f"# @Leegowlessie Warmup Strategy\n\n{text}")


# ─── Public API ────────────────────────────────────────────────────────────

def update_all_strategies():
    """End-of-day: analyze all performance data and update every strategy file.

    Costs: ~5-8 Claude Haiku calls (1 per intent with data + overviews).
    """
    print("[learn] === Updating strategies ===")

    posts = _get_recent_posts(days=7)
    warmup = _get_warmup_stats(days=7)

    if not posts and not warmup:
        print("[learn] No data at all, skipping")
        return

    # 1. Per-intent strategies for @alliiexia
    by_intent = {}
    for p in posts:
        intent = p.get("intent")
        if intent:
            by_intent.setdefault(intent, []).append(p)

    for intent, intent_posts in by_intent.items():
        if intent in INTENT_FILES:
            _update_intent_strategy(intent, intent_posts)

    # 2. Account overview for @alliiexia
    if posts:
        _update_account_overview(posts)

    # 3. KOL engagement strategy
    _update_kol_strategy(posts)

    # 4. Warmup strategy for @Leegowlessie
    _update_warmup_strategy(warmup, posts)

    print("[learn] === Strategy update complete ===")


if __name__ == "__main__":
    update_all_strategies()
