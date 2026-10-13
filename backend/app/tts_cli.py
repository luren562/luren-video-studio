"""Backend for the injected `node scripts/vf_tts.mjs` command."""
import argparse
import json
import os
import sys
from pathlib import Path

from .config import get_settings
from .narration import synthesize_narration
from .tts_providers import TtsError, normalize_rate


def workspace_path(value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_relative_to(Path.cwd().resolve()):
        raise TtsError("outside-workspace", "文本、旁白与输出文件必须位于当前工作区内")
    return path


def main():
    parser = argparse.ArgumentParser(description="生成中文旁白、SRT 与秒级时间轴；自动分块与回退")
    parser.add_argument("--text-file", required=True)
    parser.add_argument("--voice", default=os.environ.get("VF_TTS_VOICE") or None)
    parser.add_argument("--rate", default=os.environ.get("VF_TTS_RATE") or None)
    parser.add_argument("--out", default="public/audio/narration.mp3")
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
        text = workspace_path(args.text_file).read_text(encoding="utf-8-sig")
        result = synthesize_narration(text, workspace_path(args.out), settings, voice=args.voice,
                                      manual_file=workspace_path(args.manual_file) if args.manual_file else None)
        for warning in result["warnings"]:
            print(f"WARNING: {warning}", file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (TtsError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
