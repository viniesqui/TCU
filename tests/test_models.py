"""
Tests for Pydantic model validation.
Verifies that models enforce their constraints and validators.
"""
import pytest
from pydantic import ValidationError

from src.models.academic import AcademicLandscape, Course, Curriculum
from src.models.course_design import (
    Evaluator,
    EvaluationCriteria,
    LearningActivity,
    LearningObjective,
    StudyPlan,
)
from src.models.gap import GapAnalysis, SkillGap
from src.models.market import IndustryDemand, Skill


# ---------------------------------------------------------------------------
# Market model tests
# ---------------------------------------------------------------------------

class TestSkillModel:
    def test_valid_skill(self):
        skill = Skill(name="python", category="technical", frequency_score=0.85)
        assert skill.frequency_score == 0.85

    def test_rejects_frequency_score_above_1(self):
        with pytest.raises(ValidationError):
            Skill(name="python", category="technical", frequency_score=1.5)

    def test_rejects_frequency_score_below_0(self):
        with pytest.raises(ValidationError):
            Skill(name="python", category="technical", frequency_score=-0.1)

    def test_rejects_invalid_category(self):
        with pytest.raises(ValidationError):
            Skill(name="python", category="invalid_category", frequency_score=0.5)


class TestIndustryDemand:
    def test_valid_industry_demand(self, sample_industry_demand):
        assert sample_industry_demand.sector == "Desarrollo de Software"
        assert len(sample_industry_demand.top_skills) == 10

    def test_requires_research_date(self):
        with pytest.raises(ValidationError):
            IndustryDemand(
                sector="Test",
                top_skills=[],
                market_sources=["https://example.com"],
                # missing research_date
                summary="Test summary",
            )


# ---------------------------------------------------------------------------
# Gap model tests
# ---------------------------------------------------------------------------

class TestSkillGap:
    def test_valid_gap(self):
        gap = SkillGap(
            skill_name="kubernetes",
            market_demand_score=0.75,
            academic_coverage_score=0.10,
            gap_severity="critical",
            notes="Test",
        )
        assert gap.gap_severity == "critical"

    def test_rejects_invalid_severity(self):
        with pytest.raises(ValidationError):
            SkillGap(
                skill_name="test",
                market_demand_score=0.75,
                academic_coverage_score=0.10,
                gap_severity="extreme",  # invalid
                notes="Test",
            )

    def test_rejects_score_above_1(self):
        with pytest.raises(ValidationError):
            SkillGap(
                skill_name="test",
                market_demand_score=1.5,  # invalid
                academic_coverage_score=0.10,
                gap_severity="critical",
                notes="Test",
            )


class TestGapAnalysis:
    def test_valid_gap_analysis(self, sample_gap_analysis):
        assert len(sample_gap_analysis.critical_gaps) == 5
        assert sample_gap_analysis.proposed_course_title

    def test_requires_sector(self):
        with pytest.raises(ValidationError):
            GapAnalysis(
                # missing sector
                critical_gaps=[],
                moderate_gaps=[],
                well_covered=[],
                opportunity_statement="test",
                proposed_course_title="Curso Test",
                proposed_course_rationale="Rationale",
            )


# ---------------------------------------------------------------------------
# Course design model tests
# ---------------------------------------------------------------------------

class TestLearningActivity:
    def test_valid_activity(self):
        act = LearningActivity(
            week=1,
            title="Test",
            activity_type="laboratorio",
            description="Test description",
            estimated_hours=3.0,
            learning_objectives_addressed=[0, 1],
        )
        assert act.week == 1

    def test_rejects_week_zero(self):
        with pytest.raises(ValidationError):
            LearningActivity(
                week=0,  # invalid — must be >= 1
                title="Test",
                activity_type="laboratorio",
                description="Test",
                estimated_hours=3.0,
            )

    def test_rejects_zero_hours(self):
        with pytest.raises(ValidationError):
            LearningActivity(
                week=1,
                title="Test",
                activity_type="laboratorio",
                description="Test",
                estimated_hours=0.0,  # invalid — must be > 0
            )

    def test_rejects_invalid_activity_type(self):
        with pytest.raises(ValidationError):
            LearningActivity(
                week=1,
                title="Test",
                activity_type="examen",  # not a valid type
                description="Test",
                estimated_hours=2.0,
            )


class TestEvaluator:
    def test_valid_evaluator(self, sample_evaluator):
        total = sum(c.weight_percent for c in sample_evaluator.evaluation_components)
        assert abs(total - 100.0) <= 1.0

    def test_rejects_weights_not_summing_to_100(self):
        with pytest.raises(ValidationError, match="weights must sum to 100"):
            Evaluator(
                evaluation_components=[
                    EvaluationCriteria(component="A", weight_percent=50.0, rubric_items=["c1", "c2", "c3"]),
                    EvaluationCriteria(component="B", weight_percent=30.0, rubric_items=["c1", "c2", "c3"]),
                    # Missing 20% — total is 80
                ],
            )

    def test_allows_weights_within_tolerance(self):
        # Weights summing to 100.5 (within 1.0 tolerance)
        evaluator = Evaluator(
            evaluation_components=[
                EvaluationCriteria(component="A", weight_percent=60.5, rubric_items=["c1", "c2", "c3"]),
                EvaluationCriteria(component="B", weight_percent=40.0, rubric_items=["c1", "c2", "c3"]),
            ],
        )
        assert evaluator is not None


class TestStudyPlan:
    def test_valid_study_plan(self, sample_study_plan):
        assert sample_study_plan.course_code == "TCU-501"
        assert len(sample_study_plan.learning_objectives) == 7

    def test_rejects_activity_referencing_nonexistent_objective(
        self, sample_learning_objectives, sample_activities, sample_evaluator
    ):
        # Create an activity referencing out-of-bounds objective index
        bad_activities = list(sample_activities)
        bad_activities[0] = LearningActivity(
            week=1,
            title="Bad activity",
            activity_type="lectura",
            description="desc",
            estimated_hours=2.0,
            learning_objectives_addressed=[99],  # index 99 doesn't exist
        )
        with pytest.raises(ValidationError):
            StudyPlan(
                course_title="Test Course",
                course_code="TCU-501",
                credits=4,
                hours_per_week=12.0,
                total_weeks=16,
                target_audience="Test audience",
                prerequisites=[],
                learning_objectives=sample_learning_objectives,
                weekly_schedule=bad_activities,
                evaluator=sample_evaluator,
                bibliography=["Ref 1"],
            )

    def test_rejects_credits_below_1(self, sample_study_plan):
        with pytest.raises(ValidationError):
            StudyPlan(
                course_title=sample_study_plan.course_title,
                course_code=sample_study_plan.course_code,
                credits=0,  # invalid
                hours_per_week=sample_study_plan.hours_per_week,
                total_weeks=sample_study_plan.total_weeks,
                target_audience=sample_study_plan.target_audience,
                learning_objectives=sample_study_plan.learning_objectives,
                weekly_schedule=sample_study_plan.weekly_schedule,
                evaluator=sample_study_plan.evaluator,
            )

    def test_partial_study_plan_without_schedule_and_evaluator(self, sample_learning_objectives):
        """StudyPlan can be instantiated without weekly_schedule or evaluator."""
        plan = StudyPlan(
            course_title="Curso Parcial",
            course_code="TCU-001",
            credits=3,
            hours_per_week=9.0,
            total_weeks=16,
            target_audience="Estudiantes de informática.",
            learning_objectives=sample_learning_objectives,
        )
        assert plan.weekly_schedule is None
        assert plan.evaluator is None
