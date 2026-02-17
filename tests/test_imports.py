"""Smoke test to verify imports and agent construction."""

import pytest
from product_validator_search.agent import (
    root_agent,
    market_research,
    buyer_intent_research,
    community_tech_research,
)
from product_validator_search.resilient_parallel_agent import ResilientParallelAgent


def test_imports():
    """Verify that the main agent and batched sub-agents can be imported."""
    assert root_agent is not None
    assert market_research is not None
    assert buyer_intent_research is not None
    assert community_tech_research is not None
    assert isinstance(market_research, ResilientParallelAgent)
    assert isinstance(buyer_intent_research, ResilientParallelAgent)
    assert isinstance(community_tech_research, ResilientParallelAgent)

    # Check Batch 1: Market Research (3 agents)
    # Brave Search, Google Trends, Competitors
    assert len(market_research.sub_agents) == 3
    market_names = {agent.name for agent in market_research.sub_agents}
    assert market_names == {
        "brave_search_agent",
        "google_trends_agent",
        "competitors_agent",
    }

    # Check Batch 2: Buyer Intent (3 agents)
    # Review sites, jobs, SEO intent
    assert len(buyer_intent_research.sub_agents) == 3
    buyer_names = {agent.name for agent in buyer_intent_research.sub_agents}
    assert buyer_names == {
        "review_sites_agent",
        "jobs_signal_agent",
        "seo_intent_agent",
    }

    # Check Batch 3: Community & Tech (4 agents)
    # HackerNews, Reddit, GitHub, OpenAlex
    assert len(community_tech_research.sub_agents) == 4
    tech_names = {agent.name for agent in community_tech_research.sub_agents}
    assert tech_names == {
        "hackernews_agent",
        "reddit_agent",
        "github_agent",
        "openalex_agent",
    }
