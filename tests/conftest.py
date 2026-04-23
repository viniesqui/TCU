"""
Shared pytest fixtures for TCU test suite.
All fixtures provide minimal valid data that satisfies quality gate thresholds.
No API keys required — all AI/web calls are mocked at the test level.
"""
import pytest

from src.models.academic import AcademicLandscape, Curriculum, Course
from src.models.course_design import (
    Evaluator,
    EvaluationCriteria,
    LearningActivity,
    LearningObjective,
    StudyPlan,
)
from src.models.gap import GapAnalysis, SkillGap
from src.models.market import IndustryDemand, JobPosting, Skill


# ---------------------------------------------------------------------------
# Market fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_skills() -> list[Skill]:
    """10 skills across multiple categories."""
    return [
        Skill(name="python", category="technical", frequency_score=0.90),
        Skill(name="docker", category="tool", frequency_score=0.82),
        Skill(name="kubernetes", category="tool", frequency_score=0.75),
        Skill(name="fastapi", category="technical", frequency_score=0.70),
        Skill(name="postgresql", category="technical", frequency_score=0.68),
        Skill(name="aws", category="tool", frequency_score=0.65),
        Skill(name="git", category="tool", frequency_score=0.95),
        Skill(name="comunicación efectiva", category="soft", frequency_score=0.60),
        Skill(name="trabajo en equipo", category="soft", frequency_score=0.55),
        Skill(name="javascript", category="technical", frequency_score=0.72),
    ]


@pytest.fixture
def sample_job_postings() -> list[JobPosting]:
    """5 job postings for statistical validity."""
    def _skill(name: str) -> Skill:
        return Skill(name=name, category="technical", frequency_score=0.70)

    return [
        JobPosting(
            title="Backend Developer",
            company="Empresa A",
            source_url="https://example.com/job1",
            required_skills=[_skill("python"), _skill("docker"), _skill("git")],
            seniority="mid",
        ),
        JobPosting(
            title="DevOps Engineer",
            company="Empresa B",
            source_url="https://example.com/job2",
            required_skills=[_skill("kubernetes"), _skill("aws")],
            seniority="senior",
        ),
        JobPosting(
            title="Full Stack Developer",
            company="Empresa C",
            source_url="https://example.com/job3",
            required_skills=[_skill("python"), _skill("javascript"), _skill("git")],
            seniority="junior",
        ),
        JobPosting(
            title="Software Engineer",
            company="Empresa D",
            source_url="https://example.com/job4",
            required_skills=[_skill("python"), _skill("fastapi"), _skill("postgresql")],
            seniority="mid",
        ),
        JobPosting(
            title="Cloud Architect",
            company="Empresa E",
            source_url="https://example.com/job5",
            required_skills=[_skill("aws"), _skill("docker"), _skill("kubernetes")],
            seniority="senior",
        ),
    ]


@pytest.fixture
def sample_industry_demand(sample_skills, sample_job_postings) -> IndustryDemand:
    return IndustryDemand(
        sector="Desarrollo de Software",
        top_skills=sample_skills,
        job_postings_sampled=sample_job_postings,
        market_sources=[
            "https://www.linkedin.com/jobs",
            "https://computrabajo.co.cr",
            "https://camtic.org",
        ],
        research_date="2025-01-15",
        summary=(
            "El mercado laboral costarricense en desarrollo de software muestra alta demanda "
            "de habilidades en Python, contenedores y plataformas cloud. Las empresas de "
            "servicios tecnológicos dominan la oferta de empleos."
        ),
    )


