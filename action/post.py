"""Tweet posting — Owner: Alexia"""

import os
import random
import tweepy
from dotenv import load_dotenv
from models import PreparedReply

load_dotenv()

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

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

def post_reply(reply: PreparedReply) -> bool:
    """Post a quote repost reply to the original tweet."""
    if reply.confidence < 0.7:
        print(f"[action] skipping tweet {reply.tweet_id} (confidence {reply.confidence:.2f})")
        return False

    text = _build_text(reply)

    if DRY_RUN:
        print(f"[action][DRY RUN] would post:\n{text}\n")
        return True

    try:
        client = _get_client()
        response = client.create_tweet(text=text)
        print(f"[action] posted: https://twitter.com/alliiexia/status/{response.data['id']}")
        return True
    except Exception as e:
        print(f"[action] failed to post: {e}")
        return False
