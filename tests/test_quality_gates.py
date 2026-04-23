"""
Tests for all quality gates.
Each gate is tested for:
  - passing with valid, sufficient data
  - failing specific checks when thresholds are not met
"""
import pytest

from src.models.course_design import EvaluationCriteria, Evaluator, LearningActivity, LearningObjective, StudyPlan
from src.models.gap import SkillGap
from src.quality.downstream_gates import ActivitiesGate, CurriculumGate, EvaluatorGate, GapAnalysisGate
from src.quality.research_gates import AcademicResearchGate, MarketResearchGate


# ---------------------------------------------------------------------------
# MarketResearchGate
# ---------------------------------------------------------------------------

class TestMarketResearchGate:
    def test_passes_with_valid_data(self, sample_industry_demand):
        gate = MarketResearchGate()
        result = gate.evaluate(sample_industry_demand)
        assert result.passed, f"Expected pass but got issues: {result.issues}"

    def test_fails_when_too_few_skills(self, sample_industry_demand):
        sample_industry_demand.top_skills = sample_industry_demand.top_skills[:3]
        gate = MarketResearchGate()
        result = gate.evaluate(sample_industry_demand)
        assert not result.passed
        assert any("habilidades" in issue.lower() for issue in result.issues)

    def test_fails_when_too_few_postings(self, sample_industry_demand):
        sample_industry_demand.job_postings_sampled = sample_industry_demand.job_postings_sampled[:1]
        gate = MarketResearchGate()
        result = gate.evaluate(sample_industry_demand)
        assert not result.passed

    def test_fails_when_no_technical_skills(self, sample_industry_demand):
        for skill in sample_industry_demand.top_skills:
            skill.category = "soft"
        gate = MarketResearchGate()
        result = gate.evaluate(sample_industry_demand)
        assert not result.passed
        assert any("técnicas" in issue.lower() or "técnica" in issue.lower() for issue in result.issues)

    def test_suggests_broadening_when_very_thin(self, sample_industry_demand):
        # Reduce to below the broadening threshold
        sample_industry_demand.top_skills = sample_industry_demand.top_skills[:1]
        sample_industry_demand.job_postings_sampled = []
        gate = MarketResearchGate()
        result = gate.evaluate(sample_industry_demand)
        assert result.suggest_broadening

    def test_retry_instructions_non_empty_on_failure(self, sample_industry_demand):
        sample_industry_demand.top_skills = []
        gate = MarketResearchGate()
        result = gate.evaluate(sample_industry_demand)
        assert not result.passed
        assert len(result.retry_instructions) > 50


# ---------------------------------------------------------------------------
# AcademicResearchGate
# ---------------------------------------------------------------------------

class TestAcademicResearchGate:
    def test_passes_with_valid_data(self, sample_academic_landscape):
        gate = AcademicResearchGate()
        result = gate.evaluate(sample_academic_landscape)
        assert result.passed, f"Expected pass but got issues: {result.issues}"

    def test_fails_when_too_few_universities(self, sample_academic_landscape):
        sample_academic_landscape.curricula_sampled = sample_academic_landscape.curricula_sampled[:2]
        gate = AcademicResearchGate()
        result = gate.evaluate(sample_academic_landscape)
        assert not result.passed

    def test_fails_when_no_public_universities(self, sample_academic_landscape):
        for c in sample_academic_landscape.curricula_sampled:
            c.is_public = False
        gate = AcademicResearchGate()
        result = gate.evaluate(sample_academic_landscape)
        assert not result.passed
        assert any("pública" in issue.lower() for issue in result.issues)

    def test_fails_when_no_private_universities(self, sample_academic_landscape):
        for c in sample_academic_landscape.curricula_sampled:
            c.is_public = True
        gate = AcademicResearchGate()
        result = gate.evaluate(sample_academic_landscape)
        assert not result.passed
        assert any("privada" in issue.lower() for issue in result.issues)

    def test_fails_when_skills_covered_too_few(self, sample_academic_landscape):
        sample_academic_landscape.all_skills_covered = ["python", "java"]
        gate = AcademicResearchGate()
        result = gate.evaluate(sample_academic_landscape)
        assert not result.passed

    def test_suggests_broadening_when_very_few_universities(self, sample_academic_landscape):
        sample_academic_landscape.curricula_sampled = sample_academic_landscape.curricula_sampled[:1]
        gate = AcademicResearchGate()
        result = gate.evaluate(sample_academic_landscape)
        assert result.suggest_broadening


