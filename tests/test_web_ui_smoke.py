"""Smoke tests for the web UI: route shape, static surface, WebSocket contract.

Uses FastAPI's TestClient (Starlette under the hood) so it runs in CI without
a browser. The orchestrator is monkey-patched to a no-op so we exercise the
wire protocol — not the agents.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.web import server as srv


# ─── HTTP routes ──────────────────────────────────────────────────────────


@pytest.fixture
def client() -> TestClient:
    return TestClient(srv.app)


def test_index_serves_html(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


# IDs the JS event handlers and renderers depend on. If any of these go
# missing from index.html, app.js will silently fail at runtime.
_REQUIRED_DOM_IDS = [
    # input screen
    "form-start", "sector", "reviewer", "sector-chips", "stage-preview",
    "recent-reports", "open-archive", "toggle-advanced",
    # pipeline screen
    "stage-list", "current-status", "log", "btn-cancel", "toggle-details",
    # review screen (PR3)
    "review-sector", "review-kpis", "review-opportunity", "selection-counter",
    "sort-select", "btn-select-all", "btn-select-none",
    "skills-grid", "skills-empty",
    "manual-name", "manual-depth", "manual-note", "btn-manual-add",
    "review-sticky", "course-title", "course-rationale",
    "course-title-count", "course-rationale-count", "course-title-preview",
    "btn-accept", "btn-skip", "accept-label",
    # done screen (PR4)
    "done-sector", "done-timestamp", "quality-radar", "quality-summary",
    "report-link", "report-download", "btn-copy-link", "btn-restart",
    "related-sectors",
    # error screen (PR4)
    "error-title", "error-summary", "error-message",
    "btn-retry-same", "btn-restart-error", "btn-copy-error",
    # archive
    "archive-list", "btn-archive-back",
    # cross-cutting (PR4)
    "toast-container", "kbd-overlay", "kbd-close", "theme-toggle",
]


@pytest.mark.parametrize("dom_id", _REQUIRED_DOM_IDS)
def test_required_dom_id_present(client: TestClient, dom_id: str) -> None:
    body = client.get("/").text
    assert f'id="{dom_id}"' in body, f"index.html is missing id={dom_id!r}"


def test_static_assets_serve(client: TestClient) -> None:
    css = client.get("/static/style.css")
    assert css.status_code == 200
    assert "--brand:" in css.text  # token system from PR1+
    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert "STAGES" in js.text  # stage catalog from PR2+


def test_api_reports_returns_list(client: TestClient) -> None:
    r = client.get("/api/reports")
    assert r.status_code == 200
    body = r.json()
    assert "reports" in body
    assert isinstance(body["reports"], list)


def test_report_endpoint_rejects_path_traversal(client: TestClient) -> None:
    # The endpoint should reject anything that doesn't match the reporte_*.html pattern.
    r = client.get("/reports/../../etc/passwd")
    assert r.status_code in (400, 404)
    r = client.get("/reports/not-a-report.html")
    assert r.status_code == 400


# ─── WebSocket contract ───────────────────────────────────────────────────


class _NoopOrchestrator:
    """Stand-in that emits two stage_progress events and completes immediately."""
    _quality_scores = {"market_research": 0.9, "academic_research": 0.8}

    def __init__(self, progress=None, review_hook=None):
        self.progress = progress
        self.review_hook = review_hook

    def run(self, sector: str = "Desarrollo de Software") -> str:
        if self.progress is not None:
            self.progress.log("[cyan]🔎 mercado[/cyan]", stage_id="market")
            self.progress.log("[cyan]🎓 academia[/cyan]", stage_id="academic")
        return "/tmp/reporte_test_20260101.html"


def test_websocket_emits_stage_progress_with_stage_id(monkeypatch, client: TestClient) -> None:
    """The Phase 1.4 contract change: every stage_progress includes a stage_id
    field, and Rich [cyan]...[/cyan] markup is stripped before forwarding."""
    monkeypatch.setattr(srv, "Orchestrator", _NoopOrchestrator)
    # Reset any leftover session state from a prior test.
    srv._current_session = None

    with client.websocket_connect("/ws/run") as ws:
        ws.send_text(json.dumps({"type": "start", "sector": "Test"}))

        messages: list[dict] = []
        # Drain until we see complete (the noop orchestrator emits 2 progress + 1 complete).
        for _ in range(10):
            messages.append(ws.receive_json())
            if messages[-1].get("type") == "complete":
                break

    types = [m["type"] for m in messages]
    assert "stage_progress" in types
    assert "complete" in types

    progress_msgs = [m for m in messages if m["type"] == "stage_progress"]
    # stage_id is present on every progress message
    assert all("stage_id" in m for m in progress_msgs)
    # Rich markup is stripped
    assert all("[cyan]" not in (m["description"] or "") for m in progress_msgs)
    # The first stage emitted is market
    assert progress_msgs[0]["stage_id"] == "market"

    complete = next(m for m in messages if m["type"] == "complete")
    assert "quality_scores" in complete
    assert complete["quality_scores"]["market_research"] == 0.9


def test_websocket_rich_markup_is_stripped_from_description(monkeypatch, client: TestClient) -> None:
    """Frontend should never see Rich [color]...[/color] tags."""
    captured: list[str] = []

    class _CapturingOrchestrator(_NoopOrchestrator):
        def run(self, sector: str = "X") -> str:
            self.progress.log("[bold red]ERROR[/bold red] some message", stage_id="market")
            return "/tmp/reporte_x.html"

    monkeypatch.setattr(srv, "Orchestrator", _CapturingOrchestrator)
    srv._current_session = None

    with client.websocket_connect("/ws/run") as ws:
        ws.send_text(json.dumps({"type": "start", "sector": "X"}))
        msg = ws.receive_json()
        # First message back should be the stage_progress
        if msg["type"] == "stage_progress":
            assert "[bold red]" not in msg["description"]
            assert "[/bold red]" not in msg["description"]
            assert "ERROR some message" in msg["description"]


# ─── Review payload contract ──────────────────────────────────────────────


def test_apply_review_preserves_manual_note() -> None:
    """The PR3 feature: educator's note on a manual addition flows into SkillGap.notes."""
    from src.models.gap import GapAnalysis, SkillGap

    g = GapAnalysis(
        sector="Test",
        critical_gaps=[], moderate_gaps=[], well_covered=[],
        opportunity_statement="x",
        proposed_course_title="T",
        proposed_course_rationale="R",
    )
    r = srv._apply_review(g, {
        "skipped": False,
        "accepted_ids": [],
        "manual_additions": [{"name": "Threat modeling", "depth": "avanzado", "notes": "operator reason"}],
        "proposed_course_title": "",
        "proposed_course_rationale": "",
    })
    assert len(r.critical_gaps) == 1
    assert r.critical_gaps[0].notes == "operator reason"
    assert r.critical_gaps[0].market_depth_required == "avanzado"


def test_apply_review_manual_without_note_falls_back() -> None:
    """Backward compat: payloads from an older client without `notes` still work."""
    from src.models.gap import GapAnalysis

    g = GapAnalysis(
        sector="Test",
        critical_gaps=[], moderate_gaps=[], well_covered=[],
        opportunity_statement="x",
        proposed_course_title="T",
        proposed_course_rationale="R",
    )
    r = srv._apply_review(g, {
        "skipped": False,
        "accepted_ids": [],
        "manual_additions": [{"name": "Cloud", "depth": "intermedio"}],
    })
    assert "manualmente" in r.critical_gaps[0].notes
