import pytest
import json
import shutil
from pathlib import Path
from fastapi.testclient import TestClient
from src.web import server
from src import database

@pytest.fixture
def clean_saved_runs_dir():
    # Save original directory
    orig_dir = server._SAVED_RUNS_DIR
    temp_dir = Path("temp_saved_runs_test")
    temp_dir.mkdir(exist_ok=True)
    server._SAVED_RUNS_DIR = temp_dir
    yield temp_dir
    # Cleanup temp directory
    shutil.rmtree(temp_dir, ignore_errors=True)
    server._SAVED_RUNS_DIR = orig_dir

def test_saved_runs_api_flow(clean_saved_runs_dir):
    client = TestClient(server.app)
    
    # 1. Initially it should return empty runs
    res = client.get("/api/saved-runs")
    assert res.status_code == 200
    assert res.json() == {"runs": []}
    
    # 2. Seed some dummy data in DB
    database.init_db()
    sector = "Test Sector DevOps"
    industry_demand = {"demands": ["docker", "kubernetes"]}
    academic_landscape = {"universities": ["UCR", "TEC"]}
    gap_analysis = {
        "sector": sector,
        "critical_gaps": [],
        "moderate_gaps": [],
        "proposed_course_title": "Curso Test",
        "proposed_course_rationale": "Rationale Test"
    }
    
    # Save gap report to DB
    report_id = database.save_gap_report(
        sector=sector,
        industry_demand=industry_demand,
        academic_landscape=academic_landscape,
        gap_analysis=gap_analysis,
        approved_by="tester",
        approved_at="2026-01-01"
    )
    
    # Save syllabus
    syllabus_id = database.save_syllabus(
        gap_report_id=report_id,
        course_title="Curso Test",
        course_code="TCU-001",
        credits=3,
        hours_per_week=10,
        learning_objectives=[{"description": "Aprender K8s"}],
        bibliography=["Libro A"],
        approved_by="tester",
        approved_at="2026-01-01"
    )
    
    # Save weekly content
    database.save_weekly_content(
        syllabus_id=syllabus_id,
        week_number=1,
        title="Semana 1",
        activity_type="proyecto",
        reading_material="<h3>Lectura 1</h3>",
        assignment_prompt="Tarea 1"
    )
    
    # 3. Create dummy cache file
    cache_dir = Path("stage_cache")
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / "test_sector_devops_market_research.json"
    cache_file.write_text(json.dumps({"dummy": "cache_val"}), encoding="utf-8")
    
    try:
        # 4. Save the run via API
        res_save = client.post("/api/saved-runs/save", json={
            "sector": sector,
            "name": "DevOps Demo"
        })
        assert res_save.status_code == 200
        data_save = res_save.json()
        assert data_save["status"] == "success"
        filename = data_save["filename"]
        assert filename == "devops_demo.json"
        
        # 5. List runs - should show the newly saved run
        res_list = client.get("/api/saved-runs")
        assert res_list.status_code == 200
        runs = res_list.json()["runs"]
        assert len(runs) == 1
        assert runs[0]["filename"] == "devops_demo.json"
        assert runs[0]["sector"] == sector
        assert runs[0]["has_syllabus"] is True
        assert runs[0]["has_readings"] is True
        
        # 6. Delete all rows from DB and remove cache file manually to test LOAD
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM gap_reports;")
        conn.commit()
        conn.close()
        
        if cache_file.exists():
            cache_file.unlink()
            
        # Verify empty
        report_check = database.get_gap_report(sector)
        assert report_check is None
        assert not cache_file.exists()
        
        # 7. Load saved run via API
        res_load = client.post("/api/saved-runs/load", json={"filename": filename})
        assert res_load.status_code == 200
        assert res_load.json()["status"] == "success"
        
        # Verify restored database rows
        restored_report = database.get_gap_report(sector)
        assert restored_report is not None
        assert restored_report["sector"] == sector
        
        # Verify restored syllabus
        restored_syllabus = database.get_syllabus_by_gap(restored_report["id"])
        assert restored_syllabus is not None
        assert restored_syllabus["course_title"] == "Curso Test"
        
        # Verify restored weekly contents
        restored_weeks = database.get_weekly_contents(restored_syllabus["id"])
        assert len(restored_weeks) == 1
        assert restored_weeks[0]["title"] == "Semana 1"
        assert restored_weeks[0]["reading_material"] == "<h3>Lectura 1</h3>"
        
        # Verify restored cache files
        assert cache_file.exists()
        assert json.loads(cache_file.read_text(encoding="utf-8")) == {"dummy": "cache_val"}
        
        # 8. Delete saved run via API
        res_delete = client.post("/api/saved-runs/delete", json={"filename": filename})
        assert res_delete.status_code == 200
        assert res_delete.json() == {"status": "success"}
        
        # List runs - should be empty again
        res_list_end = client.get("/api/saved-runs")
        assert res_list_end.json() == {"runs": []}
        
    finally:
        # Cleanup cache file
        if cache_file.exists():
            cache_file.unlink()

