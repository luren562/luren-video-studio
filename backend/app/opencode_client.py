"""opencode headless 客户端：启动 `opencode serve` 并通过 HTTP 驱动会话。

契约以 opencode 官方 Server/SDK 文档为准（见 AGENT_OPENCODE_MIGRATION_PLAN_2026-10-03.md §2）：
- `opencode serve --hostname 127.0.0.1 --port <n>`；HTTP basic 鉴权（用户名默认 opencode）。
- `GET /global/health` → {healthy, version}
- `POST /session` → Session；`POST /session/:id/prompt_async` → 204；`POST /session/:id/abort`
- `GET /event` → SSE（首个 server.connected，其后 bus 事件）
- `GET /session/status` → {sessionID: SessionStatus}
- `POST /session/:id/permissions/:permissionID` → 响应权限请求

版本迭代快，所有端点/字段集中在本文件，升级只需在此校对。
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import httpx
from loguru import logger

API_HEALTH = "/global/health"
API_EVENT = "/event"
API_SESSION = "/session"
API_SESSION_STATUS = "/session/status"
API_SESSION_MESSAGES = "/session/{session_id}/message"
API_SESSION_PROMPT_ASYNC = "/session/{session_id}/prompt_async"
API_SESSION_ABORT = "/session/{session_id}/abort"
API_SESSION_PERMISSION = "/session/{session_id}/permissions/{permission_id}"

DEFAULT_USERNAME = "opencode"
DEFAULT_HOSTNAME = "127.0.0.1"
DEFAULT_PORT = 4096
START_TIMEOUT_SECONDS = 120.0
HEALTH_POLL_SECONDS = 0.5


class OpencodeError(RuntimeError):
    def __init__(self, message: str, *, error_type: str = "opencode_error", status_code: int | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((DEFAULT_HOSTNAME, 0))
        return int(sock.getsockname()[1])


def _normalize_error(exc: Exception) -> OpencodeError:
    if isinstance(exc, OpencodeError):
        return exc
    if isinstance(exc, httpx.TimeoutException):
        return OpencodeError("opencode 请求超时", error_type="timeout")
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return OpencodeError(f"opencode HTTP {code}：{exc.response.text[:300]}",
                             error_type="provider_error", status_code=code)
    if isinstance(exc, httpx.HTTPError):
        return OpencodeError(f"opencode 连接错误：{exc}", error_type="network_error")
    return OpencodeError(str(exc))


class OpencodeClient:
    """单个 opencode server 的 HTTP 客户端。线程安全由调用方保证（单 worker）。"""

    def __init__(self, base_url: str, password: str = "", username: str = DEFAULT_USERNAME,
                 *, timeout: float = 60.0, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self._auth = (username, password) if password else None
        self._timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, auth=self._auth, transport=self._transport,
                            timeout=httpx.Timeout(self._timeout, connect=10.0), follow_redirects=True)

    def _request(self, method: str, path: str, **kwargs):
        try:
            with self._client() as client:
                resp = client.request(method, path, **kwargs)
                resp.raise_for_status()
                if resp.status_code == 204 or not resp.content:
                    return None
                return resp.json()
        except Exception as exc:  # noqa: BLE001 - 统一归一化
            raise _normalize_error(exc) from exc

    # -- health / lifecycle ------------------------------------------------
    def health(self) -> dict:
        return self._request("GET", API_HEALTH) or {}

    def version(self) -> str:
        return str(self.health().get("version", ""))

    def delete_session(self, session_id: str) -> None:
        self._request("DELETE", f"{API_SESSION}/{session_id}")

    # -- sessions ----------------------------------------------------------
    def create_session(self, title: str = "") -> dict:
        body = {"title": title} if title else {}
        return self._request("POST", API_SESSION, json=body) or {}

    def prompt_async(self, session_id: str, text: str, *, model: dict | None = None,
                     agent: str | None = None, system: str | None = None) -> None:
        body: dict = {"parts": [{"type": "text", "text": text}]}
        if model:
            body["model"] = model
        if agent:
            body["agent"] = agent
        if system:
            body["system"] = system
        self._request("POST", API_SESSION_PROMPT_ASYNC.format(session_id=session_id), json=body)

    def abort(self, session_id: str) -> None:
        self._request("POST", API_SESSION_ABORT.format(session_id=session_id))

    def session_status(self) -> dict:
        return self._request("GET", API_SESSION_STATUS) or {}

    def is_idle(self, session_id: str) -> bool:
        status = self.session_status().get(session_id)
        if status is None:
            return True
        if isinstance(status, str):
            return status in ("idle", "")
        if isinstance(status, dict):
            return str(status.get("type", "idle")) == "idle"
        return True

    def messages(self, session_id: str, limit: int | None = None) -> list:
        params = {"limit": limit} if limit else None
        return self._request("GET", API_SESSION_MESSAGES.format(session_id=session_id), params=params) or []

    def respond_permission(self, session_id: str, permission_id: str, response: str = "once",
                           remember: bool = False) -> None:
        """放开命令模式下通常不会收到权限请求；收到时由运行器决定响应。"""
        self._request("POST", API_SESSION_PERMISSION.format(session_id=session_id, permission_id=permission_id),
                      json={"response": response, "remember": remember})

    # -- events ------------------------------------------------------------
    def iter_events(self, cancel=lambda: False) -> Iterator[dict]:
        """流式读取 SSE 事件；cancel() 为真时结束。"""
        try:
            with self._client() as client:
                with client.stream("GET", API_EVENT, timeout=httpx.Timeout(None, connect=10.0)) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if cancel():
                            return
                        if not line or not line.startswith("data:"):
                            continue
                        payload = line[len("data:"):].strip()
                        if not payload or payload == "[DONE]":
                            continue
                        try:
                            yield json.loads(payload)
                        except json.JSONDecodeError:
                            continue
        except Exception as exc:  # noqa: BLE001 - 事件流断开交由调用方决定重连/停止
            raise _normalize_error(exc) from exc


@dataclass
class OpencodeServer:
    """一个工作区对应的 opencode server 进程 + 客户端。"""

    workspace: Path
    binary: str
    port: int
    password: str
    client: OpencodeClient
    process: subprocess.Popen | None = None
    env: dict = field(default_factory=dict)

    @property
    def base_url(self) -> str:
        return self.client.base_url

    def stop(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                                       capture_output=True, timeout=15)
                    else:
                        self.process.kill()
                except Exception:  # noqa: BLE001
                    pass
        self.process = None


def _resolve_binary(binary: str) -> str:
    if os.path.sep in binary or (os.path.altsep and os.path.altsep in binary):
        return binary
    found = shutil.which(binary)
    return found or binary


def start_server(workspace: Path, *, binary: str = "opencode", password: str = "",
                 hostname: str = DEFAULT_HOSTNAME, port: int | None = None,
                 env: dict | None = None, start_timeout: float = START_TIMEOUT_SECONDS) -> OpencodeServer:
    """在 workspace 下启动一个 opencode headless server 并等待健康。

    每个项目版本独立一个 server（cwd=workspace），避免多项目串味。
    """
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    port = port or free_port()
    exe = _resolve_binary(binary)

    process_env = os.environ.copy()
    process_env["PYTHONUTF8"] = "1"
    if password:
        process_env["OPENCODE_SERVER_PASSWORD"] = password
    if env:
        process_env.update({str(k): str(v) for k, v in env.items()})

    argv = [exe, "serve", "--hostname", hostname, "--port", str(port)]
    log_path = workspace / ".opencode-server.log"
    log_handle = log_path.open("ab")
    try:
        process = subprocess.Popen(argv, cwd=str(workspace), env=process_env,
                                   stdout=log_handle, stderr=subprocess.STDOUT)
    except FileNotFoundError as exc:
        log_handle.close()
        raise OpencodeError(f"未找到 opencode 可执行文件：{exe}", error_type="configuration") from exc

    base_url = f"http://{hostname}:{port}"
    client = OpencodeClient(base_url, password=password)
    server = OpencodeServer(workspace=workspace, binary=exe, port=port, password=password,
                            client=client, process=process, env=process_env)

    deadline = time.monotonic() + start_timeout
    last_error = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log_handle.close()
            raise OpencodeError(f"opencode serve 启动即退出（exit={process.returncode}），日志：{log_path}")
        try:
            health = client.health()
            if health.get("healthy") or health.get("version"):
                logger.info(f"opencode server 就绪：{base_url}（version={health.get('version')}）")
                log_handle.close()
                return server
        except OpencodeError as exc:
            last_error = str(exc)
        time.sleep(HEALTH_POLL_SECONDS)
    server.stop()
    tail = ""
    try:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-800:]
    except OSError:
        pass
    log_handle.close()
    raise OpencodeError(f"opencode server 健康检查超时（>{start_timeout:.0f}s）；最近错误：{last_error or '无'}；日志尾部：{tail}")
