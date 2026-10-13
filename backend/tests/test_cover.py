"""AI 主题封面：接口形态、提示词、全局独立配置与手动重生成。"""
import pytest

from app.ai_client import image_endpoint
from app.cover_service import _aspect_size, build_cover_prompt
from app.models import RenderOutput, VideoProject


def test_image_endpoint_variants():
    assert image_endpoint("https://api.x.com") == "https://api.x.com/v1/images/generations"
    assert image_endpoint("https://api.x.com/v1") == "https://api.x.com/v1/images/generations"
    assert image_endpoint("https://api.x.com/v1/images/generations") == "https://api.x.com/v1/images/generations"
    # 已是 /v4 等版本段时不得再补 /v1（曾导致 404）
    assert image_endpoint("https://open.bigmodel.cn/api/paas/v4") == \
        "https://open.bigmodel.cn/api/paas/v4/images/generations"
    assert image_endpoint("https://dashscope.aliyuncs.com/compatible-mode/v1") == \
        "https://dashscope.aliyuncs.com/compatible-mode/v1/images/generations"
    with pytest.raises(Exception):
        image_endpoint("")


def test_aspect_size_matches_canvas():
    assert _aspect_size(1920, 1080) == "1792x1024"
    assert _aspect_size(1080, 1920) == "1024x1792"
    assert _aspect_size(1080, 1080) == "1024x1024"


def test_build_cover_prompt_includes_topic_title_and_accent():
    project = VideoProject(topic="黑洞", title="宇宙尽头", theme_json={"accent": "#88CCFF"})
    prompt = build_cover_prompt(project, RenderOutput(width=1080, height=1920))
    assert "黑洞" in prompt and "宇宙尽头" in prompt and "#88CCFF" in prompt


def _clear_cover_config():
    from app.database import SessionLocal
    from app.models import CoverConfig
    with SessionLocal() as db:
        for row in db.query(CoverConfig).all():
            db.delete(row)
        db.commit()


def test_regenerate_cover_validations(client, auth_headers):
    from app.database import SessionLocal

    _clear_cover_config()
    project = client.post("/api/projects", json={"topic": "封面重生成"}, headers=auth_headers).json()
    with SessionLocal() as db:
        output = RenderOutput(project_id=project["id"], version_id=0, file_path="none.mp4")
        db.add(output)
        db.commit()
        oid = output.id
    try:
        assert client.post("/api/outputs/999999/cover", headers=auth_headers).status_code == 404
        # 全局封面未配置 → 422
        resp = client.post(f"/api/outputs/{oid}/cover", headers=auth_headers)
        assert resp.status_code == 422
        # 配置测试接口在未配置时也拒绝
        assert client.post("/api/cover/test", headers=auth_headers).status_code == 422
    finally:
        client.delete(f"/api/projects/{project['id']}", headers=auth_headers)


def test_cover_config_roundtrip_and_key_never_echoed(client, auth_headers):
    resp = client.put("/api/cover/config", headers=auth_headers, json={
        "base_url": "https://api.cover.test/v1", "model": "flux-1", "size": "1024x1024", "api_key": "sk-secret"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"base_url": "https://api.cover.test/v1", "has_api_key": True,
                           "model": "flux-1", "size": "1024x1024"}
    assert "sk-secret" not in resp.text
    # 留空密钥 → 保留已存密钥
    again = client.put("/api/cover/config", headers=auth_headers, json={
        "base_url": "https://api.cover.test/v1", "model": "flux-2", "size": "", "api_key": ""})
    assert again.json()["has_api_key"] is True and again.json()["model"] == "flux-2"
    assert client.get("/api/cover/config", headers=auth_headers).json()["model"] == "flux-2"


def _make_fake_client(captured, response):
    class _Resp:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return response

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            captured.update(url=url, headers=headers, json=json)
            return _Resp()

    return _Client


def test_image_generation_siliconflow_shape(monkeypatch):
    from app import ai_client
    captured: dict = {}
    monkeypatch.setattr(ai_client.httpx, "Client",
                        _make_fake_client(captured, {"images": [{"url": "https://cdn/x.png"}], "seed": 1}))
    res = ai_client.image_generation(base_url="https://api.siliconflow.cn/v1", api_key="k",
                                     model="Kwai-Kolors/Kolors", prompt="a cat", size="1024x1024")
    assert res.url == "https://cdn/x.png"
    assert captured["json"]["image_size"] == "1024x1024" and "size" not in captured["json"]
    assert captured["headers"]["X-Enable-Watermark"] == "0"


def test_image_generation_openai_shape(monkeypatch):
    from app import ai_client
    captured: dict = {}
    monkeypatch.setattr(ai_client.httpx, "Client",
                        _make_fake_client(captured, {"data": [{"b64_json": "QUJD"}]}))
    res = ai_client.image_generation(base_url="https://api.openai.com/v1", api_key="k",
                                     model="gpt-image-1", prompt="a cat", size="1024x1024")
    assert res.b64_json == "QUJD"
    assert captured["json"]["size"] == "1024x1024" and "image_size" not in captured["json"]
    assert "watermark_enabled" not in captured["json"]


def test_image_generation_zhipu_watermark_field(monkeypatch):
    from app import ai_client
    captured: dict = {}
    monkeypatch.setattr(ai_client.httpx, "Client",
                        _make_fake_client(captured, {"data": [{"url": "https://cdn/z.png"}]}))
    ai_client.image_generation(base_url="https://open.bigmodel.cn/api/paas/v4", api_key="k",
                               model="glm-image", prompt="a cat", size="1280x1280")
    assert captured["json"]["watermark_enabled"] is False
    assert captured["json"]["size"] == "1280x1280"
