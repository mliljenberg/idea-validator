"""Product Validator Search — main agent orchestration.

Architecture:
  interactive_planner (LlmAgent, root)
  ├── tool: AgentTool(plan_generator)
  │     └── plan_generator (LlmAgent)
  │           output_schema: ResearchPlan → state "research_plan"
  └── sub_agent: execution_pipeline (SequentialAgent)
        ├── parallel_search (ParallelAgent)
        │     ├── hackernews_agent   → state "hackernews_validation"
        │     ├── openalex_agent     → state "openalex_validation"
        │     └── google_trends_agent → state "google_trends_validation"
        └── final_validator (LlmAgent)
              free-form markdown → state "final_validation"
              (also saved to reports/ as .md file via callback)
"""

from __future__ import annotations

import datetime
import os
from typing import Literal

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.agent_tool import AgentTool
from pydantic import BaseModel, Field

from .config import config
from .sources.hackernews import hackernews_agent
from .sources.openalex import openalex_agent
from .sources.google_trends import google_trends_agent

# ---------------------------------------------------------------------------
# Pydantic schemas for structured agent outputs
# ---------------------------------------------------------------------------

SOURCE_NAMES = ["hackernews", "openalex", "google_trends"]


class ResearchPlan(BaseModel):
    """Structured plan produced by the plan_generator agent."""

    product_idea: str = Field(
        description="A clear, concise summary of the product idea being validated."
    )
    selected_sources: list[Literal["hackernews", "openalex", "google_trends"]] = Field(
        description=(
            "Which data sources to query. Choose based on relevance: "
            "hackernews for developer/startup sentiment and pain points, "
            "openalex for academic research maturity and prior art, "
            "google_trends for market demand and timing signals."
        )
    )
    search_keywords: list[str] = Field(
        description="3-6 diverse keywords/phrases the source agents should use as starting points."
    )
    research_focus: str = Field(
        description=(
            "A brief directive telling the source agents what specifically "
            "to look for (e.g. 'focus on pain points around X and existing "
            "competitors in Y space')."
        )
    )
    sources_rationale: str = Field(
        default="",
        description="Rationale explaining why each source was selected or excluded.",
    )


# ---------------------------------------------------------------------------
# plan_generator — creates a ResearchPlan from the user's idea
# ---------------------------------------------------------------------------

plan_generator = LlmAgent(
    name="plan_generator",
    model=config.worker_model,
    description="Generates a structured research plan for validating a product idea.",
    instruction=f"""\
You are a product-validation planning specialist.

Given a product idea from the user, produce a structured ResearchPlan that will
guide three parallel research agents:

- **hackernews**: Developer and startup community sentiment. Best for: pain
  points, feature requests, competitor discussions, community enthusiasm or
  skepticism. Select when the idea targets developers, startups, or tech users.
- **openalex**: Academic and scientific literature. Best for: research maturity,
  prior art, technology readiness, academic competitors. Select when the idea
  involves novel technology, scientific methods, or deep-tech.
- **google_trends**: Search interest and demand signals. Best for: market
  timing, demand trajectory, keyword popularity, emerging niches. Select when
  you want to gauge mainstream interest or compare against competitors.

Guidelines:
- Select ALL sources that are relevant. For most ideas, all three provide
  complementary signals. Only exclude a source if it truly adds no value.
- Generate 3-6 diverse search_keywords covering: the product concept, the
  problem it solves, competitor names, and the broader category.
- Write a focused research_focus directive so the agents know what matters.
- Include sources_rationale explaining your source choices.

Available sources: {", ".join(SOURCE_NAMES)}
""",
    output_schema=ResearchPlan,
    output_key="research_plan",
)

# ---------------------------------------------------------------------------
# parallel_search — runs all source agents concurrently
# ---------------------------------------------------------------------------

parallel_search = ParallelAgent(
    name="parallel_search",
    sub_agents=[hackernews_agent, openalex_agent, google_trends_agent],
)

# ---------------------------------------------------------------------------
# final_validator — aggregates all evidence into a readable markdown report
# ---------------------------------------------------------------------------

