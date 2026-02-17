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
If "github" is NOT in `selected_sources`, output "Source not selected." and stop.

## Steps (only if selected)

1. **Generate keywords** — Use `search_keywords` from the plan. Focus on
   technical terms, library names, and "open source [solution]".

2. **Search** — Call `search_github` for 2-3 queries.

3. **Select top 5** — Pick the 5 most relevant repositories (stars are good,
   but relevance and recency matter more).

4. **Compose report** — Write a raw report including:
   - Repo names, URLs, star counts
   - Descriptions and key features
   - "How it works" technical details if available
   - License (permissive vs copyleft) if mentioned

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
