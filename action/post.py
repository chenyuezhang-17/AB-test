"""Tweet posting — Owner: Alexia

Anti-spam safety (P0):
1. Non-templated replies — each generated uniquely by LLM
2. Dynamic Lessie share links — unique search ID per reply, not fixed URLs
3. Human-like rate limiting — random intervals + daily cap
"""

import os
import random
import time
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import tweepy
from dotenv import load_dotenv
from models import PreparedReply

load_dotenv()

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
DAILY_POST_LIMIT = int(os.getenv("DAILY_POST_LIMIT", "20"))
MIN_INTERVAL_SEC = int(os.getenv("MIN_INTERVAL_SEC", "60"))
MAX_INTERVAL_SEC = int(os.getenv("MAX_INTERVAL_SEC", "300"))
DB_PATH = Path(__file__).parent.parent / "activity.db"

_last_post_time = 0.0

def _get_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.getenv("TWITTER_API_KEY"),
        consumer_secret=os.getenv("TWITTER_API_SECRET"),
        access_token=os.getenv("TWITTER_ACCESS_TOKEN"),
        access_token_secret=os.getenv("TWITTER_ACCESS_TOKEN_SECRET"),
    )

def _build_text(reply: PreparedReply) -> str:
    """Use bridge's personalized reply_text if available, fallback to template."""
    tweet_url = f"https://twitter.com/i/web/status/{reply.tweet_id}"

    # Bridge generates customized reply_text with lessie_url already appended
    if reply.reply_text and reply.lessie_url in reply.reply_text:
        return reply.reply_text

    # Fallback: use bridge text + append tweet URL for quote repost
    if reply.reply_text:
        return f"{reply.reply_text}\n{tweet_url}"

    # Last resort: generic template
    templates = [
        f"ran a search on Lessie — pulled a few solid profiles worth checking 👇\n{reply.lessie_url}",
        f"found some matches on Lessie — saved you a few hours of LinkedIn rabbit holes\n{reply.lessie_url}",
        f"built a list on Lessie for this, quality > quantity\n{reply.lessie_url}",
    ]
    return random.choice(templates)

def _check_daily_limit() -> bool:
    """Check if we've hit the daily post limit."""
    try:
        conn = sqlite3.connect(DB_PATH)
        today = datetime.now().strftime("%Y-%m-%d")
        count = conn.execute(
            "SELECT COUNT(*) FROM activity_log WHERE stage='action' AND status='posted' AND ts LIKE ?",
            (f"{today}%",)
        ).fetchone()[0]
        conn.close()
        return count < DAILY_POST_LIMIT
    except Exception:
        return True  # fail open on DB error


def _wait_human_interval():
    """Sleep a random interval to mimic human posting rhythm."""
    global _last_post_time
    now = time.time()
    elapsed = now - _last_post_time
    if _last_post_time > 0 and elapsed < MIN_INTERVAL_SEC:
        wait = random.uniform(MIN_INTERVAL_SEC, MAX_INTERVAL_SEC)
        print(f"[action] rate limit: waiting {wait:.0f}s (human-like interval)")
        time.sleep(wait)
    _last_post_time = time.time()


def post_reply(reply: PreparedReply) -> bool:
    """Post a quote repost reply to the original tweet."""
    if reply.confidence < 0.9:
        print(f"[action] skipping tweet {reply.tweet_id} (confidence {reply.confidence:.2f})")
        return False

    if not _check_daily_limit():
        print(f"[action] daily limit reached ({DAILY_POST_LIMIT} posts), skipping")
        return False

    text = _build_text(reply)

    if DRY_RUN:
        print(f"[action][DRY RUN] would post:\n{text}\n")
        return True

    _wait_human_interval()

    try:
        client = _get_client()
        response = client.create_tweet(text=text)
        print(f"[action] posted: https://twitter.com/alliiexia/status/{response.data['id']}")
        return True
    except Exception as e:
        print(f"[action] failed to post: {e}")
        return False
