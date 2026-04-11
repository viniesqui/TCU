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

    def research(self, sector: str) -> str:
        """
        Research academic offerings for the given sector in Costa Rica.
        Returns raw JSON string matching AcademicLandscape schema.
        """
        user_message = (
            f"Investiga los programas académicos y cursos ofrecidos por las universidades "
            f"públicas y privadas de Costa Rica en el área de '{sector}'. "
            f"Revisa los planes de estudio de UCR, TEC, UNA, ULACIT y otras universidades. "
            f"Identifica todas las habilidades y competencias que actualmente se enseñan."
        )
        return self.run(user_message)
