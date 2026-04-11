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

    def research(self, sector: str) -> str:
        """
        Research labor market demand for the given sector in Costa Rica.
        Returns raw JSON string matching IndustryDemand schema.
        """
        user_message = (
            f"Investiga el mercado laboral del sector '{sector}' en Costa Rica. "
            f"Identifica las habilidades más demandadas, analiza ofertas de trabajo reales "
            f"y consulta reportes de la industria. "
            f"Usa múltiples búsquedas web y visita páginas de resultados para obtener datos reales."
        )
        return self.run(user_message)
