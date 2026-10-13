"""AI 主题封面生成（OpenAI 兼容 /images/generations）。

职责：由项目主题/标题/风格拼出「炫酷且符合主题」的大片感封面提示词，调用**全局封面配置**
（独立于生产模型列表）生图，落盘到成片同目录 `<video>.cover.<ext>`。标题文字交给模型出图。
"""

from __future__ import annotations

import base64
from pathlib import Path

import httpx
from loguru import logger

from .ai_client import AIError, image_generation
from .config import get_settings
from .models import RenderOutput, VideoProject

# 风格基调：炫酷、电影海报质感
STYLE_HINTS = (
    "炫酷电影海报质感，戏剧化侧逆光，高对比度，丰富的色彩层次，"
    "强烈的视觉冲击力与纵深感，精致细节，专业级构图"
)


def _aspect_size(width: int, height: int) -> str:
    if height > width:
        return "1024x1792"
    if width > height:
        return "1792x1024"
    return "1024x1024"


def build_cover_prompt(project: VideoProject, output: RenderOutput) -> str:
    """把项目信息拼成封面提示词（含标题文字要求，文字由模型直接呈现）。"""
    title = (project.title or project.topic or "").strip()
    topic = (project.topic or "").strip()
    theme = project.theme_json or {}
    accent = str(theme.get("accent") or "").strip()
    parts = ["为一段中文短视频设计一张主题封面"]
    if topic:
        parts.append(f"主题：{topic}")
    if title:
        parts.append(f'画面中以醒目、美观的中文艺术字清晰呈现标题「{title}」')
    if accent:
        parts.append(f"主色调贴近 {accent}")
    parts.append(f"风格：{STYLE_HINTS}")
    parts.append("主体明确、背景大气，适合作为视频封面")
    return "，".join(parts) + "。"


def _decode_image(result, settings) -> bytes:
    if result.b64_json:
        raw = result.b64_json.split(",")[-1]  # 容忍 data:image/...;base64, 前缀
        try:
            return base64.b64decode(raw)
        except (ValueError, TypeError) as exc:
            raise AIError("invalid_response", "生图 base64 解码失败") from exc
    if result.url:
        try:
            with httpx.Client(timeout=settings.cover_timeout_seconds, follow_redirects=True) as client:
                resp = client.get(result.url)
                resp.raise_for_status()
                return resp.content
        except httpx.HTTPError as exc:
            raise AIError("network_error", "封面图片下载失败") from exc
    raise AIError("invalid_response", "生图返回既无 b64_json 也无 url")


def generate_cover(project: VideoProject, output: RenderOutput, config: dict, *,
                   settings=None) -> Path:
    """用全局封面配置生成封面并落盘，返回文件路径。失败抛 AIError。

    ``config`` 形如 ``{"base_url","api_key","model","size"}``（api_key 已解密）。
    """
    settings = settings or get_settings()
    base_url = str(config.get("base_url") or "").strip()
    model = str(config.get("model") or "").strip()
    if not base_url or not model:
        raise AIError("configuration", "尚未配置 AI 主题封面模型（请在设置页填写）")
    size = str(config.get("size") or "").strip() or _aspect_size(output.width, output.height)
    result = image_generation(
        base_url=base_url,
        api_key=str(config.get("api_key") or ""),
        model=model,
        prompt=build_cover_prompt(project, output),
        size=size,
    )
    content = _decode_image(result, settings)
    if not content:
        raise AIError("invalid_response", "生图返回空内容")
    suffix = ".png" if content[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"
    base = Path(output.file_path) if output.file_path else settings.renders_dir / f"output-{output.id}.mp4"
    target = base.with_suffix(f".cover{suffix}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    logger.info(f"主题封面已生成：{target}（model={model}）")
    return target
