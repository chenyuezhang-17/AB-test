"""
Twitter Digital Employee Pipeline
Scanner → Reasoner → Bridge → Action
"""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

from scanner.fetch import scan_tweets
from reasoner.analyze import analyze_intent
from bridge.search import search_lessie
from action.post import post_reply

load_dotenv()

DB_PATH = Path(__file__).parent / "activity.db"

def _log(stage: str, tweet_id=None, author=None, tweet_text=None,
         intent=None, confidence=None, lessie_url=None, status=None, detail=None):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS activity_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, stage TEXT, tweet_id TEXT, "
        "author TEXT, tweet_text TEXT, intent TEXT, confidence REAL, "
        "lessie_url TEXT, status TEXT, detail TEXT)"
    )
    conn.execute(
        "INSERT INTO activity_log (ts,stage,tweet_id,author,tweet_text,intent,confidence,lessie_url,status,detail) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (datetime.now(timezone.utc).isoformat(), stage, tweet_id, author,
         tweet_text, intent, confidence, lessie_url, status, detail)
    )
    conn.commit()
    conn.close()

def run_pipeline():
    # 1. Scan Twitter for relevant tweets
    tweets = scan_tweets()
    print(f"[scanner] Found {len(tweets)} tweets")
    for t in tweets:
        _log("scanner", tweet_id=t.tweet_id, author=t.author, tweet_text=t.original_text[:200])

    # 2. Analyze intent with LLM
    analyzed = []
    for tweet in tweets:
        result = analyze_intent(tweet)
        if result:
            status = "passed" if result.confidence >= 0.9 else "filtered"
            _log("reasoner", tweet_id=tweet.tweet_id, author=tweet.author,
                 tweet_text=tweet.original_text[:200], intent=result.intent,
                 confidence=result.confidence, status=status)
            if result.confidence >= 0.9:
                analyzed.append(result)
    print(f"[reasoner] {len(analyzed)} tweets passed intent filter")

    # 3. Search Lessie and prepare replies
    replies = []
    for tweet in analyzed:
        reply = search_lessie(tweet)
        if reply:
            _log("bridge", tweet_id=tweet.tweet_id, author=tweet.author,
                 lessie_url=reply.lessie_url, status="ready")
            replies.append(reply)
    print(f"[bridge] {len(replies)} replies prepared")

    # 4. Post replies
    for reply in replies:
        success = post_reply(reply)
        _log("action", tweet_id=reply.tweet_id, lessie_url=reply.lessie_url,
             status="posted" if success else "failed")
    print(f"[action] {len(replies)} replies posted")


if __name__ == "__main__":
    run_pipeline()
