"""Smoke test to verify imports and agent construction."""

import pytest
from product_validator_search.agent import (
    root_agent,
    market_research,
    community_tech_research,
)


def test_imports():
    """Verify that the main agent and batched sub-agents can be imported."""
    assert root_agent is not None
    assert market_research is not None
    assert community_tech_research is not None

    # Check Batch 1: Market Research (3 agents)
    # Brave Search, Google Trends, Competitors
    assert len(market_research.sub_agents) == 3
    market_names = {agent.name for agent in market_research.sub_agents}
    assert market_names == {
        "brave_search_agent",
        "google_trends_agent",
        "competitors_agent",
    }

    # Check Batch 2: Community & Tech (4 agents)
    # HackerNews, Reddit, GitHub, OpenAlex
    assert len(community_tech_research.sub_agents) == 4
    tech_names = {agent.name for agent in community_tech_research.sub_agents}
    assert tech_names == {
        "hackernews_agent",
        "reddit_agent",
        "github_agent",
        "openalex_agent",
    }
