"""Generate original tweet content for @Leegowlessie warmup.

Rotates through 3 themes:
  A) Tech/AI knowhow — data-driven insight or trend
  B) Job market — job seeker pain points / market observations
  C) People search lens — talent supply/demand observation (no product pitch)
"""
from __future__ import annotations

import os
import subprocess
import sqlite3
import datetime
from pathlib import Path

DB = '/Users/lessie/cc/AB-test/activity.db'

SYSTEM_PROMPT = """You write original tweets for @Leegowlessie — a tech/AI insider account.

Persona: sharp, data-aware, speaks from experience. No product pitches, no ads.
Audience: tech founders, engineers, job seekers, hiring managers.

Three rotating themes (pick whichever fits best given today's context):
A) Tech/AI knowhow: a specific, non-obvious insight about AI/tech trends, tools, or the industry
B) Job market: a real observation about the job search experience or hiring market in 2026
C) Talent & people: an observation about the human side of tech — who's building, who's hiring, who's not

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
- "every AI startup that raised in 2024 is now either profitable or quietly running out of runway. the middle ground is gone."
- "job boards are full. cold outreach is noise. the people getting hired are getting referred. networks > applications in 2026."

Output: just the tweet text. No quotes, no commentary."""


def _get_theme_for_today() -> str:
    """Rotate A/B/C based on day of year."""
    day = datetime.date.today().toordinal()
    return ["A", "B", "C"][day % 3]


def generate_tweet() -> str | None:
    """Generate one original tweet. Returns text or None on failure."""
    theme = _get_theme_for_today()
    theme_hints = {
        "A": "Focus on theme A: Tech/AI knowhow — a specific, data-backed insight about AI or tech right now.",
        "B": "Focus on theme B: Job market — a sharp observation about hiring or job seeking in 2026.",
        "C": "Focus on theme C: Talent & people — an insight about who's building things or how the talent landscape is shifting.",
    }
    prompt = f"Today's theme: {theme_hints[theme]}\n\nWrite one tweet."

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

    prompt = f'Tweet by @{author}:\n"{tweet_text[:300]}"\n\nWrite a value-add reply:'
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
