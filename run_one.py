"""
One-shot test: post 1 reply (Scene 2) + 1 trend tweet (Scene 1).
"""
import os
import json
from dotenv import load_dotenv

load_dotenv()

# Make sure lessie CLI is on PATH
nvm_bin = os.path.expanduser("~/.nvm/versions/node/v24.14.1/bin")
os.environ["PATH"] = nvm_bin + ":" + os.environ.get("PATH", "")

from scanner.fetch import scan_tweets
from reasoner.analyze import analyze_intent
from bridge.search import search_lessie
from action.post import post_reply

from scanner.trends import scan_trends
from bridge.search import _create_share_link
from action.main import post_quote_retweet

DRY_RUN = False  # REAL posting

print("=" * 60)
print("Scene 2: Reply to 1 tweet with hiring intent")
print("=" * 60)

tweets = scan_tweets()
print(f"[scanner] {len(tweets)} tweets found")

posted_reply = False
for tweet in tweets:
    if posted_reply:
        break
    result = analyze_intent(tweet)
    if not result or result.confidence < 0.7:
        continue
    print(f"[reasoner] Matched: @{tweet.author} ({result.intent}, {result.confidence:.2f})")
    reply = search_lessie(result)
    if not reply:
        print("[bridge] No reply generated, trying next...")
        continue
    print(f"[bridge] Reply ready: {reply.reply_text[:100]}...")
    print(f"[bridge] URL: {reply.lessie_url}")
    success = post_reply(reply)
    if success:
        print(f"[action] ✅ Reply posted to @{tweet.author}")
        posted_reply = True

if not posted_reply:
    print("[action] ❌ No reply posted (no matching tweets with results)")

print()
print("=" * 60)
print("Scene 1: Post 1 trend-jacking tweet")
print("=" * 60)

trends = scan_trends()
print(f"[scanner] {len(trends)} trends found")

posted_trend = False
for trend in trends:
    if posted_trend:
        break
    topic = trend["topic"]
    hook = trend["tweet_hook"]
    checkpoint = trend["search_prompt"]
    print(f"[trend] Topic: {topic}")
    print(f"[trend] Creating share link...")
    share_url = _create_share_link(checkpoint)
    if not share_url:
        print("[trend] Share link failed, trying next...")
        continue
    tweet_text = f"{hook}\n\n{share_url}"
    print(f"[trend] Posting: {tweet_text[:120]}...")
    try:
        post_quote_retweet(tweet_id="", reply_text=tweet_text, dry_run=DRY_RUN)
        print(f"[action] ✅ Trend tweet posted")
        posted_trend = True
    except Exception as e:
        print(f"[action] ❌ Failed: {e}")

if not posted_trend:
    print("[action] ❌ No trend tweet posted")
