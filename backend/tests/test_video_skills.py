"""Skills remain production methods inside the single Agent execution route."""
from pathlib import Path
import json
import pytest
from app.config import Settings
from app.models import VideoProject, VideoStyle
from app import agent_runtime as runtime
from app.agent_opencode import opencode_config
from app.agent_runtime import ModelHandle
from app.video_skills import selected_skill, validate_skill_config, DIAGRAM_STYLES


def test_unbound_style_keeps_existing_default():
    settings = Settings()
    assert selected_skill(settings, VideoStyle(name="legacy")) == settings.agent_skill_dirname


def test_bound_style_resolves_skill_and_brief():
    settings = Settings(tts_enabled=False)
    style = VideoStyle(**DIAGRAM_STYLES[0])
    assert runtime.skill_root(settings, style).name == "video-diagram-explainer"
    brief = json.loads(runtime._brief(VideoProject(id=1, topic="probability"), style, settings))
    assert brief["style"]["skill_id"] == "video-diagram-explainer"
    assert brief["style"]["engine_config"]["visual_profile"] == "ivory"
    config = opencode_config(settings, ModelHandle("http://localhost", "", "m", "m"), brief["style"]["skill_id"])
    assert config["instructions"][0] == ".opencode/skills/video-diagram-explainer/references/pipeline.md"
    assert not any("video-shotcraft" in doc for doc in config["instructions"])


@pytest.mark.parametrize("config", [
    {"skill_id":"../../outside"}, {"skill_id":[]},
    {"skill_id":"video-diagram-explainer","visual_profile":"unknown"},
])
def test_unregistered_skill_and_profile_rejected(config):
    with pytest.raises(ValueError): validate_skill_config(config)


def test_bootstrap_uses_selected_template(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path/"data", engines_dir=tmp_path/"engines")
    source = settings.engines_dir/"video-diagram-explainer"/"template"/"src"
    source.mkdir(parents=True)
    (source/"index.ts").write_text("// diagram template marker",encoding="utf-8")
    monkeypatch.setattr(runtime,"ensure_runtime",lambda _settings: tmp_path/"runtime")
    workspace = runtime._bootstrap_workspace(settings, VideoProject(id=77,topic="x"), style=VideoStyle(**DIAGRAM_STYLES[0]))
    assert (workspace/"src/index.ts").read_text(encoding="utf-8") == "// diagram template marker"
    assert (workspace/"scripts/vf_tts.mjs").exists()
    assert (workspace/".opencode/platform/audio.md").exists()


def test_style_api_preserves_binding_and_rejects_bad_skill(client, auth_headers):
    payload = {**DIAGRAM_STYLES[0], "name":"Test diagram binding"}
    response = client.post("/api/styles",json=payload,headers=auth_headers)
    assert response.status_code == 201, response.text
    style_id=response.json()["id"]
    assert response.json()["engine_config_json"]["skill_id"] == "video-diagram-explainer"
    bad=client.patch(f"/api/styles/{style_id}",json={"engine_config_json":{"skill_id":"unknown"}},headers=auth_headers)
    assert bad.status_code == 422
    persisted=client.get("/api/styles",headers=auth_headers).json()
    assert next(s for s in persisted if s["id"]==style_id)["engine_config_json"]["skill_id"]=="video-diagram-explainer"
