"""Lessie API integration — Owner: Becky"""

import json
import subprocess

from models import AnalyzedTweet, PreparedReply

LESSIE_SHARE_BASE = "https://app.lessie.ai/search"

REPLY_SYSTEM_PROMPT = """You are Alex, a growth hacker at Lessie AI. You write tweet replies.

Style:
- Silicon Valley geek who genuinely loves helping people
- Casual, direct, never sounds like a bot or ad
- Short — under 200 chars before the link
- Reference something SPECIFIC about the person or their need (show you actually read their tweet)
- Sound like a real person who just happened to have the perfect tool

You'll get: the original tweet, the author's profile, what was searched, and how many results.

Output JSON only:
{"reply_text": "your reply text (WITHOUT the link — it gets appended automatically)"}

GOOD: "yo 50 senior product designers with fintech background, a few even worked at Stripe/Square 👀"
GOOD: "just ran this through our people search — 30 creators who reviewed Notion on YT, some with crazy engagement"
BAD: "Check out these amazing results from Lessie AI!"
BAD: "I found some people for you, here's the link" """


def _call_lessie(search_data: dict) -> dict | None:
    """Call lessie find-people with rich search params."""
    filter_obj = search_data.get("filter", {})
    checkpoint = search_data.get("checkpoint", "search")
    extra = search_data.get("extra", "")
    mode = search_data.get("search_mode", "b2b")

    # Build filter JSON for Lessie CLI
    lessie_filter = {}
    if mode == "kol":
        if filter_obj.get("platform"):
            lessie_filter["platform"] = filter_obj["platform"]
        if filter_obj.get("follower_min"):
            lessie_filter["follower_min"] = filter_obj["follower_min"]
        if filter_obj.get("content_topics"):
            lessie_filter["content_topics"] = filter_obj["content_topics"]
    else:
        if filter_obj.get("person_titles"):
            lessie_filter["person_titles"] = filter_obj["person_titles"]
        if filter_obj.get("person_locations"):
            lessie_filter["person_locations"] = filter_obj["person_locations"]
        if filter_obj.get("person_seniorities"):
            lessie_filter["person_seniorities"] = filter_obj["person_seniorities"]

    # Fallback: if filter is empty, use checkpoint as a title search
    if not lessie_filter:
        lessie_filter["person_titles"] = ["professional"]

    cmd = [
        "lessie", "find-people",
        "--filter", json.dumps(lessie_filter),
        "--checkpoint", checkpoint,
        "--strategy", "saas_only",
        "--target-count", "10",
    ]
    if extra:
        cmd.extend(["--extra", extra])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print(f"[bridge] Lessie error: {result.stderr[:200]}")
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"[bridge] Lessie call failed: {e}")
        return None


def _generate_reply(tweet: AnalyzedTweet, search_data: dict, total_found: int) -> str | None:
    """Generate a personalized Alex-persona reply using Claude CLI."""
    profile = search_data.get("profile", {})
    prompt = (
        f"Original tweet by @{tweet.author}: \"{tweet.original_text}\"\n"
        f"Author: {profile.get('name', tweet.author)}, {profile.get('role', 'unknown role')} at {profile.get('company', 'unknown company')}\n"
        f"Industry: {profile.get('industry', 'unknown')}\n"
        f"What was searched: {search_data.get('checkpoint', '')}\n"
        f"Results found: {total_found} people"
    )

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--system-prompt", REPLY_SYSTEM_PROMPT, "--output-format", "json"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return None

        outer = json.loads(result.stdout)
        text = outer.get("result", "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        data = json.loads(text)
        return data.get("reply_text")

    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"[bridge] Reply generation failed: {e}")
        return None


def search_lessie(tweet: AnalyzedTweet) -> PreparedReply | None:
    """Search Lessie with rich context and generate personalized reply."""
    search_data = json.loads(tweet.search_query)

    # 1. Search Lessie
    lessie_result = _call_lessie(search_data)
    if not lessie_result or not lessie_result.get("success"):
        print(f"[bridge] No results for tweet {tweet.tweet_id}")
        return None

    search_id = lessie_result["search_id"]
    total_found = lessie_result.get("total_found", 0)
    if total_found == 0:
        return None

    # 2. Build share URL
    lessie_url = f"{LESSIE_SHARE_BASE}/{search_id}"

    # 3. Generate personalized reply
    reply_text = _generate_reply(tweet, search_data, total_found)
    if not reply_text:
        reply_text = f"found {total_found} matches that look solid 👀"

    # 4. Append link
    full_reply = f"{reply_text}\n{lessie_url}"

    return PreparedReply(
        tweet_id=tweet.tweet_id,
        lessie_url=lessie_url,
        reply_text=full_reply,
        confidence=tweet.confidence,
    )
