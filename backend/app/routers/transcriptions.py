"""视频/音频转文稿：上传文件或视频直链 → 异步转写 → 复制/下载文稿。"""
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import PipelineTask, TranscriptionJob
from ..schemas import TranscriptionCreateUrl, TranscriptionRead, TranscriptionSummary
from ..security import require_admin, require_admin_flexible
from ..transcribe_service import cleanup_job

router = APIRouter(prefix="/api/transcriptions", dependencies=[Depends(require_admin)])
# 文稿下载直链（<a download> 带不了 Authorization 头）→ 允许 ?token=
media_router = APIRouter(prefix="/api/transcriptions")


def _normalize_language(value: str) -> str:
    value = (value or "zh").strip().lower()
    return value if value in ("zh", "en", "auto") else "zh"


def _enqueue(db: Session, job: TranscriptionJob) -> None:
    db.add(PipelineTask(
        kind="transcribe",
        resource_type="transcription",
        resource_id=job.id,
        payload_json={"job_id": job.id},
        max_attempts=1,
    ))


@router.get("", response_model=list[TranscriptionSummary])
def list_jobs(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
) -> list[TranscriptionJob]:
    stmt = select(TranscriptionJob).order_by(TranscriptionJob.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(TranscriptionJob.status == status)
    return list(db.scalars(stmt).all())


@router.get("/{job_id}", response_model=TranscriptionRead)
def get_job(job_id: int, db: Session = Depends(get_db)) -> TranscriptionJob:
    job = db.get(TranscriptionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="转文稿任务不存在")
    return job


@router.post("/upload", response_model=TranscriptionSummary, status_code=201)
async def create_from_upload(
    file: UploadFile = File(...),
    language: str = Form(default="zh"),
    title: str = Form(default=""),
    db: Session = Depends(get_db),
) -> TranscriptionJob:
    settings = get_settings()
    dest_dir = settings.uploads_dir / "transcribe"
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = file.filename or ""
    suffix = Path(filename).suffix[:10]
    dest = dest_dir / f"upload-{uuid.uuid4().hex}{suffix}"
    size = 0
    max_bytes = settings.transcribe_max_download_mb * 1024 * 1024
    try:
        with dest.open("wb") as fh:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过 {settings.transcribe_max_download_mb} MB 上限",
                    )
                fh.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="上传的文件为空")

    job = TranscriptionJob(
        title=(title.strip() or Path(filename).stem or "未命名")[:300],
        source_type="upload",
        source_ref=filename or dest.name,
        media_path=str(dest),
        language=_normalize_language(language),
        model=settings.transcribe_model,
        status="queued",
    )
    db.add(job)
    db.flush()
    _enqueue(db, job)
    db.commit()
    db.refresh(job)
    return job


@router.post("/url", response_model=TranscriptionSummary, status_code=201)
def create_from_url(payload: TranscriptionCreateUrl, db: Session = Depends(get_db)) -> TranscriptionJob:
    settings = get_settings()
    title = payload.title.strip()
    if not title:
        tail = Path(urlparse(payload.url).path).stem
        title = tail or urlparse(payload.url).netloc or "链接视频"
    job = TranscriptionJob(
        title=title[:300],
        source_type="url",
        source_ref=payload.url,
        media_path="",
        language=_normalize_language(payload.language),
        model=settings.transcribe_model,
        status="queued",
    )
    db.add(job)
    db.flush()
    _enqueue(db, job)
    db.commit()
    db.refresh(job)
    return job


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: int, db: Session = Depends(get_db)) -> None:
    job = db.get(TranscriptionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="转文稿任务不存在")
    for task in db.scalars(select(PipelineTask).where(
            PipelineTask.resource_type == "transcription",
            PipelineTask.resource_id == job_id)).all():
        db.delete(task)
    media_path = Path(job.media_path) if job.media_path else None
    db.delete(job)
    db.commit()
    cleanup_job(get_settings(), job_id)
    if media_path and media_path.is_file():
        media_path.unlink(missing_ok=True)


@media_router.get("/{job_id}/file")
def get_file(
    job_id: int,
    format: str = Query(default="txt", pattern="^(txt|srt)$"),
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_flexible),
) -> FileResponse:
    job = db.get(TranscriptionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="转文稿任务不存在")
    if not job.text.strip():
        raise HTTPException(status_code=404, detail="文稿尚未生成")
    path = job.srt_path if format == "srt" else job.text_path
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=404, detail="文稿文件不存在")
    media_type = "application/x-subrip" if format == "srt" else "text/plain; charset=utf-8"
    return FileResponse(path, media_type=media_type, filename=f"transcript-{job_id}.{format}")
