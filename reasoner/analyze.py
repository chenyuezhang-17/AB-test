"""LLM intent analysis — Owner: Becky"""

from models import ScannedTweet, AnalyzedTweet


def analyze_intent(tweet: ScannedTweet) -> AnalyzedTweet | None:
    """Use Claude CLI to analyze tweet intent and extract search query.

    Returns AnalyzedTweet if the tweet has a clear intent, None otherwise.
    """
    # TODO(becky): implement with claude CLI (subprocess)
    # - Classify intent: hiring / looking_for / recommendation
    # - Extract structured search query from tweet text
    # - Return confidence score
    raise NotImplementedError("Becky: implement intent analysis with Claude CLI")
