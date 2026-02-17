"""SEO intent tools using Brave Search as a public-data fallback."""

from __future__ import annotations

from typing import Any

from ..brave_search.search_tool import search_brave

_TRANSACTIONAL_MODIFIERS = [
    "pricing",
    "buy",
    "software",
    "tool",
    "platform",
    "best",
    "alternative",
    "for teams",
]
_INFORMATIONAL_MODIFIERS = [
    "what is",
    "how to",
    "tutorial",
    "guide",
    "learn",
]


def search_seo_intent(keywords: list[str], num_results: int = 8) -> dict[str, Any]:
    """Search informational and transactional variants for keyword intent."""
    sanitized = [kw.strip() for kw in keywords if kw and kw.strip()][:5]
    if not sanitized:
        return {"queries": [], "results_by_query": [], "errors": ["No keywords provided."]}

    queries: list[str] = []
    for kw in sanitized:
        for modifier in _TRANSACTIONAL_MODIFIERS[:4]:
            queries.append(f'"{kw}" {modifier}')
        for modifier in _INFORMATIONAL_MODIFIERS[:3]:
            queries.append(f'"{kw}" {modifier}')

    deduped_queries = list(dict.fromkeys(queries))[:14]
    results_by_query: list[dict[str, Any]] = []
    errors: list[str] = []

    for query in deduped_queries:
        response = search_brave(query=query, num_results=num_results)
        if response.get("error"):
            errors.append(f'{query}: {response["error"]}')
        results_by_query.append(response)

    return {
        "queries": deduped_queries,
        "results_by_query": results_by_query,
        "errors": errors,
    }
