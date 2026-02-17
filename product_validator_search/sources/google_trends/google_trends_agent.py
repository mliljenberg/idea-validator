"""Google Trends research agent.

A SequentialAgent that:
  1. google_trends_researcher — queries Google Trends for interest-over-time
     data and related queries around a product idea, and composes a raw report.
  2. google_trends_validator — a critic model that validates and synthesizes
     the trend data into structured findings for product validation.
"""

from __future__ import annotations

from typing import Literal

from google.adk.agents import LlmAgent, SequentialAgent
from pydantic import BaseModel, Field

from ...config import config
from .search_tool import get_trends_interest_over_time, get_trends_related_queries

# ---------------------------------------------------------------------------
# Structured output schema for the validator
# ---------------------------------------------------------------------------


class GoogleTrendsValidation(BaseModel):
    """Structured output produced by the validator agent."""

    recommendation: Literal["proceed", "pivot", "abandon"]
    signal_score: int = Field(ge=0, le=100)
    confidence: Literal["low", "medium", "high"]
    evidence_strength: int = Field(default=0, ge=0, le=100)
    evidence_quality: Literal["weak", "moderate", "strong"] = "weak"
    key_findings: list[str] = Field(default_factory=list)
    trend_direction: Literal["rising", "stable", "declining", "volatile", "no_data"] = (
        "no_data"
    )
    peak_interest_keywords: list[str] = Field(default_factory=list)
    emerging_related_queries: list[str] = Field(default_factory=list)
    market_timing_assessment: str = ""
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Sub-agent 1: Researcher
# ---------------------------------------------------------------------------

google_trends_researcher = LlmAgent(
    name="google_trends_researcher",
    model=config.worker_model,
    description="Queries Google Trends for interest data relevant to a product idea.",
    instruction="""\
You are a market-trends research specialist. Your job is to assess the
demand trajectory and public interest around a product idea using Google
Trends data.

## Getting your inputs
Read the `research_plan` from session state. It contains:
- `product_idea` — the idea to validate
- `selected_sources` — list of sources to use
- `search_keywords` — suggested starting keywords
- `research_focus` — what to focus on

**IMPORTANT:** If "google_trends" is NOT in `selected_sources`, output
"Source not selected — skipped." and stop. Do not call any tools.

## Steps (only if selected)

1. **Generate keywords** — Use the `search_keywords` from the plan as a
   starting point, then derive 3-5 keywords/phrases to investigate. Include:
   - The product concept itself (e.g. "AI code review")
   - The core problem it solves (e.g. "code review automation")
   - Key competitor or category names (e.g. "CodeRabbit", "Codacy")
   - The broader market category (e.g. "developer tools")
   Keep the `research_focus` in mind.

2. **Check interest over time** — Call `get_trends_interest_over_time` with
   your keywords (max 5 per call). This gives you 12-month trend data.
   Analyze: is interest growing, stable, or declining?

3. **Get related queries** — For the 2-3 most relevant keywords, call
   `get_trends_related_queries` to discover what people also search for.
   This reveals adjacent demand, competitor awareness, and emerging niches.

4. **Compose report** — Write a detailed raw research report covering:
   - Trend direction for each keyword (rising/stable/declining)
   - First vs. latest interest values and overall trajectory
   - Notable related queries — especially "rising" ones (breakout demand)
   - Comparison between the product concept vs. competitors/alternatives
   - Whether timing looks favorable (growing interest) or risky (declining)
   - Any seasonal patterns visible in the data

Save your full report as plain text. This will be passed to a validator agent
for synthesis.
""",
    tools=[get_trends_interest_over_time, get_trends_related_queries],
    output_key="google_trends_raw_report",
)

# ---------------------------------------------------------------------------
# Sub-agent 2: Validator / Synthesizer
# ---------------------------------------------------------------------------

google_trends_validator = LlmAgent(
    name="google_trends_validator",
    model=config.critic_model,
    description="Validates and synthesizes a raw Google Trends research report.",
    instruction="""\
You are a critical product-validation analyst specializing in market timing
and demand signals. You will receive a raw research report from Google Trends
(in state key `google_trends_raw_report`).

Evaluate the evidence and produce a structured assessment:

1. **Key findings** — The most important trend signals.
2. **Trend direction** — rising / stable / declining / volatile / no_data.
   This is the overall direction for the core product concept keywords.
3. **Peak interest keywords** — Which keywords show the strongest interest.
4. **Emerging related queries** — Rising queries that indicate new demand
   or adjacent opportunities. These are especially valuable for pivots.
5. **Market timing assessment** — Is this a good time to enter? Consider:
   - Rising trend = growing demand, potentially good timing
   - Stable high = established demand, harder to differentiate
   - Declining = market may be saturating or shifting
   - Rising from low = early opportunity, but risky
6. **Signal score** (0-100) — How favorable are the trend signals for this
   product idea? Higher = stronger positive market signal.
7. **Confidence** — low / medium / high. Google Trends data is directional
   only — note its limitations honestly.
8. **Recommendation** — proceed / pivot / abandon based on the evidence.
9. **Reasoning** — A concise explanation of your assessment.

Be careful: Google Trends measures search interest, not market size. A rising
trend in a niche keyword may still be a small market. A declining trend might
mean the problem is solved, not that demand disappeared. Interpret carefully.

Recommendation rules:
- Default to skeptical because trend data is noisy.
- Use `proceed` only when core keywords show durable growth and related queries indicate expanding demand.
- Use `pivot` for mixed signals (flat/volatile demand, or growth in adjacent keywords but not the core concept).
- Use `abandon` when demand is persistently weak/declining and no credible adjacent opportunity appears.
""",
    output_schema=GoogleTrendsValidation,
    output_key="google_trends_validation",
)

# ---------------------------------------------------------------------------
# Composed agent: Researcher → Validator
# ---------------------------------------------------------------------------

google_trends_agent = SequentialAgent(
    name="google_trends_agent",
    description=(
        "Researches a product idea using Google Trends by checking interest "
        "trajectories and related queries, then validating the findings "
        "through a critic model."
    ),
    sub_agents=[google_trends_researcher, google_trends_validator],
)
