"""Agent 运行时共享原语（opencode-only 模式）。

从旧 `agent_film.py` 抽取、仅保留 opencode 运行器实际依赖的部分：
工作区脚手架、模型解析、项目简报、候选登记。自研 agent 循环已删除。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent_support import AgentError, atomic_json
from .agent_audio import install_platform_docs
from .config import Settings, get_settings
from .models import (
    AIModel,
    AIProvider,
    ContentStrategy,
    RenderOutput,
    VideoProject,
    VideoStyle,
    VideoVersion,
)
from .runtime_scaffold import ensure_runtime, runtime_root
from .security import decrypt_string
from .video_skills import selected_skill

AGENT_ENGINE = "shotcraft"  # 未指定引擎时的回退标识（路径与行为等价）
FPS = 30
WIDTH, HEIGHT = 1920, 1080
# 平台固定接线：opencode 产出的 Composition id 由交付契约约定。
AGENT_COMPOSITION = "AgentFilm"


@dataclass
class ModelHandle:
    base_url: str
    api_key: str
    model_id: str
    label: str
    capability: str = "text"


@dataclass
class JobContext:
    """把 worker 的落事件/进度/取消钩子带进 agent 运行器。"""

    emit: Callable[[str, str, dict], None] = lambda level, message, data: None
    progress: Callable[[int, int], None] = lambda current, total: None
    cancelled: Callable[[], bool] = lambda: False


# ---------------------------------------------------------------------------
# 目录
# ---------------------------------------------------------------------------
def runtime_dir(settings: Settings) -> Path:
    return runtime_root(settings)


def skill_root(settings: Settings, style: VideoStyle | None = None) -> Path:
    return settings.engines_dir / selected_skill(settings, style)


def workspace_root(settings: Settings, project_id: int) -> Path:
    return runtime_dir(settings) / "projects" / f"_agent_{project_id}"


def remotion_dir(settings: Settings, project_id: int) -> Path:
    return workspace_root(settings, project_id) / "remotion"


# ---------------------------------------------------------------------------
# 模型解析
# ---------------------------------------------------------------------------
def resolve_agent_model(db: Session, settings: Settings, model_id: int | None = None,
                        *, review: bool = False) -> ModelHandle:
    """显式模型不回退；制作与审片分别选择。"""
    def handle(row: AIModel) -> ModelHandle:
        key = decrypt_string(row.provider.encrypted_api_key) if row.provider.encrypted_api_key else ""
        return ModelHandle(row.provider.base_url, key, row.model_id,
                           f"{row.provider.name}/{row.model_id}", row.capability)

    if model_id is not None:
        row = db.get(AIModel, model_id)
        if not row or not row.is_active or not row.provider or not row.provider.is_active:
            raise AgentError(f"所选制作模型不可用（id={model_id}），请启用或更换模型")
        return handle(row)
    caps: list[str] = []
    preferred = ((settings.agent_review_model_capability,) if review else
                 (settings.agent_model_capability, "agent", "text", "vision"))
    for cap in preferred:
        if cap and cap not in caps:
            caps.append(cap)
    for cap in caps:
        rows = list(db.scalars(
            select(AIModel)
            .join(AIProvider, AIModel.provider_id == AIProvider.id)
            .where(
                AIModel.is_active.is_(True),
                AIProvider.is_active.is_(True),
                AIModel.capability == cap,
            )
            .order_by(AIModel.id)
        ).all())
        if review:
            rows.sort(key=lambda row: (1 if any(token in (row.model_id or "").lower()
                                                for token in ("pro", "thinking")) else 0, row.id))
        for row in rows:
            if row is not None and row.provider is not None:
                return handle(row)
    raise AgentError(
        "没有可用的 agent/vision 模型：请在后台「AI 供应商」添加供应商与模型"
        f"（capability={settings.agent_model_capability}）"
    )


# ---------------------------------------------------------------------------
# 简报与工作区
# ---------------------------------------------------------------------------
def _brief_hash(brief: str) -> str:
    """项目简报指纹：标题/题材/时长/风格任一变化都会改变它。"""
    return hashlib.sha256(brief.encode("utf-8")).hexdigest()


def _workspace_owner(project: VideoProject, version_number: int) -> str:
    """工作区归属令牌：项目 id + 创建时间 + 版本。"""
    created = getattr(project, "created_at", None)
    parts = [str(getattr(project, "id", "")), str(version_number)]
    if created is not None:
        parts.append(str(created))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _bootstrap_workspace(
    settings: Settings,
    project: VideoProject,
    version_number: int = 1,
    *,
    brief_hash: str | None = None,
    style: VideoStyle | None = None,
    engine=None,
    review_required: bool = True,
) -> Path:
    # engine=None 时保持旧调用（1 参）以兼容既有测试与默认回退。
    rt = ensure_runtime(settings, engine) if engine is not None else ensure_runtime(settings)
    ws = workspace_root(settings, project.id) / "versions" / f"v{version_number}"
    remotion = ws / "remotion"
    marker = ws / "initialized.json"
    owner = _workspace_owner(project, version_number)
    if marker.exists():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
        if data.get("owner") not in (None, owner):
            # 同一路径被另一个项目占用（id 复用）：隔离旧工程，重建一个干净的。
            stale = ws.with_name(f"{ws.name}-stale-{uuid.uuid4().hex[:8]}")
            try:
                ws.rename(stale)
                logger.warning(f"工作区归属不符，已隔离旧工程：{stale}")
            except OSError:
                shutil.rmtree(ws, ignore_errors=True)
        else:
            updated = {**data, "owner": owner}
            if brief_hash is not None:
                updated["brief_hash"] = brief_hash
            if updated != data:
                atomic_json(marker, updated)
            install_platform_docs(remotion, engine, review_required=review_required)
            return remotion
    if remotion.is_dir() and any(remotion.iterdir()):
        atomic_json(marker, {'project_id': project.id, 'version': version_number, 'owner': owner,
                             'brief_hash': brief_hash, 'recovered_existing': True})
        install_platform_docs(remotion, engine, review_required=review_required)
        return remotion
    remotion.mkdir(parents=True, exist_ok=True)
    skill = skill_root(settings, style)
    scaffold = getattr(engine, "scaffold", "template") or "template"
    if scaffold == "template":
        template = skill / "template"
        if template.is_dir():
            for item in template.iterdir():
                if item.name in ("node_modules", ".git", "out"):
                    continue
                dest = remotion / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True,
                                    ignore=shutil.ignore_patterns("node_modules", ".git", "out"))
                else:
                    shutil.copyfile(item, dest)
        # 把 skill 的配方卡实现与卡文复制进工程，便于本地读取/拷贝（跳过 workbench/.git/gallery 等大目录）
        refs = remotion / "refs"
        for rel in ("demos", "references"):
            src = skill / rel
            if src.is_dir():
                shutil.copytree(src, refs / rel, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("node_modules", ".git"))
    # skill-runtime（talkcraft）：只建空 remotion/ + 最小 package.json，
    # 工程与运行时由 skill 自管的脚本（link-runtime.sh / check-runtime.sh）搭建。
    (remotion / "package.json").write_text(
        json.dumps({"name": f"agent-film-{project.id}", "private": True}, indent=2), encoding="utf-8"
    )
    logger.info(f"agent 工程已初始化：{remotion}（skill={skill}，scaffold={scaffold}，runtime={rt}）")
    atomic_json(marker, {"project_id": project.id, "version": version_number, "owner": owner,
                         "brief_hash": brief_hash})
    install_platform_docs(remotion, engine, review_required=review_required)
    return remotion


def _brief(project: VideoProject, style: VideoStyle | None, settings: Settings | None = None,
           strategy: ContentStrategy | None = None) -> str:
    settings = settings or get_settings()
    theme = {"accent": "#FFFFFF", **((style.theme_json if style else {}) or {}), **(project.theme_json or {})}
    config = (style.engine_config_json if style else {}) or {}
    bgm_enabled = project.bgm_enabled if project.bgm_enabled is not None else config.get("bgm") == "required"
    narration = project.tts_enabled if project.tts_enabled is not None else config.get("narration") != "none"
    narration = bool(settings.tts_enabled and narration)
    from .tts_providers import normalize_rate, resolve_voice
    provider = "manual" if project.tts_asset_id else settings.tts_provider
    voice = resolve_voice(provider, project.tts_voice, settings) if narration else None
    project_rate = getattr(project, "tts_rate", None)
    try:
        rate = normalize_rate(project_rate) if project_rate is not None else normalize_rate(settings.tts_rate)
    except ValueError:
        rate = settings.tts_rate or "+0%"
    aspect = style.aspect if style else "16:9"
    return json.dumps(
        {
            "title": project.title,
            "topic": project.topic,
            "audience": project.audience,
            "goal": project.goal,
            "source_notes": project.source_notes,
            "constraints": project.constraints,
            "reference_url": project.reference_url,
            "lang": project.lang,
            "duration_target_sec": project.duration_target_sec,
            "theme": theme,
            "style": {"name": style.name if style else "", "aspect": aspect, "engine_config": config,
                      "skill_id": selected_skill(settings, style)},
            "strategy": (
                {
                    "name": strategy.name,
                    "tone": strategy.tone,
                    "audience": strategy.audience,
                    "content_goal": strategy.content_goal,
                    "prompt_rules": strategy.prompt_rules,
                    "banned_phrases": list(strategy.banned_phrases_json or []),
                }
                if strategy
                else None
            ),
            "requirements": {
                "dimensions": [1080, 1920] if aspect == "9:16" else [1080, 1080] if aspect == "1:1" else [WIDTH, HEIGHT],
                "accent": theme["accent"],
                "narration_required": narration,
                "narration_lang": "zh",
                "tts_provider": provider,
                "tts_voice": voice,
                "tts_rate": rate,
                "tts_manual_upload": bool(project.tts_asset_id),
                "bgm_enabled": bgm_enabled,
                "bgm_required": bgm_enabled,
                # 未显式设置（None）时按需要审片处理，保持旧行为。
                "review_required": getattr(project, "review_required", True) is not False,
            },
        },
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------------------
# 候选登记
# ---------------------------------------------------------------------------
def _gate(key: str, name: str, passed: bool, detail: str) -> dict:
    return {"key": key, "name": name, "status": "pass" if passed else "fail", "detail": detail}


def _register_candidate(db: Session, project: VideoProject, version: VideoVersion,
                        candidate: dict, model: ModelHandle, engine=None,
                        *, review_required: bool = True) -> RenderOutput:
    """同一不可变候选幂等更新；预览成功即入库为草稿。"""
    from .render_utils import extract_poster, _sha256
    path = Path(candidate["path"])
    output = db.scalar(select(RenderOutput).where(RenderOutput.version_id == version.id,
                                                  RenderOutput.file_path == str(path)))
    created = output is None
    if output is None:
        poster = path.with_suffix(".jpg")
        try:
            extract_poster(path, poster)
        except Exception as exc:
            logger.warning(f"候选封面提取失败：{exc}")
        meta = candidate["meta"]
        output = RenderOutput(project_id=project.id, version_id=version.id,
                              engine=getattr(engine, "key", None) or AGENT_ENGINE,
                              width=meta["width"], height=meta["height"], fps=round(meta["fps"]),
                              duration_frames=meta["frames"], file_path=str(path),
                              poster_path=str(poster) if poster.exists() else "", sha256=_sha256(path), status="draft")
        db.add(output)
        db.flush()  # 取得 output.id 以便登记封面任务
    output.review_json = candidate.get("review", {})
    output.status = 'draft'
    review = candidate.get("review", {})
    if review_required:
        review_gate = _gate("review", "需求与画面终检", review.get("approved") is True,
                            "；".join(i["detail"] for i in review.get("issues", []))
                            or ("已通过" if review.get("approved") else "尚未完成需求终检"))
    else:
        review_gate = {"key": "review", "name": "需求与画面终检", "status": "skip", "detail": "未启用审片"}
    output.gates_json = {"render_ok": True, "passed": False, "draft": True, "gates": [*candidate["gates"], review_gate],
                         "blocking": True,
                         "agent": {"model": candidate.get("creator_model", model.label), "candidate_id": candidate["id"],
                                   "source_hash": candidate["source_hash"], "snapshot": candidate["snapshot"],
                                   "composition": candidate["composition"],
                                   "run_summary": candidate.get("run_summary", {})}}
    db.commit()
    return output
