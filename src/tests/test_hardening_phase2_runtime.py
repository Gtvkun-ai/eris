# -*- coding: utf-8 -*-
"""Hồi quy cho đợt hardening phase 2.

Các test tập trung vào chỗ runtime trước đây dễ tự lừa mình: xưng hô được vá
mù, action dispatch bị gọi là thành công, và TTS fallback đổi luôn ngôn ngữ.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from actions.confirmation import public_action_text
from actions.contracts import ActionExecutionResult, ActionExecutionStatus
from actions.executor import ActionExecutor
from actions.observer import ActionObservation
from llm.token_pressure import TokenPressureGovernor
from runtime import hardening_metrics, observability, tts_engine
from runtime.addressing_policy import sanitize_legacy_addressing
from runtime.observability import ErisObservability
from runtime.tts_circuit_breaker import TtsCircuitBreaker


class _ActionHarness(ActionExecutor):
    def _set_volume(self, action_input: str) -> ActionExecutionResult:
        return ActionExecutionResult(
            action_name="set_volume",
            action_input=action_input,
            success=True,
            message="Đã gửi yêu cầu chỉnh âm lượng.",
            data={"level": action_input},
            status=ActionExecutionStatus.DISPATCHED,
        )


class _ConfirmedObserver:
    def observe(self, result: ActionExecutionResult, *, timeout_s: float = 0.45) -> ActionObservation:
        return ActionObservation(
            True,
            "test_postcondition_confirmed",
            ("test:volume=80",),
            {"observed_level": "80"},
        )


class _UnconfirmedObserver:
    def observe(self, result: ActionExecutionResult, *, timeout_s: float = 0.45) -> ActionObservation:
        return ActionObservation(False, "test_postcondition_missing")


def test_addressing_policy_repairs_structures_without_blind_global_replace():
    assert sanitize_legacy_addressing("Thưa Ngài, tôi đã kiểm tra.").text == "Tôi đã kiểm tra."
    assert sanitize_legacy_addressing("Tên Ngài là An.").text == "Tên bạn là An."
    assert sanitize_legacy_addressing("Mắt Ngài mỏi rồi.").text == "Mắt bạn mỏi rồi."
    assert sanitize_legacy_addressing("Ngài đang làm gì?").text == "Bạn đang làm gì?"


def test_addressing_policy_preserves_technical_master_terms():
    assert sanitize_legacy_addressing("master switch vẫn bật").text == "master switch vẫn bật"
    assert sanitize_legacy_addressing("audio master bus").text == "audio master bus"
    assert sanitize_legacy_addressing("audio mastering").text == "audio mastering"


def test_action_observer_upgrades_only_confirmed_postcondition():
    result = _ActionHarness(observer=_ConfirmedObserver()).execute("set_volume", "80")
    assert result.status == ActionExecutionStatus.OBSERVED
    assert result.observed is True
    assert result.observer_reason == "test_postcondition_confirmed"
    assert public_action_text(result) == "Âm lượng hiện ở khoảng 80 phần trăm."


def test_action_without_postcondition_stays_dispatch_only():
    result = _ActionHarness(observer=_UnconfirmedObserver()).execute("set_volume", "80")
    assert result.status == ActionExecutionStatus.DISPATCHED
    assert result.observed is False
    assert result.observer_reason == "test_postcondition_missing"
    text = public_action_text(result).lower()
    assert "gửi yêu cầu" in text
    assert "đã tăng" not in text


def test_tts_voice_configuration_rejects_cross_locale_voice(monkeypatch):
    monkeypatch.setenv("ERIS_TTS_EDGE_VI_VOICE", "ja-JP-NanamiNeural")
    assert tts_engine._edge_voice_candidates("vi") == []


def test_japanese_fallback_never_translates_vietnamese_in_hidden_lane(monkeypatch):
    monkeypatch.delenv("ERIS_TTS_EDGE_ROMAJI", raising=False)
    assert tts_engine._edge_text_candidates("Tôi đang nói tiếng Việt.", "ja") == []
    assert tts_engine._edge_text_candidates("こんにちは。", "ja") == [("raw", "こんにちは。")]


def test_romaji_fallback_is_opt_in_not_default(monkeypatch):
    monkeypatch.delenv("ERIS_TTS_EDGE_ROMAJI", raising=False)
    assert tts_engine._edge_romaji_enabled() is False


def test_training_sample_no_longer_teaches_legacy_addressing():
    path = Path(__file__).resolve().parents[1] / "machine_context_sample.jsonl"
    legacy = re.compile(r"\b(?:ngài|ngai|master)\b", re.IGNORECASE)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 700
    for raw in lines:
        item = json.loads(raw)
        for message in item.get("conversations", []):
            role = message.get("role")
            content = str(message.get("content", ""))
            if role == "assistant":
                assert not legacy.search(content)
            elif role == "system":
                # Tên từ cấm chỉ được xuất hiện trong chính câu policy cấm nó.
                residue = content.replace("Ngài/Master", "")
                assert not legacy.search(residue)


def test_report_metrics_are_exposed_in_runtime_hardening_dashboard(monkeypatch):
    store = ErisObservability(enabled=True)
    store.write_jsonl = False
    monkeypatch.setattr(observability, "GLOBAL_OBSERVABILITY", store)

    hardening_metrics.record_director_semantic_gate(
        accepted=False, reason="semantic_similarity_below_threshold", score=0.3, threshold=0.72
    )
    hardening_metrics.record_provider_rate_limit(
        provider="gemini", lane="tts", retry_after_s=60.0
    )
    hardening_metrics.record_user_correction_after_action(
        action="set_volume", strategy="repair_ack_then_answer"
    )

    dashboard = store.dashboard_payload()["dashboards"]["runtime_hardening"]
    names = {key.split("{", 1)[0] for key in dashboard}
    assert "director_semantic_reject_rate" in names
    assert "429_per_provider_per_lane" in names
    assert "user_correction_after_action_rate" in names


def test_token_governor_emits_lane_budget_and_429_metrics(monkeypatch):
    store = ErisObservability(enabled=True)
    store.write_jsonl = False
    monkeypatch.setattr(observability, "GLOBAL_OBSERVABILITY", store)
    governor = TokenPressureGovernor(window_seconds=60, budgets={"gemini": 1000})

    governor.record_request(
        "gemini", lane="speech_localizer", prompt_tokens=240, output_tokens=80, now=0
    )
    governor.record_rate_limit(
        "gemini", lane="speech_localizer", retry_after_s=20, now=1
    )

    snapshot = store.metric_snapshot()
    names = {key.split("{", 1)[0] for key in snapshot}
    assert "avg_prompt_tokens_by_lane" in names
    assert "429_per_provider_per_lane" in names


def test_tts_breaker_emits_open_metric(monkeypatch):
    store = ErisObservability(enabled=True)
    store.write_jsonl = False
    monkeypatch.setattr(observability, "GLOBAL_OBSERVABILITY", store)
    breaker = TtsCircuitBreaker(failure_threshold=1, cooldown_s=10)
    key = ("gemini", "tts", "Aoede", "vi-VN")

    breaker.record_failure(key, kind="rate_limit", now=0)

    snapshot = store.metric_snapshot()
    names = {name.split("{", 1)[0] for name in snapshot}
    assert "tts_breaker_open_count" in names
