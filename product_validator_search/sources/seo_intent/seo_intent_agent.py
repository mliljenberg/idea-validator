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
If "seo_intent" is NOT in `selected_sources`, output "Source not selected." and stop.

## Steps (only if selected)
1. Build 3-5 focused keywords from `search_keywords` and `product_idea`.
2. Call `search_seo_intent` to compare informational and transactional query variants.
3. Write a raw report covering:
   - apparent transactional vs informational intent balance
   - snippets indicating pricing/comparison behavior
   - category competitiveness clues from SERP composition
   - estimated CPC band as low/medium/high proxy based on SERP commerciality

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
