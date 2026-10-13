"""AI 主题封面的全局模型配置（独立于生产模型列表 ai_models）。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import cover_config
from ..ai_client import AIError, image_generation
from ..database import get_db
from ..schemas import CoverConfigRead, CoverConfigUpdate
from ..security import require_admin

router = APIRouter(prefix="/api/cover", dependencies=[Depends(require_admin)])


@router.get("/config", response_model=CoverConfigRead)
def read_config(db: Session = Depends(get_db)) -> dict:
    return cover_config.to_read(cover_config.get_row(db))


@router.put("/config", response_model=CoverConfigRead)
def update_config(payload: CoverConfigUpdate, db: Session = Depends(get_db)) -> dict:
    row = cover_config.save(db, base_url=payload.base_url, model=payload.model,
                            size=payload.size, api_key=payload.api_key)
    db.commit()
    db.refresh(row)
    return cover_config.to_read(row)


@router.post("/test")
def test_config(db: Session = Depends(get_db)) -> dict:
    """用当前配置真实生成一张小图，验证网关连通性与模型名。"""
    cfg = cover_config.resolved(db)
    if cfg is None:
        raise HTTPException(status_code=422, detail="请先填写并保存生图 Base URL 与模型名")
    try:
        result = image_generation(base_url=cfg["base_url"], api_key=cfg["api_key"],
                                  model=cfg["model"], prompt="一张极简黑白线条测试图",
                                  size=cfg["size"] or None)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=f"{exc.error_type}: {exc.message}") from exc
    return {"ok": True, "model": result.model, "latency_ms": result.latency_ms}
