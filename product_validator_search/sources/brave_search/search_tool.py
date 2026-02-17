"""Brave Search tools using the Brave Search API.

Provides ADK-compatible tool functions:
  - search_brave: keyword search for web results
"""

from __future__ import annotations

import os
from typing import Any
import httpx
from dotenv import load_dotenv

_BRAVE_SEARCH_API_URL = "https://api.search.brave.com/res/v1/web/search"
_TIMEOUT = 10.0


def search_brave(query: str, num_results: int = 10) -> dict[str, Any]:
    """Search the web using Brave Search.

    Args:
        query: The search query string.
        num_results: Maximum number of results to return (default 10).

    Returns:
        A dict with 'query' and 'results' — a list of search result dicts.
    """
    # Ensure env vars are loaded from .env if present
    load_dotenv()

    api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not api_key:
        return {"query": query, "error": "BRAVE_SEARCH_API_KEY not set", "results": []}

    headers = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
    }

    try:
        r = httpx.get(
            _BRAVE_SEARCH_API_URL,
            params={"q": query, "count": num_results},
            headers=headers,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"query": query, "error": str(e), "results": []}

    results = []
    # Brave Search response structure:
    # { "web": { "results": [ { "title": "...", "url": "...", "description": "..." } ] } }
    web_results = data.get("web", {}).get("results", [])

    for item in web_results:
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", "") or "",
                "age": item.get("age", ""),
            }
        )

    return {"query": query, "results": results}
