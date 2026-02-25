"""Reddit research agent.

A SequentialAgent that researches a product idea on Reddit using public JSON API.
"""

from __future__ import annotations

from typing import Literal

from google.adk.agents import LlmAgent, SequentialAgent
from pydantic import BaseModel, Field

from ...config import config
from .search_tool import search_reddit, get_reddit_comments


class RedditValidation(BaseModel):
    """Structured output produced by the Reddit validator agent."""

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
    pain_points: list[str] = Field(default_factory=list)
    competitors_mentioned: list[str] = Field(default_factory=list)
    community_sentiment: str = ""
    reasoning: str = ""


reddit_researcher = LlmAgent(
    name="reddit_researcher",
    model=config.worker_model,
    description="Searches Reddit for discussions relevant to a product idea.",
    instruction="""\
You are a Reddit research specialist. Your job is to find unfiltered user
discussions about a product idea.

## Getting your inputs
Read the `research_plan` from session state.
Use `deep_dive_hypotheses` and `evidence_validation_rules` if present.
It contains:
- `product_idea` — the idea to validate
- `selected_sources` — list of sources to use
- `search_keywords` — suggested starting keywords
- `validation_keywords` — keywords for supportive evidence
- `invalidation_keywords` — keywords for disconfirming evidence
- `validation_focus` / `invalidation_focus` — focused directions per track

**IMPORTANT:** If "reddit" is NOT in `selected_sources`, output
"Source not selected — skipped." and stop. Do not call any tools.

## Steps (only if selected)

1. **Generate dual-track keywords** — Prefer `validation_keywords` and
   `invalidation_keywords`. If either is missing, fall back to
   `search_keywords` and derive both supportive and skeptical variants. Use
   `validation_focus` and `invalidation_focus` when present, otherwise use
   `research_focus`.

2. **Validation track search** — Call `search_reddit` for at least
   2 validation queries.

3. **Invalidation track search** — Call `search_reddit` for at least
   2 invalidation queries using terms like "complaints", "regret buying",
   "doesn't work", "good enough alternative".

4. **Select top 5** — Pick the 5 most relevant threads (high comment count
   is better than high score).

5. **Fetch details** — Call `get_reddit_comments` for the selected threads.
   In refinement rounds, increase `comment_limit` and vary `sort` (for example
   `top` vs `new`) when needed to verify high-impact claims.

6. **Compose report** — Write a raw report including:
   - Thread titles and subreddits
   - Real user quotes (pain points, "I wish X existed")
   - Competitors mentioned in comments
   - Overall sentiment (cynical, excited, indifferent)
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

Save to `reddit_raw_report`.
""",
    tools=[search_reddit, get_reddit_comments],
    output_key="reddit_raw_report",
)

reddit_validator = LlmAgent(
    name="reddit_validator",
    model=config.critic_model,
    description="Validates and synthesizes a raw Reddit research report.",
    instruction="""\
You are a critical product analyst evaluating Reddit discussions.
Read `reddit_raw_report` and produce a structured assessment.

Focus on:
- **Brutal honesty**: Reddit users are often harsh. Use this to find real flaws.
- **Niche communities**: Identify which subreddits care (or hate it).
- **Competitors**: Reddit often lists "alternatives" explicitly.

Evidence reliability rules:
- Populate `material_supporting_evidence`, `weak_supporting_evidence`, `material_contradictions`, `weak_contradictions`, `deep_dive_actions_taken`, and `evidence_gaps`.
- Use moderate corroboration for BOTH support and contradiction:
  - material = at least 2 independent datapoints in-source, OR 1 strong datapoint corroborated by another source.
  - weak = not sufficiently corroborated.
- Weak evidence cannot drive recommendation changes alone.
- One-off social low-signal reactions are weak warnings unless corroborated.

Recommendation rules:
- Default to skeptical. Positive sentiment alone is not enough.
- Use `proceed` only when pain is severe, repeated across threads, and users show willingness to switch/pay.
- Use `pivot` when pain exists but this concept is weakly differentiated or poorly targeted.
- Use `abandon` when users are indifferent, hostile, or existing alternatives already satisfy the need.

Output structured `RedditValidation`.
""",
    output_schema=RedditValidation,
    output_key="reddit_validation",
)

reddit_agent = SequentialAgent(
    name="reddit_agent",
    description="Researches a product idea on Reddit.",
    sub_agents=[reddit_researcher, reddit_validator],
)
