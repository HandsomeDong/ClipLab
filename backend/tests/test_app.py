from fastapi.testclient import TestClient

from cliplab_backend.main import app


def test_healthcheck():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_server_info_shape():
    client = TestClient(app)
    response = client.get("/api/server-info")
    assert response.status_code == 200
    payload = response.json()
    assert "appName" in payload
    assert "localApiUrl" in payload
    assert "remoteSubmitUrls" in payload
    assert "remoteWebUrls" in payload


def test_logs_endpoint_returns_list():
    client = TestClient(app)
    response = client.get("/api/logs")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
