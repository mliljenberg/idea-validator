"""Hacker News search tools using the Algolia HN Search API.

Provides two ADK-compatible tool functions:
  - search_hackernews: keyword search for stories
  - get_hackernews_comments: fetch a post's full comment tree
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

_ALGOLIA_BASE = "https://hn.algolia.com/api/v1"
_TIMEOUT = 15.0


def search_hackernews(query: str, num_results: int = 20) -> dict[str, Any]:
    """Search Hacker News stories by keyword.

    Args:
        query: The search query string (keywords).
        num_results: Maximum number of story results to return (default 20).

    Returns:
        A dict with 'query' and 'hits' — a list of story dicts, each containing
        objectID, title, url, points, num_comments, and author.
    """
    r = httpx.get(
        f"{_ALGOLIA_BASE}/search",
        params={
            "query": query,
            "tags": "story",
            "hitsPerPage": num_results,
        },
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    payload = r.json()

    hits = []
    for hit in payload.get("hits", []):
        title = hit.get("title") or hit.get("story_title") or ""
        if not title:
            continue
        hits.append(
            {
                "objectID": hit.get("objectID", ""),
                "title": title,
                "url": hit.get("url")
                or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
                "points": hit.get("points", 0),
                "num_comments": hit.get("num_comments", 0),
                "author": hit.get("author", ""),
            }
        )

    return {"query": query, "total_hits": payload.get("nbHits", 0), "hits": hits}


def _flatten_comments(
    children: list[dict], max_depth: int = 3, _depth: int = 0
) -> list[dict]:
    """Recursively flatten the comment tree up to max_depth."""
    flat: list[dict] = []
    for child in children:
        if child.get("type") != "comment":
            continue
        text = child.get("text") or ""
        if not text:
            continue
        flat.append(
            {
                "author": child.get("author", ""),
                "text": text,
                "depth": _depth,
            }
        )
        if _depth < max_depth and child.get("children"):
            flat.extend(_flatten_comments(child["children"], max_depth, _depth + 1))
    return flat


def get_hackernews_comments(
    object_id: str,
    max_depth: int = 3,
    comment_limit: Optional[int] = None,
) -> dict[str, Any]:
    """Fetch a Hacker News post and its full comment tree.

    Args:
        object_id: The HN item ID (objectID from search results).
        max_depth: Maximum comment nesting depth to flatten (default 3).
        comment_limit: Optional cap on flattened comments returned.

    Returns:
        A dict with 'title', 'url', 'points', and 'comments' — a flat list of
        comment dicts with author, text, and depth.
    """
    r = httpx.get(
        f"{_ALGOLIA_BASE}/items/{object_id}",
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    item = r.json()

    comments = _flatten_comments(item.get("children", []), max_depth=max_depth)
    if comment_limit is not None and comment_limit > 0:
        comments = comments[:comment_limit]

    return {
        "objectID": object_id,
        "title": item.get("title", ""),
        "url": item.get("url") or f"https://news.ycombinator.com/item?id={object_id}",
        "points": item.get("points", 0),
        "comments": comments,
    }
