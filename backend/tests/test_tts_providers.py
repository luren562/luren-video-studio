import json
import os
import subprocess
import wave
from pathlib import Path

import pytest

from app import narration
from app.agent_audio import audio_environment, install_audio_tools
from app.config import Settings
from app.tts_providers import (SpeechChunk, TtsError, available_voices, parse_srt, split_text)


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, assets_dir=tmp_path / "assets", tts_fallback="none", tts_required=True)


def test_catalogue_ids_and_chinese_only(client, auth_headers):
    response = client.get("/api/tts/voices", headers=auth_headers)
    assert response.status_code == 200
    voices = response.json()
    assert len(voices) == 14
    assert all(v["language"] == "Chinese" for v in voices)
    assert len({v["id"] for v in voices}) == 14
    assert next(v for v in voices if v["shortName"] == "zh-CN-YunxiNeural")["id"] == "zh-CN-YunxiNeural"
    assert all(v["providers"] == ["edge"] for v in voices)
    assert sum(v["is_default"] for v in voices) == 1
    assert client.get("/api/tts/voices").status_code == 401
    assert len(available_voices()) == 14


@pytest.mark.parametrize("text", ["中文测试。" * 600, "啊" * 3000, "😀" * 1800, "句子！\n" * 1000])
def test_chunking_preserves_every_character_and_utf16_limit(text):
    chunks = split_text(text)
    assert len(chunks) >= 2
    assert "".join(chunks) == text
    assert all(0 < len(c.encode("utf-16-le")) // 2 <= 1800 for c in chunks)


def test_chunking_prefers_sentence_ends():
    assert split_text("一" * 1700 + "。" + "二" * 200) == ["一" * 1700 + "。", "二" * 200]


def wav_fixture(path, seconds=1):
    import math, struct
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        audio.writeframes(b"".join(struct.pack("<h", round(4000 * math.sin(2 * math.pi * 440 * i / 48000)))
                                   for i in range(round(seconds * 48000))))
    return path


def test_3000_characters_real_mp3_join_and_srt_offsets(settings, tmp_path, monkeypatch):
    from app.toolchain import ensure_tool_paths
    ensure_tool_paths()
    source = wav_fixture(tmp_path / "source.wav")
    calls = []
    class FakeProvider:
        def __init__(self, settings): pass
        def synth(self, text, voice, rate, out_dir):
            calls.append(text)
            return SpeechChunk(source, [{"start": 0.1, "end": 0.9, "text": "对应字幕"}], "provider")
    monkeypatch.setattr(narration, "EdgeTtsProvider", FakeProvider)
    result = narration.synthesize_narration("中文测试。" * 600, tmp_path / "narration.mp3", settings)
    assert len(calls) == 2 and sum(map(len, calls)) == 3000
    assert result["duration_sec"] == 2.25
    assert result["cues"][1]["start"] == 1.35
    assert result["cues"][1]["end"] == 2.15
    assert result["timing"] == "aligned"
    srt = parse_srt((tmp_path / "narration.srt").read_text(encoding="utf-8"))
    assert srt[1]["start"] == 1.35
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
                            str(tmp_path / "narration.mp3")], capture_output=True, text=True, check=True)
    assert abs(float(json.loads(probe.stdout)["format"]["duration"]) - 2.25) < 0.06


def test_optional_failure_removes_stale_audio_and_reports(settings, tmp_path, monkeypatch):
    settings.tts_required = False
    class Failed:
        def __init__(self, settings): pass
        def synth(self, *args): raise TtsError("quota-exceeded", "quota exceeded")
    monkeypatch.setattr(narration, "EdgeTtsProvider", Failed)
    output = tmp_path / "narration.mp3"
    output.write_bytes(b"stale")
    result = narration.synthesize_narration("你好。", output, settings)
    assert result["ok"] is False and not output.exists()
    assert output.with_suffix(".timeline.json").exists()
    settings.tts_required = True
    with pytest.raises(TtsError):
        narration.synthesize_narration("你好。", output, settings)


def test_injected_node_cli_manual_audio_and_no_bgm(settings, tmp_path):
    install_audio_tools(tmp_path)
    install_audio_tools(tmp_path)  # upgrade/retry refreshes read-only files
    original = wav_fixture(tmp_path / "manual.wav")
    (tmp_path / "narration.txt").write_text("测试中文旁白。" * 400, encoding="utf-8")
    env = {**os.environ, **audio_environment(settings, {"narration_required": True, "tts_voice": "zh-CN-YunxiNeural",
                                                       "bgm_enabled": False}, manual_file="manual.wav")}
    run = subprocess.run(["node", "scripts/vf_tts.mjs", "--text-file", "narration.txt",
                          "--out", "public/audio/narration.mp3"], cwd=tmp_path, env=env,
                         capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert result["ok"] and result["provider"] == "manual" and result["duration_sec"] == 1
    assert (tmp_path / "public/audio/narration.srt").is_file()
    # BGM=false must ignore even a nonexistent music path, preserving the dry track.
    mixed = tmp_path / "mixed.wav"
    run = subprocess.run(["node", "scripts/vf_mix.mjs", "--narration", str(original), "--bgm", "missing.mp3",
                          "--out", str(mixed)], cwd=tmp_path, env=env, capture_output=True, timeout=30)
    assert run.returncode == 0, run.stderr
    with wave.open(str(mixed)) as a, wave.open(str(original)) as b:
        assert a.readframes(a.getnframes()) == b.readframes(b.getnframes())
    env["TTS_ENABLED"] = "false"
    run = subprocess.run(["node", "scripts/vf_tts.mjs", "--text-file", "narration.txt"], cwd=tmp_path,
                         env=env, capture_output=True, timeout=30)
    assert run.returncode == 1


def test_preview_is_authenticated_cached_and_never_silently_falls_back(client, auth_headers, settings, monkeypatch):
    from app.routers import tts as router
    calls = []
    def synth(text, out, config, *, voice, allow_fallback):
        assert not allow_fallback
        calls.append(voice)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"test-audio")
    monkeypatch.setattr(router, "get_settings", lambda: settings)
    monkeypatch.setattr(router, "synthesize_narration", synth)
    assert client.post("/api/tts/preview", json={"voice": "zh-CN-YunxiNeural"}).status_code == 401
    for _ in range(2):
        response = client.post("/api/tts/preview", json={"voice": "zh-CN-YunxiNeural"}, headers=auth_headers)
        assert response.status_code == 200 and response.content == b"test-audio"
    assert calls == ["zh-CN-YunxiNeural"]
    assert client.post("/api/tts/preview", json={"voice": "unknown"}, headers=auth_headers).status_code == 422


def test_read_audio_report_does_not_accept_missing_audio(tmp_path):
    from app.agent_audio import read_audio_report
    folder = tmp_path / "public/audio"
    folder.mkdir(parents=True)
    (folder / "narration.timeline.json").write_text('{"ok": true, "warnings": []}', encoding="utf-8")
    assert not read_audio_report(tmp_path, {"narration_required": True})["ok"]
    assert read_audio_report(tmp_path, {"narration_required": False})["status"] == "disabled"


def test_manual_source_cannot_be_overwritten(settings, tmp_path):
    source = tmp_path / "narration.mp3"
    source.write_bytes(b"original recording")
    with pytest.raises(TtsError, match="不能覆盖"):
        narration.synthesize_narration("原文", source, settings, manual_file=source)
    assert source.read_bytes() == b"original recording"
