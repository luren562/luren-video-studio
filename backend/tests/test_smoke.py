from app import worker as worker_module


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_login_rejects_bad_password(client):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    assert resp.status_code == 401


def test_requires_auth(client):
    assert client.get("/api/stats").status_code == 401


def test_seeded_styles_and_engines(client, auth_headers):
    engines = client.get("/api/styles/engines", headers=auth_headers).json()
    assert {e["key"] for e in engines} == {"shotcraft", "talkcraft"}
    styles = client.get("/api/styles", headers=auth_headers).json()
    assert len(styles) >= 1
    assert any(s["is_default"] for s in styles)


def test_provider_key_is_encrypted_and_not_echoed(client, auth_headers):
    resp = client.post(
        "/api/ai/providers",
        headers=auth_headers,
        json={"name": "test-provider", "base_url": "https://api.example.com", "api_key": "secret-123"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["has_api_key"] is True
    assert "secret-123" not in resp.text
    assert "api_key" not in body


def test_project_creation_enqueues_agent_film(client, auth_headers):
    """单模式：新项目恒为 agent，任务恒为 agent_film。"""
    created = client.post(
        "/api/projects", headers=auth_headers, json={"topic": "测试主题", "duration_target_sec": 60, "mode": "structured"}
    ).json()
    assert created["status"] == "generating"
    assert created["mode"] == "agent"
    tasks = client.get(
        "/api/tasks", headers=auth_headers, params={"kind": "agent_film", "resource_id": created["id"]}
    ).json()
    assert tasks and tasks[0]["kind"] == "agent_film"
    # 取消排队任务，避免泄漏到后续用例
    client.post(f"/api/tasks/{tasks[0]['id']}/cancel", headers=auth_headers)


def test_agent_missing_config_fails_gracefully(client, auth_headers):
    # agent 未开启/无可用模型 -> worker 执行后项目 failed 且带错误信息
    created = client.post(
        "/api/projects", headers=auth_headers, json={"topic": "无模型测试", "duration_target_sec": 60}
    ).json()
    project_id = created["id"]
    assert worker_module.PipelineWorker().run_once() is True
    detail = client.get(f"/api/projects/{project_id}", headers=auth_headers).json()
    assert detail["status"] == "failed"
    assert detail["error_message"]