final_validator = LlmAgent(
    name="final_validator",
    model=config.critic_model,
    description="Aggregates evidence from all source agents and produces a human-readable validation report.",
    instruction="""\
You are a senior product strategist and validation expert. Your job is to
synthesize evidence from multiple research sources and deliver a clear,
human-readable product validation report in well-structured markdown.

## Inputs available in session state

- `research_plan` — the original plan (product_idea, selected_sources, etc.)
- `hackernews_validation` — structured findings from Hacker News (may be null if source was not selected)
- `hackernews_raw_report` — raw HN research data
- `openalex_validation` — structured findings from academic literature (may be null)
- `openalex_raw_report` — raw OpenAlex research data
- `google_trends_validation` — structured findings from Google Trends (may be null)
- `google_trends_raw_report` — raw Google Trends research data

## Output format

Write your report in clean markdown with the following structure:

# Product Validation Report: [Product Idea Name]

## Verdict
**Recommendation: [PROCEED / PIVOT / ABANDON]** | Signal Score: **[X]/100** | Confidence: **[low/medium/high]**

One-paragraph executive summary explaining the verdict.

## Source-by-Source Findings

### Hacker News
- What was found (or "source was not selected / no relevant data")
- Key pain points, competitor mentions, community sentiment
- Source signal score and assessment

### Academic Research (OpenAlex)
- What was found
- Research maturity, technology readiness, academic competitors
- Source signal score and assessment

### Google Trends
- What was found
- Trend direction, demand trajectory, related queries
- Source signal score and assessment

## Traction & Demand
Is there real evidence of demand? Cite specific data points from the sources.

## Competitive Landscape
Who are the existing players? How crowded is the space? Where are the gaps?

## Value Proposition
Is the value clear and differentiated? Is the problem painful enough to pay for?

## Pivot Suggestions
At least 2 concrete, actionable alternative directions. Be specific.

## Key Risks
- Bullet list of significant risks

## Key Opportunities
- Bullet list of promising opportunities

## Bottom Line
2-3 sentence final takeaway the founder can act on immediately.

---

## Rules
- Write in plain language — this is for a founder, not a data scientist.
- Be honest and direct. Do not inflate scores or sugarcoat weak signals.
- Reference specific data points (post titles, paper names, trend numbers).
- If a source was skipped or returned thin data, say so and note the impact on confidence.
- Weight sources that returned richer data more heavily.
- If sources contradict each other, explain the tension and how you resolved it.
- Always provide at least 2 pivot suggestions, even for "proceed" recommendations.
- Use the signal score scale consistently:
  0-30: Weak — likely abandon
  31-55: Mixed — consider pivoting
  56-75: Moderate — proceed with caution
  76-100: Strong — proceed confidently
""",
    output_key="final_validation",
)

# ---------------------------------------------------------------------------
# Callback — save the final report to a local .md file
# ---------------------------------------------------------------------------

_REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")


def _save_report_callback(callback_context: CallbackContext) -> None:
    """After the execution pipeline finishes, save the report to reports/."""
    report = callback_context.state.get("final_validation", "")
    if not report:
        return None

    os.makedirs(_REPORTS_DIR, exist_ok=True)

    # Build a filename from the product idea
    plan = callback_context.state.get("research_plan")
    idea = "unknown"
    if isinstance(plan, dict):
        idea = plan.get("product_idea", "unknown")
    elif hasattr(plan, "product_idea"):
        idea = plan.product_idea or "unknown"

    slug = "".join(c if c.isalnum() or c in " -_" else "" for c in idea)
    slug = slug[:50].strip().replace(" ", "_").lower()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(_REPORTS_DIR, f"{timestamp}_{slug}.md")

    with open(filename, "w") as f:
        f.write(report)

    return None


# ---------------------------------------------------------------------------
# execution_pipeline — parallel search → final validation (+ save to file)
# ---------------------------------------------------------------------------

execution_pipeline = SequentialAgent(
    name="execution_pipeline",
    sub_agents=[parallel_search, final_validator],
    after_agent_callback=_save_report_callback,
)

# ---------------------------------------------------------------------------
# interactive_planner — root agent that orchestrates the workflow
# ---------------------------------------------------------------------------

interactive_planner = LlmAgent(
    name="product_validator",
    model=config.worker_model,
    description=(
        "The primary product validation assistant. Collaborates with the user "
        "to create a research plan, then executes it and presents results."
    ),
    instruction=f"""\
You are a product validation assistant. You help users determine whether a
product idea is worth pursuing by gathering and synthesizing evidence from
multiple data sources.

## Workflow rules — follow these strictly

1. **Plan** — When the user describes a product idea (or asks any product
   question), IMMEDIATELY call `plan_generator` to create a research plan.
   Present the plan to the user clearly, including:
   - The product idea as you understood it
   - Which sources will be queried and why
   - The search keywords that will be used
   - What the research will focus on

2. **Refine** — If the user wants changes (different keywords, different
   sources, adjusted focus), call `plan_generator` again with the revised
   intent. Repeat until the user is satisfied.

3. **Execute** — When the user EXPLICITLY approves the plan (e.g. "looks
   good", "run it", "go ahead", "approved"), delegate to `execution_pipeline`.
   Do NOT run research before explicit approval.

4. **Present results** — After execution completes, read `final_validation`
   from state and present it directly to the user. The report is already
   formatted as clear markdown — relay it as-is. You may add a brief intro
   line but do NOT rewrite or restructure the report.
   Also let the user know the report has been saved to a local file.

## Important
- Never perform research yourself. Your job is to Plan, Refine, and Present.
- Never skip the planning step. Always generate a plan first.
- Be conversational but concise.
- Current date: {datetime.datetime.now().strftime("%Y-%m-%d")}
""",
    tools=[AgentTool(plan_generator)],
    sub_agents=[execution_pipeline],
)

# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

root_agent = interactive_planner
