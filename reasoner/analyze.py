"""LLM intent analysis + author profiling — Owner: Becky"""

import json
import subprocess

from models import ScannedTweet, AnalyzedTweet

INTENT_PROMPT = """You analyze tweets to detect people-search intent.

Given a tweet, determine if this person genuinely needs help finding someone.
Respond in JSON only, no markdown:
{
  "has_intent": true/false,
  "intent": "hiring" | "looking_for" | "recommendation",
  "confidence": 0.0-1.0,
  "raw_need": "one sentence: what they need in plain language"
}

If the tweet is venting, joking, or not a real request, set has_intent=false."""


PROFILE_PROMPT = """You are a growth intelligence analyst. You research a Twitter user's
background to understand their context deeply.

Given: their tweet, their bio/profile info, and any web research results.

Extract and infer:
{
  "name": "their name",
  "role": "their job title/role",
  "company": "their company",
  "industry": "their industry/vertical",
  "company_stage": "startup/scaleup/enterprise/unknown",
  "competitors": ["known competitors in their space"],
  "pain_context": "why they're searching — inferred from their role + tweet",
  "platforms_relevant": ["which platforms to search: youtube/tiktok/instagram/twitter/linkedin"],
  "geo_hints": ["locations relevant to their search"]
}

Be specific. Infer aggressively from context clues. If their bio says "Building @Acme"
and Acme is a note-taking app, then competitors = ["Notion", "Obsidian", "Bear"]."""


SEARCH_PROMPT = """You are a master at writing hyper-specific people search prompts.
Your goal: generate a search query so specific that the results feel like magic to the requester.

You'll receive:
- The original tweet (what they asked for)
- Their profile analysis (who they are, their company, industry, competitors)

Generate a Lessie search prompt that is:
1. SPECIFIC — name competitors, platforms, follower ranges, behavioral signals
2. CONTEXTUAL — reference their industry, not generic terms
3. ACTIONABLE — include concrete criteria (follower count, content topics, engagement signals)

Output JSON:
{
  "checkpoint": "The full rich search description (2-3 sentences, like a brief to a researcher)",
  "filter": {
    "person_titles": ["if B2B search"],
    "person_locations": ["if location relevant"],
    "person_seniorities": ["if relevant"],
    "platform": "youtube/tiktok/instagram/twitter (if KOL search)",
    "follower_min": 50000,
    "content_topics": ["topic1", "topic2"]
  },
  "extra": "additional behavioral or contextual requirements not in filter fields",
  "search_mode": "b2b" | "kol",
  "aha_factor": "one line: why this search will impress them"
}

Examples of GREAT checkpoints:
- "Find 10 YouTube/TikTok creators who reviewed Notion or ClickUp, 50k-200k followers, recent videos averaging 20k+ views, with comments showing download/signup intent"
- "Search for LinkedIn thought leaders posting about 'AI Workflow' or 'Solopreneur Tech Stack' with high engagement, bio mentions automation or productivity, recently shared LLM tool experiences"
- "Find Brazilian/Portuguese tech bloggers creating remote work routine or study tool content, showing split-screen workflows or tablet note-taking, in the productivity niche"

Examples of BAD checkpoints (too generic):
- "Find AI engineers in San Francisco"
- "Look for product designers"
- "Search for tech influencers" """


def _call_claude(prompt: str, system: str) -> dict | None:
    """Call Claude CLI and parse JSON response."""
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--system-prompt", system, "--output-format", "json"],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            print(f"[reasoner] Claude CLI error: {result.stderr[:200]}")
            return None

        outer = json.loads(result.stdout)
        text = outer.get("result", "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(text)

    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"[reasoner] Parse error: {e}")
        return None


def _research_author(author: str, tweet_text: str) -> dict:
    """Research the tweet author's background using web search."""
    try:
        result = subprocess.run(
            ["lessie", "web-search", "--query", f"Twitter @{author} bio company role"],
            capture_output=True, text=True, timeout=30
        )
        web_context = result.stdout[:2000] if result.returncode == 0 else ""
    except subprocess.TimeoutExpired:
        web_context = ""

    prompt = (
        f"Tweet by @{author}: \"{tweet_text}\"\n\n"
        f"Web research results:\n{web_context}"
    )
    profile = _call_claude(prompt, PROFILE_PROMPT)
    return profile or {}


def analyze_intent(tweet: ScannedTweet) -> AnalyzedTweet | None:
    """Analyze tweet intent, research author, and generate rich search prompt."""

    # Step 1: Quick intent check
    intent_data = _call_claude(
        f"Tweet by @{tweet.author}: \"{tweet.original_text}\"",
        INTENT_PROMPT,
    )
    if not intent_data or not intent_data.get("has_intent"):
        return None

    confidence = intent_data.get("confidence", 0.0)
    if confidence < 0.7:
        return None

    # Step 2: Research the author's background
    print(f"  [reasoner] Researching @{tweet.author}...")
    profile = _research_author(tweet.author, tweet.original_text)

    # Step 3: Generate rich, customized search prompt
    search_input = (
        f"Original tweet by @{tweet.author}: \"{tweet.original_text}\"\n"
        f"Raw need: {intent_data.get('raw_need', '')}\n\n"
        f"Author profile analysis:\n{json.dumps(profile, indent=2)}"
    )
    search_data = _call_claude(search_input, SEARCH_PROMPT)
    if not search_data:
        return None

    print(f"  [reasoner] Aha factor: {search_data.get('aha_factor', 'N/A')}")

    return AnalyzedTweet(
        tweet_id=tweet.tweet_id,
        author=tweet.author,
        intent=intent_data.get("intent", "looking_for"),
        search_query=json.dumps({
            "filter": search_data.get("filter", {}),
            "checkpoint": search_data.get("checkpoint", ""),
            "extra": search_data.get("extra", ""),
            "search_mode": search_data.get("search_mode", "b2b"),
            "profile": profile,
        }),
        original_text=tweet.original_text,
        confidence=confidence,
    )
