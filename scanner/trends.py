"""Trend scanner for Scene 1: Trend-Jacking Auto-Posting

Fetches today's hot topics in tech/hiring/people space,
converts them into Lessie search prompts.
"""

import json
import subprocess
from datetime import datetime


def _web_search(query: str) -> list[dict]:
    """Search via lessie web-search and return results."""
    try:
        result = subprocess.run(
            ["lessie", "web-search", "--query", query, "--count", "5"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout)
        return data.get("results", [])
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
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
        f"trending tech topics Twitter {today}",
        f"trending hiring layoffs startup news {today}",
        f"viral AI tool launch {today}",
        f"trending people search talent demand {today}",
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


CONVERT_PROMPT = """You convert trending topics into Lessie people-search prompts.

Given a trending topic and its context, generate a search prompt that:
1. Connects the trend to PEOPLE (talent, experts, creators, leaders)
2. Is specific enough to produce impressive results
3. Would make a great tweet: "Just ran a search on [topic] — here's who's leading this space"

Output JSON only:
{
  "should_post": true/false,
  "search_prompt": "the Lessie search checkpoint (2-3 sentences, specific)",
  "tweet_hook": "one-line tweet intro that ties the trend to the search (under 150 chars)",
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
- Topic: "Sora AI video generation launch" →
  search_prompt: "Find AI researchers and engineers who specialize in video generation, diffusion models, or text-to-video. Target people from OpenAI, Runway, Stability AI, Pika Labs who publish on these topics."
  tweet_hook: "sora just dropped and everyone's asking who built this — here's the talent behind AI video gen 🎬"

- Topic: "Stripe layoffs 300 engineers" →
  search_prompt: "Find senior engineers who recently worked at Stripe, specializing in payments infrastructure, distributed systems, or fintech platform engineering. These are top-tier candidates now on the market."
  tweet_hook: "300 Stripe engineers just hit the market — ran a search, some of these resumes are insane 👀"

- Topic: "TikTok ban debate" →
  should_post: false (too political, not people-search related)"""


def convert_trend_to_search(trend: dict) -> dict | None:
    """Use Claude to convert a trend into a Lessie search prompt."""
    prompt = (
        f"Trending topic: {trend['topic']}\n"
        f"Context: {trend['context'][:500]}"
    )

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--system-prompt", CONVERT_PROMPT,
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

    print(f"[trends] {len(results)} trends converted to search prompts")
    return results


if __name__ == "__main__":
    print("Scanning for trending topics...\n")
    results = scan_trends()
    for r in results:
        print(f"\n--- {r['topic']} ---")
        print(f"Hook: {r['tweet_hook']}")
        print(f"Search: {r['search_prompt'][:150]}...")
