import pytest
from fastapi.testclient import TestClient
from src.fwd_loader import get_fwd_academic_landscape, get_fwd_raw_data, create_custom_academic_landscape
from src.web.server import app, SECRET_KEY, ALGORITHM
import jwt
import datetime

def test_fwd_raw_data_and_landscape():
    raw = get_fwd_raw_data()
    assert "FWD Costa Rica" in raw.get("institution", "")
    assert raw.get("duration_weeks") == 13
    assert len(raw.get("all_skills_covered", [])) >= 20

    landscape = get_fwd_academic_landscape()
    assert len(landscape.curricula_sampled) == 1
    curr = landscape.curricula_sampled[0]
    assert "FWD Costa Rica" in curr.university
    assert len(curr.courses) >= 10
    assert "react" in landscape.all_skills_covered
    assert "vibe-coding" in landscape.all_skills_covered

def test_custom_academic_landscape():
    custom = create_custom_academic_landscape(
        program_title="Curso de Ciberseguridad",
        institution="ONG Ejemplo",
        skills=["linux", "wireshark", "ethical-hacking"]
    )
    assert custom.curricula_sampled[0].degree_name == "Curso de Ciberseguridad"
    assert "linux" in custom.all_skills_covered

def test_api_curriculum_endpoints():
    client = TestClient(app)
    
    # Generate test auth token
    exp = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    token = jwt.encode({"username": "VinicioPrueba", "role": "researcher", "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. GET /api/curriculum/fwd
    res_fwd = client.get("/api/curriculum/fwd", headers=headers)
    assert res_fwd.status_code == 200
    data_fwd = res_fwd.json()
    assert "FWD Costa Rica" in data_fwd["institution"]

    # 2. POST /api/curriculum/upload
    res_up = client.post("/api/curriculum/upload", headers=headers, json={
        "title": "Bootcamp Web",
        "institution": "Tech Academy",
        "text": "• HTML5 y CSS3\n• JavaScript Avanzado\n• React y Redux\n• Node.js y Express"
    })
    assert res_up.status_code == 200
    data_up = res_up.json()
    assert data_up["status"] == "success"
    assert data_up["total_skills"] >= 3
