"""Install platform commands/instructions and pass secrets only via process env."""
import os
import json
import shutil
import stat
import sys
from pathlib import Path

from .config import BACKEND_DIR, Settings

INSTRUCTIONS = """# 平台主题色与音频要求（覆盖 skill 的默认设置）

1. 全片 accent 主色必须使用简报 requirements.accent；背景、前景继承 theme。
2. requirements.bgm_enabled 是最终 BGM 开关。false 时禁止任何背景音乐（包括
   视频素材原有音乐），保留 SFX 和已启用的旁白；Remotion inputProp `bgm` 必须为 false。
   true 时允许 BGM，但旁白期间必须压低音乐。只交付 out/final.mp4，不额外生成无 BGM 版本。
3. requirements.narration_required=true 时先写中文旁白脚本，再执行平台命令：
   `node scripts/vf_tts.mjs --text-file narration.txt --out public/audio/narration.mp3`
   命令从环境读取所选音色，也可用 `--voice <requirements.tts_voice>` 显式指定。
   命令自动处理 1800 字分块、串行限速、缓存、重试、250ms 间隔和回退；不要自行调用供应商接口。
   配音固定中文（即使画面语言为英文）。脚本与音频生成后再安排镜头，不能按估计时长剪断旁白。
4. 读取同目录 narration.timeline.json 的 ok、duration_sec、cues、warnings。
   ok=true 才可引用 narration.mp3。把干声轨挂入 Remotion，字幕 start/end 单位为秒，
   按 composition fps 转帧，与旁白使用同一播放偏移；不得单独拉伸音频或凭字数重写已对齐的字幕。
   timing=estimated 时必须在 finish.json 的 warnings 中报告，不能宣称同步误差 ≤0.3s。
   ok=false 时必须记录 warnings：若 TTS_REQUIRED=true 则修复或报告阻断；否则可无旁白继续。
   人工上传的旁白由平台自动传给命令，不要重新合成或覆盖上传文件。
   人工旁白的 narration.txt 必须使用用户提供的对应原文；缺少原文时明确记录缺口，不能编造字幕。
5. narration_required=false 时不要调用配音命令，也不要挂载旁白音轨。
6. 可选干声/BGM 混音命令：
   `node scripts/vf_mix.mjs --narration public/audio/narration.mp3 --bgm <音乐文件> --out public/audio/mixed.wav`
   若使用混音轨，不得再重复挂载干声/BGM。SFX 在时间线中单独保留。
7. scripts/vf_tts.mjs 和 scripts/vf_mix.mjs 是平台只读文件，不要修改。密钥通过环境传递，
   不要读取、打印、写入工程文件或 finish.json。
8. 完成前核对主题色、BGM 开关、旁白音色、字幕与实际音频；finish.json 增加
   audio: {bgm_enabled, narration_enabled, voice, timing} 和 warnings 数组，按真实结果填写。
"""


# talkcraft（口播）音频管线：成品配音 → 字级时间戳 → timing.json。
TALKCRAFT_INSTRUCTIONS = """# 平台主题色与口播音频要求（talkcraft，优先级高于 skill 默认）

1. 先按 `.opencode/platform/style.md` 写口播稿，落成 `audio/script.json`：
   `{"sentences": ["……", "……"]}`，每句一个信息点；**数字一律用汉字**（时间戳逐字锚定，
   `197747` 无法与"十九万七千"对位）；英文品牌词直接写。
2. 生成配音（成品配音管线）。若平台已注入人工配音（环境变量 `VF_TTS_MANUAL_FILE` 非空），
   把它一并传给命令，不重新合成、不覆盖：
   `node scripts/vf_speak.mjs --script audio/script.json --wav audio/full.wav --timeline public/audio/narration.timeline.json`
   （人工配音：追加 `--manual-file "$VF_TTS_MANUAL_FILE"`）。
    该命令复用平台 TTS 后端（Edge 配音与人工旁白、缓存、限速），输出 48k 单声道 `audio/full.wav`
   与句级 `narration.timeline.json`；不要自行调用供应商接口。
3. 字级时间戳（对 `audio/full.wav` 与 `audio/script.json`）：
   `"$VF_PYTHON" .opencode/skills/video-talkcraft/scripts/timestamps_cpu.py audio/full.wav audio/script.json audio/timestamps.json --backend "${VF_TALKCRAFT_WHISPER_BACKEND:-whisper}"`
   `"$VF_PYTHON" .opencode/skills/video-talkcraft/scripts/make_timing.py audio/timestamps.json remotion/src/timing.json`
   其余按 `SKILL.md`：语义标注 / SHOTBOOK / Remotion / 三重验收；渲染交付 `out/final.mp4` + `out/finish.json`。
4. 从 `remotion/src/timing.json` 归一写 `public/audio/narration.timeline.json`（供平台核对，
   字段与平台一致）：
   `{"ok": true, "status": "ok", "provider": "…", "voice": "…", "duration_sec": 0.0,`
   ` "timing": "exact", "relative": "cues", "cues": [{"start": 0, "end": 0, "text": "…"}], "warnings": []}`
   `ok/status/provider/voice/duration_sec/timing/warnings` 字段必须齐全。
5. BGM/accent 规则沿用：全片 accent 用简报 requirements.accent；`bgm_enabled=false` 禁 BGM，
   仅保留人声/SFX；`bgm_enabled=true` 时旁白期间压低音乐。
6. `scripts/vf_speak.mjs` 是平台只读文件，不要修改。密钥通过环境传递，
   不要读取、打印、写入工程文件或 finish.json。
7. 完成前核对主题色、配音音色、字幕与实际音频；finish.json 增加
   `audio: {bgm_enabled, narration_enabled, voice, timing}` 和 warnings 数组，按真实结果填写。
"""


