from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai_client import AIError, chat_completion
from ..database import get_db
from ..models import AIModel, AIProvider, ContentStrategy, VideoProject, VideoVersion
from ..schemas import (
    AIModelCreate,
    AIModelRead,
    AIModelUpdate,
    AIProviderCreate,
    AIProviderRead,
    AIProviderUpdate,
    ProviderTestResult,
)
from ..security import decrypt_string, encrypt_string, require_admin
from ..services import provider_to_read

router = APIRouter(prefix="/api/ai", dependencies=[Depends(require_admin)])


class ProviderTestRequest(BaseModel):
    model_id: str | None = None


@router.get("/providers", response_model=list[AIProviderRead])
def list_providers(db: Session = Depends(get_db)) -> list[AIProviderRead]:
    providers = db.scalars(select(AIProvider).order_by(AIProvider.id)).all()
    return [provider_to_read(p) for p in providers]


@router.post("/providers", response_model=AIProviderRead, status_code=201)
def create_provider(payload: AIProviderCreate, db: Session = Depends(get_db)) -> AIProviderRead:
    if db.scalar(select(AIProvider).where(AIProvider.name == payload.name)):
        raise HTTPException(status_code=409, detail="同名供应商已存在")
    provider = AIProvider(
        name=payload.name,
        base_url=payload.base_url,
        encrypted_api_key=encrypt_string(payload.api_key) if payload.api_key else "",
        is_active=payload.is_active,
    )
    db.add(provider)
    db.flush()
    # 顺带建文本模型（可选），否则测试 / 生成会报「该供应商没有文本模型」
    if payload.default_model_id.strip():
        db.add(
            AIModel(
                provider_id=provider.id,
                name=payload.default_model_id.strip(),
                model_id=payload.default_model_id.strip(),
                capability="text",
            )
        )
    db.commit()
    db.refresh(provider)
    return provider_to_read(provider)


@router.patch("/providers/{provider_id}", response_model=AIProviderRead)
def update_provider(
    provider_id: int, payload: AIProviderUpdate, db: Session = Depends(get_db)
) -> AIProviderRead:
    provider = db.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    if payload.base_url is not None:
        provider.base_url = payload.base_url
    if payload.api_key:  # 空字符串表示保留原值
        provider.encrypted_api_key = encrypt_string(payload.api_key)
    if payload.is_active is not None:
        provider.is_active = payload.is_active
    db.commit()
    db.refresh(provider)
    return provider_to_read(provider)


@router.delete("/providers/{provider_id}", status_code=204)
def delete_provider(provider_id: int, db: Session = Depends(get_db)) -> None:
    provider = db.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    model_ids = [m.id for m in db.scalars(select(AIModel).where(AIModel.provider_id == provider_id)).all()]
    if model_ids:
        db.query(VideoProject).filter(VideoProject.model_id.in_(model_ids)).update(
            {VideoProject.model_id: None}, synchronize_session=False
        )
        db.query(ContentStrategy).filter(ContentStrategy.default_model_id.in_(model_ids)).update(
            {ContentStrategy.default_model_id: None}, synchronize_session=False
        )
        db.query(VideoVersion).filter(VideoVersion.model_id.in_(model_ids)).update(
            {VideoVersion.model_id: None}, synchronize_session=False
        )
        db.query(AIModel).filter(AIModel.provider_id == provider_id).delete(synchronize_session=False)
    db.delete(provider)
    db.commit()


@router.post("/providers/{provider_id}/test", response_model=ProviderTestResult)
def test_provider(
    provider_id: int, payload: ProviderTestRequest | None = None, db: Session = Depends(get_db)
) -> ProviderTestResult:
    provider = db.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    model_id = payload.model_id if payload and payload.model_id else None
    if not model_id:
        model = db.scalar(
            select(AIModel)
            .where(AIModel.provider_id == provider.id, AIModel.capability == "text")
            .order_by(AIModel.id)
        )
        model_id = model.model_id if model else ""
    if not model_id:
        return ProviderTestResult(
            ok=False,
            error_type="configuration",
            message=f"供应商「{provider.name}」下没有文本模型：请在下方「模型」区为该供应商添加一个 model_id（DeepSeek 可用 deepseek-flash / deepseek-v4-pro）",
        )
    try:
        result = chat_completion(
            base_url=provider.base_url,
            api_key=decrypt_string(provider.encrypted_api_key) if provider.encrypted_api_key else "",
            model=model_id,
            messages=[{"role": "user", "content": "ping"}],
            temperature=0,
            max_tokens=8,
        )
        return ProviderTestResult(ok=True, model=result.model, latency_ms=result.latency_ms)
    except AIError as exc:
        return ProviderTestResult(ok=False, error_type=exc.error_type, message=exc.message)


@router.get("/models", response_model=list[AIModelRead])
def list_models(db: Session = Depends(get_db)) -> list[AIModel]:
    return list(db.scalars(select(AIModel).order_by(AIModel.id)).all())


@router.post("/models", response_model=AIModelRead, status_code=201)
def create_model(payload: AIModelCreate, db: Session = Depends(get_db)) -> AIModel:
    if db.get(AIProvider, payload.provider_id) is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    if db.scalar(
        select(AIModel).where(
            AIModel.provider_id == payload.provider_id, AIModel.model_id == payload.model_id
        )
    ):
        raise HTTPException(status_code=409, detail="该供应商下已存在相同 model_id")
    model = AIModel(**payload.model_dump())
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


@router.patch("/models/{model_id}", response_model=AIModelRead)
def update_model(model_id: int, payload: AIModelUpdate, db: Session = Depends(get_db)) -> AIModel:
    model = db.get(AIModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(model, key, value)
    db.commit()
    db.refresh(model)
    return model


@router.delete("/models/{model_id}", status_code=204)
def delete_model(model_id: int, db: Session = Depends(get_db)) -> None:
    model = db.get(AIModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    db.query(VideoProject).filter(VideoProject.model_id == model_id).update(
        {VideoProject.model_id: None}, synchronize_session=False
    )
    db.query(ContentStrategy).filter(ContentStrategy.default_model_id == model_id).update(
        {ContentStrategy.default_model_id: None}, synchronize_session=False
    )
    db.query(VideoVersion).filter(VideoVersion.model_id == model_id).update(
        {VideoVersion.model_id: None}, synchronize_session=False
    )
    db.delete(model)
    db.commit()
