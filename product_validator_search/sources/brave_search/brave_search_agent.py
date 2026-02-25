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
    material_supporting_evidence: list[str] = Field(default_factory=list)
    weak_supporting_evidence: list[str] = Field(default_factory=list)
    material_contradictions: list[str] = Field(default_factory=list)
    weak_contradictions: list[str] = Field(default_factory=list)
    deep_dive_actions_taken: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
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
Use `deep_dive_hypotheses` and `evidence_validation_rules` if present.
If "brave_search" is NOT in `selected_sources`, output "Source not selected." and stop.

## Steps (only if selected)

1. **Generate keywords** — Use `search_keywords` from the plan. Combine with terms like:
   - "market size [industry]"
   - "[problem] statistics"
   - "trends in [space] 2024"
   - "why [solution] fails"
   Prefer `validation_keywords` for the validation track and
   `invalidation_keywords` for the invalidation track. If those are missing,
   fall back to `search_keywords` and derive both supportive and skeptical
   variants from it. Also use `validation_focus` and `invalidation_focus` when present,
   otherwise fall back to `research_focus`.

2. **Validation track** — Call `search_brave` for at least 2 validation queries.

3. **Invalidation track** — Call `search_brave` for at least 2 invalidation
   queries designed to find failure signals and counterevidence.

4. **Synthesize** — Write a raw report summarizing:
   - Market size and growth data (if found)
   - Recent news or articles about the problem
   - Expert opinions found in blogs/articles
   - Common advice or warnings for this industry
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

5. **Adaptive refinement loop** — Before finalizing the report:
   - Run initial validation/invalidation probes first.
   - Run up to 2 conditional refinement rounds.
   - Trigger refinement when evidence is thin, conflicting, or high-impact on either side.
   - In each round, create up to 4 targeted follow-up queries from observed claims/entities.
   - Stop early when evidence is strong, convergent, and high-impact claims are resolved.
   - Use moderate corroboration for BOTH support and contradiction:
     - material = at least 2 independent datapoints in-source, OR 1 strong datapoint corroborated by another source.
     - weak = not sufficiently corroborated; cannot drive recommendation alone.
   - Treat social low-signal reactions (emoji jokes, one-off comments) as weak warnings unless corroborated.

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

Evidence reliability rules:
- Populate `material_supporting_evidence`, `weak_supporting_evidence`, `material_contradictions`, `weak_contradictions`, `deep_dive_actions_taken`, and `evidence_gaps`.
- Use moderate corroboration for BOTH support and contradiction:
  - material = at least 2 independent datapoints in-source, OR 1 strong datapoint corroborated by another source.
  - weak = not sufficiently corroborated.
- Weak evidence cannot drive recommendation changes alone.
- One-off social low-signal reactions are weak warnings unless corroborated.

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
