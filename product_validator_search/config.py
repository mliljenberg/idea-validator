from dataclasses import dataclass, field


@dataclass
class ResearchConfiguration:
    """Configuration for research-related models and parameters.

    Attributes:
        critic_model (str): Model for evaluation tasks.
        worker_model (str): Model for working/generation tasks.
        max_search_iterations (int): Maximum search iterations allowed.
    """

    critic_model: str = "gemini-3-flash-preview"
    worker_model: str = "gemini-3-flash-preview"
    max_search_iterations: int = 5
    adaptive_refinement_rounds: int = 2
    adaptive_run_condition: str = "conditional"
    adaptive_max_queries_per_round: int = 4
    evidence_corroboration_bar: str = "moderate"
    social_weak_signal_max_impact: str = "warning"
    contradiction_penalty: int = 12
    source_evidence_weights: dict[str, float] = field(
        default_factory=lambda: {
            "review_sites": 0.22,
            "competitors": 0.18,
            "google_trends": 0.14,
            "github": 0.12,
            "reddit": 0.10,
            "hackernews": 0.08,
            "openalex": 0.08,
            "brave_search": 0.08,
            "jobs_signal": 0.07,
            "seo_intent": 0.07,
        }
    )


config = ResearchConfiguration()
