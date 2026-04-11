"""Test the pipeline with fake tweets (no Twitter API needed)."""

from models import ScannedTweet
from reasoner.analyze import analyze_intent
from bridge.search import search_lessie

TEST_TWEETS = [
    ScannedTweet(
        tweet_id="test_001",
        author="founder_jane",
        original_text="Anyone know a good AI engineer in San Francisco? We're hiring for our Series A startup, need someone with LLM experience.",
    ),
    ScannedTweet(
        tweet_id="test_002",
        author="lisahuang",
        original_text="We're launching our productivity app in Brazil next month and need to find local tech YouTubers for reviews. Anyone have contacts?",
    ),
    ScannedTweet(
        tweet_id="test_003",
        author="random_user",
        original_text="AI engineers are so overpaid lmao",
    ),
]


def main():
    print("=" * 60)
    print("Pipeline Test v2 — with author profiling")
    print("=" * 60)

    for tweet in TEST_TWEETS:
        print(f"\n{'='*60}")
        print(f"Tweet by @{tweet.author}:")
        print(f"  \"{tweet.original_text}\"")
        print("-" * 60)

        # Step 1: Reasoner (intent + profile + rich prompt)
        analyzed = analyze_intent(tweet)
        if not analyzed:
            print("  [result] ❌ Filtered out (no intent or low confidence)")
            continue

        import json
        search_data = json.loads(analyzed.search_query)
        print(f"  [reasoner] intent={analyzed.intent}, confidence={analyzed.confidence}")
        print(f"  [reasoner] checkpoint: {search_data.get('checkpoint', 'N/A')}")

        # Step 2: Bridge (Lessie search + reply — costs 20 credits)
        print(f"  [bridge] Searching Lessie...")
        reply = search_lessie(analyzed)
        if not reply:
            print("  [result] ❌ No results or reply failed")
            continue

        print(f"\n  [result] ✅ REPLY READY:")
        print(f"  {reply.reply_text}")


if __name__ == "__main__":
    main()
