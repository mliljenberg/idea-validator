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
Read the `research_plan` from session state. It contains:
- `product_idea` — the idea to validate
- `selected_sources` — list of sources to use
- `search_keywords` — suggested starting keywords

**IMPORTANT:** If "reddit" is NOT in `selected_sources`, output
"Source not selected — skipped." and stop. Do not call any tools.

## Steps (only if selected)

1. **Generate keywords** — Use `search_keywords` from the plan. Combine with
   "reddit" terms like "alternative to", "vs", "complaints", "best".

2. **Search** — Call `search_reddit` for 2-3 queries.

3. **Select top 5** — Pick the 5 most relevant threads (high comment count
   is better than high score).

4. **Fetch details** — Call `get_reddit_comments` for the selected threads.

5. **Compose report** — Write a raw report including:
   - Thread titles and subreddits
   - Real user quotes (pain points, "I wish X existed")
   - Competitors mentioned in comments
   - Overall sentiment (cynical, excited, indifferent)

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
