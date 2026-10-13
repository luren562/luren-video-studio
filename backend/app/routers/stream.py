"""SSE 实时进度通道（批次 E）。

浏览器原生 EventSource 不能带 `Authorization` 头，故本通道用 `?token=` 查询参数
校验 JWT。事件流按项目维度推送「项目状态 + 最新任务 + 事件日志」，终态即关闭。

事件负载（`data:` 单行 JSON）：
`{"project": {...}, "task": {...}|null, "events": [...], "done": bool}`
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, or_, select

from ..database import SessionLocal
from ..models import PipelineEvent, PipelineTask, VideoProject, VideoVersion
from ..security import verify_token

router = APIRouter(prefix="/api")

TERMINAL_PROJECT = {"rendered", "completed", "needs_attention", "failed"}
ACTIVE_TASK = {"queued", "running"}
POLL_SECONDS = 1.0
MAX_SECONDS = 3600.0


def _project_dict(project: VideoProject, agent_summary: dict | None = None) -> dict:
    return {
        "id": project.id,
        "title": project.title,
        "topic": project.topic,
        "status": project.status,
        "current_version_id": project.current_version_id,
        "error_message": project.error_message,
        "agent_summary": agent_summary,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


def _task_dict(task: PipelineTask) -> dict:
    return {
        "id": task.id,
        "kind": task.kind,
        "resource_type": task.resource_type,
        "resource_id": task.resource_id,
        "status": task.status,
        "attempts": task.attempts,
        "error_code": task.error_code,
        "error_message": task.error_message,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def snapshot(project_id: int) -> dict | None:
    """读取一次项目进度快照；项目不存在返回 None。"""
    with SessionLocal() as db:
        project = db.get(VideoProject, project_id)
        if project is None:
            return None
        agent_summary = None
        if project.current_version_id:
            version = db.get(VideoVersion, project.current_version_id)
            if version is not None:
                agent_summary = (version.generation_meta_json or {}).get("agent_run")
        version_ids = select(VideoVersion.id).where(VideoVersion.project_id == project_id)
        task = db.scalar(
            select(PipelineTask)
            .where(
                or_(
                    and_(PipelineTask.resource_type == "project", PipelineTask.resource_id == project_id),
                    and_(PipelineTask.resource_type == "version", PipelineTask.resource_id.in_(version_ids)),
                )
            )
            .order_by(PipelineTask.created_at.desc())
            .limit(1)
        )
        events = []
        if task is not None:
            events = [
                {
                    "id": e.id,
                    "level": e.level,
                    "message": e.message,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in db.scalars(
                    select(PipelineEvent).where(PipelineEvent.task_id == task.id).order_by(PipelineEvent.id)
                ).all()
            ]
        done = (
            project.status in TERMINAL_PROJECT
            and (task is None or task.status not in ACTIVE_TASK)
        )
        return {"project": _project_dict(project, agent_summary), "task": _task_dict(task) if task else None,
                "events": events, "done": done}


@router.get("/projects/{project_id}/stream")
async def stream_project(
    project_id: int,
    request: Request,
    token: str = Query(default=""),
) -> StreamingResponse:
    verify_token(token)
    if snapshot(project_id) is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    async def gen():
        waited = 0.0
        while waited < MAX_SECONDS:
            if await request.is_disconnected():
                break
            data = snapshot(project_id)
            if data is None:
                break
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            if data["done"]:
                break
            waited += POLL_SECONDS
            await asyncio.sleep(POLL_SECONDS)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
