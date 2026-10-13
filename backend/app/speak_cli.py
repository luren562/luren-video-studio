"""Backend for the injected `node scripts/vf_speak.mjs` command（talkcraft 成品配音）。

读 `script.json` 的逐句口播稿，合成一条整轨 48k 单声道 `audio/full.wav`
（供字级时间戳对齐），并写句级 `narration.timeline.json`（供平台核对）。
复用平台 TTS 后端（Edge 配音与人工旁白、缓存、限速）与人工上传旁白。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from .config import get_settings
from .narration import SAMPLE_RATE, ffmpeg, synthesize_narration
from .tts_providers import TtsError, normalize_rate


def workspace_path(value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_relative_to(Path.cwd().resolve()):
        raise TtsError("outside-workspace", "文本、旁白与输出文件必须位于当前工作区内")
    return path


def synthesize_script(sentences, out_wav: Path, timeline_path: Path, settings, *,
                      voice: str | None = None, manual_file: Path | None = None) -> dict:
    """逐句稿 → (48k 单声道 wav, 句级 timeline)。失败时返回 ok=False 的 timeline。"""
    text = "\n".join(str(s).strip() for s in sentences if str(s).strip())
    if not text:
        raise TtsError("empty-text", "口播稿不能为空")
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    timeline_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vf-speak-", dir=out_wav.parent) as temp:
        mp3 = Path(temp) / "narration.mp3"
        result = synthesize_narration(text, mp3, settings, voice=voice, manual_file=manual_file)
        if result.get("ok"):
            ffmpeg(settings, ["-i", str(mp3), "-ac", "1", "-ar", str(SAMPLE_RATE),
                              "-c:a", "pcm_s16le", str(out_wav)])
    timeline = {
        **result,
        "relative": "cues",
        "audio": out_wav.name,
        "timing": "exact" if result.get("timing") == "aligned" else result.get("timing", "estimated"),
    }
    timeline_path.write_text(json.dumps(timeline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return timeline


def main() -> int:
    parser = argparse.ArgumentParser(description="口播成品配音：逐句稿 → 48k wav + 句级时间轴")
    parser.add_argument("--script", required=True)
    parser.add_argument("--wav", default="audio/full.wav")
    parser.add_argument("--timeline", default="public/audio/narration.timeline.json")
    parser.add_argument("--voice", default=os.environ.get("VF_TTS_VOICE") or None)
    parser.add_argument("--rate", default=os.environ.get("VF_TTS_RATE") or None)
    parser.add_argument("--manual-file", default=os.environ.get("VF_TTS_MANUAL_FILE") or None)
    args = parser.parse_args()
    try:
        settings = get_settings()
        if not settings.tts_enabled:
            raise TtsError("disabled", "当前项目已关闭配音")
        if args.rate:
            try:
                settings = settings.model_copy(update={"tts_rate": normalize_rate(args.rate)})
            except ValueError as exc:
                raise TtsError("invalid-rate", str(exc)) from exc
        script = json.loads(workspace_path(args.script).read_text(encoding="utf-8-sig"))
        sentences = script.get("sentences") if isinstance(script, dict) else script
        if not isinstance(sentences, list):
            raise TtsError("invalid-script", 'script.json 需要 {"sentences": [...]}')
        result = synthesize_script(
            sentences, workspace_path(args.wav), workspace_path(args.timeline), settings,
            voice=args.voice,
            manual_file=workspace_path(args.manual_file) if args.manual_file else None,
        )
        for warning in result.get("warnings", []):
            print(f"WARNING: {warning}", file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 1
    except (TtsError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
