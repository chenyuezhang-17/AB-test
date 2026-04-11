"""Lessie API integration — Owner: Becky"""

from models import AnalyzedTweet, PreparedReply


def search_lessie(tweet: AnalyzedTweet) -> PreparedReply | None:
    """Search Lessie with extracted query and generate reply with share link.

    Returns PreparedReply with Lessie URL and tweet copy, None if no good results.
    """
    # TODO(becky): implement Lessie API call
    # - Call Lessie search with tweet.search_query
    # - Generate share link from results
    # - Craft reply text in "Alex" persona
    # - Return PreparedReply
    raise NotImplementedError("Becky: implement Lessie search + reply generation")
