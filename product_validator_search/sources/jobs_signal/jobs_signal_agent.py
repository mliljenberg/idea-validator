"""Jobs signal research agent.

A SequentialAgent that researches hiring demand related to the problem space.
"""

from __future__ import annotations

from typing import Literal

from google.adk.agents import LlmAgent, SequentialAgent
from pydantic import BaseModel, Field

from ...config import config
from .search_tool import search_jobs_signal


class JobsSignalValidation(BaseModel):
    """Structured output produced by the jobs-signal validator agent."""

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
    hiring_velocity_signal: str = ""
    roles_related_to_problem: list[str] = Field(default_factory=list)
    enterprise_adoption_clues: list[str] = Field(default_factory=list)
    key_findings: list[str] = Field(default_factory=list)
    reasoning: str = ""


jobs_signal_researcher = LlmAgent(
    name="jobs_signal_researcher",
    model=config.worker_model,
    description="Searches public job postings for demand and enterprise urgency signals.",
    instruction="""\
You are a labor-market research specialist for product validation.

## Getting your inputs
Read the `research_plan` from session state.
Use `deep_dive_hypotheses` and `evidence_validation_rules` if present.
If "jobs_signal" is NOT in `selected_sources`, output "Source not selected." and stop.

## Steps (only if selected)
1. Build dual-track keywords from the plan:
   - Use `validation_keywords` for supportive probes.
   - Use `invalidation_keywords` for disconfirming probes.
   - If either is missing, fall back to `search_keywords` and derive both
     supportive and skeptical variants.
   - Use `validation_focus` and `invalidation_focus` when present, otherwise
     use `research_focus`.
2. Run at least 2 validation queries with `search_jobs_signal`.
3. Run at least 2 invalidation queries with `search_jobs_signal`.
4. Write a raw report covering:
   - hiring volume and role concentration clues
   - role seniority and department clues (budget/priority proxy)
   - repeated enterprise needs indicating adoption urgency
   - whether demand looks broad or niche
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

Save to `jobs_signal_raw_report`.
""",
    tools=[search_jobs_signal],
    output_key="jobs_signal_raw_report",
)

jobs_signal_validator = LlmAgent(
    name="jobs_signal_validator",
    model=config.critic_model,
    description="Validates and synthesizes jobs-market signals.",
    instruction="""\
You are a critical product analyst evaluating jobs-market evidence.
Read `jobs_signal_raw_report` and output `JobsSignalValidation`.

Evidence reliability rules:
- Populate `material_supporting_evidence`, `weak_supporting_evidence`, `material_contradictions`, `weak_contradictions`, `deep_dive_actions_taken`, and `evidence_gaps`.
- Use moderate corroboration for BOTH support and contradiction:
  - material = at least 2 independent datapoints in-source, OR 1 strong datapoint corroborated by another source.
  - weak = not sufficiently corroborated.
- Weak evidence cannot drive recommendation changes alone.
- One-off social low-signal reactions are weak warnings unless corroborated.

Recommendation rules:
- Default to skeptical: job postings are a proxy, not direct purchase intent.
- Use `proceed` only when repeated hiring patterns indicate sustained budget and urgency.
- Use `pivot` when demand exists but appears concentrated in a different segment/workflow.
- Use `abandon` when hiring signals are sparse, stale, or unrelated to the concept.
""",
    output_schema=JobsSignalValidation,
    output_key="jobs_signal_validation",
)

jobs_signal_agent = SequentialAgent(
    name="jobs_signal_agent",
    description="Researches hiring demand as a proxy for commercial urgency.",
    sub_agents=[jobs_signal_researcher, jobs_signal_validator],
)
