from __future__ import annotations

import json
import logging

import pytest

from llm.deepseek_workers import (
    JsonlContractError,
    JsonlWorkerClient,
    canonical_json_line,
    load_worker_spec,
)
from llm.process_manager import RemoteModelProcessManager
from llm.service import LlmService


class _FakeClient:
    base_url = "http://127.0.0.1:6011/v1"
    model_name = "deepseek-v4-flash"
    configured_model_name = "deepseek-v4-flash"
    key_pool = None

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        content = self.outputs.pop(0)
        return {"choices": [{"message": {"content": content}}]}


def _call(client, *, response_format=None):
    return client.create_chat_completion(
        messages=[{"role": "user", "content": "return json"}],
        temperature=0.0,
        frequency_penalty=0.0,
        presence_penalty=0.0,
        max_tokens=64,
        response_format=response_format,
    )


def test_worker_spec_uses_exact_role_environment(monkeypatch):
    monkeypatch.setenv("ERIS_DS_BASE_URL", "http://localhost:6011/v1")
    monkeypatch.setenv("ERIS_DS_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("ERIS_DS_OBSERVER_API_KEY", "observer-gateway-key")

    spec = load_worker_spec("observer")

    assert spec.role == "observer"
    assert spec.api_key == "observer-gateway-key"
    assert spec.base_url == "http://localhost:6011/v1"
    assert spec.model == "deepseek-v4-flash"
    assert spec.jsonl_enabled is True


def test_jsonl_worker_canonicalizes_structured_content():
    raw = _FakeClient(['```json\n{ "b": 2, "a": 1 }\n```'])
    worker = JsonlWorkerClient(raw, role="observer", jsonl_enabled=True)

    payload = _call(worker, response_format={"type": "json_object"})

    content = payload["choices"][0]["message"]["content"]
    assert content == '{"b":2,"a":1}'
    assert "\n" not in content
    assert json.loads(content) == {"b": 2, "a": 1}


def test_jsonl_worker_repairs_once():
    raw = _FakeClient(["not json", '{"ok":true}'])
    worker = JsonlWorkerClient(raw, role="critic", jsonl_enabled=True, repair_attempts=1)

    payload = _call(worker, response_format={"type": "json_object"})

    assert payload["choices"][0]["message"]["content"] == '{"ok":true}'
    assert len(raw.calls) == 2
    assert "ONE valid JSON value" in raw.calls[1]["messages"][-1]["content"]


def test_jsonl_worker_does_not_touch_free_text():
    raw = _FakeClient(["plain style text"])
    worker = JsonlWorkerClient(raw, role="style", jsonl_enabled=False)

    payload = _call(worker, response_format=None)

    assert payload["choices"][0]["message"]["content"] == "plain style text"


def test_jsonl_worker_raises_after_failed_repair():
    raw = _FakeClient(["bad", "still bad"])
    worker = JsonlWorkerClient(raw, role="inner", jsonl_enabled=True, repair_attempts=1)

    with pytest.raises(JsonlContractError):
        _call(worker, response_format={"type": "json_object"})


def test_process_manager_builds_and_caches_role_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("ERIS_DS_BASE_URL", "http://127.0.0.1:6011/v1")
    monkeypatch.setenv("ERIS_DS_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("ERIS_DS_RESEARCH_API_KEY", "research-gateway-key")
    manager = RemoteModelProcessManager(logger=logging.getLogger("test"), project_root=str(tmp_path))

    first = manager.build_deepseek_worker_client("research")
    second = manager.build_deepseek_worker_client("research")

    assert first is second
    assert first.worker_role == "research"
    assert first.api_key == "research-gateway-key"


def test_llm_service_exposes_named_workers():
    companion = object()
    observer = object()
    critic = object()
    inner = object()
    style = object()
    research = object()

    service = LlmService(
        companion,
        style_client=style,
        observer_client=observer,
        critic_client=critic,
        inner_client=inner,
        research_client=research,
    )

    assert service.companion_client is companion
    assert service.observer_client is observer
    assert service.critic_client is critic
    assert service.inner_client is inner
    assert service.style_client is style
    assert service.research_client is research
    assert service.social_parser_client is observer
    assert service.social_critic_client is critic


def test_companion_key_can_boot_without_official_deepseek_key(monkeypatch, tmp_path):
    import llm.process_manager as pm

    monkeypatch.setenv("ERIS_REMOTE_PROVIDER", "deepseek")
    monkeypatch.setenv("ERIS_REMOTE_API_ENABLED", "1")
    monkeypatch.setenv("ERIS_DS_COMPANION_API_KEY", "companion-gateway-key")
    monkeypatch.setenv("ERIS_DS_BASE_URL", "http://127.0.0.1:6011/v1")
    monkeypatch.setenv("ERIS_DS_MODEL", "deepseek-v4-flash")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ERIS_REMOTE_API_KEY", raising=False)
    monkeypatch.delenv("ERIS_DS2API_API_KEY", raising=False)
    monkeypatch.setattr(pm, "get_provider_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(pm, "get_secret", lambda *names, default="": "")
    monkeypatch.setattr(pm, "_bootstrap_pool_key", lambda pool: "")

    manager = RemoteModelProcessManager(logger=logging.getLogger("test"), project_root=str(tmp_path))
    client = manager.build_client()

    assert client.worker_role == "companion"
    assert client.base_url == "http://127.0.0.1:6011/v1"
