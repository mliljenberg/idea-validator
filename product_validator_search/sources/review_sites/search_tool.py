"""Review-site focused search tools built on Brave Search."""

from __future__ import annotations

from typing import Any

from ..brave_search.search_tool import search_brave


def search_review_sites(keywords: list[str], num_results: int = 8) -> dict[str, Any]:
    """Search review platforms for buyer-intent signals.

    Uses Brave Search with targeted site filters to gather public review evidence
    from G2, Capterra, and Trustpilot without requiring premium APIs.
    """
    sanitized = [kw.strip() for kw in keywords if kw and kw.strip()][:5]
    if not sanitized:
        return {"queries": [], "results_by_query": [], "errors": ["No keywords provided."]}

    queries: list[str] = []
    for kw in sanitized:
        queries.extend(
            [
                f'site:g2.com "{kw}" reviews pricing',
                f'site:capterra.com "{kw}" reviews alternatives',
                f'site:trustpilot.com "{kw}" review complaints',
            ]
        )

    deduped_queries = list(dict.fromkeys(queries))[:9]
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
