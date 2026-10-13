"""opencode headless 运行器：配置/完成信号/事件/客户端契约。"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app import agent_opencode as ao
from app.agent_runtime import ModelHandle
from app.config import get_settings
from app.opencode_client import OpencodeClient, OpencodeError, start_server


def _model() -> ModelHandle:
    return ModelHandle(base_url="https://gateway.example/v1", api_key="sk-test",
                       model_id="mimo-v2.6-pro", label="MiMo/mimo-v2.6-pro")


def test_config_uses_env_placeholders_and_model():
    config = ao.opencode_config(get_settings(), _model(), "video-shotcraft")
    options = config["provider"][config["model"].split("/")[0]]["options"]
    assert options["baseURL"] == "{env:VFO_BASE_URL}"
    assert options["apiKey"] == "{env:VFO_API_KEY}"
    assert config["model"].endswith("/mimo-v2.6-pro")
    assert config["permission"] == {"*": "allow", "question": "deny"}
    assert config["instructions"] == [
        ".opencode/skills/video-shotcraft/references/pipeline.md",
        ".opencode/platform/audio.md",
        ".opencode/platform/review.md",
    ]


def test_build_prompt_has_completion_contract():
    prompt = ao.build_prompt('{"topic":"x"}', {"dimensions": [1920, 1080]}, "video-shotcraft")
    assert ao.FINAL_VIDEO_REL in prompt
    assert ao.FINISH_JSON_REL in prompt
    assert "video-shotcraft" in prompt


def test_detect_completion(tmp_path):
    assert ao.detect_completion(tmp_path) is None
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "final.mp4").write_bytes(b"v")
    assert ao.detect_completion(tmp_path)["finish"] == {}
    (tmp_path / "out" / "finish.json").write_text('{"composition":"AgentFilm"}', encoding="utf-8")
    found = ao.detect_completion(tmp_path)
    assert found["finish"]["composition"] == "AgentFilm"


@pytest.mark.parametrize("event,expect_level", [
    ({"type": "server.connected"}, "info"),
    ({"type": "message.part.updated", "properties": {"text": "hello"}}, "info"),
    ({"type": "session.error", "properties": {"message": "boom"}}, "error"),
    ({}, "info"),
])
def test_summarize_event(event, expect_level):
    level, message, data = ao.summarize_event(event)
    assert level == expect_level
    assert isinstance(message, str) and message
    assert data["event"]


def test_extract_usage_accumulates():
    usage: dict = {}
    ao.extract_usage({"type": "x", "properties": {"tokens": {"input": 10, "output": 4}}}, usage)
    ao.extract_usage({"type": "x", "properties": {"tokens": {"input": 5, "output": 1}}}, usage)
    assert usage == {"prompt_tokens": 15, "completion_tokens": 5}


def test_build_summary_shape():
    summary = ao.build_summary(status="completed", usage={"prompt_tokens": 10, "completion_tokens": 2},
                               candidate_count=1, stop_reason=None, session_id="s1",
                               model_label="m/m", iterations=0, opencode_version="1.0.0", last_event="x")
    assert summary["usage"]["total_tokens"] == 12
    assert summary["opencode"] == {"session_id": "s1", "model": "m/m", "version": "1.0.0"}
    assert summary["status"] == "completed"


def test_describe_event_filters_noise_and_reports_tools():
    assert ao.describe_event({"type": "message.part.delta", "properties": {}}) is None
    assert ao.describe_event({"type": "server.heartbeat", "properties": {}}) is None
    assert ao.describe_event(
        {"type": "message.part.updated", "properties": {"part": {"type": "text", "text": "hi"}}}
    ) is None
    level, message, _ = ao.describe_event(
        {"type": "message.part.updated",
         "properties": {"part": {"type": "tool", "tool": "bash", "state": {"status": "running", "title": "npm run build"}}}}
    )
    assert level == "info" and "bash" in message
    level, message, _ = ao.describe_event(
        {"type": "session.error", "properties": {"error": {"data": {"message": "boom"}}}}
    )
    assert level == "error" and "boom" in message


def test_import_skill_copy_fallback(tmp_path, monkeypatch):
    skill = tmp_path / "video-shotcraft"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: video-shotcraft\n---", encoding="utf-8")

    def boom(*a, **k):
        raise OSError("no symlink")

    class Result:
        returncode = 1

    monkeypatch.setattr(ao.os, "symlink", boom)
    monkeypatch.setattr(ao.subprocess, "run", lambda *a, **k: Result())
    dest = ao.import_skill(tmp_path / "workspace", skill)
    assert dest == tmp_path / "workspace" / ".opencode" / "skills" / "video-shotcraft"
    assert (dest / "SKILL.md").is_file()


def test_client_lifecycle_with_mock_transport():
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        path = request.url.path
        if path == "/global/health":
            return httpx.Response(200, json={"healthy": True, "version": "9.9.9"})
        if path == "/session" and request.method == "POST":
            return httpx.Response(200, json={"id": "sess-1", "title": "t"})
        if path == "/session/status":
            return httpx.Response(200, json={"sess-1": {"type": "idle"}})
        if path.endswith("/prompt_async"):
            return httpx.Response(204)
        if path.endswith("/abort"):
            return httpx.Response(200, json=True)
        return httpx.Response(200, json={})

    client = OpencodeClient("http://127.0.0.1:1", password="pw",
                            transport=httpx.MockTransport(handler))
    assert client.health()["version"] == "9.9.9"
    session = client.create_session("title")
    assert session["id"] == "sess-1"
    client.prompt_async("sess-1", "hi", model={"providerID": "openai", "modelID": "m"})
    assert client.is_idle("sess-1") is True
    client.abort("sess-1")
    assert ("POST", "/session") in calls
    assert ("POST", "/session/sess-1/prompt_async") in calls


def test_client_iter_events_parses_sse():
    body = b'data: {"type":"server.connected"}\n\ndata: {"type":"session.idle"}\n\n'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    client = OpencodeClient("http://127.0.0.1:1", transport=httpx.MockTransport(handler))
    events = list(client.iter_events())
    assert [e["type"] for e in events] == ["server.connected", "session.idle"]


def test_start_server_missing_binary_raises(tmp_path, monkeypatch):
    from app import opencode_client

    monkeypatch.setattr(opencode_client, "_resolve_binary", lambda _b: str(tmp_path / "nope-opencode"))
    with pytest.raises(OpencodeError) as exc:
        opencode_client.start_server(tmp_path / "ws", binary="nope-opencode", start_timeout=1)
    assert exc.value.error_type == "configuration"


def test_client_error_normalized_on_500():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = OpencodeClient("http://127.0.0.1:1", transport=httpx.MockTransport(handler))
    with pytest.raises(OpencodeError) as exc:
        client.health()
    assert exc.value.status_code == 500


@pytest.mark.parametrize("has_audio,required,report_ok,expected", [
    (False, False, False, "draft"), (True, True, False, "draft"),
    (True, False, False, "gates_passed"), (True, True, True, "gates_passed"),
])
def test_finalize_enforces_audio_and_records_narration_warnings(tmp_path, monkeypatch,
                                                              has_audio, required, report_ok, expected):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.models import VideoProject, VideoVersion
    from app.agent_runtime import JobContext
    from app.config import Settings
    from app import render_utils

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    final = tmp_path / "out/final.mp4"
    final.parent.mkdir()
    final.write_bytes(b"fixture")
    audio = tmp_path / "public/audio"
    audio.mkdir(parents=True)
    (audio / "narration.timeline.json").write_text(json.dumps({"ok": report_ok, "status": "ready" if report_ok else "failed",
        "provider": "edge", "warnings": ["fallback-test"]}), encoding="utf-8")
    if report_ok:
        (audio / "narration.mp3").write_bytes(b"audio")
    monkeypatch.setattr(ao, "probe_video", lambda path: {"width": 1920, "height": 1080, "fps": 30,
                                                       "frames": 30, "has_audio": has_audio})
    monkeypatch.setattr(render_utils, "extract_poster", lambda *a: None)
    events = []
    with Session(engine) as db:
        project = VideoProject(topic="x")
        db.add(project)
        db.flush()
        version = VideoVersion(project_id=project.id, generation_input_json={"requirements": {"narration_required": True}})
        db.add(version)
        db.commit()
        result = ao._finalize(db, project, version, _model(), tmp_path, {"video": str(final)},
                              JobContext(emit=lambda *args: events.append(args)), {"status": "completed"},
                              Settings(_env_file=None, tts_required=required))
        assert result.status == expected
        assert result.gates_json["tts"]["warnings"] == ["fallback-test"]
        assert any("fallback-test" in e[1] for e in events)
        assert project.status == ("rendered" if expected == "gates_passed" else "needs_attention")
    engine.dispose()


# ---------------------------------------------------------------------------
# P3：视觉能力 / question 治理 / review_required 贯通
# ---------------------------------------------------------------------------
def _model_with(capability: str) -> ModelHandle:
    return ModelHandle(base_url="https://g/v1", api_key="sk", model_id="m", label="p/m",
                       capability=capability)


def test_opencode_config_marks_attachment_for_vision():
    config = ao.opencode_config(get_settings(), _model_with("vision"), "video-shotcraft")
    entry = config["provider"][config["model"].split("/")[0]]["models"]["m"]
    assert entry["attachment"] is True


def test_opencode_config_text_model_has_no_attachment():
    config = ao.opencode_config(get_settings(), _model_with("text"), "video-shotcraft")
    entry = config["provider"][config["model"].split("/")[0]]["models"]["m"]
    assert "attachment" not in entry


def test_opencode_config_denies_question_by_default():
    config = ao.opencode_config(get_settings(), _model_with("text"), "video-shotcraft")
    assert config["permission"] == {"*": "allow", "question": "deny"}


def test_build_prompt_skips_self_review_when_not_required():
    prompt = ao.build_prompt('{"topic":"x"}', {}, "video-shotcraft", review_required=False)
    assert "npx remotion still" in prompt
    assert "不要读图自审" in prompt


def test_build_prompt_keeps_self_review_default():
    prompt = ao.build_prompt('{"topic":"x"}', {}, "video-shotcraft")
    assert "完成后自审画面与音画同步" in prompt


def test_describe_event_flags_question_asked():
    event = {"type": "question.asked",
             "properties": {"questions": [{"header": "无法读图", "question": "怎么办？"}]}}
    level, message, data = ao.describe_event(event)
    assert level == "warning"
    assert "无法读图" in message
    assert data["event"] == "question.asked"
    assert data["questions"][0]["header"] == "无法读图"


def test_review_gate_skipped_when_not_required(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.models import VideoProject, VideoVersion

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    final = tmp_path / "out/final.mp4"
    final.parent.mkdir()
    final.write_bytes(b"fixture")
    candidate = {
        "id": "c1", "path": str(final),
        "meta": {"width": 1920, "height": 1080, "fps": 30, "frames": 30, "has_audio": True},
        "gates": [], "source_hash": "h", "snapshot": str(tmp_path / "snap.zip"),
        "composition": "AgentFilm", "creator_model": "m", "review": {},
    }
    with Session(engine) as db:
        project = VideoProject(topic="x")
        db.add(project)
        db.flush()
        version = VideoVersion(project_id=project.id)
        db.add(version)
        db.commit()
        output = ao._register_candidate(db, project, version, candidate, _model_with("vision"),
                                        review_required=False)
        review_gate = next(g for g in output.gates_json["gates"] if g["key"] == "review")
        assert review_gate["status"] == "skip"
        assert review_gate["detail"] == "未启用审片"
    engine.dispose()


def test_resolve_agent_model_prefers_vision_capability():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.models import AIModel, AIProvider
    from app.agent_runtime import resolve_agent_model
    from app.config import Settings

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        provider = AIProvider(name="gw", base_url="https://g/v1", encrypted_api_key="")
        db.add(provider)
        db.flush()
        db.add(AIModel(provider_id=provider.id, name="v", model_id="mimo", capability="vision"))
        db.commit()
        handle = resolve_agent_model(db, Settings(_env_file=None, agent_model_capability="text"))
        assert handle.model_id == "mimo"
        assert handle.capability == "vision"
    engine.dispose()


def test_platform_review_doc_written(tmp_path):
    from app.agent_audio import install_platform_docs

    install_platform_docs(tmp_path, None, review_required=False)
    off = (tmp_path / ".opencode/platform/review.md").read_text(encoding="utf-8")
    assert "禁止" in off and "requirements.review_required=false" in off

    install_platform_docs(tmp_path, None, review_required=True)
    on = (tmp_path / ".opencode/platform/review.md").read_text(encoding="utf-8")
    assert "requirements.review_required=true" in on
    assert "禁止" not in on
