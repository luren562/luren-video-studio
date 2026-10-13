"""Worker：项目删除（任务清理）单测。"""


def test_delete_project_removes_it(client, auth_headers):
    resp = client.post("/api/projects", json={"topic": "删除测试主题"}, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    assert client.delete(f"/api/projects/{pid}", headers=auth_headers).status_code == 204
    assert client.get(f"/api/projects/{pid}", headers=auth_headers).status_code == 404
