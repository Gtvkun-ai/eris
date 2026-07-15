# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass

import pytest


@pytest.fixture(autouse=True)
def _isolate_global_rollout_controller():
    import runtime.rollout_control as rollout

    previous = rollout.GLOBAL_ROLLOUT_CONTROLLER
    yield
    rollout.GLOBAL_ROLLOUT_CONTROLLER = previous


def test_secure_redactor_hides_secret_url_path_and_email():
    from runtime.secure_redaction import SecureRedactor

    redactor = SecureRedactor(redact_pii=True)
    raw = (
        "api_key=AIza1234567890abcdefghijklmnop "
        "Bearer abcdefghijklmnop.qwertyuiop "
        "http://127.0.0.1:8000/a?token=rawsecret "
        r"C:\Users\Nam\secret.txt nam@example.com"
    )
    result = redactor.text(raw)
    assert "AIza123" not in result.value
    assert "rawsecret" not in result.value
    assert "127.0.0.1" not in result.value
    assert "Nam\\secret" not in result.value
    assert "nam@example.com" not in result.value
    assert {"google_api_key", "bearer", "private_url", "internal_path", "email"}.issubset(set(result.blocked_kinds))


def test_observability_redacts_nested_fields_and_sensitive_tag(tmp_path):
    from runtime.observability import ErisObservability

    obs = ErisObservability(enabled=True, jsonl_path=tmp_path / "obs.jsonl")
    obs.write_jsonl = False
    obs.log(
        "provider_error",
        tags={"authorization": "Bearer abcdefghijklmnop"},
        fields={"api_key": "sk-1234567890abcdefghijkl", "nested": {"email": "a@b.com"}},
    )
    event = obs.recent_events(limit=1)[0]
    rendered = json.dumps(event, ensure_ascii=False)
    assert "sk-123456" not in rendered
    assert "abcdefghijklmnop" not in rendered
    assert "a@b.com" not in rendered
    assert "đã ẩn" in rendered


def test_secure_log_filter_redacts_before_output():
    from app_logging import SecureLogFilter

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SecureLogFilter())
    logger = logging.getLogger("phase4-redaction-test")
    logger.handlers[:] = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.info("token=%s", "sk-1234567890abcdefghijkl")
    output = stream.getvalue()
    assert "sk-123456" not in output
    assert "đã ẩn" in output


def test_secret_versions_activate_and_rollback(tmp_path):
    from secret_versions import SecretVersionManager

    manager = SecretVersionManager(root=tmp_path)
    fp1 = manager.stage("v1", {"api_keys": {"GEMINI_API_KEY": "one"}})
    manager.activate("v1")
    fp2 = manager.stage("v2", {"api_keys": {"GEMINI_API_KEY": "two"}})
    status = manager.activate("v2")
    assert status.active_version == "v2"
    assert status.previous_version == "v1"
    assert fp1 != fp2
    assert manager.active_payload()["api_keys"]["GEMINI_API_KEY"] == "two"
    rolled = manager.rollback()
    assert rolled.active_version == "v1"
    assert manager.active_payload()["api_keys"]["GEMINI_API_KEY"] == "one"


def test_secret_versions_reject_latest_and_immutable_overwrite(tmp_path):
    from secret_versions import SecretVersionManager

    manager = SecretVersionManager(root=tmp_path)
    with pytest.raises(ValueError):
        manager.stage("latest", {"x": "y"})
    manager.stage("v1", {"x": "one"})
    with pytest.raises(FileExistsError):
        manager.stage("v1", {"x": "two"})


def test_provider_registry_requires_complete_protocol():
    from runtime.provider_interfaces import ProviderHealth, ProviderRegistry

    class GoodAction:
        def execute(self, action_name: str, action_input: str = ""):
            return (action_name, action_input)

        def health(self):
            return ProviderHealth(True, "good_action")

    class Broken:
        pass

    registry = ProviderRegistry()
    registry.register("action", GoodAction())
    assert registry.get("action").execute("x", "y") == ("x", "y")
    assert registry.health()["action"].ready is True
    with pytest.raises(TypeError):
        registry.register("speech", Broken())


