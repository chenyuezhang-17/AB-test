"""Lessie API integration — Owner: Becky

Two search paths:
1. lessie CLI (find-people) — fast, structured results
2. Lessie Web API (chat/stream) — creates conversation with share link

We use CLI for search, then Web API to create a shareable conversation + link.
"""

import json
import os
import subprocess
import httpx
from datetime import datetime, timezone

from models import AnalyzedTweet, PreparedReply

LESSIE_APP = "https://app.lessie.ai"
LESSIE_JWT = os.getenv("LESSIE_JWT", "")

REPLY_SYSTEM_PROMPT = """You are Leego, a growth hacker at Lessie AI. You write tweet replies.

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


def _create_share_link(checkpoint: str) -> str | None:
    """Create a Lessie web conversation and return a public share link.

    1. POST to chat/stream with the search query → get conversation_id
    2. POST to shares/v1 → get share_id
    3. Return https://app.lessie.ai/share/{share_id}
    """
    jwt = LESSIE_JWT
    if not jwt:
        print("[bridge] No LESSIE_JWT configured, cannot create share link")
        return None

    headers = {
        "Cookie": f"Authorization={jwt}",
        "Content-Type": "application/json",
        "Origin": LESSIE_APP,
    }

    # Step 1: Create conversation via stream
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    stream_body = {
        "messages": [{
            "role": "user",
            "content": checkpoint,
            "id": f"msg_{int(datetime.now().timestamp())}",
            "parts": [{"type": "text", "text": checkpoint}],
            "peosonList": [],
            "createdAt": now,
        }],
        "payload": {"task_id": "", "person_info_list": []},
        "id": f"conv_{int(datetime.now().timestamp())}",
    }

    conversation_id = None
    try:
        with httpx.Client(timeout=120) as client:
            with client.stream(
                "POST",
                f"{LESSIE_APP}/sourcing-api/chat/v1/stream",
                headers=headers,
                json=stream_body,
            ) as response:
                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        data = json.loads(line[6:])
                        if "conversation_id" in data:
                            conversation_id = data["conversation_id"]
                            break
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        print(f"[bridge] Stream failed: {e}")
        return None

    if not conversation_id:
        print("[bridge] No conversation_id from stream")
        return None

    print(f"[bridge] Conversation created: {conversation_id}")

    # Step 2: Wait for search to complete (stream is still running)
    # We just need the conversation_id, the search runs server-side

    # Step 3: Create public share link
    try:
        resp = httpx.post(
            f"{LESSIE_APP}/sourcing-api/shares/v1",
            headers=headers,
            json={"conversation_id": conversation_id, "access_permission": 2},
            timeout=30,
        )
        share_data = resp.json()
        if share_data.get("code") == 200:
            share_id = share_data["data"]["share_id"]
            return f"{LESSIE_APP}/share/{share_id}"
    except Exception as e:
        print(f"[bridge] Share creation failed: {e}")

    return None


def _call_lessie_cli(search_data: dict) -> dict | None:
    """Call lessie find-people CLI for structured results."""
    filter_obj = search_data.get("filter", {})
    checkpoint = search_data.get("checkpoint", "search")
    extra = search_data.get("extra", "")
    mode = search_data.get("search_mode", "b2b")

    lessie_filter = {}
    if mode == "kol":
        if filter_obj.get("platform"):
            lessie_filter["platform"] = filter_obj["platform"]
        if filter_obj.get("follower_min"):
            lessie_filter["follower_min"] = filter_obj["follower_min"]
        if filter_obj.get("content_topics"):
            lessie_filter["content_topics"] = filter_obj["content_topics"][:3]
    else:
        if filter_obj.get("person_titles"):
            lessie_filter["person_titles"] = filter_obj["person_titles"]
        if filter_obj.get("person_locations"):
            lessie_filter["person_locations"] = filter_obj["person_locations"]
        if filter_obj.get("person_seniorities"):
            lessie_filter["person_seniorities"] = filter_obj["person_seniorities"]

    if not lessie_filter:
        lessie_filter["person_titles"] = ["professional"]

    if "platform" in lessie_filter and "," in str(lessie_filter["platform"]):
        lessie_filter["platform"] = lessie_filter["platform"].split(",")[0].strip()

    cmd = [
        "lessie", "find-people",
        "--filter", json.dumps(lessie_filter),
        "--checkpoint", checkpoint[:300],
        "--strategy", "hybrid" if mode == "kol" else "saas_only",
        "--target-count", "10",
    ]
    if extra:
        cmd.extend(["--extra", extra[:150]])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            print(f"[bridge] Lessie CLI error: {result.stderr[:200]}")
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"[bridge] Lessie CLI failed: {e}")
        return None


def _generate_reply(tweet: AnalyzedTweet, search_data: dict, total_found: int) -> str | None:
    """Generate a personalized reply using Claude CLI."""
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
            ["claude", "-p", prompt, "--system-prompt", REPLY_SYSTEM_PROMPT,
             "--output-format", "json", "--model", "sonnet"],
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
    """Search Lessie and generate personalized reply with share link."""
    search_data = json.loads(tweet.search_query)
    checkpoint = search_data.get("checkpoint", "")

    # 1. Search via CLI (fast, structured results)
    lessie_result = _call_lessie_cli(search_data)
    total_found = 0
    if lessie_result and lessie_result.get("success"):
        total_found = lessie_result.get("total_found", 0)

    if total_found == 0:
        print(f"[bridge] No results for tweet {tweet.tweet_id}")
        return None

    # 2. Create share link via Web API (uses the same checkpoint query)
    print(f"[bridge] Creating share link...")
    lessie_url = _create_share_link(checkpoint)
    if not lessie_url:
        lessie_url = "https://lessie.ai"  # fallback to homepage
        print(f"[bridge] Share link failed, using fallback URL")

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
