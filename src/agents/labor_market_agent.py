from src.agents.base_agent import BaseAgent
from src.prompts import LABOR_MARKET_PROMPT
from src.tools.tool_registry import RESEARCH_TOOLS


class LaborMarketAgent(BaseAgent):
    """
    Investigates the labor market in Costa Rica for a given sector.
    Uses web_search and web_fetch tools to find real job postings and industry reports.
    Outputs: IndustryDemand (JSON)
    """

    def __init__(self) -> None:
        super().__init__(
            name="LaborMarketAgent",
            system_prompt=LABOR_MARKET_PROMPT,
            tools=RESEARCH_TOOLS,
        )

    def research(self, sector: str, retry_context: str | None = None) -> str:
        """
        Research labor market demand for the given sector in Costa Rica.
        Args:
            sector: Industry sector to research.
            retry_context: Quality gate feedback from a previous attempt (Spanish instructions).
        Returns raw JSON string matching IndustryDemand schema.
        """
        user_message = (
            f"Investiga el mercado laboral del sector '{sector}' en Costa Rica. "
            f"Identifica las habilidades más demandadas, analiza ofertas de trabajo reales "
            f"y consulta reportes de la industria. "
            f"Usa múltiples búsquedas web y visita páginas de resultados para obtener datos reales."
        )
        if retry_context:
            user_message += f"\n\n{retry_context}"
        return self.run(user_message)
