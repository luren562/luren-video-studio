"""语速（全局默认 + 每项目覆盖）与 Edge 音色目录。"""
import json

import pytest

from app import runtime_settings
from app.agent_audio import audio_environment
from app.agent_runtime import _brief
from app.config import Settings
from app.models import VideoProject
from app.tts_providers import available_voices, normalize_rate, rate_percent


@pytest.mark.parametrize("value,expected", [("+25%", 25), (-10, -10), ("0%", 0), ("+100%", 100)])
def test_rate_percent_accepts(value, expected):
    assert rate_percent(value) == expected
    assert normalize_rate(value) == f"{expected:+d}%"


@pytest.mark.parametrize("bad", ["abc", "10", "1000%", True, 101, -101, None])
def test_rate_percent_rejects_invalid(bad):
    with pytest.raises(ValueError):
        rate_percent(bad)


def test_available_voices_are_edge_only():
    voices = available_voices()
    by_short = {v["shortName"]: v for v in voices}
    assert by_short["zh-CN-YunxiNeural"]["providers"] == ["edge"]
    assert by_short["zh-CN-YunxiNeural"]["id"] == "zh-CN-YunxiNeural"
    assert len(voices) == 14
    assert len({v["id"] for v in voices}) == len(voices)


def test_brief_project_rate_overrides_then_inherits():
    settings = Settings(_env_file=None)
    project = VideoProject(tts_enabled=True, tts_rate=30)
    assert json.loads(_brief(project, None, settings))["requirements"]["tts_rate"] == "+30%"
    project.tts_rate = None
    assert json.loads(_brief(project, None, settings))["requirements"]["tts_rate"] == settings.tts_rate


def test_audio_environment_rate_defaults_empty():
    settings = Settings(_env_file=None)
    env = audio_environment(settings, {"narration_required": True, "tts_voice": "x", "bgm_enabled": False})
    assert env["VF_TTS_RATE"] == ""


def test_runtime_settings_rate_roundtrip(tmp_path):
    saved = runtime_settings.save_overrides(tmp_path, {"tts_rate": "+15%"})
    assert saved["tts_rate"] == "+15%"
    assert runtime_settings.load_overrides(tmp_path)["tts_rate"] == "+15%"
    runtime_settings.save_overrides(tmp_path, {"tts_rate": "bogus"})  # 非法值忽略
    assert runtime_settings.load_overrides(tmp_path)["tts_rate"] == "+15%"


def test_settings_endpoint_rate(client, auth_headers, monkeypatch, tmp_path):
    from app.routers import settings as router
    settings = Settings(_env_file=None, data_dir=tmp_path)
    monkeypatch.setattr(router, "get_settings", lambda: settings)
    r = client.put("/api/settings", json={"render_concurrency": 2, "tts_rate": 20}, headers=auth_headers)
    assert r.status_code == 200 and r.json() == {"render_concurrency": 2, "tts_rate": 20}
    assert settings.tts_rate == "+20%"
    assert client.get("/api/settings", headers=auth_headers).json()["tts_rate"] == 20
