"""工具链：确保 ffmpeg / ffprobe 在 PATH 上可用。

本机原本只有 ffmpeg（无 ffprobe），但引擎侧若干脚本（talkcraft 的 render_shots.mjs、
motion_check 的并发抖动子检、preflight --host）依赖 ffprobe。这里统一兜底：

- `ensure_tool_paths()`：把 `static-ffmpeg` 自带的一套 ffmpeg/ffprobe 注入当前进程 PATH
  （幂等；首次调用可能联网下载，失败则静默降级）。子进程用 `os.environ.copy()` 时会继承。
- `install_ffprobe()`：把 ffprobe 拷到系统 ffmpeg 同目录（真正「装一份」到 PATH），
  供手工运行引擎脚本时也能解析。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from loguru import logger

_injected = False


def ensure_tool_paths() -> dict:
    """把 static-ffmpeg 的 ffmpeg/ffprobe 注入 PATH；返回可用工具路径。"""
    global _injected
    if not _injected:
        _injected = True
        try:
            import static_ffmpeg

            static_ffmpeg.add_paths()
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"static-ffmpeg 注入失败（可忽略）：{exc}")
    return {"ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe")}


def ffprobe_path(default: str = "ffprobe") -> str:
    ensure_tool_paths()
    return shutil.which("ffprobe") or default


def install_ffprobe(target_dir: Path | None = None) -> dict:
    """把 ffprobe（必要时含 ffmpeg）复制到 PATH 目录，使之脱离本进程也可用。"""
    import static_ffmpeg

    if target_dir is None:
        existing = shutil.which("ffmpeg")  # 注入前解析：系统 ffmpeg 目录
        target_dir = Path(existing).parent if existing else Path(os.environ.get("PATH", "").split(os.pathsep)[0])
    static_ffmpeg.add_paths()
    found = shutil.which("ffprobe")
    if not found:
        raise RuntimeError("static-ffmpeg 未提供 ffprobe")
    src = Path(found)
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if src.resolve() == dest.resolve():
        return {"ffprobe": str(dest), "version_source": str(src), "already": True}
    shutil.copyfile(src, dest)
    return {"ffprobe": str(dest), "version_source": str(src), "already": False}
