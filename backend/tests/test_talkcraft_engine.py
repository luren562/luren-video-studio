"""P2 talkcraft 引擎接入：注册表、解析回退、指令、脚手架、平台文档、播种白名单。"""
from __future__ import annotations

from sqlalchemy import select

from app import migrations
from app.agent_audio import install_platform_docs
from app.agent_opencode import opencode_config
from app.agent_runtime import ModelHandle
from app.config import Settings
from app.database import SessionLocal
from app.engine_registry import ENGINES, resolve_engine
from app.models import VideoProject, VideoStyle
from app import agent_runtime as runtime


def test_engine_registry_has_talkcraft():
    spec = ENGINES["talkcraft"]
    assert spec.audio_mode == "timestamps"
    assert spec.scaffold == "skill-runtime"
    assert spec.instructions == ("SKILL.md",)
    assert spec.aspect == "9:16"


def test_resolve_engine_falls_back_to_shotcraft():
    assert resolve_engine(None).key == "shotcraft"
    assert resolve_engine(VideoStyle(name="legacy")).key == "shotcraft"
    assert resolve_engine(VideoStyle(name="x", engine="unknown")).key == "shotcraft"
    assert resolve_engine(VideoStyle(name="x", engine="talkcraft")).key == "talkcraft"


def test_opencode_config_uses_skill_entry_doc():
    model = ModelHandle(base_url="https://g/v1", api_key="sk", model_id="m", label="p/m")
    config = opencode_config(Settings(_env_file=None), model, "video-talkcraft", ENGINES["talkcraft"])
    assert config["instructions"][0] == ".opencode/skills/video-talkcraft/SKILL.md"
    assert config["instructions"][1] == ".opencode/platform/audio.md"
    # 回退 shotcraft：默认不改变旧输出
    legacy = opencode_config(Settings(_env_file=None), model, "video-shotcraft")
    assert legacy["instructions"][0] == ".opencode/skills/video-shotcraft/references/pipeline.md"


def test_bootstrap_skill_runtime_skips_template(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", engines_dir=tmp_path / "engines")
    source = settings.engines_dir / "video-talkcraft" / "template" / "src"
    source.mkdir(parents=True)
    (source / "index.ts").write_text("// shotcraft template marker", encoding="utf-8")
    monkeypatch.setattr(runtime, "ensure_runtime", lambda _settings, _engine=None: tmp_path / "runtime")
    style = VideoStyle(name="talk", engine="talkcraft", aspect="9:16",
                       engine_config_json={"skill_id": "video-talkcraft"})
    workspace = runtime._bootstrap_workspace(
        settings, VideoProject(id=9, topic="x"), style=style, engine=ENGINES["talkcraft"])
    # 不拷 shotcraft 模板
    assert not (workspace / "src/index.ts").exists()
    assert (workspace / "package.json").is_file()
    assert (workspace / "scripts/vf_speak.mjs").is_file()
    assert "timestamps_cpu.py" in (workspace / ".opencode/platform/audio.md").read_text(encoding="utf-8")


def test_platform_docs_talkcraft_audio_md(tmp_path):
    install_platform_docs(tmp_path, ENGINES["talkcraft"])
    doc = (tmp_path / ".opencode/platform/audio.md").read_text(encoding="utf-8")
    assert "vf_speak.mjs" in doc
    assert "timestamps_cpu.py" in doc
    assert "make_timing.py" in doc
    assert (tmp_path / "scripts/vf_speak.mjs").is_file()


def test_seed_keeps_talkcraft_style(client):
    migrations.seed_defaults()
    migrations.seed_defaults()  # 幂等
    with SessionLocal() as session:
        rows = list(session.scalars(select(VideoStyle)).all())
    talkcraft = [s for s in rows if s.engine == "talkcraft"]
    assert any(s.name == "口播 · 观点（竖屏）" for s in talkcraft)
    assert all(s.engine in {"shotcraft", "talkcraft"} for s in rows)
