from src.agents.base_agent import BaseAgent
from src.prompts import ACADEMIC_PROMPT
from src.tools.tool_registry import RESEARCH_TOOLS


class AcademicAgent(BaseAgent):
    """
    Investigates university course offerings in Costa Rica for a given sector.
    Uses web_search and web_fetch tools to find curricula from public and private universities.
    Outputs: AcademicLandscape (JSON)
    """

    def __init__(self) -> None:
        super().__init__(
            name="AcademicAgent",
            system_prompt=ACADEMIC_PROMPT,
            tools=RESEARCH_TOOLS,
        )

    def research(
        self,
        sector: str,
        retry_context: str | None = None,
        broaden_to_region: bool = False,
    ) -> str:
        """
        Research academic offerings for the given sector in Costa Rica.
        Args:
            sector: Industry sector to research.
            retry_context: Quality gate feedback from a previous attempt (Spanish instructions).
            broaden_to_region: If True, broaden search to Central America when CR data is thin.
        Returns raw JSON string matching AcademicLandscape schema.
        """
        scope = "Costa Rica y Centroamérica" if broaden_to_region else "Costa Rica"
        user_message = (
            f"Investiga los programas académicos y cursos ofrecidos por las universidades "
            f"públicas y privadas de {scope} en el área de '{sector}'. "
            f"Revisa los planes de estudio de UCR, TEC, UNA, ULACIT y otras universidades. "
            f"Identifica todas las habilidades y competencias que actualmente se enseñan."
        )
        if broaden_to_region:
            user_message += (
                "\n\nNOTA: Amplía la búsqueda a universidades de toda Centroamérica si "
                "los datos de Costa Rica son insuficientes (USAC Guatemala, UES El Salvador, etc.)."
            )
        if retry_context:
            user_message += f"\n\n{retry_context}"
        return self.run(user_message)
