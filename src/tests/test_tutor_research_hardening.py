# -*- coding: utf-8 -*-
"""Hardening/eval cho research-followup nhẹ của Eris."""

from __future__ import annotations

from types import SimpleNamespace

from cortex.tutor.config import TutorConfig, TutorLogger
from llm.tutor_backend import FakeTutorBackend
from runtime.tutor_daemon import TutorDaemon


class _CapturingBackend(FakeTutorBackend):
    def __init__(self, answer_text: str):
        super().__init__(answer_text=answer_text)
        self.questions = []

    def ask(self, question, *, on_stage=None):
        self.questions.append(question)
        return super().ask(question, on_stage=on_stage)


class _DigestSpy:
    def __init__(self):
        self.calls = 0

    def digest(self, episode):
        self.calls += 1
        return 1


def _daemon(*, answer: str, persist: bool = False, max_words: int = 180):
    config = TutorConfig(
        enabled=True,
        research_answer_max_words=max_words,
        research_persist_answers=persist,
    ).normalized()
    backend = _CapturingBackend(answer)
    digest = _DigestSpy()
    daemon = TutorDaemon(
        config,
        collector=object(),
        gate=object(),
        formulator=object(),
        backend=backend,
        digest=digest,
        logger=TutorLogger(),
    )
    return daemon, backend, digest


def test_anchor_resolver_returns_confidence_and_candidates_for_reference_followup():
    from runtime.tutor_research_policy import resolve_research_anchor

    resolution = resolve_research_anchor(
        "nghiên cứu sâu phần này đi",
        [
            "Newton là ai?",
            "Thiết kế Gemma hỏi Gemini rồi local critic phân tích lại cho Eris",
        ],
    )

    assert "Gemma hỏi Gemini" in resolution.topic
    assert resolution.confidence >= 0.6
    assert resolution.anchor_text.startswith("Thiết kế")
    assert resolution.misread_risk in {"low", "medium"}
    assert resolution.candidates


def test_anchor_resolver_keeps_focus_when_user_corrects_to_gemma_section():
    from runtime.tutor_research_policy import resolve_research_anchor

    resolution = resolve_research_anchor(
        "không, ý tôi là phần Gemma ấy",
        ["So sánh Gemini và Gemma cho research follow-up của Eris"],
    )

    assert "phần Gemma" in resolution.topic
    assert "Neo hội thoại" in resolution.topic
    assert "Gemini và Gemma" in resolution.topic
    assert resolution.assumption_note.startswith("focused_followup")


def test_anchor_resolution_is_written_to_coordinator_ledger_meta():
    from domain import Decision
    from runtime.coordinator import RuntimeCoordinator

    class _Ledger:
        def __init__(self):
            self.records = []

        def record_assistant(self, text, *, meta=None):
            self.records.append((text, meta or {}))

    class _Probe:
        _deliver_research_followup = RuntimeCoordinator._deliver_research_followup
        _apply_director_precommit_guard = lambda self, decision, frame=None, channel="chat": decision
        _apply_v3_authority_guard = lambda self, decision, frame=None, channel="chat": decision
        _send_decision_to_body = lambda self, decision, channel="chat": None

        def __init__(self):
            self._last_tutor_anchor_resolution = {
                "topic": "Neo Gemma",
                "confidence": 0.82,
                "anchor_text": "So sánh Gemini/Gemma",
                "misread_risk": "low",
            }
            self._last_tutor_research_artifact = {
                "bundle_id": "evb_test",
                "verification": {"overall_status": "passed"},
            }
            self._last_tutor_research_thread = {"thread_id": "evb_test"}
            self._last_tutor_research_metrics = {"source_count": 1}
            self._last_tutor_research_memory_decision = {"should_persist": False, "reason": "quick_search_ephemeral"}
            self.ledger = _Ledger()
            self.logger = SimpleNamespace(warning=lambda *a, **k: None)
            self.last_chat_answer = ""

        def _ensure_session_turn_ledger(self):
            return self.ledger

        def _append_chat_history(self, *args, **kwargs):
            pass

    owner = _Probe()
    owner._deliver_research_followup("Gemma", "Kết quả có nguồn.", mode="research")

    assert owner.ledger.records
    meta = owner.ledger.records[-1][1]
    assert meta["anchor_resolution"]["confidence"] == 0.82
    assert meta["research_memory_policy"]["reason"] == "quick_search_ephemeral"


def test_research_memory_policy_blocks_ephemeral_quick_search_even_when_persist_enabled():
    from cortex.tutor.research_memory_policy import should_persist_research_answer

    cfg = TutorConfig(enabled=True, research_persist_answers=True).normalized()
    bundle = {
        "mode": "quick_search",
        "sources": [{"trust_tier": 3}],
        "claims": [{"status": "supported", "support_source_ids": ["src_1"]}],
        "verification": {
            "overall_status": "passed",
            "citation_coverage": 1.0,
            "orphan_claim_count": 0,
            "contested_claim_count": 0,
        },
    }

    decision = should_persist_research_answer(cfg, bundle, mode="quick_search")

    assert decision.should_persist is False
    assert decision.reason == "quick_search_ephemeral"


def test_research_memory_policy_allows_verified_research_when_persist_enabled():
    from cortex.tutor.research_memory_policy import should_persist_research_answer

    cfg = TutorConfig(enabled=True, research_persist_answers=True).normalized()
    bundle = {
        "mode": "research",
        "sources": [{"trust_tier": 3}],
        "claims": [{"status": "supported", "support_source_ids": ["src_1"]}],
        "verification": {
            "overall_status": "passed",
            "citation_coverage": 0.92,
            "orphan_claim_count": 0,
            "contested_claim_count": 0,
        },
    }

    decision = should_persist_research_answer(cfg, bundle, mode="research")

    assert decision.should_persist is True
    assert decision.reason == "verified_research_persist"


def test_research_now_with_persist_enabled_still_blocks_missing_sources_from_digest():
    daemon, backend, digest = _daemon(answer="Kết luận nghe có vẻ đúng nhưng không có nguồn.", persist=True)

    result = daemon.research_now("kiểm chứng claim thiếu nguồn")

    assert result
    assert digest.calls == 0
    assert daemon.last_research_memory_decision["should_persist"] is False
    assert daemon.last_research_memory_decision["reason"] in {"no_sources", "verification_failed", "low_citation_coverage"}


def test_search_now_sends_memory_policy_artifact_and_never_digests_quick_search():
    daemon, backend, digest = _daemon(
        answer="Kết luận có nguồn. Nguồn: https://godotengine.org/releases",
        persist=True,
    )

    result = daemon.search_now("Godot release mới nhất")

    assert result
    assert digest.calls == 0
    assert daemon.last_research_memory_decision["reason"] == "quick_search_ephemeral"


def test_secret_scrubber_redacts_bearer_and_common_service_tokens_in_critic_prompt():
    from cortex.tutor.gemma_research_critic import build_gemma_critic_prompt
    from cortex.tutor.secret_scrubber import contains_secret_like

    prompt = build_gemma_critic_prompt(
        "check token",
        "Bearer abcdefghijklmnopqrstuvwxyz123456 and api_key=supersecretvalue12345",
    )

    assert "Bearer abc" not in prompt
    assert "supersecretvalue" not in prompt
    assert contains_secret_like(prompt) is False
