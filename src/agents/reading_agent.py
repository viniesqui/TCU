from src.agents.base_agent import BaseAgent
import json
import logging

logger = logging.getLogger(__name__)

WEEKLY_READING_PROMPT = """Eres un profesor universitario costarricense y experto en educación técnica en el sector.
Tu misión es redactar una lección y lectura didáctica completa en español, junto con una consigna de tarea práctica para una semana específica del curso universitario diseñado.

El formato del resultado DEBE ser un objeto JSON con las siguientes llaves exactas:
{
  "reading_material": "Texto didáctico completo en español en formato HTML (con títulos <h3>, párrafos <p>, y listas <ul>/<li>). Debe ser detallado (al menos 300-500 palabras) explicando los conceptos teóricos y prácticos de la semana. SI SE TE PIDE, INCLUYE CÓDIGO HTML DE MERMAID O FLASHCARDS EXACTAMENTE COMO SE TE INDIQUE.",
  "assignment_prompt": "Instrucciones detalladas de la tarea o pregunta que el estudiante debe responder y resolver para aplicar lo aprendido esta semana."
}

CRÍTICO: Debes escapar TODAS las comillas dobles internas con \\" y TODOS los saltos de línea con \\n dentro de los textos. El JSON fallará si hay saltos de línea reales dentro del valor de las llaves, especialmente en los diagramas de Mermaid.

FORMATO DE RESPUESTA: Responde ÚNICAMENTE con JSON válido. Sin texto adicional. Sin bloques de código markdown. Solo el objeto JSON puro.
"""

NOTEBOOKLM_PROMPT = """Eres un experto en educación y un brillante presentador de podcasts inmersivos (estilo NotebookLM).
Tu misión es transformar el contenido de la clase en un guion de podcast altamente inmersivo, coloquial y conversacional en español.
Imagina que dos presentadores (Host 1 y Host 2) discuten la teoría y las aplicaciones prácticas, haciendo bromas ligeras, analogías de la vida real y explicando conceptos complejos de manera sencilla para que el estudiante pueda 'escucharlo' y aprender.

El formato del resultado DEBE ser un objeto JSON con las siguientes llaves exactas:
{
  "reading_material": "Texto HTML completo del podcast. DEBES usar etiquetas <div class='podcast-transcript'> para envolver todo, y etiquetas <p class='host-1'><strong>Host 1:</strong> ...</p> y <p class='host-2'><strong>Host 2:</strong> ...</p> para los diálogos.",
  "assignment_prompt": "Instrucciones de la tarea o pregunta reflexiva basada en el podcast."
}

FORMATO DE RESPUESTA: Responde ÚNICAMENTE con JSON válido. Sin texto adicional. Sin bloques de código markdown. Solo el objeto JSON puro.
"""

class NotebookLMAgent(BaseAgent):
    """
    Agent that generates audio-like podcast transcripts for the Aural learning style.
    """
    def __init__(self, max_cost: float | None = None) -> None:
        super().__init__(max_cost=max_cost, 
            name="NotebookLMAgent",
            system_prompt=NOTEBOOKLM_PROMPT,
            tools=[],
        )

    def generate_reading(
        self,
        course_title: str,
        week_number: int,
        week_title: str,
        activity_type: str,
        week_description: str,
        objectives: str,
        learning_profile: dict = None,
    ) -> str:
        user_message = (
            f"Curso: {course_title}\n"
            f"Semana: {week_number}\n"
            f"Título de la Semana: {week_title}\n"
            f"Tipo de Actividad: {activity_type}\n"
            f"Descripción de la Actividad: {week_description}\n"
            f"Objetivos de aprendizaje abordados: {objectives}\n\n"
            f"Convierte este contenido en un episodio de podcast súper interesante y dinámico entre Host 1 y Host 2.\n"
        )
        return self.run(user_message)


