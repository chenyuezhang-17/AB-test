"""
Dashboard: Real-time activity monitor for the Twitter Digital Employee.
Run with: python dashboard/app.py
Visit: http://localhost:5000
"""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template_string, request

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
    """Scrape engagement metrics from Twitter pages via browser CDP."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from db_log import scrape_engagement
        scrape_engagement()
    except Exception as e:
        print(f"[dashboard] engagement sync failed: {e}")

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM activity_log ORDER BY ts DESC LIMIT 100").fetchall()
    scanned = conn.execute("SELECT COUNT(*) FROM activity_log WHERE stage='scanner'").fetchone()[0]
    passed = conn.execute("SELECT COUNT(*) FROM activity_log WHERE stage='reasoner' AND status='passed'").fetchone()[0]
    posted = conn.execute("SELECT COUNT(*) FROM posted_tweets").fetchone()[0]

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
      grid-template-columns: 180px 1fr;
      min-height: 100vh;
    }

    /* Sidebar */
    .sidebar {
      border-right: 2px solid var(--ink);
      padding: 20px 16px;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .brand {
      font-size: 1.1rem;
      font-weight: 700;
      margin-bottom: 4px;
      line-height: 1;
    }
    .brand-line {
      height: 2px;
      background: var(--ink);
      margin-bottom: 16px;
    }
    .nav-item {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 0.85rem;
      padding: 5px 0;
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
      padding: 2px 4px;
      font-size: 0.75rem;
    }
    .nav-icon { font-size: 0.85rem; }
    .sidebar-bottom {
      margin-top: auto;
      font-size: 0.78rem;
      color: var(--muted);
      display: flex;
      align-items: center;
      gap: 6px;
    }

    /* Main content */
    .main {
      padding: 24px 32px;
    }
    .main-header {
      margin-bottom: 20px;
    }
    .main-header h1 {
      font-size: 1.6rem;
      font-weight: 700;
      line-height: 1.1;
    }
    .main-header .sub {
      font-size: 0.82rem;
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
      font-size: 0.75rem;
      color: var(--muted);
      margin-bottom: 6px;
    }
    .card-num {
      font-size: 1.8rem;
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
      font-size: 0.95rem;
      font-weight: 700;
      margin-bottom: 12px;
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
      font-size: 1.3rem;
      font-weight: 700;
      color: var(--ink);
      line-height: 1;
      margin-bottom: 2px;
    }
    .engage-label {
      font-size: 0.72rem;
      color: var(--muted);
    }

    /* Activity log panel */
    .activity-panel {
      border: 2px solid var(--ink);
      border-radius: 4px;
      padding: 18px 20px;
    }
    .activity-title {
      font-size: 0.95rem;
      font-weight: 700;
      margin-bottom: 10px;
    }
    .activity-item {
      display: flex;
      gap: 10px;
      align-items: flex-start;
      padding: 8px 0;
      border-top: 1px solid var(--line);
    }
    .activity-item:first-of-type { border-top: none; }
    .activity-avatar {
      width: 28px; height: 28px;
      border: 1.5px solid var(--ink);
      border-radius: 4px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 0.65rem;
      font-weight: 700;
      flex-shrink: 0;
      background: rgba(54,69,217,0.08);
      color: #3645d9;
      font-family: 'Space Grotesk', sans-serif;
    }
    .activity-avatar.red { background: rgba(232,50,26,0.08); color: var(--red); }
    .activity-content { flex: 1; min-width: 0; }
    .activity-name { font-size: 0.82rem; font-weight: 700; }
    .activity-desc {
      font-size: 0.75rem;
      color: var(--muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .activity-time { font-size: 0.7rem; color: var(--muted); margin-top: 1px; }

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

  </div>
</div>

</body>
</html>"""

DAILY_LIMIT = 5


