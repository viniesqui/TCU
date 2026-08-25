import json
import logging

from src.agents.base_agent import BaseAgent
from src.prompts import ACADEMIC_PROMPT
from src.tools.tool_registry import RESEARCH_TOOLS

logger = logging.getLogger(__name__)


class AcademicAgent(BaseAgent):
    """
    Investigates university course offerings in Costa Rica for a given sector.
    Uses web_search and web_fetch tools to find curricula from public and private universities.
    Outputs: AcademicLandscape (JSON)
    """

    def __init__(self, max_cost: float | None = None) -> None:
        super().__init__(max_cost=max_cost, 
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
        raw = self.run(user_message)
        return self._clean_skills_in_json(raw)

    def _deduplicate_skills(self, skills: list[str]) -> list[str]:
        """
        Single focused Claude call to merge semantic duplicates in a skills list.
        E.g. ['React.js', 'ReactJS', 'Library React'] -> ['react']
        Returns the cleaned list, or the original list on any error.
        """
        if not skills:
            return skills
        try:
            skills_json = json.dumps(skills, ensure_ascii=False)
            response = self._client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=(
                    "Eres una herramienta de normalización de habilidades. "
                    "Tu única tarea es eliminar duplicados semánticos de una lista de habilidades. "
                    "Devuelve ÚNICAMENTE un arreglo JSON válido de strings. "
                    "Sin texto adicional, sin bloques de código markdown."
                ),
                messages=[{"role": "user", "content": (
                    f"Fusiona los duplicados semánticos de esta lista de habilidades técnicas. "
                    f"Ejemplo: 'React.js', 'ReactJS', 'Library React' → 'react'. "
                    f"Usa nombres cortos en minúsculas. Conserva habilidades únicas sin duplicar.\n"
                    f"Lista:\n{skills_json}"
                )}],
            )
            text = self._extract_text(response)
            cleaned = json.loads(self.clean_json(text))
            if isinstance(cleaned, list) and all(isinstance(s, str) for s in cleaned):
                return cleaned
            logger.warning("[AcademicAgent] _deduplicate_skills: unexpected response shape")
        except Exception as exc:
            logger.warning(f"[AcademicAgent] _deduplicate_skills failed: {exc}")
        return skills

    def _clean_skills_in_json(self, raw_json: str) -> str:
        """
        Parse raw_json, semantically deduplicate all_skills_covered, and return updated JSON.
        Falls back to the original string on any parsing or API error.
        """
        try:
            data = json.loads(self.clean_json(raw_json))
            skills = data.get("all_skills_covered", [])
            if not isinstance(skills, list):
                return raw_json
            data["all_skills_covered"] = self._deduplicate_skills(skills)
            return json.dumps(data, ensure_ascii=False)
        except Exception as exc:
            logger.warning(f"[AcademicAgent] _clean_skills_in_json failed: {exc}")
            return raw_json
