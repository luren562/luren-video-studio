"""OpenAI 兼容的文本客户端。

职责边界：组装 URL / 认证头、超时、调用 Chat Completions、解析 JSON、
把上游错误归一化为稳定的错误类型。业务提示词与落库不在这里。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import get_settings


ERROR_TYPES = {
    "authentication",
    "rate_limit",
    "timeout",
    "invalid_response",
    "provider_error",
    "configuration",
    "network_error",
}


class AIError(Exception):
    def __init__(self, error_type: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.error_type = error_type if error_type in ERROR_TYPES else "provider_error"
        self.message = message
        self.status_code = status_code


@dataclass
class ChatResult:
    content: str
    model: str = ""
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0


@dataclass
class ChatMessageResult:
    """完整返回一轮 assistant message（含 tool_calls / reasoning_content），供 agent 循环使用。"""

    message: dict
    model: str = ""
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0
    finish_reason: str = ""


@dataclass
class ImageResult:
    """一张生成图：网关可能返回 base64 或可下载 url，两者都保留。"""

    b64_json: str = ""
    url: str = ""
    revised_prompt: str = ""
    model: str = ""
    latency_ms: int = 0


USAGE_KEYS = ("prompt_tokens", "completion_tokens", "reasoning_tokens", "cached_tokens", "total_tokens")


def normalize_usage(value: dict | None) -> dict:
    """把不同 OpenAI 兼容网关的 usage 形状统一成可累计的结构。

    网关有的把 reasoning/cached 放在 ``*_tokens_details``，有的直接放在顶层。
    保留未知字段与 raw，便于后续成本分析，同时让 Agent 只依赖这五个标准字段。
    """
    raw = dict(value or {}) if isinstance(value, dict) else {}
    prompt_details = raw.get("prompt_tokens_details") or {}
    completion_details = raw.get("completion_tokens_details") or {}

    def number(*values: Any) -> int:
        for item in values:
            if isinstance(item, (int, float)):
                return max(0, int(item))
            if isinstance(item, str) and item.isdigit():
                return int(item)
        return 0

    prompt = number(raw.get("prompt_tokens"), raw.get("input_tokens"))
    completion = number(raw.get("completion_tokens"), raw.get("output_tokens"))
    reasoning = number(raw.get("reasoning_tokens"), raw.get("reasoning"),
                       completion_details.get("reasoning_tokens"), completion_details.get("reasoning"))
    cached = number(raw.get("cached_tokens"), raw.get("cache_read_input_tokens"),
                    raw.get("prompt_cache_hit_tokens"), prompt_details.get("cached_tokens"),
                    prompt_details.get("cache_read_input_tokens"))
    total = number(raw.get("total_tokens"), raw.get("total")) or prompt + completion
    normalized = {**raw, "prompt_tokens": prompt, "completion_tokens": completion,
                  "reasoning_tokens": reasoning, "cached_tokens": cached, "total_tokens": total}
    normalized["raw"] = raw
    return normalized


def chat_endpoint(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise AIError("configuration", "AI base_url 未配置")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def image_endpoint(base_url: str) -> str:
    """OpenAI 兼容生图端点。

    若 Base URL 已带版本段（`/v1`、`/v4`、`/compatible-mode/v1`、`/api/paas/v4` 等）就直接拼
    `/images/generations`；只有裸主机名才补 `/v1/images/generations`，避免出现 `.../v4/v1/...`。
    """
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise AIError("configuration", "AI base_url 未配置")
    if base.endswith("/images/generations"):
        return base
    if re.search(r"/v\d+$", base):  # 已含版本段（v1/v2/v3/v4…）
        return base + "/images/generations"
    return base + "/v1/images/generations"


def _normalize_error(exc: Exception) -> AIError:
    if isinstance(exc, AIError):
        return exc
    if isinstance(exc, httpx.TimeoutException):
        return AIError("timeout", "请求超时")
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return AIError("authentication", f"鉴权失败（{code}）", code)
        if code == 429:
            return AIError("rate_limit", "触发限流（429）", code)
        if code >= 500:
            return AIError("provider_error", f"上游错误（{code}）", code)
        return AIError("provider_error", f"请求失败（{code}）", code)
    if isinstance(exc, httpx.HTTPError):
        return AIError("network_error", f"网络错误：{exc}")
    if isinstance(exc, json.JSONDecodeError):
        return AIError("invalid_response", "响应不是合法 JSON")
    return AIError("provider_error", str(exc))


def chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int | None = None,
    response_json: bool = False,
) -> ChatResult:
    settings = get_settings()
    endpoint = chat_endpoint(base_url)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if response_json:
        payload["response_format"] = {"type": "json_object"}

    started = time.perf_counter()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(
                settings.ai_total_timeout_seconds,
                connect=settings.ai_connect_timeout_seconds,
                read=settings.ai_read_timeout_seconds,
            ),
            follow_redirects=True,
        ) as client:
            resp = client.post(endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001 - 统一归一化
        raise _normalize_error(exc) from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIError("invalid_response", "响应缺少 choices/message/content") from exc

    return ChatResult(
        content=content or "",
        model=data.get("model", model),
        usage=normalize_usage(data.get("usage")),
        latency_ms=latency_ms,
    )


def chat_message(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict | None = None,
    temperature: float = 0.4,
    max_tokens: int | None = None,
    extra_body: dict[str, Any] | None = None,
) -> ChatMessageResult:
    """Agent 用：支持 function/tool calling 与多模态 content 数组，返回完整 message。

    与 `chat_completion` 的区别只在于返回 `choices[0].message` 原样（含 `tool_calls`），
    便于工具循环。OpenAI 兼容网关（OpenRouter/DeepInfra/Vercel 上的 MiMo 等）均适用。
    """
    settings = get_settings()
    endpoint = chat_endpoint(base_url)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice or "auto"
    if extra_body:
        payload.update(extra_body)

    started = time.perf_counter()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(
                settings.ai_total_timeout_seconds,
                connect=settings.ai_connect_timeout_seconds,
                read=settings.ai_read_timeout_seconds,
            ),
            follow_redirects=True,
        ) as client:
            resp = client.post(endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001 - 统一归一化
        raise _normalize_error(exc) from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    try:
        choice = data["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIError("invalid_response", "响应缺少 choices/message") from exc

    return ChatMessageResult(
        message=message or {},
        model=data.get("model", model),
        usage=normalize_usage(data.get("usage")),
        latency_ms=latency_ms,
        finish_reason=choice.get("finish_reason") or "",
    )


def image_generation(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    size: str | None = None,
    n: int | None = None,
    response_format: str | None = None,
    extra: dict[str, Any] | None = None,
    timeout_seconds: float | None = None,
) -> ImageResult:
    """OpenAI 兼容 `POST /v1/images/generations`（同时兼容硅基流动等变体）。

    - 尺寸字段：硅基流动用 `image_size`，OpenAI 用 `size`（按 base_url 自动选择）。
    - 去水印：统一带 `X-Enable-Watermark: 0` 请求头；智谱额外用 body 的 `watermark_enabled`。
    - 响应：`data[0]`（OpenAI）与 `images[0]`（硅基流动）都解析；b64 与 url 均支持。
    """
    settings = get_settings()
    endpoint = image_endpoint(base_url)
    low = (base_url or "").lower()
    is_siliconflow = "siliconflow" in low
    is_zhipu = "bigmodel" in low or "zhipu" in low
    # 关闭显式 AI 水印：硅基流动用请求头；智谱用 body 字段；其他网关忽略未知项。
    headers = {"Content-Type": "application/json", "X-Enable-Watermark": "0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload: dict[str, Any] = {"model": model, "prompt": prompt}
    if n:
        payload["n"] = n
    if size:
        payload["image_size" if is_siliconflow else "size"] = size
    if response_format:
        payload["response_format"] = response_format
    if is_zhipu:
        payload["watermark_enabled"] = False
    if extra:
        payload.update(extra)

    timeout = timeout_seconds or settings.cover_timeout_seconds
    started = time.perf_counter()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout, connect=settings.ai_connect_timeout_seconds, read=timeout),
            follow_redirects=True,
        ) as client:
            resp = client.post(endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        body = (exc.response.text or "")[:300] if exc.response is not None else ""
        raise AIError("provider_error", f"{status} @ {endpoint}：{body}".strip(), status) from exc
    except Exception as exc:  # noqa: BLE001 - 统一归一化
        raise _normalize_error(exc) from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    items = None
    if isinstance(data, dict):
        for key in ("data", "images"):  # OpenAI= data[]，硅基流动= images[]
            value = data.get(key)
            if isinstance(value, list) and value:
                items = value
                break
    if not items:
        raise AIError("invalid_response", "生图响应缺少 data/images")
    item = items[0]
    if not isinstance(item, dict) or not (item.get("b64_json") or item.get("url")):
        raise AIError("invalid_response", "生图响应既无 b64_json 也无 url")
    return ImageResult(
        b64_json=item.get("b64_json") or "",
        url=item.get("url") or "",
        revised_prompt=item.get("revised_prompt") or "",
        model=data.get("model", model),
        latency_ms=latency_ms,
    )


def extract_json(text: str) -> dict:
    """从模型输出里抽取 JSON 对象（容忍 ```json 包裹与前后噪声）。"""
    if not text:
        raise AIError("invalid_response", "模型返回为空")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.lstrip().lower().startswith("json"):
            cleaned = cleaned.lstrip()[4:]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError as exc:
                raise AIError("invalid_response", "无法解析模型返回的 JSON") from exc
        raise AIError("invalid_response", "无法解析模型返回的 JSON")
