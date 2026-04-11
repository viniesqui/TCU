#!/usr/bin/env python3
"""
TCU – Sistema Multi-Agente para Análisis de Brecha Educativa en Costa Rica
===========================================================================
Investiga la brecha entre las necesidades del mercado laboral y la oferta
académica universitaria, y genera un curso propuesto para cerrar esa brecha.

Uso:
    python main.py
    python main.py --sector "Ciberseguridad"
    python main.py --sector "Inteligencia Artificial" --verbose
"""

import argparse
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.text import Text

console = Console()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="TCU – Análisis de Brecha Educativa con Agentes de IA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python main.py
  python main.py --sector "Ciberseguridad"
  python main.py --sector "Desarrollo de Software" --verbose
        """,
    )
    parser.add_argument(
        "--sector",
        default="Desarrollo de Software",
        help="Sector del mercado laboral a analizar (default: 'Desarrollo de Software')",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Mostrar logs detallados de cada agente",
    )
    return parser.parse_args()


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    # Silence noisy third-party loggers
    for noisy in ["httpx", "httpcore", "urllib3", "duckduckgo_search"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    args = parse_args()
    setup_logging(args.verbose)

    console.print()
    console.print(Panel.fit(
        "[bold blue]TCU – Análisis de Brecha Educativa[/bold blue]\n"
        "[dim]Sistema Multi-Agente de Inteligencia Artificial[/dim]",
        border_style="blue",
    ))
    console.print(f"\nSector: [bold cyan]{args.sector}[/bold cyan]")
    console.print("Iniciando pipeline de agentes...\n")

    try:
        from src.config import settings  # Validate API key early
        console.print(f"[dim]Modelo: {settings.model}[/dim]\n")
    except Exception as e:
        console.print(f"[bold red]Error de configuración:[/bold red] {e}")
        console.print("[yellow]Asegúrate de que el archivo .env existe con ANTHROPIC_API_KEY definido.[/yellow]")
        sys.exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:

        task = progress.add_task("Ejecutando agentes...", total=None)

        stages = [
            "🔎 Investigando mercado laboral en Costa Rica...",
            "🎓 Investigando oferta académica universitaria...",
            "📊 Analizando brecha educativa...",
            "📝 Diseñando plan de estudios...",
            "📅 Creando actividades de aprendizaje...",
            "✅ Diseñando sistema de evaluación...",
            "📄 Generando reporte HTML...",
        ]

        current_stage = {"idx": 0}

        def on_progress(description: str) -> None:
            if current_stage["idx"] < len(stages):
                progress.update(task, description=stages[current_stage["idx"]])
                current_stage["idx"] += 1

        from src.agents.orchestrator import Orchestrator
        orchestrator = Orchestrator()

        # Monkey-patch the progress callback
        original_update = orchestrator._update_progress
        def patched_update(desc: str) -> None:
            on_progress(desc)
            original_update(desc)
        orchestrator._update_progress = patched_update

        try:
            progress.update(task, description=stages[0])
            report_path = orchestrator.run(sector=args.sector)
            progress.update(task, description="[bold green]¡Completado![/bold green]")
        except Exception as e:
            progress.stop()
            console.print(f"\n[bold red]Error durante la ejecución:[/bold red] {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()
            sys.exit(1)

    console.print()
    console.print(Panel(
        f"[bold green]¡Reporte generado exitosamente![/bold green]\n\n"
        f"Archivo: [bold]{report_path}[/bold]\n"
        f"Abre el archivo en tu navegador para ver el análisis completo.",
        border_style="green",
        title="TCU – Completado",
    ))
    console.print()


if __name__ == "__main__":
    main()
