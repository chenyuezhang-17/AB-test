"""Twitter data fetching — Owner: Alexia"""

import os
import httpx
from dotenv import load_dotenv
from models import ScannedTweet

load_dotenv()

TIKHUB_BASE = "https://api.tikhub.io"

def scan_tweets() -> list[ScannedTweet]:
    """Fetch tweets matching intent keywords from Twitter API via TikHub."""
    api_key = os.getenv("TIKHUB_API_KEY")
    keywords_raw = os.getenv("SCAN_KEYWORDS", ",".join([
        # hiring
        "hiring AI engineer", "we are hiring", "join our team", "open role",
        # cofounder / collaborator
        "looking for cofounder", "looking for co-founder", "need a technical cofounder", "seeking collaborator",
        # expert / consultant / advisor
        "looking for an advisor", "need an expert in", "looking for a consultant", "need someone who knows",
        "anyone know a good", "can anyone recommend a",
        # KOL / creator
        "looking for creators", "looking for influencers", "seeking brand ambassadors", "collab with us",
        # investor
        "looking for investors", "raising a round", "seeking angel investors", "looking for VCs",
        # talent scouting
        "who are the best", "who builds the best", "know anyone who specializes in",
        # freelance / project
        "looking for a freelancer", "need someone to build", "looking for agency",
    ]))
    keywords = [k.strip() for k in keywords_raw.split(",")]

    seen_ids = set()
    results = []

    with httpx.Client() as client:
        for keyword in keywords:
            try:
                resp = client.get(
                    f"{TIKHUB_BASE}/api/v1/twitter/web/fetch_search_timeline",
                    headers={"Authorization": f"Bearer {api_key}"},
                    params={"keyword": keyword, "search_type": "Latest"},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("data", {}).get("timeline", []):
                    if item.get("type") != "tweet":
                        continue
                    tweet_id = item.get("tweet_id")
                    if tweet_id in seen_ids:
                        continue
                    seen_ids.add(tweet_id)
                    results.append(ScannedTweet(
                        tweet_id=tweet_id,
                        author=item.get("screen_name", "unknown"),
                        original_text=item.get("text", ""),
                        author_bio=item.get("user_description", item.get("bio", "")),
                    ))
            except Exception as e:
                print(f"[scanner] error for '{keyword}': {e}")

    return results
