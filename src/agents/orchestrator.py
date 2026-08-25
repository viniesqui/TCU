"""
TCU Orchestrator – simplified pipeline with quality gates
=========================================================
Python state machine that sequences the specialist agents.
Between every stage, a quality gate validates the output and — if the result
is insufficient — re-runs the agent with targeted Spanish-language instructions
explaining exactly what to improve.

Pipeline:
    Stage 1: LaborMarketAgent    → IndustryDemand      → MarketResearchGate
    Stage 2: AcademicAgent       → AcademicLandscape   → AcademicResearchGate
    Stage 3: GapAnalystAgent     → GapAnalysis         → GapAnalysisGate
    Stage 4: CourseDesignerAgent → StudyPlan (partial) → CurriculumGate + ActivitiesGate
    Stage 5: EvaluatorAgent      → Evaluator           → EvaluatorGate
    Stage 6: ReportGenerator     → HTML file
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ReviewHook = Callable[["GapAnalysis"], tuple["GapAnalysis", dict | None]]

from pydantic import ValidationError

from src.agents.academic_agent import AcademicAgent
from src.agents.base_agent import BaseAgent
from src.agents.course_designer_agent import CourseDesignerAgent
from src.agents.evaluator_agent import EvaluatorAgent
from src.agents.gap_analyst_agent import GapAnalystAgent
from src.agents.labor_market_agent import LaborMarketAgent
from src.config import settings
from src.models.academic import AcademicLandscape
from src.models.course_design import Evaluator, StudyPlan
from src.models.gap import GapAnalysis
from src.models.market import IndustryDemand
from src.quality.downstream_gates import ActivitiesGate, CurriculumGate, EvaluatorGate, GapAnalysisGate
from src.quality.research_gates import AcademicResearchGate, MarketResearchGate

logger = logging.getLogger(__name__)

_STAGE_CACHE_DIR = Path("stage_cache")


@dataclass
class OrchestratorResult:
    """All structured outputs produced by the orchestration pipeline."""
    sector: str
    industry_demand: IndustryDemand
    academic_landscape: AcademicLandscape
    gap_analysis: GapAnalysis
    study_plan: StudyPlan
    report_path: str = ""
    quality_scores: dict[str, float] = field(default_factory=dict)


class Orchestrator:
    """
    State machine orchestrator with quality gates between every stage.

    Quality gate behavior:
    - Gate passes  → proceed to next stage
    - Gate fails   → retry the agent with targeted retry_instructions
    - Max retries  → log warning and proceed with best available output
                     (the pipeline never hard-fails due to quality alone)

    Stage checkpointing: each stage result is persisted to
    stage_cache/{sector}_{stage}.json and reloaded on subsequent runs,
    allowing mid-pipeline crash recovery and fast iteration during development.
    """

    def __init__(self, progress: Any = None, review_hook: ReviewHook | None = None) -> None:
        self.progress = progress
        self.review_hook = review_hook
        self.max_retries: int = settings.max_stage_retries
        self._quality_scores: dict[str, float] = {}
        self._review_record: dict | None = None
        self._sector: str = ""
        _STAGE_CACHE_DIR.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run_research(
        self,
        sector: str,
        custom_academic_landscape: AcademicLandscape | None = None
    ) -> tuple[IndustryDemand, AcademicLandscape, GapAnalysis]:
        """Execute Stage 1-3. Returns (demand, academic, gap)."""
        BaseAgent.reset_cost()
        self._sector = sector
        industry_demand = self._stage_market_research(sector)
        if custom_academic_landscape is not None:
            academic_landscape = custom_academic_landscape
            self._save_stage_cache("academic_research", academic_landscape)
        else:
            academic_landscape = self._stage_academic_research(sector)
        gap_analysis = self._stage_gap_analysis(industry_demand, academic_landscape)
        return industry_demand, academic_landscape, gap_analysis

    def run_course_design(self, gap_analysis: GapAnalysis) -> StudyPlan:
        """Execute Stage 4 (Course Design). Returns StudyPlan."""
        BaseAgent.reset_cost()
        if not self._sector and gap_analysis.sector:
            self._sector = gap_analysis.sector
        return self._stage_course_design(gap_analysis)

    def run_evaluator(self, study_plan: StudyPlan) -> Evaluator:
        """Execute Stage 5 (Evaluator). Returns Evaluator."""
        BaseAgent.reset_cost()
        if not self._sector and study_plan.course_title:
            self._sector = study_plan.course_title
        return self._stage_evaluator(study_plan)

    def run(self, sector: str = "Desarrollo de Software") -> str:
        """Execute the full pipeline. Returns path to generated HTML report."""
        BaseAgent.reset_cost()
        self._sector = sector
        logger.info(f"[Orchestrator] ── Pipeline start ── sector='{sector}'")

        # Stage 1 – Labor Market Research
        self._progress("🔎 Investigando mercado laboral en Costa Rica...")
        industry_demand = self._stage_market_research(sector)

        # Stage 2 – Academic Research
        self._progress("🎓 Investigando oferta académica universitaria...")
        academic_landscape = self._stage_academic_research(sector)

        # Stage 3 – Gap Analysis
        self._progress("📊 Analizando brecha educativa...")
        gap_analysis = self._stage_gap_analysis(industry_demand, academic_landscape)

        # Checkpoint – optional human review before committing to a curriculum.
        # The hook may mutate gap_analysis (drop/add skills, edit title) and
        # returns an audit record that flows into the final report.
        if self.review_hook is not None:
            logger.info("[Orchestrator] Invoking review hook for gap analysis")
            gap_analysis, self._review_record = self.review_hook(gap_analysis)

        # Stage 4 – Course Design (curriculum + activities in one call)
        self._progress("📝 Diseñando plan de estudios y cronograma de actividades...")
        study_plan = self._stage_course_design(gap_analysis)

        # Stage 5 – Evaluator
        self._progress("✅ Diseñando sistema de evaluación...")
        evaluator = self._stage_evaluator(study_plan)
        study_plan.evaluator = evaluator

        # Stage 6 – Report
        self._progress("📄 Generando reporte HTML...")
        from src.report_generator import ReportGenerator
        report_path = ReportGenerator().render(
            industry_demand=industry_demand,
            academic_landscape=academic_landscape,
            gap_analysis=gap_analysis,
            study_plan=study_plan,
            quality_scores=self._quality_scores,
            review_record=self._review_record,
        )

        logger.info(f"[Orchestrator] ── Pipeline complete ── report={report_path}")
        return str(report_path)

    # ------------------------------------------------------------------
    # Stage 1: Labor Market Research
    # ------------------------------------------------------------------

    def _stage_market_research(self, sector: str) -> IndustryDemand:
        cached = self._load_stage_cache("market_research", IndustryDemand)
        if cached is not None:
            return cached

        gate = MarketResearchGate()
        agent = LaborMarketAgent(max_cost=settings.max_cost_researcher)
        retry_context: str | None = None

        for attempt in range(1, self.max_retries + 2):
            logger.info(f"[Stage 1] Attempt {attempt}/{self.max_retries + 1}")
            try:
                raw = agent.research(sector, retry_context=retry_context)
                result = IndustryDemand.model_validate_json(BaseAgent.clean_json(raw))
            except (ValidationError, ValueError, json.JSONDecodeError) as e:
                logger.warning(f"[Stage 1] Parse/validation error: {e}")
                retry_context = (
                    f"Tu respuesta anterior no fue JSON válido. Error: {e}. "
                    f"Responde ÚNICAMENTE con el objeto JSON, sin markdown ni texto adicional."
                )
                if attempt > self.max_retries:
                    raise RuntimeError(f"Stage 1 failed to produce valid JSON after {attempt} attempts") from e
                continue

            gate_result = gate.evaluate(result)
            self._quality_scores["market_research"] = gate_result.score
            self._log_gate(gate_result)

            if gate_result.passed:
                self._save_stage_cache("market_research", result)
                return result

            if attempt > self.max_retries:
                logger.warning(f"[Stage 1] Quality gate failed after all retries. Proceeding with best result.")
                self._save_stage_cache("market_research", result)
                return result

            retry_context = gate_result.retry_instructions

        return result  # unreachable but satisfies type checker

    # ------------------------------------------------------------------
    # Stage 2: Academic Research
    # ------------------------------------------------------------------

    def _stage_academic_research(self, sector: str) -> AcademicLandscape:
        cached = self._load_stage_cache("academic_research", AcademicLandscape)
        if cached is not None:
            return cached

        gate = AcademicResearchGate()
        agent = AcademicAgent(max_cost=settings.max_cost_researcher)
        retry_context: str | None = None
        broaden = False

        for attempt in range(1, self.max_retries + 2):
            logger.info(f"[Stage 2] Attempt {attempt}/{self.max_retries + 1} broaden={broaden}")
            try:
                raw = agent.research(sector, retry_context=retry_context, broaden_to_region=broaden)
                result = AcademicLandscape.model_validate_json(BaseAgent.clean_json(raw))
            except (ValidationError, ValueError, json.JSONDecodeError) as e:
                logger.warning(f"[Stage 2] Parse/validation error: {e}")
                retry_context = (
                    f"Tu respuesta anterior no fue JSON válido. Error: {e}. "
                    f"Responde ÚNICAMENTE con el objeto JSON, sin markdown ni texto adicional."
                )
                if attempt > self.max_retries:
                    raise RuntimeError(f"Stage 2 failed to produce valid JSON after {attempt} attempts") from e
                continue

            gate_result = gate.evaluate(result)
            self._quality_scores["academic_research"] = gate_result.score
            self._log_gate(gate_result)

            if gate_result.passed:
                self._save_stage_cache("academic_research", result)
                return result

            if attempt > self.max_retries:
                logger.warning(f"[Stage 2] Quality gate failed after all retries. Proceeding with best result.")
                self._save_stage_cache("academic_research", result)
                return result

            # On first failure: try geographic broadening if suggested.
            # Use broadening-specific instructions instead of the gate's CR-focused ones
            # to avoid sending contradictory guidance (search CA + focus on UCR/TEC).
            if gate_result.suggest_broadening and not broaden:
                logger.info("[Stage 2] Broadening search scope to Central America")
                broaden = True
                retry_context = (
                    "La búsqueda en Costa Rica no encontró suficientes programas. "
                    "Amplía la búsqueda a toda Centroamérica: incluye USAC (Guatemala), "
                    "UES (El Salvador), UNAH (Honduras), UNAN (Nicaragua), UP (Panamá) "
                    "además de las universidades costarricenses ya encontradas."
                )
            else:
                retry_context = gate_result.retry_instructions

        return result

    # ------------------------------------------------------------------
    # Stage 3: Gap Analysis
    # ------------------------------------------------------------------

    def _stage_gap_analysis(
        self, industry_demand: IndustryDemand, academic_landscape: AcademicLandscape
    ) -> GapAnalysis:
        cached = self._load_stage_cache("gap_analysis", GapAnalysis)
        if cached is not None:
            return cached

        gate = GapAnalysisGate()
        agent = GapAnalystAgent(max_cost=settings.max_cost_coordinator)
        demand_json = industry_demand.model_dump_json(indent=2)
        academic_json = academic_landscape.model_dump_json(indent=2)
        retry_context: str | None = None

        for attempt in range(1, self.max_retries + 2):
            logger.info(f"[Stage 3] Attempt {attempt}/{self.max_retries + 1}")
            try:
                raw = agent.analyze(demand_json, academic_json, retry_context=retry_context)
                result = GapAnalysis.model_validate_json(BaseAgent.clean_json(raw))
            except (ValidationError, ValueError, json.JSONDecodeError) as e:
                logger.warning(f"[Stage 3] Parse/validation error: {e}")
                retry_context = f"JSON inválido. Error: {e}. Responde solo con JSON."
                if attempt > self.max_retries:
                    raise RuntimeError(f"Stage 3 failed after {attempt} attempts") from e
                continue

            gate_result = gate.evaluate(result)
            self._quality_scores["gap_analysis"] = gate_result.score
            self._log_gate(gate_result)

            if gate_result.passed:
                self._save_stage_cache("gap_analysis", result)
                return result

            if attempt > self.max_retries:
                logger.warning("[Stage 3] Proceeding with best result after gate failures.")
                self._save_stage_cache("gap_analysis", result)
                return result

            retry_context = gate_result.retry_instructions

        return result

    # ------------------------------------------------------------------
    # Stage 4: Course Design (curriculum + activities)
    # ------------------------------------------------------------------

    def _stage_course_design(self, gap_analysis: GapAnalysis) -> StudyPlan:
        cached = self._load_stage_cache("course_design", StudyPlan)
        if cached is not None:
            return cached

        curriculum_gate = CurriculumGate()
        activities_gate = ActivitiesGate()
        agent = CourseDesignerAgent(max_cost=settings.max_cost_coordinator)
        gap_json = gap_analysis.model_dump_json(indent=2)
        retry_context: str | None = None

        for attempt in range(1, self.max_retries + 2):
            logger.info(f"[Stage 4] Attempt {attempt}/{self.max_retries + 1}")
            try:
                ref_mat = getattr(self, "_reference_material", None)
                raw = agent.design(gap_json, retry_context=retry_context, reference_material=ref_mat)
                result = StudyPlan.model_validate_json(BaseAgent.clean_json(raw))
            except (ValidationError, ValueError, json.JSONDecodeError) as e:
                logger.warning(f"[Stage 4] Parse/validation error: {e}")
                retry_context = f"JSON inválido o índices de objetivos fuera de rango. Error: {e}. Responde solo con JSON."
                if attempt > self.max_retries:
                    raise RuntimeError(f"Stage 4 failed after {attempt} attempts") from e
                continue

            curriculum_result = curriculum_gate.evaluate(result)
            activities_result = activities_gate.evaluate(
                activities=result.weekly_schedule or [],
                total_weeks=result.total_weeks,
                num_objectives=len(result.learning_objectives),
            )
            self._quality_scores["curriculum"] = curriculum_result.score
            self._quality_scores["activities"] = activities_result.score
            self._log_gate(curriculum_result)
            self._log_gate(activities_result)

            if curriculum_result.passed and activities_result.passed:
                self._save_stage_cache("course_design", result)
                return result

            if attempt > self.max_retries:
                logger.warning("[Stage 4] Quality gate(s) failed after all retries. Proceeding with best result.")
                self._save_stage_cache("course_design", result)
                return result

            parts = [
                curriculum_result.retry_instructions if not curriculum_result.passed else "",
                activities_result.retry_instructions if not activities_result.passed else "",
            ]
            retry_context = "\n\n".join(p for p in parts if p)

        return result  # unreachable but satisfies type checker

    # ------------------------------------------------------------------
    # Stage 5: Evaluator
    # ------------------------------------------------------------------

    def _stage_evaluator(self, study_plan: StudyPlan) -> Evaluator:
        cached = self._load_stage_cache("evaluator", Evaluator)
        if cached is not None:
            return cached

        gate = EvaluatorGate()
        agent = EvaluatorAgent(max_cost=settings.max_cost_coordinator)
        full_json = study_plan.model_dump_json(indent=2, exclude={"evaluator"})
        retry_context: str | None = None

        for attempt in range(1, self.max_retries + 2):
            logger.info(f"[Stage 5] Attempt {attempt}/{self.max_retries + 1}")
            try:
                raw = agent.design(full_json, retry_context=retry_context)
                result = Evaluator.model_validate_json(BaseAgent.clean_json(raw))
            except ValidationError as e:
                logger.warning(f"[Stage 5] Validation error (weights?): {e}")
                retry_context = (
                    f"Error de validación Pydantic: {e}. "
                    f"CRÍTICO: los weight_percent de todos los componentes DEBEN sumar exactamente 100."
                )
                if attempt > self.max_retries:
                    raise RuntimeError(f"Stage 5 failed after {attempt} attempts") from e
                continue
            except Exception as e:
                logger.warning(f"[Stage 5] Error: {e}")
                retry_context = f"Tu respuesta anterior no fue JSON válido. Error: {e}. Responde solo con JSON."
                if attempt > self.max_retries:
                    raise RuntimeError(f"Stage 5 failed after {attempt} attempts") from e
                continue

            gate_result = gate.evaluate(result)
            self._quality_scores["evaluator"] = gate_result.score
            self._log_gate(gate_result)

            if gate_result.passed:
                self._save_stage_cache("evaluator", result)
                return result

            if attempt > self.max_retries:
                logger.warning("[Stage 5] Quality gate failed after all retries. Proceeding with best result.")
                self._save_stage_cache("evaluator", result)
                return result

            retry_context = gate_result.retry_instructions

        raise RuntimeError("Stage 5: unreachable")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _cache_path(self, stage: str) -> Path:
        """Return the cache file path for a given stage and current sector."""
        key = re.sub(r"[^\w]", "_", self._sector).lower()
        return _STAGE_CACHE_DIR / f"{key}_{stage}.json"

    def _load_stage_cache(self, stage: str, model_class: Any) -> Any | None:
        """Return a deserialized model from disk cache if the file exists, else None."""
        path = self._cache_path(stage)
        if not path.exists():
            return None
        try:
            data = path.read_text(encoding="utf-8")
            result = model_class.model_validate_json(data)
            logger.info(f"[Orchestrator] Cache hit – stage='{stage}' file={path}")
            return result
        except Exception as e:
            logger.warning(f"[Orchestrator] Cache read failed for stage='{stage}': {e}. Re-running stage.")
            return None

    def _save_stage_cache(self, stage: str, model: Any) -> None:
        """Persist a Pydantic model's JSON representation to the stage cache."""
        path = self._cache_path(stage)
        try:
            path.write_text(model.model_dump_json(indent=2), encoding="utf-8")
            logger.info(f"[Orchestrator] Stage '{stage}' cached → {path}")
        except Exception as e:
            logger.warning(f"[Orchestrator] Cache write failed for stage='{stage}': {e}")

    def _log_gate(self, result) -> None:
        status = "PASSED ✓" if result.passed else "FAILED ✗"
        logger.info(
            f"[QualityGate] {result.gate_name}: {status} "
            f"score={result.score:.2f} issues={len(result.issues)}"
        )
        for issue in result.issues:
            logger.warning(f"  ↳ {issue}")

    def _progress(self, description: str) -> None:
        if self.progress is not None:
            try:
                self.progress.log(f"[cyan]{description}[/cyan]")
            except Exception:
                pass
        logger.info(f"[Orchestrator] {description}")
