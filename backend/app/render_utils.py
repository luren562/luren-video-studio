"""渲染通用小工具（从 render_service 抽取）。

只包含与「引擎无关」的成片后处理：输出唯一名、原子落盘、封面抽帧、哈希。
供 agent 路径与后续改造复用，避免依赖整套结构化渲染服务。
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
import uuid
from pathlib import Path

from loguru import logger

from .config import get_settings


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique_out_path(out_path: Path) -> Path:
    """给 Remotion 一个唯一输出名。

    Remotion 收尾会把 `<out>.remotion-in-progress` 重命名成 `<out>`；Windows 下若 `<out>`
    正被别的进程占用（后端流式预览、杀毒扫描等），重命名会 `EPERM`。用唯一名避开覆盖，
    渲染完再由 `_promote_output` 落到正式路径。
    """
    return out_path.with_name(f"{out_path.stem}.{uuid.uuid4().hex}.mp4")


def _promote_output(rendered: Path, out_path: Path) -> Path:
    """把渲染产物落到正式路径；被占用则保留唯一文件并返回它。"""
    if rendered == out_path:
        return out_path
    for attempt in range(5):
        try:
            os.replace(rendered, out_path)
            return out_path
        except PermissionError:
            time.sleep(0.5 * (attempt + 1))
    logger.warning(f"正式成片被占用，改用唯一文件：{rendered}")
    return rendered


def _cleanup_partial(rendered: Path) -> None:
    for leftover in rendered.parent.glob(f"{rendered.name}*"):
        try:
            leftover.unlink()
        except OSError:
            pass


def extract_poster(video_path: Path, poster_path: Path) -> bool:
    settings = get_settings()
    cmd = [
        settings.ffmpeg_binary,
        "-y",
        "-ss",
        "1",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(poster_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.warning(f"封面抽帧失败：{exc}")
        return False
    return proc.returncode == 0 and poster_path.exists()
