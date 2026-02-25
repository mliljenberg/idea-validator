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
    evidence_strength: int = Field(default=0, ge=0, le=100)
    evidence_quality: Literal["weak", "moderate", "strong"] = "weak"
    material_supporting_evidence: list[str] = Field(default_factory=list)
    weak_supporting_evidence: list[str] = Field(default_factory=list)
    material_contradictions: list[str] = Field(default_factory=list)
    weak_contradictions: list[str] = Field(default_factory=list)
    deep_dive_actions_taken: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
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
Use `deep_dive_hypotheses` and `evidence_validation_rules` if present.
If "competitors" is NOT in `selected_sources`, output "Source not selected." and stop.

## Steps (only if selected)

1. **Construct Site-Specific Queries** — Use `product_idea` and keywords to search:
   - `site:producthunt.com [keywords]` (Find launches)
   - `site:appsumo.com [keywords]` (Find lifetime deals/SaaS)
   - `site:alternativeto.net [keywords]` (Find software categories)
   - `site:x.com [keywords] "launching"` or `"built"` (Find indie hacker projects)
   - `site:reddit.com [keywords] "competitor"` (Find user discussions about competitors)
   Prefer `validation_keywords` for supportive checks and
   `invalidation_keywords` for disconfirming checks. If either is missing,
   fall back to `search_keywords` and derive both supportive and skeptical
   variants. Use `validation_focus` and `invalidation_focus` when present,
   otherwise use `research_focus`.

2. **Validation track search** — Use `search_brave` for at least
   2 validation queries targeting differentiation opportunities.

3. **Invalidation track search** — Use `search_brave` for at least
   2 invalidation queries targeting heavy saturation, incumbent lock-in, and
   feature parity.

4. **Analyze & Report** — Write a raw report detailing:
   - List of Competitors (Names + URLs)
   - Their core value proposition (from snippets)
   - Pricing info (if visible in snippets like "$49 lifetime")
   - User feedback/ratings found in search snippets
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

Evidence reliability rules:
- Populate `material_supporting_evidence`, `weak_supporting_evidence`, `material_contradictions`, `weak_contradictions`, `deep_dive_actions_taken`, and `evidence_gaps`.
- Use moderate corroboration for BOTH support and contradiction:
  - material = at least 2 independent datapoints in-source, OR 1 strong datapoint corroborated by another source.
  - weak = not sufficiently corroborated.
- Weak evidence cannot drive recommendation changes alone.
- One-off social low-signal reactions are weak warnings unless corroborated.

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
