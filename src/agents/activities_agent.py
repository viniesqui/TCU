from src.agents.base_agent import BaseAgent
from src.prompts import ACTIVITIES_PROMPT


class ActivitiesAgent(BaseAgent):
    """
    Designs the weekly learning activities schedule for the course.
    Pure reasoning agent — creates varied, pedagogically sound weekly activities.
    Outputs: weekly_schedule (JSON list of LearningActivity)
    """

    def __init__(self) -> None:
        super().__init__(
            name="ActivitiesAgent",
            system_prompt=ACTIVITIES_PROMPT,
            tools=[],  # No tools — pure reasoning
        )

    def design(self, partial_plan_json: str) -> str:
        """
        Design weekly learning activities for the course.
        Args:
            partial_plan_json: serialized partial StudyPlan (without weekly_schedule)
        Returns raw JSON string with {"weekly_schedule": [...]} matching LearningActivity list.
        """
        user_message = (
            f"Diseña el cronograma semanal de actividades de aprendizaje para este curso. "
            f"Crea una actividad variada y práctica para cada semana del semestre, "
            f"asegurando progresión pedagógica y alineación con los objetivos de aprendizaje.\n\n"
            f"=== PLAN DE ESTUDIOS ===\n{partial_plan_json}"
        )
        return self.run(user_message)
