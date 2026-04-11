"""
Tests for the ReportGenerator.
Verifies that the HTML output contains expected content without requiring an API key.
"""
from pathlib import Path

import pytest

from src.report_generator import ReportGenerator, _categorize_skill, _group_skills_by_category


@pytest.fixture(autouse=True)
def mock_env(monkeypatch, tmp_path):
    """Set required env vars and clear the settings cache so tests are isolated."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-for-unit-tests")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    from src.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Skill categorization unit tests
# ---------------------------------------------------------------------------

class TestCategorizeSkill:
    def test_python_is_language(self):
        assert _categorize_skill("python") == "Lenguajes de Programación"

    def test_javascript_is_language(self):
        assert _categorize_skill("javascript") == "Lenguajes de Programación"

    def test_docker_is_tool(self):
        assert _categorize_skill("docker") == "Herramientas y Plataformas"

    def test_aws_is_tool(self):
        assert _categorize_skill("aws") == "Herramientas y Plataformas"

    def test_postgresql_is_database(self):
        assert _categorize_skill("postgresql") == "Bases de Datos"

    def test_sql_is_database(self):
        assert _categorize_skill("sql") == "Bases de Datos"

    def test_comunicacion_is_soft(self):
        assert _categorize_skill("comunicación efectiva") == "Habilidades Blandas"

    def test_unknown_falls_to_concepts(self):
        assert _categorize_skill("quantum computing") == "Conceptos y Metodologías"


class TestGroupSkillsByCategory:
    def test_groups_correctly(self):
        skills = ["python", "docker", "sql", "comunicación", "arquitectura de microservicios"]
        result = _group_skills_by_category(skills)
        assert "Lenguajes de Programación" in result
        assert "python" in result["Lenguajes de Programación"]
        assert "Herramientas y Plataformas" in result
        assert "docker" in result["Herramientas y Plataformas"]
        assert "Bases de Datos" in result
        assert "sql" in result["Bases de Datos"]

    def test_returns_sorted_skills(self):
        skills = ["python", "java", "javascript", "c#"]
        result = _group_skills_by_category(skills)
        lang_skills = result.get("Lenguajes de Programación", [])
        assert lang_skills == sorted(lang_skills)

    def test_empty_input(self):
        result = _group_skills_by_category([])
        assert result == {}


# ---------------------------------------------------------------------------
# ReportGenerator tests
# ---------------------------------------------------------------------------

class TestReportGenerator:
    """mock_env autouse fixture (defined above) sets OUTPUT_DIR to tmp_path — no explicit patch needed."""

    def _render(self, sample_industry_demand, sample_academic_landscape,
                sample_gap_analysis, sample_study_plan, quality_scores=None):
        """Helper to avoid repeating render boilerplate."""
        generator = ReportGenerator()
        return generator.render(
            industry_demand=sample_industry_demand,
            academic_landscape=sample_academic_landscape,
            gap_analysis=sample_gap_analysis,
            study_plan=sample_study_plan,
            quality_scores=quality_scores,
        )

    def test_generates_file(
        self,
        sample_industry_demand,
        sample_academic_landscape,
        sample_gap_analysis,
        sample_study_plan,
    ):
        path = self._render(sample_industry_demand, sample_academic_landscape,
                            sample_gap_analysis, sample_study_plan,
                            quality_scores={"market_research": 0.85, "curriculum": 0.90})
        assert path.exists()
        assert path.suffix == ".html"

    def test_html_contains_sector_name(
        self,
        sample_industry_demand,
        sample_academic_landscape,
        sample_gap_analysis,
        sample_study_plan,
    ):
        path = self._render(sample_industry_demand, sample_academic_landscape,
                            sample_gap_analysis, sample_study_plan)
        html = path.read_text(encoding="utf-8")
        assert "Desarrollo de Software" in html

    def test_html_contains_course_title(
        self,
        sample_industry_demand,
        sample_academic_landscape,
        sample_gap_analysis,
        sample_study_plan,
    ):
        path = self._render(sample_industry_demand, sample_academic_landscape,
                            sample_gap_analysis, sample_study_plan)
        html = path.read_text(encoding="utf-8")
        assert "Cloud-Native" in html

    def test_html_contains_obj_badges(
        self,
        sample_industry_demand,
        sample_academic_landscape,
        sample_gap_analysis,
        sample_study_plan,
    ):
        """Verify that the activities table includes OBJ objective badges."""
        path = self._render(sample_industry_demand, sample_academic_landscape,
                            sample_gap_analysis, sample_study_plan)
        html = path.read_text(encoding="utf-8")
        assert "OBJ " in html  # At least one objective badge present

    def test_html_contains_skills_by_category(
        self,
        sample_industry_demand,
        sample_academic_landscape,
        sample_gap_analysis,
        sample_study_plan,
    ):
        """Verify that skills are grouped by category in the academic section."""
        path = self._render(sample_industry_demand, sample_academic_landscape,
                            sample_gap_analysis, sample_study_plan)
        html = path.read_text(encoding="utf-8")
        assert any(
            cat in html for cat in [
                "Lenguajes de Programación",
                "Herramientas y Plataformas",
                "Bases de Datos",
                "Habilidades Blandas",
                "Conceptos y Metodologías",
            ]
        )

    def test_html_quality_scores_render(
        self,
        sample_industry_demand,
        sample_academic_landscape,
        sample_gap_analysis,
        sample_study_plan,
    ):
        """Verify quality scores appear in the HTML output."""
        quality_scores = {
            "market_research": 0.90,
            "academic_research": 0.80,
            "gap_analysis": 0.75,
            "curriculum": 0.85,
            "activities": 0.88,
            "evaluator": 1.00,
        }
        path = self._render(sample_industry_demand, sample_academic_landscape,
                            sample_gap_analysis, sample_study_plan,
                            quality_scores=quality_scores)
        html = path.read_text(encoding="utf-8")
        assert "Calidad de investigación" in html
        assert "90%" in html or "80%" in html

    def test_market_sources_rendered_as_links(
        self,
        sample_industry_demand,
        sample_academic_landscape,
        sample_gap_analysis,
        sample_study_plan,
    ):
        """Verify HTTP sources are rendered as anchor tags."""
        path = self._render(sample_industry_demand, sample_academic_landscape,
                            sample_gap_analysis, sample_study_plan)
        html = path.read_text(encoding="utf-8")
        assert 'href="https://www.linkedin.com/jobs"' in html
