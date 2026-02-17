"""Competitor Scout agent.

A SequentialAgent that uses Brave Search to specifically hunt for
competitors on Product Hunt, AppSumo, X (Twitter), and AlternativeTo.
"""

from __future__ import annotations

from typing import Literal

from google.adk.agents import LlmAgent, SequentialAgent
from pydantic import BaseModel, Field

from ...config import config
from ..brave_search.search_tool import search_brave


class CompetitorValidation(BaseModel):
    """Structured output produced by the Competitor Scout validator agent."""

    recommendation: Literal["proceed", "pivot", "abandon"]
    signal_score: int = Field(ge=0, le=100)
    confidence: Literal["low", "medium", "high"]
    identified_competitors: list[str] = Field(default_factory=list)
    feature_gaps: list[str] = Field(default_factory=list)
    pricing_insights: str = ""
    differentiation_opportunities: list[str] = Field(default_factory=list)
    reasoning: str = ""


competitors_researcher = LlmAgent(
    name="competitors_researcher",
    model=config.worker_model,
    description="Scouts for competitors on Product Hunt, AppSumo, and social media.",
    instruction="""\
You are a Competitive Intelligence Scout. Your job is to find direct and indirect competitors
by searching specific platforms known for launching new products.

## Getting your inputs
Read the `research_plan` from session state.
If "competitors" is NOT in `selected_sources`, output "Source not selected." and stop.

## Steps (only if selected)

1. **Construct Site-Specific Queries** — Use `product_idea` and keywords to search:
   - `site:producthunt.com [keywords]` (Find launches)
   - `site:appsumo.com [keywords]` (Find lifetime deals/SaaS)
   - `site:alternativeto.net [keywords]` (Find software categories)
   - `site:x.com [keywords] "launching"` or `"built"` (Find indie hacker projects)
   - `site:reddit.com [keywords] "competitor"` (Find user discussions about competitors)

2. **Search** — Use the `search_brave` tool for these targeted queries.

3. **Analyze & Report** — Write a raw report detailing:
   - List of Competitors (Names + URLs)
   - Their core value proposition (from snippets)
   - Pricing info (if visible in snippets like "$49 lifetime")
   - User feedback/ratings found in search snippets

Save to `competitors_raw_report`.
""",
    tools=[search_brave],
    output_key="competitors_raw_report",
)

competitors_validator = LlmAgent(
    name="competitors_validator",
    model=config.critic_model,
    description="Validates and synthesizes the competitor research report.",
    instruction="""\
You are a Strategy Consultant. Read `competitors_raw_report` and analyze the landscape.

Focus on:
- **Direct vs Indirect**: Who solves the EXACT same problem vs. adjacent problems?
- **Saturation**: Are there 50 clones or just 2 big players?
- **Gaps**: What are they all missing? (Pricing, features, UX?)

Recommendation rules:
- Default to skeptical in crowded categories.
- Use `proceed` only when a concrete, defensible gap is visible and competitors fail on it.
- Use `pivot` when market demand is real but your current concept is not differentiated enough.
- Use `abandon` when competitor density is high and no credible wedge appears.

Output structured `CompetitorValidation`.
""",
    output_schema=CompetitorValidation,
    output_key="competitors_validation",
)

competitors_agent = SequentialAgent(
    name="competitors_agent",
    description="Scouts for competitors on Product Hunt, AppSumo, and X.",
    sub_agents=[competitors_researcher, competitors_validator],
)
