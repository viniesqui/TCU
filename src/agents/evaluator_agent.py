from src.agents.base_agent import BaseAgent
from src.prompts import EVALUATOR_PROMPT


class EvaluatorAgent(BaseAgent):
    """
    Designs the assessment and evaluation system for the course.
    Pure reasoning agent — creates evaluation components, rubrics, competency matrix.
    Outputs: Evaluator (JSON)
    """

    def __init__(self) -> None:
        super().__init__(
            name="EvaluatorAgent",
            system_prompt=EVALUATOR_PROMPT,
            tools=[],  # No tools — pure reasoning
        )

    def design(self, full_plan_json: str) -> str:
        """
        Design the evaluation system for the course.
        Args:
            full_plan_json: serialized StudyPlan with weekly_schedule included
        Returns raw JSON string matching Evaluator schema.
        """
        user_message = (
            f"Diseña el sistema de evaluación completo para este curso universitario. "
            f"Define los componentes de evaluación (que sumen exactamente 100%), "
            f"crea rúbricas detalladas para cada componente, "
            f"y elabora la matriz de competencias.\n\n"
            f"=== PLAN DE ESTUDIOS CON ACTIVIDADES ===\n{full_plan_json}"
        )
        return self.run(user_message)
