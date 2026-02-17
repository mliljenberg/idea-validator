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
If "jobs_signal" is NOT in `selected_sources`, output "Source not selected." and stop.

## Steps (only if selected)
1. Build 3-5 focused keywords from `search_keywords` and `product_idea`.
2. Call `search_jobs_signal` with those keywords.
3. Write a raw report covering:
   - hiring volume and role concentration clues
   - role seniority and department clues (budget/priority proxy)
   - repeated enterprise needs indicating adoption urgency
   - whether demand looks broad or niche

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
