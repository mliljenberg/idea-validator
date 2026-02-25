"""Prompt contract tests for dual-track validation and invalidation research."""

import re

from product_validator_search.sources.brave_search.brave_search_agent import (
    brave_search_researcher,
)
from product_validator_search.sources.competitors.competitors_agent import (
    competitors_researcher,
)
from product_validator_search.sources.github.github_agent import github_researcher
from product_validator_search.sources.google_trends.google_trends_agent import (
    google_trends_researcher,
)
from product_validator_search.sources.hackernews.hackernews_agent import (
    hackernews_researcher,
)
from product_validator_search.sources.jobs_signal.jobs_signal_agent import (
    jobs_signal_researcher,
)
from product_validator_search.sources.openalex.openalex_agent import (
    openalex_researcher,
)
from product_validator_search.sources.reddit.reddit_agent import reddit_researcher
from product_validator_search.sources.review_sites.review_sites_agent import (
    review_sites_researcher,
)
from product_validator_search.sources.seo_intent.seo_intent_agent import (
    seo_intent_researcher,
)


RESEARCHERS = [
    brave_search_researcher,
    competitors_researcher,
    github_researcher,
    google_trends_researcher,
    hackernews_researcher,
    jobs_signal_researcher,
    openalex_researcher,
    reddit_researcher,
    review_sites_researcher,
    seo_intent_researcher,
]


def test_researchers_require_dual_track_keywords_with_fallback():
    for researcher in RESEARCHERS:
        prompt = researcher.instruction
        lowered = prompt.lower()
        assert "validation_keywords" in prompt, researcher.name
        assert "invalidation_keywords" in prompt, researcher.name
        assert "search_keywords" in prompt, researcher.name
        assert ("validation_focus" in prompt or "research_focus" in prompt), researcher.name
        assert ("invalidation_focus" in prompt or "research_focus" in prompt), researcher.name
        assert "fall back" in lowered, researcher.name


def test_researchers_require_validation_and_invalidation_probes():
    for researcher in RESEARCHERS:
        lowered = researcher.instruction.lower()
        assert re.search(r"at least\s+2\s+validation", lowered), researcher.name
        assert re.search(r"at least\s+2\s+invalidation", lowered), researcher.name


def test_researchers_require_disconfirming_output_sections():
    for researcher in RESEARCHERS:
        prompt = researcher.instruction
        assert "Supporting evidence" in prompt, researcher.name
        assert "Disconfirming evidence" in prompt, researcher.name
        assert "Contradictions" in prompt, researcher.name
        assert "Data quality gaps" in prompt, researcher.name
        assert "Provisional source verdict" in prompt, researcher.name


def test_researchers_require_social_weak_signal_and_symmetric_corroboration():
    for researcher in RESEARCHERS:
        prompt = researcher.instruction
        assert "moderate corroboration for BOTH support and contradiction" in prompt, researcher.name
        assert "social low-signal reactions" in prompt, researcher.name