# ---------------------------------------------------------------------------
# GapAnalysisGate
# ---------------------------------------------------------------------------

class TestGapAnalysisGate:
    def test_passes_with_valid_data(self, sample_gap_analysis):
        gate = GapAnalysisGate()
        result = gate.evaluate(sample_gap_analysis)
        assert result.passed, f"Expected pass but got issues: {result.issues}"

    def test_fails_when_too_few_actionable_gaps(self, sample_gap_analysis):
        sample_gap_analysis.critical_gaps = []
        sample_gap_analysis.moderate_gaps = []
        gate = GapAnalysisGate()
        result = gate.evaluate(sample_gap_analysis)
        assert not result.passed

    def test_fails_when_critical_gap_has_low_demand(self, sample_gap_analysis):
        # Add a critical gap with demand below 0.6 threshold
        sample_gap_analysis.critical_gaps.append(
            SkillGap(
                skill_name="low-demand skill",
                market_demand_score=0.30,  # Below 0.6 threshold
                academic_coverage_score=0.05,
                gap_severity="critical",
                notes="Should fail — low demand",
            )
        )
        gate = GapAnalysisGate()
        result = gate.evaluate(sample_gap_analysis)
        assert not result.passed
        assert any("low-demand skill" in issue for issue in result.issues)

    def test_fails_when_critical_gap_has_high_coverage(self, sample_gap_analysis):
        # Add a critical gap with coverage above 0.2 threshold
        sample_gap_analysis.critical_gaps.append(
            SkillGap(
                skill_name="well-covered skill",
                market_demand_score=0.85,
                academic_coverage_score=0.70,  # Above 0.2 threshold
                gap_severity="critical",
                notes="Should fail — too well covered",
            )
        )
        gate = GapAnalysisGate()
        result = gate.evaluate(sample_gap_analysis)
        assert not result.passed

    def test_fails_when_no_well_covered_list(self, sample_gap_analysis):
        sample_gap_analysis.well_covered = []
        gate = GapAnalysisGate()
        result = gate.evaluate(sample_gap_analysis)
        assert not result.passed
        assert any("bien cubiertas" in issue.lower() or "well_covered" in issue.lower() or "cubiertas" in issue.lower() for issue in result.issues)

    def test_fails_when_course_title_too_short(self, sample_gap_analysis):
        sample_gap_analysis.proposed_course_title = "Curso"
        gate = GapAnalysisGate()
        result = gate.evaluate(sample_gap_analysis)
        assert not result.passed


# ---------------------------------------------------------------------------
# CurriculumGate
# ---------------------------------------------------------------------------

