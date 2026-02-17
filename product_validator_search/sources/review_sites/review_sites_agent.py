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
If "review_sites" is NOT in `selected_sources`, output "Source not selected." and stop.

## Steps (only if selected)
1. Build 3-5 focused keywords from `search_keywords` and `product_idea`.
2. Call `search_review_sites` with those keywords.
3. Write a raw report covering:
   - review volume and recency clues
   - rating distribution clues from snippets
   - explicit switching reasons ("moved from X to Y")
   - pricing complaints and willingness-to-pay language
   - strongest unmet needs found across G2/Capterra/Trustpilot snippets

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
