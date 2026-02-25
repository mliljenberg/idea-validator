"""SEO intent research agent.

A SequentialAgent that researches commercial-intent search behavior.
"""

from __future__ import annotations

from typing import Literal

from google.adk.agents import LlmAgent, SequentialAgent
from pydantic import BaseModel, Field

from ...config import config
from .search_tool import search_seo_intent


class SeoIntentValidation(BaseModel):
    """Structured output produced by the SEO-intent validator agent."""

    recommendation: Literal["proceed", "pivot", "abandon"]
    signal_score: int = Field(ge=0, le=100)
    confidence: Literal["low", "medium", "high"]
    evidence_strength: int = Field(default=0, ge=0, le=100)
    evidence_quality: Literal["weak", "moderate", "strong"] = "weak"
    material_supporting_evidence: list[str] = Field(default_factory=list)
    weak_supporting_evidence: list[str] = Field(default_factory=list)
    material_contradictions: list[str] = Field(default_factory=list)
    weak_contradictions: list[str] = Field(default_factory=list)
    deep_dive_actions_taken: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    transactional_keyword_share: str = ""
    estimated_cpc_band: str = ""
    category_competitiveness: str = ""
    key_findings: list[str] = Field(default_factory=list)
    reasoning: str = ""


seo_intent_researcher = LlmAgent(
    name="seo_intent_researcher",
    model=config.worker_model,
    description="Searches commercial and informational keyword variants for intent mix.",
    instruction="""\
You are an SEO market-intent specialist.

## Getting your inputs
Read the `research_plan` from session state.
Use `deep_dive_hypotheses` and `evidence_validation_rules` if present.
If "seo_intent" is NOT in `selected_sources`, output "Source not selected." and stop.

## Steps (only if selected)
1. Build dual-track keywords from the plan:
   - Use `validation_keywords` for supportive probes.
   - Use `invalidation_keywords` for disconfirming probes.
   - If either is missing, fall back to `search_keywords` and derive both
     supportive and skeptical variants.
   - Use `validation_focus` and `invalidation_focus` when present, otherwise
     use `research_focus`.
2. Run at least 2 validation queries with `search_seo_intent`.
3. Run at least 2 invalidation queries with `search_seo_intent`.
4. Write a raw report covering:
   - apparent transactional vs informational intent balance
   - snippets indicating pricing/comparison behavior
   - category competitiveness clues from SERP composition
   - estimated CPC band as low/medium/high proxy based on SERP commerciality
   The raw report MUST include:
   - Supporting evidence
   - Disconfirming evidence
   - Contradictions
   - Data quality gaps
   - Material supporting evidence (corroborated)
   - Weak supporting evidence (non-decisive)
   - Material contradictions (corroborated)
   - Weak contradictions (warning-only unless corroborated)
   - Deep-dive actions taken
   - Evidence gaps
   - Provisional source verdict: `pass`, `warning`, or `fail`

5. Adaptive refinement loop before finalizing:
   - Run initial validation/invalidation probes first.
   - Run up to 2 conditional refinement rounds.
   - Trigger refinement when evidence is thin, conflicting, or high-impact on either side.
   - In each round, create up to 4 targeted follow-up queries from observed claims/entities.
   - Stop early when evidence is strong, convergent, and high-impact claims are resolved.
   - Use moderate corroboration for BOTH support and contradiction:
     - material = at least 2 independent datapoints in-source, OR 1 strong datapoint corroborated by another source.
     - weak = not sufficiently corroborated; cannot drive recommendation alone.
   - Treat social low-signal reactions (emoji jokes, one-off comments) as weak warnings unless corroborated.

Save to `seo_intent_raw_report`.
""",
    tools=[search_seo_intent],
    output_key="seo_intent_raw_report",
)

seo_intent_validator = LlmAgent(
    name="seo_intent_validator",
    model=config.critic_model,
    description="Validates and synthesizes SEO intent signals.",
    instruction="""\
You are a critical product analyst evaluating SEO intent data.
Read `seo_intent_raw_report` and output `SeoIntentValidation`.

Evidence reliability rules:
- Populate `material_supporting_evidence`, `weak_supporting_evidence`, `material_contradictions`, `weak_contradictions`, `deep_dive_actions_taken`, and `evidence_gaps`.
- Use moderate corroboration for BOTH support and contradiction:
  - material = at least 2 independent datapoints in-source, OR 1 strong datapoint corroborated by another source.
  - weak = not sufficiently corroborated.
- Weak evidence cannot drive recommendation changes alone.
- One-off social low-signal reactions are weak warnings unless corroborated.

Recommendation rules:
- Default to skeptical: SERP evidence is directional and noisy.
- Use `proceed` only when transactional intent is meaningfully present and competitive pressure is manageable.
- Use `pivot` when intent exists but is mostly informational or concentrated in adjacent use cases.
- Use `abandon` when commercial intent is weak and category competitiveness is extreme.
""",
    output_schema=SeoIntentValidation,
    output_key="seo_intent_validation",
)

seo_intent_agent = SequentialAgent(
    name="seo_intent_agent",
    description="Researches transactional search intent for the product category.",
    sub_agents=[seo_intent_researcher, seo_intent_validator],
)
