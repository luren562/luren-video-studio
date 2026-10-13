"""opencode headless 运行器：用 opencode 作为 agent 大脑，取代自研循环。

职责（详见 AGENT_OPENCODE_MIGRATION_PLAN_2026-10-03.md）：
- 复用既有工作区脚手架（`_bootstrap_workspace`）与简报（`_brief`）。
- 每项目版本启动一个 opencode server（cwd=工作区），生成 `opencode.json` 并挂载 skill。
- 发送简报，桥接 opencode 事件到 PipelineEvent，看门狗盯墙钟/取消/预算。
- 完成信号：`out/final.mp4` + `out/finish.json`；随后平台校验、快照、入库。

放开命令模式：opencode 在工作区内自由使用 bash/edit/read/write 与 skill 自带的脚本，
平台不再提供工具白名单，仅保留工作区脚手架、事件桥接、看门狗与交付落库。
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent_runtime import (
    AGENT_COMPOSITION,
    JobContext,
    ModelHandle,
    _bootstrap_workspace,
    _brief,
    _brief_hash,
    _gate,
    _register_candidate,
    resolve_agent_model,
    skill_root,
    workspace_root,
)
from .agent_support import (
    AgentCancelled,
    AgentError,
    AgentStopped,
    atomic_json,
    execution_lock,
    input_hash,
    probe_video,
    snapshot_inputs,
)
from .config import Settings, get_settings
from .agent_audio import audio_environment, read_audio_report
from .agent_style import STYLE_DOC_REL, install_style_doc
from .engine_registry import resolve_engine
from .models import (
    ContentStrategy,
    MediaAsset,
    RenderOutput,
    VideoProject,
    VideoStyle,
    VideoVersion,
)
from .opencode_client import OpencodeClient, OpencodeError, start_server

FINAL_VIDEO_REL = "out/final.mp4"
FINISH_JSON_REL = "out/finish.json"
CONFIG_FILENAME = "opencode.json"
EVENT_TAIL = 40
# deny 策略下仍观测到 question.asked 时，超过该秒数即主动中止，避免空等到墙钟。
QUESTION_BLOCK_SECONDS = 60.0


# ---------------------------------------------------------------------------
# 配置与 skill 挂载（纯函数，便于单测）
# ---------------------------------------------------------------------------
def _model_attachment(capability: str) -> bool:
    """capability 含 vision/image 时，模型条目声明 attachment，opencode 才会把图片喂给模型。"""
    caps = {c.strip().lower() for c in (capability or "").split(",")}
    return bool(caps & {"vision", "image"})


def opencode_config(settings: Settings, model: ModelHandle, skill_name: str,
                    engine=None, extra_docs: list[str] | None = None) -> dict:
    """生成写入工作区的 opencode.json。

    用自定义 provider（`@ai-sdk/openai-compatible`）显式注册模型，避免内置 provider
    只认 models.dev 目录里的模型。密钥走 {env:...}，不落盘明文。
    `engine` 决定 skill 入口文档；为 None 时回退 shotcraft 的 `references/pipeline.md`。
    `extra_docs`（如作者风格文档）默认不追加，保持现有输出不变。
    """
    provider_id = settings.opencode_provider_id
    entry: dict = {"name": model.model_id}
    if _model_attachment(model.capability):
        entry["attachment"] = True
    config: dict = {
        "$schema": "https://opencode.ai/config.json",
        "autoupdate": False,
        "share": "disabled",
        "snapshot": False,
        "model": f"{provider_id}/{model.model_id}",
        "small_model": f"{provider_id}/{model.model_id}",
        "provider": {
            provider_id: {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Video Foundry Gateway",
                "options": {
                    "baseURL": "{env:VFO_BASE_URL}",
                    "apiKey": "{env:VFO_API_KEY}",
                },
                "models": {
                    model.model_id: entry,
                },
            }
        },
        # 放开命令：工作区内自由执行；question 工具按策略拒绝，避免无人回答时空转到墙钟。
        "permission": {"*": "allow"},
    }
    if getattr(settings, "agent_question_policy", "deny") == "deny":
        config["permission"]["question"] = "deny"
    if engine is None:
        instructions = [f".opencode/skills/{skill_name}/references/pipeline.md", ".opencode/platform/audio.md"]
    else:
        instructions = [f".opencode/skills/{skill_name}/{doc}" for doc in engine.instructions]
        instructions.append(".opencode/platform/audio.md")
    instructions.append(".opencode/platform/review.md")
    if extra_docs:
        instructions.extend(extra_docs)
    config["instructions"] = instructions
    return config


def import_skill(workspace: Path, skill: Path) -> Path:
    """把引擎 skill 挂到工作区 `.opencode/skills/<name>`（优先 junction/软链，失败则复制）。"""
    dest = workspace / ".opencode" / "skills" / skill.name
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(skill, dest, target_is_directory=True)
        return dest
    except OSError:
        pass
    if os.name == "nt":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(dest), str(skill)],
                                capture_output=True, text=True)
        if result.returncode == 0:
            return dest
    shutil.copytree(skill, dest, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("node_modules", ".git", "out"))
    return dest


def write_config(workspace: Path, config: dict) -> Path:
    path = workspace / CONFIG_FILENAME
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def detect_completion(workspace: Path) -> dict | None:
    """完成信号：final.mp4 存在即视为可交付；finish.json 提供元数据（缺失也接受）。"""
    final = workspace / FINAL_VIDEO_REL
    if not final.is_file():
        return None
    finish: dict = {}
    finish_path = workspace / FINISH_JSON_REL
    if finish_path.is_file():
        try:
            finish = json.loads(finish_path.read_text(encoding="utf-8"))
        except ValueError:
            finish = {}
    return {"video": str(final), "finish": finish}


def build_prompt(brief: str, requirements: dict, skill_name: str,
                 review_required: bool = True) -> str:
    """发给 opencode 的首轮指令：读 skill、按简报制作、产出完成信号。

    `review_required=False` 时不再要求抽帧自审（与平台 review.md 开关一致），默认保持旧行为。
    """
    review_line = (
        "- 先规划再制作，完成后自审画面与音画同步，再写完成信号。\n"
        if review_required else
        "- 本项目关闭了视觉审片：**不要**执行 `npx remotion still` 抽帧、不要读图自审，直接产出成片与完成信号。\n"
    )
    return (
        f"使用 skill「{skill_name}」完成一支视频。工作区就是当前目录，remotion 工程在根目录下。\n\n"
        f"## 项目简报\n{brief}\n\n"
        f"## 交付契约（务必照做）\n"
        f"- 在 `out/` 下产出成片 `{FINAL_VIDEO_REL}`（必须含音轨）。\n"
        f"- 口播片请把最终成片命名为 `{FINAL_VIDEO_REL}`（talkcraft 的 `render_shots --mux` 产物拷一份即可）。\n"
        f"- 额外写 `{FINISH_JSON_REL}`，JSON 至少包含：\n"
        f'  {{"composition": "<Composition id>", "entry": "src/index.ts", "duration_sec": <number>, '
        f'"review": {{"approved": <bool>, "issues": []}}, "summary": "<一句话>"}}\n'
        f"- 主题色与配音/BGM 按 `.opencode/platform/audio.md` 执行；平台要求优先于 skill 默认。\n"
        f"- 若存在 `.opencode/platform/style.md`，写作与口播稿必须遵守其中的作者风格要求。\n"
        f"- 全片主色必须用 requirements.accent；bgm_enabled=false 时只保留旁白/SFX，文件仍为 final.mp4。\n"
        f"- 只在当前工作区内读写，不要修改 node_modules 或工作区外的文件。\n\n"
        f"## 硬性要求\n"
        f"- 目标时长**大致把握即可**（不必精确到秒），尺寸见 requirements：{json.dumps(requirements, ensure_ascii=False)}。\n"
        f"{review_line}"
        f"- **整片只渲染一次**：产出 `{FINAL_VIDEO_REL}` 与 `{FINISH_JSON_REL}` 后请立即结束，不要反复重渲或补写额外文档。\n"
    )


# ---------------------------------------------------------------------------
# 事件 / 摘要
# ---------------------------------------------------------------------------
def summarize_event(event: dict) -> tuple[str, str, dict]:
    """把 opencode 事件压成 (level, message, data)。事件 schema 未知时也不崩。"""
    etype = str(event.get("type", "") or "event")
    props = event.get("properties") or event.get("data") or {}
    if not isinstance(props, dict):
        props = {"value": props}
    level = "error" if "error" in etype else "info"
    message = f"opencode:{etype}"
    detail = props.get("text") or props.get("message") or props.get("name") or props.get("tool")
    if detail:
        message = f"{message} {str(detail)[:200]}"
    data = {"event": etype, "properties": props}
    return level, message, data


# 流式碎片事件直接丢弃，避免每条 token 都写库。
_NOISY_EVENTS = {"message.part.delta", "server.heartbeat"}


def describe_event(event: dict, *, question_policy: str = "deny") -> tuple[str, str, dict] | None:
    """把 opencode 事件压成值得落库的一条；噪音返回 None。"""
    etype = str(event.get("type", "") or "")
    props = event.get("properties") or event.get("data") or {}
    if not isinstance(props, dict):
        props = {}
    if etype in _NOISY_EVENTS:
        return None
    if etype == "question.asked":
        questions = props.get("questions")
        first = questions[0] if isinstance(questions, list) and questions else {}
        if not isinstance(first, dict):
            first = {}
        header = first.get("header") or first.get("question") or ""
        data = {"event": etype, "questions": questions, "question_policy": question_policy}
        return "warning", f"agent 提问（策略={question_policy}）：{header}", data
    if etype == "message.part.updated":
        part = props.get("part") or {}
        if not isinstance(part, dict):
            return None
        if part.get("type") == "tool":
            tool = part.get("tool") or part.get("name") or "tool"
            state = part.get("state") or {}
            status = state.get("status") or part.get("status") or ""
            title = state.get("title") or ""
            detail = " ".join(str(x) for x in (tool, status, title) if x)
            return "info", f"工具 {detail}".strip(), {"event": etype, "tool": tool, "status": status}
        # 文本/推理增量不落库（由 delta 流式产生）
        return None
    if etype == "session.error":
        err = props.get("error") or {}
        message = (err.get("data") or {}).get("message") if isinstance(err, dict) else ""
        return "error", f"opencode 出错：{message or err}", {"event": etype, "error": err}
    level, message, data = summarize_event(event)
    return level, message, data


def extract_usage(event: dict, usage: dict) -> None:
    """尽力从事件里累计 token usage；字段名不确定时忽略。"""
    props = event.get("properties") or event.get("data") or {}
    if not isinstance(props, dict):
        return
    tokens = props.get("tokens") or props.get("usage")
    if not isinstance(tokens, dict):
        info = props.get("info")
        tokens = info.get("tokens") if isinstance(info, dict) else None
    if not isinstance(tokens, dict):
        return
    for key, aliases in (
        ("prompt_tokens", ("input", "prompt", "prompt_tokens")),
        ("completion_tokens", ("output", "completion", "completion_tokens")),
        ("reasoning_tokens", ("reasoning", "reasoning_tokens")),
        ("cached_tokens", ("cache_read", "cached", "cached_tokens")),
    ):
        for alias in aliases:
            value = tokens.get(alias)
            if isinstance(value, (int, float)):
                usage[key] = usage.get(key, 0) + int(value)
                break


def build_summary(*, status: str, usage: dict, candidate_count: int, stop_reason: dict | None,
                  session_id: str, model_label: str, iterations: int, opencode_version: str,
                  last_event: str) -> dict:
    """前端兼容的 agent_run 摘要（沿用 AgentRunSummary 字段并加 opencode 块）。"""
    return {
        "schema_version": 2,
        "phase": "build_verify",
        "phase_label": "opencode 制作",
        "status": status,
        "usage": {"total_tokens": sum(usage.get(k, 0) for k in (
            "prompt_tokens", "completion_tokens")), **usage},
        "candidate_count": candidate_count,
        "inspections": 0,
        "render_attempts": 0,
        "iteration": iterations,
        "max_iters": 0,
        "last_tool": last_event,
        "updated_at": time.time(),
        "stop_reason": stop_reason,
        "opencode": {"session_id": session_id, "model": model_label, "version": opencode_version},
    }


# ---------------------------------------------------------------------------
# 运行入口
# ---------------------------------------------------------------------------
def run_agent_opencode(db: Session, project: VideoProject, version: VideoVersion,
                       ctx: JobContext | None = None, settings: Settings | None = None,
                       *, grant_render: bool = False) -> RenderOutput:
    settings = settings or get_settings()
    with execution_lock(workspace_root(settings, project.id) / ".execution.lock"):
        return _run(db, project, version, ctx or JobContext(), settings, grant_render=grant_render)


def _finalize(db: Session, project: VideoProject, version: VideoVersion, model: ModelHandle,
              workspace: Path, completion: dict, ctx: JobContext, summary: dict,
              settings: Settings | None = None, engine=None) -> RenderOutput:
    """校验成片、快照源码、登记成片并标记完成。"""
    final = Path(completion["video"])
    meta = probe_video(final)
    finish = completion.get("finish") or {}
    review = finish.get("review") if isinstance(finish.get("review"), dict) else {}
    settings = settings or get_settings()
    requirements = (version.generation_input_json or {}).get("requirements", {})
    review_required = requirements.get("review_required", True) is not False
    audio_report = read_audio_report(workspace, requirements)
    for warning in audio_report["warnings"]:
        ctx.emit("warning", f"配音：{warning}", {"provider": audio_report.get("provider"), "timing": audio_report.get("timing")})
    audio_ok = not (requirements.get("narration_required") and settings.tts_required and not audio_report.get("ok"))
    snapshot = workspace / ".agent" / "candidates" / f"{hashlib.sha256(str(final).encode()).hexdigest()[:16]}.zip"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot_inputs(workspace, snapshot)
    candidate = {
        "id": hashlib.sha256(str(final).encode("utf-8")).hexdigest()[:16],
        "path": str(final),
        "meta": meta,
        "gates": [
            _gate("frame_assert", "成片可解析", True, f"{meta['width']}x{meta['height']}@{meta['fps']:.0f}"),
            _gate("audio", "含音轨", bool(meta.get("has_audio")), "已含音轨" if meta.get("has_audio") else "无音轨"),
            _gate("narration", "旁白合成", audio_ok, audio_report.get("status", "unknown")),
        ],
        "source_hash": input_hash(workspace),
        "snapshot": str(snapshot),
        "composition": finish.get("composition") or AGENT_COMPOSITION,
        "creator_model": model.label,
        "review": review,
        "run_summary": summary,
    }
    output = _register_candidate(db, project, version, candidate, model, engine,
                                 review_required=review_required)
    passed = bool(meta.get("has_audio")) and audio_ok
    output.status = "gates_passed" if passed else "draft"
    output.gates_json = {**output.gates_json, "passed": passed, "draft": not passed, "blocking": not passed,
                         "tts": audio_report,
                         "agent": {**output.gates_json.get("agent", {}), "summary": finish.get("summary", "")}}
    project.status = "rendered" if passed else "needs_attention"
    project.error_message = "" if passed else "成片已保存，但缺少音轨或必需的中文旁白"
    if not passed:
        summary = {**summary, "status": "needs_attention", "stop_reason": {"code": "audio_missing", "detail": project.error_message}}
        version.generation_meta_json = {**(version.generation_meta_json or {}), "agent_run": summary}
    if not db.scalar(select(MediaAsset).where(MediaAsset.path == output.file_path)):
        path = Path(output.file_path)
        db.add(MediaAsset(source_type="render", filename=path.name, path=str(path), mime="video/mp4",
                          sha256=output.sha256, size_bytes=path.stat().st_size,
                          width=output.width, height=output.height,
                          metadata_json={"project_id": project.id, "version_id": version.id, "agent": True}))
    db.commit()
    ctx.emit("info" if passed else "warning", "opencode 成片验收完成" if passed else project.error_message,
             {"output_id": output.id, "file": output.file_path})
    return output


def _run(db: Session, project: VideoProject, version: VideoVersion, ctx: JobContext,
         settings: Settings, *, grant_render: bool = False) -> RenderOutput:
    style = db.get(VideoStyle, project.style_id) if project.style_id else None
    engine = resolve_engine(style, settings)
    skill = skill_root(settings, style)
    if not skill.is_dir():
        raise AgentError(f"skill 仓库未接入：{skill}")

    model = resolve_agent_model(db, settings, project.model_id)
    strategy = db.get(ContentStrategy, project.strategy_id) if project.strategy_id else None
    brief = _brief(project, style, settings, strategy)
    requirements = json.loads(brief).get("requirements", {})
    review_required = requirements.get("review_required", True) is not False
    workspace = _bootstrap_workspace(settings, project, version.version_number,
                                     brief_hash=_brief_hash(brief), style=style, engine=engine,
                                     review_required=review_required)
    # bootstrap 对已存在工作区会提前 return，风格文档仍需每次刷新写入。
    install_style_doc(workspace, strategy)
    manual_file = ""
    if project.tts_asset_id and requirements["narration_required"]:
        asset = db.get(MediaAsset, project.tts_asset_id)
        if not asset or not Path(asset.path).is_file():
            raise AgentError("上传的旁白音频已不存在，请重新选择")
        dest = workspace / "public/audio" / ("uploaded-narration" + Path(asset.path).suffix)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(asset.path, dest)
        manual_file = dest.relative_to(workspace).as_posix()
    import_skill(workspace, skill)
    config = opencode_config(settings, model, skill.name, engine,
                             extra_docs=[STYLE_DOC_REL] if strategy else None)
    write_config(workspace, config)

    version.generation_input_json = json.loads(brief)
    version.generation_meta_json = {
        **(version.generation_meta_json or {}),
        "mode": "agent", "runner": "opencode", "workspace": str(workspace), "skill_id": skill.name,
        "model": model.label, "agent_run": build_summary(
            status="running", usage={}, candidate_count=0, stop_reason=None, session_id="",
            model_label=model.label, iterations=0, opencode_version="", last_event=""),
    }
    db.commit()

    password = settings.opencode_server_password or hashlib.sha256(os.urandom(32)).hexdigest()[:24]
    server = start_server(
        workspace, binary=settings.opencode_binary, password=password,
        hostname=settings.opencode_hostname, port=settings.opencode_port or None,
        env={"VFO_BASE_URL": model.base_url, "VFO_API_KEY": model.api_key,
             **audio_environment(settings, requirements, manual_file=manual_file)},
        start_timeout=settings.opencode_start_timeout_seconds,
    )
    ctx.emit("info", f"opencode server 已启动：{server.base_url}", {"model": model.label})

    usage: dict = {}
    last_event = {"type": ""}
    session: dict = {}
    stop_flag = threading.Event()
    event_queue: "queue.Queue[dict]" = queue.Queue()
    question_policy = getattr(settings, "agent_question_policy", "deny")
    question_state = {"seen_at": None}

    def consume_events() -> None:
        """后台线程只读事件并入队；绝不触碰 DB / ctx（Session 非线程安全）。"""
        client = OpencodeClient(server.base_url, password=password)
        while not stop_flag.is_set():
            try:
                for event in client.iter_events(cancel=stop_flag.is_set):
                    if stop_flag.is_set():
                        return
                    event_queue.put(event)
            except OpencodeError as exc:
                logger.warning(f"opencode 事件流断开，稍后重连：{exc}")
                if stop_flag.wait(settings.opencode_event_reconnect_seconds):
                    return

    last_message = {"text": None}

    def drain_events() -> None:
        """主线程统一把排队事件落库并累计 usage；连续重复事件只落一次。"""
        while True:
            try:
                event = event_queue.get_nowait()
            except queue.Empty:
                return
            etype = str(event.get("type", "") or "")
            last_event["type"] = etype
            extract_usage(event, usage)
            described = describe_event(event, question_policy=question_policy)
            if described is not None and described[1] != last_message["text"]:
                last_message["text"] = described[1]
                ctx.emit(*described)
            if etype == "question.asked" and question_policy == "deny" and question_state["seen_at"] is None:
                # deny 策略下不应再出现提问；记录起点，超过阈值后兜底中止。
                question_state["seen_at"] = time.monotonic()
                logger.warning("opencode 在 deny 策略下仍发起提问，等待兜底中止")

    try:
        session = server.client.create_session(title=f"v{version.version_number} {project.title}"[:120])
        session_id = str(session.get("id") or session.get("sessionID") or "")
        if not session_id:
            raise AgentError(f"opencode 未返回 session id：{session}")
        ctx.emit("info", f"opencode session 已创建：{session_id}", {})
        server.client.prompt_async(session_id,
                                   build_prompt(brief, requirements, skill.name,
                                                review_required=review_required),
                                   model={"providerID": settings.opencode_provider_id, "modelID": model.model_id})

        events_thread = threading.Thread(target=consume_events, name="opencode-events", daemon=True)
        events_thread.start()

        deadline = time.monotonic() + settings.agent_wall_seconds
        completion: dict | None = None
        stop_reason: dict | None = None
        while time.monotonic() < deadline:
            drain_events()
            if ctx.cancelled():
                server.client.abort(session_id)
                stop_reason = {"code": "cancelled", "detail": "任务已取消"}
                break
            q_at = question_state["seen_at"]
            if q_at is not None and time.monotonic() - q_at > QUESTION_BLOCK_SECONDS:
                server.client.abort(session_id)
                stop_reason = {"code": "question_blocked",
                               "detail": "agent 提问无人回答，已按 question 策略中止，避免空转到墙钟"}
                break
            found = detect_completion(workspace)
            if found and server.client.is_idle(session_id):
                completion = found
                break
            time.sleep(settings.opencode_poll_seconds)
        else:
            server.client.abort(session_id)
            stop_reason = {"code": "timeout", "detail": f"墙钟耗尽（{settings.agent_wall_seconds}s）"}

        stop_flag.set()
        events_thread.join(timeout=5)
        drain_events()

        if completion is not None:
            summary = build_summary(status="completed", usage=usage, candidate_count=1,
                                    stop_reason=None, session_id=session_id, model_label=model.label,
                                    iterations=0, opencode_version=server.client.version(),
                                    last_event=last_event["type"])
            version.generation_meta_json = {**(version.generation_meta_json or {}), "agent_run": summary}
            db.commit()
            return _finalize(db, project, version, model, workspace, completion, ctx, summary, settings, engine)

        # 未完成：保留草稿/工程，写停止原因。
        draft = detect_completion(workspace)
        summary = build_summary(status="needs_attention", usage=usage,
                                candidate_count=1 if draft else 0, stop_reason=stop_reason,
                                session_id=session_id, model_label=model.label, iterations=0,
                                opencode_version=server.client.version(), last_event=last_event["type"])
        version.generation_meta_json = {**(version.generation_meta_json or {}), "agent_run": summary}
        if draft is not None:
            output = _finalize(db, project, version, model, workspace, draft, ctx, summary, settings, engine)
            output.status = "draft"
            project.status = "needs_attention"
            project.error_message = f"草稿已保存，尚未通过验收：{stop_reason['detail'] if stop_reason else ''}"
            db.commit()
            return output
        project.status = "failed"
        project.error_message = stop_reason["detail"] if stop_reason else "opencode 未产出成片"
        db.commit()
        raise AgentStopped(stop_reason["code"] if stop_reason else "no_output",
                           project.error_message)
    finally:
        stop_flag.set()
        server.stop()
