"""内置创作策略预设（作者风格画像）。`seed_defaults` 按 name 幂等播种并刷新正文。

风格画像正文保存在同目录 `style_assets/`，便于随项目维护，不把大段文本塞进代码。
"""
from pathlib import Path

_ASSETS_DIR = Path(__file__).resolve().parent / "style_assets"


def _read_asset(name: str) -> str:
    path = _ASSETS_DIR / name
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


STYLE_GUIDE_GUANGYU = _read_asset("guangyu.md")

PRESET_STRATEGIES = [
    {
        "name": "光宇 · 数学拆解人生",
        "description": "用数学/物理/心理学/经济学原理拆解人生决策的抖音作者风格",
        "audience": "对认知成长、反常识内容感兴趣的年轻人",
        "tone": "冷静、笃定、有揭示感；第二人称直呼‘你’；不用感叹号煽情",
        "content_goal": "用一个硬核概念重构日常问题，给出可量化、可操作的结论",
        "prompt_rules": (
            "结构：①钩子（反问/两派对立/数据，以设问收尾）→②否定问题本身"
            "→③引信源（年代+学科+人名/效应）→④翻译成人话→⑤场景算账（场景一/二/三，代入数字）"
            "→⑥反直觉结论+把两类人归为‘同一种人’→⑦金句收尾+固定签名。"
            "通篇用‘你’，句长中位 8 字，语速约 320 字/分钟，一句一个信息点。"
            "必须把问题从‘要不要’重构成‘是多少’，并给出可计算的比例/数字。"
        ),
        "banned_phrases": ["加油", "暴富", "只要努力就能成功", "你一定行", "相信奇迹"],
        "style_guide_md": STYLE_GUIDE_GUANGYU,
        "is_default": False,
        "is_active": True,
    },
]
