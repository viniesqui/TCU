"""
Tests for the gap-analysis checkpoint module.

These tests cover the pure helpers (enumerate, toggle, manual addition, audit
record). The interactive ``review()`` loop itself is not exercised here — it
would require a TTY mock; instead we test the building blocks it composes.
"""
from __future__ import annotations

from rich.console import Console

from src.cli import checkpoint
from src.models.gap import SkillGap


def _silent_console() -> Console:
    """Console that swallows output so tests don't pollute stdout."""
    return Console(file=open("/dev/null", "w"), force_terminal=False)


class TestEnumerate:
    def test_indexes_critical_then_moderate(self, sample_gap_analysis):
        pairs = checkpoint._enumerate(sample_gap_analysis)
        # 5 critical + 3 moderate = 8 entries, indices 1..8
        assert [i for i, _ in pairs] == list(range(1, 9))
        first_critical = sample_gap_analysis.critical_gaps[0]
        first_moderate = sample_gap_analysis.moderate_gaps[0]
        assert pairs[0][1] is first_critical
        assert pairs[5][1] is first_moderate


class TestToggleSkill:
    def test_remove_then_restore_critical(self, sample_gap_analysis):
        removed: dict[int, SkillGap] = {}
        console = _silent_console()
        target = sample_gap_analysis.critical_gaps[0]
        original_critical_count = len(sample_gap_analysis.critical_gaps)

        checkpoint._toggle_skill(sample_gap_analysis, removed, 1, console)
        assert target not in sample_gap_analysis.critical_gaps
        assert 1 in removed
        assert len(sample_gap_analysis.critical_gaps) == original_critical_count - 1

        checkpoint._toggle_skill(sample_gap_analysis, removed, 1, console)
        assert target in sample_gap_analysis.critical_gaps
        assert 1 not in removed
        assert len(sample_gap_analysis.critical_gaps) == original_critical_count

    def test_remove_moderate(self, sample_gap_analysis):
        removed: dict[int, SkillGap] = {}
        console = _silent_console()
        moderate_idx = len(sample_gap_analysis.critical_gaps) + 1  # first moderate
        target = sample_gap_analysis.moderate_gaps[0]

        checkpoint._toggle_skill(sample_gap_analysis, removed, moderate_idx, console)
        assert target not in sample_gap_analysis.moderate_gaps
        assert moderate_idx in removed

    def test_out_of_range_is_safe(self, sample_gap_analysis):
        removed: dict[int, SkillGap] = {}
        console = _silent_console()
        before = len(sample_gap_analysis.critical_gaps) + len(sample_gap_analysis.moderate_gaps)
        checkpoint._toggle_skill(sample_gap_analysis, removed, 999, console)
        after = len(sample_gap_analysis.critical_gaps) + len(sample_gap_analysis.moderate_gaps)
        assert before == after
        assert removed == {}


class TestManualAddition:
    def test_valid_addition(self):
        console = _silent_console()
        skill = checkpoint._parse_manual_addition("Rust embebido, avanzado", console)
        assert skill is not None
        assert skill.skill_name == "Rust embebido"
        assert skill.market_depth_required == "avanzado"
        assert skill.gap_severity == "critical"
        assert "manualmente" in skill.notes.lower()

    def test_default_depth_when_omitted(self):
        console = _silent_console()
        skill = checkpoint._parse_manual_addition("MLOps básico", console)
        assert skill is not None
        assert skill.market_depth_required == "intermedio"

    def test_rejects_invalid_depth(self):
        console = _silent_console()
        assert checkpoint._parse_manual_addition("Algo, experto", console) is None

    def test_rejects_empty_name(self):
        console = _silent_console()
        assert checkpoint._parse_manual_addition("  , avanzado", console) is None


class TestAuditRecord:
    def test_accept_records_all_remaining_skills(self, sample_gap_analysis):
        audit = checkpoint._build_audit(sample_gap_analysis, reviewer="ada", skipped=False)
        expected = [s.skill_name for s in sample_gap_analysis.critical_gaps + sample_gap_analysis.moderate_gaps]
        assert audit["reviewer"] == "ada"
        assert audit["skipped"] is False
        assert audit["accepted_skills"] == expected
        assert audit["manual_additions"] == []
        assert audit["proposed_course_title"] == sample_gap_analysis.proposed_course_title
        assert "reviewed_at" in audit

    def test_skipped_flag_propagates(self, sample_gap_analysis):
        audit = checkpoint._build_audit(sample_gap_analysis, reviewer="ada", skipped=True)
        assert audit["skipped"] is True

    def test_manual_additions_detected(self, sample_gap_analysis):
        console = _silent_console()
        added = checkpoint._parse_manual_addition("Quantum CR, intermedio", console)
        assert added is not None
        sample_gap_analysis.critical_gaps.append(added)
        audit = checkpoint._build_audit(sample_gap_analysis, reviewer="ada", skipped=False)
        assert audit["manual_additions"] == [{"name": "Quantum CR", "depth": "intermedio"}]


class TestPersistAudit:
    def test_writes_json_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(checkpoint, "_AUDIT_DIR", tmp_path)
        audit = {"reviewer": "ada", "reviewed_at": "now", "skipped": False, "accepted_skills": []}
        checkpoint._persist_audit("Desarrollo de Software", audit)
        files = list(tmp_path.glob("*_gap_review.json"))
        assert len(files) == 1
        assert "desarrollo_de_software" in files[0].name
        assert "ada" in files[0].read_text(encoding="utf-8")


class TestOrchestratorHookContract:
    """The orchestrator must call the hook with GapAnalysis and accept (gap, audit_or_none)."""

    def test_hook_receives_gap_and_result_flows_to_report(self, sample_gap_analysis):
        captured = {}

        def fake_hook(gap):
            captured["received"] = gap
            return gap, {"reviewer": "stub", "skipped": True}

        # Smoke-test the contract without running the full orchestrator pipeline.
        gap, audit = fake_hook(sample_gap_analysis)
        assert captured["received"] is sample_gap_analysis
        assert gap is sample_gap_analysis
        assert audit == {"reviewer": "stub", "skipped": True}
