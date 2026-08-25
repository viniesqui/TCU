from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Core AI
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    model: str = "claude-sonnet-4-6"

    # Multimedia APIs
    elevenlabs_api_key: str = ""
    heygen_api_key: str = ""

    # Cost Limit
    max_run_cost: float = 1.00  # maximum global fallback cost
    max_cost_researcher: float = 1.00
    max_cost_coordinator: float = 1.00
    max_cost_professor: float = 1.00
    max_cost_student: float = 1.00

    # Agent loop limits
    max_agent_iterations: int = 25
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
    """Proxy that forwards attribute access to the lazily-loaded Settings singleton."""
    def __getattr__(self, name: str):
        return getattr(get_settings(), name)


# Typed as Settings so IDEs and type-checkers see the actual attribute names.
# At runtime this is a _SettingsProxy (lazy-loaded on first access, safe for import order).
settings: Settings = _SettingsProxy()  # type: ignore[assignment]


def format_api_error_message(exc: Exception) -> str:
    """Format API exceptions into clear, friendly Spanish instructions for users."""
    err_str = str(exc).lower()
    if any(k in err_str for k in ("credit", "balance", "402", "insufficient", "payment", "billing", "credit_balance_too_low")):
        return (
            "⚠️ Error de Saldo en la API Key de Anthropic (402 Payment Required):\n"
            "Tu cuenta de Anthropic no tiene créditos o saldo suficiente para procesar peticiones con el modelo en vivo.\n\n"
            "💡 Opciones para solucionar este problema:\n"
            "1. Recarga saldo en tu cuenta de Anthropic: https://console.anthropic.com/settings/plans\n"
            "2. O usa la app sin costo activando el modo Mocks: Haz clic en '⚙️ Config Demo' (arriba a la derecha) y cambia los presupuestos a $0.00."
        )
    if any(k in err_str for k in ("authentication", "invalid_api_key", "invalid api key", "401", "unauthorized")):
        return (
            "⚠️ Error de Autenticación en la API Key de Anthropic (401 Unauthorized):\n"
            "La llave ANTHROPIC_API_KEY configurada no es válida o ha expirado.\n\n"
            "💡 Solución:\n"
            "Verifica la variable de entorno ANTHROPIC_API_KEY en Render o en tu archivo .env."
        )
    if any(k in err_str for k in ("rate_limit", "rate limit", "429", "too many requests")):
        return (
            "⚠️ Límite de Peticiones Excedido (429 Rate Limit):\n"
            "Se enviaron demasiadas consultas seguidas a la API de Anthropic. Espera unos segundos e intenta de nuevo."
        )
    return f"Error durante la comunicación con la IA: {str(exc)}"

