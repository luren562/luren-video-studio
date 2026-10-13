"""模型响应元数据必须保留，供 Agent 判断截断与安全重试。"""
import json

import httpx
import pytest

from app import ai_client


@pytest.mark.parametrize("reason", ["length", "tool_calls", "repetition_truncation", None])
def test_chat_message_preserves_finish_reason_and_usage(monkeypatch, reason):
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "mimo-v2.6-pro", "choices": [{
            "finish_reason": reason, "message": {"role": "assistant", "content": "", "reasoning_content": "reason"}}],
            "usage": {"completion_tokens": 8000, "completion_tokens_details": {"reasoning_tokens": 7990}}})
    real_client = httpx.Client
    monkeypatch.setattr(ai_client.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    result = ai_client.chat_message(base_url="https://example.invalid/v1", api_key="", model="mimo-v2.6-pro",
                                    messages=[{"role": "user", "content": "test"}],
                                    extra_body={"max_completion_tokens": 8000, "thinking": {"type": "disabled"}})
    assert result.finish_reason == (reason or "")
    assert result.message["reasoning_content"] == "reason"
    assert result.usage["reasoning_tokens"] == 7990
    assert "max_tokens" not in captured[0]
    assert captured[0]["max_completion_tokens"] == 8000
