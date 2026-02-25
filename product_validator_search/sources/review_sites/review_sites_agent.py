"""Review sites research agent.

A SequentialAgent that researches buyer intent on review platforms.
"""

from __future__ import annotations

from typing import Literal

from google.adk.agents import LlmAgent, SequentialAgent
from pydantic import BaseModel, Field

from ...config import config
from .search_tool import search_review_sites


class ReviewSitesValidation(BaseModel):
    """Structured output produced by the review-sites validator agent."""

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
    review_volume_signal: str = ""
    avg_rating_signal: str = ""
    top_switching_reasons: list[str] = Field(default_factory=list)
    price_sensitivity_mentions: list[str] = Field(default_factory=list)
    key_findings: list[str] = Field(default_factory=list)
    reasoning: str = ""


review_sites_researcher = LlmAgent(
    name="review_sites_researcher",
    model=config.worker_model,
    description="Searches review platforms for paid-intent and switching signals.",
    instruction="""\
You are a buyer-intent research specialist focusing on review platforms.

## Getting your inputs
Read the `research_plan` from session state.
Use `deep_dive_hypotheses` and `evidence_validation_rules` if present.
If "review_sites" is NOT in `selected_sources`, output "Source not selected." and stop.

## Steps (only if selected)
1. Build dual-track keywords from the plan:
   - Use `validation_keywords` for supportive probes.
   - Use `invalidation_keywords` for disconfirming probes.
   - If either is missing, fall back to `search_keywords` and derive both
     supportive and skeptical variants.
   - Use `validation_focus` and `invalidation_focus` when present, otherwise
     use `research_focus`.
2. Run at least 2 validation queries with `search_review_sites`.
3. Run at least 2 invalidation queries with `search_review_sites`.
4. Write a raw report covering:
   - review volume and recency clues
   - rating distribution clues from snippets
   - explicit switching reasons ("moved from X to Y")
   - pricing complaints and willingness-to-pay language
   - strongest unmet needs found across G2/Capterra/Trustpilot snippets
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

Save to `review_sites_raw_report`.
""",
    tools=[search_review_sites],
    output_key="review_sites_raw_report",
)

review_sites_validator = LlmAgent(
    name="review_sites_validator",
    model=config.critic_model,
    description="Validates and synthesizes review-site evidence.",
    instruction="""\
You are a critical product analyst evaluating buyer intent from review sites.
Read `review_sites_raw_report` and output `ReviewSitesValidation`.

Evidence reliability rules:
- Populate `material_supporting_evidence`, `weak_supporting_evidence`, `material_contradictions`, `weak_contradictions`, `deep_dive_actions_taken`, and `evidence_gaps`.
- Use moderate corroboration for BOTH support and contradiction:
  - material = at least 2 independent datapoints in-source, OR 1 strong datapoint corroborated by another source.
  - weak = not sufficiently corroborated.
- Weak evidence cannot drive recommendation changes alone.
- One-off social low-signal reactions are weak warnings unless corroborated.

Recommendation rules:
- Default to skeptical if data is thin or stale.
- Use `proceed` only if there is clear dissatisfaction with incumbents and concrete switching intent.
- Use `pivot` if demand exists but pain points suggest a different wedge/segment.
- Use `abandon` if there is weak demand signal or incumbents already satisfy core needs.
""",
    output_schema=ReviewSitesValidation,
    output_key="review_sites_validation",
)

review_sites_agent = SequentialAgent(
    name="review_sites_agent",
    description="Researches buyer-intent signals on public review platforms.",
    sub_agents=[review_sites_researcher, review_sites_validator],
)
