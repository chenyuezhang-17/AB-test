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
  <link href="https://fonts.googleapis.com/css2?family=Caveat:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;600&display=swap" rel="stylesheet">
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
      font-family: 'Space Grotesk', sans-serif;
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
      font-family: 'Space Grotesk', sans-serif;
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
    <a href="/" class="nav-item {% if page == 'dashboard' %}active{% endif %}" style="text-decoration:none;color:inherit">
      <span class="nav-icon">🏠</span> Dashboard
    </a>
    <a href="/analytics" class="nav-item {% if page == 'analytics' %}active{% endif %}" style="text-decoration:none;color:inherit">
      <span class="nav-icon">📊</span> Analytics
    </a>
    <a href="/tweets" class="nav-item {% if page == 'tweets' %}active{% endif %}" style="text-decoration:none;color:inherit">
      <span class="nav-icon">🐦</span> Tweets
    </a>
    <a href="/settings" class="nav-item {% if page == 'settings' %}active{% endif %}" style="text-decoration:none;color:inherit">
      <span class="nav-icon">⚙️</span> Settings
    </a>
    <div class="sidebar-bottom">
      <span>⚡</span> Leego is live
    </div>
  </div>

  <!-- Main -->
  <div class="main">
    <div class="main-header">
      <span class="live-badge"><span class="live-dot"></span> {{ now }}</span>
      <h1>Here's what Leego has been up to.</h1>
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
    return render_template_string(HTML, stats=stats, now=datetime.now().strftime("%H:%M:%S"), page="dashboard")

@app.route("/analytics")
def analytics():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Pipeline conversion funnel
    scanned = conn.execute("SELECT COUNT(*) FROM activity_log WHERE stage='scanner'").fetchone()[0]
    passed = conn.execute("SELECT COUNT(*) FROM activity_log WHERE stage='reasoner' AND status='passed'").fetchone()[0]
    filtered = conn.execute("SELECT COUNT(*) FROM activity_log WHERE stage='reasoner' AND status='filtered'").fetchone()[0]
    bridge_ready = conn.execute("SELECT COUNT(*) FROM activity_log WHERE stage='bridge' AND status='ready'").fetchone()[0]
    posted = conn.execute("SELECT COUNT(*) FROM activity_log WHERE stage='action' AND status='posted'").fetchone()[0]

    # Scene breakdown
    scene1 = conn.execute("SELECT COUNT(*) FROM activity_log WHERE detail LIKE '%Scene 1%'").fetchone()[0]
    scene2 = conn.execute("SELECT COUNT(*) FROM activity_log WHERE detail LIKE '%Scene 2%'").fetchone()[0]

    # Intent distribution
    intents = conn.execute(
        "SELECT intent, COUNT(*) as cnt FROM activity_log WHERE stage='reasoner' AND intent IS NOT NULL GROUP BY intent ORDER BY cnt DESC"
    ).fetchall()

    # Framework distribution
    frameworks = conn.execute(
        "SELECT detail, COUNT(*) as cnt FROM activity_log WHERE stage='reasoner' AND status='passed' AND detail LIKE 'Framework%' GROUP BY detail ORDER BY cnt DESC"
    ).fetchall()

    conn.close()

    analytics_html = HTML.replace(
        '<!-- Stat cards -->',
        '''<!-- Analytics Content -->
    <h2 style="font-family:'Caveat',cursive;font-size:1.6rem;margin-bottom:16px">Pipeline Funnel</h2>
    <div class="cards">
      <div class="stat-card"><div class="card-label">Scanned</div><div class="card-number">''' + str(scanned) + '''</div></div>
      <div class="stat-card"><div class="card-label">Passed Reasoner</div><div class="card-number">''' + str(passed) + '''</div></div>
      <div class="stat-card"><div class="card-label">Filtered Out</div><div class="card-number">''' + str(filtered) + '''</div></div>
      <div class="stat-card"><div class="card-label">Bridge Ready</div><div class="card-number">''' + str(bridge_ready) + '''</div></div>
      <div class="stat-card"><div class="card-label">Posted</div><div class="card-number">''' + str(posted) + '''</div></div>
    </div>
    <div style="margin-top:24px" class="cards">
      <div class="stat-card"><div class="card-label">Scene 1: Trends</div><div class="card-number">''' + str(scene1) + '''</div></div>
      <div class="stat-card"><div class="card-label">Scene 2: Intent</div><div class="card-number">''' + str(scene2) + '''</div></div>
    </div>
    <h2 style="font-family:'Caveat',cursive;font-size:1.6rem;margin:24px 0 12px">Intent Distribution</h2>
    <div class="activity-list">''' + ''.join(
        f'<div class="activity-item"><div class="activity-badge" style="background:#0e7490;color:#cffafe">{r["intent"]}</div><div class="activity-content"><div class="activity-title">{r["cnt"]} tweets</div></div></div>'
        for r in intents
    ) + '''</div>
    <h2 style="font-family:'Caveat',cursive;font-size:1.6rem;margin:24px 0 12px">Frameworks Used</h2>
    <div class="activity-list">''' + ''.join(
        f'<div class="activity-item"><div class="activity-badge" style="background:#7c3aed;color:#ede9fe">FR</div><div class="activity-content"><div class="activity-title">{r["detail"]}</div><div class="activity-meta">{r["cnt"]}x</div></div></div>'
        for r in frameworks
    ) + '''</div>
    <!-- Stat cards (hidden) -->'''
    ).replace(
        '<h1>Here\'s what Leego has been up to.</h1>',
        '<h1>Analytics</h1>'
    ).replace(
        'Your Twitter Digital Employee overview for today.',
        'Pipeline performance and conversion metrics.'
    )
    # Hide the engagement + activity sections on analytics page
    analytics_html = analytics_html.replace('<!-- Engagement grid -->', '<!-- hidden --><!--').replace('<!-- Activity Log -->', '--><!-- Activity Log -->')

    return render_template_string(analytics_html, stats=get_stats(), now=datetime.now().strftime("%H:%M:%S"), page="analytics")

