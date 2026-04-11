from src.agents.base_agent import BaseAgent
from src.prompts import CURRICULUM_PROMPT


class CurriculumAgent(BaseAgent):
    """
    Designs the course curriculum (study plan) based on the gap analysis.
    Pure reasoning agent — creates learning objectives, course metadata, bibliography.
    Outputs: Partial StudyPlan (JSON) — without weekly_schedule and evaluator
    """

    def __init__(self) -> None:
        super().__init__(
            name="CurriculumAgent",
            system_prompt=CURRICULUM_PROMPT,
            tools=[],  # No tools — pure reasoning
        )

    def design(self, gap_analysis_json: str) -> str:
        """
        Design the course curriculum based on gap analysis.
        Args:
            gap_analysis_json: serialized GapAnalysis model
        Returns raw JSON string matching partial StudyPlan schema.
        """
        user_message = (
            f"Diseña el plan de estudios base para el curso propuesto. "
            f"Crea objetivos de aprendizaje usando la taxonomía de Bloom, "
            f"define los metadatos del curso y selecciona la bibliografía adecuada.\n\n"
            f"=== ANÁLISIS DE BRECHA ===\n{gap_analysis_json}"
        )
        return self.run(user_message)
