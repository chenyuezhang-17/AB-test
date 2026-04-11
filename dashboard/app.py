"""
Dashboard: Real-time activity monitor for the Twitter Digital Employee.
Run with: python dashboard/app.py
Visit: http://localhost:5000
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, render_template_string

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
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM activity_log ORDER BY ts DESC LIMIT 100").fetchall()
    total = conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]
    scanned = conn.execute("SELECT COUNT(*) FROM activity_log WHERE stage='scanner'").fetchone()[0]
    passed = conn.execute("SELECT COUNT(*) FROM activity_log WHERE stage='reasoner' AND status='passed'").fetchone()[0]
    posted = conn.execute("SELECT COUNT(*) FROM activity_log WHERE stage='action' AND status='posted'").fetchone()[0]
    conn.close()
    return {
        "total": total,
        "scanned": scanned,
        "passed_filter": passed,
        "posted": posted,
        "recent": [dict(r) for r in rows],
    }

HTML = """<!DOCTYPE html>
<html>
<head>
  <title>Lessie Twitter Employee</title>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="15">
  <style>
    body { font-family: -apple-system, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 24px; }
    h1 { font-size: 1.4rem; margin-bottom: 4px; color: #f8fafc; }
    .sub { color: #64748b; font-size: 0.85rem; margin-bottom: 24px; }
    .cards { display: flex; gap: 16px; margin-bottom: 28px; flex-wrap: wrap; }
    .card { background: #1e293b; border-radius: 12px; padding: 20px 28px; min-width: 140px; }
    .card .num { font-size: 2rem; font-weight: 700; color: #38bdf8; }
    .card .label { font-size: 0.8rem; color: #94a3b8; margin-top: 4px; }
    table { width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 12px; overflow: hidden; }
    th { text-align: left; padding: 12px 16px; font-size: 0.75rem; color: #64748b; text-transform: uppercase; border-bottom: 1px solid #334155; }
    td { padding: 12px 16px; font-size: 0.85rem; border-bottom: 1px solid #1e293b; vertical-align: top; }
    tr:hover td { background: #263044; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 99px; font-size: 0.75rem; font-weight: 600; }
    .badge.scanner { background: #1d4ed8; color: #bfdbfe; }
    .badge.reasoner { background: #7c3aed; color: #ede9fe; }
    .badge.bridge { background: #0f766e; color: #ccfbf1; }
    .badge.action { background: #15803d; color: #dcfce7; }
    .badge.passed { background: #166534; color: #bbf7d0; }
    .badge.filtered { background: #7f1d1d; color: #fecaca; }
    .badge.posted { background: #065f46; color: #a7f3d0; }
    .tweet-text { max-width: 320px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #94a3b8; }
    .conf { color: #facc15; }
  </style>
</head>
<body>
  <h1>Lessie Twitter Digital Employee</h1>
  <div class="sub">Auto-refreshes every 15s &nbsp;·&nbsp; Last updated: {{ now }}</div>
  <div class="cards">
    <div class="card"><div class="num">{{ stats.scanned }}</div><div class="label">Tweets Scanned</div></div>
    <div class="card"><div class="num">{{ stats.passed_filter }}</div><div class="label">Passed Filter</div></div>
    <div class="card"><div class="num">{{ stats.posted }}</div><div class="label">Replies Posted</div></div>
    <div class="card"><div class="num">{{ "%.0f"|format(stats.posted / stats.scanned * 100 if stats.scanned else 0) }}%</div><div class="label">Conversion Rate</div></div>
  </div>
  <table>
    <tr>
      <th>Time</th><th>Stage</th><th>Author</th><th>Tweet</th><th>Intent</th><th>Conf</th><th>Status</th>
    </tr>
    {% for r in stats.recent %}
    <tr>
      <td>{{ r.ts[11:19] }}</td>
      <td><span class="badge {{ r.stage }}">{{ r.stage }}</span></td>
      <td>{% if r.author %}<a href="https://twitter.com/{{ r.author }}" style="color:#38bdf8">@{{ r.author }}</a>{% endif %}</td>
      <td class="tweet-text">{{ r.tweet_text or r.detail or "" }}</td>
      <td>{{ r.intent or "" }}</td>
      <td class="conf">{% if r.confidence %}{{ "%.0f"|format(r.confidence * 100) }}%{% endif %}</td>
      <td>{% if r.status %}<span class="badge {{ r.status }}">{{ r.status }}</span>{% endif %}</td>
    </tr>
    {% endfor %}
  </table>
</body>
</html>"""

@app.route("/")
def index():
    stats = get_stats()
    return render_template_string(HTML, stats=stats, now=datetime.now().strftime("%H:%M:%S"))

@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())

if __name__ == "__main__":
    init_db()
    print("Dashboard running at http://localhost:5000")
    app.run(debug=False, port=5000)
