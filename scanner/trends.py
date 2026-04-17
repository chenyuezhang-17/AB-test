"""Trend scanner for Scene 1: Trend-Jacking Auto-Posting

Fetches today's hot topics in tech/hiring/people space,
converts them into Lessie search prompts.
"""

from __future__ import annotations
import json
import subprocess
from datetime import datetime


import os
import shutil

def _lessie_bin() -> str:
    path = shutil.which("lessie")
    if path:
        return path
    nvm = os.path.expanduser("~/.nvm/versions/node/v24.14.1/bin/lessie")
    if os.path.exists(nvm):
        return nvm
    return "lessie"


def _web_search(query: str) -> list[dict]:
    """Search via lessie call web_search and return results."""
    import os
    env = os.environ.copy()
    nvm_node = os.path.expanduser("~/.nvm/versions/node/v24.14.1/bin")
    env["PATH"] = nvm_node + ":" + env.get("PATH", "")
    try:
        args_json = json.dumps({"query": query, "count": 5})
        result = subprocess.run(
            [_lessie_bin(), "call", "web_search", "--args", args_json],
            capture_output=True, text=True, timeout=30, env=env
        )
        if result.returncode != 0:
            print(f"[trends] web_search error: {result.stderr[:200]}")
            return []
        data = json.loads(result.stdout)
        return data.get("results", [])
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"[trends] web_search failed: {e}")
        return []


def fetch_trends() -> list[dict]:
    """Fetch today's trending topics relevant to people search.

    Returns list of:
    {
        "topic": "trending topic name",
        "context": "why it's trending",
        "source_url": "where we found it"
    }
    """
    today = datetime.now().strftime("%Y-%m-%d")
    trends = []
    seen = set()

    queries = [
        # hiring / talent market
        f"major tech layoffs {today}",
        f"tech company hiring surge remote jobs {today}",
        # startup / funding → find founders & builders
        f"AI startup funding raised {today}",
        f"new unicorn startup founded {today}",
        # new products → find builders, KOLs, early adopters
        f"new AI tool product launch this week",
        f"viral app launch indie hacker {today}",
        # creator economy → find KOLs
        f"top creator influencer marketing deal brand {today}",
        # expert demand → consultants, advisors
        f"demand for AI consultants experts 2026",
    ]

    for query in queries:
        results = _web_search(query)
        for r in results:
            name = r.get("name", "").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            trends.append({
                "topic": name,
                "context": r.get("snippet", ""),
                "source_url": r.get("url", ""),
            })

    print(f"[trends] Found {len(trends)} trending topics")
    return trends


CONVERT_PROMPT = """You convert trending topics into Lessie people-search prompts AND high-performing tweets.

Given a trending topic and its context, generate a search prompt AND a tweet hook.

## Tweet hook rules:
- Write like a smart insider, NOT a marketer
- Lead with a SPECIFIC data point, contrarian take, or surprising insight from the trend
- Make it feel like an observation, not an ad ("I searched this and found..." NOT "Check out Lessie!")
- Create genuine curiosity — the reader should think "wait, really?"
- Under 240 chars total (hook + link)
- English only, lowercase tone, 1 emoji max
- DO NOT use phrases like "ran a search", "here's who", "check this out"
- GOOD hooks make a claim or ask a question the trend raises about PEOPLE

Output JSON only:
{
  "should_post": true/false,
  "search_prompt": "the Lessie search checkpoint (2-3 sentences, specific)",
  "tweet_hook": "tweet text under 200 chars — a sharp take or data point about the people behind this trend",
  "filter": {
    "person_titles": ["if B2B"],
    "person_locations": ["if relevant"],
    "platform": "if KOL search",
    "content_topics": ["if KOL"],
    "follower_min": 10000
  },
  "search_mode": "b2b" | "kol"
}

Set should_post=false if the topic is too generic, controversial, or not related to people.

Examples:
- Topic: "Stripe layoffs 300 engineers" →
  tweet_hook: "300 Stripe engineers just hit the market. payments infra + distributed systems background, mostly senior. wild timing given how many fintechs are still hiring 👀"

- Topic: "52K tech layoffs Q1 2026" →
  tweet_hook: "52K tech workers laid off in Q1 alone — the majority are mid-senior engineers, not juniors. companies cutting the wrong people?"

- Topic: "AI startup funding boom 2026" →
  tweet_hook: "VCs deployed $8.4B into AI in Q1. the founders getting funded all have one thing in common — look who's actually building these teams"

- Topic: "TikTok ban debate" →
  should_post: false (too political, not people-search related)"""


def convert_trend_to_search(trend: dict) -> dict | None:
    """Use Claude to convert a trend into a Lessie search prompt."""
    prompt = (
        f"Trending topic: {trend['topic']}\n"
        f"Context: {trend['context'][:500]}"
    )

    try:
        CLAUDE_BIN = "/Users/lessie/Library/Application Support/Claude/claude-code/2.1.92/claude.app/Contents/MacOS/claude"
        result = subprocess.run(
            [CLAUDE_BIN, "-p", prompt, "--system-prompt", CONVERT_PROMPT,
             "--output-format", "json", "--model", "sonnet"],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            return None

        outer = json.loads(result.stdout)
        text = outer.get("result", "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        data = json.loads(text)

        if not data.get("should_post", False):
            return None

        data["topic"] = trend["topic"]
        data["source_url"] = trend.get("source_url", "")
        return data

    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"[trends] Convert failed: {e}")
        return None


def scan_trends() -> list[dict]:
    """Full trend scan: fetch trends → convert to search prompts.

    Returns list of dicts ready for bridge module:
    {
        "topic": "...",
        "search_prompt": "...",    (= checkpoint for bridge)
        "tweet_hook": "...",
        "filter": {...},
        "search_mode": "b2b" | "kol",
    }
    """
    trends = fetch_trends()
    results = []

    for trend in trends:
        print(f"[trends] Evaluating: {trend['topic'][:60]}...")
        converted = convert_trend_to_search(trend)
        if converted:
            results.append(converted)
            print(f"[trends] ✅ {converted['tweet_hook'][:80]}...")

    # Dedup: skip trends with very similar hooks
    seen_hooks = set()
    deduped = []
    for r in results:
        # Use first 5 words as dedup key
        key = " ".join(r["tweet_hook"].lower().split()[:5])
        if key not in seen_hooks:
            seen_hooks.add(key)
            deduped.append(r)

    print(f"[trends] {len(deduped)} unique trends (from {len(results)} total)")
    return deduped


if __name__ == "__main__":
    print("Scanning for trending topics...\n")
    results = scan_trends()
    for r in results:
        print(f"\n--- {r['topic']} ---")
        print(f"Hook: {r['tweet_hook']}")
        print(f"Search: {r['search_prompt'][:150]}...")