# ---------------------------------------------------------------------------
# Academic fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_curricula() -> list[Curriculum]:
    """5 curricula — 3 public, 2 private."""
    return [
        Curriculum(
            degree_name="Bachillerato en Ingeniería en Computación",
            degree_level="bachillerato",
            university="TEC",
            is_public=True,
            url="https://tec.ac.cr/carrera",
            courses=[
                Course(name="Algoritmos y Estructuras de Datos", credits=4, skills_taught=["python", "algoritmos"]),
                Course(name="Bases de Datos I", credits=3, skills_taught=["sql", "postgresql"]),
                Course(name="Redes de Computadoras", credits=3, skills_taught=["redes", "tcp/ip"]),
                Course(name="Ingeniería de Software", credits=3, skills_taught=["scrum", "git"]),
                Course(name="Programación Orientada a Objetos", credits=4, skills_taught=["java", "poo"]),
            ],
        ),
        Curriculum(
            degree_name="Bachillerato en Ciencias de la Computación",
            degree_level="bachillerato",
            university="UCR",
            is_public=True,
            url="https://ecci.ucr.ac.cr",
            courses=[
                Course(name="Programación I", credits=4, skills_taught=["python", "lógica"]),
                Course(name="Estructuras Discretas", credits=3, skills_taught=["lógica matemática"]),
                Course(name="Sistemas Operativos", credits=3, skills_taught=["linux", "concurrencia"]),
                Course(name="Compiladores", credits=4, skills_taught=["teoría de compiladores"]),
                Course(name="Inteligencia Artificial", credits=3, skills_taught=["machine learning", "python"]),
            ],
        ),
        Curriculum(
            degree_name="Ingeniería en Informática",
            degree_level="bachillerato",
            university="UNA",
            is_public=True,
            url="https://una.ac.cr/informatica",
            courses=[
                Course(name="Fundamentos de Programación", credits=4, skills_taught=["python", "javascript"]),
                Course(name="Base de Datos Avanzada", credits=3, skills_taught=["postgresql", "mongodb"]),
                Course(name="Desarrollo Web", credits=3, skills_taught=["html", "css", "javascript"]),
                Course(name="Seguridad Informática", credits=3, skills_taught=["ciberseguridad"]),
            ],
        ),
        Curriculum(
            degree_name="Bachillerato en Ingeniería de Software",
            degree_level="bachillerato",
            university="ULACIT",
            is_public=False,
            url="https://ulacit.ac.cr/software",
            courses=[
                Course(name="Metodologías Ágiles", credits=3, skills_taught=["scrum", "kanban"]),
                Course(name="Arquitectura de Software", credits=3, skills_taught=["patrones de diseño"]),
                Course(name="Desarrollo Móvil", credits=3, skills_taught=["kotlin", "swift"]),
                Course(name="Cloud Computing", credits=3, skills_taught=["aws", "azure"]),
            ],
        ),
        Curriculum(
            degree_name="Ingeniería en Computación",
            degree_level="bachillerato",
            university="CENFOTEC",
            is_public=False,
            url="https://ucenfotec.ac.cr",
            courses=[
                Course(name="DevOps y CI/CD", credits=3, skills_taught=["docker", "jenkins", "git"]),
                Course(name="Machine Learning", credits=3, skills_taught=["python", "machine learning"]),
                Course(name="Desarrollo de APIs", credits=3, skills_taught=["fastapi", "rest"]),
                Course(name="Seguridad en Aplicaciones", credits=3, skills_taught=["ciberseguridad", "owasp"]),
            ],
        ),
    ]


@pytest.fixture
def sample_academic_landscape(sample_curricula) -> AcademicLandscape:
    return AcademicLandscape(
        curricula_sampled=sample_curricula,
        all_skills_covered=[
            "python", "java", "javascript", "html", "css", "sql", "postgresql",
            "mongodb", "docker", "git", "aws", "azure", "scrum", "kanban",
            "machine learning", "linux", "redes", "ciberseguridad",
        ],
        research_date="2025-01-15",
        summary=(
            "Las universidades costarricenses ofrecen programas sólidos en fundamentos "
            "de programación y bases de datos, pero muestran cobertura limitada en "
            "tecnologías de contenedores y orquestación modernas."
        ),
    )


