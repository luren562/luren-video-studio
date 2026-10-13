"""运行时设置：引擎渲染帧并发、全局默认语速，可在设置页直接改并持久化。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..config import get_settings
from ..runtime_settings import save_overrides
from ..security import require_admin
from ..tts_providers import normalize_rate, rate_percent

router = APIRouter(prefix="/api/settings", dependencies=[Depends(require_admin)])


class RuntimeSettingsPayload(BaseModel):
    render_concurrency: int = Field(default=1, ge=1, le=16)
    tts_rate: int | None = Field(default=None, ge=-50, le=50)


def _current() -> dict:
    settings = get_settings()
    try:
        percent = rate_percent(settings.tts_rate)
    except ValueError:
        percent = 0
    return {"render_concurrency": int(getattr(settings, "render_concurrency", 1)),
            "tts_rate": percent}


@router.get("")
def read_settings() -> dict:
    return _current()


@router.put("")
def update_settings(payload: RuntimeSettingsPayload) -> dict:
    settings = get_settings()
    values: dict = {"render_concurrency": payload.render_concurrency}
    settings.render_concurrency = int(payload.render_concurrency)
    if payload.tts_rate is not None:
        rate = normalize_rate(payload.tts_rate)
        values["tts_rate"] = rate
        settings.tts_rate = rate
    # 缓存的是同一 Settings 对象，改属性即可对后续渲染立即生效。
    save_overrides(settings.data_dir, values)
    return _current()
