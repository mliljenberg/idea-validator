"""Prompt contract tests for adaptive evidence refinement and reliability rules."""

from product_validator_search.sources.brave_search.brave_search_agent import (
    brave_search_researcher,
    brave_search_validator,
)
from product_validator_search.sources.competitors.competitors_agent import (
    competitors_researcher,
    competitors_validator,
)
from product_validator_search.sources.github.github_agent import (
    github_researcher,
    github_validator,
)
from product_validator_search.sources.google_trends.google_trends_agent import (
    google_trends_researcher,
    google_trends_validator,
)
from product_validator_search.sources.hackernews.hackernews_agent import (
    hackernews_researcher,
    hackernews_validator,
)
from product_validator_search.sources.jobs_signal.jobs_signal_agent import (
    jobs_signal_researcher,
    jobs_signal_validator,
)
from product_validator_search.sources.openalex.openalex_agent import (
    openalex_researcher,
    openalex_validator,
)
from product_validator_search.sources.reddit.reddit_agent import (
    reddit_researcher,
    reddit_validator,
)
from product_validator_search.sources.review_sites.review_sites_agent import (
    review_sites_researcher,
    review_sites_validator,
)
from product_validator_search.sources.seo_intent.seo_intent_agent import (
    seo_intent_researcher,
    seo_intent_validator,
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

VALIDATORS = [
    brave_search_validator,
    competitors_validator,
    github_validator,
    google_trends_validator,
    hackernews_validator,
    jobs_signal_validator,
    openalex_validator,
    reddit_validator,
    review_sites_validator,
    seo_intent_validator,
]


def test_researchers_require_conditional_refinement_rounds():
    for researcher in RESEARCHERS:
        prompt = researcher.instruction
        assert "up to 2 conditional refinement rounds" in prompt, researcher.name
        assert "Trigger refinement when evidence is thin, conflicting, or high-impact" in prompt, researcher.name
        assert "Stop early when evidence is strong, convergent" in prompt, researcher.name
        assert "Deep-dive actions taken" in prompt, researcher.name
        assert "Evidence gaps" in prompt, researcher.name


def test_researchers_require_reliability_classification():
    for researcher in RESEARCHERS:
        prompt = researcher.instruction
        assert "Material supporting evidence" in prompt, researcher.name
        assert "Weak supporting evidence" in prompt, researcher.name
        assert "Material contradictions" in prompt, researcher.name
        assert "Weak contradictions" in prompt, researcher.name
        assert "moderate corroboration for BOTH support and contradiction" in prompt, researcher.name
        assert "social low-signal reactions" in prompt, researcher.name


def test_validators_require_symmetric_corroboration_rules():
    for validator in VALIDATORS:
        prompt = validator.instruction
        assert "Evidence reliability rules:" in prompt, validator.name
        assert "material_supporting_evidence" in prompt, validator.name
        assert "material_contradictions" in prompt, validator.name
        assert "moderate corroboration for BOTH support and contradiction" in prompt, validator.name
        assert "Weak evidence cannot drive recommendation changes alone." in prompt, validator.name