class TestCurriculumGate:
    _BLOOM_LEVELS = ["recordar", "comprender", "aplicar", "analizar", "evaluar", "crear", "aplicar"]

    def _make_study_plan(self, obj_count=7, credits=4, hours_per_week=12.0, total_weeks=16, bibliography=None):
        objectives = [
            LearningObjective(bloom_level=level, description=f"Objetivo {i}")
            for i, level in enumerate(self._BLOOM_LEVELS[:obj_count])
        ]
        return StudyPlan(
            course_title="Curso de Prueba",
            course_code="TCU-001",
            credits=credits,
            hours_per_week=hours_per_week,
            total_weeks=total_weeks,
            target_audience="Estudiantes de ingeniería.",
            learning_objectives=objectives,
            bibliography=bibliography or ["Ref 1", "Ref 2", "Ref 3", "Ref 4"],
        )

    def test_passes_with_valid_data(self):
        gate = CurriculumGate()
        result = gate.evaluate(self._make_study_plan())
        assert result.passed, f"Expected pass but got issues: {result.issues}"

    def test_fails_when_obj_count_below_6(self):
        gate = CurriculumGate()
        result = gate.evaluate(self._make_study_plan(obj_count=4))
        assert not result.passed
        assert any("objetivos" in issue.lower() for issue in result.issues)

    def test_passes_with_exactly_6_objectives(self):
        gate = CurriculumGate()
        result = gate.evaluate(self._make_study_plan(obj_count=6))
        assert result.passed, f"Expected pass with 6 objectives but got: {result.issues}"

    def test_fails_when_no_higher_bloom_levels(self):
        gate = CurriculumGate()
        # Only "recordar" — no analizar/evaluar/crear
        plan = StudyPlan(
            course_title="Test", course_code="TCU-001", credits=4,
            hours_per_week=12.0, total_weeks=16, target_audience="Test",
            learning_objectives=[
                LearningObjective(bloom_level="recordar", description=f"Obj {i}") for i in range(7)
            ],
            bibliography=["Ref 1", "Ref 2", "Ref 3"],
        )
        result = gate.evaluate(plan)
        assert not result.passed

    def test_fails_when_no_crear_level(self):
        gate = CurriculumGate()
        plan = StudyPlan(
            course_title="Test", course_code="TCU-001", credits=4,
            hours_per_week=12.0, total_weeks=16, target_audience="Test",
            learning_objectives=[
                LearningObjective(bloom_level="recordar", description="Obj 1"),
                LearningObjective(bloom_level="comprender", description="Obj 2"),
                LearningObjective(bloom_level="aplicar", description="Obj 3"),
                LearningObjective(bloom_level="analizar", description="Obj 4"),
                LearningObjective(bloom_level="evaluar", description="Obj 5"),
                LearningObjective(bloom_level="aplicar", description="Obj 6"),
            ],
            bibliography=["Ref 1", "Ref 2", "Ref 3"],
        )
        result = gate.evaluate(plan)
        assert not result.passed
        assert any("crear" in issue.lower() for issue in result.issues)

    def test_fails_when_hours_too_low_for_credits(self):
        gate = CurriculumGate()
        # 4 credits → expected 12 hrs/week; 5 is below 0.8*12=9.6
        result = gate.evaluate(self._make_study_plan(credits=4, hours_per_week=5.0))
        assert not result.passed
        assert any("horas" in issue.lower() or "crédito" in issue.lower() for issue in result.issues)

    def test_fails_when_hours_too_high_for_credits(self):
        gate = CurriculumGate()
        # 4 credits → expected 12 hrs/week; 20 is above 1.2*12=14.4
        result = gate.evaluate(self._make_study_plan(credits=4, hours_per_week=20.0))
        assert not result.passed

    def test_fails_when_total_weeks_out_of_range(self):
        gate = CurriculumGate()
        result = gate.evaluate(self._make_study_plan(total_weeks=8))
        assert not result.passed
        assert any("semanas" in issue.lower() or "semestre" in issue.lower() for issue in result.issues)


# ---------------------------------------------------------------------------
# ActivitiesGate
# ---------------------------------------------------------------------------

class TestActivitiesGate:
    def test_passes_with_valid_data(self, sample_activities, sample_learning_objectives):
        gate = ActivitiesGate()
        result = gate.evaluate(
            activities=sample_activities,
            total_weeks=16,
            num_objectives=len(sample_learning_objectives),
        )
        assert result.passed, f"Expected pass but got issues: {result.issues}"

    def test_fails_when_activity_count_too_low(self, sample_activities, sample_learning_objectives):
        gate = ActivitiesGate()
        result = gate.evaluate(
            activities=sample_activities[:5],
            total_weeks=16,
            num_objectives=len(sample_learning_objectives),
        )
        assert not result.passed
        assert any("actividades" in issue.lower() for issue in result.issues)

    def test_fails_when_objectives_uncovered(self, sample_learning_objectives):
        # Create activities that never reference objective index 6
        activities = [
            LearningActivity(
                week=i + 1,
                title=f"Act {i + 1}",
                activity_type="laboratorio",
                description="desc",
                estimated_hours=3.0,
                learning_objectives_addressed=[0, 1],  # never covers index 6
            )
            for i in range(16)
        ]
        gate = ActivitiesGate()
        result = gate.evaluate(
            activities=activities,
            total_weeks=16,
            num_objectives=len(sample_learning_objectives),
        )
        assert not result.passed
        assert any("6" in issue for issue in result.issues)

    def test_fails_when_activity_types_not_varied(self, sample_learning_objectives):
        activities = [
            LearningActivity(
                week=i + 1,
                title=f"Act {i + 1}",
                activity_type="lectura",  # all the same type
                description="desc",
                estimated_hours=2.0,
                learning_objectives_addressed=[i % len(sample_learning_objectives)],
            )
            for i in range(16)
        ]
        gate = ActivitiesGate()
        result = gate.evaluate(
            activities=activities,
            total_weeks=16,
            num_objectives=len(sample_learning_objectives),
        )
        assert not result.passed

    def test_fails_when_no_practical_activities(self, sample_learning_objectives):
        activities = [
            LearningActivity(
                week=i + 1,
                title=f"Act {i + 1}",
                activity_type="lectura" if i % 2 == 0 else "debate",
                description="desc",
                estimated_hours=2.0,
                learning_objectives_addressed=[i % len(sample_learning_objectives)],
            )
            for i in range(16)
        ]
        gate = ActivitiesGate()
        result = gate.evaluate(
            activities=activities,
            total_weeks=16,
            num_objectives=len(sample_learning_objectives),
        )
        assert not result.passed
        assert any("práctica" in issue.lower() or "laboratorio" in issue.lower() for issue in result.issues)

    def test_fails_when_no_evaluation_activity(self, sample_learning_objectives):
        activities = [
            LearningActivity(
                week=i + 1,
                title=f"Act {i + 1}",
                activity_type="laboratorio",
                description="desc",
                estimated_hours=3.0,
                learning_objectives_addressed=[i % len(sample_learning_objectives)],
            )
            for i in range(16)
        ]
        gate = ActivitiesGate()
        result = gate.evaluate(
            activities=activities,
            total_weeks=16,
            num_objectives=len(sample_learning_objectives),
        )
        assert not result.passed
        assert any("evaluacion" in issue.lower() or "evaluación" in issue.lower() for issue in result.issues)


