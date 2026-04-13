# Leego — Twitter Digital Employee for Lessie AI

Twitter 数字员工：自动抓取推特上的找人需求，生成 Lessie 搜索结果，通过引用转发回复。

Hackathon MVP — "先提供价值，再建立认知"。

## Quick Start

```bash
git clone https://github.com/chenyuezhang-17/AB-test.git
cd AB-test
pip install -r requirements.txt
npm install                # Lessie CLI
lessie auth                # browser login
cp .env.example .env       # fill in API keys
python main.py             # Scene 2: intent interception
python trend_pipeline.py   # Scene 1: trend-jacking
python dashboard/app.py    # Dashboard at localhost:5000
```

See [SETUP.md](SETUP.md) for detailed instructions.

## Architecture

```
scanner/       ← Twitter data fetching (keywords + trends)
reasoner/      ← LLM intent analysis + Lessie Enrich profiling + 4-framework prompt gen
bridge/        ← Lessie search + real share link generation via Web API
action/        ← Tweet posting with anti-spam rate limiting
dashboard/     ← Flask web UI: Dashboard / Analytics / Tweets / Settings
demo/          ← Pitch page + before/after comparison + static demo data
docs/          ← PRD
```

## Team

| Member | GitHub | Modules | Scope |
|--------|--------|---------|-------|
| Becky | chenyuezhang-17 | reasoner/ bridge/ | LLM intent + Lessie API + share links |
| Alexia | alexiayx | scanner/ action/ | Twitter API + posting |
| Shane | shanezchang | TBD | TBD |

## Tech Stack

- Python 3.10+
- Lessie CLI + Web API (people search + share links)
- Claude Code CLI (zero-cost LLM)
- TikHub API (Twitter data)
- Tweepy (Twitter posting)
- Flask (dashboard)

## Docs

- [PRD](docs/PRD.md) — 完整产品需求文档
- [CLAUDE.md](CLAUDE.md) — 开发约定与接口定义
- [SETUP.md](SETUP.md) — 安装和运行指南
