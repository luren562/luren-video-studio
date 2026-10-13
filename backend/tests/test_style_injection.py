"""P1 风格注入：播种、风格文档、简报、opencode 配置。"""
from __future__ import annotations

import json

from sqlalchemy import select

from app import migrations
from app.agent_opencode import opencode_config
from app.agent_runtime import ModelHandle, _brief
from app.agent_style import STYLE_DOC_REL, build_style_doc, install_style_doc
from app.config import Settings, get_settings
from app.database import SessionLocal
from app.models import ContentStrategy, VideoProject, VideoStyle

GUANGYU = "光宇 · 数学拆解人生"


def test_seed_creates_guangyu_strategy(client):
    migrations.seed_defaults()
    migrations.seed_defaults()  # 幂等
    with SessionLocal() as session:
        rows = list(session.scalars(
            select(ContentStrategy).where(ContentStrategy.name == GUANGYU)
        ).all())
    assert len(rows) == 1
    assert rows[0].style_guide_md.strip()
    assert rows[0].banned_phrases_json


def test_guangyu_style_guide_has_full_profile(client):
    migrations.seed_defaults()
    with SessionLocal() as session:
        row = session.scalar(select(ContentStrategy).where(ContentStrategy.name == GUANGYU))
    assert "开场钩子库" in row.style_guide_md
    assert "我是光宇，我们下期见" in row.style_guide_md


def test_seed_refreshes_stale_preset_body(client):
    migrations.seed_defaults()
    with SessionLocal() as session:
        row = session.scalar(select(ContentStrategy).where(ContentStrategy.name == GUANGYU))
        row.style_guide_md = "旧版精简正文"
        session.commit()
    migrations.seed_defaults()
    with SessionLocal() as session:
        row = session.scalar(select(ContentStrategy).where(ContentStrategy.name == GUANGYU))
    assert "开场钩子库" in row.style_guide_md


def test_list_strategies_api_serializes_style_guide(client, auth_headers):
    response = client.get("/api/strategies", headers=auth_headers)
    assert response.status_code == 200, response.text
    items = response.json()
    assert any(item["name"] == GUANGYU and item["style_guide_md"] for item in items)


def _strategy() -> ContentStrategy:
    return ContentStrategy(
        name="测试风格",
        tone="冷静、笃定",
        prompt_rules="钩子→信源→翻译成人话",
        banned_phrases_json=["加油", "暴富"],
        style_guide_md="# 正文风格\n用第二人称。",
    )


def test_build_style_doc_contains_sections():
    doc = build_style_doc(_strategy())
    assert "用第二人称" in doc
    assert "语气" in doc and "冷静、笃定" in doc
    assert "结构/写法规则" in doc
    assert "加油" in doc and "暴富" in doc


def test_install_style_doc_writes_file(tmp_path):
    assert install_style_doc(tmp_path, None) is None
    path = install_style_doc(tmp_path, _strategy())
    assert path == tmp_path / STYLE_DOC_REL
    assert path.is_file()
    assert "第二人称" in path.read_text(encoding="utf-8")


def test_brief_includes_strategy():
    settings = Settings(_env_file=None)
    project = VideoProject(topic="x")
    brief = json.loads(_brief(project, VideoStyle(name="s"), settings, _strategy()))
    assert brief["strategy"]["name"] == "测试风格"
    assert brief["strategy"]["banned_phrases"] == ["加油", "暴富"]
    # 缺省仍为 None，向后兼容
    legacy = json.loads(_brief(project, VideoStyle(name="s"), settings))
    assert legacy["strategy"] is None


def test_opencode_config_appends_style_doc():
    model = ModelHandle(base_url="https://g/v1", api_key="sk", model_id="m", label="p/m")
    base = opencode_config(get_settings(), model, "video-shotcraft")
    assert base["instructions"] == [
        ".opencode/skills/video-shotcraft/references/pipeline.md",
        ".opencode/platform/audio.md",
        ".opencode/platform/review.md",
    ]
    extended = opencode_config(get_settings(), model, "video-shotcraft", extra_docs=[STYLE_DOC_REL])
    assert extended["instructions"][-1] == STYLE_DOC_REL
