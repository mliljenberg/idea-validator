"""GitHub search tools using the public REST API.

Provides ADK-compatible tool functions:
  - search_github: keyword search for repositories
"""

from __future__ import annotations

from typing import Any
import httpx

_GITHUB_BASE = "https://api.github.com"
_TIMEOUT = 10.0


def search_github(query: str, num_results: int = 5) -> dict[str, Any]:
    """Search GitHub repositories by keyword.

    Args:
        query: The search query string.
        num_results: Maximum number of results to return (default 5).

    Returns:
        A dict with 'query' and 'repositories' — a list of repo dicts.
    """
    try:
        r = httpx.get(
            f"{_GITHUB_BASE}/search/repositories",
            params={"q": query, "per_page": num_results, "sort": "stars"},
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"query": query, "error": str(e), "repositories": []}

    repos = []
    for item in data.get("items", []):
        repos.append(
            {
                "name": item.get("full_name", ""),
                "url": item.get("html_url", ""),
                "description": item.get("description", "") or "",
                "stars": item.get("stargazers_count", 0),
                "language": item.get("language", ""),
                "updated_at": item.get("updated_at", ""),
                "topics": item.get("topics", []),
            }
        )

    return {"query": query, "repositories": repos}
