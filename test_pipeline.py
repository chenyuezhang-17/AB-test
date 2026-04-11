"""Test the pipeline with fake tweets (no Twitter API needed)."""

from models import ScannedTweet
from reasoner.analyze import analyze_intent
from bridge.search import search_lessie

TEST_TWEETS = [
    ScannedTweet(
        tweet_id="test_001",
        author="toaborhese",
        original_text="Looking for a senior AI/ML engineer to join our team. Must have experience with LLMs and retrieval systems. Remote OK, US-based preferred. DM me.",
        author_bio="CTO @DataflowLabs | Building AI-powered search | Ex-Google | Stanford CS",
        recent_tweets=[
            "Just shipped our new RAG pipeline — 3x faster retrieval with hybrid search 🚀",
            "Hiring is so hard in this market. Every good ML engineer has 5 offers.",
            "Great talk at NeurIPS on sparse attention mechanisms",
            "Our Series A is closing next month. Exciting times at @DataflowLabs",
            "Been experimenting with Anthropic's Claude for structured extraction. Impressive.",
            "Anyone else frustrated with vector DB pricing? We're evaluating Qdrant vs Pinecone",
        ],
    ),
    ScannedTweet(
        tweet_id="test_002",
        author="lenaboroditsky",
        original_text="Anyone know content creators who focus on language learning tools? We need reviewers for our new translation feature launch in Latin America.",
        author_bio="Head of Growth @LinguaFlow | Language tech | Previously @Duolingo | 🇧🇷🇺🇸",
        recent_tweets=[
            "Our Portuguese user base grew 40% last quarter 🇧🇷",
            "Duolingo's new AI features are interesting but miss the mark for advanced learners",
            "Looking at TikTok as a channel for LatAm. The edutech creators there are incredible.",
            "Just got back from São Paulo. The language learning market in Brazil is massive.",
            "We're launching AI-powered real-time translation in 3 weeks. Need beta testers!",
            "Hot take: the best language learning happens through content consumption, not drills",
        ],
    ),
]


def main():
    print("=" * 60)
    print("Pipeline Test v3 — with tweet history profiling")
    print("=" * 60)

    for tweet in TEST_TWEETS:
        print(f"\n{'='*60}")
        print(f"Tweet by @{tweet.author}:")
        print(f"  \"{tweet.original_text}\"")
        print(f"  Bio: {tweet.author_bio}")
        print("-" * 60)

        # Step 1: Reasoner
        analyzed = analyze_intent(tweet)
        if not analyzed:
            print("  [result] ❌ Filtered out")
            continue

        import json
        search_data = json.loads(analyzed.search_query)
        print(f"  [reasoner] framework={search_data.get('framework', '?')}, intent={analyzed.intent}")
        print(f"  [reasoner] checkpoint: {search_data.get('checkpoint', 'N/A')[:200]}...")

        # Step 2: Bridge
        print(f"  [bridge] Searching Lessie...")
        reply = search_lessie(analyzed)
        if not reply:
            print("  [result] ❌ No results or reply failed")
            continue

        print(f"\n  [result] ✅ REPLY READY:")
        print(f"  {reply.reply_text}")


if __name__ == "__main__":
    main()
