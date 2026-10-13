import json

import pytest
from sqlalchemy import create_engine, text, inspect

from app.agent_runtime import _brief
from app.config import Settings
from app.models import VideoProject, VideoStyle
from app import migrations


def test_creation_and_regeneration_roundtrip(client, auth_headers):
    payload = {"topic": "主题与声音", "theme_json": {"accent": "#12AbEF"}, "bgm_enabled": False,
               "tts_enabled": False, "tts_voice": "zh-CN-YunxiNeural"}
    response = client.post("/api/projects", json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    project = response.json()
    for key in payload:
        assert project[key] == payload[key]
    url = f"/api/projects/{project['id']}/regenerate"
    assert client.post(f"/api/tasks/{project['latest_task_id']}/cancel", headers=auth_headers).status_code == 200
    unchanged = client.post(url, json={}, headers=auth_headers).json()
    assert unchanged["theme_json"] == payload["theme_json"]
    assert unchanged["bgm_enabled"] is False and unchanged["tts_enabled"] is False
    assert client.post(f"/api/tasks/{unchanged['latest_task_id']}/cancel", headers=auth_headers).status_code == 200
    reset = client.post(url, json={"theme_json": {}, "bgm_enabled": None, "tts_voice": None,
                                  "tts_enabled": True}, headers=auth_headers).json()
    assert reset["theme_json"] == {} and reset["bgm_enabled"] is None
    assert reset["tts_voice"] is None and reset["tts_enabled"] is True
    assert client.delete(f"/api/projects/{project['id']}", headers=auth_headers).status_code == 204


@pytest.mark.parametrize("theme", [{"accent": "red"}, {"accent": "#fff"}, {"accent": "#000000\n"},
                                     {"bg": "#000000"}, {"accent": 123}, {"accent": "#GG0000"}])
def test_reject_invalid_or_non_accent_theme(client, auth_headers, theme):
    response = client.post("/api/projects", json={"topic": "x", "theme_json": theme}, headers=auth_headers)
    assert response.status_code == 422


def test_brief_overrides_and_inherits_without_mutating_style():
    settings = Settings(_env_file=None)
    style = VideoStyle(name="dark", aspect="16:9", theme_json={"accent": "#AABBCC", "bg": "#111111"},
                       engine_config_json={"bgm": "required", "narration": "required"})
    project = VideoProject(theme_json={"accent": "#112233"}, bgm_enabled=False, tts_enabled=False)
    brief = json.loads(_brief(project, style, settings))
    assert brief["theme"] == {"accent": "#112233", "bg": "#111111"}
    assert brief["requirements"]["accent"] == "#112233"
    assert not brief["requirements"]["bgm_required"]
    assert not brief["requirements"]["bgm_enabled"]
    assert not brief["requirements"]["narration_required"]
    assert style.theme_json["accent"] == "#AABBCC"
    project.bgm_enabled, project.tts_enabled, project.theme_json = None, None, None
    inherited = json.loads(_brief(project, style, settings))
    assert inherited["requirements"]["bgm_enabled"] is True
    assert inherited["requirements"]["tts_voice"] == "zh-CN-YunxiNeural"
    assert inherited["requirements"]["narration_lang"] == "zh"
    assert inherited["theme"]["accent"] == "#AABBCC"


def test_manual_asset_must_exist_and_be_audio(client, auth_headers):
    response = client.post("/api/projects", json={"topic": "x", "tts_asset_id": 999999}, headers=auth_headers)
    assert response.status_code == 422


@pytest.mark.parametrize("versioned", [False, True])
def test_existing_database_adds_columns_and_preserves_rows(tmp_path, monkeypatch, versioned):
    from alembic.config import Config
    db = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    with db.begin() as con:
        con.execute(text("CREATE TABLE video_projects (id INTEGER PRIMARY KEY, topic TEXT)"))
        con.execute(text("INSERT INTO video_projects VALUES (1, 'preserve-me')"))
        if versioned:
            con.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            con.execute(text("INSERT INTO alembic_version VALUES ('0001_baseline')"))
    config = Config()
    config.set_main_option("script_location", str(migrations.BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    monkeypatch.setattr(migrations, "engine", db)
    monkeypatch.setattr(migrations, "_alembic_config", lambda: config)
    migrations.upgrade_database()
    migrations.upgrade_database()
    assert {"theme_json", "bgm_enabled", "tts_enabled", "tts_voice", "tts_asset_id", "review_required"} <= {
        c["name"] for c in inspect(db).get_columns("video_projects")}
    with db.connect() as con:
        assert con.execute(text("SELECT topic, bgm_enabled FROM video_projects WHERE id=1")).one() == ("preserve-me", None)
    db.dispose()
