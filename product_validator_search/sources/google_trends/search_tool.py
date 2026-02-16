"""Google Trends search tools.

Provides two ADK-compatible tool functions:
  - get_trends_interest_over_time: fetch interest-over-time data for keywords
  - get_trends_related_queries: fetch related queries for a keyword
"""

from __future__ import annotations

from typing import Any


def get_trends_interest_over_time(
    keywords: list[str], timeframe: str = "today 12-m", geo: str = "US"
) -> dict[str, Any]:
    """Get Google Trends interest-over-time data for up to 5 keywords.

    Args:
        keywords: A list of 1-5 keywords to compare.
        timeframe: Trends timeframe string (default 'today 12-m').
        geo: Two-letter country code (default 'US').

    Returns:
        A dict with 'keywords', 'timeframe', 'geo', and 'trends' — a dict
        mapping each keyword to its trend data (first_value, latest_value,
        avg_value, series of date->value pairs).
    """
    from pytrends.request import TrendReq

    keywords = [kw[:100] for kw in keywords[:5] if kw]
    if not keywords:
        return {"keywords": [], "timeframe": timeframe, "geo": geo, "trends": {}}

    pytrends = TrendReq(hl="en-US", tz=360)
    pytrends.build_payload(keywords, timeframe=timeframe, geo=geo)
    df = pytrends.interest_over_time()

    if df.empty:
        return {"keywords": keywords, "timeframe": timeframe, "geo": geo, "trends": {}}

    trends: dict[str, Any] = {}
    for kw in keywords:
        if kw not in df.columns:
            continue
        series = {str(idx.date()): int(val) for idx, val in df[kw].items()}
        values = list(series.values())
        trends[kw] = {
            "first_value": values[0] if values else 0,
            "latest_value": values[-1] if values else 0,
            "avg_value": round(sum(values) / len(values), 1) if values else 0,
            "num_data_points": len(values),
            "series": series,
        }

    return {
        "keywords": keywords,
        "timeframe": timeframe,
        "geo": geo,
        "trends": trends,
    }


def get_trends_related_queries(keyword: str) -> dict[str, Any]:
    """Get related queries for a keyword from Google Trends.

    Args:
        keyword: The keyword to look up related queries for.

    Returns:
        A dict with 'keyword', 'top_queries', and 'rising_queries'.
        Each is a list of dicts with 'query' and 'value'.
    """
    from pytrends.request import TrendReq

    keyword = keyword[:100]
    pytrends = TrendReq(hl="en-US", tz=360)
    pytrends.build_payload([keyword], timeframe="today 12-m", geo="US")
    related = pytrends.related_queries()

    top_queries: list[dict[str, Any]] = []
    rising_queries: list[dict[str, Any]] = []

    kw_data = related.get(keyword, {})

    top_df = kw_data.get("top")
    if top_df is not None and not top_df.empty:
        for _, row in top_df.head(10).iterrows():
            top_queries.append(
                {"query": str(row.get("query", "")), "value": int(row.get("value", 0))}
            )

    rising_df = kw_data.get("rising")
    if rising_df is not None and not rising_df.empty:
        for _, row in rising_df.head(10).iterrows():
            rising_queries.append(
                {"query": str(row.get("query", "")), "value": str(row.get("value", ""))}
            )

    return {
        "keyword": keyword,
        "top_queries": top_queries,
        "rising_queries": rising_queries,
    }