# ---------------------------------------------------------------------------
# Gap analysis fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_gap_analysis() -> GapAnalysis:
    return GapAnalysis(
        sector="Desarrollo de Software",
        critical_gaps=[
            SkillGap(skill_name="kubernetes", market_demand_score=0.75, academic_coverage_score=0.10, gap_severity="critical", notes="Alta demanda, casi sin cobertura académica", market_depth_required="avanzado"),
            SkillGap(skill_name="fastapi", market_demand_score=0.70, academic_coverage_score=0.15, gap_severity="critical", notes="Framework moderno con poca presencia en curricula", market_depth_required="intermedio"),
            SkillGap(skill_name="ci/cd pipelines", market_demand_score=0.68, academic_coverage_score=0.10, gap_severity="critical", notes="Prácticas DevOps con mínima cobertura", market_depth_required="avanzado"),
            SkillGap(skill_name="microservicios", market_demand_score=0.65, academic_coverage_score=0.05, gap_severity="critical", notes="Arquitectura muy demandada, casi no enseñada", market_depth_required="avanzado"),
            SkillGap(skill_name="terraform", market_demand_score=0.62, academic_coverage_score=0.00, gap_severity="critical", notes="Infraestructura como código ausente en currículas", market_depth_required="avanzado"),
        ],
        moderate_gaps=[
            SkillGap(skill_name="observabilidad", market_demand_score=0.55, academic_coverage_score=0.30, gap_severity="moderate", notes="Monitoring y logging parcialmente cubiertos"),
            SkillGap(skill_name="seguridad en APIs", market_demand_score=0.50, academic_coverage_score=0.35, gap_severity="moderate", notes="Seguridad básica enseñada pero no en contexto de APIs"),
            SkillGap(skill_name="bases de datos distribuidas", market_demand_score=0.48, academic_coverage_score=0.40, gap_severity="moderate", notes="Bases de datos distribuidas poco cubiertas"),
        ],
        well_covered=[
            SkillGap(skill_name="python", market_demand_score=0.90, academic_coverage_score=0.95, gap_severity="covered", notes="Bien cubierto en todas las universidades"),
            SkillGap(skill_name="sql", market_demand_score=0.80, academic_coverage_score=0.90, gap_severity="covered", notes="Estándar en todos los programas"),
            SkillGap(skill_name="git", market_demand_score=0.95, academic_coverage_score=0.85, gap_severity="covered", notes="Control de versiones enseñado universalmente"),
        ],
        opportunity_statement=(
            "Existe una brecha significativa entre la alta demanda del mercado costarricense "
            "por habilidades en DevOps y arquitecturas cloud-native y la escasa cobertura "
            "que ofrecen actualmente las universidades del país. Un curso especializado en "
            "estas tecnologías permitiría a los egresados entrar al mercado con habilidades "
            "inmediatamente aplicables."
        ),
        proposed_course_title="Ingeniería de Plataformas Cloud-Native y DevOps",
        proposed_course_depth="avanzado",
        proposed_course_rationale=(
            "Un curso práctico que cubra contenedores, orquestación, CI/CD, "
            "e infraestructura como código, conectando directamente con las "
            "necesidades identificadas en el mercado laboral costarricense."
        ),
    )


# ---------------------------------------------------------------------------
# Course design fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_learning_objectives() -> list[LearningObjective]:
    return [
        LearningObjective(bloom_level="recordar", description="Identificar los componentes principales de una arquitectura cloud-native."),
        LearningObjective(bloom_level="comprender", description="Explicar el ciclo de vida de un contenedor Docker y su rol en el despliegue moderno."),
        LearningObjective(bloom_level="aplicar", description="Implementar una aplicación multi-contenedor usando Docker Compose."),
        LearningObjective(bloom_level="aplicar", description="Usar Kubernetes para desplegar y escalar servicios en un clúster de práctica."),
        LearningObjective(bloom_level="analizar", description="Comparar estrategias de CI/CD y seleccionar la más adecuada según el contexto del proyecto."),
        LearningObjective(bloom_level="evaluar", description="Evaluar la seguridad y observabilidad de un pipeline de despliegue dado."),
        LearningObjective(bloom_level="crear", description="Diseñar e implementar un pipeline CI/CD completo para una aplicación real usando herramientas open-source."),
    ]


