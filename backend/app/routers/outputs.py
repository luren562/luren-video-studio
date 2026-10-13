from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import cover_config
from ..database import get_db
from ..models import RenderOutput
from ..schemas import RenderOutputRead
from ..security import require_admin, require_admin_flexible
from ..services import enqueue_task

router = APIRouter(prefix="/api/outputs", dependencies=[Depends(require_admin)])
# 媒体直链（<video>/<img>/<a download> 带不了 Authorization 头）→ 允许 ?token=
media_router = APIRouter(prefix="/api/outputs")


@router.get("", response_model=list[RenderOutputRead])
def list_outputs(
    engine: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
) -> list[RenderOutput]:
    stmt = select(RenderOutput).order_by(RenderOutput.created_at.desc()).limit(limit)
    if engine:
        stmt = stmt.where(RenderOutput.engine == engine)
    if status:
        stmt = stmt.where(RenderOutput.status == status)
    return list(db.scalars(stmt).all())


@router.get("/{output_id}", response_model=RenderOutputRead)
def get_output(output_id: int, db: Session = Depends(get_db)) -> RenderOutput:
    output = db.get(RenderOutput, output_id)
    if output is None:
        raise HTTPException(status_code=404, detail="成片不存在")
    return output


def _serve(path: str, media_type: str) -> FileResponse:
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, media_type=media_type)


@media_router.get("/{output_id}/file")
def get_file(output_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin_flexible)) -> FileResponse:
    output = db.get(RenderOutput, output_id)
    if output is None:
        raise HTTPException(status_code=404, detail="成片不存在")
    return _serve(output.file_path, "video/mp4")


@media_router.get("/{output_id}/poster")
def get_poster(output_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin_flexible)) -> FileResponse:
    output = db.get(RenderOutput, output_id)
    if output is None:
        raise HTTPException(status_code=404, detail="成片不存在")
    return _serve(output.poster_path, "image/jpeg")


@media_router.get("/{output_id}/cover")
def get_cover(output_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin_flexible)) -> FileResponse:
    output = db.get(RenderOutput, output_id)
    if output is None:
        raise HTTPException(status_code=404, detail="成片不存在")
    if not output.cover_path:
        raise HTTPException(status_code=404, detail="AI 封面尚未生成")
    media = "image/png" if output.cover_path.lower().endswith(".png") else "image/jpeg"
    return _serve(output.cover_path, media)


@router.post("/{output_id}/cover", response_model=RenderOutputRead)
def regenerate_cover(output_id: int, db: Session = Depends(get_db)) -> RenderOutput:
    """手动生成/重新生成 AI 主题封面（使用设置页的全局封面模型配置）。"""
    output = db.get(RenderOutput, output_id)
    if output is None:
        raise HTTPException(status_code=404, detail="成片不存在")
    if not cover_config.is_configured(db):
        raise HTTPException(status_code=422, detail="尚未配置 AI 主题封面模型，请先到「设置」填写")
    output.cover_status = "queued"
    output.cover_error = ""
    enqueue_task(db, kind="cover", resource_type="output", resource_id=output.id,
                 payload={"output_id": output.id}, max_attempts=2)
    db.commit()
    db.refresh(output)
    return output