def _write_scripts(workspace: Path, names: tuple[str, ...]) -> None:
    scripts = workspace / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for name in names:
        src, dest = BACKEND_DIR / "agent_scripts" / name, scripts / name
        if dest.exists():
            dest.chmod(stat.S_IWRITE | stat.S_IREAD)
        shutil.copyfile(src, dest)
        dest.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def install_audio_tools(workspace: Path) -> None:
    """shotcraft 音频工具与平台文档（保留为兼容包装）。"""
    _write_scripts(workspace, ("vf_tts.mjs", "vf_mix.mjs"))
    doc = workspace / ".opencode/platform/audio.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(INSTRUCTIONS, encoding="utf-8")


def _install_talkcraft_tools(workspace: Path) -> None:
    """talkcraft 音频工具与平台文档（成品配音 + 字级时间戳管线）。"""
    _write_scripts(workspace, ("vf_speak.mjs",))
    doc = workspace / ".opencode/platform/audio.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(TALKCRAFT_INSTRUCTIONS, encoding="utf-8")


# 平台视觉审片要求：随项目 review_required 开关切换，覆盖 skill 默认流程。
REVIEW_INSTRUCTIONS_ON = """# 平台视觉审片要求（本项目已开启审片）

1. 本项目 `requirements.review_required=true`。
2. 若所用模型支持图片输入（已声明附件能力 attachment），按 skill 流程抽帧自审画面与音画同步。
3. 若所用模型不支持图片输入，跳过读图，改为源码/数值核对，并如实记录无法读图。
4. 交付契约不变：`out/final.mp4`（含音轨）+ `out/finish.json`。
"""

REVIEW_INSTRUCTIONS_OFF = """# 平台视觉审片要求（本项目已关闭审片）

1. 本项目 `requirements.review_required=false`。
2. **禁止**执行 Remotion 抽帧审片（`remotion still` / 读取 PNG），直接交付 `out/final.mp4` + `out/finish.json`。
3. 平台要求优先于 skill 默认流程；技术闸（可解析 / 含音轨 / 旁白达标）照常。
"""


def _write_review_doc(workspace: Path, review_required: bool) -> None:
    doc = workspace / ".opencode/platform/review.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(REVIEW_INSTRUCTIONS_ON if review_required else REVIEW_INSTRUCTIONS_OFF,
                   encoding="utf-8")


def install_platform_docs(workspace: Path, engine=None, *, review_required: bool = True) -> None:
    """按引擎的 `audio_mode` 注入对应音频工具与平台文档（默认回退 shotcraft）。"""
    mode = getattr(engine, "audio_mode", "tts-synth") or "tts-synth"
    if mode == "timestamps":
        _install_talkcraft_tools(workspace)
    else:
        install_audio_tools(workspace)
    _write_review_doc(workspace, review_required)


def audio_environment(settings: Settings, requirements: dict, *, manual_file: str = "") -> dict[str, str]:
    keys = ("tts_provider", "tts_fallback", "tts_required", "tts_voice_zh", "tts_rate", "tts_retries",
            "tts_proxy", "tts_force_ipv4", "tts_timeout_seconds", "ffmpeg_binary", "assets_dir")
    env = {key.upper(): str(getattr(settings, key)).lower() if isinstance(getattr(settings, key), bool)
           else str(getattr(settings, key)) for key in keys}
    talkcraft_cache = settings.data_dir / "talkcraft_cache"
    env.update({"VF_PYTHON": sys.executable, "PYTHONIOENCODING": "utf-8",
                "ASSETS_DIR": str(settings.assets_dir.resolve()),
                "PYTHONPATH": os.pathsep.join(filter(None, [str(BACKEND_DIR), os.environ.get("PYTHONPATH", "")])),
                "TTS_ENABLED": str(requirements["narration_required"]).lower(),
                "VF_TTS_VOICE": requirements["tts_voice"] or "",
                "VF_TTS_RATE": str(requirements.get("tts_rate") or ""),
                "VF_TTS_MANUAL_FILE": manual_file,
                "VF_BGM_ENABLED": str(requirements["bgm_enabled"]).lower(),
                # talkcraft：whisper 后端与模型持久缓存（首跑下 460MB，之后命中缓存）。
                "VF_TALKCRAFT_WHISPER_BACKEND": "whisper",
                "HF_HOME": str(talkcraft_cache.resolve()),
                "XDG_CACHE_HOME": str(talkcraft_cache.resolve())})
    return env


def read_audio_report(workspace: Path, requirements: dict) -> dict:
    if not requirements.get("narration_required"):
        return {"ok": True, "status": "disabled", "warnings": []}
    path = workspace / "public/audio/narration.timeline.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or not isinstance(report.get("warnings"), list):
            raise ValueError()
    except (OSError, ValueError):
        return {"ok": False, "status": "missing", "warnings": ["缺少旁白时间轴报告，无法核对配音结果"]}
    report = {key: report[key] for key in ("ok", "status", "provider", "voice", "duration_sec", "timing", "warnings") if key in report}
    report["warnings"] = [str(w)[:1000] for w in report["warnings"]][:30]
    audio_candidates = (workspace / "public/audio/narration.mp3", workspace / "audio/full.wav")
    if report.get("ok") and not any(path.is_file() for path in audio_candidates):
        report["ok"] = False
        report["warnings"].append("旁白报告存在但音频文件缺失")
    return report
