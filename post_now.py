"""
Direct post: pick one tweet from DB, run reasoner→bridge→action only.
No scanner, no full pipeline.
"""
import os
os.environ["PATH"] = os.path.expanduser("~/.nvm/versions/node/v24.14.1/bin") + ":" + os.environ.get("PATH", "")

from dotenv import load_dotenv
load_dotenv()

from models import ScannedTweet
from reasoner.analyze import analyze_intent
from bridge.search import search_lessie
from action.post import post_reply

# Scene 2: one tweet from reasoner results
tweet = ScannedTweet(
    tweet_id="2040003697489703203",
    author="Rubab_Mentor",
    original_text="Looking for a frontend developer \n\nPay rate - $7000/project\n@rubab_mentor",
    author_bio="",
)

print("=" * 60)
print("Scene 2: Reply pipeline — 1 tweet")
print("=" * 60)
print(f"Tweet: @{tweet.author}: {tweet.original_text[:80]}")

result = analyze_intent(tweet)
if result:
    print(f"[reasoner] intent={result.intent} confidence={result.confidence:.2f}")
    reply = search_lessie(result)
    if reply:
        print(f"[bridge] reply={reply.reply_text[:100]}")
        print(f"[bridge] url={reply.lessie_url}")
        success = post_reply(reply)
        print(f"[action] {'✅ posted' if success else '❌ failed'}")
    else:
        print("[bridge] ❌ no reply generated")
else:
    print("[reasoner] ❌ no intent detected")

# Scene 1: trend-jacking — post 1 original tweet
print()
print("=" * 60)
print("Scene 1: Trend-jacking — 1 original tweet")
print("=" * 60)

from scanner.trends import scan_trends
from bridge.search import _create_share_link
from action.browser_post import post_tweet_browser

trends = scan_trends()
print(f"[scanner] {len(trends)} trends found")

for trend in trends:
    print(f"[trend] {trend['topic']}")
    share_url = _create_share_link(trend["search_prompt"])
    if not share_url:
        print("[bridge] no share link, skip")
        continue
    tweet_text = f"{trend['tweet_hook']}\n\n{share_url}"
    print(f"[action] posting: {tweet_text[:120]}")
    try:
        post_tweet_browser(tweet_text)
        print("[action] ✅ posted")
    except Exception as e:
        print(f"[action] ❌ {e}")
    break
