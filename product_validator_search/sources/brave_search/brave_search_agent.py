"""Brave Search research agent.

A SequentialAgent that researches a product idea using Brave Search API.
"""

from __future__ import annotations

from typing import Literal

from google.adk.agents import LlmAgent, SequentialAgent
from pydantic import BaseModel, Field

from ...config import config
from .search_tool import search_brave


class BraveSearchValidation(BaseModel):
    """Structured output produced by the Brave Search validator agent."""

    recommendation: Literal["proceed", "pivot", "abandon"]
    signal_score: int = Field(ge=0, le=100)
    confidence: Literal["low", "medium", "high"]
    evidence_strength: int = Field(default=0, ge=0, le=100)
    evidence_quality: Literal["weak", "moderate", "strong"] = "weak"
    key_findings: list[str] = Field(default_factory=list)
    market_trends: list[str] = Field(default_factory=list)
    consumer_sentiment: str = ""
    reasoning: str = ""


brave_search_researcher = LlmAgent(
    name="brave_search_researcher",
    model=config.worker_model,
    description="Uses Brave Search to find market reports, articles, and general validation signals.",
    instruction="""\
You are a Market Research Specialist using Brave Search.
Your goal is to find high-level market signals, trends, and articles validation the problem space.

## Getting your inputs
Read the `research_plan` from session state.
If "brave_search" is NOT in `selected_sources`, output "Source not selected." and stop.

## Steps (only if selected)

1. **Generate keywords** — Use `search_keywords` from the plan. Combine with terms like:
   - "market size [industry]"
   - "[problem] statistics"
   - "trends in [space] 2024"
   - "why [solution] fails"

2. **Search** — Call `search_brave` for 3-5 distinct queries.

3. **Synthesize** — Write a raw report summarizing:
   - Market size and growth data (if found)
   - Recent news or articles about the problem
   - Expert opinions found in blogs/articles
   - Common advice or warnings for this industry

Save to `brave_search_raw_report`.
""",
    tools=[search_brave],
    output_key="brave_search_raw_report",
)

brave_search_validator = LlmAgent(
    name="brave_search_validator",
    model=config.critic_model,
    description="Validates and synthesizes a raw Brave Search research report.",
    instruction="""\
You are a Market Analyst. Read `brave_search_raw_report` and produce a structured assessment.

Focus on:
- **Macro Trends**: Is the market growing or shrinking?
- **Timing**: Is this the right time for this idea?
- **Saturation**: Does the search volume suggest a crowded market?

Recommendation rules:
- Default to skeptical. Broad market buzz is not enough.
- Use `proceed` only when market growth, timing, and whitespace align clearly.
- Use `pivot` when demand exists but current positioning is weak or crowded.
- Use `abandon` when market signals are weak/declining or competition is too entrenched for the current concept.

Output structured `BraveSearchValidation`.
""",
    output_schema=BraveSearchValidation,
    output_key="brave_search_validation",
)

brave_search_agent = SequentialAgent(
    name="brave_search_agent",
    description="Researches a product idea using Brave Search.",
    sub_agents=[brave_search_researcher, brave_search_validator],
)
