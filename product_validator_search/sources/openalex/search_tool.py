"""OpenAlex search tools using the OpenAlex REST API.

Provides two ADK-compatible tool functions:
  - search_openalex: keyword search for academic works (papers, articles)
  - get_openalex_work_details: fetch full metadata for a specific work
"""

from __future__ import annotations

from typing import Any

import httpx

_BASE = "https://api.openalex.org"
_TIMEOUT = 15.0


def search_openalex(query: str, num_results: int = 20) -> dict[str, Any]:
    """Search OpenAlex for academic works matching a query.

    Args:
        query: The search query string.
        num_results: Maximum number of results to return (default 20).

    Returns:
        A dict with 'query', 'total_count', and 'works' — a list of work dicts
        containing id, title, publication_year, cited_by_count, doi, and
        top concepts.
    """
    r = httpx.get(
        f"{_BASE}/works",
        params={
            "search": query,
            "per-page": num_results,
            "sort": "relevance_score:desc",
        },
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    payload = r.json()

    works = []
    for item in payload.get("results", []):
        title = item.get("display_name", "")
        if not title:
            continue
        concepts = [
            c.get("display_name", "")
            for c in (item.get("concepts") or [])[:5]
            if c.get("display_name")
        ]
        works.append(
            {
                "id": item.get("id", ""),
                "title": title,
                "publication_year": item.get("publication_year"),
                "cited_by_count": item.get("cited_by_count", 0),
                "doi": item.get("doi", ""),
                "type": item.get("type", ""),
                "concepts": concepts,
            }
        )

    return {
        "query": query,
        "total_count": payload.get("meta", {}).get("count", 0),
        "works": works,
    }


def get_openalex_work_details(work_id: str) -> dict[str, Any]:
    """Fetch detailed metadata for a single OpenAlex work.

    Args:
        work_id: The OpenAlex work ID — accepts either the full entity URL
            (e.g. 'https://openalex.org/W2741809807') or just the short ID
            (e.g. 'W2741809807').

    Returns:
        A dict with title, abstract, publication_year, cited_by_count,
        concepts, referenced_works count, related_works count, and
        authorships.
    """
    # The search results return IDs like "https://openalex.org/W..."
    # but the API endpoint is "https://api.openalex.org/works/W..."
    short_id = work_id.rsplit("/", 1)[-1] if "/" in work_id else work_id
    r = httpx.get(
        f"{_BASE}/works/{short_id}",
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    item = r.json()

    # Reconstruct abstract from inverted index if available
    abstract = ""
    inv_index = item.get("abstract_inverted_index")
    if inv_index:
        word_positions: list[tuple[int, str]] = []
        for word, positions in inv_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort()
        abstract = " ".join(w for _, w in word_positions)

    concepts = [
        {"name": c.get("display_name", ""), "score": round(c.get("score", 0), 3)}
        for c in (item.get("concepts") or [])[:10]
        if c.get("display_name")
    ]

    authorships = [
        {
            "name": a.get("author", {}).get("display_name", ""),
            "institution": (a.get("institutions") or [{}])[0].get("display_name", "")
            if a.get("institutions")
            else "",
        }
        for a in (item.get("authorships") or [])[:10]
    ]

    return {
        "id": item.get("id", ""),
        "title": item.get("display_name", ""),
        "abstract": abstract[:2000],
        "publication_year": item.get("publication_year"),
        "cited_by_count": item.get("cited_by_count", 0),
        "type": item.get("type", ""),
        "doi": item.get("doi", ""),
        "concepts": concepts,
        "authorships": authorships,
        "referenced_works_count": len(item.get("referenced_works", [])),
        "related_works_count": len(item.get("related_works", [])),
    }
