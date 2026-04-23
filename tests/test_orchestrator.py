"""
Integration tests for the Orchestrator with mocked agents.
No real API calls — all agents return hardcoded valid JSON.
"""
import json
import os
from unittest.mock import MagicMock, patch, call

import pytest

from src.models.academic import AcademicLandscape
from src.models.course_design import Evaluator, StudyPlan
from src.models.gap import GapAnalysis
from src.models.market import IndustryDemand


# ---------------------------------------------------------------------------
# Helpers: pre-serialized valid JSON for each agent output
# ---------------------------------------------------------------------------

def _make_industry_demand_json():
    return json.dumps({
        "sector": "Desarrollo de Software",
        "top_skills": [
            {"name": f"skill{i}", "category": "technical", "frequency_score": 0.9 - i * 0.05, "example_sources": []}
            for i in range(10)
        ],
        "job_postings_sampled": [
            {
                "title": f"Developer {i}", "company": f"Co {i}",
                "source_url": f"https://example.com/job{i}",
                "required_skills": [], "preferred_skills": [],
                "seniority": "mid", "location": "Costa Rica",
            }
            for i in range(5)
        ],
        "market_sources": ["https://linkedin.com", "https://computrabajo.co.cr", "https://camtic.org"],
        "research_date": "2025-01-15",
        "summary": "Resumen del mercado laboral con suficiente longitud para pasar el gate de calidad.",
    })


def _make_academic_landscape_json():
    return json.dumps({
        "curricula_sampled": [
            {
                "degree_name": f"Carrera {i}",
                "degree_level": "bachillerato",
                "university": f"Universidad {i}",
                "is_public": i < 3,
                "url": f"https://universidad{i}.ac.cr",
                "courses": [
                    {"code": None, "name": f"Curso {j}", "credits": 3, "skills_taught": [f"skill{j}"], "description": None}
                    for j in range(5)
                ],
                "last_updated": "2024",
            }
            for i in range(5)
        ],
        "all_skills_covered": [f"skill{i}" for i in range(15)],
        "research_date": "2025-01-15",
        "summary": "Resumen de la oferta académica costarricense con descripción de programas públicos y privados.",
    })


def _make_gap_analysis_json():
    return json.dumps({
        "sector": "Desarrollo de Software",
        "critical_gaps": [
            {"skill_name": f"gap_skill{i}", "market_demand_score": 0.80, "academic_coverage_score": 0.10, "gap_severity": "critical", "notes": "Critical gap"}
            for i in range(5)
        ],
        "moderate_gaps": [
            {"skill_name": f"mod_skill{i}", "market_demand_score": 0.55, "academic_coverage_score": 0.40, "gap_severity": "moderate", "notes": "Moderate gap"}
            for i in range(3)
        ],
        "well_covered": [
            {"skill_name": f"covered_skill{i}", "market_demand_score": 0.70, "academic_coverage_score": 0.85, "gap_severity": "covered", "notes": "Well covered"}
            for i in range(3)
        ],
        "opportunity_statement": "Existe una brecha educativa significativa que justifica la creación de un nuevo curso en tecnologías modernas de desarrollo.",
        "proposed_course_title": "Desarrollo Cloud-Native y DevOps Moderno",
        "proposed_course_rationale": "El mercado demanda competencias que las universidades costarricenses no cubren adecuadamente.",
    })


def _make_course_design_json():
    """Combined course design output: learning objectives + weekly schedule (no evaluator)."""
    activity_types = ["lectura", "laboratorio", "laboratorio", "taller",
                      "laboratorio", "caso_estudio", "proyecto", "taller",
                      "laboratorio", "proyecto", "debate", "proyecto",
                      "proyecto", "proyecto", "taller", "evaluacion"]
    return json.dumps({
        "course_title": "Desarrollo Cloud-Native y DevOps Moderno",
        "course_code": "TCU-501",
        "credits": 4,
        "hours_per_week": 12.0,
        "total_weeks": 16,
        "target_audience": "Estudiantes de tercer año de Ingeniería en Computación.",
        "prerequisites": ["Sistemas Operativos"],
        "learning_objectives": [
            {"bloom_level": "recordar", "description": "Identificar componentes cloud."},
            {"bloom_level": "comprender", "description": "Explicar contenedores Docker."},
            {"bloom_level": "aplicar", "description": "Implementar aplicación con Docker."},
            {"bloom_level": "aplicar", "description": "Usar Kubernetes para desplegar servicios."},
            {"bloom_level": "analizar", "description": "Comparar estrategias CI/CD."},
            {"bloom_level": "evaluar", "description": "Evaluar seguridad de pipelines."},
            {"bloom_level": "crear", "description": "Diseñar pipeline CI/CD completo."},
        ],
        "bibliography": ["Ref 1", "Ref 2", "Ref 3"],
        "weekly_schedule": [
            {
                "week": i + 1,
                "title": f"Actividad semana {i + 1}",
                "activity_type": activity_types[i],
                "description": f"Descripción detallada de la actividad de la semana {i + 1}.",
                "estimated_hours": 3.0 if activity_types[i] == "lectura" else 5.0,
                "learning_objectives_addressed": [i % 7, (i + 1) % 7],
            }
            for i in range(16)
        ],
    })


