"""Product Validator Search — main agent orchestration.

Architecture:
  interactive_planner (LlmAgent, root)
  ├── tool: AgentTool(plan_generator)
  │     └── plan_generator (LlmAgent)
  │           output_schema: ResearchPlan → state "research_plan"
  └── sub_agent: execution_pipeline (SequentialAgent)
        ├── market_research (ResilientParallelAgent)
        │     ├── brave_search_agent  → state "brave_search_validation"
        │     ├── google_trends_agent → state "google_trends_validation"
        │     └── competitors_agent   → state "competitors_validation"
        ├── buyer_intent_research (ResilientParallelAgent)
        │     ├── review_sites_agent  → state "review_sites_validation"
        │     ├── jobs_signal_agent   → state "jobs_signal_validation"
        │     └── seo_intent_agent    → state "seo_intent_validation"
        ├── community_tech_research (ResilientParallelAgent)
        │     ├── hackernews_agent    → state "hackernews_validation"
        │     ├── reddit_agent        → state "reddit_validation"
        │     ├── github_agent        → state "github_validation"
        │     └── openalex_agent      → state "openalex_validation"
        └── final_validator (LlmAgent)
              free-form markdown → state "final_validation"
              (also saved to reports/ as .md file via callback)
"""

from __future__ import annotations

import datetime
import os
from typing import Literal

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.agent_tool import AgentTool
from pydantic import BaseModel, Field

from .config import config
from .resilient_parallel_agent import ResilientParallelAgent
from .sources.hackernews import hackernews_agent
from .sources.openalex import openalex_agent
from .sources.google_trends import google_trends_agent
from .sources.reddit import reddit_agent
from .sources.github import github_agent
from .sources.brave_search import brave_search_agent
from .sources.competitors import competitors_agent
from .sources.review_sites import review_sites_agent
from .sources.jobs_signal import jobs_signal_agent
from .sources.seo_intent import seo_intent_agent

# ---------------------------------------------------------------------------
# Pydantic schemas for structured agent outputs
# ---------------------------------------------------------------------------

SOURCE_NAMES = [
    "hackernews",
    "openalex",
    "google_trends",
    "reddit",
    "github",
    "brave_search",
    "competitors",
    "review_sites",
    "jobs_signal",
    "seo_intent",
]


