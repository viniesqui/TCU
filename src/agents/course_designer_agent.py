from src.agents.base_agent import BaseAgent
from src.prompts import COURSE_DESIGNER_PROMPT


class CourseDesignerAgent(BaseAgent):
    """
    Designs the complete course curriculum and weekly activity schedule in a single LLM call.
    Pure reasoning agent — outputs a StudyPlan JSON (without evaluator).

    Combining curriculum and activities into one call eliminates the objective-index
    reference errors that occurred when ActivitiesAgent generated indices without
    seeing the full objective list it was referencing.
    """

    def __init__(self) -> None:
        super().__init__(
            name="CourseDesignerAgent",
            system_prompt=COURSE_DESIGNER_PROMPT,
            tools=[],  # No tools — pure reasoning
        )

    def design(self, gap_analysis_json: str, retry_context: str | None = None) -> str:
        """
        Design the complete course curriculum and weekly schedule based on gap analysis.

        Args:
            gap_analysis_json: serialized GapAnalysis model
            retry_context: Quality gate feedback from a previous attempt (Spanish).

        Returns:
            Raw JSON string matching StudyPlan schema (without evaluator field).
        """
        user_message = (
            f"Diseña el plan de estudios completo para el curso propuesto. "
            f"Primero define los metadatos y objetivos de aprendizaje (Fase 1), "
            f"luego crea el cronograma semanal de actividades que referencien "
            f"esos objetivos por su índice exacto (Fase 2).\n\n"
            f"=== ANÁLISIS DE BRECHA ===\n{gap_analysis_json}"
        )
        if retry_context:
            user_message += f"\n\n{retry_context}"
        return self.run(user_message)
