from src.agents.base_agent import BaseAgent
from src.prompts import COURSE_DESIGNER_PROMPT
from src.agents.course_rag import CourseMaterialRAG


class CourseDesignerAgent(BaseAgent):
    """
    Designs the complete course curriculum and weekly activity schedule in a single LLM call.
    Pure reasoning agent — outputs a StudyPlan JSON (without evaluator).
    Grounded in CourseMaterialRAG if reference material is provided.
    """

    def __init__(self, max_cost: float | None = None) -> None:
        super().__init__(max_cost=max_cost, 
            name="CourseDesignerAgent",
            system_prompt=COURSE_DESIGNER_PROMPT,
            tools=[],  # No tools — pure reasoning
        )

    def design(self, gap_analysis_json: str, retry_context: str | None = None, reference_material: str | None = None) -> str:
        """
        Design the complete course curriculum and weekly schedule based on gap analysis.

        Args:
            gap_analysis_json: serialized GapAnalysis model
            retry_context: Quality gate feedback from a previous attempt (Spanish).
            reference_material: Grounded reference text/syllabus/textbook provided by professor.

        Returns:
            Raw JSON string matching StudyPlan schema (without evaluator field).
        """
        user_message = (
            f"Diseña el plan de estudios completo para el curso propuesto. "
            f"Primero define los metadatos y objetivos de aprendizaje de la Taxonomía de Bloom (Fase 1), "
            f"luego crea el cronograma semanal de actividades que referencien "
            f"esos objetivos por su índice exacto (Fase 2).\n\n"
        )

        if reference_material:
            CourseMaterialRAG.index_material("current_course", reference_material)
            user_message += CourseMaterialRAG.get_reference_context("current_course")

        user_message += f"=== ANÁLISIS DE BRECHA ===\n{gap_analysis_json}"

        if retry_context:
            user_message += f"\n\n{retry_context}"
        return self.run(user_message)
