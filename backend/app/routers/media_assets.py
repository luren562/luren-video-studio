import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import MediaAsset
from ..schemas import MediaAssetRead
from ..security import require_admin

router = APIRouter(prefix="/api/media-assets", dependencies=[Depends(require_admin)])


@router.get("", response_model=list[MediaAssetRead])
def list_assets(
    source_type: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
) -> list[MediaAsset]:
    stmt = select(MediaAsset).order_by(MediaAsset.created_at.desc()).limit(limit)
    if source_type:
        stmt = stmt.where(MediaAsset.source_type == source_type)
    return list(db.scalars(stmt).all())


@router.post("", response_model=MediaAssetRead, status_code=201)
async def upload_asset(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> MediaAsset:
    settings = get_settings()
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    raw = await file.read()
    digest = hashlib.sha256(raw).hexdigest()
    suffix = Path(file.filename or "").suffix
    stored = settings.uploads_dir / f"{uuid.uuid4().hex}{suffix}"
    stored.write_bytes(raw)

    existing = db.scalar(select(MediaAsset).where(MediaAsset.sha256 == digest))
    if existing is not None:
        stored.unlink(missing_ok=True)
        return existing

    asset = MediaAsset(
        source_type="upload",
        filename=file.filename or stored.name,
        path=str(stored),
        mime=file.content_type or "",
        sha256=digest,
        size_bytes=len(raw),
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/{asset_id}/file")
def get_file(asset_id: int, db: Session = Depends(get_db)) -> FileResponse:
    asset = db.get(MediaAsset, asset_id)
    if asset is None or not asset.path or not Path(asset.path).exists():
        raise HTTPException(status_code=404, detail="素材文件不存在")
    return FileResponse(asset.path, media_type=asset.mime or "application/octet-stream")
