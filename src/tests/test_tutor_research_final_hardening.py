# -*- coding: utf-8 -*-
"""Final hardening tests cho Tutor search/research runtime."""

from __future__ import annotations

from types import SimpleNamespace


def test_low_confidence_anchor_requires_clarification():
    from runtime.tutor_research_policy import (
        FollowupAnchorResolution,
        anchor_resolution_needs_clarification,
        build_anchor_clarification_text,
    )

    resolution = FollowupAnchorResolution(
        topic="nghiên cứu sâu phần đó đi",
        confidence=0.31,
        assumption_note="no_prior_anchor_found",
        misread_risk="high",
    )

    assert anchor_resolution_needs_clarification(resolution) is True
    assert "chưa chắc" in build_anchor_clarification_text(resolution)


def test_tutor_search_job_marks_different_topic_as_not_same():
    from runtime.tutor_search_jobs import hash_topic, looks_same_topic, make_tutor_search_job

    job = make_tutor_search_job("Gemma critic phân tích Tutor answer", mode="research", seq=3)

    assert job.job_id
    assert job.topic_hash == hash_topic("Gemma critic phân tích Tutor answer")
    assert looks_same_topic("Gemma critic phân tích lại Tutor", job.topic) is True
    assert looks_same_topic("hôm nay ăn ốc có nên bỏ tủ lạnh không", job.topic) is False


def test_tutor_logger_scrubs_nested_secret_payload():
    from cortex.tutor.config import TutorLogger
    from cortex.tutor.secret_scrubber import contains_secret_like

    logger = TutorLogger()
    logger._emit({
        "kind": "nested",
        "meta": {
            "prompt": "Bearer abcdefghijklmnopqrstuvwxyz123456",
            "list": ["api_key=supersecretvalue123456"],
        },
    })

    payload = str(logger.records[-1])
    assert "abcdefghijklmnopqrstuvwxyz" not in payload
    assert "supersecretvalue" not in payload
    assert contains_secret_like(payload) is False


def test_settings_protocol_accepts_tutor_policy_patch():
    from runtime.settings_protocol import normalize_settings_message

    normalized = normalize_settings_message({
        "scope": "advanced",
        "settings": {
            "tutor": {
                "quick_search_enabled": False,
                "research_enabled": True,
                "self_search_enabled": False,
                "stale_result_guard_enabled": True,
            }
        },
    })

    assert normalized.patch["tutor"]["quick_search_enabled"] is False
    assert normalized.patch["tutor"]["research_enabled"] is True
    assert normalized.rejected_fields == ()


def test_coordinator_drops_stale_research_followup_before_body_send():
    from domain import Decision
    from runtime.coordinator import RuntimeCoordinator

    class _Probe:
        _deliver_research_followup = RuntimeCoordinator._deliver_research_followup
        _tutor_runtime_bool = lambda self, *path, default=True: True
        logger = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)

        def __init__(self):
            self._active_research_job = {"job_id": "job_old", "topic": "Gemma", "stale": True, "stale_reason": "user_changed_topic"}
            self.sent = []
            self.records = []

        def _send_decision_to_body(self, decision, channel="chat"):
            self.sent.append(decision)

        def _ensure_session_turn_ledger(self):
            return SimpleNamespace(record_assistant=lambda text, meta=None: self.records.append((text, meta or {})))

        def _append_chat_history(self, *a, **k):
            pass

        def _apply_director_precommit_guard(self, decision, frame=None, channel="chat"):
            return decision

        def _apply_v3_authority_guard(self, decision, frame=None, channel="chat"):
            return decision

    owner = _Probe()
    owner._deliver_research_followup("Gemma", "Kết quả cũ", mode="research", job_id="job_old")

    assert owner.sent == []
    assert owner.records == []
