from __future__ import annotations

import json
import logging
from types import SimpleNamespace

from runtime.companion_model_routing import (
    CompanionRoutingPolicy,
    route_companion_turn,
)


def test_clear_companion_turn_stays_on_flash() -> None:
    decision = route_companion_turn("mấy giờ rồi")
    assert decision.tier == "flash"
    assert decision.thinking_mode == "disabled"


def test_abstract_companion_turn_uses_pro_with_thinking() -> None:
    decision = route_companion_turn(
        "Nếu ký ức tạo nên con người thì một AI mất ký ức còn là chính nó không?"
    )
    assert decision.tier == "pro"
    assert decision.thinking_mode == "enabled"
    assert decision.reasoning_effort in {"high", "max"}
    assert "abstract_meaning" in decision.reasons


def test_explicit_literary_request_uses_pro_without_forced_thinking() -> None:
    decision = route_companion_turn(
        "Viết lại câu này tinh tế và có hồn hơn, đừng khô như thông báo hệ thống."
    )
    assert decision.tier == "pro"
    assert decision.style_sensitive is True
    assert decision.thinking_mode == "disabled"
    assert "expressive_style_request" in decision.reasons


def test_relational_subtext_uses_pro() -> None:
    decision = route_companion_turn(
        "Eris, em thật sự nghĩ gì về tôi và mối quan hệ giữa tôi với em?"
    )
    assert decision.tier == "pro"
    assert "relational_subtext" in decision.reasons


def test_short_contextual_reference_uses_pro_when_history_exists() -> None:
    history = [
        {"role": "assistant", "content": "Tôi nghĩ cậu đang né điều cậu thực sự muốn nói."}
    ]
    decision = route_companion_turn("sao em nói vậy?", recent_history=history)
    assert decision.tier == "pro"
    assert "contextual_ambiguity" in decision.reasons


def test_missing_required_facts_prefers_one_clarification_not_pro() -> None:
    decision = route_companion_turn("sửa nó đi")
    assert decision.tier == "flash"
    assert decision.clarification_preferred is True
    assert "ask exactly one focused question" in decision.prompt_context()


def test_policy_can_disable_pro_routing() -> None:
    decision = route_companion_turn(
        "Viết thật sâu sắc về ý nghĩa tồn tại.",
        policy=CompanionRoutingPolicy(enabled=False),
    )
    assert decision.tier == "flash"
    assert decision.reasons == ("routing_disabled",)


def test_runtime_public_writer_passes_route_thinking_to_deepseek() -> None:
    from runtime.ai_orchestrated.model_router import AIRuntimeModelRouter

    captured: dict[str, object] = {}

    class _Client:
        base_url = "https://api.deepseek.com"
        model_name = "deepseek-v4-pro"

        def create_chat_completion(self, **kwargs):
            captured.update(kwargs)
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "text": "Một câu trả lời.",
                                    "should_speak": True,
                                    "performance_hint": "soft",
                                    "semantic_frame": {},
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

    pro = _Client()
    service = SimpleNamespace(
        client=SimpleNamespace(),
        fallback_client=None,
        style_client=None,
        _resolve_escalation_client=lambda: pro,
    )
    router = AIRuntimeModelRouter(service, logger=logging.getLogger("test"))
    router._run_inference = lambda _tier, func, **_kwargs: func()

    payload = router.generate_public_reply(
        chat_history=[],
        user_text="Ý nghĩa của ký ức là gì?",
        use_escalation=True,
        reasoning_effort="max",
        thinking_mode="enabled",
        routing_context="PRO abstract route",
    )

    assert payload["text"] == "Một câu trả lời."
    assert captured["thinking_mode"] == "enabled"
    assert captured["reasoning_effort"] == "max"
    messages = captured["messages"]
    assert isinstance(messages, list)
    assert "Runtime companion routing" in messages[0]["content"]


def test_deepseek_default_escalation_client_reuses_main_key(monkeypatch) -> None:
    import llm.deepseek_workers as deepseek_workers
    import llm.process_manager as process_manager
    from llm.deepseek_workers import WORKER_ROLES

    captured: dict[str, object] = {}

    class _Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    for name in (
        "ERIS_ESCALATION_PROVIDER",
        "ERIS_ESCALATION_MODEL",
        "ERIS_ESCALATION_BASE_URL",
        "ERIS_ESCALATION_API_KEY",
        "ERIS_REMOTE_BASE_URL",
        "ERIS_REMOTE_MODEL",
        "ERIS_REMOTE_API_KEY",
        "ERIS_DS2API_ENABLED",
        "ERIS_DS2API_API_KEY",
        "ERIS_DS_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    for role in WORKER_ROLES:
        monkeypatch.delenv(f"ERIS_DS_{role.upper()}_API_KEY", raising=False)
    monkeypatch.setenv("ERIS_REMOTE_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-main-deepseek")
    monkeypatch.setattr(process_manager, "apply_secrets_to_environ", lambda: None)
    monkeypatch.setattr(
        process_manager,
        "get_secret",
        lambda *names, default="": "sk-main-deepseek" if "DEEPSEEK_API_KEY" in names else default,
    )
    monkeypatch.setattr(deepseek_workers, "get_secret", lambda *names, default="": default)
    monkeypatch.setattr(process_manager, "OpenAICompatibleClient", _Client)

    manager = process_manager.RemoteModelProcessManager(
        logger=logging.getLogger("test"),
        project_root=".",
    )
    client = manager.build_escalation_client()

    assert client is not None
    assert captured["base_url"] == "https://api.deepseek.com"
    assert captured["model_name"] == "deepseek-v4-pro"
    assert captured["api_key"] == "sk-main-deepseek"
