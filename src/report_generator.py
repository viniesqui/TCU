import logging
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.config import settings
from src.models.academic import AcademicLandscape
from src.models.course_design import StudyPlan
from src.models.gap import GapAnalysis
from src.models.market import IndustryDemand

logger = logging.getLogger(__name__)


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

        html = template.render(
            industry_demand=industry_demand,
            academic_landscape=academic_landscape,
            gap_analysis=gap_analysis,
            study_plan=study_plan,
            generated_date=datetime.now().strftime("%d de %B de %Y, %H:%M"),
        )

        output_dir = Path(settings.output_dir)
        output_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        sector_slug = gap_analysis.sector.lower().replace(" ", "_")[:30]
        output_path = output_dir / f"reporte_{sector_slug}_{timestamp}.html"

        output_path.write_text(html, encoding="utf-8")
        logger.info(f"[ReportGenerator] Report written to: {output_path}")
        return output_path
