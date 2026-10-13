"""视频/音频转文稿：直链下载 → ffmpeg 抽音轨 → faster-whisper 转写。

与 TTS 管线解耦：只负责把一段媒体转成「纯文本 + 句级时间轴 + SRT」，
供用户复制为补充资料。转写较慢，统一走 PipelineTask(kind="transcribe") 异步执行。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
import wave
from pathlib import Path
from urllib.parse import urlparse

import httpx
from loguru import logger

from .config import Settings
from .toolchain import ensure_tool_paths

SAMPLE_RATE = 16000
_CHUNK = 1024 * 1024


class TranscribeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _ffmpeg(settings: Settings) -> str:
    ensure_tool_paths()
    return settings.ffmpeg_binary or "ffmpeg"


def _ffprobe(settings: Settings) -> str:
    ensure_tool_paths()
    return str(Path(settings.ffmpeg_binary or "ffmpeg").with_name(
        "ffprobe.exe" if os.name == "nt" else "ffprobe"))


def probe_media(settings: Settings, path: Path) -> dict:
    try:
        result = subprocess.run(
            [_ffprobe(settings), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", timeout=60, check=True,
        )
        data = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise TranscribeError("probe-failed", "无法解析该媒体文件，请确认是有效的视频/音频") from exc
    streams = data.get("streams", [])
    duration = 0.0
    for stream in streams:
        try:
            duration = max(duration, float(stream.get("duration") or 0))
        except (TypeError, ValueError):
            pass
    try:
        duration = max(duration, float(data.get("format", {}).get("duration") or 0))
    except (TypeError, ValueError):
        pass
    return {
        "duration": duration,
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "has_video": any(s.get("codec_type") == "video" for s in streams),
    }


def download_direct_url(settings: Settings, url: str) -> Path:
    """下载用户提供的视频直链到 uploads 目录（仅 http/https，限制体积）。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise TranscribeError("bad-url", "仅支持 http/https 视频直链")
    dest_dir = settings.uploads_dir / "transcribe"
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(parsed.path).suffix
    if len(suffix) > 8 or not re.fullmatch(r"\.[A-Za-z0-9]+", suffix or ""):
        suffix = ".mp4"
    dest = dest_dir / f"url-{uuid.uuid4().hex}{suffix}"
    max_bytes = settings.transcribe_max_download_mb * 1024 * 1024
    timeout = httpx.Timeout(connect=20.0, read=300.0, write=120.0, pool=120.0)
    written = 0
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=timeout) as response:
            response.raise_for_status()
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise TranscribeError("too-large", f"视频超过 {settings.transcribe_max_download_mb} MB 上限")
            with dest.open("wb") as fh:
                for chunk in response.iter_bytes(_CHUNK):
                    written += len(chunk)
                    if written > max_bytes:
                        raise TranscribeError("too-large", f"视频超过 {settings.transcribe_max_download_mb} MB 上限")
                    fh.write(chunk)
    except TranscribeError:
        dest.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise TranscribeError("download-failed", f"视频直链下载失败：{exc}") from exc
    if written == 0:
        dest.unlink(missing_ok=True)
        raise TranscribeError("empty-media", "直链返回空内容，请检查链接是否可直接播放")
    return dest


