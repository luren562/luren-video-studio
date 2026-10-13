"""Provider-independent long narration assembly and subtitle timing."""
from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
import wave
from pathlib import Path

from .config import Settings
from .tts_providers import (EdgeTtsProvider, ManualUploadProvider,
                            SpeechChunk, TtsError, resolve_voice, split_text)

SAMPLE_RATE = 48000
GAP_SECONDS = 0.25


def ffmpeg(settings: Settings, args: list[str]) -> None:
    try:
        subprocess.run([settings.ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-y", *args],
                       capture_output=True, check=True, timeout=settings.tts_timeout_seconds)
    except (OSError, subprocess.SubprocessError) as exc:
        raise TtsError("audio-processing", "配音音频处理失败，请检查 ffmpeg 和音频文件") from exc


def estimate_cues(text: str, duration: float) -> list[dict]:
    sentences = re.findall(r"[^。！？!?；;\n]+[。！？!?；;\n]*|[。！？!?；;\n]+", text)
    parts = [part.strip() for sentence in sentences for part in split_text(sentence, 28) if part.strip()]
    total = sum(len(part) for part in parts) or 1
    cursor, cues = 0.0, []
    for part in parts:
        end = cursor + duration * len(part) / total
        cues.append({"start": cursor, "end": end, "text": part})
        cursor = end
    return cues


def srt_timestamp(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    sec, ms = divmod(millis, 1000)
    minute, sec = divmod(sec, 60)
    hour, minute = divmod(minute, 60)
    return f"{hour:02}:{minute:02}:{sec:02},{ms:03}"


def write_sidecars(out: Path, timeline: dict) -> None:
    out.with_suffix(".timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out.with_suffix(".srt").write_text("\n\n".join(
        f"{i}\n{srt_timestamp(c['start'])} --> {srt_timestamp(c['end'])}\n{c['text']}"
        for i, c in enumerate(timeline["cues"], 1)) + "\n", encoding="utf-8")


def assemble(chunks: list[tuple[str, SpeechChunk]], out: Path, settings: Settings, *, provider: str,
             voice: str, warnings: list[str]) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    all_cues, chunk_meta = [], []
    cursor_samples = 0
    with tempfile.TemporaryDirectory(prefix="vf-tts-", dir=out.parent) as temp:
        tempdir = Path(temp)
        joined = tempdir / "joined.wav"
        with wave.open(str(joined), "wb") as track:
            track.setnchannels(1)
            track.setsampwidth(2)
            track.setframerate(SAMPLE_RATE)
            for i, (text, chunk) in enumerate(chunks):
                decoded = tempdir / f"chunk-{i}.wav"
                ffmpeg(settings, ["-i", str(chunk.path), "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(decoded)])
                with wave.open(str(decoded), "rb") as audio:
                    count = audio.getnframes()
                    if count <= 0:
                        raise TtsError("empty-audio", "合成音频没有有效采样")
                    duration = count / SAMPLE_RATE
                    start = cursor_samples / SAMPLE_RATE
                    while raw := audio.readframes(SAMPLE_RATE):
                        track.writeframesraw(raw)
                cues = chunk.cues or estimate_cues(text, duration)
                timing = chunk.timing
                # Reject malformed/out-of-range upstream timing; never label an estimate as exact.
                if any(not math.isfinite(c["start"]) or not math.isfinite(c["end"]) or
                       c["start"] < 0 or c["end"] > duration + 0.3 or c["end"] <= c["start"] for c in cues):
                    cues, timing = estimate_cues(text, duration), "estimated"
                    warnings.append(f"第 {i + 1} 段字幕超出音频时长，改用估算时间轴")
                for cue in cues:
                    begin, end = min(cue["start"], duration), min(cue["end"], duration)
                    if end > begin:
                        all_cues.append({"start": round(start + begin, 4), "end": round(start + end, 4), "text": cue["text"]})
                warnings.extend(chunk.warnings)
                chunk_meta.append({"index": i, "start": start, "duration": duration, "characters": len(text), "timing": timing})
                cursor_samples += count
                if i + 1 < len(chunks):
                    silence = round(SAMPLE_RATE * GAP_SECONDS)
                    track.writeframesraw(b"\x00\x00" * silence)
                    cursor_samples += silence
        encoded = tempdir / "narration.mp3"
        ffmpeg(settings, ["-i", str(joined), "-c:a", "libmp3lame", "-b:a", "192k", str(encoded)])
        encoded.replace(out)
    estimated = any(c["timing"] == "estimated" for c in chunk_meta)
    if estimated:
        warnings.append("字幕含估算时间，不能保证误差 ≤0.3 秒，请核对或提供 SRT")
    timeline = {"schema_version": 1, "ok": True, "status": "ready", "provider": provider, "voice": voice,
                "audio": out.name, "duration_sec": cursor_samples / SAMPLE_RATE, "sample_rate": SAMPLE_RATE,
                "gap_sec": GAP_SECONDS, "timing": "estimated" if estimated else "aligned",
                "chunks": chunk_meta, "cues": all_cues, "warnings": list(dict.fromkeys(warnings))}
    write_sidecars(out, timeline)
    return timeline


def synthesize_narration(text: str, out: Path, settings: Settings, *, voice: str | None = None,
                         manual_file: Path | None = None, allow_fallback: bool = True) -> dict:
    if not text.strip():
        raise TtsError("empty-text", "旁白文本不能为空")
    if out.suffix.lower() != ".mp3":
        raise TtsError("invalid-output", "配音输出文件必须使用 .mp3 扩展名")
    if manual_file and manual_file.resolve() == out.resolve():
        raise TtsError("invalid-output", "输出文件不能覆盖上传的原始旁白，请选择其他输出路径")
    out.parent.mkdir(parents=True, exist_ok=True)
    # A previous successful run must never masquerade as the current failed run.
    for path in (out, out.with_suffix(".srt"), out.with_suffix(".timeline.json")):
        path.unlink(missing_ok=True)
    primary = "manual" if manual_file else settings.tts_provider
    providers = [primary]
    if allow_fallback and settings.tts_fallback not in {primary, "none"}:
        providers.append(settings.tts_fallback)
    warnings = []
    for name in providers:
        try:
            selected = resolve_voice(name, voice, settings)
            if name == "edge":
                provider = EdgeTtsProvider(settings)
            else:
                provider = ManualUploadProvider(manual_file)
            texts = [text] if name == "manual" else split_text(text)
            chunks = [(part, provider.synth(part, selected, settings.tts_rate, settings.assets_dir / "tts_cache"))
                      for part in texts]
            return assemble(chunks, out, settings, provider=name, voice=selected, warnings=warnings)
        except TtsError as exc:
            warnings.append(f"{name} 配音失败 [{exc.code}]：{exc}")
    result = {"schema_version": 1, "ok": False, "status": "failed", "provider": primary, "voice": voice,
              "audio": None, "duration_sec": 0, "chunks": [], "cues": [], "timing": "unavailable",
              "warnings": warnings}
    write_sidecars(out, result)
    if settings.tts_required or not allow_fallback:
        raise TtsError("narration-failed", "; ".join(warnings))
    return result