@app.route("/tweets")
def tweets():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Get full pipeline data: group by tweet_id to show the complete journey
    all_items = conn.execute(
        "SELECT * FROM activity_log ORDER BY tweet_id, ts ASC"
    ).fetchall()
    conn.close()

    # Group by tweet_id
    grouped = {}
    for r in all_items:
        tid = r['tweet_id'] or r['id']
        if tid not in grouped:
            grouped[tid] = {'scanner': None, 'reasoner': None, 'bridge': None, 'action': None}
        grouped[tid][r['stage']] = dict(r)

    # Build cards — only show items that have at least a scanner entry
    cards_html = ""
    for tid, stages in sorted(grouped.items(), key=lambda x: (x[1].get('action') or x[1].get('scanner') or {}).get('ts', ''), reverse=True):
        scanner = stages.get('scanner')
        reasoner = stages.get('reasoner')
        bridge = stages.get('bridge')
        action = stages.get('action')

        if not scanner:
            continue

        author = scanner.get('author', '')
        original_text = scanner.get('tweet_text', '')
        is_scene1 = not author or (reasoner and reasoner.get('intent') == 'trend')
        scene_label = 'S1 · Trend' if is_scene1 else 'S2 · Intent'
        scene_color = '#0e7490' if is_scene1 else '#e8321a'

        # Status
        if action and action.get('status') == 'posted':
            status_badge = '<span style="background:#166534;color:#bbf7d0;padding:2px 8px;border-radius:99px;font-size:0.75rem;font-weight:600;">Posted</span>'
        elif reasoner and reasoner.get('status') == 'filtered':
            status_badge = '<span style="background:#7f1d1d;color:#fecaca;padding:2px 8px;border-radius:99px;font-size:0.75rem;font-weight:600;">Filtered</span>'
        elif bridge:
            status_badge = '<span style="background:#ca8a04;color:#fef9c3;padding:2px 8px;border-radius:99px;font-size:0.75rem;font-weight:600;">Ready to Post</span>'
        else:
            status_badge = '<span style="background:#6b7280;color:#e5e7eb;padding:2px 8px;border-radius:99px;font-size:0.75rem;font-weight:600;">Processing</span>'

        # Reply text and share link
        reply_text = (action or {}).get('tweet_text', '')
        lessie_url = (action or bridge or {}).get('lessie_url', '')
        tweet_url = f"https://x.com/{author}/status/{tid}" if author and tid.startswith('tw_') is False else ''

        # Confidence
        conf = reasoner.get('confidence', 0) if reasoner else 0
        conf_str = f"{conf*100:.0f}%" if conf else ''

        # Framework / detail
        detail = (reasoner or {}).get('detail', '')

        # Build the card
        cards_html += f'''
        <div class="border-sketch-sm" style="padding:20px;margin-bottom:16px;background:#fff;cursor:pointer;" onclick="this.querySelector('.tweet-expand').style.display=this.querySelector('.tweet-expand').style.display==='none'?'block':'none'">
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
            <span style="background:{scene_color};color:white;padding:3px 10px;border-radius:99px;font-size:0.75rem;font-weight:600;">{scene_label}</span>
            {status_badge}
            <span style="color:var(--ink-muted);font-size:0.8rem;">{conf_str}</span>
            <span style="color:var(--ink-muted);font-size:0.8rem;margin-left:auto;">{scanner.get("ts", "")[:19]}</span>
          </div>
          <div style="font-size:0.95rem;font-weight:600;margin-bottom:4px;">{"@" + author if author else "Trend Post"}</div>
          <div style="font-size:0.88rem;color:var(--ink-light);line-height:1.5;">{original_text[:150]}{"..." if len(original_text) > 150 else ""}</div>
          <div style="font-size:0.78rem;color:var(--ink-muted);margin-top:6px;">Click to expand ↓</div>

          <div class="tweet-expand" style="display:none;margin-top:16px;padding-top:16px;border-top:1.5px solid var(--line);">
            <div style="font-size:0.82rem;color:var(--ink-muted);text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px;">Original Tweet</div>
            <div style="font-size:0.9rem;color:var(--ink);line-height:1.6;padding:12px;background:var(--bg);border-radius:8px;margin-bottom:16px;">{original_text}</div>

            {"<div style='margin-bottom:12px;'><span style='font-size:0.82rem;color:var(--ink-muted);'>Framework: </span><span style='font-size:0.85rem;color:#7c3aed;font-weight:600;'>" + detail + "</span></div>" if detail else ""}

            {"<div style='font-size:0.82rem;color:var(--ink-muted);text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px;'>Leego Reply</div><div id='reply-{tid}' style='font-size:0.9rem;color:var(--ink);line-height:1.6;padding:12px;background:#f0fdf4;border-radius:8px;border-left:3px solid #16a34a;margin-bottom:12px;'>" + reply_text + "</div>" if reply_text else ""}

            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              {"<button onclick='event.stopPropagation();navigator.clipboard.writeText(document.getElementById(\"reply-" + tid + "\").innerText);this.textContent=\"Copied!\";setTimeout(()=>this.textContent=\"Copy Reply\",2000)' style='background:var(--ink);color:var(--paper);border:2px solid var(--ink);padding:8px 16px;border-radius:100px 4px 100px 4px/4px 100px 4px 100px;font-family:Space Grotesk,sans-serif;font-size:0.85rem;font-weight:600;cursor:pointer;'>Copy Reply</button>" if reply_text else ""}
              {"<a href='" + lessie_url + "' target='_blank' onclick='event.stopPropagation()' style='display:inline-flex;align-items:center;background:transparent;color:#e8321a;border:2px solid #e8321a;padding:8px 16px;border-radius:4px 100px 4px 100px/100px 4px 100px 4px;font-family:Space Grotesk,sans-serif;font-size:0.85rem;font-weight:600;text-decoration:none;cursor:pointer;'>View Results ↗</a>" if lessie_url else ""}
              {"<a href='https://x.com/intent/tweet?in_reply_to=" + tid + "' target='_blank' onclick='event.stopPropagation()' style='display:inline-flex;align-items:center;background:#1d9bf0;color:white;border:2px solid #1d9bf0;padding:8px 16px;border-radius:100px 4px 100px 4px/4px 100px 4px 100px;font-family:Space Grotesk,sans-serif;font-size:0.85rem;font-weight:600;text-decoration:none;cursor:pointer;'>Reply on X ↗</a>" if author and not is_scene1 else ""}
              {"<a href='https://x.com/intent/tweet' target='_blank' onclick='event.stopPropagation()' style='display:inline-flex;align-items:center;background:#1d9bf0;color:white;border:2px solid #1d9bf0;padding:8px 16px;border-radius:100px 4px 100px 4px/4px 100px 4px 100px;font-family:Space Grotesk,sans-serif;font-size:0.85rem;font-weight:600;text-decoration:none;cursor:pointer;'>Post on X ↗</a>" if is_scene1 else ""}
            </div>
          </div>
        </div>'''

    tweets_html = HTML.replace(
        '<!-- Stat cards -->',
        '''<!-- Tweets Content -->
    <h2 style="font-family:'Caveat',cursive;font-size:1.6rem;margin-bottom:16px">Pipeline Results</h2>
    <div style="font-size:0.85rem;color:var(--ink-muted);margin-bottom:20px;">Click any card to expand → review → copy → post on X</div>
    ''' + cards_html + '''
    <!-- Stat cards (hidden) -->'''
    ).replace(
        '<h1>Here\'s what Leego has been up to.</h1>',
        '<h1>Tweets</h1>'
    ).replace(
        'Your Twitter Digital Employee overview for today.',
        'Review and post Leego\'s replies.'
    )
    tweets_html = tweets_html.replace('<!-- Engagement grid -->', '<!-- hidden --><!--').replace('<!-- Activity Log -->', '--><!-- Activity Log -->')

    return render_template_string(tweets_html, stats=get_stats(), now=datetime.now().strftime("%H:%M:%S"), page="tweets")