def extract_audio(settings: Settings, src: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [_ffmpeg(settings), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
             "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(out)],
            capture_output=True, check=True, timeout=settings.transcribe_timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TranscribeError("extract-failed", "提取音轨失败，请确认媒体包含可解码的音频") from exc
    if not out.is_file() or out.stat().st_size == 0:
        raise TranscribeError("extract-failed", "提取出的音轨为空")


def _read_pcm16(wav: Path) -> "np.ndarray":
    """用标准库 wave + numpy 读取 ffmpeg 抽出的 16k 单声道 PCM。

    faster-whisper 默认走 PyAV 解码，其 av.open(metadata_errors=...) 与部分 PyAV
    版本不兼容（报 unexpected keyword argument 'metadata_errors'）。这里直接喂 float32
    数组，绕开 PyAV，版本无关。
    """
    import numpy as np

    with wave.open(str(wav), "rb") as fh:
        if fh.getsampwidth() != 2:
            raise TranscribeError("extract-failed", "抽音轨不是 16bit PCM 格式")
        frames = fh.readframes(fh.getnframes())
    if not frames:
        raise TranscribeError("extract-failed", "抽音轨为空")
    return np.frombuffer(frames, dtype="<i2").astype("float32") / 32768.0


def transcribe_audio(settings: Settings, wav: Path, language: str) -> tuple[str, list[dict]]:
    # 模型缓存统一落在 data 目录，避免污染用户主目录（首跑自动下载）。
    cache_dir = settings.data_dir / "whisper_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(cache_dir))
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:  # noqa: BLE001
        raise TranscribeError(
            "missing-dependency", "未安装 faster-whisper，请执行 pip install faster-whisper"
        ) from exc
    resolved = None if (language or "").strip().lower() in ("", "auto") else language
    audio = _read_pcm16(wav)
    try:
        model = WhisperModel(
            settings.transcribe_model,
            device=settings.transcribe_device,
            compute_type=settings.transcribe_compute_type,
        )
        segments, _info = model.transcribe(
            audio, language=resolved, vad_filter=True, beam_size=5, word_timestamps=False,
        )
        parts: list[str] = []
        cues: list[dict] = []
        for segment in segments:
            text = (segment.text or "").strip()
            if not text:
                continue
            parts.append(text)
            cues.append({"start": round(segment.start, 3), "end": round(segment.end, 3), "text": text})
    except TranscribeError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("转写失败")
        raise TranscribeError("transcribe-failed", f"语音识别失败：{exc}") from exc
    if not cues:
        raise TranscribeError("empty-result", "未识别到有效语音内容")
    return "\n".join(parts), cues


def srt_timestamp(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    sec, ms = divmod(millis, 1000)
    minute, sec = divmod(sec, 60)
    hour, minute = divmod(minute, 60)
    return f"{hour:02}:{minute:02}:{sec:02},{ms:03}"


def write_sidecars(out_dir: Path, text: str, cues: list[dict]) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    text_path = out_dir / "transcript.txt"
    srt_path = out_dir / "transcript.srt"
    text_path.write_text(text + "\n", encoding="utf-8")
    srt_path.write_text("\n\n".join(
        f"{i}\n{srt_timestamp(c['start'])} --> {srt_timestamp(c['end'])}\n{c['text']}"
        for i, c in enumerate(cues, 1)) + "\n", encoding="utf-8")
    return {"text_path": str(text_path), "srt_path": str(srt_path)}


def transcribe_job(settings: Settings, *, job_id: int, media_path: Path | None, source_type: str,
                   source_ref: str, language: str, title: str,
                   emit=None, progress=None) -> dict:
    """完整转写流程，返回 text/segments/duration/sidecar 路径。不触碰数据库。"""
    def _emit(message: str) -> None:
        if emit:
            emit(message)

    if source_type == "url":
        _emit("下载视频直链…")
        media = download_direct_url(settings, source_ref)
    else:
        if not media_path or not Path(media_path).is_file():
            raise TranscribeError("missing-media", "上传的媒体文件不存在")
        media = Path(media_path)

    try:
        _emit("解析媒体信息…")
        info = probe_media(settings, media)
        if not info["has_audio"]:
            raise TranscribeError("no-audio", "该媒体没有音轨，无法转文稿")
        duration = info["duration"]

        work_dir = settings.transcripts_dir / str(job_id)
        wav = work_dir / "audio.wav"
        _emit("提取音轨…")
        extract_audio(settings, media, wav)

        _emit(f"语音识别中（{settings.transcribe_model}）…")
        if progress and duration:
            progress(0, int(duration))
        text, cues = transcribe_audio(settings, wav, language)
        sidecars = write_sidecars(work_dir, text, cues)
        if progress:
            progress(int(duration) or 1, int(duration) or 1)
        return {"text": text, "segments": cues, "duration_sec": duration, "title": title, **sidecars}
    finally:
        if source_type == "url":
            media.unlink(missing_ok=True)


def cleanup_job(settings: Settings, job_id: int) -> None:
    work_dir = settings.transcripts_dir / str(job_id)
    if work_dir.is_dir():
        for path in work_dir.rglob("*"):
            if path.is_file():
                path.unlink(missing_ok=True)
        for path in sorted(work_dir.rglob("*"), reverse=True):
            if path.is_dir():
                path.rmdir()
        work_dir.rmdir()
