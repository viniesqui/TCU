from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Core AI
    anthropic_api_key: str
    model: str = "claude-sonnet-4-5"

    # Agent loop limits
    max_agent_iterations: int = 12
    max_stage_retries: int = 2  # retries per stage on gate failure (total attempts = retries + 1)

    # Web search
    search_max_results: int = 5

    # Output
    output_dir: str = "output"
    log_level: str = "INFO"

    # ── Quality gate thresholds ──────────────────────────────────────────
    # Stage 1 – Market Research
    quality_min_skills: int = 8          # minimum distinct skills in IndustryDemand
    quality_min_job_postings: int = 5    # minimum job postings sampled as evidence (raised from 2 for statistical validity)
    quality_min_sources: int = 2         # minimum sources consulted

    # Stage 2 – Academic Research
    quality_min_universities: int = 5    # minimum university programs found (raised from 3 for CR coverage)
    quality_min_courses_per_program: int = 3  # minimum courses per curriculum entry
    quality_min_skills_covered: int = 10 # minimum skills in all_skills_covered

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Lazy singleton — only instantiated when first called."""
    return Settings()


class _SettingsProxy:
    """Proxy that forwards attribute access to the lazily-loaded Settings."""
    def __getattr__(self, name: str):
        return getattr(get_settings(), name)


settings = _SettingsProxy()
