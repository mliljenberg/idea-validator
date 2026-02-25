"""GitHub research agent.

A SequentialAgent that researches a product idea on GitHub using public REST API.
"""

from __future__ import annotations

from typing import Literal

from google.adk.agents import LlmAgent, SequentialAgent
from pydantic import BaseModel, Field

from ...config import config
from .search_tool import search_github


class GitHubValidation(BaseModel):
    """Structured output produced by the GitHub validator agent."""

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
    competitors_mentioned: list[str] = Field(default_factory=list)
    technical_feasibility: str = ""
    reasoning: str = ""


github_researcher = LlmAgent(
    name="github_researcher",
    model=config.worker_model,
    description="Searches GitHub for open source projects relevant to a product idea.",
    instruction="""\
You are a GitHub research specialist. Your job is to find existing open source
solutions, libraries, or competitors for a product idea.

## Getting your inputs
Read the `research_plan` from session state.
Use `deep_dive_hypotheses` and `evidence_validation_rules` if present.
If "github" is NOT in `selected_sources`, output "Source not selected." and stop.

## Steps (only if selected)

1. **Generate keywords** — Use `search_keywords` from the plan. Focus on
   technical terms, library names, and "open source [solution]".
   Prefer `validation_keywords` for supportive checks and
   `invalidation_keywords` for disconfirming checks. If either is missing,
   fall back to `search_keywords` and derive both supportive and skeptical
   variants. Use `validation_focus` and `invalidation_focus` when present,
   otherwise use `research_focus`.

2. **Validation track search** — Call `search_github` for at least
   2 validation queries.

3. **Invalidation track search** — Call `search_github` for at least
   2 invalidation queries designed to find commoditization, mature open-source
   substitutes, and low technical moat.

4. **Select top 5** — Pick the 5 most relevant repositories (stars are good,
   but relevance and recency matter more).

5. **Compose report** — Write a raw report including:
   - Repo names, URLs, star counts
   - Descriptions and key features
   - "How it works" technical details if available
   - License (permissive vs copyleft) if mentioned
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

6. **Adaptive refinement loop** — Before finalizing the report:
   - Run initial validation/invalidation probes first.
   - Run up to 2 conditional refinement rounds.
   - Trigger refinement when evidence is thin, conflicting, or high-impact on either side.
   - In each round, create up to 4 targeted follow-up queries from observed claims/entities.
   - Stop early when evidence is strong, convergent, and high-impact claims are resolved.
   - Use moderate corroboration for BOTH support and contradiction:
     - material = at least 2 independent datapoints in-source, OR 1 strong datapoint corroborated by another source.
     - weak = not sufficiently corroborated; cannot drive recommendation alone.
   - Treat social low-signal reactions (emoji jokes, one-off comments) as weak warnings unless corroborated.

Save to `github_raw_report`.
""",
    tools=[search_github],
    output_key="github_raw_report",
)

github_validator = LlmAgent(
    name="github_validator",
    model=config.critic_model,
    description="Validates and synthesizes a raw GitHub research report.",
    instruction="""\
You are a technical product analyst evaluating GitHub repositories.
Read `github_raw_report` and produce a structured assessment.

Focus on:
- **Prior Art**: Does this already exist as a free open-source tool?
- **Commoditization**: Is the core value prop just a wrapper around a library?
- **Developer Interest**: Are people starring/forking these projects?

Evidence reliability rules:
- Populate `material_supporting_evidence`, `weak_supporting_evidence`, `material_contradictions`, `weak_contradictions`, `deep_dive_actions_taken`, and `evidence_gaps`.
- Use moderate corroboration for BOTH support and contradiction:
  - material = at least 2 independent datapoints in-source, OR 1 strong datapoint corroborated by another source.
  - weak = not sufficiently corroborated.
- Weak evidence cannot drive recommendation changes alone.
- One-off social low-signal reactions are weak warnings unless corroborated.

Recommendation rules:
- Default to skeptical if strong open-source substitutes already exist.
- Use `proceed` only when there is a clear defensible wedge beyond existing repos.
- Use `pivot` when demand exists but the current implementation angle is commoditized.
- Use `abandon` when the concept is already solved broadly and differentiation is not credible.

Output structured `GitHubValidation`.
""",
    output_schema=GitHubValidation,
    output_key="github_validation",
)

github_agent = SequentialAgent(
    name="github_agent",
    description="Researches a product idea on GitHub.",
    sub_agents=[github_researcher, github_validator],
)
