# Product Validator Search

Product validation system built with Python + Google ADK, plus a Tauri desktop client.

## Prerequisites

- Python 3.9+
- `uv`
- Rust toolchain (for Tauri desktop)
- `bun` (for desktop frontend)

## Python backend setup

```bash
uv venv
uv sync --extra dev
```

Copy env template:

```bash
cp .env.example .env
```

Required keys:

```bash
GOOGLE_API_KEY=your_key_here
BRAVE_SEARCH_API_KEY=your_key_here
```

## Run ADK web directly

```bash
uv run web
```

or:

```bash
uv run start
```

Both commands forward to:

```bash
uv run adk web .
```

## Desktop app (Tauri + React)

The desktop app lives in `desktop/` and manages the local ADK backend automatically.

Install desktop dependencies:

```bash
cd desktop
bun install
```

Run desktop in development:

```bash
bun run tauri:dev
```

Build desktop app:

```bash
bun run tauri:build
```

## Tests

Python tests:

```bash
uv run pytest -q
```

Desktop frontend unit tests:

```bash
cd desktop
bun test
```

Rust unit tests:

```bash
cd desktop/src-tauri
cargo test
```

## Troubleshooting

- `uv` missing:
  Install uv and ensure it is on your `PATH`.
- Backend won't start in desktop:
  Confirm keys exist in app settings or `.env`, then press **Start / Refresh**.
- Port conflict on 8765:
  Desktop automatically retries higher ports.
- Missing keys:
  Open desktop key settings panel and save keys to OS keychain.

## Project structure

- `product_validator_search/`: Python agent orchestration and sources
- `desktop/`: Tauri desktop app with streaming UI
- `reports/`: generated markdown reports (gitignored)
