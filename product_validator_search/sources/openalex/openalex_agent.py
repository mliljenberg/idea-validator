"""OpenAlex academic research agent.

A SequentialAgent that:
  1. openalex_researcher — searches OpenAlex for academic works relevant to a
     product idea, selects the top 5 papers, fetches their full details
     (abstracts, concepts, citation counts), and composes a raw research report.
  2. openalex_validator — a critic model that validates and synthesizes the raw
     report into structured findings for product validation.
"""

from __future__ import annotations

from typing import Literal

from google.adk.agents import LlmAgent, SequentialAgent
from pydantic import BaseModel, Field

from ...config import config
from .search_tool import get_openalex_work_details, search_openalex

# ---------------------------------------------------------------------------
# Structured output schema for the validator
# ---------------------------------------------------------------------------


class OpenAlexValidation(BaseModel):
    """Structured output produced by the validator agent."""

    recommendation: Literal["proceed", "pivot", "abandon"]
    signal_score: int = Field(ge=0, le=100)
    confidence: Literal["low", "medium", "high"]
    key_findings: list[str] = Field(default_factory=list)
    research_maturity: Literal["nascent", "emerging", "established", "saturated"] = (
        "nascent"
    )
    active_research_areas: list[str] = Field(default_factory=list)
    potential_competitors_from_academia: list[str] = Field(default_factory=list)
    technology_readiness: str = ""
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Sub-agent 1: Researcher
# ---------------------------------------------------------------------------

openalex_researcher = LlmAgent(
    name="openalex_researcher",
    model=config.worker_model,
    description="Searches OpenAlex for academic papers relevant to a product idea.",
    instruction="""\
You are an academic research specialist. Your job is to investigate the
scholarly landscape around a product idea using OpenAlex.

## Getting your inputs
Read the `research_plan` from session state. It contains:
- `product_idea` — the idea to validate
- `selected_sources` — list of sources to use
- `search_keywords` — suggested starting keywords
- `research_focus` — what to focus on

**IMPORTANT:** If "openalex" is NOT in `selected_sources`, output
"Source not selected — skipped." and stop. Do not call any tools.

## Steps (only if selected)

1. **Generate queries** — Use the `search_keywords` from the plan as a
   starting point, then derive 2-4 additional search queries targeting:
   - The core technology or methodology
   - The problem domain or pain point
   - Adjacent or competing approaches
   - Application areas
   Keep the `research_focus` in mind.

2. **Search** — Call `search_openalex` for each query. Collect all results.

3. **Select top 5** — From all combined results, pick the 5 most relevant
   works. Prioritize by: relevance to the product idea, citation count
   (higher = more influential), and recency (prefer recent work showing
   active research).

4. **Fetch details** — For each of the 5 selected works, call
   `get_openalex_work_details` with its `id` to get the full metadata
   including the abstract.

5. **Compose report** — Write a detailed raw research report covering:
   - Each paper's title, year, citation count, abstract summary
   - Key concepts and research themes
   - Whether the research indicates an unsolved problem (opportunity) or
     a well-established solution (competition risk)
   - Signs of industry–academia crossover (commercial potential)
   - Overall maturity of the research area

Save your full report as plain text. This will be passed to a validator agent
for synthesis.
""",
    tools=[search_openalex, get_openalex_work_details],
    output_key="openalex_raw_report",
)

# ---------------------------------------------------------------------------
# Sub-agent 2: Validator / Synthesizer
# ---------------------------------------------------------------------------

openalex_validator = LlmAgent(
    name="openalex_validator",
    model=config.critic_model,
    description="Validates and synthesizes a raw OpenAlex research report.",
    instruction="""\
You are a critical product-validation analyst specializing in academic
research signals. You will receive a raw research report from OpenAlex
(in state key `openalex_raw_report`).

Evaluate the evidence and produce a structured assessment:

1. **Key findings** — The most important academic signals.
2. **Research maturity** — nascent / emerging / established / saturated.
   - nascent: few papers, early-stage exploration
   - emerging: growing body of work, active research, not yet commoditized
   - established: well-studied area, many solutions exist
   - saturated: heavily researched, little room for novel contribution
3. **Active research areas** — Specific sub-topics being actively studied.
4. **Potential competitors from academia** — Research groups, institutions,
   or spin-offs that could become or already are competitors.
5. **Technology readiness** — Is the underlying tech ready for productization,
   or still theoretical?
6. **Signal score** (0-100) — How favorable is the academic landscape for
   this product idea? Higher = stronger opportunity signal.
   Consider: unsolved problems = opportunity, saturated field = risk.
7. **Confidence** — low / medium / high based on volume and quality of data.
8. **Recommendation** — proceed / pivot / abandon based on the evidence.
9. **Reasoning** — A concise explanation of your assessment.

Be rigorous. A heavily-researched area might mean opportunity (validated
problem) or risk (many competing solutions). Distinguish carefully.

Recommendation rules:
- Default to skeptical. Academic interest does not guarantee commercial demand.
- Use `proceed` only when research momentum is active, technology readiness is practical, and there is room to differentiate.
- Use `pivot` when the science is promising but commercialization path or target use case is weak.
- Use `abandon` when the field is saturated, impractical, or unlikely to convert into a defensible product.
""",
    output_schema=OpenAlexValidation,
    output_key="openalex_validation",
)

# ---------------------------------------------------------------------------
# Composed agent: Researcher → Validator
# ---------------------------------------------------------------------------

openalex_agent = SequentialAgent(
    name="openalex_agent",
    description=(
        "Researches a product idea in academic literature via OpenAlex by "
        "searching for relevant papers, fetching full details, and validating "
        "the findings through a critic model."
    ),
    sub_agents=[openalex_researcher, openalex_validator],
)
