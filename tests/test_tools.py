from __future__ import annotations

from datetime import datetime

from product_validator.agent import ResearchAgent
from product_validator.models import PainPoint, ResearchPlan
from product_validator.scoring import calculate_signal_score
from product_validator.tools.arxiv import ArxivTool
from product_validator.tools.crunchbase import CrunchbaseTool
from product_validator.tools.github import GitHubTool
from product_validator.tools.google_trends import GoogleTrendsTool
from product_validator.tools.hackernews import HackerNewsTool
from product_validator.tools.openalex import OpenAlexTool
from product_validator.tools.producthunt import ProductHuntTool
from product_validator.tools.stackoverflow import StackOverflowTool


def test_github_parse_payload():
    payload = {
        "total_count": 1,
        "items": [
            {
                "full_name": "acme/email-ai",
                "html_url": "https://github.com/acme/email-ai",
                "stargazers_count": 120,
                "open_issues_count": 40,
                "language": "Python",
                "updated_at": "2026-02-10T00:00:00Z",
                "description": "Email summarizer",
            }
        ],
    }
    result = GitHubTool().parse_payload(payload)
    assert result.open_source_alternatives
    assert result.similar_projects
    assert result.pain_points


def test_stackoverflow_parse_payload():
    payload = {
        "items": [
            {
                "title": "How to summarize long email threads?",
                "link": "https://stackoverflow.com/q/1",
                "answer_count": 0,
                "score": 0,
            }
        ]
    }
    result = StackOverflowTool().parse_payload(payload)
    assert len(result.pain_points) == 1
    assert len(result.feature_requests) == 1


def test_hackernews_parse_payload():
    payload = {
        "nbHits": 1,
        "hits": [
            {
                "title": "We built an AI email summary tool",
                "url": "https://example.com/post",
                "points": 42,
                "objectID": "123",
            }
        ],
    }
    result = HackerNewsTool().parse_payload(payload)
    assert result.pain_points
    assert result.competitors


def test_openalex_parse_payload():
    payload = {
        "meta": {"count": 1},
        "results": [
            {
                "display_name": "Large language models for customer support automation",
                "id": "https://openalex.org/W1",
                "cited_by_count": 11,
            }
        ],
    }
    result = OpenAlexTool().parse_payload(payload)
    assert result.pain_points


def test_arxiv_parse_payload():
    xml_payload = """
    <feed xmlns=\"http://www.w3.org/2005/Atom\">
      <entry>
        <id>http://arxiv.org/abs/1234.5678</id>
        <title>AI for ticket routing</title>
        <summary>Paper discusses routing and tagging support tickets.</summary>
      </entry>
    </feed>
    """
    result = ArxivTool().parse_payload(xml_payload)
    assert result.pain_points


def test_scoring_thresholds():
    agent = ResearchAgent(tools=[])
    report = agent.aggregate_results(
        idea="AI tool for support ticket tagging",
        category="customer-support",
        results=[],
    )
    assert report.recommendation in {"proceed", "pivot", "abandon"}
    assert 0 <= report.signal_score <= 100
    assert "should" in report.conclusion_paragraph


def test_product_hunt_parse_payload():
    payload = {
        "data": {
            "posts": {
                "edges": [
                    {
                        "node": {
                            "name": "Inbox Brief",
                            "tagline": "AI email thread summarizer for teams",
                            "createdAt": "2026-02-01T00:00:00Z",
                            "votesCount": 250,
                            "url": "https://www.producthunt.com/posts/inbox-brief",
                        }
                    }
                ]
            }
        }
    }
    result = ProductHuntTool().parse_payload(payload, idea="email summarizer", category="productivity")
    assert len(result.successful_launches) == 1
    assert len(result.competitors) == 1


def test_crunchbase_parse_payload():
    payload = {
        "entities": [
            {
                "identifier": {"permalink": "/organization/acme"},
                "properties": {
                    "organization_identifier": {"value": "Acme"},
                    "money_raised": {"value_usd": 1000000},
                    "announced_on": {"value": "2026-01-10"},
                },
            }
        ]
    }
    result = CrunchbaseTool().parse_payload(payload)
    assert len(result.recent_funding) == 1


def test_verified_pain_points_marked():
    agent = ResearchAgent(tools=[])
    pain_points = [
        PainPoint(quote="ticket tagging is inaccurate for many teams", source="GitHub issues", url="a"),
        PainPoint(quote="ticket tagging is inaccurate in our setup", source="Stack Overflow", url="b"),
        PainPoint(quote="ticket tagging is inaccurate and noisy", source="Hacker News", url="c"),
    ]
    marked = agent._mark_verified_pain_points(pain_points)
    assert sum(1 for p in marked if p.verified) == 3


def test_create_plan_contains_sources_and_steps():
    agent = ResearchAgent()
    plan = agent.create_plan(
        idea="AI tool that summarizes long email threads",
        category="productivity",
        user_updates="focus on B2B support teams",
    )
    assert plan.idea
    assert len(plan.sources) >= 1
    assert len(plan.execution_steps) >= 3
    assert plan.approved is False


def test_research_requires_approved_plan():
    agent = ResearchAgent(tools=[])
    plan = ResearchPlan(
        idea="Browser extension that blocks distracting sites",
        category="productivity",
        objective="Validate market",
        sources=[],
        approved=False,
    )
    try:
        import asyncio

        asyncio.run(agent.research_with_plan(plan))
        assert False, "Expected ValueError for unapproved plan"
    except ValueError:
        assert True
