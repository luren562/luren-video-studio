from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .models import (
    AIProvider,
    PipelineTask,
    RenderOutput,
    TranscriptionJob,
    VideoProject,
    VideoScene,
    VideoVersion,
    utcnow,
)
from .schemas import (
    AIProviderRead,
    VideoProjectDetail,
    VideoSceneRead,
    VideoVersionRead,
)


def enqueue_task(
    db: Session,
    *,
    kind: str,
    resource_type: str,
    resource_id: int | None,
    payload: dict | None = None,
    idempotency_key: str | None = None,
    max_attempts: int = 2,
) -> PipelineTask:
    if idempotency_key:
        existing = db.scalar(
            select(PipelineTask).where(PipelineTask.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing
    task = PipelineTask(
        kind=kind,
        resource_type=resource_type,
        resource_id=resource_id,
        payload_json=payload or {},
        idempotency_key=idempotency_key,
        max_attempts=max_attempts,
    )
    db.add(task)
    db.flush()
    return task


def mark_task_cancelled(db: Session, task: PipelineTask, message: str = "任务已取消") -> None:
    """Keep the task and its project in a terminal state in the same transaction."""
    task.status = "cancelled"
    task.cancel_requested = True
    task.finished_at = utcnow()
    task.lease_owner = None
    task.lease_expires_at = None
    task.error_code = "cancelled"
    task.error_message = message
    if task.kind == "agent_film" and task.resource_type == "project":
        project = db.get(VideoProject, task.resource_id)
        if project is not None and project.status in {"generating", "rendering", "failed", "needs_attention"}:
            project.status = "needs_attention"
            project.error_message = message
    elif task.kind == "transcribe" and task.resource_type == "transcription":
        job = db.get(TranscriptionJob, task.resource_id)
        if job is not None:
            job.status = "failed"
            job.error_message = message
    elif task.kind == "cover" and task.resource_type == "output":
        output = db.get(RenderOutput, task.resource_id)
        if output is not None:
            output.cover_status = "failed"
            output.cover_error = message


def provider_to_read(provider: AIProvider) -> AIProviderRead:
    return AIProviderRead(
        id=provider.id,
        name=provider.name,
        base_url=provider.base_url,
        has_api_key=bool(provider.encrypted_api_key),
        is_active=provider.is_active,
        created_at=provider.created_at,
    )


def version_to_read(db: Session, version: VideoVersion) -> VideoVersionRead:
    scenes = db.scalars(
        select(VideoScene)
        .where(VideoScene.version_id == version.id)
        .order_by(VideoScene.position)
    ).all()
    return VideoVersionRead(
        id=version.id,
        project_id=version.project_id,
        version_number=version.version_number,
        model_id=version.model_id,
        prompt_version=version.prompt_version,
        spec_json=version.spec_json,
        generation_meta_json=version.generation_meta_json,
        validation_json=version.validation_json,
        created_at=version.created_at,
        scenes=[VideoSceneRead.model_validate(s) for s in scenes],
    )


def project_to_detail(db: Session, project: VideoProject) -> VideoProjectDetail:
    current = None
    if project.current_version_id:
        version = db.get(VideoVersion, project.current_version_id)
        if version is not None:
            current = version_to_read(db, version)

    # 渲染/素材任务挂在版本上（resource_type="version"），若只看 project 任务，
    # 渲染期间项目详情拿不到最新任务与事件日志，这里一并纳入该项目的版本任务。
    version_ids = select(VideoVersion.id).where(VideoVersion.project_id == project.id)
    latest_task = db.scalar(
        select(PipelineTask)
        .where(
            or_(
                and_(PipelineTask.resource_type == "project", PipelineTask.resource_id == project.id),
                and_(PipelineTask.resource_type == "version", PipelineTask.resource_id.in_(version_ids)),
            )
        )
        .order_by(PipelineTask.created_at.desc())
        .limit(1)
    )
    detail = VideoProjectDetail.model_validate(project)
    detail.current_version = current
    detail.latest_task_id = latest_task.id if latest_task else None
    if current is not None:
        from .schemas import AgentRunSummary
        summary = (current.generation_meta_json or {}).get("agent_run")
        detail.agent_summary = AgentRunSummary.model_validate(summary) if summary else None
    return detail
