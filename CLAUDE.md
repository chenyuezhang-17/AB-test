# Twitter Digital Employee for Lessie AI

## Project Overview
Twitter 数字员工：自动抓取推特上的找人需求，生成 Lessie 搜索结果，通过引用转发回复。
Hackathon MVP — "先提供价值，再建立认知"。

## Team
- **Becky (chenyuezhang-17)** — Project lead, Lessie product expert
- **Alexia (alexiayx)** — Collaborator

## Language
- 代码注释和 commit message 用英文
- 文档和 UI 文案中英混合
- 团队沟通用中文

## Architecture

```
scanner/       ← Twitter data fetching (keywords, trends)
reasoner/      ← LLM intent analysis + prompt generation
bridge/        ← Lessie API integration + share link generation
action/        ← Tweet posting / quote repost
dashboard/     ← Simple web UI for daily review
docs/          ← PRD, specs, design docs
```

## Tech Stack
- Python 3.14
- Twitter API or alternative (TBD)
- LLM: Claude via claude CLI (zero API cost)
- Lessie: /lessie skill for search + enrichment

## Development Rules

### Workflow
1. Non-trivial changes: brainstorm → plan → execute → verify
2. Create feature branches: `becky/xxx` or `alexia/xxx`
3. PR for review before merging to main
4. Keep PRD.md updated when scope changes

### Code
1. Each module is a separate directory with its own README
2. Config via environment variables or .env (never commit secrets)
3. No hardcoded API keys — use .env.example as template
4. Test before commit: at minimum, syntax check + import test

### Git
1. Commit messages: concise English, describe WHY not WHAT
2. Pull before push: `git pull --rebase origin main`
3. Don't force push to main
