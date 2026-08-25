# 🎓 TCU – Portal Curricular Multi-Persona con Inteligencia Artificial

> **Trabajo Comunal Universitario — Universidad de Costa Rica**

Una plataforma web interactiva impulsada por **múltiples agentes de Inteligencia Artificial** que colaboran para investigar el mercado laboral, diseñar planes de estudio universitarios, impartir clases, evaluar estudiantes y generar recursos multimedia — todo de forma autónoma.

---

## 📋 Tabla de Contenidos

- [Descripción del Proyecto](#-descripción-del-proyecto)
- [Las 4 Personas (Roles de IA)](#-las-4-personas-roles-de-ia)
- [Capturas de Pantalla](#-capturas-de-pantalla)
- [Requisitos Previos](#-requisitos-previos)
- [Instalación y Configuración](#-instalación-y-configuración)
- [Obtener las Llaves de API](#-obtener-las-llaves-de-api)
- [Uso](#-uso)
- [Modo Demo (Sin Gastar Créditos)](#-modo-demo-sin-gastar-créditos)
- [Arquitectura del Sistema](#-arquitectura-del-sistema)
- [Estructura del Proyecto](#-estructura-del-proyecto)
- [Tests](#-tests)
- [Despliegue en Producción](#-despliegue-en-producción)
- [Autores](#-autores)
- [Licencia](#-licencia)

---

## 📖 Descripción del Proyecto

**TCU** (Trabajo Comunal Universitario) es un sistema multi-agente que analiza la **brecha entre las necesidades del mercado laboral** y la **oferta académica universitaria** en Costa Rica. Una vez identificada la brecha, los agentes generan automáticamente:

1. Un análisis del mercado laboral (habilidades demandadas, ofertas de empleo).
2. Un análisis de la oferta académica (mallas curriculares existentes en universidades costarricenses).
3. Un análisis de brecha (qué habilidades faltan en la formación actual).
4. Un plan de estudios (syllabus) diseñado para cerrar esa brecha.
5. Material de lectura y actividades semana a semana.
6. Evaluaciones y retroalimentación automática para los estudiantes.
7. Recursos multimedia: audio TTS, flashcards Anki y cuestionarios interactivos.

---

## 🎭 Las 4 Personas (Roles de IA)

El sistema simula un ecosistema universitario completo dividido en **4 agentes especializados**:

| # | Persona | Rol | Qué hace |
|---|---------|-----|----------|
| 1 | 🔎 **Investigador** | Labor Market & Academic Agent | Busca en tiempo real ofertas de empleo y mallas curriculares en Costa Rica. Identifica brechas entre lo que pide el mercado y lo que enseñan las universidades. |
| 2 | 🎓 **Coordinador Académico** | Curriculum & Approver Agent | Revisa la investigación, aprueba los hallazgos y diseña la estructura del nuevo curso (Syllabus) enfocado en cerrar la brecha. |
| 3 | 👨‍🏫 **Profesor** | Professor Agent | Toma el plan de estudios aprobado y genera material de lectura detallado semana a semana, actividades y evaluaciones. |
| 4 | 📖 **Estudiante** | Student Agent | Lee el material del profesor, investiga por su cuenta y genera entregas/tareas para ser evaluadas por el sistema. |

El flujo se completa cuando el **Evaluator Agent** califica las entregas del estudiante y proporciona retroalimentación detallada.

---

## 🖼️ Capturas de Pantalla

*(Se incluye un video de demostración `tcu_live_software_demo.webm` en el repositorio.)*

---

## ✅ Requisitos Previos

- **Python 3.11** o superior
- **pip** (se instala automáticamente con Python)
- **Git** para clonar el repositorio
- Una **API Key de Anthropic** (obligatoria — ver sección siguiente)
- *Opcionales:* API Keys de OpenAI, ElevenLabs y/o HeyGen para funciones multimedia

---

## 🔧 Instalación y Configuración

### 1. Clonar el repositorio

```bash
git clone https://github.com/viniesqui/TCU.git
cd TCU
```

### 2. Configurar las variables de entorno

El proyecto **nunca incluye llaves reales** en el repositorio. Debes crear tu propio archivo `.env`:

```bash
cp .env.example .env
```

Luego abre el archivo `.env` con tu editor favorito y pega tus llaves:

```bash
# Abre con nano, vim, VS Code, o cualquier editor:
nano .env
```

El archivo se verá así (rellena solo las llaves que tengas):

```env
# OBLIGATORIA
ANTHROPIC_API_KEY=sk-ant-tu-llave-real-aqui

# OPCIONALES (para funciones multimedia)
OPENAI_API_KEY=tu-llave-openai-aqui
ELEVENLABS_API_KEY=tu-llave-elevenlabs-aqui
HEYGEN_API_KEY=tu-llave-heygen-aqui
```

> ⚠️ **Importante:** El archivo `.env` está en el `.gitignore` y **nunca se sube al repositorio**. No compartas tus llaves.

### 3. Iniciar la plataforma

El proyecto incluye un script llamado `./run` que hace todo automáticamente:
- Crea el entorno virtual (`.venv`)
- Instala las dependencias
- Solicita la llave de Anthropic si no existe el `.env`
- Levanta el servidor web

```bash
./run web
```

Esto abrirá automáticamente tu navegador en `http://127.0.0.1:8765/`.

---

## 🔑 Obtener las Llaves de API

### Anthropic (Obligatoria)

Esta es la llave principal que alimenta a todos los agentes de IA del sistema.

1. Ve a [console.anthropic.com](https://console.anthropic.com/)
2. Crea una cuenta o inicia sesión
3. Navega a **Settings → API Keys**
4. Haz clic en **"Create Key"**
5. Copia la llave (empieza con `sk-ant-...`)
6. Pégala en tu archivo `.env` como `ANTHROPIC_API_KEY`

> 💡 Anthropic ofrece créditos gratuitos para nuevas cuentas. Después de eso, las llamadas se cobran según el uso.

### OpenAI (Opcional — Audio TTS)

Necesaria para generar audio narrado con las voces de OpenAI.

1. Ve a [platform.openai.com](https://platform.openai.com/)
2. Crea una cuenta o inicia sesión
3. Navega a **API Keys** en el menú lateral
4. Haz clic en **"Create new secret key"**
5. Copia y pega en `.env` como `OPENAI_API_KEY`

### ElevenLabs (Opcional — Audio TTS alternativo)

Para generar audio con voces más naturales y en español.

1. Ve a [elevenlabs.io](https://elevenlabs.io/)
2. Crea una cuenta (el plan gratuito incluye 10,000 caracteres/mes)
3. Ve a **Profile → API Key**
4. Copia la llave y pégala como `ELEVENLABS_API_KEY`

### HeyGen (Opcional — Video con Avatar)

Para generar videos con avatares virtuales que presentan el contenido.

1. Ve a [heygen.com](https://www.heygen.com/)
2. Crea una cuenta
3. Navega a **Settings → API**
4. Genera una llave y pégala como `HEYGEN_API_KEY`

---

## 🚀 Uso

### Interfaz Web (Recomendada)

```bash
./run web
```

Navega con el menú de 4 pestañas (Investigador → Coordinador → Profesor → Estudiante) para ejecutar cada etapa del pipeline.

**Características principales de la interfaz:**
- 🔐 Sistema de login con roles (investigador, coordinador, profesor, estudiante)
- 📊 Progreso en vivo del pipeline de agentes
- ✅ Revisión humana del análisis de brecha antes de diseñar el curso
- 📖 Material de lectura interactivo con narración de audio
- 🃏 Flashcards interactivas con exportación a Anki
- 📝 Evaluaciones con retroalimentación automática
- 🌙 Modo oscuro / claro
- ⚙️ Panel de configuración para presupuestos de API

### Línea de Comandos (CLI)

```bash
# Análisis con sector por defecto (Desarrollo de Software)
./run

# Especificar un sector distinto
./run --sector "Ciberseguridad"

# Con logs detallados
./run --sector "Inteligencia Artificial" --verbose

# Con revisión humana antes de diseñar el curso
./run --review
```

### Ejecutar Tests

```bash
./run test
```

---

## 🎮 Modo Demo (Sin Gastar Créditos)

Si quieres hacer una demostración rápida **sin consumir créditos de API**:

1. Abre la aplicación web (`./run web`)
2. Ve a la esquina superior derecha y haz clic en **"⚙️ Config Demo"**
3. Cambia los presupuestos máximos de los agentes a **$0.00**
4. El sistema activará automáticamente el **Fallback Local (Mocks)**, simulando las respuestas de los agentes con datos pre-guardados

Esto permite mostrar el flujo completo del sistema en segundos.

> 📝 Todos los consumos, costos y decisiones de los agentes quedan registrados en `logs/agent_activity.log`.

---

## 🏗️ Arquitectura del Sistema

```
┌─────────────────────────────────────────────────────────┐
│                    Usuario (Navegador)                    │
│              HTML5 + CSS + JavaScript Vanilla             │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP / WebSocket
┌────────────────────────▼────────────────────────────────┐
│                   FastAPI + Uvicorn                       │
│              (src/web/server.py · Puerto 8765)           │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│              Orquestador de Agentes                      │
│            (src/agents/orchestrator.py)                   │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Investigador  │→ │ Coordinador  │→ │   Profesor   │  │
│  │  (Mercado +   │  │  (Brecha +   │  │  (Lecturas + │  │
│  │  Académico)   │  │   Syllabus)  │  │ Actividades) │  │
│  └──────────────┘  └──────────────┘  └──────┬───────┘  │
│                                              │          │
│                    ┌──────────────┐  ┌───────▼──────┐   │
│                    │  Evaluador   │← │  Estudiante  │   │
│                    │  (Califica)  │  │  (Entregas)  │   │
│                    └──────────────┘  └──────────────┘   │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────┐
│  SQLite (tcu.db)  │  Anthropic API  │  Búsqueda Web    │
│  Persistencia      │  Claude Sonnet  │  DuckDuckGo      │
└─────────────────────────────────────────────────────────┘
```

**Stack tecnológico:**

| Capa | Tecnología |
|------|-----------|
| **Frontend** | HTML5, CSS Nativo, JavaScript Vanilla |
| **Backend** | Python 3.11+, FastAPI, Uvicorn |
| **Base de Datos** | SQLite (persistencia entre reinicios) |
| **Motor de IA** | Anthropic Claude (vía SDK de Python) |
| **Búsqueda Web** | DuckDuckGo Search (sin API key) |
| **Audio TTS** | OpenAI TTS / ElevenLabs (opcional) |
| **Video Avatar** | HeyGen (opcional) |
| **Flashcards** | genanki (exportación a Anki) |

---

## 📂 Estructura del Proyecto

```
TCU/
├── .env.example           # Plantilla de variables de entorno
├── .gitignore             # Archivos excluidos del repositorio
├── main.py                # Punto de entrada CLI
├── main_web.py            # Punto de entrada Web (FastAPI)
├── run                    # Script de arranque (bootstrap)
├── requirements.txt       # Dependencias de Python
│
├── src/
│   ├── config.py          # Configuración (lee .env)
│   ├── database.py        # Persistencia SQLite
│   ├── multimedia.py      # Audio TTS, Flashcards Anki, Video
│   ├── prompts.py         # Prompts del sistema para los agentes
│   ├── report_generator.py # Generación de reportes HTML
│   │
│   ├── agents/            # 🤖 Motor multi-agente
│   │   ├── orchestrator.py        # Orquestador principal
│   │   ├── base_agent.py          # Clase base con tool-use loop
│   │   ├── labor_market_agent.py  # Agente de mercado laboral
│   │   ├── academic_agent.py      # Agente académico
│   │   ├── gap_analyst_agent.py   # Agente de análisis de brecha
│   │   ├── course_designer_agent.py # Diseñador de curso
│   │   ├── reading_agent.py       # Agente de lecturas
│   │   ├── evaluator_agent.py     # Agente evaluador
│   │   ├── exam_agent.py          # Generador de exámenes
│   │   └── grading_agent.py       # Calificador de entregas
│   │
│   ├── web/               # 🌐 Interfaz web
│   │   ├── server.py      # Endpoints FastAPI
│   │   └── static/        # HTML, CSS, JS del frontend
│   │
│   ├── quality/           # ✅ Quality gates automáticos
│   ├── tools/             # 🔧 Herramientas de los agentes
│   └── models/            # 📦 Modelos de datos (Pydantic)
│
├── tests/                 # 🧪 Suite de tests (pytest)
├── config/                # ⚙️ Configuraciones adicionales
├── templates/             # 📄 Plantillas Jinja2
└── logs/                  # 📝 Logs de actividad de agentes
```

---

## 🧪 Tests

El proyecto incluye una suite completa de tests unitarios con `pytest`:

```bash
# Ejecutar todos los tests
./run test

# Ejecutar con salida detallada
./run test -v

# Ejecutar un archivo de tests específico
./run test tests/test_orchestrator.py
```

Los tests cubren:
- Modelos de datos y validación
- Orquestador de agentes
- Quality gates automáticos
- Generador de reportes
- Servidor web (endpoints de la API)
- Base de datos (CRUD)
- Flashcards y coherencia de contenido

---

## ☁️ Despliegue en Producción

> ⚠️ El sistema utiliza SQLite y procesos de investigación que pueden tardar más de 60 segundos. **No se recomienda plataformas serverless** (Vercel, AWS Lambda).

Se recomienda usar contenedores o servidores con persistencia de disco:
- [Render](https://render.com/)
- [Railway](https://railway.app/)
- [DigitalOcean](https://www.digitalocean.com/)

### Comando de arranque para producción:

```bash
python main_web.py --host 0.0.0.0 --no-browser
```

Variables de entorno que debes definir en tu plataforma de hosting:

```
ANTHROPIC_API_KEY=sk-ant-tu-llave...
```

---

## 👥 Autores

- **Vinicio Esquivel** — Desarrollo principal

---

## 📄 Licencia

Este proyecto fue desarrollado como parte del **Trabajo Comunal Universitario (TCU)** de la Universidad de Costa Rica.

---

<p align="center">
  <b>🎓 TCU — Portal Curricular Multi-Persona con Inteligencia Artificial</b><br>
  <i>Cerrando la brecha entre la academia y el mercado laboral en Costa Rica</i>
</p>
