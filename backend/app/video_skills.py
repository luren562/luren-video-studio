"""Select a production skill within the existing Agent runner, not a new execution mode."""
from __future__ import annotations

VIDEO_SKILLS = {
    "video-shotcraft": "电影感产品视频",
    "video-diagram-explainer": "科普图解视频",
    "video-talkcraft": "口播观点视频",
}


def validate_skill_config(config: dict | None) -> None:
    config = config or {}
    skill_id = config.get("skill_id")
    if skill_id is not None and (not isinstance(skill_id, str) or skill_id not in VIDEO_SKILLS):
        raise ValueError("未知视频 skill，请选择已注册的制作能力")
    profile = config.get("visual_profile")
    if skill_id == "video-diagram-explainer" and profile not in (None, "ivory", "midnight", "paper"):
        raise ValueError("科普视觉预设必须是 ivory、midnight 或 paper")


def selected_skill(settings, style=None) -> str:
    config = (style.engine_config_json if style else {}) or {}
    validate_skill_config(config)
    skill = config.get("skill_id")
    if not skill:
        # 未显式指定 skill 时按引擎目录回退（talkcraft → video-talkcraft）。
        from .engine_registry import ENGINES

        engine = getattr(style, "engine", None)
        if engine in ENGINES:
            skill = ENGINES[engine].dir_name
    return skill or settings.agent_skill_dirname


DIAGRAM_STYLES = [
    {
        "name": f"科普图解 · {name}",
        # Keep the existing Agent runtime; skill_id is the production-method selector.
        "engine": "shotcraft", "aspect": "16:9", "lang": "zh",
        "default_duration_sec": 150,
        "theme_json": {"bg": bg, "fg": fg, "accent": accent},
        "engine_config_json": {
            "skill_id": "video-diagram-explainer", "visual_profile": profile,
            "bgm": "optional", "narration": "required",
            "description": "解说驱动的机制演示、人物与流程图、公式和数据比较；使用 Agent 精修制作。",
        },
        "is_default": False, "is_active": True,
    }
    for name, profile, bg, fg, accent in [
        ("米白极简", "ivory", "#FCFAF6", "#282A2D", "#00897B"),
        ("深色技术", "midnight", "#101923", "#F0F4F7", "#55D8C1"),
        ("清晰教材", "paper", "#FFFFFF", "#172B45", "#176BD1"),
    ]
]
