"""
Integration tests for the web server's WebSocket pipeline.

Stubs the orchestrator so we can drive the full progress → review → complete
flow without making any API calls.
"""
from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.web import server


@pytest.fixture(autouse=True)
def _reset_session():
    """Each test starts with no active session."""
    server._current_session = None
    yield
    server._current_session = None


def _fake_orchestrator_factory(sample_gap_analysis):
    """Build a stub Orchestrator class that exercises progress + review hook."""

    class _FakeOrchestrator:
        def __init__(self, progress=None, review_hook=None):
            self.progress = progress
            self.review_hook = review_hook
            self._quality_scores = {}

        def run(self, sector: str):
            # Stage 1
            self.progress.log("🔎 Investigando mercado laboral...")
            self._quality_scores["market_research"] = 0.85
            # Stage 2
            self.progress.log("🎓 Investigando oferta académica...")
            self._quality_scores["academic_research"] = 0.78
            # Stage 3
            self.progress.log("📊 Analizando brecha educativa...")
            # Review hook
            if self.review_hook is not None:
                gap, audit = self.review_hook(sample_gap_analysis)
                assert audit is not None
            # Stage 4-6
            self.progress.log("📝 Diseñando plan de estudios...")
            self.progress.log("📄 Generando reporte HTML...")
            return "output/reporte_test_20260101_000000.html"

    return _FakeOrchestrator


def test_http_index_serves_html():
    client = TestClient(server.app)
    res = client.get("/")
    assert res.status_code == 200
    assert "TCU" in res.text


def test_http_static_files_served():
    client = TestClient(server.app)
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_http_reports_endpoint_validates_filename():
    client = TestClient(server.app)
    # Wrong prefix (would also fail prefix check) → 400
    assert client.get("/reports/passwd.html").status_code == 400
    # Wrong extension → 400
    assert client.get("/reports/reporte_test.txt").status_code == 400
    # Valid prefix but missing file → 404
    assert client.get("/reports/reporte_does_not_exist.html").status_code == 404
    # Encoded traversal that DOES reach the route is rejected by the prefix check.
    # (starlette normalizes literal '../' before routing, so we use a name that contains '..')
    assert client.get("/reports/..reporte_x.html").status_code == 400


def test_ws_rejects_non_start_message():
    client = TestClient(server.app)
    with client.websocket_connect("/ws/run") as ws:
        ws.send_json({"type": "garbage"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "start" in msg["message"].lower()


def test_ws_full_pipeline_with_review(sample_gap_analysis):
    """Drive the full flow: start → progress → review_request → review_response → complete."""
    client = TestClient(server.app)
    Fake = _fake_orchestrator_factory(sample_gap_analysis)

    with patch.object(server, "Orchestrator", Fake):
        with client.websocket_connect("/ws/run") as ws:
            ws.send_json({"type": "start", "sector": "Test Sector", "reviewer": "tester"})

            progress_count = 0
            review_seen = False
            completed = False
            for _ in range(20):
                msg = ws.receive_json()
                if msg["type"] == "stage_progress":
                    progress_count += 1
                elif msg["type"] == "review_request":
                    review_seen = True
                    # Accept all critical, drop all moderate, add one manual.
                    accepted = [f"c{i}" for i in range(len(msg["gap_analysis"]["critical_gaps"]))]
                    ws.send_json({
                        "type": "review_response",
                        "payload": {
                            "skipped": False,
                            "accepted_ids": accepted,
                            "manual_additions": [{"name": "Manual Skill X", "depth": "avanzado"}],
                            "proposed_course_title": "Curso editado en test",
                            "proposed_course_rationale": "Razón editada",
                            "audit": {"reviewer": "tester", "skipped": False, "accepted_skills": [], "manual_additions": []},
                        },
                    })
                elif msg["type"] == "complete":
                    completed = True
                    assert msg["report_path"].startswith("reporte_")
                    assert "market_research" in msg["quality_scores"]
                    break
                elif msg["type"] == "error":
                    pytest.fail(f"Pipeline errored: {msg['message']}")

    assert progress_count >= 3, "Should have streamed several stage_progress messages"
    assert review_seen, "Review request should have been emitted"
    assert completed, "Pipeline should have completed"


def test_ws_skip_review_path(sample_gap_analysis):
    """The 'skipped' review path returns the gap analysis unchanged."""
    client = TestClient(server.app)
    Fake = _fake_orchestrator_factory(sample_gap_analysis)

    with patch.object(server, "Orchestrator", Fake):
        with client.websocket_connect("/ws/run") as ws:
            ws.send_json({"type": "start", "sector": "Test", "reviewer": None})
            for _ in range(20):
                msg = ws.receive_json()
                if msg["type"] == "review_request":
                    ws.send_json({"type": "review_response", "payload": {"skipped": True}})
                elif msg["type"] == "complete":
                    return
                elif msg["type"] == "error":
                    pytest.fail(msg["message"])
    pytest.fail("did not complete")


def test_apply_review_drops_unchecked_skills(sample_gap_analysis):
    """Unit test the _apply_review pure helper."""
    payload = {
        "skipped": False,
        "accepted_ids": ["c0", "c2"],  # Keep two critical, drop the rest
        "manual_additions": [{"name": "Added Skill", "depth": "intermedio"}],
        "proposed_course_title": "New Title",
        "proposed_course_rationale": "New rationale",
    }
    result = server._apply_review(sample_gap_analysis, payload)
    # 2 kept critical + 1 manual = 3 critical
    assert len(result.critical_gaps) == 3
    assert any(s.skill_name == "Added Skill" for s in result.critical_gaps)
    assert len(result.moderate_gaps) == 0  # none in accepted_ids
    assert result.proposed_course_title == "New Title"


def test_apply_review_skipped_returns_unchanged(sample_gap_analysis):
    payload = {"skipped": True}
    result = server._apply_review(sample_gap_analysis, payload)
    assert result is sample_gap_analysis


def test_apply_review_rejects_invalid_manual_depth(sample_gap_analysis):
    payload = {
        "skipped": False,
        "accepted_ids": [],
        "manual_additions": [{"name": "Bad", "depth": "expert"}],
        "proposed_course_title": sample_gap_analysis.proposed_course_title,
        "proposed_course_rationale": sample_gap_analysis.proposed_course_rationale,
    }
    result = server._apply_review(sample_gap_analysis, payload)
    # Invalid depth filtered out
    assert all(s.skill_name != "Bad" for s in result.critical_gaps)
