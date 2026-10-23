from fastapi.testclient import TestClient

from app.main import app


def test_health_ok() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_index_responds_html() -> None:
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "Rekomendasi Pembimbing Skripsi" in response.text