@pytest.fixture
def sample_activities(sample_learning_objectives) -> list[LearningActivity]:
    num_objectives = len(sample_learning_objectives)
    activities = []
    type_rotation = [
        "lectura", "laboratorio", "laboratorio", "taller",
        "laboratorio", "caso_estudio", "proyecto", "taller",
        "laboratorio", "proyecto", "debate", "proyecto",
        "proyecto", "proyecto", "taller", "evaluacion",
    ]
    titles = [
        "Introducción a Cloud-Native", "Primeros pasos con Docker", "Docker Compose en práctica",
        "Taller: Contenedores en CI", "Kubernetes básico", "Caso: Netflix y microservicios",
        "Proyecto 1: App conteneurizada", "Taller: Helm Charts",
        "Laboratorio: Pipelines CI/CD", "Proyecto 2: Pipeline completo",
        "Debate: DevOps vs SRE", "Proyecto 3: Infraestructura como código",
        "Proyecto integrador (parte 1)", "Proyecto integrador (parte 2)",
        "Taller de revisión y optimización", "Evaluación final del proyecto",
    ]
    for week in range(1, 17):
        idx = week - 1
        act_type = type_rotation[idx]
        obj_refs = [idx % num_objectives, (idx + 1) % num_objectives]
        activities.append(LearningActivity(
            week=week,
            title=titles[idx],
            activity_type=act_type,
            description=f"Actividad de la semana {week}: {titles[idx]}. Los estudiantes explorarán conceptos clave.",
            estimated_hours=3.0 if act_type == "lectura" else 5.0,
            learning_objectives_addressed=obj_refs,
        ))
    return activities


@pytest.fixture
def sample_evaluator() -> Evaluator:
    return Evaluator(
        evaluation_components=[
            EvaluationCriteria(
                component="Laboratorios y Tareas",
                weight_percent=25.0,
                rubric_items=["Código funciona correctamente", "Documentación incluida", "Buenas prácticas aplicadas"],
                passing_threshold=70.0,
            ),
            EvaluationCriteria(
                component="Proyecto Integrador",
                weight_percent=35.0,
                rubric_items=["Pipeline CI/CD funcional", "Contenedores bien configurados", "Infraestructura como código", "Presentación clara"],
                passing_threshold=70.0,
            ),
            EvaluationCriteria(
                component="Examen Parcial",
                weight_percent=15.0,
                rubric_items=["Conceptos correctos", "Aplicación práctica demostrada", "Casos de uso identificados"],
                passing_threshold=70.0,
            ),
            EvaluationCriteria(
                component="Examen Final",
                weight_percent=20.0,
                rubric_items=["Comprensión integral", "Análisis crítico", "Soluciones propuestas justificadas"],
                passing_threshold=70.0,
            ),
            EvaluationCriteria(
                component="Participación",
                weight_percent=5.0,
                rubric_items=["Asistencia activa", "Aportes en debates", "Colaboración con compañeros"],
                passing_threshold=70.0,
            ),
        ],
        competency_matrix={
            "docker": ["Primeros pasos con Docker", "Docker Compose en práctica"],
            "kubernetes": ["Kubernetes básico", "Proyecto integrador (parte 1)"],
            "ci/cd": ["Laboratorio: Pipelines CI/CD", "Proyecto 2: Pipeline completo"],
        },
    )


@pytest.fixture
def sample_study_plan(
    sample_learning_objectives,
    sample_activities,
    sample_evaluator,
) -> StudyPlan:
    return StudyPlan(
        course_title="Ingeniería de Plataformas Cloud-Native y DevOps",
        course_code="TCU-501",
        credits=4,
        hours_per_week=12.0,
        total_weeks=16,
        target_audience="Estudiantes de tercer o cuarto año de Ingeniería en Computación o carrera afín.",
        prerequisites=["Sistemas Operativos", "Redes de Computadoras"],
        learning_objectives=sample_learning_objectives,
        weekly_schedule=sample_activities,
        evaluator=sample_evaluator,
        bibliography=[
            "Burns, B. et al. (2022). Kubernetes: Up and Running. O'Reilly.",
            "Kim, G. et al. (2021). The DevOps Handbook. IT Revolution Press.",
            "Docker Documentation. https://docs.docker.com",
        ],
    )
