"""Tests for buyer-intent source expansion and stricter synthesis rules."""

from product_validator_search.agent import (
    ResearchPlan,
    SOURCE_NAMES,
    final_validator,
    plan_generator,
    market_research,
    buyer_intent_research,
)
from product_validator_search.config import config
from product_validator_search.resilient_parallel_agent import ResilientParallelAgent
from product_validator_search.sources.jobs_signal.jobs_signal_agent import (
    JobsSignalValidation,
    jobs_signal_researcher,
)
from product_validator_search.sources.review_sites.review_sites_agent import (
    ReviewSitesValidation,
    review_sites_researcher,
)
from product_validator_search.sources.seo_intent.seo_intent_agent import (
    SeoIntentValidation,
    seo_intent_researcher,
)


def test_new_sources_registered():
    assert isinstance(market_research, ResilientParallelAgent)
    assert isinstance(buyer_intent_research, ResilientParallelAgent)
    assert "review_sites" in SOURCE_NAMES
    assert "jobs_signal" in SOURCE_NAMES
    assert "seo_intent" in SOURCE_NAMES

    buyer_names = {agent.name for agent in buyer_intent_research.sub_agents}
    assert "review_sites_agent" in buyer_names
    assert "jobs_signal_agent" in buyer_names
    assert "seo_intent_agent" in buyer_names


def test_research_plan_supports_dual_hypothesis_fields():
    model_fields = ResearchPlan.model_fields
    assert "validation_keywords" in model_fields
    assert "invalidation_keywords" in model_fields
    assert "validation_focus" in model_fields
    assert "invalidation_focus" in model_fields
    assert "falsification_criteria" in model_fields
    assert "deep_dive_hypotheses" in model_fields
    assert "evidence_validation_rules" in model_fields


def test_plan_generator_requires_invalidation_track():
    prompt = plan_generator.instruction
    assert "Thesis + anti-thesis required" in prompt
    assert "validation_keywords" in prompt
    assert "invalidation_keywords" in prompt
    assert "falsification_criteria" in prompt
    assert "deep_dive_hypotheses" in prompt
    assert "evidence_validation_rules" in prompt
    assert "Material evidence requires" in prompt
    assert "Source rationale must mention invalidation value" in prompt


def test_buyer_intent_validation_schemas():
    review = ReviewSitesValidation(
        recommendation="pivot",
        signal_score=58,
        confidence="medium",
        evidence_strength=60,
        evidence_quality="moderate",
        review_volume_signal="Moderate volume in last 12 months",
        avg_rating_signal="3.9/5 weighted estimate",
        top_switching_reasons=["Poor onboarding", "Weak integrations"],
        price_sensitivity_mentions=["Too expensive for SMB", "Pricing is unclear"],
        reasoning="Clear pain exists, but wedge is not yet differentiated.",
    )
    assert review.recommendation == "pivot"
    assert review.evidence_quality == "moderate"

    jobs = JobsSignalValidation(
        recommendation="proceed",
        signal_score=74,
        confidence="medium",
        evidence_strength=71,
        evidence_quality="strong",
        hiring_velocity_signal="Consistent openings across enterprise firms",
        roles_related_to_problem=["RevOps Analyst", "Sales Enablement Manager"],
        enterprise_adoption_clues=["Implementation roles mention budget ownership"],
        reasoning="Budget urgency appears sustained across multiple industries.",
    )
    assert jobs.recommendation == "proceed"
    assert jobs.evidence_strength >= 70

    seo = SeoIntentValidation(
        recommendation="abandon",
        signal_score=32,
        confidence="low",
        evidence_strength=35,
        evidence_quality="weak",
        transactional_keyword_share="Low (~15%)",
        estimated_cpc_band="low",
        category_competitiveness="high",
        reasoning="Commercial intent is weak in this category.",
    )
    assert seo.recommendation == "abandon"
    assert seo.evidence_quality == "weak"


def test_new_researchers_preserve_skip_behavior():
    assert 'If "review_sites" is NOT in `selected_sources`' in review_sites_researcher.instruction
    assert 'If "jobs_signal" is NOT in `selected_sources`' in jobs_signal_researcher.instruction
    assert 'If "seo_intent" is NOT in `selected_sources`' in seo_intent_researcher.instruction


def test_final_validator_includes_evidence_and_contradictions_rules():
    prompt = final_validator.instruction
    assert "## Evidence Quality" in prompt
    assert "## Contradictions" in prompt
    assert "## What Would Invalidate This Idea" in prompt
    assert "## What Was Actually Invalidated" in prompt
    assert "## Falsification Criteria Check" in prompt
    assert "## Supporting Evidence Reliability Assessment" in prompt
    assert "## Contradiction Reliability Assessment" in prompt
    assert "## Deep-Dive Verification Outcomes" in prompt
    assert "## Net Evidence Conclusion" in prompt
    assert "## Why This Might Still Fail" in prompt
    assert "source citation" in prompt
    assert "contradiction penalty" in prompt
    assert "critical invalidation findings" in prompt
    assert "falsification criteria" in prompt
    assert "Weak supporting evidence cannot count toward `PROCEED` thresholds." in prompt
    assert "Weak contradictions reduce confidence" in prompt
    assert "Cap confidence at `medium`" in prompt
    assert "reason taxonomy tag" in prompt


def test_source_weight_config_defaults():
    expected = {
        "review_sites",
        "competitors",
        "google_trends",
        "github",
        "reddit",
        "hackernews",
        "openalex",
        "brave_search",
        "jobs_signal",
        "seo_intent",
    }
    assert set(config.source_evidence_weights) == expected
    assert config.source_evidence_weights["review_sites"] > config.source_evidence_weights["reddit"]
    assert config.adaptive_refinement_rounds == 2
    assert config.adaptive_run_condition == "conditional"
    assert config.adaptive_max_queries_per_round == 4
    assert config.evidence_corroboration_bar == "moderate"
    assert config.social_weak_signal_max_impact == "warning"
