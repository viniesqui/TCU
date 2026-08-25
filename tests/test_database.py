import os
from pathlib import Path
import pytest
from src import database


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch, tmp_path):
    """Point database to a temporary DB path for each test."""
    test_db = tmp_path / "test_database.db"
    monkeypatch.setattr(database, "DB_PATH", test_db)
    database.init_db()
    yield
    if test_db.exists():
        os.remove(test_db)


def test_init_db():
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()

    assert "users" in tables
    assert "gap_reports" in tables
    assert "syllabi" in tables
    assert "weekly_contents" in tables
    assert "submissions" in tables


def test_save_and_get_gap_report():
    demand = {"sector": "Test", "top_skills": []}
    landscape = {"curricula_sampled": []}
    analysis = {"critical_gaps": []}

    report_id = database.save_gap_report(
        sector="Test Sector",
        industry_demand=demand,
        academic_landscape=landscape,
        gap_analysis=analysis,
        approved_by="test_user",
        approved_at="2026-06-04"
    )

    assert report_id > 0

    report = database.get_gap_report("Test Sector")
    assert report is not None
    assert report["sector"] == "Test Sector"
    assert report["industry_demand"] == demand
    assert report["approved_by"] == "test_user"


def test_save_and_get_syllabus():
    report_id = database.save_gap_report("Test", {}, {}, {})
    syllabus_id = database.save_syllabus(
        gap_report_id=report_id,
        course_title="Test Course",
        course_code="TC-101",
        credits=3,
        hours_per_week=9.0,
        learning_objectives=[{"bloom_level": "recordar", "description": "obj"}],
        bibliography=["ref1"],
        approved_by="approver1",
        approved_at="2026-06-04"
    )

    assert syllabus_id > 0

    syllabus = database.get_syllabus_by_gap(report_id)
    assert syllabus is not None
    assert syllabus["course_title"] == "Test Course"
    assert syllabus["learning_objectives"] == [{"bloom_level": "recordar", "description": "obj"}]


def test_weekly_content_and_submissions():
    report_id = database.save_gap_report("Test", {}, {}, {})
    syllabus_id = database.save_syllabus(report_id, "Title", "Code", 3, 9.0, [], [])

    database.save_weekly_content(
        syllabus_id=syllabus_id,
        week_number=1,
        title="Week 1 Introduction",
        activity_type="lectura",
        reading_material="Content text",
        assignment_prompt="Answer this question",
        points=10
    )

    contents = database.get_weekly_contents(syllabus_id)
    assert len(contents) == 1
    assert contents[0]["title"] == "Week 1 Introduction"

    content_id = contents[0]["id"]
    database.save_submission(
        weekly_content_id=content_id,
        student_id="student_1",
        submitted_text="My answer content",
        submitted_at="2026-06-04T16:00:00"
    )

    submissions = database.get_submissions("student_1")
    assert len(submissions) == 1
    assert submissions[0]["submitted_text"] == "My answer content"
    assert submissions[0]["week_title"] == "Week 1 Introduction"
