from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import PipelineEvent, PipelineTask, RenderOutput, TranscriptionJob, VideoProject
from ..schemas import PipelineEventRead, PipelineTaskRead
from ..security import require_admin
from ..services import mark_task_cancelled

router = APIRouter(prefix="/api/tasks", dependencies=[Depends(require_admin)])


@router.get("", response_model=list[PipelineTaskRead])
def list_tasks(
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    resource_id: int | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
) -> list[PipelineTask]:
    stmt = select(PipelineTask).order_by(PipelineTask.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(PipelineTask.status == status)
    if kind:
        stmt = stmt.where(PipelineTask.kind == kind)
    if resource_id:
        stmt = stmt.where(PipelineTask.resource_id == resource_id)
    return list(db.scalars(stmt).all())


@router.get("/{task_id}", response_model=PipelineTaskRead)
def get_task(task_id: int, db: Session = Depends(get_db)) -> PipelineTask:
    task = db.get(PipelineTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/{task_id}/events", response_model=list[PipelineEventRead])
def get_events(task_id: int, db: Session = Depends(get_db)) -> list[PipelineEvent]:
    return list(
        db.scalars(
            select(PipelineEvent)
            .where(PipelineEvent.task_id == task_id)
            .order_by(PipelineEvent.id)
        ).all()
    )


@router.post("/{task_id}/retry", response_model=PipelineTaskRead)
def retry_task(task_id: int, db: Session = Depends(get_db)) -> PipelineTask:
    task = db.get(PipelineTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in ("failed", "cancelled"):
        raise HTTPException(status_code=422, detail="只有失败或取消的任务可以重试")
    if task.kind == 'agent_film':
        other = db.scalar(select(PipelineTask.id).where(PipelineTask.id != task.id,
            PipelineTask.kind == 'agent_film', PipelineTask.resource_id == task.resource_id,
            PipelineTask.resource_type == task.resource_type,
            PipelineTask.status.in_(['queued', 'running'])))
        if other:
            raise HTTPException(status_code=409, detail='该项目已有排队或运行中的 Agent 任务')
    changed = db.execute(update(PipelineTask).where(PipelineTask.id == task.id,
        PipelineTask.status.in_(['failed', 'cancelled'])).values(status='queued'))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail='任务已经被其他请求续跑')
    db.refresh(task)
    task.error_code = ""
    task.error_message = ""
    task.attempts = 0
    task.cancel_requested = False
    task.started_at = None
    task.finished_at = None
    task.lease_owner = None
    task.lease_expires_at = None
    task.progress_current = 0
    task.progress_total = 0
    if task.kind == "agent_film":
        # 显式用户续跑：仅当上次因审片/墙钟停止时，本次额外放行 1 次整片渲染额度。
        task.payload_json = {**(task.payload_json or {}), "user_resume": True}
        project = db.get(VideoProject, task.resource_id)
        if project is not None:
            project.status = "generating"
            project.error_message = ""
    elif task.kind == "transcribe":
        job = db.get(TranscriptionJob, task.resource_id)
        if job is not None:
            job.status = "queued"
            job.error_message = ""
    elif task.kind == "cover":
        output = db.get(RenderOutput, task.resource_id)
        if output is not None:
            output.cover_status = "queued"
            output.cover_error = ""
    db.commit()
    db.refresh(task)
    return task


@router.post("/{task_id}/cancel", response_model=PipelineTaskRead)
def cancel_task(task_id: int, db: Session = Depends(get_db)) -> PipelineTask:
    task = db.get(PipelineTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in {"queued", "running"}:
        raise HTTPException(status_code=422, detail="只有排队或执行中的任务可以取消")
    if task.status == "queued":
        # Worker 也会原子领取 queued 任务；只有取消先成功时才立即结束它。
        changed = db.execute(update(PipelineTask).where(
            PipelineTask.id == task.id, PipelineTask.status == "queued"
        ).values(status="cancelled"))
        if changed.rowcount == 1:
            mark_task_cancelled(db, task)
            db.add(PipelineEvent(task_id=task.id, level="info", message="任务已取消"))
        else:
            db.refresh(task)
            if task.status != "running":
                raise HTTPException(status_code=409, detail="任务状态已变化，请刷新后重试")
            task.cancel_requested = True
    else:
        task.cancel_requested = True
    db.commit()
    db.refresh(task)
    return task
