"""Authenticated voice catalogue and on-demand short previews."""
import hashlib
import threading

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..config import get_settings
from ..narration import synthesize_narration
from ..security import require_admin
from ..tts_providers import TtsError, available_voices, normalize_rate, resolve_voice

router = APIRouter(prefix="/api/tts", dependencies=[Depends(require_admin)])
_preview_lock = threading.Lock()
PREVIEW_TEXT = "你好，这是中文配音试听。让清晰自然的声音，为你的故事增添色彩。"


@router.get("/voices")
def list_voices() -> list[dict]:
    settings = get_settings()
    default = resolve_voice(settings.tts_provider, None, settings)
    return [{**voice, "is_default": voice["id"] == default or voice.get("shortName") == default}
            for voice in available_voices()]


class PreviewRequest(BaseModel):
    voice: str = Field(min_length=1, max_length=120)
    rate: int | None = Field(default=None, ge=-50, le=50)


@router.post("/preview")
def preview(payload: PreviewRequest):
    settings = get_settings()
    try:
        voice = resolve_voice(settings.tts_provider, payload.voice, settings)
    except TtsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if settings.tts_provider == "manual":
        raise HTTPException(status_code=422, detail="人工旁白请试听上传的音频")
    # 试听按所选语速合成；保持 synthesize_narration 调用签名不变。
    preview_settings = (settings.model_copy(update={"tts_rate": normalize_rate(payload.rate)})
                        if payload.rate is not None else settings)
    key = hashlib.sha256(
        f"{settings.tts_provider}|{voice}|{preview_settings.tts_rate}|{PREVIEW_TEXT}".encode()
    ).hexdigest()
    out = settings.assets_dir / "tts_previews" / f"{key}.mp3"
    # Concurrent preview clicks must not remove a FileResponse's in-flight file.
    with _preview_lock:
        if not out.is_file():
            try:
                synthesize_narration(PREVIEW_TEXT, out, preview_settings, voice=voice, allow_fallback=False)
            except TtsError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FileResponse(out, media_type="audio/mpeg", filename="voice-preview.mp3")
