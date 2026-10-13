"""AI 供应商/模型的增删（设置页删除按钮）单测。"""


def _create_provider(client, headers, name, model_id=""):
    resp = client.post(
        "/api/ai/providers",
        json={"name": name, "base_url": "https://api.deepseek.com", "default_model_id": model_id},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_create_provider_with_default_model(client, auth_headers):
    pid = _create_provider(client, auth_headers, "test-del-prov-a", "deepseek-flash")
    try:
        models = [m for m in client.get("/api/ai/models", headers=auth_headers).json() if m["provider_id"] == pid]
        assert any(m["model_id"] == "deepseek-flash" and m["capability"] == "text" for m in models)
    finally:
        assert client.delete(f"/api/ai/providers/{pid}", headers=auth_headers).status_code == 204
    # 级联删除其模型
    remaining = [m for m in client.get("/api/ai/models", headers=auth_headers).json() if m["provider_id"] == pid]
    assert remaining == []


def test_delete_model(client, auth_headers):
    pid = _create_provider(client, auth_headers, "test-del-prov-b", "deepseek-v4-pro")
    try:
        mid = [m for m in client.get("/api/ai/models", headers=auth_headers).json() if m["provider_id"] == pid][0]["id"]
        assert client.delete(f"/api/ai/models/{mid}", headers=auth_headers).status_code == 204
        assert client.delete(f"/api/ai/models/{mid}", headers=auth_headers).status_code == 404
    finally:
        client.delete(f"/api/ai/providers/{pid}", headers=auth_headers)


def test_delete_missing_provider_404(client, auth_headers):
    assert client.delete("/api/ai/providers/999999", headers=auth_headers).status_code == 404