def get_today_queue():
    """Return today's candidates and posted count."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Today's posted count
    today_posted = conn.execute(
        "SELECT COUNT(*) FROM posted_tweets WHERE posted_at LIKE ?", (f"{today}%",)
    ).fetchone()[0]

    # Already posted tweet_ids (to mark as done)
    posted_ids = set(
        r[0] for r in conn.execute(
            "SELECT original_tweet_id FROM posted_tweets WHERE original_tweet_id IS NOT NULL"
        ).fetchall()
    )

    # Scene 2 candidates: reasoner-passed tweets not yet posted (last 7 days)
    candidates = conn.execute(
        """SELECT tweet_id, author, tweet_text, intent, ts
           FROM activity_log
           WHERE stage='reasoner' AND status='passed'
           ORDER BY ts DESC LIMIT 30"""
    ).fetchall()

    conn.close()
    return {
        "today_posted": today_posted,
        "remaining": max(0, DAILY_LIMIT - today_posted),
        "candidates": [dict(r) for r in candidates],
        "posted_ids": list(posted_ids),
    }


@app.route("/")
def index():
    refresh_engagement()
    stats = get_stats()
    queue = get_today_queue()
    today = datetime.now().strftime("%Y-%m-%d")

    remaining = queue["remaining"]
    today_posted = queue["today_posted"]
    candidates = queue["candidates"]
    posted_ids = set(queue["posted_ids"])

    limit_color = "#e8321a" if remaining == 0 else ("#f59e0b" if remaining <= 2 else "#166534")
    limit_bar = f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:20px">' \
                f'<span style="font-size:0.78rem;color:#8a8880">Daily limit</span>' \
                f'<div style="flex:1;height:6px;background:#e5e2d8;border-radius:3px;overflow:hidden">' \
                f'<div style="width:{min(100,today_posted/DAILY_LIMIT*100):.0f}%;height:100%;background:{limit_color};transition:width .3s"></div>' \
                f'</div>' \
                f'<span style="font-size:0.82rem;font-weight:700;color:{limit_color}">{today_posted}/{DAILY_LIMIT} posted today</span>' \
                f'</div>'

    def _candidate_row(c, collapsed=False):
        tweet_id = c["tweet_id"] or ""
        author = c["author"] or ""
        text = (c["tweet_text"] or "")[:160]
        intent = c["intent"] or ""
        already = tweet_id in posted_ids
        hidden = 'display:none' if collapsed else ''

        if already:
            btn = '<span style="font-size:0.82rem;color:#166534;font-weight:600">✓ Posted</span>'
        elif remaining == 0:
            btn = '<span style="font-size:0.82rem;color:#8a8880">Limit reached</span>'
        else:
            btn = (f'<button onclick="postReply(\'{tweet_id}\',\'{author}\',this)" '
                   f'style="font-size:0.82rem;font-weight:700;padding:6px 12px;border:1.5px solid #111;'
                   f'border-radius:4px;background:#111;color:#fff;cursor:pointer;white-space:nowrap">Post Reply</button>')

        intent_badge = f'<span style="font-size:0.72rem;background:#0e7490;color:#cffafe;padding:2px 7px;border-radius:3px;margin-left:6px">{intent}</span>' if intent else ''
        date_str = (c["ts"] or "")[:10]
        return (
            f'<div class="s2-extra" style="{hidden};padding:10px 14px;border-radius:6px;margin-bottom:6px;background:#faf9f6;border:1.5px solid #e5e2d8">'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">'
            f'<span style="font-size:0.88rem;font-weight:700">@{author}</span>{intent_badge}'
            f'<span style="font-weight:400;color:#8a8880;margin-left:auto;font-size:0.75rem">{date_str}</span>'
            f'{btn}</div>'
            f'<div style="font-size:0.82rem;color:#444;line-height:1.45">{text}</div>'
            f'</div>'
        )

    top_c = candidates[:4]
    rest_c = candidates[4:]
    cands_top  = "".join(_candidate_row(c, collapsed=False) for c in top_c)
    cands_rest = "".join(_candidate_row(c, collapsed=True)  for c in rest_c)
    show_more_c = (f'<button onclick="toggleMoreS2(this)" style="font-size:0.82rem;color:#111;background:none;border:none;cursor:pointer;padding:4px 0;font-weight:600">'
                   f'▸ Show {len(rest_c)} more candidates</button>') if rest_c else ''
    candidates_html = (cands_top + cands_rest + show_more_c) if candidates else \
        '<div style="color:#8a8880;font-style:italic;font-size:0.88rem;padding:16px 0">No candidates scanned today yet.</div>'

    scene1_disabled = 'disabled style="opacity:.5;cursor:not-allowed"' if remaining == 0 else ''

    # Load trend candidates from DB
    from db_log import get_trend_candidates
    trend_candidates = get_trend_candidates()

    def _trend_card(t, collapsed=False):
        tid = t['id']
        hook = t['tweet_hook'] or t['topic']
        topic = t['topic']
        date = (t['scanned_at'] or '')[:10]
        posted = t['status'] == 'posted'
        style = 'display:none' if collapsed else ''
        if posted:
            btn = '<span style="font-size:0.82rem;color:#166534;font-weight:600">✓ Posted</span>'
        elif remaining == 0:
            btn = '<span style="font-size:0.82rem;color:#8a8880">Limit reached</span>'
        else:
            btn = (f'<button onclick="selectTrend({tid},this)" '
                   f'style="font-size:0.82rem;font-weight:700;padding:6px 14px;border:1.5px solid #3645d9;'
                   f'border-radius:4px;background:#3645d9;color:white;cursor:pointer;white-space:nowrap">Use this</button>')
        return (
            f'<div class="trend-extra" style="{style};display:{"none" if collapsed else "flex"};align-items:center;gap:12px;padding:10px 14px;border-radius:6px;margin-bottom:6px;background:#faf9f6;border:1.5px solid #e5e2d8">'
            f'<div style="flex:1;min-width:0">'
            f'<div style="font-size:0.92rem;font-weight:600;line-height:1.35;margin-bottom:3px">{hook[:120]}</div>'
            f'<div style="font-size:0.78rem;color:#8a8880">{topic[:80]}<span style="margin-left:8px;opacity:.6">{date}</span></div>'
            f'</div>'
            f'<div style="flex-shrink:0">{btn}</div>'
            f'</div>'
        )

    top5 = trend_candidates[:5]
    rest  = trend_candidates[5:]
    top_html  = ''.join(_trend_card(t, collapsed=False) for t in top5)
    rest_html = ''.join(_trend_card(t, collapsed=True)  for t in rest)
    show_more = (f'<button onclick="toggleMore(this)" style="font-size:0.82rem;color:#3645d9;background:none;border:none;cursor:pointer;padding:4px 0;font-weight:600">'
                 f'▸ Show {len(rest)} more topics</button>') if rest else ''
    trends_html = (top_html + rest_html + show_more) if trend_candidates else \
        '<div style="color:#8a8880;font-size:0.88rem;font-style:italic;padding:16px 0">No trends scanned yet — click Scan Now to fetch today\'s hot topics.</div>'

    # Replace the lower section content
    dashboard_html = HTML.replace(
        "<!-- Lower: Engagement + Activity -->",
        f"""<!-- Lower: Queue + Activity -->
    {limit_bar}

    <!-- Scene 1 -->
    <div style="border:2px solid var(--ink);border-radius:4px;padding:20px 24px;margin-bottom:16px">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px">
        <span style="background:#3645d9;color:white;font-size:0.78rem;font-weight:700;padding:3px 10px;border-radius:3px">S1</span>
        <span style="font-size:1rem;font-weight:700">Scene 1 · Trend Posts</span>
        <span style="font-size:0.82rem;color:#8a8880">Today's hot topics — pick one, Leego drafts + posts</span>
        <button onclick="scanTrends(this)" style="margin-left:auto;font-size:0.82rem;font-weight:700;padding:6px 16px;border:1.5px solid #111;border-radius:4px;background:#fff;cursor:pointer">↻ Scan Now</button>
      </div>
      <div id="trendsContainer">{trends_html}</div>
      <div id="s1preview" style="margin-top:14px;display:none;border-top:1.5px solid #e5e2d8;padding-top:14px">
        <div style="font-size:0.82rem;color:#8a8880;margin-bottom:6px">Preview — edit if needed before posting</div>
        <textarea id="s1text" style="width:100%;padding:10px 12px;border:1.5px solid #d4d0c8;border-radius:4px;font-size:0.9rem;font-family:inherit;resize:vertical;min-height:90px;background:#faf9f6;line-height:1.6"></textarea>
        <div style="display:flex;gap:10px;margin-top:10px">
          <button onclick="postTrend()" id="s1postBtn"
            style="padding:8px 20px;border:1.5px solid #3645d9;border-radius:4px;background:#3645d9;color:white;font-size:0.88rem;font-weight:700;cursor:pointer">
            ↗ Post this tweet
          </button>
          <button onclick="document.getElementById('s1preview').style.display='none'"
            style="padding:8px 14px;border:1.5px solid #d4d0c8;border-radius:4px;background:#fff;font-size:0.88rem;cursor:pointer">Cancel</button>
        </div>
      </div>
    </div>

    <!-- Scene 2 + Recent Activity -->
    <div class="lower">
      <div class="panel">
        <div style="font-size:1rem;font-weight:700;margin-bottom:4px">Scene 2 · Reply Candidates</div>
        <div style="font-size:0.82rem;color:#8a8880;margin-bottom:10px">Tweets matched — click to reply with Lessie results</div>
        {candidates_html}
      </div>

      <div class="activity-panel">
        <div class="activity-title">Recent Activity</div>
        {{% if stats.recent %}}
          {{% for r in stats.recent[:6] %}}
          <div class="activity-item">
            <div class="activity-avatar {{% if r.stage == 'action' %}}red{{% endif %}}">
              {{{{ r.stage[:2].upper() if r.stage else '?' }}}}
            </div>
            <div class="activity-content">
              <div class="activity-name">
                {{% if r.author %}}@{{{{ r.author }}}}{{% else %}}{{{{ r.stage }}}}{{% endif %}}
                {{% if r.intent %}} · <span style="font-weight:400;color:var(--muted)">{{{{ r.intent }}}}</span>{{% endif %}}
              </div>
              <div class="activity-desc">{{{{ r.tweet_text or r.detail or "—" }}}}</div>
              <div class="activity-time">{{{{ r.ts[11:19] }}}} · {{{{ r.status or "" }}}}</div>
            </div>
          </div>
          {{% endfor %}}
        {{% else %}}
          <div class="empty-state">Waiting for pipeline to run...</div>
        {{% endif %}}
      </div>
    </div>

    <script>
    let _s1TweetText = '';
    let _s1TrendId = null;

    async function selectTrend(tid, btn) {{
      const orig = btn.textContent;
      btn.textContent = 'Generating...'; btn.disabled = true;
      try {{
        const r = await fetch('/api/generate-trend', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{trend_id: tid}})
        }});
        const d = await r.json();
        if (d.ok) {{
          _s1TweetText = d.tweet_text;
          _s1TrendId = tid;
          document.getElementById('s1text').value = d.tweet_text;
          document.getElementById('s1preview').style.display = 'block';
          const postBtn = document.getElementById('s1postBtn');
          postBtn.disabled = false; postBtn.style.opacity = '1';
          postBtn.textContent = '↗ Post this tweet';
          postBtn.style.background = '#3645d9'; postBtn.style.borderColor = '#3645d9';
        }} else {{
          alert('Generate failed: ' + d.error);
          btn.textContent = orig; btn.disabled = false;
        }}
      }} catch(e) {{ alert('Error: ' + e); btn.textContent = orig; btn.disabled = false; }}
    }}

    async function scanTrends(btn) {{
      const orig = btn.textContent;
      btn.textContent = 'Scanning...'; btn.disabled = true;
      try {{
        const r = await fetch('/api/scan-trends', {{method: 'POST'}});
        const d = await r.json();
        if (d.ok) {{
          btn.textContent = `✓ ${{d.count}} topics found`;
          setTimeout(() => location.reload(), 1200);
        }} else {{
          alert('Scan failed: ' + (d.error || 'unknown error'));
          btn.textContent = orig; btn.disabled = false;
        }}
      }} catch(e) {{ alert('Error: ' + e); btn.textContent = orig; btn.disabled = false; }}
    }}

    async function postTrend() {{
      const btn = document.getElementById('s1postBtn');
      const tweetText = document.getElementById('s1text').value.trim();
      if (!tweetText) return;
      btn.textContent = 'Posting...'; btn.disabled = true;
      try {{
        const r = await fetch('/api/post-trend', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{tweet_text: tweetText, trend_id: _s1TrendId}})
        }});
        const d = await r.json();
        if (d.ok) {{
          btn.textContent = '✓ Posted';
          btn.style.background = '#166534'; btn.style.borderColor = '#166534';
          setTimeout(() => location.reload(), 1200);
        }} else {{
          alert('Post failed: ' + d.error);
          btn.textContent = '↗ Post this tweet'; btn.disabled = false;
        }}
      }} catch(e) {{ alert('Error: ' + e); btn.textContent = '↗ Post this tweet'; btn.disabled = false; }}
    }}

    function toggleMore(btn) {{
      const extras = document.querySelectorAll('.trend-extra[style*="display:none"], .trend-extra[style*="display: none"]');
      const hidden = document.querySelectorAll('.trend-extra');
      let anyHidden = false;
      hidden.forEach(el => {{ if(el.style.display === 'none') anyHidden = true; }});
      if (anyHidden) {{
        hidden.forEach(el => {{ el.style.display = 'flex'; }});
        btn.textContent = '▾ Show fewer topics';
      }} else {{
        let count = 0;
        hidden.forEach(el => {{ if(count++ >= 5) el.style.display = 'none'; }});
        btn.textContent = '▸ Show more topics';
      }}
    }}

    function toggleMoreS2(btn) {{
      const items = document.querySelectorAll('.s2-extra');
      let anyHidden = false;
      items.forEach(el => {{ if(el.style.display === 'none') anyHidden = true; }});
      if (anyHidden) {{
        items.forEach(el => {{ el.style.display = 'block'; }});
        btn.textContent = '▾ Show fewer candidates';
      }} else {{
        let count = 0;
        items.forEach(el => {{ if(count++ >= 4) el.style.display = 'none'; }});
        btn.textContent = '▸ Show more candidates';
      }}
    }}

    async function postReply(tweetId, author, btn) {{
      btn.disabled = true;
      btn.textContent = 'Posting...';
      try {{
        const r = await fetch('/api/post', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{tweet_id: tweetId, author: author}})
        }});
        const d = await r.json();
        if (d.ok) {{
          btn.textContent = '✓ Posted';
          btn.style.background = '#166534';
          btn.style.borderColor = '#166534';
          setTimeout(() => location.reload(), 1000);
        }} else {{
          btn.textContent = '✗ Failed';
          btn.style.background = '#e8321a';
          btn.disabled = false;
        }}
      }} catch(e) {{
        btn.textContent = 'Error';
        btn.disabled = false;
      }}
    }}
    </script>
    <!-- hidden lower -->"""
    )

    return render_template_string(dashboard_html, stats=stats, now=datetime.now().strftime("%H:%M:%S"), page="dashboard")


@app.route("/api/generate-trend", methods=["POST"])
def api_generate_trend():
    """Generate Scene 1 tweet copy + share link for a trend candidate or raw topic."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    data = request.get_json() or {}
    trend_id = data.get("trend_id")
    topic = data.get("topic", "").strip()

    # If trend_id provided, look up stored search_prompt and tweet_hook
    tweet_hook = None
    search_prompt = None
    if trend_id:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT topic, tweet_hook, search_prompt FROM trend_candidates WHERE id=?", (trend_id,)
        ).fetchone()
        conn.close()
        if row:
            topic = row[0] or topic
            tweet_hook = row[1]
            search_prompt = row[2]

    if not topic and not search_prompt:
        return jsonify({"ok": False, "error": "missing topic or trend_id"})

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
        from bridge.search import _create_share_link

        checkpoint = search_prompt or f"Find professionals and experts relevant to this topic: {topic}"
        share_url = _create_share_link(checkpoint) or "https://lessie.ai"

        hook = tweet_hook or topic[:200]
        tweet_text = f"{hook}\n\nran a search on who's actually working in this space 👇\n\n{share_url}"
        return jsonify({"ok": True, "tweet_text": tweet_text, "share_url": share_url})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/post-trend", methods=["POST"])
