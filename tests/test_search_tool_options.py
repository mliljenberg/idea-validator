"""Tests for optional depth/sorting parameters in search tools."""

from product_validator_search.sources.hackernews import search_tool as hn_tool
from product_validator_search.sources.reddit import search_tool as reddit_tool


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_search_reddit_supports_custom_sort_and_time_window(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None, follow_redirects=None):
        captured["url"] = url
        captured["params"] = params
        return _FakeResponse({"data": {"children": []}})

    monkeypatch.setattr(reddit_tool.time, "sleep", lambda _x: None)
    monkeypatch.setattr(reddit_tool.httpx, "get", fake_get)

    reddit_tool.search_reddit("idea query", num_results=7, sort="new", time_window="month")

    assert captured["url"].endswith("/search.json")
    assert captured["params"]["limit"] == 7
    assert captured["params"]["sort"] == "new"
    assert captured["params"]["t"] == "month"


def test_get_reddit_comments_honors_comment_limit_and_sort(monkeypatch):
    captured = {}
    payload = [
        {"data": {"children": [{"data": {"title": "Post", "subreddit": "test", "score": 5}}]}},
        {
            "data": {
                "children": [
                    {"data": {"author": "a1", "body": "c1", "score": 1}},
                    {"data": {"author": "a2", "body": "c2", "score": 2}},
                    {"data": {"author": "a3", "body": "c3", "score": 3}},
                ]
            }
        },
    ]

    def fake_get(url, params=None, headers=None, timeout=None, follow_redirects=None):
        captured["url"] = url
        captured["params"] = params
        return _FakeResponse(payload)

    monkeypatch.setattr(reddit_tool.time, "sleep", lambda _x: None)
    monkeypatch.setattr(reddit_tool.httpx, "get", fake_get)

    result = reddit_tool.get_reddit_comments(
        "https://www.reddit.com/r/test/comments/abc/sample_post/",
        comment_limit=2,
        sort="new",
    )

    assert captured["url"].endswith(".json")
    assert captured["params"]["sort"] == "new"
    assert len(result["comments"]) == 2


def test_get_hackernews_comments_honors_max_depth_and_comment_limit(monkeypatch):
    payload = {
        "title": "HN post",
        "url": "https://example.com",
        "points": 10,
        "children": [
            {
                "type": "comment",
                "author": "u1",
                "text": "root",
                "children": [
                    {
                        "type": "comment",
                        "author": "u2",
                        "text": "child",
                        "children": [
                            {"type": "comment", "author": "u3", "text": "grandchild"},
                        ],
                    }
                ],
            }
        ],
    }

    def fake_get(url, timeout=None):
        return _FakeResponse(payload)

    monkeypatch.setattr(hn_tool.httpx, "get", fake_get)

    result = hn_tool.get_hackernews_comments("123", max_depth=1, comment_limit=2)

    assert len(result["comments"]) == 2
    assert all(c["depth"] <= 1 for c in result["comments"])
