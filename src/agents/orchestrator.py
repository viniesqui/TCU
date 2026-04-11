import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from src.agents.academic_agent import AcademicAgent
from src.agents.activities_agent import ActivitiesAgent
from src.agents.base_agent import BaseAgent
from src.agents.curriculum_agent import CurriculumAgent
from src.agents.evaluator_agent import EvaluatorAgent
from src.agents.gap_analyst_agent import GapAnalystAgent
from src.agents.labor_market_agent import LaborMarketAgent
from src.config import settings
from src.models.academic import AcademicLandscape
from src.models.course_design import Evaluator, LearningActivity, StudyPlan
from src.models.gap import GapAnalysis
from src.models.market import IndustryDemand

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorResult:
    """All structured outputs produced by the orchestration pipeline."""
    sector: str
    industry_demand: IndustryDemand
    academic_landscape: AcademicLandscape
    gap_analysis: GapAnalysis
    study_plan: StudyPlan
    report_path: str = ""
    stage_outputs: dict[str, str] = field(default_factory=dict)


class Orchestrator:
    """
    Python state machine that sequences the six specialist agents and
    validates their Pydantic outputs at each stage boundary.

    Pipeline:
        Stage 1: LaborMarketAgent    → IndustryDemand
        Stage 2: AcademicAgent       → AcademicLandscape
        Stage 3: GapAnalystAgent     → GapAnalysis
        Stage 4: CurriculumAgent     → partial StudyPlan
        Stage 5: ActivitiesAgent     → weekly_schedule
        Stage 6: EvaluatorAgent      → Evaluator
        Stage 7: ReportGenerator     → HTML file
    """

    def __init__(self, progress: Any = None) -> None:
        self.progress = progress  # Rich Progress object (optional)
        self.max_stage_retries = settings.max_stage_retries

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, sector: str = "Software Development") -> str:
        """
        Execute the full pipeline for the given sector.
        Returns the path to the generated HTML report.
        """
        logger.info(f"[Orchestrator] Starting pipeline for sector: '{sector}'")
        result = self._run_pipeline(sector)

        # Generate report
        from src.report_generator import ReportGenerator
        report_path = ReportGenerator().render(
            industry_demand=result.industry_demand,
            academic_landscape=result.academic_landscape,
            gap_analysis=result.gap_analysis,
            study_plan=result.study_plan,
        )
        logger.info(f"[Orchestrator] Report generated: {report_path}")
        return str(report_path)

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------

    def _run_pipeline(self, sector: str) -> OrchestratorResult:
        stage_outputs: dict[str, str] = {}

        # --- Stage 1: Labor Market Research ---
        self._update_progress("Investigando mercado laboral...")
        industry_demand = self._run_stage(
            stage_name="Stage 1 – Labor Market Research",
            agent=LaborMarketAgent(),
            user_message_fn=lambda: LaborMarketAgent().research(sector),
            output_model=IndustryDemand,
            raw_call=True,
            sector=sector,
        )
        stage_outputs["industry_demand"] = industry_demand.model_dump_json(indent=2)
        logger.info(f"[Orchestrator] Stage 1 complete. Top skills: {[s.name for s in industry_demand.top_skills[:5]]}")

        # --- Stage 2: Academic Landscape Research ---
        self._update_progress("Investigando oferta académica universitaria...")
        academic_landscape = self._run_stage(
            stage_name="Stage 2 – Academic Research",
            agent=AcademicAgent(),
            user_message_fn=lambda: AcademicAgent().research(sector),
            output_model=AcademicLandscape,
            raw_call=True,
            sector=sector,
        )
        stage_outputs["academic_landscape"] = academic_landscape.model_dump_json(indent=2)
        logger.info(f"[Orchestrator] Stage 2 complete. Universities sampled: {len(academic_landscape.curricula_sampled)}")

        # --- Stage 3: Gap Analysis ---
        self._update_progress("Analizando brecha educativa...")
        gap_analysis = self._run_stage(
            stage_name="Stage 3 – Gap Analysis",
            agent=GapAnalystAgent(),
            user_message_fn=lambda: GapAnalystAgent().analyze(
                stage_outputs["industry_demand"],
                stage_outputs["academic_landscape"],
            ),
            output_model=GapAnalysis,
            raw_call=True,
        )
        stage_outputs["gap_analysis"] = gap_analysis.model_dump_json(indent=2)
        logger.info(f"[Orchestrator] Stage 3 complete. Critical gaps: {len(gap_analysis.critical_gaps)}")
        logger.info(f"[Orchestrator] Proposed course: '{gap_analysis.proposed_course_title}'")

        # --- Stage 4: Curriculum Design ---
        self._update_progress("Diseñando plan de estudios...")
        partial_plan_data = self._run_stage(
            stage_name="Stage 4 – Curriculum Design",
            agent=CurriculumAgent(),
            user_message_fn=lambda: CurriculumAgent().design(stage_outputs["gap_analysis"]),
            output_model=_PartialStudyPlan,
            raw_call=True,
        )
        stage_outputs["partial_plan"] = partial_plan_data.model_dump_json(indent=2)
        logger.info(f"[Orchestrator] Stage 4 complete. Course: '{partial_plan_data.course_title}', {partial_plan_data.total_weeks} weeks")

        # --- Stage 5: Learning Activities ---
        self._update_progress("Diseñando actividades de aprendizaje...")
        activities_data = self._run_stage(
            stage_name="Stage 5 – Learning Activities",
            agent=ActivitiesAgent(),
            user_message_fn=lambda: ActivitiesAgent().design(stage_outputs["partial_plan"]),
            output_model=_ActivitiesWrapper,
            raw_call=True,
        )
        stage_outputs["activities"] = activities_data.model_dump_json(indent=2)
        logger.info(f"[Orchestrator] Stage 5 complete. Activities: {len(activities_data.weekly_schedule)}")

        # Merge activities into the partial plan for evaluator context
        full_plan_dict = partial_plan_data.model_dump()
        full_plan_dict["weekly_schedule"] = [a.model_dump() for a in activities_data.weekly_schedule]
        full_plan_dict["evaluator"] = None  # Placeholder, filled in stage 6
        import json
        stage_outputs["full_plan_no_eval"] = json.dumps(full_plan_dict, ensure_ascii=False, indent=2)

        # --- Stage 6: Evaluator / Assessment ---
        self._update_progress("Diseñando sistema de evaluación...")
        evaluator_data = self._run_stage(
            stage_name="Stage 6 – Evaluator Design",
            agent=EvaluatorAgent(),
            user_message_fn=lambda: EvaluatorAgent().design(stage_outputs["full_plan_no_eval"]),
            output_model=Evaluator,
            raw_call=True,
        )
        logger.info(f"[Orchestrator] Stage 6 complete. Evaluation components: {len(evaluator_data.evaluation_components)}")

        # Assemble the final StudyPlan
        full_plan_dict["evaluator"] = evaluator_data.model_dump()
        study_plan = StudyPlan.model_validate(full_plan_dict)

        return OrchestratorResult(
            sector=sector,
            industry_demand=industry_demand,
            academic_landscape=academic_landscape,
            gap_analysis=gap_analysis,
            study_plan=study_plan,
            stage_outputs=stage_outputs,
        )

    # ------------------------------------------------------------------
    # Stage runner with Pydantic validation + retry
    # ------------------------------------------------------------------

    def _run_stage(
        self,
        stage_name: str,
        agent: BaseAgent,
        user_message_fn,
        output_model,
        raw_call: bool = False,
        **kwargs,
    ):
        """
        Run an agent stage, validate output with Pydantic, retry on failure.
        raw_call=True means user_message_fn() already runs the agent (returns raw JSON string).
        """
        last_error: Exception | None = None

        for attempt in range(1, self.max_stage_retries + 2):
            logger.info(f"[Orchestrator] {stage_name} – attempt {attempt}")
            try:
                raw_json = user_message_fn()
                clean = BaseAgent.clean_json(raw_json)
                result = output_model.model_validate_json(clean)
                return result
            except (ValidationError, ValueError, Exception) as e:
                last_error = e
                logger.warning(f"[Orchestrator] {stage_name} attempt {attempt} failed: {e}")
                if attempt > self.max_stage_retries:
                    break
                # On retry, re-instantiate the agent with validation error feedback
                logger.info(f"[Orchestrator] Retrying {stage_name}...")

        raise RuntimeError(
            f"Stage '{stage_name}' failed after {self.max_stage_retries + 1} attempts. "
            f"Last error: {last_error}"
        )

    def _update_progress(self, description: str) -> None:
        if self.progress is not None:
            try:
                self.progress.log(f"[cyan]{description}[/cyan]")
            except Exception:
                pass
        logger.info(f"[Orchestrator] {description}")


# ---------------------------------------------------------------------------
# Internal helper models for partial pipeline outputs
# ---------------------------------------------------------------------------

from pydantic import BaseModel  # noqa: E402


class _PartialStudyPlan(BaseModel):
    """Partial StudyPlan without weekly_schedule and evaluator (filled in later stages)."""
    course_title: str
    course_code: str
    credits: int
    hours_per_week: float
    total_weeks: int
    target_audience: str
    prerequisites: list[str] = []
    learning_objectives: list[dict] = []
    bibliography: list[str] = []


class _ActivitiesWrapper(BaseModel):
    """Wrapper for activities agent output."""
    weekly_schedule: list[LearningActivity]
