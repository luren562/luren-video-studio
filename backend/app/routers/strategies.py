from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ContentStrategy, VideoProject
from ..schemas import ContentStrategyCreate, ContentStrategyRead, ContentStrategyUpdate
from ..security import require_admin

router = APIRouter(prefix="/api/strategies", dependencies=[Depends(require_admin)])


def _payload_to_data(payload: ContentStrategyCreate) -> dict:
    """schema 用 banned_phrases，模型字段是 banned_phrases_json。"""
    data = payload.model_dump()
    data["banned_phrases_json"] = data.pop("banned_phrases", [])
    return data


@router.get("", response_model=list[ContentStrategyRead])
def list_strategies(active_only: bool = False, db: Session = Depends(get_db)) -> list[ContentStrategy]:
    stmt = select(ContentStrategy).order_by(ContentStrategy.id)
    if active_only:
        stmt = stmt.where(ContentStrategy.is_active.is_(True))
    return list(db.scalars(stmt).all())


@router.get("/{strategy_id}", response_model=ContentStrategyRead)
def get_strategy(strategy_id: int, db: Session = Depends(get_db)) -> ContentStrategy:
    strategy = db.get(ContentStrategy, strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="创作策略不存在")
    return strategy


@router.post("", response_model=ContentStrategyRead, status_code=201)
def create_strategy(payload: ContentStrategyCreate, db: Session = Depends(get_db)) -> ContentStrategy:
    if db.scalar(select(ContentStrategy).where(ContentStrategy.name == payload.name)):
        raise HTTPException(status_code=409, detail="同名创作策略已存在")
    strategy = ContentStrategy(**_payload_to_data(payload))
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return strategy


@router.patch("/{strategy_id}", response_model=ContentStrategyRead)
def update_strategy(
    strategy_id: int, payload: ContentStrategyUpdate, db: Session = Depends(get_db)
) -> ContentStrategy:
    strategy = db.get(ContentStrategy, strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="创作策略不存在")
    updated = payload.model_dump(exclude_unset=True)
    if "banned_phrases" in updated:
        updated["banned_phrases_json"] = updated.pop("banned_phrases")
    if "name" in updated and updated["name"] != strategy.name and db.scalar(
        select(ContentStrategy).where(ContentStrategy.name == updated["name"])
    ):
        raise HTTPException(status_code=409, detail="同名创作策略已存在")
    for key, value in updated.items():
        setattr(strategy, key, value)
    db.commit()
    db.refresh(strategy)
    return strategy


@router.post("/{strategy_id}/set-default", response_model=ContentStrategyRead)
def set_default(strategy_id: int, db: Session = Depends(get_db)) -> ContentStrategy:
    strategy = db.get(ContentStrategy, strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="创作策略不存在")
    for other in db.scalars(select(ContentStrategy)).all():
        other.is_default = other.id == strategy.id
    db.commit()
    db.refresh(strategy)
    return strategy


@router.delete("/{strategy_id}", status_code=204)
def delete_strategy(strategy_id: int, db: Session = Depends(get_db)) -> None:
    strategy = db.get(ContentStrategy, strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="创作策略不存在")
    # 解除被引用项目的关联，避免留下悬空外键。
    for project in db.scalars(
        select(VideoProject).where(VideoProject.strategy_id == strategy_id)
    ).all():
        project.strategy_id = None
    db.delete(strategy)
    db.commit()
