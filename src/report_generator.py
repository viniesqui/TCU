import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

from src.config import settings
from src.models.academic import AcademicLandscape
from src.models.course_design import StudyPlan
from src.models.gap import GapAnalysis
from src.models.market import IndustryDemand

logger = logging.getLogger(__name__)

_CATEGORIES_CONFIG_PATH = Path(__file__).parent.parent / "config" / "categories.yaml"


def _load_categories_config() -> dict:
    """Load skill categorisation config from config/categories.yaml."""
    if not _CATEGORIES_CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Categories config not found: {_CATEGORIES_CONFIG_PATH}. "
            "Ensure config/categories.yaml is present in the project root."
        )
    with _CATEGORIES_CONFIG_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# Load once at import time so the file is read only once per process.
_CATEGORIES_CONFIG = _load_categories_config()
_MATCH_ORDER: list[str] = _CATEGORIES_CONFIG["match_order"]
_DISPLAY_ORDER: list[str] = _CATEGORIES_CONFIG["display_order"]
_DEFAULT_CATEGORY: str = _CATEGORIES_CONFIG["default_category"]
# Build frozensets of keywords keyed by category name for O(1) membership tests.
_CATEGORY_KEYWORDS: dict[str, frozenset[str]] = {
    cat: frozenset(kw.lower() for kw in keywords)
    for cat, keywords in _CATEGORIES_CONFIG["categories"].items()
}


def _categorize_skill(skill: str) -> str:
    """Assign a display category to a skill string based on keyword matching."""
    s = skill.lower()
    for cat_name in _MATCH_ORDER:
        if any(kw in s for kw in _CATEGORY_KEYWORDS.get(cat_name, frozenset())):
            return cat_name
    return _DEFAULT_CATEGORY


def _group_skills_by_category(skills: list[str]) -> dict[str, list[str]]:
    """Group a flat skill list into display categories, sorted alphabetically within each."""
    groups: dict[str, list[str]] = defaultdict(list)
    for skill in skills:
        groups[_categorize_skill(skill)].append(skill)
    result: dict[str, list[str]] = {}
    for cat in _DISPLAY_ORDER:
        if cat in groups:
            result[cat] = sorted(groups[cat])
    # Preserve any categories added in the YAML that fall outside the display order.
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
        review_record: dict | None = None,
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
            review_record=review_record,
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
