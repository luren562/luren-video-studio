from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..engine_registry import ENGINES
from ..models import VideoStyle
from ..schemas import VideoStyleCreate, VideoStyleRead, VideoStyleUpdate
from ..security import require_admin
from ..video_skills import validate_skill_config

router = APIRouter(prefix="/api/styles", dependencies=[Depends(require_admin)])


@router.get("/engines")
def list_engines() -> list[dict]:
    return [
        {
            "key": e.key,
            "display_name": e.display_name,
            "description": e.description,
            "aspect": e.aspect,
            "lang": e.lang,
            "default_duration_sec": e.default_duration_sec,
            "gates": e.gates,
            "needs_voiceover": e.needs_voiceover,
            "needs_assets": e.needs_assets,
            "needs_review_agent": e.needs_review_agent,
        }
        for e in ENGINES.values()
    ]


@router.get("", response_model=list[VideoStyleRead])
def list_styles(db: Session = Depends(get_db)) -> list[VideoStyle]:
    return list(db.scalars(select(VideoStyle).order_by(VideoStyle.id)).all())


@router.post("", response_model=VideoStyleRead, status_code=201)
def create_style(payload: VideoStyleCreate, db: Session = Depends(get_db)) -> VideoStyle:
    try:
        validate_skill_config(payload.engine_config_json)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.engine not in ENGINES:
        raise HTTPException(status_code=422, detail=f"未知引擎：{payload.engine}")
    if db.scalar(select(VideoStyle).where(VideoStyle.name == payload.name)):
        raise HTTPException(status_code=409, detail="同名风格档已存在")
    style = VideoStyle(**payload.model_dump())
    db.add(style)
    db.commit()
    db.refresh(style)
    return style


@router.patch("/{style_id}", response_model=VideoStyleRead)
def update_style(
    style_id: int, payload: VideoStyleUpdate, db: Session = Depends(get_db)
) -> VideoStyle:
    style = db.get(VideoStyle, style_id)
    if style is None:
        raise HTTPException(status_code=404, detail="风格档不存在")
    updated = payload.model_dump(exclude_unset=True)
    if "engine_config_json" in updated:
        try:
            validate_skill_config(updated["engine_config_json"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if "name" in updated and updated["name"] != style.name and db.scalar(select(VideoStyle).where(VideoStyle.name == updated["name"])):
        raise HTTPException(status_code=409, detail="同名风格档已存在")
    for key, value in updated.items():
        setattr(style, key, value)
    db.commit()
    db.refresh(style)
    return style


@router.post("/{style_id}/set-default", response_model=VideoStyleRead)
def set_default(style_id: int, db: Session = Depends(get_db)) -> VideoStyle:
    style = db.get(VideoStyle, style_id)
    if style is None:
        raise HTTPException(status_code=404, detail="风格档不存在")
    for other in db.scalars(select(VideoStyle)).all():
        other.is_default = other.id == style.id
    db.commit()
    db.refresh(style)
    return style