class ReadingAgent(BaseAgent):
    """
    Agent that generates detailed weekly readings and assignments.
    """

    def __init__(self, max_cost: float | None = None) -> None:
        super().__init__(max_cost=max_cost, 
            name="ReadingAgent",
            system_prompt=WEEKLY_READING_PROMPT,
            tools=[],
        )

    def generate_reading(
        self,
        course_title: str,
        week_number: int,
        week_title: str,
        activity_type: str,
        week_description: str,
        objectives: str,
        learning_profile: dict = None,
    ) -> str:
        """
        Generate detailed lesson reading and assignment prompt for a given week.
        """
        style_instruction = ""
        if learning_profile:
            v = learning_profile.get("visual_score", 0)
            a = learning_profile.get("aural_score", 0)
            r = learning_profile.get("reading_score", 0)
            k = learning_profile.get("kinesthetic_score", 0)
            
            total = v + a + r + k
            if total > 0:
                vp = round(v / total * 100)
                ap = round(a / total * 100)
                rp = round(r / total * 100)
                kp = round(k / total * 100)
                
                style_instruction = f"PERFIL DE APRENDIZAJE DEL ESTUDIANTE: Visual {vp}%, Auditivo {ap}%, Lectura {rp}%, Kinestésico {kp}%\n\n"
                style_instruction += "ADAPTACIONES HÍBRIDAS SOLICITADAS SEGÚN PERFIL:\n"
                if vp > 25:
                    style_instruction += "- (Visual) Utiliza listas, esquemas claros y OBLIGATORIAMENTE incluye un diagrama de flujo o mapa mental interactivo de Mermaid incrustado EXACTAMENTE en etiquetas <pre class=\"mermaid\">tu diagrama aquí</pre>.\n"
                if ap > 25:
                    style_instruction += "- (Auditivo) Incorpora un tono conversacional y menciona que pueden discutir los conceptos en voz alta.\n"
                if rp > 25:
                    style_instruction += "- (Lectura/Escritura) Asegúrate de incluir definiciones precisas, léxico formal y estructurar el texto lógicamente.\n"
                if kp > 25 or True:
                    style_instruction += (
                        "- (Flashcards Segmentadas y Atómicas - Micro-learning) IMPORTANTÍSIMO: Incluye OBLIGATORIAMENTE entre 6 y 8 flashcards pequeñas y altamente segmentadas.\n"
                        "  REGLAS DE ORO DE COHERENCIA Y LÓGICA:\n"
                        "  1. PROHIBIDO usar títulos de módulo/semana/capítulo (ej: PROHIBIDO 'Módulo de la semana 2...', '1. Introducción', 'Resumen').\n"
                        "  2. PROHIBIDO incluir texto de UI como '(Click para revelar)' o '(Haz clic aquí)'.\n"
                        "  3. CADA <summary> DEBE SER UNA PREGUNTA TÉCNICA O CONCEPTO ATÓMICO REAL (ej: '¿Qué hace git status?', 'Diferencia entre Working Tree y Staging Area').\n"
                        "  Estructura EXACTA de cada tarjeta:\n"
                        "  <details class=\"flashcard\"><summary>¿Qué función cumple 'git commit'?</summary><div class=\"flashcard-body\">Guarda un snapshot del Staging Area en el historial local con un mensaje explicativo.</div></details>\n"
                    )
            else:
                style_instruction = (
                    "ESTILO LECTURA PROFUNDA: Incluye de 6 a 8 flashcards con PREGUNTAS TÉCNICAS REALES (prohibido títulos de capítulos o '(Click para revelar)'): "
                    "<details class=\"flashcard\"><summary>¿Qué es X?</summary><div class=\"flashcard-body\">Explicación corta (1-3 líneas)...</div></details>"
                )
        else:
            style_instruction = (
                "ESTILO LECTURA PROFUNDA: Incluye de 6 a 8 flashcards con PREGUNTAS TÉCNICAS REALES (prohibido títulos de capítulos o '(Click para revelar)'): "
                "<details class=\"flashcard\"><summary>¿Qué es X?</summary><div class=\"flashcard-body\">Explicación corta (1-3 líneas)...</div></details>"
            )

        user_message = (
            f"Curso: {course_title}\n"
            f"Semana: {week_number}\n"
            f"Título de la Semana: {week_title}\n"
            f"Tipo de Actividad: {activity_type}\n"
            f"Descripción de la Actividad: {week_description}\n"
            f"Objetivos de aprendizaje abordados: {objectives}\n\n"
            f"{style_instruction}\n\n"
            f"Genera la lectura didáctica HTML y la tarea para esta semana en JSON."
        )
        return self.run(user_message)