def _make_evaluator_json():
    return json.dumps({
        "evaluation_components": [
            {"component": "Laboratorios", "weight_percent": 25.0, "rubric_items": ["Funciona", "Documentado", "Buenas prácticas"], "passing_threshold": 70.0},
            {"component": "Proyecto", "weight_percent": 35.0, "rubric_items": ["Completo", "Funcional", "Presentado", "Bien documentado"], "passing_threshold": 70.0},
            {"component": "Examen Parcial", "weight_percent": 15.0, "rubric_items": ["Conceptos correctos", "Aplicación práctica", "Casos de uso"], "passing_threshold": 70.0},
            {"component": "Examen Final", "weight_percent": 20.0, "rubric_items": ["Comprensión integral", "Análisis crítico", "Soluciones justificadas"], "passing_threshold": 70.0},
            {"component": "Participación", "weight_percent": 5.0, "rubric_items": ["Asistencia", "Aportes", "Colaboración"], "passing_threshold": 70.0},
        ],
        "competency_matrix": {
            "docker": ["Actividad semana 2", "Actividad semana 3"],
            "kubernetes": ["Actividad semana 5", "Actividad semana 13"],
        },
    })


# ---------------------------------------------------------------------------
# Orchestrator integration tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_env(monkeypatch, tmp_path):
    """Set required environment variables and stub out the lru_cache so tests are isolated."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-for-unit-tests")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    # Clear the lru_cache so settings are freshly loaded with our env vars
    from src.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestOrchestratorIntegration:
    """
    Tests the full orchestrator pipeline with all agents mocked.
    Verifies stage sequencing, quality gate integration, and error recovery.
    """

    def _patch_all_agents(self):
        """Return a dict of mock return values for all agents."""
        return {
            "LaborMarketAgent.research": _make_industry_demand_json(),
            "AcademicAgent.research": _make_academic_landscape_json(),
            "GapAnalystAgent.analyze": _make_gap_analysis_json(),
            "CourseDesignerAgent.design": _make_course_design_json(),
            "EvaluatorAgent.design": _make_evaluator_json(),
        }

    def _run_pipeline(self, patches_dict):
        """Helper: patch all agents and run the pipeline."""
        from src.agents.orchestrator import Orchestrator

        with (
            patch("src.agents.labor_market_agent.LaborMarketAgent.research", return_value=patches_dict["LaborMarketAgent.research"]),
            patch("src.agents.academic_agent.AcademicAgent.research", return_value=patches_dict["AcademicAgent.research"]),
            patch("src.agents.gap_analyst_agent.GapAnalystAgent.analyze", return_value=patches_dict["GapAnalystAgent.analyze"]),
            patch("src.agents.course_designer_agent.CourseDesignerAgent.design", return_value=patches_dict["CourseDesignerAgent.design"]),
            patch("src.agents.evaluator_agent.EvaluatorAgent.design", return_value=patches_dict["EvaluatorAgent.design"]),
        ):
            orchestrator = Orchestrator()
            report_path = orchestrator.run(sector="Desarrollo de Software")
            return orchestrator, report_path

    def test_full_pipeline_produces_report(self, tmp_path):
        """Full pipeline with valid mocked data should produce an HTML report."""
        orchestrator, report_path = self._run_pipeline(self._patch_all_agents())

        assert report_path
        from pathlib import Path
        assert Path(report_path).exists()

    def test_quality_scores_populated_after_run(self, tmp_path):
        """Verify quality_scores dict is populated after successful run."""
        orchestrator, _ = self._run_pipeline(self._patch_all_agents())

        assert "market_research" in orchestrator._quality_scores
        assert "academic_research" in orchestrator._quality_scores
        assert "evaluator" in orchestrator._quality_scores

    def test_gate_failure_triggers_retry(self, tmp_path):
        """When a gate fails, the agent should be called again on the next attempt."""
        from src.agents.orchestrator import Orchestrator

        patches = self._patch_all_agents()
        thin_demand = json.loads(patches["LaborMarketAgent.research"])
        thin_demand["top_skills"] = thin_demand["top_skills"][:2]  # Too few — will fail
        market_side_effects = [json.dumps(thin_demand), patches["LaborMarketAgent.research"]]

        research_mock = MagicMock(side_effect=market_side_effects)

        with (
            patch("src.agents.labor_market_agent.LaborMarketAgent.research", research_mock),
            patch("src.agents.academic_agent.AcademicAgent.research", return_value=patches["AcademicAgent.research"]),
            patch("src.agents.gap_analyst_agent.GapAnalystAgent.analyze", return_value=patches["GapAnalystAgent.analyze"]),
            patch("src.agents.course_designer_agent.CourseDesignerAgent.design", return_value=patches["CourseDesignerAgent.design"]),
            patch("src.agents.evaluator_agent.EvaluatorAgent.design", return_value=patches["EvaluatorAgent.design"]),
        ):
            orchestrator = Orchestrator()
            orchestrator.run(sector="Desarrollo de Software")

        # Agent was called at least twice (failed once, succeeded on retry)
        assert research_mock.call_count >= 2

    def test_max_retries_exceeded_still_produces_output(self, tmp_path):
        """If gate keeps failing beyond max_retries, pipeline should NOT crash."""
        from src.agents.orchestrator import Orchestrator

        patches = self._patch_all_agents()
        thin_demand = json.loads(patches["LaborMarketAgent.research"])
        thin_demand["top_skills"] = thin_demand["top_skills"][:1]  # Will always fail gate

        with (
            patch("src.agents.labor_market_agent.LaborMarketAgent.research", return_value=json.dumps(thin_demand)),
            patch("src.agents.academic_agent.AcademicAgent.research", return_value=patches["AcademicAgent.research"]),
            patch("src.agents.gap_analyst_agent.GapAnalystAgent.analyze", return_value=patches["GapAnalystAgent.analyze"]),
            patch("src.agents.course_designer_agent.CourseDesignerAgent.design", return_value=patches["CourseDesignerAgent.design"]),
            patch("src.agents.evaluator_agent.EvaluatorAgent.design", return_value=patches["EvaluatorAgent.design"]),
        ):
            orchestrator = Orchestrator()
            # Should NOT raise — pipeline proceeds with best available result
            report_path = orchestrator.run(sector="Desarrollo de Software")

        assert report_path

    def test_evaluator_passes_retry_context_on_weight_error(self, tmp_path):
        """When evaluator weights don't sum to 100, retry_context should be passed on next call."""
        from src.agents.orchestrator import Orchestrator

        patches = self._patch_all_agents()
        bad_evaluator = {
            "evaluation_components": [
                {"component": "A", "weight_percent": 50.0, "rubric_items": ["c1", "c2", "c3"], "passing_threshold": 70.0},
                {"component": "B", "weight_percent": 30.0, "rubric_items": ["c1", "c2", "c3"], "passing_threshold": 70.0},
                # Missing 20% — total is 80, will fail Pydantic's check_weights_sum
            ],
            "competency_matrix": {"skill": ["Act 1"]},
        }

        call_args_list = []

        def evaluator_side_effect(full_json, retry_context=None):
            call_args_list.append(retry_context)
            if len(call_args_list) == 1:
                return json.dumps(bad_evaluator)
            return patches["EvaluatorAgent.design"]

        with (
            patch("src.agents.labor_market_agent.LaborMarketAgent.research", return_value=patches["LaborMarketAgent.research"]),
            patch("src.agents.academic_agent.AcademicAgent.research", return_value=patches["AcademicAgent.research"]),
            patch("src.agents.gap_analyst_agent.GapAnalystAgent.analyze", return_value=patches["GapAnalystAgent.analyze"]),
            patch("src.agents.course_designer_agent.CourseDesignerAgent.design", return_value=patches["CourseDesignerAgent.design"]),
            patch("src.agents.evaluator_agent.EvaluatorAgent.design", side_effect=evaluator_side_effect),
        ):
            orchestrator = Orchestrator()
            orchestrator.run(sector="Desarrollo de Software")

        # First call had no retry_context; second call had retry_context with error info
        assert len(call_args_list) >= 2
        assert call_args_list[0] is None
        assert call_args_list[1] is not None
        assert "100" in call_args_list[1]  # Error message mentions 100% sum requirement