def api_post_trend():
    """Post a Scene 1 trend tweet via browser CDP."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    data = request.get_json() or {}
    tweet_text = data.get("tweet_text", "").strip()
    if not tweet_text:
        return jsonify({"ok": False, "error": "missing tweet_text"})

    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    today_count = conn.execute(
        "SELECT COUNT(*) FROM posted_tweets WHERE posted_at LIKE ?", (f"{today}%",)
    ).fetchone()[0]
    conn.close()
    if today_count >= DAILY_LIMIT:
        return jsonify({"ok": False, "error": f"Daily limit of {DAILY_LIMIT} reached"})

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
        from action.browser_post import post_tweet_browser
        from db_log import log_action

        import re
        url_match = re.search(r'https://app\.lessie\.ai/share/\S+', tweet_text)
        share_url = url_match.group(0) if url_match else ""

        success, result_url = post_tweet_browser(tweet_text)
        if success:
            log_action(
                reply_text=tweet_text,
                lessie_url=share_url,
                scene="Scene 1: Trends",
                our_tweet_url=result_url if result_url.startswith("http") else "",
            )
            # Mark trend candidate as posted
            trend_id = data.get("trend_id")
            if trend_id:
                conn = sqlite3.connect(DB_PATH)
                conn.execute("UPDATE trend_candidates SET status='posted' WHERE id=?", (trend_id,))
                conn.commit()
                conn.close()
            return jsonify({"ok": True, "url": result_url})
        else:
            return jsonify({"ok": False, "error": result_url})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/post", methods=["POST"])
def api_post():
    """Manually trigger a reply post for a given tweet_id."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    data = request.get_json() or {}
    tweet_id = data.get("tweet_id", "")
    author = data.get("author", "")

    if not tweet_id:
        return jsonify({"ok": False, "error": "missing tweet_id"})

    # Daily limit check
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    today_count = conn.execute(
        "SELECT COUNT(*) FROM posted_tweets WHERE posted_at LIKE ?", (f"{today}%",)
    ).fetchone()[0]
    conn.close()
    if today_count >= DAILY_LIMIT:
        return jsonify({"ok": False, "error": f"Daily limit of {DAILY_LIMIT} reached"})

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
        from bridge.search import _create_share_link
        from action.browser_post import post_reply_browser
        from db_log import log_action

        tweet_url = f"https://x.com/{author}/status/{tweet_id}"
        checkpoint = f"Find people relevant to hiring needs from @{author} on Twitter"
        share_url = _create_share_link(checkpoint) or "https://lessie.ai"

        reply = f"ran a search on this — here's a relevant talent pool that might help 👀\n\n{share_url}"
        success, result_url = post_reply_browser(tweet_url, reply)

        if success:
            log_action(
                reply_text=reply,
                lessie_url=share_url,
                original_tweet_id=tweet_id,
                author=author,
                scene="Scene 2: Intent",
                our_tweet_url=result_url if result_url.startswith("http") else "",
            )
            return jsonify({"ok": True, "url": result_url})
        else:
            return jsonify({"ok": False, "error": result_url})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

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
    posted = conn.execute(
        "SELECT * FROM posted_tweets ORDER BY posted_at DESC LIMIT 50"
    ).fetchall()
    conn.close()

    def _card(r):
        scene = r['scene'] or ''
        is_reply = 'Scene 2' in scene or bool(r['original_tweet_id'])
        badge_bg = '#e8321a' if is_reply else '#3645d9'
        label = 'S2' if is_reply else 'S1'
        target = f"@{r['original_tweet_id']}" if is_reply else 'Trend'

        tweet_link = ''
        if r['our_tweet_url']:
            tweet_link = f'<a href="{r["our_tweet_url"]}" target="_blank" style="color:#3645d9;font-weight:600;text-decoration:none">↗ View tweet</a>'

        lessie_link = ''
        if r['lessie_url']:
            lessie_link = f'<a href="{r["lessie_url"]}" target="_blank" style="color:#e8321a;text-decoration:none">Lessie results →</a>'

        eng = f'❤️ {r["likes"] or 0}  🔁 {r["retweets"] or 0}  👁 {r["views"] or 0}'

        return (
            f'<div style="border:1.5px solid #d4d0c8;border-radius:6px;padding:14px 16px;margin-bottom:12px;background:#faf9f6">'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">'
            f'<span style="background:{badge_bg};color:white;font-size:0.7rem;font-weight:700;padding:2px 7px;border-radius:3px">{label}</span>'
            f'<span style="font-size:0.78rem;color:#8a8880">{r["posted_at"][:16].replace("T"," ")} · {scene}</span>'
            f'<span style="margin-left:auto;display:flex;gap:12px">{tweet_link} {lessie_link}</span>'
            f'</div>'
            f'<div style="font-size:0.82rem;line-height:1.5;color:#111110;white-space:pre-wrap;margin-bottom:8px">{r["reply_text"] or ""}</div>'
            f'<div style="font-size:0.72rem;color:#8a8880">{eng}</div>'
            f'</div>'
        )

    cards_html = ''.join(_card(r) for r in posted) or '<div style="color:#8a8880;font-style:italic;padding:24px 0">No tweets posted yet.</div>'

    total_likes    = sum(r['likes']    or 0 for r in posted)
    total_rts      = sum(r['retweets'] or 0 for r in posted)
    total_views    = sum(r['views']    or 0 for r in posted)
    total_posted   = len(posted)
    scene1_count   = sum(1 for r in posted if 'Scene 1' in (r['scene'] or ''))
    scene2_count   = sum(1 for r in posted if 'Scene 2' in (r['scene'] or ''))

    summary = f'''
    <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:20px">
      <div class="card"><div class="card-label">Total Posted</div><div class="card-num">{total_posted}</div></div>
      <div class="card"><div class="card-label">Scene 1 (Trend)</div><div class="card-num" style="color:#3645d9">{scene1_count}</div></div>
      <div class="card"><div class="card-label">Scene 2 (Reply)</div><div class="card-num" style="color:#e8321a">{scene2_count}</div></div>
      <div class="card"><div class="card-label">Total Likes</div><div class="card-num">{"—" if total_likes == 0 else total_likes}</div></div>
      <div class="card"><div class="card-label">Total Views</div><div class="card-num">{"—" if total_views == 0 else total_views}</div></div>
    </div>'''

    tweets_html = HTML.replace(
        '<!-- Stat cards -->',
        f'''<!-- Tweets Content -->
    {summary}
    <div style="margin-bottom:20px">{cards_html}</div>
    <!-- Stat cards (hidden) -->'''
    ).replace(
        "<h1>Here's what Leego has been up to.</h1>",
        '<h1>Tweets</h1>'
    ).replace(
        'Your Twitter Digital Employee overview for today.',
        'All tweets posted by Leego — click to view originals.'
    )
    tweets_html = tweets_html.replace('<!-- Lower: Engagement + Activity -->', '<!-- hidden --><!--').replace('</div>\n\n</div>', '--></div>\n\n</div>', 1)

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

@app.route("/api/scan-trends", methods=["POST"])
def api_scan_trends():
    """Run trend scanner and save candidates to DB."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from scanner.trends import scan_trends
        from db_log import save_trend_candidates
        trends = scan_trends()
        saved = save_trend_candidates(trends)
        return jsonify({"ok": True, "count": len(trends), "saved": saved})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())

if __name__ == "__main__":
    init_db()
    print("Dashboard running at http://localhost:5000")
    app.run(debug=False, port=5000)
