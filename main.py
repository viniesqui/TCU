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
import re
import sys
import webbrowser
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

console = Console()

# Whitelist: letters (including Spanish accented chars), digits, spaces, hyphens.
# Rejects path separators, shell metacharacters, quotes, and other injection vectors.
_SECTOR_ALLOWED_RE = re.compile(r"[^a-zA-ZáéíóúüñÁÉÍÓÚÜÑ0-9 \-]")


def _sanitize_sector(value: str) -> str:
    """Sanitize the --sector argument using a strict character whitelist."""
    sanitized = _SECTOR_ALLOWED_RE.sub("", value)
    sanitized = " ".join(sanitized.split())  # collapse extra whitespace
    if not sanitized:
        raise argparse.ArgumentTypeError(
            f"Sector inválido: '{value}'. "
            "Solo se permiten letras, dígitos, espacios y guiones."
        )
    return sanitized


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
        type=_sanitize_sector,
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


class _RichProgressAdapter:
    """Adapts the Rich Progress object for use as an Orchestrator progress callback."""

    def __init__(self, rich_progress: Progress, task_id: object) -> None:
        self._progress = rich_progress
        self._task_id = task_id

    def log(self, message: str) -> None:
        self._progress.update(self._task_id, description=message)


def _print_quality_scores(quality_scores: dict) -> None:
    """Print a quality scores summary table to the console."""
    if not quality_scores:
        return

    table = Table(title="Calidad de Investigación (Gates Automáticos)", show_header=True)
    table.add_column("Etapa", style="bold")
    table.add_column("Puntuación", justify="right")
    table.add_column("Estado", justify="center")

    stage_names = {
        "market_research": "Mercado Laboral",
        "academic_research": "Oferta Académica",
        "gap_analysis": "Análisis de Brecha",
        "curriculum": "Plan de Estudios",
        "activities": "Actividades",
        "evaluator": "Sistema de Evaluación",
    }

    for stage, score in quality_scores.items():
        pct = int(score * 100)
        label = stage_names.get(stage, stage.replace("_", " ").title())
        if pct >= 75:
            status = "[bold green]✓ Bueno[/bold green]"
            score_fmt = f"[green]{pct}%[/green]"
        elif pct >= 50:
            status = "[bold yellow]⚠ Aceptable[/bold yellow]"
            score_fmt = f"[yellow]{pct}%[/yellow]"
        else:
            status = "[bold red]✗ Bajo[/bold red]"
            score_fmt = f"[red]{pct}%[/red]"
        table.add_row(label, score_fmt, status)

    console.print()
    console.print(table)


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

        task = progress.add_task("🔎 Investigando mercado laboral...", total=None)

        # Create a progress adapter so the orchestrator can update the Rich progress bar
        progress_adapter = _RichProgressAdapter(progress, task)

        from src.agents.orchestrator import Orchestrator
        orchestrator = Orchestrator(progress=progress_adapter)

        try:
            report_path = orchestrator.run(sector=args.sector)
            progress.update(task, description="[bold green]¡Completado![/bold green]")
        except Exception as e:
            progress.stop()
            console.print(f"\n[bold red]Error durante la ejecución:[/bold red] {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()
            sys.exit(1)

    # Print quality scores summary
    _print_quality_scores(orchestrator._quality_scores)

    console.print()
    console.print(Panel(
        f"[bold green]¡Reporte generado exitosamente![/bold green]\n\n"
        f"Archivo: [bold]{report_path}[/bold]\n"
        f"Abre el archivo en tu navegador para ver el análisis completo.",
        border_style="green",
        title="TCU – Completado",
    ))
    console.print()

    # Offer to open the report in the browser
    try:
        answer = input("¿Abrir el reporte en el navegador? [s/N]: ").strip().lower()
        if answer in ("s", "si", "sí", "y", "yes"):
            webbrowser.open(Path(report_path).resolve().as_uri())
            console.print("[dim]Abriendo reporte en el navegador...[/dim]")
    except (EOFError, KeyboardInterrupt):
        pass  # Non-interactive environment or user pressed Ctrl+C


if __name__ == "__main__":
    main()
