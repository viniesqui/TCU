import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.config import settings
from src.models.academic import AcademicLandscape
from src.models.course_design import StudyPlan
from src.models.gap import GapAnalysis
from src.models.market import IndustryDemand

logger = logging.getLogger(__name__)

# Keywords used to assign skills to display categories
_LANGUAGE_KEYWORDS = {
    "python", "java", "javascript", "typescript", "go", "golang", "rust", "c++",
    "c#", "php", "ruby", "kotlin", "swift", "scala", "r ", " r,", "matlab",
    "perl", "bash", "shell", "powershell", "html", "css",
}
_TOOL_KEYWORDS = {
    "docker", "kubernetes", "k8s", "git", "jenkins", "terraform", "ansible",
    "aws", "azure", "gcp", "linux", "nginx", "apache", "maven", "gradle",
    "jira", "confluence", "postman", "swagger", "graphql", "rest", "api",
}
_DB_KEYWORDS = {
    "sql", "mysql", "postgresql", "postgres", "mongodb", "mongo", "redis",
    "elasticsearch", "oracle", "nosql", "sqlite", "mariadb", "cassandra",
    "base de datos", "database", "firestore", "dynamodb",
}
_SOFT_KEYWORDS = {
    "comunicación", "liderazgo", "trabajo en equipo", "teamwork", "resolución",
    "pensamiento crítico", "creatividad", "adaptabilidad", "scrum", "agile",
    "kanban", "gestión", "presentación", "negociación",
}


def _categorize_skill(skill: str) -> str:
    """Assign a display category to a skill string based on keyword matching."""
    s = skill.lower()
    if any(kw in s for kw in _LANGUAGE_KEYWORDS):
        return "Lenguajes de Programación"
    if any(kw in s for kw in _DB_KEYWORDS):
        return "Bases de Datos"
    if any(kw in s for kw in _TOOL_KEYWORDS):
        return "Herramientas y Plataformas"
    if any(kw in s for kw in _SOFT_KEYWORDS):
        return "Habilidades Blandas"
    return "Conceptos y Metodologías"


def _group_skills_by_category(skills: list[str]) -> dict[str, list[str]]:
    """Group a flat skill list into display categories, sorted alphabetically within each."""
    groups: dict[str, list[str]] = defaultdict(list)
    for skill in skills:
        groups[_categorize_skill(skill)].append(skill)
    # Sort skills within each category, and order categories logically
    category_order = [
        "Lenguajes de Programación",
        "Herramientas y Plataformas",
        "Bases de Datos",
        "Conceptos y Metodologías",
        "Habilidades Blandas",
    ]
    result = {}
    for cat in category_order:
        if cat in groups:
            result[cat] = sorted(groups[cat])
    # Add any unexpected categories at the end
    for cat, skills_list in groups.items():
        if cat not in result:
            result[cat] = sorted(skills_list)
    return result


class ReportGenerator:
    """Renders pipeline outputs into a styled HTML report using Jinja2."""

    TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
    TEMPLATE_NAME = "report.html.jinja2"

    def render(
        self,
        industry_demand: IndustryDemand,
        academic_landscape: AcademicLandscape,
        gap_analysis: GapAnalysis,
        study_plan: StudyPlan,
        quality_scores: dict[str, float] | None = None,
    ) -> Path:
        """
        Render all pipeline outputs into an HTML report.
        Returns the Path to the generated file.
        """
        env = Environment(
            loader=FileSystemLoader(str(self.TEMPLATE_DIR)),
            autoescape=True,
        )
        template = env.get_template(self.TEMPLATE_NAME)

        skills_by_category = _group_skills_by_category(academic_landscape.all_skills_covered)

        html = template.render(
            industry_demand=industry_demand,
            academic_landscape=academic_landscape,
            gap_analysis=gap_analysis,
            study_plan=study_plan,
            quality_scores=quality_scores or {},
            generated_date=datetime.now().strftime("%d de %B de %Y, %H:%M"),
            skills_by_category=skills_by_category,
        )

        output_dir = Path(settings.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Sanitize sector name: keep only alphanumeric, spaces, hyphens; replace spaces with underscores
        import re as _re
        safe_sector = _re.sub(r"[^\w\s-]", "", gap_analysis.sector)
        sector_slug = safe_sector.lower().replace(" ", "_")[:30]
        output_path = output_dir / f"reporte_{sector_slug}_{timestamp}.html"

        try:
            output_path.write_text(html, encoding="utf-8")
        except OSError as e:
            raise RuntimeError(
                f"[ReportGenerator] Failed to write report to '{output_path}': {e}. "
                f"Check disk space and directory permissions."
            ) from e

        logger.info(f"[ReportGenerator] Report written to: {output_path}")
        return output_path
