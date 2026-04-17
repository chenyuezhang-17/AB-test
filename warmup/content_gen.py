"""Generate original tweet content for @Leegowlessie warmup.

Rotates through 6 themes (expanded from 3):
  A) Tech/AI knowhow — data-driven insight or trend
  B) Job market — job seeker pain points / market observations
  C) Talent & people — who's building, who's hiring
  D) Growth & marketing — PLG, distribution, GTM observations
  E) Creator economy — newsletters, personal brand, content strategy
  F) Founder life — building, fundraising, remote work, lessons learned
"""
from __future__ import annotations

import os
import subprocess
import sqlite3
import datetime
import random
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from learn import load_warmup_strategy

DB = '/Users/lessie/cc/AB-test/activity.db'

SYSTEM_PROMPT = """You write original tweets for @Leegowlessie — a sharp insider account.

Persona: data-aware, speaks from experience, wide range of interests. No product pitches, no ads.
Audience: tech founders, growth marketers, creators, engineers, job seekers.

Six themes (the prompt will tell you which to focus on):
A) Tech/AI knowhow: a specific, non-obvious insight about AI/tech trends
B) Job market: a real observation about the hiring market in 2026
C) Talent & people: the human side of tech — who's building, who's hiring
D) Growth & marketing: PLG, distribution, GTM, SaaS metrics, content strategy
E) Creator economy: newsletters, personal brand, YouTube/podcast, creator tools
F) Founder life: building in public, fundraising, remote work, hard-won lessons

Rules:
- English only
- Sound like a smart practitioner, not a blogger
- Lead with a specific data point, observation, or contrarian take
- Under 240 chars
- 1 emoji max, at the end or nowhere
- NO phrases: "excited to share", "thread", "hot take:", "unpopular opinion:", "game-changer", "revolutionize"
- No hashtags

GOOD examples:
- "most senior engineers who got laid off in 2025 are still job hunting in April 2026. the market absorbed juniors faster. counterintuitive."
- "LLM context windows hit 1M tokens and people are still feeding them the wrong data. the bottleneck shifted from size to curation."
- "every newsletter that hit 100k subscribers in 2025 did it through one channel: Twitter/X replies. not SEO, not paid, not cross-promo."
- "the best growth hires I've seen this year don't come from growth roles. they come from product, data, or content. title mismatch = opportunity."
- "building in public used to be a flex. now it's a funnel. the founders getting traction are the ones who document before they monetize."

Output: just the tweet text. No quotes, no commentary."""


THEMES = {
    "A": "Focus on theme A: Tech/AI knowhow — a specific, data-backed insight about AI or tech right now.",
    "B": "Focus on theme B: Job market — a sharp observation about hiring or job seeking in 2026.",
    "C": "Focus on theme C: Talent & people — an insight about who's building things or how talent is shifting.",
    "D": "Focus on theme D: Growth & marketing — a PLG, distribution, or GTM observation from the trenches.",
    "E": "Focus on theme E: Creator economy — newsletters, personal brand, or content strategy insight.",
    "F": "Focus on theme F: Founder life — building, fundraising, remote work, or a hard-won lesson.",
}


def _get_theme_for_today() -> str:
    """Pick theme: weighted random (strategy can influence) instead of rigid rotation."""
    # Default weights (equal for new themes, slightly favor established ones)
    weights = {"A": 2, "B": 2, "C": 2, "D": 1.5, "E": 1.5, "F": 1.5}
    keys = list(weights.keys())
    w = [weights[k] for k in keys]
    return random.choices(keys, weights=w, k=1)[0]


def generate_tweet() -> str | None:
    """Generate one original tweet. Returns text or None on failure."""
    theme = _get_theme_for_today()

    # Load strategy memory for context
    strategy = load_warmup_strategy(topic="content")
    strategy_block = ""
    if strategy:
        strategy_block = f"\n--- STRATEGY (from past performance) ---\n{strategy[:500]}\n---\n\n"

    prompt = f"{strategy_block}Today's theme: {THEMES[theme]}\n\nWrite one tweet."

    claude_bin = (
        "/Users/lessie/.local/bin/claude"
        if os.path.exists("/Users/lessie/.local/bin/claude")
        else "claude"
    )
    for attempt in range(2):
        try:
            result = subprocess.run(
                [claude_bin, "-p", prompt, "--system-prompt", SYSTEM_PROMPT, "--model", "haiku"],
                capture_output=True, text=True, timeout=60,
                env={**os.environ, "PATH": "/Users/lessie/.local/bin:" +
                     os.path.expanduser("~/.nvm/versions/node/v24.14.1/bin") + ":" +
                     os.environ.get("PATH", "")}
            )
            text = result.stdout.strip()
            # Strip surrounding quotes if model added them
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1].strip()
            bad_signals = ["api error", "authentication_error", "\"type\":\"error\"", "failed to authenticate", "traceback"]
            if text and 20 < len(text) < 260 and not any(b in text.lower() for b in bad_signals):
                return text
        except subprocess.TimeoutExpired:
            print(f"  [content_gen] timeout attempt {attempt+1}")
        except Exception as e:
            print(f"  [content_gen] error: {e}")
            break
    return None


def get_reply_for_tweet(tweet_text: str, author: str) -> str | None:
    """Generate a value-add reply to another user's tweet."""
    reply_prompt_system = """You write short, value-add tweet replies for @Leegowlessie.

Rules:
- Sound like a smart peer, not a marketer
- Add a specific insight, data point, or personal observation that extends the conversation
- Do NOT mention Leego or any product
- Under 200 chars
- English only, casual tech tone
- Don't start with "Great point!" or similar filler
- No hashtags, max 1 emoji

Output: just the reply text."""

    strategy = load_warmup_strategy(topic="engagement")
    strategy_block = ""
    if strategy:
        strategy_block = f"--- STRATEGY ---\n{strategy[:400]}\n---\n\n"
    prompt = f'{strategy_block}Tweet by @{author}:\n"{tweet_text[:300]}"\n\nWrite a value-add reply:'
    claude_bin = (
        "/Users/lessie/.local/bin/claude"
        if os.path.exists("/Users/lessie/.local/bin/claude")
        else "claude"
    )
    try:
        result = subprocess.run(
            [claude_bin, "-p", prompt, "--system-prompt", reply_prompt_system, "--model", "haiku"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "PATH": "/Users/lessie/.local/bin:" +
                 os.path.expanduser("~/.nvm/versions/node/v24.14.1/bin") + ":" +
                 os.environ.get("PATH", "")}
        )
        text = result.stdout.strip()
        # Reject error messages, API errors, or suspiciously long output
        bad_signals = ["api error", "authentication", "error:", "{\"type\"", "failed to", "traceback", "exception"]
        if text and 10 < len(text) < 210 and not any(b in text.lower() for b in bad_signals):
            return text
    except Exception as e:
        print(f"  [content_gen] reply error: {e}")
    return None
