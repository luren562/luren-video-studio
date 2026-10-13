"""Pipeline Worker：轮询 PipelineTask 队列并执行。

单机思路：一个 worker 线程，串行处理。项目创建即入队 `agent_film`，
由 opencode headless 运行器在工作区内制作并交付成片。
"""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger
from sqlalchemy import func, select, update, or_
from sqlalchemy.orm import Session

from .ai_client import AIError
from .agent_runtime import JobContext
from .agent_support import AgentCancelled, AgentError, AgentStopped
from .config import get_settings
from .database import SessionLocal
from .models import (PipelineEvent, PipelineTask, RenderOutput,
                     TranscriptionJob, VideoProject, VideoVersion)
from .services import mark_task_cancelled

RETRYABLE = {"timeout", "rate_limit", "provider_error"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def add_event(db: Session, task: PipelineTask, level: str, message: str, data: dict | None = None) -> None:
    db.add(
        PipelineEvent(
            task_id=task.id, level=level, message=message, data_json=data or {}
        )
    )


def _maybe_enqueue_cover(db: Session, output: RenderOutput) -> None:
    """出片后按全局封面配置登记 AI 主题封面任务（幂等，每个成片一张）。"""
    settings = get_settings()
    if not getattr(settings, "cover_enabled", True):
        return
    from . import cover_config
    if not cover_config.is_configured(db):
        return
    from .services import enqueue_task

    enqueue_task(db, kind="cover", resource_type="output", resource_id=output.id,
                 payload={"output_id": output.id}, idempotency_key=f"cover:{output.id}", max_attempts=2)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def handle_agent_film(db: Session, task: PipelineTask) -> dict:
    """agent 路径：opencode headless 驱动，在工作区内自由制作并交付成片。"""
    from .agent_opencode import run_agent_opencode as runner

    project = db.get(VideoProject, task.resource_id)
    if project is None:
        raise ValueError(f"项目不存在：{task.resource_id}")

    project.status = "rendering"
    project.error_message = ""
    # 同一任务重试/服务重启继续同一版本；“重新生成”仍创建新的任务和版本。
    payload = dict(task.payload_json or {})
    version = db.get(VideoVersion, payload["agent_version_id"]) if payload.get("agent_version_id") else None
    if version is not None and version.project_id != project.id:
        raise ValueError("任务检查点所属项目不一致")
    if version is None:
        next_number = (db.scalar(select(func.max(VideoVersion.version_number)).where(
            VideoVersion.project_id == project.id)) or 0) + 1
        version = VideoVersion(project_id=project.id, version_number=next_number,
                               model_id=project.model_id,
                               spec_json={"title": project.title, "topic": project.topic, "agent": True},
                               generation_meta_json={"mode": "agent"}, created_by=project.created_by)
        db.add(version)
        db.flush()
        task.payload_json = {**payload, "agent_version_id": version.id}
    project.current_version_id = version.id
    add_event(db, task, "info", f"开始/继续 Agent 造片 v{version.version_number}")
    db.commit()

    task_id = task.id

    def emit(level: str, message: str, data: dict | None = None) -> None:
        add_event(db, task, level, message, data or {})
        task.lease_expires_at = utcnow() + timedelta(seconds=max(get_settings().pipeline_lease_seconds,
                                                               get_settings().agent_render_timeout_seconds + 60))
        db.commit()

    def progress(current: int, total: int) -> None:
        task.progress_current = current
        task.progress_total = total
        db.commit()

    def cancelled() -> bool:
        # scalar 查询绕过 identity map；另一 HTTP 请求可以实时取消本次任务。
        return bool(db.scalar(select(PipelineTask.cancel_requested).where(PipelineTask.id == task_id)))

    ctx = JobContext(emit=emit, progress=progress, cancelled=cancelled)
    # 用户显式续跑（retry 接口打标记）：一次性消费，仅对审片/墙钟停止授予 +1 渲染额度。
    grant_render = bool(payload.get('user_resume'))
    if grant_render:
        # 基于当前 payload 合并，避免丢掉本次运行刚写入的 agent_version_id。
        task.payload_json = {**(task.payload_json or {}), 'user_resume': False}
        db.commit()
    output = runner(db, project, version, ctx, grant_render=grant_render)
    _maybe_enqueue_cover(db, output)
    task.result_json = {"output_id": output.id, "file": output.file_path, "draft": output.status == "draft"}
    db.commit()
    if output.status == "draft":
        stop = (version.generation_meta_json or {}).get('agent_run', {}).get('stop_reason') or {}
        raise AgentStopped(stop.get('code', 'review_blocker'), project.error_message or "草稿已保存，尚未通过验收")
    return {"output_id": output.id, "file": output.file_path}


def handle_transcribe(db: Session, task: PipelineTask) -> dict:
    """视频/音频转文稿：抽音轨 + faster-whisper，异步执行避免阻塞 HTTP。"""
    from .transcribe_service import TranscribeError, transcribe_job

    job = db.get(TranscriptionJob, task.resource_id)
    if job is None:
        raise ValueError(f"转文稿任务不存在：{task.resource_id}")
    job.status = "running"
    job.error_message = ""
    add_event(db, task, "info", f"开始转文稿：{job.title}")
    db.commit()

    def renew() -> None:
        task.lease_expires_at = utcnow() + timedelta(seconds=max(
            get_settings().pipeline_lease_seconds, get_settings().transcribe_timeout_seconds + 60))

    def emit(message: str) -> None:
        add_event(db, task, "info", message)
        renew()
        db.commit()

    def progress(current: int, total: int) -> None:
        task.progress_current = current
        task.progress_total = total
        renew()
        db.commit()

    try:
        result = transcribe_job(
            get_settings(),
            job_id=job.id,
            media_path=Path(job.media_path) if job.media_path else None,
            source_type=job.source_type,
            source_ref=job.source_ref,
            language=job.language,
            title=job.title,
            emit=emit,
            progress=progress,
        )
    except TranscribeError as exc:
        job.status = "failed"
        job.error_message = str(exc)
        db.commit()
        raise
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error_message = str(exc)
        db.commit()
        raise

    job.status = "succeeded"
    job.title = result.get("title") or job.title
    job.duration_sec = result.get("duration_sec")
    job.text = result.get("text", "")
    job.segments_json = result.get("segments", [])
    job.text_path = result.get("text_path", "")
    job.srt_path = result.get("srt_path", "")
    job.error_message = ""
    db.commit()
    return {"job_id": job.id, "segments": len(job.segments_json), "text_path": job.text_path}


def handle_cover(db: Session, task: PipelineTask) -> dict:
    """AI 主题封面：用全局封面配置（独立于生产模型）生图并落盘到成片同目录。"""
    from . import cover_config
    from .cover_service import generate_cover

    output = db.get(RenderOutput, task.resource_id)
    if output is None:
        raise ValueError(f"成片不存在：{task.resource_id}")
    project = db.get(VideoProject, output.project_id)
    config = cover_config.resolved(db)
    if config is None:
        output.cover_status = "failed"
        output.cover_error = "尚未配置 AI 主题封面模型（请到「设置」填写）"
        db.commit()
        raise AgentError("cover_config", output.cover_error)

    output.cover_status = "running"
    output.cover_error = ""
    add_event(db, task, "info", f"生成 AI 主题封面：{config['model']}")
    db.commit()

    def renew() -> None:
        task.lease_expires_at = utcnow() + timedelta(
            seconds=max(get_settings().pipeline_lease_seconds, get_settings().cover_timeout_seconds + 60))

    renew()
    db.commit()
    try:
        path = generate_cover(project, output, config, settings=get_settings())
    except Exception as exc:  # noqa: BLE001 - 归一化到任务失败，保留错误供 UI 展示
        output.cover_status = "failed"
        output.cover_error = str(exc)[:500]
        db.commit()
        raise
    output.cover_path = str(path)
    output.cover_status = "ready"
    output.cover_error = ""
    db.commit()
    return {"cover": str(path), "model": config["model"]}


HANDLERS: dict[str, Callable[[Session, PipelineTask], dict]] = {
    "agent_film": handle_agent_film,
    "transcribe": handle_transcribe,
    "cover": handle_cover,
}


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
class PipelineWorker:
    def __init__(self, owner: str = "worker-1"):
        self.owner = owner
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._recovered = False

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="pipeline-worker", daemon=True)
        self._thread.start()
        logger.info("Pipeline worker 已启动")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        settings = get_settings()
        if not self._recovered and settings.pipeline_reset_running_on_start:
            self._reset_stale_running()
            self._recovered = True
        while not self._stop.is_set():
            try:
                worked = self.run_once()
            except Exception:  # noqa: BLE001
                logger.exception("worker 循环异常")
                worked = False
            if not worked:
                self._stop.wait(settings.pipeline_poll_seconds)

    def _reset_stale_running(self) -> None:
        """单机单 worker：启动时把任何残留 running 任务重新入队（上次进程被杀留下的）。"""
        with SessionLocal() as db:
            rows = db.scalars(select(PipelineTask).where(PipelineTask.status == "running", or_(
                PipelineTask.lease_expires_at.is_(None), PipelineTask.lease_expires_at < utcnow()))).all()
            for task in rows:
                task.status = "queued"
                task.lease_owner = None
                task.lease_expires_at = None
                add_event(db, task, "warning", "服务重启，未完成任务重新入队")
            if rows:
                db.commit()
                logger.warning(f"重置 {len(rows)} 个残留 running 任务")

    # -- task handling -----------------------------------------------------
    def _recover_expired(self, db: Session) -> None:
        now = utcnow()
        expired = db.scalars(
            select(PipelineTask).where(
                PipelineTask.status == "running",
                PipelineTask.lease_expires_at.is_not(None),
                PipelineTask.lease_expires_at < now,
            )
        ).all()
        for task in expired:
            task.status = "queued"
            task.lease_owner = None
            task.lease_expires_at = None
            add_event(db, task, "warning", "任务租约过期，重新入队")
        if expired:
            db.commit()

    def run_once(self) -> bool:
        settings = get_settings()
        with SessionLocal() as db:
            self._recover_expired(db)
            task = db.scalar(
                select(PipelineTask)
                .where(PipelineTask.status == "queued")
                .order_by(PipelineTask.created_at)
                .limit(1)
            )
            if task is None:
                return False

            claimed = db.execute(update(PipelineTask).where(PipelineTask.id == task.id,
                PipelineTask.status == 'queued').values(status='running', attempts=PipelineTask.attempts + 1))
            if claimed.rowcount != 1:
                db.rollback()
                return False
            db.refresh(task)
            task.started_at = task.started_at or utcnow()
            task.lease_owner = self.owner
            task.lease_expires_at = utcnow() + timedelta(seconds=settings.pipeline_lease_seconds)
            add_event(db, task, "info", f"领取任务（第 {task.attempts} 次尝试）")
            db.commit()
            task_id = task.id
            kind = task.kind

        handler = HANDLERS.get(kind)
        with SessionLocal() as db:
            task = db.get(PipelineTask, task_id)
            if task is None:
                logger.warning(f"任务 {task_id} 在执行前已被删除，跳过")
                return True
            if handler is None:
                self._fail(db, task, "obsolete_kind", f"未知或已下线的任务类型：{kind}", retry=False)
                return True
            try:
                result = handler(db, task)
                task.status = "succeeded"
                task.result_json = result or {}
                task.finished_at = utcnow()
                task.lease_owner = None
                task.lease_expires_at = None
                add_event(db, task, "info", "任务完成", result or {})
                db.commit()
            except AgentCancelled as exc:
                mark_task_cancelled(db, task, str(exc))
                add_event(db, task, "info", str(exc))
                db.commit()
            except AIError as exc:
                self._fail(db, task, exc.error_type, exc.message, retry=exc.error_type in RETRYABLE)
            except AgentError as exc:
                self._fail(db, task, exc.error_code, str(exc), retry=False)
            except Exception as exc:  # noqa: BLE001
                logger.exception("任务执行失败")
                self._fail(db, task, "internal_error", str(exc), retry=False, detail=traceback.format_exc())
        return True

    def _fail(
        self,
        db: Session,
        task: PipelineTask,
        error_code: str,
        message: str,
        *,
        retry: bool,
        detail: str = "",
    ) -> None:
        if error_code == "cancelled":
            mark_task_cancelled(db, task, message)
            add_event(db, task, "info", message)
            db.commit()
            return
        task.error_code = error_code
        task.error_message = message
        if retry and task.attempts < task.max_attempts:
            task.status = "queued"
            task.lease_owner = None
            task.lease_expires_at = None
            add_event(db, task, "warning", f"任务失败将重试：{message}", {"error_code": error_code})
        else:
            task.status = "failed"
            task.finished_at = utcnow()
            task.lease_owner = None
            task.lease_expires_at = None
            add_event(db, task, "error", f"任务失败：{message}", {"error_code": error_code, "detail": detail[:2000]})
            if task.resource_type == "project" and task.resource_id:
                project = db.get(VideoProject, task.resource_id)
                if project is not None and project.status in ("generating", "rendering"):
                    project.status = "failed"
                    project.error_message = message
        db.commit()
