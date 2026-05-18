"""
Interactive gap-analysis checkpoint
===================================
After Stage 3 (gap analysis), the educator reviews the priority skills the
agents discovered, before Stage 4 (curriculum design) commits to a course.

The orchestrator stays decoupled: it receives a ``review_hook`` callable that
takes a ``GapAnalysis`` and returns ``(modified_gap, audit_record)``. This
module implements the Rich-based CLI version of that hook; a future web
frontend would supply its own implementation against the same contract.
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.models.gap import GapAnalysis, SkillGap

logger = logging.getLogger(__name__)

_AUDIT_DIR = Path("stage_cache")
_DEPTHS = ("basico", "intermedio", "avanzado")


def review(
    gap_analysis: GapAnalysis,
    reviewer: str | None = None,
    console: Console | None = None,
) -> tuple[GapAnalysis, dict[str, Any]]:
    """Run the interactive review. Returns (possibly-modified gap, audit record)."""
    console = console or Console()
    reviewer = reviewer or _default_reviewer()

    while True:
        _render(gap_analysis, console)
        choice = _prompt(
            console,
            "[A]ceptar  [E]ditar  [T]ítulo  [V]er detalle  [S]altar (auto)",
        ).strip().lower()

        if choice in ("a", "aceptar", ""):
            audit = _build_audit(gap_analysis, reviewer, skipped=False)
            _persist_audit(gap_analysis.sector, audit)
            console.print("[green]✓ Brecha aceptada. Continuando al diseño del curso...[/green]\n")
            return gap_analysis, audit

        if choice in ("s", "saltar"):
            audit = _build_audit(gap_analysis, reviewer, skipped=True)
            _persist_audit(gap_analysis.sector, audit)
            console.print("[yellow]→ Modo automático: usando la selección detectada sin cambios.[/yellow]\n")
            return gap_analysis, audit

        if choice in ("e", "editar"):
            gap_analysis = _edit_skills(gap_analysis, console)
            continue

        if choice in ("t", "titulo", "título"):
            gap_analysis = _edit_title_rationale(gap_analysis, console)
            continue

        if choice in ("v", "ver"):
            _view_skill(gap_analysis, console)
            continue

        console.print(f"[red]Opción no reconocida: '{choice}'[/red]")


# ──────────────────────────────────────────────────────────────────────────
# Rendering
# ──────────────────────────────────────────────────────────────────────────

def _render(gap: GapAnalysis, console: Console) -> None:
    console.print()
    console.print(Panel.fit(
        f"[bold]CHECKPOINT · Revisión de Brecha Educativa[/bold]\n"
        f"[dim]Sector:[/dim] [cyan]{gap.sector}[/cyan]",
        border_style="blue",
    ))
    console.print(
        "[dim]La selección actual será usada por el agente de diseño curricular. "
        "Las habilidades [b]ya cubiertas[/b] no se incluyen en el curso.[/dim]\n"
    )

    _render_section(console, "BRECHAS CRÍTICAS", gap.critical_gaps, start_idx=1, color="red")
    moderate_start = 1 + len(gap.critical_gaps)
    _render_section(console, "BRECHAS MODERADAS", gap.moderate_gaps, start_idx=moderate_start, color="yellow")

    if gap.well_covered:
        names = ", ".join(s.skill_name for s in gap.well_covered)
        console.print(Panel(
            f"[dim]{names}[/dim]",
            title="[dim]YA CUBIERTO (referencia)[/dim]",
            border_style="dim",
        ))

    console.print()
    console.print(f"[bold]Título propuesto:[/bold]   {gap.proposed_course_title}")
    console.print(f"[bold]Profundidad:[/bold]        {gap.proposed_course_depth}")
    console.print(f"[bold]Justificación:[/bold]      {_truncate(gap.proposed_course_rationale, 180)}")

    total = len(gap.critical_gaps) + len(gap.moderate_gaps)
    console.print(f"\n[dim]Total de habilidades que entrarán al curso: {total}[/dim]")


def _render_section(
    console: Console,
    title: str,
    skills: list[SkillGap],
    start_idx: int,
    color: str,
) -> None:
    if not skills:
        return
    table = Table(title=title, title_style=f"bold {color}", show_lines=False)
    table.add_column("#", justify="right", style="dim", width=3)
    table.add_column("Habilidad", style="bold")
    table.add_column("Demanda", justify="left")
    table.add_column("Cobertura", justify="left")
    table.add_column("Profundidad", justify="left")

    for offset, skill in enumerate(skills):
        idx = start_idx + offset
        table.add_row(
            str(idx),
            skill.skill_name,
            _bar(skill.market_demand_score),
            _bar(skill.academic_coverage_score),
            skill.market_depth_required,
        )
    console.print(table)


def _bar(score: float, width: int = 8) -> str:
    filled = int(round(score * width))
    return "█" * filled + "·" * (width - filled) + f" {score:.2f}"


def _truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


# ──────────────────────────────────────────────────────────────────────────
# Edit actions
# ──────────────────────────────────────────────────────────────────────────

def _edit_skills(gap: GapAnalysis, console: Console) -> GapAnalysis:
    console.print(
        "\n[bold]Editar selección[/bold]\n"
        "[dim]Comandos:[/dim]\n"
        "  [dim]<n>[/dim]                            descartar/restaurar habilidad #n\n"
        "  [dim]+<nombre>, <profundidad>[/dim]      agregar habilidad manual\n"
        "  [dim]done[/dim]                          terminar edición\n"
    )

    removed: dict[int, SkillGap] = {}

    while True:
        _render_editor(gap, removed, console)
        cmd = _prompt(console, "edit").strip()
        if not cmd or cmd.lower() in ("done", "ok", "q"):
            break

        if cmd.startswith("+"):
            added = _parse_manual_addition(cmd[1:], console)
            if added is not None:
                gap.critical_gaps.append(added)
                console.print(f"[green]✓ Agregado:[/green] {added.skill_name} ({added.market_depth_required})")
            continue

        if cmd.isdigit():
            idx = int(cmd)
            _toggle_skill(gap, removed, idx, console)
            continue

        console.print(f"[red]Comando no reconocido: '{cmd}'[/red]")

    return gap


def _render_editor(gap: GapAnalysis, removed: dict[int, SkillGap], console: Console) -> None:
    all_skills = _enumerate(gap)
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="right", width=3, style="dim")
    table.add_column("Estado", width=8)
    table.add_column("Habilidad")
    table.add_column("Severidad", style="dim")
    for idx, skill in all_skills:
        is_removed = idx in removed
        state = "[red]✗[/red]" if is_removed else "[green]✓[/green]"
        name = f"[strike]{skill.skill_name}[/strike]" if is_removed else skill.skill_name
        table.add_row(str(idx), state, name, skill.gap_severity)
    console.print()
    console.print(table)


def _toggle_skill(
    gap: GapAnalysis,
    removed: dict[int, SkillGap],
    idx: int,
    console: Console,
) -> None:
    all_skills = _enumerate(gap)
    by_idx = {i: s for i, s in all_skills}
    if idx not in by_idx:
        console.print(f"[red]Índice fuera de rango: {idx}[/red]")
        return

    skill = by_idx[idx]
    if idx in removed:
        # Restore: append back to critical_gaps (severity is preserved on the SkillGap itself)
        restored = removed.pop(idx)
        if restored.gap_severity == "critical":
            gap.critical_gaps.append(restored)
        else:
            gap.moderate_gaps.append(restored)
        console.print(f"[green]↺ Restaurado:[/green] {restored.skill_name}")
    else:
        # Remove from whichever list it lives in
        for bucket in (gap.critical_gaps, gap.moderate_gaps):
            if skill in bucket:
                bucket.remove(skill)
                removed[idx] = skill
                console.print(f"[yellow]✗ Descartado:[/yellow] {skill.skill_name}")
                return


def _parse_manual_addition(raw: str, console: Console) -> SkillGap | None:
    parts = [p.strip() for p in raw.split(",")]
    name = parts[0] if parts else ""
    depth = parts[1].lower() if len(parts) >= 2 else "intermedio"
    if not name:
        console.print("[red]Nombre vacío.[/red]")
        return None
    if depth not in _DEPTHS:
        console.print(f"[red]Profundidad inválida '{depth}'. Use: {', '.join(_DEPTHS)}[/red]")
        return None
    return SkillGap(
        skill_name=name,
        market_demand_score=0.7,
        academic_coverage_score=0.1,
        gap_severity="critical",
        notes="Agregado manualmente por el educador durante revisión.",
        market_depth_required=depth,  # type: ignore[arg-type]
    )


def _edit_title_rationale(gap: GapAnalysis, console: Console) -> GapAnalysis:
    console.print(f"\n[dim]Título actual:[/dim] {gap.proposed_course_title}")
    new_title = _prompt(console, "Nuevo título (Enter para mantener)").strip()
    if new_title:
        gap.proposed_course_title = new_title
        console.print("[green]✓ Título actualizado.[/green]")

    console.print(f"\n[dim]Justificación actual:[/dim] {gap.proposed_course_rationale}")
    new_rat = _prompt(console, "Nueva justificación (Enter para mantener)").strip()
    if new_rat:
        gap.proposed_course_rationale = new_rat
        console.print("[green]✓ Justificación actualizada.[/green]")

    return gap


def _view_skill(gap: GapAnalysis, console: Console) -> None:
    raw = _prompt(console, "Número de habilidad").strip()
    if not raw.isdigit():
        console.print(f"[red]Índice inválido: '{raw}'[/red]")
        return
    idx = int(raw)
    by_idx = {i: s for i, s in _enumerate(gap)}
    if idx not in by_idx:
        console.print(f"[red]Índice fuera de rango: {idx}[/red]")
        return

    s = by_idx[idx]
    console.print(Panel(
        f"[bold]{s.skill_name}[/bold]\n\n"
        f"Severidad:           {s.gap_severity}\n"
        f"Demanda mercado:     {s.market_demand_score:.2f}\n"
        f"Cobertura académica: {s.academic_coverage_score:.2f}\n"
        f"Profundidad pedida:  {s.market_depth_required}\n\n"
        f"[dim]Notas del agente:[/dim]\n{s.notes}",
        border_style="cyan",
    ))


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def _enumerate(gap: GapAnalysis) -> list[tuple[int, SkillGap]]:
    out: list[tuple[int, SkillGap]] = []
    i = 1
    for s in gap.critical_gaps:
        out.append((i, s)); i += 1
    for s in gap.moderate_gaps:
        out.append((i, s)); i += 1
    return out


def _prompt(console: Console, message: str) -> str:
    try:
        return console.input(f"[bold cyan]{message} ›[/bold cyan] ")
    except (EOFError, KeyboardInterrupt):
        # Non-interactive context: behave like "accept and continue"
        console.print()
        return "a"


def _default_reviewer() -> str:
    return os.environ.get("TCU_REVIEWER") or _safe_user() or "anónimo"


def _safe_user() -> str | None:
    try:
        return getpass.getuser()
    except Exception:
        return None


def _build_audit(gap: GapAnalysis, reviewer: str, skipped: bool) -> dict[str, Any]:
    accepted = [s.skill_name for s in gap.critical_gaps + gap.moderate_gaps]
    manual = [
        {"name": s.skill_name, "depth": s.market_depth_required}
        for s in gap.critical_gaps + gap.moderate_gaps
        if "Agregado manualmente" in (s.notes or "")
    ]
    return {
        "reviewer": reviewer,
        "reviewed_at": datetime.now().isoformat(timespec="seconds"),
        "skipped": skipped,
        "accepted_skills": accepted,
        "manual_additions": manual,
        "proposed_course_title": gap.proposed_course_title,
    }


def _persist_audit(sector: str, audit: dict[str, Any]) -> None:
    _AUDIT_DIR.mkdir(exist_ok=True)
    key = re.sub(r"[^\w]", "_", sector).lower()
    path = _AUDIT_DIR / f"{key}_gap_review.json"
    try:
        path.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"[Checkpoint] Audit written → {path}")
    except OSError as e:
        logger.warning(f"[Checkpoint] Failed to persist audit: {e}")
