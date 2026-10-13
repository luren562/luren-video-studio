"""TTS 配音与时间轴服务。

把结构化规格（VideoVersion.spec_json）里的逐镜解说词合成为**一条整轨 wav**，
并按词级边界回填真实时间轴（每镜起始帧、时长、字幕块起止帧）。

设计要点（沿用 anything2explainer/template/scripts/tts_build.py）：
- edge-tts 云端合成，显式请求 WordBoundary → 字幕块起点最准；
- 整条音轨一次性拼装、统一归一化，不逐镜分段（避免音画错位）；
- 逐句 mp3 缓存（键含 voice/rate/text），改一句只重合成一句；
- 时间轴用帧号（0 起、半开区间）表达，直接喂给 web/renderer。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from loguru import logger

from .config import Settings, get_settings

FPS = 30
SR = 48000
CHAPTER_ROLES = {"chapter", "chapter_card"}


@dataclass
class TtsResult:
    ok: bool
    engine: str = ""
    voice: str = ""
    duration_sec: float = 0.0
    scenes_count: int = 0
    chunks_count: int = 0
    wav_path: Path | None = None
    timeline: dict | None = None
    error: str = ""
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 音频工具
# ---------------------------------------------------------------------------
def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    """float32 (n,) 单声道 或 (n,2) 立体声 → 16bit PCM wav。"""
    arr = np.asarray(samples, dtype=np.float32)
    pcm = (np.clip(arr, -1.0, 1.0) * 32767).astype(np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1 if arr.ndim == 1 else arr.shape[1])
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def decode_audio(path: Path) -> np.ndarray:
    """任意音频 → 48k 单声道 float32（走 ffmpeg）。"""
    settings = get_settings()
    proc = subprocess.run(
        [
            settings.ffmpeg_binary,
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "f32le",
            "-ac",
            "1",
            "-ar",
            str(SR),
            "-",
        ],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def trim_edges(x: np.ndarray, threshold: float = 0.004) -> tuple[np.ndarray, float]:
    """裁掉首尾静音，返回 (裁剪后音频, 被裁掉的起始秒数)。"""
    idx = np.where(np.abs(x) > threshold)[0]
    if len(idx) == 0:
        return x, 0.0
    start = max(0, idx[0] - int(0.03 * SR))
    end = min(len(x), idx[-1] + int(0.12 * SR))
    return x[start:end], start / SR


def text_em(text: str) -> float:
    """与 renderer 字幕宽度预判一致的字宽（约 em）。"""
    total = 0.0
    for ch in text:
        code = ord(ch)
        if code >= 0x2000:
            total += 1.0
        elif ch == " ":
            total += 0.227
        elif "A" <= ch <= "Z":
            total += 0.668
        elif "0" <= ch <= "9":
            total += 0.59
        elif "a" <= ch <= "z":
            total += 0.566
        elif 0xC0 <= code < 0x250:
            total += 0.58
        else:
            total += 0.325
    return total


# ---------------------------------------------------------------------------
# edge-tts 合成
# ---------------------------------------------------------------------------
def _cache_path(cache_dir: Path, voice: str, rate: str, text: str, ext: str) -> Path:
    sig = f"edge|{voice}|{rate}|{text}"
    return cache_dir / (hashlib.sha1(sig.encode()).hexdigest()[:16] + ext)


async def synth_edge(
    text: str, voice: str, rate: str, cache_dir: Path, tries: int | None = None,
    *, settings: Settings | None = None,
) -> tuple[Path, list[dict]]:
    """整句合成 + 词级边界。返回 (mp3 路径, 词边界列表)。"""
    settings = settings or get_settings()
    if tries is None:
        tries = settings.tts_retries
    proxy = settings.tts_proxy or None
    mp3 = _cache_path(cache_dir, voice, rate, text, ".mp3")
    js = _cache_path(cache_dir, voice, rate, text, ".json")
    if mp3.exists() and mp3.stat().st_size and js.exists():
        try:
            return mp3, json.loads(js.read_text(encoding="utf-8"))
        except ValueError:
            pass

    import socket

    import edge_tts

    last_error = ""
    for attempt in range(1, tries + 1):
        audio = bytearray()
        words: list[dict] = []
        connector = None
        if settings.tts_force_ipv4:
            import aiohttp

            connector = aiohttp.TCPConnector(family=socket.AF_INET)
        try:
            comm = edge_tts.Communicate(
                text, voice, rate=rate, boundary="WordBoundary", proxy=proxy, connector=connector
            )
            async for event in comm.stream():
                if event["type"] == "audio":
                    audio.extend(event["data"])
                elif event["type"] == "WordBoundary":
                    words.append(
                        {
                            "t": event["offset"] / 1e7,
                            "d": event["duration"] / 1e7,
                            "text": event["text"],
                        }
                    )
            if audio:
                break
            last_error = "端点返回空音频"
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
        finally:
            if connector is not None and not connector.closed:
                try:
                    await connector.close()
                except Exception:  # noqa: BLE001
                    pass
        if attempt == tries:
            raise RuntimeError(f"edge-tts 连续 {tries} 次失败（{last_error}）：{text[:24]}…")
        await asyncio.sleep(min(6.0, 0.8 * attempt))

    from tempfile import NamedTemporaryFile
    cache_dir.mkdir(parents=True, exist_ok=True)
    for target, raw in [(mp3, bytes(audio)), (js, json.dumps(words, ensure_ascii=False).encode())]:
        with NamedTemporaryFile(dir=cache_dir, delete=False) as handle:
            handle.write(raw)
            temporary = Path(handle.name)
        temporary.replace(target)
    return mp3, words


def chunk_starts(
    tts_text: str, chunks: list[str], words: list[dict], lead_cut: float, dur: float, sep: str
) -> list[float]:
    """字幕块在句内的起始秒：按词边界把字符游标对齐回原句；无边界则按字数插值。"""
    char_t: list[float | None] = [None] * len(tts_text)
    cursor = 0
    for word in words:
        token = re.sub(r"[\s，。、！？：；“”（）,.!?:;()\-—…]", "", word["text"])
        if not token:
            continue
        pos = tts_text.find(token, cursor)
        if pos < 0:
            pos = tts_text.find(token[0], cursor)
            if pos < 0:
                continue
        for i in range(pos, min(len(tts_text), pos + len(token))):
            char_t[i] = word["t"] - lead_cut
        cursor = pos + len(token)

    starts: list[float | None] = []
    pos = 0
    for chunk in chunks:
        start = None
        for i in range(pos, pos + len(chunk)):
            if i < len(char_t) and char_t[i] is not None:
                start = char_t[i]
                break
        starts.append(start)
        pos += len(chunk) + len(sep)

    for i, start in enumerate(starts):
        if start is None:
            prev = starts[i - 1] if i > 0 and starts[i - 1] is not None else 0.0
            starts[i] = prev + dur * len(chunks[i - 1]) / max(1, len(tts_text)) if i > 0 else 0.0
    starts[0] = 0.0
    return [max(0.0, s) for s in starts]


async def synth_sentence(
    chunks: list[str], sep: str, voice: str, rate: str, cache_dir: Path
) -> tuple[np.ndarray, list[float], float]:
    """一句（由字幕块拼成）→ (音频, 各块句内起始秒, 句长秒)。"""
    tts_text = sep.join(chunks)
    mp3, words = await synth_edge(tts_text, voice, rate, cache_dir)
    x, lead_cut = trim_edges(decode_audio(mp3))
    dur = len(x) / SR
    return x, chunk_starts(tts_text, chunks, words, lead_cut, dur, sep), dur


# ---------------------------------------------------------------------------
# 时间轴
# ---------------------------------------------------------------------------
def _scene_chunks(scene: dict) -> list[str]:
    chunks = [str(c).strip() for c in (scene.get("subtitle_chunks") or []) if str(c).strip()]
    if not chunks:
        narration = str(scene.get("narration") or "").strip()
        if narration:
            chunks = [narration]
    return chunks


def _build_subs(starts: list[float], dur: float, chunks: list[str]) -> list[dict]:
    subs: list[dict] = []
    total = max(1, int(round(dur * FPS)))
    for i, chunk in enumerate(chunks):
        begin = 0 if i == 0 else int(round(starts[i] * FPS))
        end = (int(round(starts[i + 1] * FPS)) - 1) if i + 1 < len(starts) else total - 1
        begin = max(0, min(begin, total - 1))
        end = max(begin, min(end, total - 1))
        subs.append({"from": begin, "to": end, "text": chunk})
    return subs


def _chapter_track(spec: dict, scene_timings: list[dict], scenes: list[dict]) -> tuple[list[int], list[str]]:
    names = [str(c.get("name")) for c in (spec.get("chapters") or []) if isinstance(c, dict) and c.get("name")]
    if not names:
        names = ["全片"]
    starts: list[int] = []
    ci = 0
    for i, (scene, timing) in enumerate(zip(scenes, scene_timings)):
        role = scene.get("role", "content")
        if i == 0:
            starts.append(timing["start"])
            ci = 1
        elif role in CHAPTER_ROLES and ci < len(names):
            starts.append(timing["start"])
            ci += 1
    if not starts:
        starts = [0]
    return starts, names[: len(starts)] if len(names) >= len(starts) else names + [
        f"第 {i + 1} 章" for i in range(len(starts) - len(names))
    ]


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def build_narration(
    spec: dict,
    lang: str,
    work_dir: Path,
    version_number: int,
    settings: Settings | None = None,
) -> TtsResult:
    """合成整片配音并生成真实时间轴。失败时返回 ok=False（不抛异常）。"""
    settings = settings or get_settings()
    scenes = [s for s in (spec.get("scenes") or []) if isinstance(s, dict)]
    if not scenes:
        return TtsResult(ok=False, error="规格里没有镜头，无法配音")

    voice = settings.tts_voice_en if lang == "en" else settings.tts_voice_zh
    rate = settings.tts_rate
    engine = settings.tts_engine
    cache_dir = settings.assets_dir / "tts_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    if engine != "edge":
        return TtsResult(ok=False, engine=engine, error=f"暂不支持的 TTS 引擎：{engine}")

    placements: list[tuple[float, np.ndarray]] = []
    scene_timings: list[dict] = []
    warnings: list[str] = []
    cursor_f = settings.tts_lead_frames
    chunks_count = 0
    speech_sec = 0.0

    async def run() -> None:
        nonlocal cursor_f, chunks_count, speech_sec
        for scene in scenes:
            chunks = _scene_chunks(scene)
            if not chunks:
                hold = max(1, int(round(1.5 * FPS)))
                scene_timings.append({"start": cursor_f, "duration": hold, "subs": []})
                cursor_f += hold
                continue
            sep = " " if lang == "en" else ""
            x, starts, dur = await synth_sentence(chunks, sep, voice, rate, cache_dir)
            gap = (
                settings.tts_chapter_gap_frames
                if scene.get("role") in CHAPTER_ROLES
                else settings.tts_gap_frames
            )
            scene_start_sec = cursor_f / FPS
            placements.append((scene_start_sec, x))
            subs = _build_subs(starts, dur, chunks)
            for sub in subs:
                if text_em(sub["text"]) * 44 > 1160:
                    warnings.append(f"字幕块超宽：{sub['text']}")
            duration_f = max(1, int(round(dur * FPS))) + gap
            scene_timings.append({"start": cursor_f, "duration": duration_f, "subs": subs})
            cursor_f += duration_f
            chunks_count += len(chunks)
            speech_sec += dur

    try:
        asyncio.run(run())
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"TTS 合成失败：{exc}")
        return TtsResult(ok=False, engine=engine, voice=voice, error=str(exc))

    total_frames = max(1, cursor_f + settings.tts_tail_frames)
    total_samples = int(round(total_frames / FPS * SR))
    track = np.zeros(total_samples, dtype=np.float32)
    for start_sec, x in placements:
        offset = int(round(start_sec * SR))
        end = min(total_samples, offset + len(x))
        if end > offset:
            track[offset:end] += x[: end - offset]
    peak = float(np.max(np.abs(track))) or 1.0
    track = track / peak * 0.89

    wav_path = work_dir / f"narration_v{version_number}.wav"
    write_wav(wav_path, np.stack([track, track], axis=1), SR)

    chapter_starts, chapter_names = _chapter_track(spec, scene_timings, scenes)
    timeline = {
        "fps": FPS,
        "totalFrames": total_frames,
        "scenes": scene_timings,
        "chapterStarts": chapter_starts,
        "chapterNames": chapter_names,
    }
    return TtsResult(
        ok=True,
        engine=engine,
        voice=voice,
        duration_sec=total_frames / FPS,
        scenes_count=len(scene_timings),
        chunks_count=chunks_count,
        wav_path=wav_path,
        timeline=timeline,
        warnings=warnings,
    )
