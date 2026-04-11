"""LLM intent analysis + author profiling — Owner: Becky

Pipeline:
1. claude -p → intent detection (is this a real people-search request?)
2. lessie enrich-people + enrich-org → author profile (real data, not guessing)
3. claude -p → framework selection + rich prompt generation (4 frameworks from Becky)
4. Output: structured search params for bridge module
"""

import json
import re
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


PROFILE_PROMPT = """You are a growth intelligence analyst. Given a Twitter user's tweet,
their bio, and their Lessie enrichment data (professional background, company info),
synthesize a profile.

Respond in JSON only, no markdown:
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

Be specific. If enrichment data shows they work at a note-taking startup,
competitors = ["Notion", "Obsidian", "Bear"]. Use the REAL data, don't guess."""


SEARCH_PROMPT = """You are a master at writing hyper-specific people search prompts.
Your goal: generate a search query so specific that the results feel like magic.

You'll receive: the original tweet, their profile (with real LinkedIn/company data from Lessie).

## Pick the best framework:

### A: 竞品平替 (Competitor Replacement)
When they have a product and need creators/people in that space.
Search for people who engage with their COMPETITORS, not generic terms.

### B: 精准痛点 (Precise Pain Point)
When the tweet reveals a specific workflow problem or hiring need.
Target exact behavioral signals, tools mentioned, or complaint keywords.

### C: 高转化 KOC (High-Conversion Micro-Influencer)
When they need niche experts with high engagement, not big names.
Focus on engagement rate, bio keywords, authentic tool experience.

### D: 跨境出海 (Cross-Border / Localization)
When expanding to a new market. Find bilingual/cross-cultural creators
who bridge two language markets.

## Output JSON only, no markdown:
{
  "framework": "A" | "B" | "C" | "D",
  "checkpoint": "2-3 sentence search brief packed with specifics (competitor names, platforms, follower ranges, behavioral signals)",
  "filter": {
    "person_titles": ["if B2B"],
    "person_locations": ["if relevant"],
    "person_seniorities": ["if relevant"],
    "platform": "youtube/tiktok/instagram/twitter (if KOL)",
    "follower_min": 50000,
    "content_topics": ["topic1"]
  },
  "extra": "behavioral signals, engagement criteria — max 200 chars",
  "search_mode": "b2b" | "kol",
  "aha_factor": "one line: why this will impress them"
}"""


def _call_claude(prompt: str, system: str) -> dict | None:
    """Call Claude CLI and parse JSON response."""
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--system-prompt", system,
             "--output-format", "json", "--model", "sonnet"],
            capture_output=True, text=True, timeout=90
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


def _research_author(tweet: ScannedTweet) -> dict:
    """Research author via Lessie enrich APIs, then synthesize with Claude."""

    # 1. Enrich person via Twitter username (KOL path, 1 credit)
    person_raw = ""
    try:
        result = subprocess.run(
            ["lessie", "enrich-people",
             "--people", json.dumps([{"twitter_screen_name": tweet.author}])],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            person_raw = result.stdout[:1500]
    except subprocess.TimeoutExpired:
        pass

    # 2. If bio mentions a company, try to enrich it (1 credit)
    company_raw = ""
    if tweet.author_bio:
        companies = re.findall(r"@(\w+)", tweet.author_bio)
        if companies:
            try:
                result = subprocess.run(
                    ["lessie", "find-orgs", "--name", companies[0]],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    orgs = json.loads(result.stdout).get("organizations", [])
                    if orgs:
                        domain = orgs[0].get("primary_domain", "")
                        if domain:
                            result2 = subprocess.run(
                                ["lessie", "enrich-org", "--domains", domain],
                                capture_output=True, text=True, timeout=30
                            )
                            if result2.returncode == 0:
                                company_raw = result2.stdout[:1500]
            except (subprocess.TimeoutExpired, json.JSONDecodeError):
                pass

    # 3. Synthesize with Claude
    prompt = (
        f"Tweet by @{tweet.author}: \"{tweet.original_text}\"\n"
        f"Bio: {tweet.author_bio or 'N/A'}\n\n"
        f"Lessie person enrichment:\n{person_raw or 'No data'}\n\n"
        f"Lessie company enrichment:\n{company_raw or 'No data'}"
    )
    return _call_claude(prompt, PROFILE_PROMPT) or {}


def analyze_intent(tweet: ScannedTweet) -> AnalyzedTweet | None:
    """Analyze tweet intent, research author, generate rich search prompt."""

    # Step 1: Intent check
    intent_data = _call_claude(
        f"Tweet by @{tweet.author}: \"{tweet.original_text}\"",
        INTENT_PROMPT,
    )
    if not intent_data or not intent_data.get("has_intent"):
        return None

    confidence = intent_data.get("confidence", 0.0)
    if confidence < 0.7:
        return None

    # Step 2: Research author via Lessie enrich (real data)
    print(f"  [reasoner] Enriching @{tweet.author} via Lessie...")
    profile = _research_author(tweet)
    if not profile:
        profile = {"name": tweet.author, "role": "unknown", "company": "unknown"}

    # Step 3: Generate rich search prompt with frameworks
    search_input = (
        f"Original tweet by @{tweet.author}: \"{tweet.original_text}\"\n"
        f"Raw need: {intent_data.get('raw_need', '')}\n\n"
        f"Author profile (from real Lessie data):\n{json.dumps(profile, indent=2)}"
    )
    search_data = _call_claude(search_input, SEARCH_PROMPT)
    if not search_data:
        return None

    print(f"  [reasoner] Framework: {search_data.get('framework', '?')}")
    print(f"  [reasoner] Aha: {search_data.get('aha_factor', 'N/A')}")

    return AnalyzedTweet(
        tweet_id=tweet.tweet_id,
        author=tweet.author,
        intent=intent_data.get("intent", "looking_for"),
        search_query=json.dumps({
            "filter": search_data.get("filter", {}),
            "checkpoint": search_data.get("checkpoint", ""),
            "extra": search_data.get("extra", "")[:300],
            "search_mode": search_data.get("search_mode", "b2b"),
            "profile": profile,
        }),
        original_text=tweet.original_text,
        confidence=confidence,
    )
