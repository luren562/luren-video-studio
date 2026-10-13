from app import tts_service as tts


def test_chunk_starts_aligns_to_word_boundaries():
    # 中文：tts_text == "".join(chunks)
    chunks = ["阳光包含各种颜色", "蓝光波长更短"]
    text = "".join(chunks)
    words = [
        {"t": 0.0, "d": 0.3, "text": "阳光"},
        {"t": 0.3, "d": 0.3, "text": "包含"},
        {"t": 0.6, "d": 0.3, "text": "各种"},
        {"t": 0.9, "d": 0.3, "text": "颜色"},
        {"t": 1.3, "d": 0.3, "text": "蓝光"},
        {"t": 1.6, "d": 0.3, "text": "波长"},
        {"t": 1.9, "d": 0.3, "text": "更短"},
    ]
    starts = tts.chunk_starts(text, chunks, words, 0.0, 2.2, "")
    assert starts[0] == 0.0
    assert starts[1] == 1.3


def test_chunk_starts_falls_back_to_interpolation():
    chunks = ["一二三四", "五六七八"]
    text = "".join(chunks)
    starts = tts.chunk_starts(text, chunks, [], 0.0, 2.0, "")
    assert starts[0] == 0.0
    assert starts[1] == 1.0


def test_build_subs_spans_scene_and_is_monotonic():
    subs = tts._build_subs([0.0, 1.0], 2.0, ["上一句", "下一句"])
    assert subs[0]["from"] == 0
    assert subs[-1]["to"] == 2 * tts.FPS - 1
    assert all(s["from"] <= s["to"] for s in subs)
    assert subs[0]["to"] < subs[1]["from"] + 1


def test_scene_chunks_falls_back_to_narration():
    assert tts._scene_chunks({"subtitle_chunks": [], "narration": "只有解说词"}) == ["只有解说词"]
    assert tts._scene_chunks({"subtitle_chunks": ["a", " b "]}) == ["a", "b"]


def test_chapter_track_detects_chapter_roles():
    spec = {"chapters": [{"index": 1, "name": "开场"}, {"index": 2, "name": "原理"}]}
    scenes = [{"role": "cover"}, {"role": "chapter"}, {"role": "content"}]
    timings = [
        {"start": 12, "duration": 100, "subs": []},
        {"start": 112, "duration": 90, "subs": []},
        {"start": 202, "duration": 120, "subs": []},
    ]
    starts, names = tts._chapter_track(spec, timings, scenes)
    assert starts == [12, 112]
    assert names == ["开场", "原理"]


def test_build_narration_without_scenes_fails_gracefully():
    result = tts.build_narration({"scenes": []}, "zh", tts.get_settings().data_dir, 1)
    assert result.ok is False
    assert result.error


def test_build_narration_unknown_engine_fails_gracefully():
    settings = tts.get_settings().model_copy(update={"tts_engine": "nope"})
    result = tts.build_narration(
        {"scenes": [{"narration": "你好", "subtitle_chunks": ["你好"]}]},
        "zh",
        settings.data_dir,
        1,
        settings,
    )
    assert result.ok is False
    assert "nope" in result.error
