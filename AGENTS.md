# Product Validator Search - Agent Guide

This repository contains a product validation tool built with Python and the Google ADK (Agent Development Kit). It orchestrates multiple LLM-based agents to research and validate product ideas across various sources (Brave Search, Google Trends, Reddit, etc.).

## 1. Build, Lint, and Test

### Environment Setup
This project uses `uv` for dependency management and `hatchling` for building.

```bash
# Install dependencies
uv pip install -e ".[dev]"

# Activate virtual environment (if not using uv run)
source .venv/bin/activate  # or similar
```

### Testing
Tests are located in `tests/`. We use `pytest` with `pytest-asyncio`.

```bash
# Run all tests
pytest

# Run a specific test file
pytest tests/test_imports.py

# Run a single test function (Useful for debugging)
pytest tests/test_imports.py::test_imports

# Run with output capture disabled (to see print statements)
pytest -s tests/test_imports.py
```

### Linting & Formatting
Follow standard Python conventions.

```bash
# Check code style (using ruff if available, otherwise standard flake8/black)
ruff check .
ruff format .
```

## 2. Code Style & Conventions

### General
- **Python Version**: Target Python 3.9+.
- **Type Hints**: strict typing is required. Use `typing` module or modern `list[]`/`dict[]` syntax where supported.
- **Docstrings**: Use **Google-style** docstrings for all modules, classes, and functions.
  ```python
  def fetch_data(query: str) -> dict:
      """Fetches data from the source.

      Args:
          query: The search string.

      Returns:
          A dictionary containing the results.
      """
  ```

### Imports
Group imports in this order:
1. Standard library (`os`, `sys`, `typing`)
2. Third-party libraries (`google.adk`, `pydantic`, `httpx`)
3. Local application imports (`from .config import config`)

Use absolute imports for external packages and relative imports for internal module references when inside the package.

### Architecture & patterns
- **Agent Definition**: Agents are defined in `product_validator_search/agent.py` and `product_validator_search/sources/`.
- **Configuration**: Use `dataclasses` for configuration (see `product_validator_search/config.py`).
- **Schemas**: Use `pydantic.BaseModel` for all structured outputs and data exchange between agents.
- **Error Handling**: 
  - Fail gracefully. Agents should not crash the entire pipeline.
  - Use `try/except` blocks around external API calls.
  - Log errors but allow the agent to return a partial or "unknown" result if possible.

### Agent Specifics (Google ADK)
- **State Management**: Agents communicate via the shared `state` dictionary.
- **Tools**: Wrap functional logic in `AgentTool` before passing to an `LlmAgent`.
- **Parallel Execution**: Use `ParallelAgent` for independent research tasks to reduce latency.
- **Callbacks**: Use `after_agent_callback` for side effects like saving files (e.g., `_save_report_callback`).

## 3. Directory Structure
- `product_validator_search/`: Main package.
  - `agent.py`: Core orchestration logic and agent definitions.
  - `config.py`: Configuration settings.
  - `sources/`: Individual source agents (HackerNews, Reddit, etc.).
- `tests/`: Unit and integration tests.
- `reports/`: Generated markdown reports (git-ignored).

## 4. Cursor / Copilot Rules
*No specific .cursorrules or Copilot instructions found. Follow the general Python and ADK guidelines above.*
