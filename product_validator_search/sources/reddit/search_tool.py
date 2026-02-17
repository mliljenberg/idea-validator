"""Reddit search tools using the public JSON API.

Provides two ADK-compatible tool functions:
  - search_reddit: keyword search for posts
  - get_reddit_comments: fetch a post's comments
"""

from __future__ import annotations

from typing import Any
import httpx
import time

_REDDIT_BASE = "https://www.reddit.com"
_TIMEOUT = 10.0
_USER_AGENT = "product-validator/0.1"


def search_reddit(query: str, num_results: int = 10) -> dict[str, Any]:
    """Search Reddit posts by keyword.

    Args:
        query: The search query string.
        num_results: Maximum number of results to return (default 10).

    Returns:
        A dict with 'query' and 'posts' — a list of post dicts.
    """
    headers = {"User-Agent": _USER_AGENT}
    try:
        # Respect Reddit's API rules - avoid hitting it too hard
        time.sleep(1.0)

        r = httpx.get(
            f"{_REDDIT_BASE}/search.json",
            params={"q": query, "limit": num_results, "sort": "relevance", "t": "year"},
            headers=headers,
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"query": query, "error": str(e), "posts": []}

    posts = []
    # Reddit JSON structure: data -> children -> [ { data: { title, ... } } ]
    children = data.get("data", {}).get("children", [])

    for child in children:
        post_data = child.get("data", {})
        posts.append(
            {
                "title": post_data.get("title", ""),
                "url": f"{_REDDIT_BASE}{post_data.get('permalink', '')}",
                "score": post_data.get("score", 0),
                "num_comments": post_data.get("num_comments", 0),
                "subreddit": post_data.get("subreddit", ""),
                "selftext": (post_data.get("selftext", "") or "")[:500],  # Truncate
            }
        )

    return {"query": query, "posts": posts}


def get_reddit_comments(url: str) -> dict[str, Any]:
    """Fetch a Reddit post and its top comments.

    Args:
        url: The full URL of the Reddit post.

    Returns:
        A dict with post details and a list of top comments.
    """
    if not url.endswith(".json"):
        if url.endswith("/"):
            url = url[:-1]
        url = f"{url}.json"

    headers = {"User-Agent": _USER_AGENT}
    try:
        time.sleep(1.0)

        r = httpx.get(
            url,
            headers=headers,
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"url": url, "error": str(e)}

    # Reddit JSON API returns a list: [post_listing, comment_listing]
    if not isinstance(data, list) or len(data) < 2:
        return {"url": url, "error": "Invalid Reddit JSON response"}

    # Extract post info from the first listing
    post_children = data[0].get("data", {}).get("children", [])
    if not post_children:
        return {"url": url, "error": "No post data found"}

    post_data = post_children[0].get("data", {})

    # Extract comments from the second listing
    comments_data = data[1].get("data", {}).get("children", [])

    comments = []
    for child in comments_data:
        c = child.get("data", {})
        # Only include actual comments, not "more" objects
        if c.get("body"):
            comments.append(
                {
                    "author": c.get("author", "[deleted]"),
                    "body": (c.get("body", "") or "")[:1000],  # Truncate
                    "score": c.get("score", 0),
                }
            )

    return {
        "title": post_data.get("title", ""),
        "subreddit": post_data.get("subreddit", ""),
        "score": post_data.get("score", 0),
        "comments": comments[:10],  # Limit to top 10 root comments
    }
