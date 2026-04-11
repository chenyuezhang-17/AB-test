"""
Dashboard: Real-time activity monitor for the Twitter Digital Employee.
Run with: python dashboard/app.py
Visit: http://localhost:5000
"""

import os
import sqlite3
import tweepy
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template_string

load_dotenv()
app = Flask(__name__)
DB_PATH = Path(__file__).parent.parent / "activity.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            stage TEXT NOT NULL,
            tweet_id TEXT,
            author TEXT,
            tweet_text TEXT,
            intent TEXT,
            confidence REAL,
            lessie_url TEXT,
            status TEXT,
            detail TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posted_tweets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            posted_at TEXT NOT NULL,
            our_tweet_id TEXT UNIQUE,
            original_tweet_id TEXT,
            reply_text TEXT,
            lessie_url TEXT,
            views INTEGER DEFAULT 0,
            retweets INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            replies INTEGER DEFAULT 0,
            last_synced TEXT
        )
    """)
    conn.commit()
    conn.close()

def refresh_engagement():
    """Fetch latest engagement metrics for our posted tweets from Twitter API."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT our_tweet_id FROM posted_tweets WHERE our_tweet_id IS NOT NULL"
    ).fetchall()
    conn.close()

    if not rows:
        return

    try:
        client = tweepy.Client(
            bearer_token=os.getenv("TWITTER_BEARER_TOKEN"),
            consumer_key=os.getenv("TWITTER_API_KEY"),
            consumer_secret=os.getenv("TWITTER_API_SECRET"),
            access_token=os.getenv("TWITTER_ACCESS_TOKEN"),
            access_token_secret=os.getenv("TWITTER_ACCESS_TOKEN_SECRET"),
        )
        ids = [r[0] for r in rows]
        response = client.get_tweets(
            ids=ids,
            tweet_fields=["public_metrics", "non_public_metrics"],
        )
        if not response.data:
            return
        conn = sqlite3.connect(DB_PATH)
        now = datetime.now(timezone.utc).isoformat()
        for tweet in response.data:
            m = tweet.public_metrics or {}
            conn.execute(
                "UPDATE posted_tweets SET views=?, retweets=?, likes=?, replies=?, last_synced=? WHERE our_tweet_id=?",
                (m.get("impression_count", 0), m.get("retweet_count", 0),
                 m.get("like_count", 0), m.get("reply_count", 0), now, str(tweet.id))
            )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[dashboard] engagement sync failed: {e}")

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM activity_log ORDER BY ts DESC LIMIT 100").fetchall()
    scanned = conn.execute("SELECT COUNT(*) FROM activity_log WHERE stage='scanner'").fetchone()[0]
    passed = conn.execute("SELECT COUNT(*) FROM activity_log WHERE stage='reasoner' AND status='passed'").fetchone()[0]
    posted = conn.execute("SELECT COUNT(*) FROM activity_log WHERE stage='action' AND status='posted'").fetchone()[0]

    today = datetime.now().strftime("%Y-%m-%d")
    today_posts = conn.execute(
        "SELECT COUNT(*) FROM posted_tweets WHERE posted_at LIKE ?", (f"{today}%",)
    ).fetchone()[0]
    engagement = conn.execute(
        "SELECT COALESCE(SUM(views),0), COALESCE(SUM(retweets),0), COALESCE(SUM(likes),0), COALESCE(SUM(replies),0) FROM posted_tweets"
    ).fetchone()
    posted_list = conn.execute(
        "SELECT * FROM posted_tweets ORDER BY posted_at DESC LIMIT 20"
    ).fetchall()
    conn.close()

    return {
        "scanned": scanned,
        "passed_filter": passed,
        "posted": posted,
        "today_posts": today_posts,
        "total_views": engagement[0],
        "total_retweets": engagement[1],
        "total_likes": engagement[2],
        "total_replies": engagement[3],
        "recent": [dict(r) for r in rows],
        "posted_tweets": [dict(r) for r in posted_list],
    }

