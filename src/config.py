from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    anthropic_api_key: str
    model: str = "claude-sonnet-4-5"
    max_agent_iterations: int = 12
    max_stage_retries: int = 2
    search_max_results: int = 5
    output_dir: str = "output"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Lazy singleton — only instantiated when first called."""
    return Settings()


# Module-level proxy: use get_settings() to defer instantiation
# This avoids import-time failure when .env is missing during testing.
class _SettingsProxy:
    """Proxy that forwards attribute access to the lazily-loaded Settings."""
    def __getattr__(self, name: str):
        return getattr(get_settings(), name)


settings = _SettingsProxy()
