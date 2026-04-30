# TCU – Análisis de Brecha Educativa con IA

Sistema multi-agente que investiga la brecha entre las necesidades del mercado laboral costarricense y la oferta académica universitaria, y genera automáticamente un curso propuesto para cerrar esa brecha.

---

## ¿Qué hace?

El pipeline ejecuta 7 etapas en secuencia:

1. **Mercado laboral** — busca ofertas de empleo reales y extrae las habilidades más demandadas en el sector indicado.
2. **Oferta académica** — mapea los currículos de universidades públicas y privadas de Costa Rica.
3. **Análisis de brecha** — cruza la demanda del mercado con la cobertura académica e identifica brechas críticas y moderadas.
4. **Plan de estudios** — diseña un nuevo curso con objetivos de aprendizaje (taxonomía de Bloom), créditos y duración.
5. **Actividades** — genera el cronograma semanal de 16 semanas con actividades variadas (laboratorios, proyectos, talleres, etc.).
6. **Sistema de evaluación** — propone los componentes de evaluación, rúbricas y una matriz de competencias.
7. **Reporte HTML** — genera un reporte interactivo con todo el análisis.

Cada etapa pasa por un **quality gate** automático. Si el resultado no cumple los umbrales de calidad, el agente reintenta con instrucciones de corrección específicas.

---

## Requisitos

- Python 3.11 o superior
- Una API key de Anthropic (`ANTHROPIC_API_KEY`)

---

## Inicio rápido

Un solo comando. Crea el venv, instala dependencias, configura `.env` y ejecuta el pipeline:

```bash
git clone https://github.com/viniesqui/TCU.git && cd TCU
./run
```

`./run` es **idempotente**: ejecutarlo diez veces produce el mismo estado limpio. Solo recompila lo que cambió.

La API key se descubre automáticamente:
1. Si `ANTHROPIC_API_KEY` está exportada en tu shell, se usa.
2. Si existe `.env`, se respeta tal cual.
3. Si no, se solicita una vez (entrada oculta) y se persiste en `.env`.

---

## Uso

```bash
./run                                      # sector por defecto: "Desarrollo de Software"
./run --sector "Ciberseguridad"
./run --sector "Inteligencia Artificial" --verbose
./run --help
./run test                                 # ejecuta la suite pytest
```

---

## Salida

Al finalizar, el sistema muestra:

- Una tabla de **calidad por etapa** (porcentaje ✓ / ⚠ / ✗) directamente en la terminal.
- La ruta al **reporte HTML** generado en la carpeta `output/`.
- Una pregunta para **abrir el reporte en el navegador** automáticamente.

El reporte HTML incluye:

- Habilidades del mercado más demandadas, con fuentes verificables.
- Mapa de cobertura académica por universidad.
- Tabla de brechas críticas y moderadas.
- Plan de estudios completo con objetivos por nivel de Bloom.
- Cronograma semanal con tipos de actividad y objetivos cubiertos.
- Sistema de evaluación con rúbricas y matriz de competencias.

---

## Tests

El proyecto incluye una suite de 93 pruebas automatizadas. No requieren API key — todos los agentes y llamadas HTTP están mockeados.

```bash
./run test                                 # toda la suite
./run test tests/test_quality_gates.py -v  # un módulo específico
```

### Módulos de test

| Archivo | Qué prueba |
|---|---|
| `tests/test_quality_gates.py` | Todos los quality gates (umbrales, mensajes de error, retry) |
| `tests/test_models.py` | Validaciones Pydantic (Evaluator, StudyPlan, IndustryDemand, etc.) |
| `tests/test_tools.py` | `web_search` y `web_fetch` con HTTP mockeado |
| `tests/test_report_generator.py` | Renderizado HTML y agrupación de habilidades por categoría |
| `tests/test_orchestrator.py` | Pipeline completo con agentes mockeados; reintentos por gate failure |

---

## Estructura del proyecto

```
TCU/
├── main.py                    # Punto de entrada CLI
├── requirements.txt
├── .env                       # Tu API key (no está en el repo)
├── src/
│   ├── agents/
│   │   ├── orchestrator.py    # Coordina las 7 etapas del pipeline
│   │   ├── labor_market_agent.py
│   │   ├── academic_agent.py
│   │   ├── gap_analyst_agent.py
│   │   ├── curriculum_agent.py
│   │   ├── activities_agent.py
│   │   └── evaluator_agent.py
│   ├── quality/
│   │   ├── research_gates.py  # Gates etapas 1–2
│   │   └── downstream_gates.py# Gates etapas 3–6
│   ├── models/                # Esquemas Pydantic de cada etapa
│   ├── tools/                 # web_search y web_fetch
│   ├── prompts.py             # Prompts de sistema para cada agente
│   ├── report_generator.py    # Renderizado Jinja2 → HTML
│   └── config.py              # Settings con pydantic-settings
├── templates/
│   └── report.html.jinja2     # Plantilla del reporte
└── tests/                     # Suite de pruebas pytest
```

---

## Variables de configuración avanzada

Todas son opcionales y se pueden agregar al `.env`:

| Variable | Default | Descripción |
|---|---|---|
| `MODEL` | `claude-sonnet-4-5` | Modelo de Claude a usar |
| `MAX_AGENT_ITERATIONS` | `12` | Límite de iteraciones por agente (tool-use loop) |
| `MAX_STAGE_RETRIES` | `2` | Reintentos por etapa si el quality gate falla |
| `SEARCH_MAX_RESULTS` | `5` | Resultados máximos por búsqueda web |
| `OUTPUT_DIR` | `output` | Carpeta de salida del reporte |
| `QUALITY_MIN_SKILLS` | `8` | Mínimo de habilidades distintas en etapa 1 |
| `QUALITY_MIN_JOB_POSTINGS` | `5` | Mínimo de ofertas de empleo analizadas |
| `QUALITY_MIN_UNIVERSITIES` | `5` | Mínimo de programas universitarios mapeados |
