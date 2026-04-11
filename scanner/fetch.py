"""Twitter data fetching — Owner: Alexia"""

from models import ScannedTweet


def scan_tweets() -> list[ScannedTweet]:
    """Fetch tweets matching intent keywords from Twitter API."""
    # TODO(alexia): implement with tweepy
    # - Use keywords from SCAN_KEYWORDS env var
    # - Filter by recency (last SCAN_INTERVAL_SECONDS)
    # - Return list of ScannedTweet
    raise NotImplementedError("Alexia: implement Twitter API scanning")
