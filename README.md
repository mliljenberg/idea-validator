# Product Validator (Phase 1)

Automated research agent for software/SaaS ideas using Python, `uv`, and Google ADK integration.

## Setup

```bash
uv venv
uv sync --extra dev
```

To enable Tier 2 sources (Reddit via PRAW):

```bash
uv sync --extra dev --extra tier2
```

## Run CLI

```bash
uv run product-validator "AI tool that summarizes long email threads" "productivity" --pretty
```

CLI now starts with a plan-review step:
- Shows which sources will be used.
- Shows source-specific search queries.
- Shows execution steps.
- Prompts: `approve`, `edit`, or `cancel`.

Useful flags:
- `--plan-only` to generate plan without running research.
- `--plan-updates "..."` to pre-seed plan changes.
- `--auto-approve` to skip interactive approval.

The output includes a final `conclusion_paragraph` that summarizes why the idea should or should not be pursued.
It also includes `source_diagnostics` so you can see query terms, per-source hit counts, and any source-specific errors.
The decision layer is hybrid: rule-based baseline plus Gemini-based analysis when `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) is set.

## ADK App

```python
from product_validator.adk_app import build_app

app = build_app(model="gemini-3.0-flash")
```

## Test ideas

1. AI tool that summarizes long email threads
2. No-code platform for building Discord bots
3. Browser extension that blocks distracting sites during focus time

## Optional environment variables

```bash
GITHUB_TOKEN=ghp_xxx
REDDIT_CLIENT_ID=xxx
REDDIT_CLIENT_SECRET=xxx
REDDIT_USER_AGENT=product-validator/0.1
PRODUCT_HUNT_TOKEN=xxx
CRUNCHBASE_API_KEY=xxx
GOOGLE_API_KEY=xxx
PV_ENABLE_LLM_ANALYSIS=true
PV_LLM_ANALYSIS_MODEL=gemini-3.0-flash
```
