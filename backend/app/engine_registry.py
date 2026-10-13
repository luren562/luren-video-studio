"""引擎注册表：opencode 单模式下可挂多个引擎。

- `shotcraft`：电影感产品宣传片（横屏 16:9，预拷模板，平台 TTS 直出时间轴）。
- `talkcraft`：稿→成品配音→字级时间戳→Remotion 的竖屏口播片（9:16，skill 自管运行时）。

平台不重写引擎的 Remotion 场景代码，只把「项目简报 + 工作区脚手架」交给
opencode，由它读 skill 在工作区内自由制作并交付成片。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .video_skills import DIAGRAM_STYLES

if TYPE_CHECKING:
    from .config import Settings
    from .models import VideoStyle


@dataclass(frozen=True)
class EngineSpec:
    key: str
    display_name: str
    dir_name: str
    root: str  # 相对 engines_dir 的子路径
    description: str
    aspect: str
    lang: str
    default_duration_sec: int
    # 该引擎的质检闸（脚本名 -> 说明）；opencode 模式下由 opencode 自审。
    gates: dict[str, str] = field(default_factory=dict)
    # 是否需要成品配音/ASR 管线
    needs_voiceover: bool = False
    # 是否需要外部素材（截图/B-roll）
    needs_assets: bool = False
    # 是否依赖编码 Agent 才能保证质量（无脚本闸的独立审片）
    needs_review_agent: bool = False
    # skill 内注入 opencode 的入口文档（相对 skill 根）；默认回退 shotcraft。
    instructions: tuple[str, ...] = ("references/pipeline.md",)
    # 工作区脚手架方式：template=预拷模板（shotcraft）；skill-runtime=skill 自管运行时（talkcraft）。
    scaffold: str = "template"
    # 音频管线：tts-synth=平台 TTS 直出时间轴；timestamps=成品配音 + 字级时间戳。
    audio_mode: str = "tts-synth"
    # data/engine_runtime/<runtime_name> 与运行时依赖清单（相对引擎目录）。
    runtime_name: str = "shotcraft"
    runtime_package: str = "template/package.json"


ENGINES: dict[str, EngineSpec] = {
    "shotcraft": EngineSpec(
        key="shotcraft",
        display_name="电影感产品宣传片",
        dir_name="video-shotcraft",
        root="template",
        description="由 opencode 读 skill 制作的电影感产品宣传片：真实页面/素材 + 2.5D 运镜 + 卡点 BGM + 声音设计。",
        aspect="16:9",
        lang="zh",
        default_duration_sec=45,
        gates={
            "review": "opencode 自审（vision 子代理，final-review.md 清单）",
        },
        needs_assets=True,
        needs_review_agent=True,
    ),
    "talkcraft": EngineSpec(
        key="talkcraft",
        display_name="口播观点视频",
        dir_name="video-talkcraft",
        root="remotion",
        description="稿→成品配音→字级时间戳→Remotion 的竖屏口播片。",
        aspect="9:16",
        lang="zh",
        default_duration_sec=95,
        gates={"review": "opencode 自审（review-protocol.md）"},
        instructions=("SKILL.md",),
        scaffold="skill-runtime",
        audio_mode="timestamps",
        runtime_name="talkcraft",
        runtime_package="runtime/package.json",
        needs_voiceover=True,
        needs_assets=True,
        needs_review_agent=True,
    ),
}


# 首次启动时写入的默认风格档
DEFAULT_STYLES: list[dict] = [
    {
        "name": "产品宣传片 · 电影感（横屏）",
        "engine": "shotcraft",
        "aspect": "16:9",
        "lang": "zh",
        "default_duration_sec": 45,
        "theme_json": {"accent": "#FFFFFF", "bg": "#0B0B0F", "fg": "#FFFFFF"},
        "engine_config_json": {"bgm": "required", "beat_sync": True},
        "is_default": True,
        "is_active": True,
    },
    {
        "name": "口播 · 观点（竖屏）",
        "engine": "talkcraft",
        "aspect": "9:16",
        "lang": "zh",
        "default_duration_sec": 95,
        "theme_json": {"bg": "#0B0B0F", "fg": "#FFFFFF", "accent": "#FFC91A"},
        "engine_config_json": {"skill_id": "video-talkcraft", "bgm": "optional", "narration": "required"},
        "is_default": False,
        "is_active": True,
    },
] + DIAGRAM_STYLES


def get_engine(key: str) -> EngineSpec:
    try:
        return ENGINES[key]
    except KeyError as exc:
        raise ValueError(f"unknown engine: {key}") from exc


def resolve_engine(style: "VideoStyle | None", settings: "Settings | None" = None) -> EngineSpec:
    """按风格档的 engine 解析引擎；未知/未指定回退 shotcraft（行为等价）。"""
    key = (getattr(style, "engine", None) or "").strip()
    if key in ENGINES:
        return ENGINES[key]
    return ENGINES["shotcraft"]
