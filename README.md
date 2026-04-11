```bash
    git clone https://github.com/chenyuezhang-17/AB-test.git
    cd AB-test
    pip install -r requirements.txt
    cp .env.example .env
    # Fill in your API keys in .env
    python main.py

    Team

    ┌────────┬───────────────────┬──────────────────────────────────┐
    │ Member │      Modules      │              Scope               │
    ├────────┼───────────────────┼──────────────────────────────────┤
    │ Becky  │ reasoner/ bridge/ │ LLM intent analysis + Lessie API │
    ├────────┼───────────────────┼──────────────────────────────────┤
    │ Alexia │ scanner/ action/  │ Twitter API fetching + posting   │
    └────────┴───────────────────┴──────────────────────────────────┘

    Tech Stack

    - Python 3.14
    - Twitter API (via tweepy)
    - Lessie People Search CLI
    - Claude CLI (zero API cost LLM)

    Docs

    - PRD — 完整产品需求文档
    - CLAUDE.md — 开发约定与接口定义