@app.route("/settings")
def settings():
    import os
    settings_html = HTML.replace(
        '<!-- Stat cards -->',
        '''<!-- Settings Content -->
    <h2 style="font-family:'Caveat',cursive;font-size:1.6rem;margin-bottom:16px">Configuration</h2>
    <div class="activity-list">
      <div class="activity-item"><div class="activity-badge" style="background:#166534;color:#bbf7d0">OK</div><div class="activity-content"><div class="activity-title">Lessie CLI</div><div class="activity-meta">''' + ('Authorized' if os.path.exists(os.path.expanduser('~/.lessie/oauth.json')) else 'Not configured — run: lessie auth') + '''</div></div></div>
      <div class="activity-item"><div class="activity-badge" style="background:''' + ('#166534' if os.getenv('TIKHUB_API_KEY') else '#7f1d1d') + ''';color:''' + ('#bbf7d0' if os.getenv('TIKHUB_API_KEY') else '#fecaca') + '''">''' + ('OK' if os.getenv('TIKHUB_API_KEY') else '!!') + '''</div><div class="activity-content"><div class="activity-title">TikHub API</div><div class="activity-meta">''' + ('Configured' if os.getenv('TIKHUB_API_KEY') else 'Missing — add TIKHUB_API_KEY to .env') + '''</div></div></div>
      <div class="activity-item"><div class="activity-badge" style="background:''' + ('#166534' if os.getenv('TWITTER_API_KEY') else '#7f1d1d') + ''';color:''' + ('#bbf7d0' if os.getenv('TWITTER_API_KEY') else '#fecaca') + '''">''' + ('OK' if os.getenv('TWITTER_API_KEY') else '!!') + '''</div><div class="activity-content"><div class="activity-title">Twitter API</div><div class="activity-meta">''' + ('Configured' if os.getenv('TWITTER_API_KEY') else 'Missing — add Twitter keys to .env') + '''</div></div></div>
      <div class="activity-item"><div class="activity-badge" style="background:''' + ('#166534' if os.getenv('LESSIE_JWT') else '#7f1d1d') + ''';color:''' + ('#bbf7d0' if os.getenv('LESSIE_JWT') else '#fecaca') + '''">''' + ('OK' if os.getenv('LESSIE_JWT') else '!!') + '''</div><div class="activity-content"><div class="activity-title">Lessie JWT (Share Links)</div><div class="activity-meta">''' + ('Configured' if os.getenv('LESSIE_JWT') else 'Missing — add LESSIE_JWT to .env') + '''</div></div></div>
      <div class="activity-item"><div class="activity-badge" style="background:#0e7490;color:#cffafe">ℹ️</div><div class="activity-content"><div class="activity-title">DRY_RUN Mode</div><div class="activity-meta">''' + ('ON — tweets will NOT be posted' if os.getenv('DRY_RUN', 'true').lower() == 'true' else 'OFF — tweets WILL be posted to Twitter') + '''</div></div></div>
    </div>
    <!-- Stat cards (hidden) -->'''
    ).replace(
        '<h1>Here\'s what Leego has been up to.</h1>',
        '<h1>Settings</h1>'
    ).replace(
        'Your Twitter Digital Employee overview for today.',
        'API keys and pipeline configuration status.'
    )
    settings_html = settings_html.replace('<!-- Engagement grid -->', '<!-- hidden --><!--').replace('<!-- Activity Log -->', '--><!-- Activity Log -->')

    return render_template_string(settings_html, stats=get_stats(), now=datetime.now().strftime("%H:%M:%S"), page="settings")

@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())

if __name__ == "__main__":
    init_db()
    print("Dashboard running at http://localhost:5000")
    app.run(debug=False, port=5000)
