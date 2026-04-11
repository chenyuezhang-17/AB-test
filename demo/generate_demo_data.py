"""Generate static demo data: run pipeline on curated tweets, save results."""

import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import ScannedTweet
from reasoner.analyze import analyze_intent
from bridge.search import search_lessie

DEMO_TWEETS = [
    ScannedTweet(
        tweet_id="demo_001",
        author="toaborhese",
        original_text="Looking for a senior AI/ML engineer to join our team. Must have experience with LLMs and retrieval systems. Remote OK, US-based preferred. DM me.",
        author_bio="CTO @DataflowLabs | Building AI-powered search | Ex-Google | Stanford CS",
    ),
    ScannedTweet(
        tweet_id="demo_002",
        author="lenaboroditsky",
        original_text="Anyone know content creators who focus on language learning tools? We need reviewers for our new translation feature launch in Latin America.",
        author_bio="Head of Growth @LinguaFlow | Language tech | Previously @Duolingo",
    ),
    ScannedTweet(
        tweet_id="demo_003",
        author="marcustech_",
        original_text="Hiring a product designer for our fintech startup. Need someone who's worked on payment flows and compliance UX. NYC preferred but open to remote.",
        author_bio="CEO @PayStack | YC W24 | Building the Stripe for Africa",
    ),
]

def main():
    results = []

    for tweet in DEMO_TWEETS:
        print(f"\n{'='*60}")
        print(f"Processing @{tweet.author}...")

        entry = {
            "tweet_id": tweet.tweet_id,
            "author": tweet.author,
            "author_bio": tweet.author_bio,
            "original_text": tweet.original_text,
            "pipeline_result": None,
            "generic_search": f"title: {tweet.original_text.split('.')[0]}",
        }

        analyzed = analyze_intent(tweet)
        if not analyzed:
            entry["pipeline_result"] = {"status": "filtered", "reason": "no intent"}
            results.append(entry)
            continue

        search_data = json.loads(analyzed.search_query)
        entry["pipeline_result"] = {
            "status": "analyzed",
            "intent": analyzed.intent,
            "confidence": analyzed.confidence,
            "framework": search_data.get("framework", "?"),
            "checkpoint": search_data.get("checkpoint", ""),
            "aha_factor": search_data.get("aha_factor", ""),
            "profile": search_data.get("profile", {}),
        }

        reply = search_lessie(analyzed)
        if reply:
            entry["pipeline_result"]["reply_text"] = reply.reply_text
            entry["pipeline_result"]["lessie_url"] = reply.lessie_url
            entry["pipeline_result"]["status"] = "ready"

        results.append(entry)
        print(f"  Done: {entry['pipeline_result']['status']}")

    # Save
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_data.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Saved {len(results)} demo entries to {out_path}")


if __name__ == "__main__":
    main()
