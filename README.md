# Product Validator Search

Product validation agent built with Python + Google ADK.  
It researches an idea across multiple sources and returns a critical go/pivot/abandon report.

## Prerequisites

- Python 3.9+
- `uv` installed

## Setup

```bash
uv venv
uv sync --extra dev
```

## Configure API key(s)

Create `.env` (or export env vars) with at least:

```bash
GOOGLE_API_KEY=your_key_here
BRAVE_SEARCH_API_KEY=your_key_here
```

Optional:

```bash
GEMINI_API_KEY=your_key_here
GITHUB_TOKEN=ghp_xxx
REDDIT_CLIENT_ID=xxx
REDDIT_CLIENT_SECRET=xxx
REDDIT_USER_AGENT=product-validator/0.1
```

## Run Web UI

Recommended shortcut:

```bash
uv run web
```

Alternative alias:

```bash
uv run start
```

Equivalent direct command:

```bash
uv run adk web .
```

Custom host/port:

```bash
uv run web --host 0.0.0.0 --port 8000
```

Then open the URL shown in terminal (usually `http://127.0.0.1:8000`).

## Run tests

```bash
uv run pytest -q
```

## Project structure

- `product_validator_search/agent.py`: root orchestration and report synthesis
- `product_validator_search/sources/`: source-specific researcher/validator agents
- `reports/`: generated reports (gitignored)
