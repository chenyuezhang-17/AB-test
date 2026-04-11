"""
Twitter Digital Employee Pipeline
Scanner → Reasoner → Bridge → Action
"""

import os
from dotenv import load_dotenv

from scanner.fetch import scan_tweets
from reasoner.analyze import analyze_intent
from bridge.search import search_lessie
from action.post import post_reply

load_dotenv()


def run_pipeline():
    # 1. Scan Twitter for relevant tweets
    tweets = scan_tweets()
    print(f"[scanner] Found {len(tweets)} tweets")

    # 2. Analyze intent with LLM
    analyzed = []
    for tweet in tweets:
        result = analyze_intent(tweet)
        if result and result.confidence >= 0.7:
            analyzed.append(result)
    print(f"[reasoner] {len(analyzed)} tweets passed intent filter")

    # 3. Search Lessie and prepare replies
    replies = []
    for tweet in analyzed:
        reply = search_lessie(tweet)
        if reply:
            replies.append(reply)
    print(f"[bridge] {len(replies)} replies prepared")

    # 4. Post replies
    for reply in replies:
        post_reply(reply)
    print(f"[action] {len(replies)} replies posted")


if __name__ == "__main__":
    run_pipeline()
