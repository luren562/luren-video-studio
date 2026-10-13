import json

import pytest

from app.database import SessionLocal
from app.migrations import upgrade_database
from app.models import PipelineEvent, PipelineTask, VideoProject, VideoVersion
from app.routers import stream as stream_module


@pytest.fixture(autouse=True)
def _ensure_schema():
    upgrade_database()


def _make_project(status: str, with_running_task: bool = False) -> int:
    with SessionLocal() as db:
        project = VideoProject(topic="流测试", title="流测试", lang="zh", status=status)
        db.add(project)
        db.flush()
        if with_running_task:
            task = PipelineTask(
                kind="render", resource_type="project", resource_id=project.id, status="running"
            )
            db.add(task)
            db.flush()
            db.add(PipelineEvent(task_id=task.id, level="info", message="开始渲染"))
        db.commit()
        return project.id


def test_snapshot_done_for_terminal_project():
    pid = _make_project("rendered")
    data = stream_module.snapshot(pid)
    assert data is not None
    assert data["done"] is True
    assert data["project"]["status"] == "rendered"


def test_snapshot_not_done_while_task_running():
    pid = _make_project("rendering", with_running_task=True)
    data = stream_module.snapshot(pid)
    assert data is not None
    assert data["done"] is False
    assert data["task"]["status"] == "running"
    assert data["events"][0]["message"] == "开始渲染"


def test_snapshot_includes_version_task():
    # 渲染/素材任务挂在版本上，流快照也应能看到（否则渲染期间看不到进度）
    with SessionLocal() as db:
        project = VideoProject(topic="流测试", title="流测试", lang="zh", status="rendering")
        db.add(project)
        db.flush()
        version = VideoVersion(project_id=project.id, version_number=1, spec_json={})
        db.add(version)
        db.flush()
        task = PipelineTask(
            kind="render", resource_type="version", resource_id=version.id, status="running"
        )
        db.add(task)
        db.flush()
        db.add(PipelineEvent(task_id=task.id, level="info", message="开始渲染"))
        db.commit()
        pid = project.id
    data = stream_module.snapshot(pid)
    assert data is not None
    assert data["task"] is not None and data["task"]["status"] == "running"
    assert data["events"][0]["message"] == "开始渲染"


def test_snapshot_missing_project_returns_none():
    assert stream_module.snapshot(999999) is None


def test_stream_endpoint_emits_and_closes(client, auth_headers):
    pid = _make_project("rendered")
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    token = resp.json()["access_token"]
    stream = client.get(f"/api/projects/{pid}/stream?token={token}")
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    line = [ln for ln in stream.text.splitlines() if ln.startswith("data: ")][0]
    payload = json.loads(line[len("data: "):])
    assert payload["done"] is True
    assert payload["project"]["id"] == pid


def test_stream_endpoint_rejects_bad_token(client):
    pid = _make_project("rendered")
    resp = client.get(f"/api/projects/{pid}/stream?token=not-a-real-token")
    assert resp.status_code == 401


def test_stream_endpoint_404_for_missing_project(client, auth_headers):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    token = resp.json()["access_token"]
    resp = client.get(f"/api/projects/999999/stream?token={token}")
    assert resp.status_code == 404
