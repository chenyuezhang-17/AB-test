"""
Action: Post quote retweets on Twitter as @alliiexia (Alex persona).
Uses OAuth 1.0a for user-context posting.
"""
import os
import tweepy
from dotenv import load_dotenv

load_dotenv()

def get_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.getenv("TWITTER_API_KEY"),
        consumer_secret=os.getenv("TWITTER_API_SECRET"),
        access_token=os.getenv("TWITTER_ACCESS_TOKEN"),
        access_token_secret=os.getenv("TWITTER_ACCESS_TOKEN_SECRET"),
    )

def post_quote_retweet(tweet_id: str, reply_text: str, dry_run: bool = True) -> dict:
    """
    Post a quote retweet replying to tweet_id with reply_text.
    Set dry_run=False to actually post.
    """
    tweet_url = f"https://twitter.com/i/web/status/{tweet_id}"
    full_text = f"{reply_text}\n\n{tweet_url}"

    if dry_run:
        print(f"[DRY RUN] Would post:\n{full_text}\n")
        return {"dry_run": True, "text": full_text}

    client = get_client()
    response = client.create_tweet(text=full_text)
    tweet_data = response.data
    print(f"Posted tweet: https://twitter.com/alliiexia/status/{tweet_data['id']}")
    return {"id": tweet_data["id"], "text": full_text}

def build_reply_text(username: str, lessie_url: str, role_hint: str = "") -> str:
    """Generate a human-like reply text in Alex's voice."""
    role_part = f" for {role_hint}" if role_hint else ""
    templates = [
        f"ran a search on Lessie{role_part} — pulled a few solid profiles worth checking out 👇\n{lessie_url}",
        f"found some matches{role_part} on Lessie — saved you a few hours of LinkedIn rabbit holes\n{lessie_url}",
        f"@{username} built a list{role_part} on Lessie, quality > quantity here\n{lessie_url}",
    ]
    import random
    return random.choice(templates)

if __name__ == "__main__":
    # Test dry run
    test_text = build_reply_text(
        username="testuser",
        lessie_url="https://lessie.ai/share/test123",
        role_hint="frontend developers",
    )
    post_quote_retweet(
        tweet_id="2042351754805740007",
        reply_text=test_text,
        dry_run=True,
    )
