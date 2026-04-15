from datetime import timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from cliplab_backend.main import app, log_repository, repository
from cliplab_backend.schemas import TaskRecord
from cliplab_backend.storage.db import utcnow


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


def test_clear_history_keeps_running_tasks_and_clears_logs():
    client = TestClient(app)
    repository.clear_task_history()
    log_repository.clear_logs()

    now = utcnow().astimezone(timezone.utc)
    finished = TaskRecord(
        id=str(uuid4()),
        type="download",
        status="succeeded",
        progress=100,
        input="finished-task",
        outputPath="/tmp/finished.mp4",
        createdAt=now,
        updatedAt=now,
        metadata={},
    )
    running = TaskRecord(
        id=str(uuid4()),
        type="remove_watermark",
        status="running",
        progress=48,
        input="running-task",
        outputPath=None,
        createdAt=now,
        updatedAt=now,
        metadata={},
    )
    repository.save(finished)
    repository.save(running)
    log_repository.create(level="info", source="task", message="demo log")

    response = client.post("/api/history/clear")

    assert response.status_code == 200
    assert response.json()["clearedTasks"] >= 1
    assert response.json()["clearedLogs"] >= 1
    task_ids = {task.id for task in repository.list()}
    assert finished.id not in task_ids
    assert running.id in task_ids
    assert log_repository.list() == []

    repository.save(
        running.model_copy(update={"status": "failed", "progress": 100, "updatedAt": utcnow().astimezone(timezone.utc)})
    )
    repository.clear_task_history()
