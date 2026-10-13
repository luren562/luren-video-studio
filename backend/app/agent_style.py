"""把创作策略（作者风格画像）写成工作区风格指令文档。

生成时写入 `<workspace>/.opencode/platform/style.md`，并通过 `opencode.json`
的 `instructions` 挂载，使风格优先级高于 skill 默认。
"""
from __future__ import annotations

from pathlib import Path

from .models import ContentStrategy

STYLE_DOC_REL = ".opencode/platform/style.md"


def build_style_doc(strategy: ContentStrategy) -> str:
    parts = ["# 创作风格要求（平台注入，优先级高于 skill 默认）\n"]
    if strategy.style_guide_md:
        parts.append(strategy.style_guide_md.strip())
    if strategy.tone:
        parts.append(f"\n## 语气\n{strategy.tone}")
    if strategy.prompt_rules:
        parts.append(f"\n## 结构/写法规则\n{strategy.prompt_rules}")
    if strategy.banned_phrases_json:
        parts.append("\n## 禁止出现的表达\n- " + "\n- ".join(strategy.banned_phrases_json))
    return "\n".join(parts) + "\n"


def install_style_doc(workspace: Path, strategy: ContentStrategy | None) -> Path | None:
    if strategy is None:
        return None
    doc = workspace / STYLE_DOC_REL
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(build_style_doc(strategy), encoding="utf-8")
    return doc
