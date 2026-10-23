from fastapi.testclient import TestClient


def test_health_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["phase"] == 5


def test_index_responds_html(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Rekomendasi Pembimbing Skripsi" in response.text
