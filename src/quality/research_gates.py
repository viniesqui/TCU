"""
Quality gates for the two research stages (Stages 1 & 2).

These are the most important gates because thin research propagates
as poor quality through every downstream stage.

MarketResearchGate  – validates IndustryDemand from LaborMarketAgent
AcademicResearchGate – validates AcademicLandscape from AcademicAgent
"""

from __future__ import annotations

from src.config import settings
from src.models.academic import AcademicLandscape
from src.models.market import IndustryDemand
from src.quality.base_gate import QualityGate, QualityResult


class MarketResearchGate(QualityGate):
    """
    Validates that labor market research is sufficiently rich.

    Checks:
    - Enough distinct skills identified
    - Enough job postings sampled as evidence
    - Enough sources consulted
    - Summary is substantive (not a stub)
    - At least some technical skills (not just soft skills)
    - Top skill has meaningful demand score
    """

    # Class-level defaults; overridden by settings at runtime
    MIN_SKILLS: int = 8
    MIN_POSTINGS: int = 2
    MIN_SOURCES: int = 2

    @property
    def gate_name(self) -> str:
        return "MarketResearchGate"

    def evaluate(self, data: IndustryDemand) -> QualityResult:
        issues: list[str] = []
        score_components: list[float] = []

        try:
            min_skills = settings.quality_min_skills
            min_postings = settings.quality_min_job_postings
            min_sources = settings.quality_min_sources
        except Exception:
            min_skills, min_postings, min_sources = self.MIN_SKILLS, self.MIN_POSTINGS, self.MIN_SOURCES

        # --- Check: skill count ---
        skill_count = len(data.top_skills)
        if skill_count < min_skills:
            issues.append(
                f"Solo se identificaron {skill_count} habilidades (mínimo requerido: {min_skills})."
            )
        score_components.append(min(skill_count / min_skills, 1.0))

        # --- Check: job postings as evidence ---
        posting_count = len(data.job_postings_sampled)
        if posting_count < min_postings:
            issues.append(
                f"Solo se muestrearon {posting_count} ofertas de trabajo (mínimo: {min_postings}). "
                f"Necesitas visitar páginas de ofertas reales."
            )
        score_components.append(min(posting_count / min_postings, 1.0))

        # --- Check: sources ---
        source_count = len(data.market_sources)
        if source_count < min_sources:
            issues.append(
                f"Solo se consultaron {source_count} fuentes (mínimo: {min_sources}). "
                f"Consulta LinkedIn, Computrabajo, CAMTIC, CINDE."
            )
        score_components.append(min(source_count / min_sources, 1.0))

        # --- Check: summary substance ---
        summary_len = len(data.summary or "")
        if summary_len < 80:
            issues.append(
                f"El resumen es muy breve ({summary_len} caracteres). "
                f"Debe ser un párrafo informativo de al menos 80 caracteres."
            )
        score_components.append(min(summary_len / 200, 1.0))

        # --- Check: technical skills present ---
        technical_skills = [s for s in data.top_skills if s.category == "technical"]
        if len(technical_skills) < 3:
            issues.append(
                f"Solo {len(technical_skills)} habilidades técnicas identificadas. "
                f"El análisis necesita más habilidades técnicas específicas del sector."
            )
        score_components.append(min(len(technical_skills) / 5, 1.0))

        # --- Check: demand score makes sense ---
        if data.top_skills:
            top_score = data.top_skills[0].frequency_score
            if top_score < 0.3:
                issues.append(
                    f"El score de demanda de la habilidad principal es muy bajo ({top_score:.2f}). "
                    f"Los scores deben reflejar la frecuencia real en las ofertas encontradas."
                )
            score_components.append(min(top_score / 0.7, 1.0))

        # --- Determine if broadening is needed ---
        suggest_broadening = skill_count < max(3, min_skills // 2) or posting_count == 0

        overall_score = sum(score_components) / len(score_components) if score_components else 0.0
        return self._result(issues, overall_score, suggest_broadening=suggest_broadening)

    def _build_retry_instructions(self, issues: list[str]) -> str:
        lines = [
            "INSTRUCCIONES DE MEJORA (intento anterior no cumplió estándares de calidad):",
            "",
        ]
        lines += [f"- {issue}" for issue in issues]
        lines += [
            "",
            "ACCIONES REQUERIDAS PARA ESTE INTENTO:",
            "- Realiza AL MENOS 3 búsquedas adicionales con términos diferentes.",
            "- Visita y lee el contenido de al menos 2 páginas de ofertas de empleo reales.",
            "- Consulta explícitamente: LinkedIn Costa Rica, Computrabajo Costa Rica, CAMTIC, CINDE.",
            "- Asegúrate de que cada habilidad técnica aparezca en múltiples fuentes antes de incluirla.",
            "- Asigna frequency_score basándote en cuántas veces aparece la habilidad (no estimes).",
        ]
        return "\n".join(lines)


class AcademicResearchGate(QualityGate):
    """
    Validates that academic landscape research is sufficiently rich.

    Checks:
    - Enough universities sampled (public + private mix)
    - Enough courses per curriculum
    - Skills list is non-trivial
    - Both public and private universities represented
    - Summary is substantive
    """

    MIN_UNIVERSITIES: int = 3
    MIN_COURSES_PER_PROGRAM: int = 3
    MIN_SKILLS_COVERED: int = 10

    @property
    def gate_name(self) -> str:
        return "AcademicResearchGate"

    def evaluate(self, data: AcademicLandscape) -> QualityResult:
        issues: list[str] = []
        score_components: list[float] = []

        try:
            min_universities = settings.quality_min_universities
            min_courses_per_program = settings.quality_min_courses_per_program
            min_skills_covered = settings.quality_min_skills_covered
        except Exception:
            min_universities = self.MIN_UNIVERSITIES
            min_courses_per_program = self.MIN_COURSES_PER_PROGRAM
            min_skills_covered = self.MIN_SKILLS_COVERED

        # --- Check: university count ---
        uni_count = len(data.curricula_sampled)
        if uni_count < min_universities:
            issues.append(
                f"Solo se encontraron {uni_count} programas universitarios (mínimo: {min_universities}). "
                f"Busca en UCR, TEC, UNA, ULACIT, Latina y otras universidades costarricenses."
            )
        score_components.append(min(uni_count / min_universities, 1.0))

        # --- Check: public/private mix ---
        has_public = any(c.is_public for c in data.curricula_sampled)
        has_private = any(not c.is_public for c in data.curricula_sampled)
        if data.curricula_sampled:
            if not has_public:
                issues.append(
                    "No se encontraron programas de universidades públicas. "
                    "Incluye UCR, TEC, UNA, UNED o UTN."
                )
            if not has_private:
                issues.append(
                    "No se encontraron programas de universidades privadas. "
                    "Incluye ULACIT, Latina, Fidélitas, Veritas o CENFOTEC."
                )
        mix_score = (1.0 if has_public else 0.0) * 0.5 + (1.0 if has_private else 0.0) * 0.5
        score_components.append(mix_score)

        # --- Check: courses per curriculum ---
        thin_programs = [
            c for c in data.curricula_sampled
            if len(c.courses) < min_courses_per_program
        ]
        if thin_programs:
            names = ", ".join(c.university for c in thin_programs[:3])
            issues.append(
                f"{len(thin_programs)} programa(s) tienen menos de {min_courses_per_program} cursos "
                f"({names}). Visita los catálogos de cursos completos."
            )
        avg_courses = (
            sum(len(c.courses) for c in data.curricula_sampled) / uni_count
            if uni_count > 0 else 0
        )
        score_components.append(min(avg_courses / (min_courses_per_program * 2), 1.0))

        # --- Check: skills coverage breadth ---
        skill_count = len(data.all_skills_covered)
        if skill_count < min_skills_covered:
            issues.append(
                f"Solo {skill_count} habilidades cubiertas identificadas (mínimo: {min_skills_covered}). "
                f"Extrae habilidades de las descripciones de cada curso."
            )
        score_components.append(min(skill_count / min_skills_covered, 1.0))

        # --- Check: summary substance ---
        summary_len = len(data.summary or "")
        if summary_len < 80:
            issues.append("El resumen de la oferta académica es muy breve o inexistente.")
        score_components.append(min(summary_len / 200, 1.0))

        suggest_broadening = uni_count < max(2, min_universities // 2)

        overall_score = sum(score_components) / len(score_components) if score_components else 0.0
        return self._result(issues, overall_score, suggest_broadening=suggest_broadening)

    def _build_retry_instructions(self, issues: list[str]) -> str:
        lines = [
            "INSTRUCCIONES DE MEJORA (investigación académica insuficiente):",
            "",
        ]
        lines += [f"- {issue}" for issue in issues]
        lines += [
            "",
            "ACCIONES REQUERIDAS PARA ESTE INTENTO:",
            "- Busca explícitamente: 'plan de estudios [carrera] UCR', 'cursos informática TEC'.",
            "- Visita los sitios web oficiales de al menos 4 universidades diferentes.",
            "- Incluye tanto universidades públicas (UCR, TEC, UNA) como privadas (ULACIT, Latina).",
            "- Para cada programa, lista TODOS los cursos relevantes que puedas encontrar.",
            "- Extrae habilidades concretas de las descripciones de los cursos (no generalidades).",
        ]
        return "\n".join(lines)
