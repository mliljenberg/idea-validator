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
    evidence_strength: int = Field(default=0, ge=0, le=100)
    evidence_quality: Literal["weak", "moderate", "strong"] = "weak"
    material_supporting_evidence: list[str] = Field(default_factory=list)
    weak_supporting_evidence: list[str] = Field(default_factory=list)
    material_contradictions: list[str] = Field(default_factory=list)
    weak_contradictions: list[str] = Field(default_factory=list)
    deep_dive_actions_taken: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
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
Read the `research_plan` from session state.
Use `deep_dive_hypotheses` and `evidence_validation_rules` if present.
It contains:
- `product_idea` — the idea to validate
- `selected_sources` — list of sources to use
- `search_keywords` — suggested starting keywords
- `validation_keywords` — keywords for supportive evidence
- `invalidation_keywords` — keywords for disconfirming evidence
- `research_focus` — what to focus on
- `validation_focus` / `invalidation_focus` — focused directions per track

**IMPORTANT:** If "openalex" is NOT in `selected_sources`, output
"Source not selected — skipped." and stop. Do not call any tools.

## Steps (only if selected)

1. **Generate dual-track queries** — Use `validation_keywords` and
   `invalidation_keywords` from the plan. If either is missing, fall back to
   `search_keywords` and derive both supportive and skeptical variants.
   Keep `validation_focus` and `invalidation_focus` in mind when present,
   otherwise use `research_focus`.
   Build queries targeting:
   - The core technology or methodology
   - The problem domain or pain point
   - Adjacent or competing approaches
   - Application areas

2. **Validation track search** — Call `search_openalex` for at least
   2 validation queries. Collect results.

3. **Invalidation track search** — Call `search_openalex` for at least
   2 invalidation queries to find prior-art saturation, practical blockers,
   and low-readiness signals. Collect results.

4. **Select top 5** — From all combined results, pick the 5 most relevant
   works. Prioritize by: relevance to the product idea, citation count
   (higher = more influential), and recency (prefer recent work showing
   active research).

5. **Fetch details** — For each of the 5 selected works, call
   `get_openalex_work_details` with its `id` to get the full metadata
   including the abstract.

6. **Compose report** — Write a detailed raw research report covering:
   - Each paper's title, year, citation count, abstract summary
   - Key concepts and research themes
   - Whether the research indicates an unsolved problem (opportunity) or
     a well-established solution (competition risk)
   - Signs of industry–academia crossover (commercial potential)
   - Overall maturity of the research area
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

7. **Adaptive refinement loop** — Before finalizing the report:
   - Run initial validation/invalidation probes first.
   - Run up to 2 conditional refinement rounds.
   - Trigger refinement when evidence is thin, conflicting, or high-impact on either side.
   - In each round, create up to 4 targeted follow-up queries from observed claims/entities.
   - Stop early when evidence is strong, convergent, and high-impact claims are resolved.
   - Use moderate corroboration for BOTH support and contradiction:
     - material = at least 2 independent datapoints in-source, OR 1 strong datapoint corroborated by another source.
     - weak = not sufficiently corroborated; cannot drive recommendation alone.
   - Treat social low-signal reactions (emoji jokes, one-off comments) as weak warnings unless corroborated.

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

Evidence reliability rules:
- Populate `material_supporting_evidence`, `weak_supporting_evidence`, `material_contradictions`, `weak_contradictions`, `deep_dive_actions_taken`, and `evidence_gaps`.
- Use moderate corroboration for BOTH support and contradiction:
  - material = at least 2 independent datapoints in-source, OR 1 strong datapoint corroborated by another source.
  - weak = not sufficiently corroborated.
- Weak evidence cannot drive recommendation changes alone.
- One-off social low-signal reactions are weak warnings unless corroborated.

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
