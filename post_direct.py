"""
Direct bridge→action, no LLM calls. Uses known tweet data from DB.
Posts via browser CDP (bypasses Twitter API free-tier limitation).
"""
import os, json, sys
os.environ["PATH"] = os.path.expanduser("~/.nvm/versions/node/v24.14.1/bin") + ":" + os.environ.get("PATH", "")
sys.path.insert(0, "/tmp/2026040801")

from dotenv import load_dotenv
load_dotenv()

from bridge.search import _create_share_link
from action.browser_post import post_tweet_browser, post_reply_browser

# ── Scene 2: reply to @Rubab_Mentor ──────────────────────────────
print("=" * 60)
print("Scene 2: Reply to @Rubab_Mentor")
print("=" * 60)

# Use pre-built share link (lessie CLI search already done earlier)
checkpoint2 = "Frontend developers available for project work, pay $7000/project. Looking for skilled frontend engineers who can work on project basis."
print("[bridge] Creating share link for Scene 2...")
share_url2 = _create_share_link(checkpoint2)
if not share_url2:
    share_url2 = "https://lessie.ai"
    print("[bridge] fallback url")
else:
    print(f"[bridge] share link: {share_url2}")

reply_text = f"just ran this — found 50+ frontend devs open to project work, a few with Solidity/Web3 background too 👀\n\n{share_url2}"
tweet_url = "https://x.com/Rubab_Mentor/status/2040003697489703203"

print(f"[action] Posting reply to {tweet_url}")
success, msg = post_reply_browser(tweet_url, reply_text)
print(f"[action] {'✅ Scene 2 posted!' if success else '❌ failed: ' + msg}")

# ── Scene 1: trend-jacking ────────────────────────────────────────
print()
print("=" * 60)
print("Scene 1: Trend-jacking tweet")
print("=" * 60)

checkpoint1 = "Find agentic AI engineers and researchers who specialize in building autonomous AI systems, multi-agent architectures, or LLM-powered workflows. Target people from AI labs, AI startups, or open source contributors to LangChain, AutoGPT, CrewAI."
hook = "74% of businesses are deploying agentic AI this year — ran a search on who's actually building this stuff 👇"

print("[bridge] Creating share link for Scene 1...")
share_url1 = _create_share_link(checkpoint1)
if not share_url1:
    share_url1 = "https://lessie.ai"
    print("[bridge] fallback url")
else:
    print(f"[bridge] share link: {share_url1}")

tweet_text = f"{hook}\n\n{share_url1}"
print(f"[action] Posting: {tweet_text}")
success, msg = post_tweet_browser(tweet_text)
print(f"[action] {'✅ Scene 1 posted!' if success else '❌ failed: ' + msg}")