class ResearchPlan(BaseModel):
    """Structured plan produced by the plan_generator agent."""

    product_idea: str = Field(
        description="A clear, concise summary of the product idea being validated."
    )
    selected_sources: list[
        Literal[
            "hackernews",
            "openalex",
            "google_trends",
            "reddit",
            "github",
            "brave_search",
            "competitors",
            "review_sites",
            "jobs_signal",
            "seo_intent",
        ]
    ] = Field(
        description=(
            "Which data sources to query. Select based on relevance:\n"
            "- hackernews: Tech/startup sentiment\n"
            "- openalex: Academic/deep-tech research\n"
            "- google_trends: Market demand timing\n"
            "- reddit: User pain points & discussions\n"
            "- github: Open source competitors/tools\n"
            "- brave_search: General market reports & news\n"
            "- competitors: Product Hunt, AppSumo, X launches (via Brave)\n"
            "- review_sites: G2/Capterra/Trustpilot buyer intent signals\n"
            "- jobs_signal: Hiring demand as budget/urgency proxy\n"
            "- seo_intent: Transactional vs informational search intent"
        )
    )
    search_keywords: list[str] = Field(
        description="3-6 diverse keywords/phrases the source agents should use as starting points."
    )
    validation_keywords: list[str] = Field(
        default_factory=list,
        description=(
            "3-6 keywords/phrases focused on validating the idea thesis. "
            "If empty, source agents should fall back to `search_keywords`."
        ),
    )
    invalidation_keywords: list[str] = Field(
        default_factory=list,
        description=(
            "3-6 keywords/phrases focused on disproving/falsifying the idea. "
            "If empty, source agents should derive skeptical variants from "
            "`search_keywords`."
        ),
    )
    research_focus: str = Field(
        description=(
            "A brief directive telling the source agents what specifically "
            "to look for (e.g. 'focus on pain points around X and existing "
            "competitors in Y space')."
        )
    )
    validation_focus: str = Field(
        default="",
        description=(
            "Focused instruction for what would count as strong supporting "
            "evidence for this idea."
        ),
    )
    invalidation_focus: str = Field(
        default="",
        description=(
            "Focused instruction for what would count as disconfirming "
            "evidence that invalidates this idea."
        ),
    )
    falsification_criteria: list[str] = Field(
        default_factory=list,
        description=(
            "3-5 concrete kill conditions that, if met, should strongly push "
            "the verdict toward pivot or abandon."
        ),
    )
    deep_dive_hypotheses: list[str] = Field(
        default_factory=list,
        description=(
            "Specific claims that require follow-up verification during "
            "adaptive query refinement rounds."
        ),
    )
    evidence_validation_rules: list[str] = Field(
        default_factory=list,
        description=(
            "Rules that define what counts as material evidence vs weak "
            "evidence for BOTH supporting and contradictory claims."
        ),
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
guide parallel research agents.

## Available Sources

- **hackernews**: Developer sentiment, startup critiques. Best for tech products.
- **openalex**: Academic papers. Best for deep-tech, AI, health, science.
- **google_trends**: Search volume. Best for consumer demand and timing.
- **reddit**: Unfiltered user feedback. Best for B2C and community-driven tools.
- **github**: Open source code. Best for devtools and technical feasibility checks.
- **brave_search**: General market research, articles, and industry reports.
- **competitors**: Targeted scout for Product Hunt, AppSumo, and social launches.
- **review_sites**: Buyer-intent clues from G2/Capterra/Trustpilot snippets.
- **jobs_signal**: Hiring demand as a proxy for enterprise urgency and budget.
- **seo_intent**: Commercial-intent keyword and SERP competitiveness signals.

## Guidelines
- **Select relevant sources only**: Don't just select all. If it's a B2B SaaS, `reddit` might be weak but `competitors` is critical. If it's a deep-tech AI tool, `openalex` and `github` are essential.
- **Thesis + anti-thesis required**: Explicitly plan how to test both why the idea might work and why it might fail.
- **Keywords**:
  - Fill `search_keywords` with 3-6 broad base phrases.
  - Fill `validation_keywords` with 3-6 supporting-evidence phrases.
  - Fill `invalidation_keywords` with 3-6 falsification phrases.
- **Focus**:
  - Fill `research_focus` as the overall research direction.
  - Fill `validation_focus` with what positive evidence should look like.
  - Fill `invalidation_focus` with what disconfirming evidence should look like.
- **Falsification criteria**: Fill `falsification_criteria` with 3-5 concrete kill conditions.
- **Deep-dive hypotheses**: Fill `deep_dive_hypotheses` with 2-5 high-impact claims that should trigger follow-up query refinement if evidence is thin or conflicting.
- **Evidence validation rules**: Fill `evidence_validation_rules` with concrete corroboration rules for BOTH supporting evidence and contradiction evidence.
  - Default corroboration bar is moderate:
    - Material evidence requires at least 2 independent datapoints in one source, OR 1 strong datapoint corroborated by another selected source.
    - Weak evidence cannot drive recommendation changes by itself.
    - Social low-signal reactions (emoji jokes, one-off comments) are warning-only unless corroborated.
- **Source rationale must mention invalidation value**: In `sources_rationale`, include not only why each source can validate demand, but also what it can reveal to invalidate the idea.

Available sources: {", ".join(SOURCE_NAMES)}
""",
    output_schema=ResearchPlan,
    output_key="research_plan",
)

# ---------------------------------------------------------------------------
# Split Execution — Resilient parallel batches for speed + fault isolation
# ---------------------------------------------------------------------------

market_research = ResilientParallelAgent(
    name="market_research",
    sub_agents=[
        brave_search_agent,
        google_trends_agent,
        competitors_agent,
    ],
)

buyer_intent_research = ResilientParallelAgent(
    name="buyer_intent_research",
    sub_agents=[
        review_sites_agent,
        jobs_signal_agent,
        seo_intent_agent,
    ],
)

community_tech_research = ResilientParallelAgent(
    name="community_tech_research",
    sub_agents=[
        hackernews_agent,
        reddit_agent,
        github_agent,
        openalex_agent,
    ],
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

- `research_plan` — the original plan
- `hackernews_validation`, `hackernews_raw_report`
- `openalex_validation`, `openalex_raw_report`
- `google_trends_validation`, `google_trends_raw_report`
- `reddit_validation`, `reddit_raw_report`
- `github_validation`, `github_raw_report`
- `brave_search_validation`, `brave_search_raw_report`
- `competitors_validation`, `competitors_raw_report`
- `review_sites_validation`, `review_sites_raw_report`
- `jobs_signal_validation`, `jobs_signal_raw_report`
- `seo_intent_validation`, `seo_intent_raw_report`

## Output format

Write your report in clean markdown with the following structure:

# Product Validation Report: [Product Idea Name]

## Verdict
**Recommendation: [PROCEED / PIVOT / ABANDON]** | Signal Score: **[X]/100** | Confidence: **[low/medium/high]**

One-paragraph executive summary explaining the verdict.
If recommendation is PIVOT or ABANDON, explicitly say: "This is a bad idea in its current form."
Add a one-line reason taxonomy tag: one of
`no-demand`, `crowded-market`, `weak-differentiation`, `distribution-risk`, `execution-risk`.

## What Would Invalidate This Idea
- List the `falsification_criteria` from `research_plan`.
- If `falsification_criteria` is empty, infer 3-5 concrete criteria and say they were inferred.
- Apply `evidence_validation_rules` from `research_plan` where available.

## What Was Actually Invalidated
- List specific disconfirming findings discovered across sources.
- Separate critical blockers vs non-critical warnings.

## Falsification Criteria Check
- For each criterion, mark status as: `triggered`, `partially_triggered`, or `not_triggered`.
- Include source citations for each status.

## Supporting Evidence Reliability Assessment
- Classify supporting evidence as `material_supporting_evidence` vs `weak_supporting_evidence`.
- Explain corroboration quality and why weak evidence is non-decisive.
- If no explicit `evidence_validation_rules` are provided, use moderate corroboration defaults.

## Contradiction Reliability Assessment
- Classify contradictions as `material_contradictions` vs `weak_contradictions`.
- Explicitly mark one-off social reactions as weak warnings unless corroborated.

## Deep-Dive Verification Outcomes
- Summarize follow-up checks run by source agents (`deep_dive_actions_taken`).
- State which high-impact claims were confirmed, unresolved, or downgraded.
- Use `deep_dive_hypotheses` from `research_plan` as the baseline checklist when present.

## Source-by-Source Findings

### Competitor Landscape (Product Hunt, AppSumo, X)
- Key competitors found
- Saturation level and differentiation gaps

### User Sentiment (Reddit & Hacker News)
- Real pain points mentioned
- Community enthusiasm vs skepticism

### Market Demand (Brave Search & Google Trends)
- Macro trends and market timing
- Search interest trajectory

### Buyer Intent (Review Sites, Jobs, SEO Intent)
- Evidence of willingness to pay and switching behavior
- Hiring urgency / enterprise budget proxy
- Transactional vs informational intent mix

### Technical & Academic (GitHub & OpenAlex)
- Existing open source solutions
- Research maturity and prior art

## Traction & Demand
Is there real evidence of demand? Cite specific data points.

## Value Proposition
Is the value clear and differentiated? Is the problem painful enough to pay for?

## Evidence Quality
- Assess evidence breadth, freshness, and reliability.
- Call out weak/noisy sources explicitly.

## Contradictions
- Required bullet list of contradictions across sources.
- Include at least one contradiction when signals conflict, otherwise write "No major contradictions found."

## Net Evidence Conclusion
- Explain how supporting evidence and disconfirming evidence were weighted against each other.
- State clearly why the final recommendation is not overly optimistic.

## Key Risks
- Bullet list of significant risks

## Key Opportunities
- Bullet list of promising opportunities

## Why This Might Still Fail
- 2-4 bullets on practical failure paths even if recommendation is PROCEED.

## Bottom Line
2-3 sentence final takeaway the founder can act on immediately.

## Pivot / Alternative Paths
At least 2 concrete, actionable alternatives. Only include paths supported by evidence.

---

## Rules
- Write in plain language — this is for a founder, not a data scientist.
- Be honest and direct. Do not inflate scores.
- Reference specific data points (post titles, paper names, trend numbers, review snippets, hiring patterns).
- Each major claim must include at least one concrete source citation in-line using this format: `[source: <source_name>, data: <brief datapoint>]`.
- If a source was skipped or returned thin data, note it briefly.
- Use evidence weights for synthesis (default):
  - review_sites: 0.22
  - competitors: 0.18
  - google_trends: 0.14
  - github: 0.12
  - reddit: 0.10
  - hackernews: 0.08
  - openalex: 0.08
  - brave_search: 0.08
  - jobs_signal: 0.07
  - seo_intent: 0.07
- Apply a contradiction penalty of -12 to the final signal score when demand is high but saturation/differentiation is poor.
- Apply additional penalties for unresolved disconfirming evidence:
  - -10 for each critical blocker that is not credibly mitigated.
  - -6 for each falsification criterion marked `triggered`.
  - -3 for each falsification criterion marked `partially_triggered`.
- Reliability handling:
  - Weak supporting evidence cannot count toward `PROCEED` thresholds.
  - Only material supporting evidence can satisfy a "strong source" contribution.
  - Weak contradictions reduce confidence, not recommendation, unless corroborated into material contradictions.
  - If supporting evidence is mostly weak/unconfirmed, downgrade recommendation even if narrative appears positive.
- Be conservative by default. `PROCEED` is rare and requires strong, multi-source evidence of demand, differentiation, and viable execution.
- Recommendation thresholds:
  - `PROCEED`: only when at least 3 independent sources show MATERIAL supporting signal, no critical invalidation findings (material contradictions), and most falsification criteria are `not_triggered`.
  - `PIVOT`: mixed evidence, weak differentiation, or clear demand but wrong approach/segment.
  - `ABANDON`: low demand, severe saturation with no wedge, major trust/regulatory blocker, or weak evidence quality.
- Confidence calibration:
  - Cap confidence at `medium` unless at least 3 strong sources agree and data is reasonably fresh.
  - Reduce confidence for stale, thin, or conflicting evidence.
- If evidence is weak or conflicting, never output `PROCEED`.
- Every verdict justification must cite BOTH supporting and disconfirming evidence.
- Always provide at least 2 pivot/alternative paths at the end.
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

    try:
        with open(filename, "w") as f:
            f.write(report)
    except Exception:
        # Silently fail on file write error to avoid crashing the agent response
        pass

    return None


# ---------------------------------------------------------------------------
# execution_pipeline — Batched Parallel Search → Final Validation (+ save to file)
# ---------------------------------------------------------------------------

execution_pipeline = SequentialAgent(
    name="execution_pipeline",
    sub_agents=[
        market_research,  # Batch 1: Market timing + competitors
        buyer_intent_research,  # Batch 2: Buyer-intent sources
        community_tech_research,  # Batch 3: Reddit, HN, GitHub, OpenAlex
        final_validator,  # Synthesis
    ],
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
   Present the plan to the user clearly in these blocks:
   - **How we will validate**
   - **How we will try to invalidate**
   - **What would kill this idea**
   - **How we will verify supporting evidence**
   - **How we will verify contradiction evidence**
   Include:
   - The product idea as you understood it
   - Which sources will be queried and why
   - Validation keywords and invalidation keywords
   - Overall focus plus validation focus and invalidation focus
   - The falsification criteria
   - Deep-dive hypotheses and evidence validation rules

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
# Export batched source runners for testing if needed
parallel_search = market_research  # Legacy export for smoke tests