def test_rollout_registers_hardening_features_and_singing_defaults_off(monkeypatch, tmp_path):
    import runtime.rollout_control as rollout

    monkeypatch.delenv("ERIS_ROLLOUT_SINGING_CAPABILITY_MODE", raising=False)
    monkeypatch.delenv("ERIS_SINGING_CAPABILITY", raising=False)
    controller = rollout.RolloutController(state_path=tmp_path / "rollout.json")
    assert "director_semantic_gate" in controller.configs
    assert "stage_final_sanitizer" in controller.configs
    assert controller.decide("director_semantic_gate", session_id="a").apply is True
    assert controller.decide("singing_capability", session_id="a").apply is False


def test_hardening_health_gate_kills_locale_switch_immediately(tmp_path):
    from runtime.hardening_rollout import HardeningHealthGate
    from runtime.rollout_control import RolloutController

    controller = RolloutController(state_path=tmp_path / "rollout.json")
    gate = HardeningHealthGate(controller)
    findings = gate.evaluate({
        "tts_locale_switch_rate{provider=edge}": {"count": 1, "sum": 1.0, "p95": 1.0},
    })
    finding = next(item for item in findings if item.metric == "tts_locale_switch_rate")
    assert finding.triggered is True
    assert controller.decide("tts_language_pin", session_id="x").killed is True


def test_hardening_health_gate_uses_false_success_baseline(monkeypatch, tmp_path):
    from runtime.hardening_rollout import HardeningHealthGate
    from runtime.rollout_control import RolloutController

    monkeypatch.setenv("ERIS_BASELINE_FALSE_SUCCESS_RATE", "0.10")
    monkeypatch.setenv("ERIS_HARDENING_ROLLBACK_MIN_SAMPLES", "20")
    controller = RolloutController(state_path=tmp_path / "rollout.json")
    gate = HardeningHealthGate(controller)
    findings = gate.evaluate({
        "false_success_action_rate": {"count": 3, "sum": 3.0},
        "action_confirmation_total": {"count": 20, "sum": 20.0},
    })
    finding = next(item for item in findings if item.metric == "false_success_action_rate")
    assert finding.observed == pytest.approx(0.15)
    assert finding.threshold == pytest.approx(0.12)
    assert finding.triggered is True


def test_speech_contract_safe_rollback_ignores_bad_turn_override(monkeypatch, tmp_path):
    import runtime.rollout_control as rollout
    from runtime.speech_contract import SpeechContractResolver

    controller = rollout.RolloutController(state_path=tmp_path / "rollout.json")
    controller.request_kill("tts_language_pin", reason="test")
    contract = SpeechContractResolver().resolve(
        {"speech_contract": {"language": "ja", "locale": "ja-JP", "voice_family": "wrong"}},
        text="Xin chào, đây là tiếng Việt.",
    )
    assert contract.language == "vi"
    assert contract.locale == "vi-VN"
    assert contract.provider_tier == "safe_legacy"


def test_action_confirmation_rollout_can_disable_observer(monkeypatch, tmp_path):
    import runtime.rollout_control as rollout
    from actions.executor import ActionExecutor
    from actions.contracts import ActionExecutionResult
    from actions.observer import ActionObservation

    class Observer:
        calls = 0

        def observe(self, result, *, timeout_s=0.45):
            self.calls += 1
            return ActionObservation(True, "should_not_run")

    class Executor(ActionExecutor):
        def _set_volume(self, action_input: str):
            return ActionExecutionResult(
                action_name="set_volume", action_input=action_input,
                success=True, message="sent", status="dispatched",
            )

    controller = rollout.RolloutController(state_path=tmp_path / "rollout.json")
    controller.request_kill("action_confirmation", reason="test")
    observer = Observer()
    result = Executor(observer=observer).execute("set_volume", "50")
    assert observer.calls == 0
    assert result.observed is False
    assert result.observer_reason == "confirmation_feature_disabled"


def test_eris_secrets_reads_active_version_manifest(monkeypatch, tmp_path):
    import importlib
    import secret_versions

    monkeypatch.setenv("ERIS_PROJECT_ROOT", str(tmp_path))
    manager = secret_versions.SecretVersionManager()
    manager.stage("v1", {"secrets": {"ERIS_PHASE4_SECRET_TEST": "versioned-value"}})
    manager.activate("v1")

    import eris_secrets
    importlib.reload(eris_secrets)
    eris_secrets.reload_secrets()
    assert eris_secrets.get_secret("ERIS_PHASE4_SECRET_TEST") == "versioned-value"
