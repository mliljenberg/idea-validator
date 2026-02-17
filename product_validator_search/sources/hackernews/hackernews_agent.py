"""Hacker News research agent.

A SequentialAgent that:
  1. hackernews_researcher — searches HN for relevant keywords, selects the
     top 5 posts, fetches their comment trees, and composes a raw research
     report into session state.
  2. hackernews_validator — a critic model that validates and synthesizes the
     raw report into structured findings (signal score, recommendation, etc.).
"""

from __future__ import annotations

from typing import Literal

from google.adk.agents import LlmAgent, SequentialAgent
from pydantic import BaseModel, Field

from ...config import config
from .search_tool import get_hackernews_comments, search_hackernews

# ---------------------------------------------------------------------------
# Structured output schema for the validator
# ---------------------------------------------------------------------------


class HackerNewsValidation(BaseModel):
    """Structured output produced by the validator agent."""

    recommendation: Literal["proceed", "pivot", "abandon"]
    signal_score: int = Field(ge=0, le=100)
    confidence: Literal["low", "medium", "high"]
    evidence_strength: int = Field(default=0, ge=0, le=100)
    evidence_quality: Literal["weak", "moderate", "strong"] = "weak"
    key_findings: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    competitors_mentioned: list[str] = Field(default_factory=list)
    community_sentiment: str = ""
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Sub-agent 1: Researcher
# ---------------------------------------------------------------------------

hackernews_researcher = LlmAgent(
    name="hackernews_researcher",
    model=config.worker_model,
    description="Searches Hacker News for posts and comments relevant to a product idea.",
    instruction="""\
You are a Hacker News research specialist. Your job is to deeply research a
product idea on Hacker News using the tools provided.

## Getting your inputs
Read the `research_plan` from session state. It contains:
- `product_idea` — the idea to validate
- `selected_sources` — list of sources to use
- `search_keywords` — suggested starting keywords
- `research_focus` — what to focus on

**IMPORTANT:** If "hackernews" is NOT in `selected_sources`, output
"Source not selected — skipped." and stop. Do not call any tools.

## Steps (only if selected)

1. **Generate keywords** — Use the `search_keywords` from the plan as a
   starting point, then derive 2-4 additional search queries covering
   different angles (the problem space, existing solutions, competitor names,
   relevant technology). Keep the `research_focus` in mind.

2. **Search** — Call `search_hackernews` for each query. Collect all results.

3. **Select top 5** — From the combined results, pick the 5 most relevant
   posts (by relevance to the idea AND engagement: points + num_comments).

4. **Fetch comments** — For each of the 5 selected posts, call
   `get_hackernews_comments` with its `objectID` to get the full comment tree.

5. **Compose report** — Write a detailed raw research report that includes:
   - Each post's title, URL, points
   - Key excerpts from the comments (pain points, feature requests, sentiment,
     competitor mentions, criticism)
   - A summary of community sentiment toward the problem/solution space

Save your full report as plain text. This will be passed to a validator agent
for synthesis.
""",
    tools=[search_hackernews, get_hackernews_comments],
    output_key="hackernews_raw_report",
)

# ---------------------------------------------------------------------------
# Sub-agent 2: Validator / Synthesizer
# ---------------------------------------------------------------------------

hackernews_validator = LlmAgent(
    name="hackernews_validator",
    model=config.critic_model,
    description="Validates and synthesizes a raw Hacker News research report.",
    instruction="""\
You are a critical product-validation analyst. You will receive a raw research
report from Hacker News (in state key `hackernews_raw_report`).

Your job is to evaluate the evidence and produce a structured assessment:

1. **Key findings** — The most important signals from the posts and comments.
2. **Pain points** — Real user pain points mentioned in discussions.
3. **Competitors mentioned** — Any products, tools, or projects that HN users
   reference as existing solutions.
4. **Community sentiment** — Overall tone: enthusiastic, skeptical, mixed, etc.
5. **Signal score** (0-100) — How strong is the market signal based on
   this HN evidence alone?  0 = no signal, 100 = overwhelming demand.
6. **Confidence** — low / medium / high based on volume and quality of data.
7. **Recommendation** — proceed / pivot / abandon based on the evidence.
8. **Reasoning** — A concise explanation of your assessment.

Be rigorous. Do not inflate scores. If the data is thin or ambiguous, say so.

Recommendation rules:
- Default to skeptical. Curiosity in comments is not product demand.
- Use `proceed` only if multiple threads show repeated pain, clear urgency, and dissatisfaction with current options.
- Use `pivot` for partial demand signals with weak fit, wrong audience, or unclear differentiation.
- Use `abandon` when sentiment is mostly dismissive, problem urgency is low, or alternatives are "good enough."
""",
    output_schema=HackerNewsValidation,
    output_key="hackernews_validation",
)

# ---------------------------------------------------------------------------
# Composed agent: Researcher → Validator
# ---------------------------------------------------------------------------

hackernews_agent = SequentialAgent(
    name="hackernews_agent",
    description=(
        "Researches a product idea on Hacker News by searching for relevant "
        "posts, fetching comment threads, and validating the findings through "
        "a critic model."
    ),
    sub_agents=[hackernews_researcher, hackernews_validator],
)