def test_bypass_and_force_rebuild(clean_saved_runs_dir):
    from unittest.mock import patch, MagicMock
    from src.models.market import IndustryDemand
    from src.models.academic import AcademicLandscape
    from src.models.gap import GapAnalysis
    from src.models.course_design import StudyPlan, LearningObjective, LearningActivity, Evaluator, EvaluationCriteria
    
    client = TestClient(server.app)
    database.init_db()
    
    sector = "Bypass Test Sector"
    
    # Setup mock returns
    mock_demand = IndustryDemand(
        sector=sector,
        top_skills=[],
        job_postings_sampled=[],
        market_sources=[],
        research_date="2026-01-01",
        summary="Summary test"
    )
    mock_academic = AcademicLandscape(
        curricula_sampled=[],
        all_skills_covered=[],
        research_date="2026-01-01",
        summary="Academic test"
    )
    mock_gap = GapAnalysis(
        sector=sector,
        critical_gaps=[],
        moderate_gaps=[],
        well_covered=[],
        opportunity_statement="Oppy",
        proposed_course_title="Curso Bypass",
        proposed_course_rationale="Rationale",
        proposed_course_depth="intermedio"
    )
    mock_syllabus = StudyPlan(
        course_title="Curso Bypass",
        course_code="TCU-BYP",
        credits=3,
        hours_per_week=10,
        total_weeks=2,
        target_audience="Estudiantes",
        prerequisites=[],
        learning_objectives=[LearningObjective(bloom_level="comprender", description="Obj 1")],
        weekly_schedule=[
            LearningActivity(week=1, title="S1", activity_type="lectura", description="Desc 1", estimated_hours=3, learning_objectives_addressed=[0]),
            LearningActivity(week=2, title="S2", activity_type="proyecto", description="Desc 2", estimated_hours=3, learning_objectives_addressed=[0])
        ],
        evaluator=Evaluator(evaluation_components=[EvaluationCriteria(component="Proyecto", weight_percent=100.0, rubric_items=["Crit 1"])]),
        bibliography=["Bib 1"]
    )
    
    # Clean database first
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM gap_reports WHERE sector = ?", (sector,))
    conn.commit()
    conn.close()
    
    # Ensure no pre-existing saved run file
    sector_key = server._get_sector_key(sector)
    saved_run_file = clean_saved_runs_dir / f"{sector_key}.json"
    if saved_run_file.exists():
        saved_run_file.unlink()

    # MOCK the Orchestrator and ReadingAgent methods
    with patch("src.agents.orchestrator.Orchestrator.run_research") as mock_run_research, \
         patch("src.agents.orchestrator.Orchestrator.run_course_design") as mock_run_course_design, \
         patch("src.agents.reading_agent.ReadingAgent.generate_reading") as mock_generate_reading:
         
        mock_run_research.return_value = (mock_demand, mock_academic, mock_gap)
        mock_run_course_design.return_value = mock_syllabus
        mock_generate_reading.return_value = '{"reading_material": "Lectura IA", "assignment_prompt": "Tarea IA"}'
        
        # Login first to get authenticated cookie & bearer token
        login_res = client.post("/api/login", json={"username": "admin", "password": "1234"})
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # --- A. TEST RESEARCH ENDPOINT ---
        
        # First call: No DB, No Saved Run -> Should call orchestrator
        res1 = client.post("/api/research", json={"sector": sector, "force_rebuild": False}, headers=headers)
        assert res1.status_code == 200
        assert mock_run_research.call_count == 1
        
        mock_run_research.reset_mock()
        
        # Second call: Now in DB, force_rebuild = False -> Should NOT call orchestrator (bypass!)
        res2 = client.post("/api/research", json={"sector": sector, "force_rebuild": False}, headers=headers)
        assert res2.status_code == 200
        assert mock_run_research.call_count == 0
        
        # Third call: Now in DB, force_rebuild = True -> Should call orchestrator!
        res3 = client.post("/api/research", json={"sector": sector, "force_rebuild": True}, headers=headers)
        assert res3.status_code == 200
        assert mock_run_research.call_count == 1
        
        mock_run_research.reset_mock()
        
        # --- B. TEST COURSE-DESIGN ENDPOINT ---
        
        # Get the gap report ID
        report = database.get_gap_report(sector)
        assert report is not None
        gap_report_id = report["id"]
        
        # First call: No syllabus in DB -> Should call orchestrator course design
        res_cd1 = client.post("/api/course-design", json={"gap_report_id": gap_report_id, "force_rebuild": False}, headers=headers)
        assert res_cd1.status_code == 200
        assert mock_run_course_design.call_count == 1
        
        mock_run_course_design.reset_mock()
        
        # Second call: Now in DB, force_rebuild = False -> Should NOT call orchestrator (bypass!)
        res_cd2 = client.post("/api/course-design", json={"gap_report_id": gap_report_id, "force_rebuild": False}, headers=headers)
        assert res_cd2.status_code == 200
        assert mock_run_course_design.call_count == 0
        
        # Third call: Now in DB, force_rebuild = True -> Should call orchestrator!
        res_cd3 = client.post("/api/course-design", json={"gap_report_id": gap_report_id, "force_rebuild": True}, headers=headers)
        assert res_cd3.status_code == 200
        assert mock_run_course_design.call_count == 1
        
        mock_run_course_design.reset_mock()
        
        # --- C. TEST GENERATE-READING ENDPOINT ---
        
        syllabus = database.get_syllabus_by_gap(gap_report_id)
        assert syllabus is not None
        syllabus_id = syllabus["id"]
        
        # First call: No reading in DB -> Should call reading agent
        res_gr1 = client.post("/api/generate-reading", json={"syllabus_id": syllabus_id, "week_number": 1, "force_rebuild": False}, headers=headers)
        assert res_gr1.status_code == 200
        assert mock_generate_reading.call_count == 1
        
        mock_generate_reading.reset_mock()
        
        # Second call: Now in DB, force_rebuild = False -> Should NOT call reading agent (bypass!)
        res_gr2 = client.post("/api/generate-reading", json={"syllabus_id": syllabus_id, "week_number": 1, "force_rebuild": False}, headers=headers)
        assert res_gr2.status_code == 200
        assert mock_generate_reading.call_count == 0
        
        # Third call: Now in DB, force_rebuild = True -> Should call reading agent!
        res_gr3 = client.post("/api/generate-reading", json={"syllabus_id": syllabus_id, "week_number": 1, "force_rebuild": True}, headers=headers)
        assert res_gr3.status_code == 200
        assert mock_generate_reading.call_count == 1

