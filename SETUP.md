# Setup Guide

## Prerequisites

- Python 3.10+
- Node.js (for Lessie CLI)
- Claude Code CLI (`claude` command available)

## 1. Install dependencies

```bash
cd AB-test
pip install -r requirements.txt
```

## 2. Install & auth Lessie CLI

```bash
npm install -g @lessie/cli
lessie auth          # opens browser for login
lessie status        # verify: authorized: true
```

## 3. Configure environment

```bash
cp .env.example .env
# Edit .env — fill in TIKHUB_API_KEY and Twitter API keys
```

## 4. Test the pipeline (no Twitter API needed)

```bash
python test_pipeline.py
```

This runs 2 curated tweets through reasoner + bridge. Takes ~3 min, costs ~40 Lessie credits.

## 5. Run full pipeline (needs TikHub + Twitter API)

```bash
python main.py
```

Default is `DRY_RUN=true` — prints replies but doesn't post to Twitter.

## 6. View dashboard

```bash
pip install flask
python dashboard/app.py
# Open http://localhost:5000
```

## 7. View static demo (no setup needed)

```bash
open demo/index.html
```
