"""Jobs-market signal tools built on Brave Search."""

from __future__ import annotations

from typing import Any

from ..brave_search.search_tool import search_brave


def search_jobs_signal(keywords: list[str], num_results: int = 8) -> dict[str, Any]:
    """Search hiring pages for demand and budget proxies."""
    sanitized = [kw.strip() for kw in keywords if kw and kw.strip()][:5]
    if not sanitized:
        return {"queries": [], "results_by_query": [], "errors": ["No keywords provided."]}

    queries: list[str] = []
    for kw in sanitized:
        queries.extend(
            [
                f'site:linkedin.com/jobs "{kw}"',
                f'site:indeed.com "{kw}" "job"',
                f'"{kw}" "hiring" "product manager"',
                f'"{kw}" "implementation" "enterprise"',
            ]
        )

    deduped_queries = list(dict.fromkeys(queries))[:10]
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
