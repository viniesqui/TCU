from src.agents.base_agent import BaseAgent
import logging

logger = logging.getLogger(__name__)

GRADING_PROMPT = """Eres un profesor universitario costarricense evaluando la tarea de un estudiante.
Tu misión es leer la respuesta del estudiante, compararla con la consigna original de la tarea y calificar su desempeño.
Debes proporcionar una calificación numérica sobre 100 y retroalimentación constructiva.

El formato del resultado DEBE ser un objeto JSON con las siguientes llaves exactas:
{
  "grade": <Un número entre 0 y 100 indicando la calificación>,
  "feedback": "Texto detallado con la retroalimentación cualitativa para el estudiante, explicando en qué acertó y en qué puede mejorar. Utiliza un tono académico pero alentador."
}

FORMATO DE RESPUESTA: Responde ÚNICAMENTE con JSON válido. Sin texto adicional. Sin bloques de código markdown. Solo el objeto JSON puro.
"""

class GradingAgent(BaseAgent):
    """
    Agent that grades student submissions based on the assignment prompt.
    """

    def __init__(self, max_cost: float | None = None) -> None:
        super().__init__(max_cost=max_cost, 
            name="GradingAgent",
            system_prompt=GRADING_PROMPT,
            tools=[],
        )

    def get_fallback_response(self, user_message: str) -> str:
        """Fallback response when API limits are reached."""
        import json
        return json.dumps({
            "grade": 95,
            "feedback": "¡Excelente trabajo! Has demostrado una comprensión sólida de los conceptos de Kubernetes y Docker Compose. (Generado localmente por mock)."
        })

    def grade_submission(
        self,
        assignment_prompt: str,
        submitted_text: str,
    ) -> str:
        """
        Evaluate a student's submission and return a grade and feedback in JSON.
        """
        user_message = (
            f"Consigna de la Tarea:\n{assignment_prompt}\n\n"
            f"Respuesta del Estudiante:\n{submitted_text}\n\n"
            f"Evalúa la respuesta y genera la calificación y retroalimentación en JSON."
        )
        return self.run(user_message)