HTML = """<!DOCTYPE html>
<html>
<head>
  <title>Lessie · Twitter Digital Employee</title>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="15">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Caveat:wght@400;500;600;700&family=Inter:wght@400;500&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg: #f2efe8;
      --ink: #111110;
      --muted: #8a8880;
      --line: #d4d0c8;
      --red: #e8321a;
      --red-soft: rgba(232, 50, 26, 0.08);
    }

    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: 'Caveat', cursive;
      background: var(--bg);
      color: var(--ink);
      min-height: 100vh;
      padding: 0 0 80px;
    }

    /* Layout: sidebar + main */
    .layout {
      display: grid;
      grid-template-columns: 220px 1fr;
      min-height: 100vh;
    }

    /* Sidebar */
    .sidebar {
      border-right: 2px solid var(--ink);
      padding: 32px 24px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .brand {
      font-size: 1.8rem;
      font-weight: 700;
      margin-bottom: 4px;
      line-height: 1;
    }
    .brand-line {
      height: 2px;
      background: var(--ink);
      margin-bottom: 28px;
    }
    .nav-item {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 1.2rem;
      padding: 6px 0;
      color: var(--muted);
      cursor: default;
    }
    .nav-item.active {
      color: var(--ink);
    }
    .nav-item.active .nav-icon {
      background: rgba(54,69,217,0.12);
      border: 1.5px solid var(--ink);
      border-radius: 6px;
      padding: 3px 5px;
      font-size: 0.9rem;
    }
    .nav-icon { font-size: 1rem; }
    .sidebar-bottom {
      margin-top: auto;
      font-size: 1rem;
      color: var(--muted);
      display: flex;
      align-items: center;
      gap: 8px;
    }

    /* Main content */
    .main {
      padding: 36px 44px;
    }
    .main-header {
      margin-bottom: 32px;
    }
    .main-header h1 {
      font-size: 2.6rem;
      font-weight: 700;
      line-height: 1.1;
    }
    .main-header .sub {
      font-size: 1.2rem;
      color: var(--muted);
      margin-top: 4px;
    }
    .live-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border: 1.5px solid var(--ink);
      border-radius: 4px;
      padding: 3px 10px;
      font-size: 0.9rem;
      float: right;
      margin-top: 6px;
    }
    .live-dot {
      width: 7px; height: 7px;
      background: var(--red);
      border-radius: 50%;
      animation: blink 1.8s infinite;
    }
    @keyframes blink {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.15; }
    }

    /* Stat cards row */
    .cards {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 16px;
      margin-bottom: 20px;
    }
    .card {
      border: 2px solid var(--ink);
      border-radius: 4px;
      padding: 18px 20px 20px;
      position: relative;
      background: var(--bg);
    }
    .card-label {
      font-size: 1rem;
      color: var(--muted);
      margin-bottom: 8px;
    }
    .card-num {
      font-size: 2.8rem;
      font-weight: 700;
      line-height: 1;
      color: var(--ink);
    }
    .card-num.blue { color: #3645d9; }
    .card-squiggle {
      position: absolute;
      bottom: 14px;
      right: 16px;
      color: var(--muted);
      font-size: 1.4rem;
      font-weight: 400;
      font-style: italic;
    }

    /* Two column lower */
    .lower {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-bottom: 20px;
    }

    /* Engagement panel */
    .panel {
      border: 2px solid var(--ink);
      border-radius: 4px;
      padding: 18px 20px;
    }
    .panel-title {
      font-size: 1.5rem;
      font-weight: 700;
      margin-bottom: 16px;
    }
    .engage-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    .engage-item {
      border-top: 1.5px solid var(--line);
      padding-top: 10px;
    }
    .engage-num {
      font-size: 2rem;
      font-weight: 700;
      color: var(--ink);
      line-height: 1;
      margin-bottom: 4px;
    }
    .engage-label {
      font-size: 0.9rem;
      color: var(--muted);
    }

    /* Activity log panel */
    .activity-panel {
      border: 2px solid var(--ink);
      border-radius: 4px;
      padding: 18px 20px;
    }
    .activity-title {
      font-size: 1.5rem;
      font-weight: 700;
      margin-bottom: 14px;
    }
    .activity-item {
      display: flex;
      gap: 12px;
      align-items: flex-start;
      padding: 10px 0;
      border-top: 1px solid var(--line);
    }
    .activity-item:first-of-type { border-top: none; }
    .activity-avatar {
      width: 32px; height: 32px;
      border: 1.5px solid var(--ink);
      border-radius: 4px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 0.75rem;
      font-weight: 700;
      flex-shrink: 0;
      background: rgba(54,69,217,0.08);
      color: #3645d9;
      font-family: 'Inter', sans-serif;
    }
    .activity-avatar.red { background: rgba(232,50,26,0.08); color: var(--red); }
    .activity-content { flex: 1; min-width: 0; }
    .activity-name { font-size: 1.05rem; font-weight: 700; }
    .activity-desc {
      font-size: 0.9rem;
      color: var(--muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .activity-time { font-size: 0.8rem; color: var(--muted); margin-top: 2px; }

    .empty-state {
      text-align: center;
      padding: 32px 0;
      color: var(--muted);
      font-size: 1.1rem;
      font-style: italic;
    }
  </style>
</head>
<body>

<div class="layout">

  <!-- Sidebar -->
  <div class="sidebar">
    <div class="brand">Lessie.ai</div>
    <div class="brand-line"></div>
    <div class="nav-item active">
      <span class="nav-icon">🏠</span> Dashboard
    </div>
    <div class="nav-item">
      <span class="nav-icon">📊</span> Analytics
    </div>
    <div class="nav-item">
      <span class="nav-icon">🐦</span> Tweets
    </div>
    <div class="nav-item">
      <span class="nav-icon">⚙️</span> Settings
    </div>
    <div class="sidebar-bottom">
      <span>⚡</span> Alex is live
    </div>
  </div>

  <!-- Main -->
  <div class="main">
    <div class="main-header">
      <span class="live-badge"><span class="live-dot"></span> {{ now }}</span>
      <h1>Here's what Alex has been up to.</h1>
      <div class="sub">Your Twitter Digital Employee overview for today.</div>
    </div>

    <!-- Stat cards -->
    <div class="cards">
      <div class="card">
        <div class="card-label">Tweets Scanned</div>
        <div class="card-num">{{ stats.scanned }}</div>
        <div class="card-squiggle">～</div>
      </div>
      <div class="card">
        <div class="card-label">High Matched</div>
        <div class="card-num blue">{{ stats.passed_filter }}</div>
        <div class="card-squiggle" style="color:#3645d9">↗</div>
      </div>
      <div class="card">
        <div class="card-label">Replies Posted</div>
        <div class="card-num" style="color:var(--red)">{{ stats.posted }}</div>
        <div class="card-squiggle" style="color:var(--red)">✓</div>
      </div>
    </div>

    <!-- Lower: Engagement + Activity -->
    <div class="lower">

      <div class="panel">
        <div class="panel-title">Today's Engagement</div>
        <div class="engage-grid">
          <div class="engage-item">
            <div class="engage-num">{{ stats.today_posts }}</div>
            <div class="engage-label">Posts Today</div>
          </div>
          <div class="engage-item">
            <div class="engage-num">{{ stats.total_views }}</div>
            <div class="engage-label">Total Views</div>
          </div>
          <div class="engage-item">
            <div class="engage-num">{{ stats.total_retweets }}</div>
            <div class="engage-label">Retweets</div>
          </div>
          <div class="engage-item">
            <div class="engage-num">{{ stats.total_likes }}</div>
            <div class="engage-label">Likes</div>
          </div>
        </div>
      </div>

      <div class="activity-panel">
        <div class="activity-title">Recent Activity</div>
        {% if stats.recent %}
          {% for r in stats.recent[:6] %}
          <div class="activity-item">
            <div class="activity-avatar {% if r.stage == 'action' %}red{% endif %}">
              {{ r.stage[:2].upper() if r.stage else '?' }}
            </div>
            <div class="activity-content">
              <div class="activity-name">
                {% if r.author %}@{{ r.author }}{% else %}{{ r.stage }}{% endif %}
                {% if r.intent %} · <span style="font-weight:400;color:var(--muted)">{{ r.intent }}</span>{% endif %}
              </div>
              <div class="activity-desc">{{ r.tweet_text or r.detail or "—" }}</div>
              <div class="activity-time">{{ r.ts[11:19] }} · {{ r.status or "" }}</div>
            </div>
          </div>
          {% endfor %}
        {% else %}
          <div class="empty-state">Waiting for pipeline to run...</div>
        {% endif %}
      </div>

    </div>

  </div>
</div>

</body>
</html>"""

@app.route("/")
def index():
    refresh_engagement()
    stats = get_stats()
    return render_template_string(HTML, stats=stats, now=datetime.now().strftime("%H:%M:%S"))

@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())

if __name__ == "__main__":
    init_db()
    print("Dashboard running at http://localhost:5000")
    app.run(debug=False, port=5000)
