"""
Scene 1: Trend-Jacking Auto-Posting Pipeline
Fetch trends → Convert to search → Lessie search + share link → Post original tweet
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

from scanner.trends import scan_trends
from bridge.search import _call_lessie_cli, _create_share_link
from action.browser_post import post_tweet_browser

load_dotenv()

DB_PATH = Path(__file__).parent / "activity.db"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"


def _log(stage, topic=None, status=None, detail=None):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS activity_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, stage TEXT, tweet_id TEXT, "
        "author TEXT, tweet_text TEXT, intent TEXT, confidence REAL, "
        "lessie_url TEXT, status TEXT, detail TEXT)"
    )
    conn.execute(
        "INSERT INTO activity_log (ts,stage,tweet_text,status,detail) VALUES (?,?,?,?,?)",
        (datetime.now(timezone.utc).isoformat(), stage, topic, status, detail)
    )
    conn.commit()
    conn.close()


def run_trend_pipeline():
    print("=" * 60)
    print("Scene 1: Trend-Jacking Auto-Posting")
    print("=" * 60)

    # 1. Scan trends
    trends = scan_trends()
    print(f"\n[pipeline] {len(trends)} postable trends found")

    for trend in trends:
        topic = trend["topic"]
        hook = trend["tweet_hook"]
        checkpoint = trend["search_prompt"]

        print(f"\n--- {topic} ---")
        _log("trend_scan", topic=topic[:200], status="found")

        # 2. Search Lessie via CLI
        search_data = {
            "filter": trend.get("filter", {}),
            "checkpoint": checkpoint,
            "extra": "",
            "search_mode": trend.get("search_mode", "b2b"),
        }

        print(f"[pipeline] Searching Lessie...")
        lessie_result = _call_lessie_cli(search_data)
        if not lessie_result or not lessie_result.get("success"):
            print(f"[pipeline] ❌ Search failed, skipping")
            _log("trend_search", topic=topic[:200], status="failed")
            continue

        total = lessie_result.get("total_found", 0)
        if total == 0:
            print(f"[pipeline] ❌ 0 results, skipping")
            continue

        print(f"[pipeline] Found {total} people")

        # 3. Create share link
        print(f"[pipeline] Creating share link...")
        share_url = _create_share_link(checkpoint)
        if not share_url:
            share_url = "https://lessie.ai"
            print(f"[pipeline] ⚠️ Share link failed, using fallback")

        # 4. Compose and post original tweet
        tweet_text = f"{hook}\n\n{share_url}"

        if DRY_RUN:
            print(f"[pipeline] [DRY RUN] Would post:")
            print(f"  {tweet_text}")
            _log("trend_post", topic=topic[:200], status="dry_run", detail=tweet_text[:500])
        else:
            try:
                post_tweet_browser(tweet_text)
                print(f"[pipeline] posted via browser")
                _log("trend_post", topic=topic[:200], status="posted", detail=tweet_text[:500])
            except Exception as e:
                print(f"[pipeline] ❌ Post failed: {e}")
                _log("trend_post", topic=topic[:200], status="failed", detail=str(e)[:200])

    print(f"\n{'='*60}")
    print(f"Done. Processed {len(trends)} trends.")


if __name__ == "__main__":
    run_trend_pipeline()
