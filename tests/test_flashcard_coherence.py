import pytest
from src.web.server import validate_and_sanitize_flashcards, extract_flashcards_from_html


def test_junk_module_titles_rejected():
    raw = [
        {"front": "Módulo de la Semana 2: Introducción y Práctica en el Diseño", "back": "Contenido del módulo..."},
        {"front": "Semana 4: Arquitectura de Software", "back": "Explicación de la semana..."},
        {"front": "1. Introducción.", "back": "Texto de introducción de la lección..."},
        {"front": "Conclusión", "back": "Resumen final de la clase..."},
    ]
    result = validate_and_sanitize_flashcards(raw)
    assert len(result) == 0, f"Expected 0 cards, got {result}"


def test_ui_text_cleaning_and_question_formatting():
    raw = [
        {"front": "Control de Versiones con Git (Click para revelar).", "back": "Permite registrar cambios en archivos a lo largo del tiempo."},
        {"front": "git status", "back": "Muestra el estado del árbol de trabajo y del área de preparación."},
        {"front": "¿Qué es el Staging Area?", "back": "Es la zona de preparación antes de confirmar un commit."},
    ]
    result = validate_and_sanitize_flashcards(raw)
    assert len(result) == 3
    assert result[0]["front"] == "📌 ¿En qué consiste 'Control de Versiones con Git' y cuál es su función?"
    assert result[1]["front"] == "📌 ¿En qué consiste 'git status' y cuál es su función?"
    assert result[2]["front"] == "📌 ¿Qué es el Staging Area?"


def test_html_extraction_with_sanitization():
    html_sample = """
    <h2>Módulo de la Semana 1: Fundamentos</h2>
    <h3>1. Introducción</h3>
    <p>Esta es la introducción a la materia de desarrollo de software.</p>

    <details class="flashcard">
        <summary>git commit (Click para revelar)</summary>
        <div class="flashcard-body">Guarda un snapshot del área de preparación en el repositorio local.</div>
    </details>

    <details class="flashcard">
        <summary>¿Qué diferencia existe entre git merge y git rebase?</summary>
        <div class="flashcard-body">Merge une ramas creando un commit de fusión; rebase vuelve a aplicar los commits sobre otra base.</div>
    </details>
    """
    cards = extract_flashcards_from_html(html_sample)
    assert len(cards) == 2
    assert "git commit" in cards[0]["front"]
    assert "git merge" in cards[1]["front"]
