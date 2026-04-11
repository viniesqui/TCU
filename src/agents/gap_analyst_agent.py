from src.agents.base_agent import BaseAgent
from src.prompts import GAP_ANALYST_PROMPT


class GapAnalystAgent(BaseAgent):
    """
    Analyzes the gap between labor market needs and academic offerings.
    Pure reasoning agent — no web tools needed, works from structured data passed in.
    Outputs: GapAnalysis (JSON)
    """

    def __init__(self) -> None:
        super().__init__(
            name="GapAnalystAgent",
            system_prompt=GAP_ANALYST_PROMPT,
            tools=[],  # No tools — pure reasoning
        )

    def analyze(
        self,
        industry_demand_json: str,
        academic_landscape_json: str,
        retry_context: str | None = None,
    ) -> str:
        """
        Analyze gap between market needs and academic offerings.
        Args:
            industry_demand_json: serialized IndustryDemand model
            academic_landscape_json: serialized AcademicLandscape model
            retry_context: Quality gate feedback from a previous attempt.
        Returns raw JSON string matching GapAnalysis schema.
        """
        user_message = (
            f"Analiza la brecha entre las necesidades del mercado laboral y la oferta académica "
            f"universitaria en Costa Rica. Basándote en los datos a continuación, identifica "
            f"las brechas críticas, moderadas y bien cubiertas, y propone un curso que las aborde.\n\n"
            f"=== DEMANDA DEL MERCADO LABORAL ===\n{industry_demand_json}\n\n"
            f"=== OFERTA ACADÉMICA UNIVERSITARIA ===\n{academic_landscape_json}"
        )
        if retry_context:
            user_message += f"\n\n{retry_context}"
        return self.run(user_message)
