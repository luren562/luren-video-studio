"""Chinese narration provider — Edge TTS (free, no login) plus manual audio upload."""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .config import Settings

CATALOG = json.loads((Path(__file__).parent / "data/voice_catalog.json").read_text(encoding="utf-8"))
EDGE_NAMES = {"zh-CN-XiaoxiaoNeural", "zh-CN-XiaoyiNeural", "zh-CN-YunjianNeural",
              "zh-CN-YunxiNeural", "zh-CN-YunxiaNeural", "zh-CN-YunyangNeural",
              "zh-CN-liaoning-XiaobeiNeural", "zh-CN-shaanxi-XiaoniNeural",
              "zh-HK-HiuGaaiNeural", "zh-HK-HiuMaanNeural", "zh-HK-WanLungNeural",
              "zh-TW-HsiaoChenNeural", "zh-TW-HsiaoYuNeural", "zh-TW-YunJheNeural"}


class TtsError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        self.code, self.retryable = code, retryable
        super().__init__(message)


def rate_percent(value: object) -> int:
    """语速（int 百分数 / '+0%' 字符串）→ 整型百分数；非法时抛 ValueError。"""
    if isinstance(value, bool):
        raise ValueError("语速必须是 -100% ~ +100% 的整数")
    if isinstance(value, int):
        percent = value
    elif isinstance(value, str):
        text = value.strip()
        if not re.fullmatch(r"[+-]?\d+%", text):
            raise ValueError(f"语速格式应为 +0%：{value!r}")
        percent = int(text[:-1])
    else:
        raise ValueError("语速必须是整数百分数")
    if not -100 <= percent <= 100:
        raise ValueError("语速范围 -100% ~ +100%")
    return percent


def normalize_rate(value: object) -> str:
    """任意合法语速表示 → 规范字符串（如 '+20%'）。"""
    return f"{rate_percent(value):+d}%"


@dataclass
class SpeechChunk:
    path: Path
    cues: list[dict] = field(default_factory=list)
    timing: str = "estimated"
    warnings: list[str] = field(default_factory=list)


class TtsProvider(Protocol):
    name: str
    def list_voices(self) -> list[dict]: ...
    def synth(self, text: str, voice: str, rate: str, out_dir: Path) -> SpeechChunk: ...


def available_voices() -> list[dict]:
    """Edge 免费音色目录（本项目的自动配音引擎，免登录）。

    目录内置 14 个 Edge 中文音色；每个音色都标注 ``providers=["edge"]``，
    选择键 ``id`` 即 Azure shortName。
    """
    voices: list[dict] = []
    seen: set[str] = set()
    for raw in CATALOG["voices"]:
        short = raw["shortName"]
        if short not in EDGE_NAMES:
            continue
        seen.add(short)
        voices.append({**raw, "id": short, "provider": "edge", "providers": ["edge"]})
    for short in sorted(EDGE_NAMES - seen):
        voices.append({"id": short, "name": short, "localName": short, "shortName": short,
                       "locale": short[:5], "gender": "", "language": "Chinese",
                       "provider": "edge", "providers": ["edge"], "styles": ["general"]})
    return voices


def resolve_voice(provider: str, requested: str | None, settings: Settings) -> str:
    if provider == "manual":
        return "manual"
    value = requested or settings.tts_voice_zh
    if value in EDGE_NAMES:
        return value
    match = next((v for v in CATALOG["voices"] if value == v["shortName"]), None)
    if match and match["shortName"] in EDGE_NAMES:
        return match["shortName"]
    raise TtsError("invalid-voice", "请选择目录中的中文音色")


def split_text(text: str, limit: int = 1800) -> list[str]:
    """Keep every character; measure UTF-16 units like the web client's 2000 limit."""
    if limit < 2:
        raise ValueError("limit must be >= 2")
    chunks, start, units, boundary = [], 0, 0, 0
    index = 0
    while index < len(text):
        cost = 2 if ord(text[index]) > 0xFFFF else 1
        if units + cost > limit:
            end = boundary if boundary > start else index
            chunks.append(text[start:end])
            start = index = end
            units, boundary = 0, end
            continue
        units += cost
        index += 1
        if text[index - 1] in "。！？!?；;\n":
            boundary = index
    if start < len(text):
        chunks.append(text[start:])
    return chunks


def parse_srt(text: str) -> list[dict]:
    cues = []
    pattern = r"(\d{1,3}):(\d{2}):(\d{2})[,.](\d{3})"
    for block in re.split(r"\n\s*\n", text.replace("\r", "").strip()):
        lines = block.splitlines()
        line = next((i for i, v in enumerate(lines) if "-->" in v), None)
        if line is None:
            continue
        matches = re.findall(pattern, lines[line])
        if len(matches) != 2:
            continue
        times = [int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000 for h, m, s, ms in matches]
        caption = "\n".join(lines[line + 1:]).strip()
        if caption and times[1] > times[0] and (not cues or times[0] >= cues[-1]["end"] - 0.001):
            cues.append({"start": times[0], "end": times[1], "text": caption})
    return cues


class EdgeTtsProvider:
    name = "edge"

    def __init__(self, settings: Settings):
        self.settings = settings

    def list_voices(self):
        return available_voices()

    def synth(self, text: str, voice: str, rate: str, out_dir: Path) -> SpeechChunk:
        from .tts_service import synth_edge
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            path, words = asyncio.run(synth_edge(text, voice, rate, out_dir, settings=self.settings))
        except Exception as exc:
            raise TtsError("edge-failed", "Edge 配音失败，请检查网络或上传旁白") from exc
        cues = [{"start": w["t"], "end": w["t"] + w["d"], "text": w["text"]} for w in words if w["d"] > 0]
        return SpeechChunk(path, cues, "word-boundary" if cues else "estimated")


class ManualUploadProvider:
    name = "manual"

    def __init__(self, path: Path | None):
        self.path = path

    def list_voices(self):
        return []

    def synth(self, text: str, voice: str, rate: str, out_dir: Path) -> SpeechChunk:
        if not self.path or not self.path.is_file():
            raise TtsError("manual-required", "请在项目中上传旁白音频")
        subtitle = self.path.with_suffix(".srt")
        cues = parse_srt(subtitle.read_text(encoding="utf-8-sig")) if subtitle.is_file() else []
        return SpeechChunk(self.path, cues, "provider" if cues else "estimated",
                           [] if cues else ["上传旁白未附字幕，时间轴按文本估算，需核对同步"])
