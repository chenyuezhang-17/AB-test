"""
Scanner: Search Twitter for hiring/recommendation intent tweets via TikHub API.
"""
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

TIKHUB_BASE = "https://api.tikhub.io"
TIKHUB_API_KEY = os.getenv("TIKHUB_API_KEY")

INTENT_KEYWORDS = [
    "looking for a developer",
    "anyone recommend a developer",
    "need a frontend developer",
    "need a backend developer",
    "hiring AI engineer",
    "recommend an engineer",
    "looking for cofounder",
    "anyone know a good designer",
    "looking for a data scientist",
    "need a product designer",
]

def search_intent_tweets(keyword: str, max_results: int = 10) -> list[dict]:
    headers = {"Authorization": f"Bearer {TIKHUB_API_KEY}"}
    params = {"keyword": keyword, "search_type": "Latest"}

    with httpx.Client() as client:
        resp = client.get(
            f"{TIKHUB_BASE}/api/v1/twitter/web/fetch_search_timeline",
            headers=headers,
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

    tweets = []
    for item in data.get("data", {}).get("timeline", []):
        if item.get("type") != "tweet":
            continue
        tweets.append({
            "id": item.get("tweet_id"),
            "text": item.get("text", ""),
            "username": item.get("screen_name", "unknown"),
            "created_at": item.get("created_at", ""),
            "metrics": {
                "likes": item.get("favorites", 0),
                "retweets": item.get("retweets", 0),
                "replies": item.get("replies", 0),
                "views": item.get("views", 0),
            },
        })
        if len(tweets) >= max_results:
            break

    return tweets

def scan_all_keywords(max_per_keyword: int = 5) -> list[dict]:
    """Scan all intent keywords and return deduplicated results."""
    seen_ids = set()
    all_tweets = []
    for keyword in INTENT_KEYWORDS:
        try:
            tweets = search_intent_tweets(keyword, max_results=max_per_keyword)
            for t in tweets:
                if t["id"] not in seen_ids:
                    seen_ids.add(t["id"])
                    t["matched_keyword"] = keyword
                    all_tweets.append(t)
        except Exception as e:
            print(f"[scanner] error for keyword '{keyword}': {e}")
    return all_tweets

if __name__ == "__main__":
    print("Scanning for intent tweets...\n")
    tweets = scan_all_keywords(max_per_keyword=3)
    print(f"Found {len(tweets)} tweets\n")
    for t in tweets:
        print(f"@{t['username']}: {t['text'][:120]}")
        print(f"  id={t['id']} | keyword='{t['matched_keyword']}'\n")
