"""Queue lifecycle regressions; all records live in the temporary test database."""
import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import PipelineEvent, PipelineTask, RenderOutput, TranscriptionJob, VideoProject
from app.routers.stream import snapshot
from app.worker import PipelineWorker


@pytest.fixture
def queued_project(client, auth_headers):
    response = client.post("/api/projects", json={"topic": "任务生命周期测试"}, headers=auth_headers)
    assert response.status_code == 201, response.text
    project = response.json()
    yield project
    client.delete(f"/api/projects/{project['id']}", headers=auth_headers)


def test_regenerate_rejects_active_task_without_changing_project(client, auth_headers, queued_project):
    project = queued_project
    response = client.post(f"/api/projects/{project['id']}/regenerate",
                           json={"topic": "不应保存的修改"}, headers=auth_headers)
    assert response.status_code == 409
    detail = client.get(f"/api/projects/{project['id']}", headers=auth_headers).json()
    assert detail["topic"] == project["topic"]
    with SessionLocal() as db:
        tasks = db.scalars(select(PipelineTask).where(
            PipelineTask.resource_type == "project", PipelineTask.resource_id == project["id"])).all()
        assert len(tasks) == 1


def test_cancel_then_retry_keeps_project_and_stream_in_sync(client, auth_headers, queued_project):
    project = queued_project
    task_id = project["latest_task_id"]
    response = client.post(f"/api/tasks/{task_id}/cancel", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["finished_at"] is not None
    cancelled = snapshot(project["id"])
    assert cancelled["project"]["status"] == "needs_attention"
    assert cancelled["done"] is True

    response = client.post(f"/api/tasks/{task_id}/retry", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["finished_at"] is None
    retried = snapshot(project["id"])
    assert retried["project"]["status"] == "generating"
    assert retried["project"]["error_message"] == ""
    assert retried["done"] is False


def test_completed_task_cannot_be_cancelled(client, auth_headers, queued_project):
    task_id = queued_project["latest_task_id"]
    with SessionLocal() as db:
        db.get(PipelineTask, task_id).status = "succeeded"
        db.commit()
    response = client.post(f"/api/tasks/{task_id}/cancel", headers=auth_headers)
    assert response.status_code == 422
    with SessionLocal() as db:
        assert db.get(PipelineTask, task_id).cancel_requested is False


def test_delete_project_removes_output_tasks_and_events(client, auth_headers, queued_project):
    project_id = queued_project["id"]
    with SessionLocal() as db:
        output = RenderOutput(project_id=project_id, version_id=0)
        db.add(output)
        db.flush()
        task = PipelineTask(kind="cover", resource_type="output", resource_id=output.id)
        db.add(task)
        db.flush()
        event = PipelineEvent(task_id=task.id, message="封面排队")
        db.add(event)
        db.commit()
        output_id, task_id, event_id = output.id, task.id, event.id
    response = client.delete(f"/api/projects/{project_id}", headers=auth_headers)
    assert response.status_code == 204
    with SessionLocal() as db:
        assert db.get(VideoProject, project_id) is None
        assert db.get(RenderOutput, output_id) is None
        assert db.get(PipelineTask, task_id) is None
        assert db.get(PipelineEvent, event_id) is None


def test_worker_cancellation_is_cancelled_instead_of_failed(client, queued_project):
    with SessionLocal() as db:
        project = db.get(VideoProject, queued_project["id"])
        project.status = "rendering"
        task = db.get(PipelineTask, queued_project["latest_task_id"])
        task.status = "running"
        PipelineWorker()._fail(db, task, "cancelled", "任务已取消", retry=False)
        assert task.status == "cancelled"
        assert task.finished_at is not None
        assert project.status == "needs_attention"
    assert snapshot(queued_project["id"])["done"] is True


@pytest.mark.parametrize("kind", ["transcribe", "cover"])
def test_queued_cancel_and_retry_sync_related_resource(client, auth_headers, queued_project, kind):
    with SessionLocal() as db:
        if kind == "transcribe":
            resource = TranscriptionJob(title="取消转文稿")
            resource_type = "transcription"
        else:
            resource = RenderOutput(project_id=queued_project["id"], version_id=0, cover_status="queued")
            resource_type = "output"
        db.add(resource)
        db.flush()
        resource_id = resource.id
        task = PipelineTask(kind=kind, resource_type=resource_type, resource_id=resource_id)
        db.add(task)
        db.commit()
        task_id = task.id
    try:
        assert client.post(f"/api/tasks/{task_id}/cancel", headers=auth_headers).status_code == 200
        with SessionLocal() as db:
            cancelled = db.get(type(resource), resource_id)
            assert (cancelled.status if kind == "transcribe" else cancelled.cover_status) == "failed"
        assert client.post(f"/api/tasks/{task_id}/retry", headers=auth_headers).status_code == 200
        with SessionLocal() as db:
            retried = db.get(type(resource), resource_id)
            assert (retried.status if kind == "transcribe" else retried.cover_status) == "queued"
    finally:
        with SessionLocal() as db:
            db.delete(db.get(PipelineTask, task_id))
            db.delete(db.get(type(resource), resource_id))
            db.commit()