# ---------------------------------------------------------------------------
# EvaluatorGate (new)
# ---------------------------------------------------------------------------

class TestEvaluatorGate:
    def test_passes_with_valid_data(self, sample_evaluator):
        gate = EvaluatorGate()
        result = gate.evaluate(sample_evaluator)
        assert result.passed, f"Expected pass but got issues: {result.issues}"

    def test_fails_when_too_few_components(self, sample_evaluator):
        # Reduce to 3 components, adjusting weights to still sum to 100
        sample_evaluator.evaluation_components = [
            EvaluationCriteria(component="A", weight_percent=40.0, rubric_items=["c1", "c2", "c3"]),
            EvaluationCriteria(component="B", weight_percent=40.0, rubric_items=["c1", "c2", "c3"]),
            EvaluationCriteria(component="C", weight_percent=20.0, rubric_items=["c1", "c2", "c3"]),
        ]
        gate = EvaluatorGate()
        result = gate.evaluate(sample_evaluator)
        assert not result.passed

    def test_fails_when_component_exceeds_40_percent(self, sample_evaluator):
        # Make one component weight 45% (above the 40% limit)
        components = list(sample_evaluator.evaluation_components)
        components[0] = EvaluationCriteria(
            component=components[0].component,
            weight_percent=45.0,
            rubric_items=components[0].rubric_items,
        )
        # Reduce another component so total stays ~100
        components[1] = EvaluationCriteria(
            component=components[1].component,
            weight_percent=components[1].weight_percent - 10.0,
            rubric_items=components[1].rubric_items,
        )
        sample_evaluator.evaluation_components = components
        gate = EvaluatorGate()
        result = gate.evaluate(sample_evaluator)
        assert not result.passed
        assert any("peso excesivo" in issue.lower() or "40" in issue for issue in result.issues)

    def test_fails_when_rubric_items_too_few(self, sample_evaluator):
        # Set one component to have only 1 rubric item
        components = list(sample_evaluator.evaluation_components)
        components[0] = EvaluationCriteria(
            component=components[0].component,
            weight_percent=components[0].weight_percent,
            rubric_items=["solo un criterio"],  # Below min of 3
        )
        sample_evaluator.evaluation_components = components
        gate = EvaluatorGate()
        result = gate.evaluate(sample_evaluator)
        assert not result.passed
        assert any("rúbrica" in issue.lower() for issue in result.issues)

    def test_fails_when_competency_matrix_empty(self, sample_evaluator):
        sample_evaluator.competency_matrix = {}
        gate = EvaluatorGate()
        result = gate.evaluate(sample_evaluator)
        assert not result.passed
        assert any("competencias" in issue.lower() or "matriz" in issue.lower() for issue in result.issues)

    def test_retry_instructions_present_on_failure(self, sample_evaluator):
        sample_evaluator.competency_matrix = {}
        gate = EvaluatorGate()
        result = gate.evaluate(sample_evaluator)
        assert not result.passed
        assert len(result.retry_instructions) > 50
