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
    keywords_raw = os.getenv("SCAN_KEYWORDS", "looking for a developer,hiring AI engineer,need a frontend developer,recommend an engineer,looking for cofounder")
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
