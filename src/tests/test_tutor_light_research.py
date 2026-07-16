# -*- coding: utf-8 -*-
"""Regression cho đường nghiên cứu nhẹ qua Tutor web."""

from __future__ import annotations

from cortex.tutor.config import TutorConfig, TutorLogger
from cortex.tutor.contracts import TutorAnswer
from llm.tutor_backend import FakeTutorBackend
from runtime.tutor_daemon import TutorDaemon
from runtime.tutor_research_policy import (
    build_lightweight_research_prompt,
    compact_research_answer,
    resolve_research_topic,
    score_research_need,
)


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


def _daemon(*, answer: str, persist: bool = False, max_words: int = 120):
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


def test_simple_world_knowledge_does_not_burn_tutor_turn():
    decision = score_research_need("Pytest là gì?", intent="world_knowledge")
    assert decision.should_delegate is False
    assert decision.score < 0.58


def test_explicit_research_always_routes_even_when_classifier_is_unclear():
    decision = score_research_need(
        "Nghiên cứu kỹ và kiểm chứng vụ này giúp tôi",
        intent="unclear",
        meaning_missing=True,
    )
    assert decision.should_delegate is True
    assert decision.reason == "explicit_research_cue"


def test_complex_world_question_routes_without_deep_research_stack():
    decision = score_research_need(
        "So sánh chi tiết hai hướng, kiểm chứng bằng nguồn mới nhất rồi đánh giá rủi ro",
        intent="world_knowledge",
    )
    assert decision.should_delegate is True


def test_reference_followup_reuses_previous_substantive_topic():
    topic = resolve_research_topic(
        "nghiên cứu sâu phần này đi",
        ["pytest là gì", "Cách sửa lỗi TTS đổi ngôn ngữ giữa hai câu"],
    )
    assert topic == "Cách sửa lỗi TTS đổi ngôn ngữ giữa hai câu"


def test_prompt_is_short_and_tells_tutor_to_search_concisely():
    prompt = build_lightweight_research_prompt(
        "Cách sửa lỗi TTS đổi giọng và đổi ngôn ngữ giữa các câu trong Eris",
        context="Ưu tiên giải pháp ít token",
        max_words=220,
    )
    assert len(prompt) <= 395
    assert "tìm kiếm web nếu cần" in prompt
    assert "tối đa 220 từ" in prompt
    assert "nguồn chính thức" in prompt


def test_research_now_bypasses_rewrite_and_does_not_digest_by_default():
    answer = "Kết luận ngắn. " + "chi tiết " * 180 + "\nNguồn:\n1. Tài liệu chính thức"
    daemon, backend, digest = _daemon(answer=answer, persist=False, max_words=120)

    result = daemon.research_now("Kiểm chứng lỗi TTS", context="Eris")

    assert result
    assert len(result.split()) <= 130  # có vài từ marker rút gọn + nguồn
    assert digest.calls == 0
    assert len(backend.questions) == 1
    assert "tìm kiếm web nếu cần" in backend.questions[0].text
    assert len(backend.questions[0].text) <= 400


def test_research_persist_is_opt_in_only():
    answer = "Kết luận có nguồn chính thức. Nguồn: https://godotengine.org/releases"
    daemon, backend, digest = _daemon(answer=answer, persist=True)
    assert daemon.research_now("Kiểm chứng điều này")
    assert digest.calls == 1


def test_answer_compaction_keeps_source_tail_when_present():
    text = " ".join(f"w{i}" for i in range(500)) + "\nNguồn:\nhttps://example.test/doc"
    compacted = compact_research_answer(text, max_words=140)
    assert "Đã rút gọn" in compacted
    assert "example.test" in compacted


def test_coordinator_routes_explicit_followup_to_previous_topic_only_once():
    from types import SimpleNamespace
    from runtime.coordinator import RuntimeCoordinator

    class _Probe:
        _maybe_tutor_on_unclear_user = RuntimeCoordinator._maybe_tutor_on_unclear_user
        _resolve_tutor_research_topic = RuntimeCoordinator._resolve_tutor_research_topic
        _is_tutor_delegation_only = RuntimeCoordinator._is_tutor_delegation_only
        _normalize_marker_text = RuntimeCoordinator._normalize_marker_text

        def __init__(self):
            self.tutor_daemon = object()
            self.request_tutor_answer = lambda *a, **k: ""
            self.last_user_intent = "unclear"
            self.last_user_text_for_semantics = "Cách sửa lỗi TTS đổi ngôn ngữ giữa hai câu"
            self.calls = []

        def _ensure_session_turn_ledger(self):
            return SimpleNamespace(user_turns=lambda: [])

        def _research_can_start(self):
            return True

        def _fire_research_followup(self, topic, *, context=""):
            self.calls.append((topic, context))

    owner = _Probe()
    frame = SimpleNamespace(meaning_layer=SimpleNamespace(meaning="follow-up research"))
    owner._maybe_tutor_on_unclear_user("nghiên cứu sâu phần này đi", frame)

    assert owner._research_pending is True
    assert owner._research_topic == "Cách sửa lỗi TTS đổi ngôn ngữ giữa hai câu"
    assert len(owner.calls) == 1
    assert owner.calls[0][0] == owner._research_topic


def test_coordinator_does_not_route_trivial_world_knowledge_to_tutor():
    from types import SimpleNamespace
    from runtime.coordinator import RuntimeCoordinator

    class _Probe:
        _maybe_tutor_on_unclear_user = RuntimeCoordinator._maybe_tutor_on_unclear_user
        _resolve_tutor_research_topic = RuntimeCoordinator._resolve_tutor_research_topic
        _is_tutor_delegation_only = RuntimeCoordinator._is_tutor_delegation_only
        _normalize_marker_text = RuntimeCoordinator._normalize_marker_text

        def __init__(self):
            self.tutor_daemon = object()
            self.request_tutor_answer = lambda *a, **k: ""
            self.last_user_intent = "world_knowledge"
            self.last_user_text_for_semantics = ""
            self.calls = []

        def _ensure_session_turn_ledger(self):
            return SimpleNamespace(user_turns=lambda: [])

        def _research_can_start(self):
            return True

        def _fire_research_followup(self, topic, *, context=""):
            self.calls.append((topic, context))

        def _fire_tutor_lookup(self, topic, *, context=""):
            self.calls.append(("lookup", topic))

    owner = _Probe()
    frame = SimpleNamespace(meaning_layer=SimpleNamespace(meaning="ask definition"))
    owner._maybe_tutor_on_unclear_user("Pytest là gì?", frame)

    assert owner._research_pending is False
    assert owner.calls == []


def test_relay_prompt_addresses_gemini_and_stays_under_contract():
    from cortex.tutor.research_relay import build_gemini_research_prompt

    prompt = build_gemini_research_prompt(
        "cách fix elegant lỗi Eris hỏi sai follow-up",
        context="không dùng Deep Research API",
        max_words=220,
    )
    assert prompt.startswith("Gemini,")
    assert "tìm kiếm web nếu cần" in prompt
    assert "nguồn chính thức" in prompt
    assert len(prompt) <= 395


def test_relay_analyzer_marks_missing_sources_as_low_confidence():
    from cortex.tutor.research_relay import analyze_tutor_research_answer

    relay = analyze_tutor_research_answer(
        "pytest fixtures",
        "Pytest fixtures dùng để chuẩn bị dữ liệu test và tái sử dụng setup.",
    )
    assert relay.confidence == "low"
    assert "chưa đưa nguồn" in relay.answer_text


def test_relay_analyzer_keeps_sources_and_lets_local_critic_rewrite():
    from cortex.tutor.research_relay import analyze_tutor_research_answer

    def critic(prompt: str) -> str:
        assert "Tutor/Gemini" in prompt
        return "Fixtures trong pytest là cơ chế setup/tái sử dụng dữ liệu test; kết luận này bám tài liệu Tutor đưa."

    relay = analyze_tutor_research_answer(
        "pytest fixtures",
        "Kết luận chắc: Fixtures giúp chia sẻ setup test.\nNguồn: https://docs.pytest.org/en/stable/how-to/fixtures.html",
        critic_fn=critic,
    )
    assert relay.confidence in {"medium", "high"}
    assert "Fixtures trong pytest" in relay.answer_text
    assert "docs.pytest.org" in relay.answer_text


def test_explicit_normal_search_routes_quick_search_not_deep_research():
    from runtime.tutor_research_policy import score_tutor_delegation

    decision = score_tutor_delegation("search web giá vàng hôm nay giúp tôi", intent="world_knowledge")
    assert decision.should_delegate is True
    assert decision.mode == "quick_search"
    assert decision.reason == "explicit_search_cue"


def test_freshness_question_routes_quick_search_even_without_search_word():
    from runtime.tutor_research_policy import score_tutor_delegation

    decision = score_tutor_delegation("Giá vàng hôm nay bao nhiêu?", intent="world_knowledge")
    assert decision.should_delegate is True
    assert decision.mode == "quick_search"
    assert decision.reason == "freshness_web_needed"


def test_common_knowledge_stays_on_main_brain_not_tutor():
    from runtime.tutor_research_policy import score_tutor_delegation

    decision = score_tutor_delegation("Newton là ai?", intent="world_knowledge")
    assert decision.should_delegate is False
    assert decision.mode == "none"


def test_search_prompt_is_short_and_not_deep_research():
    from cortex.tutor.research_relay import build_gemini_search_prompt

    prompt = build_gemini_search_prompt("giá vàng hôm nay", context="search bình thường", max_words=150)
    assert prompt.startswith("Gemini,")
    assert "search web nhanh" in prompt
    assert "tối đa 150 từ" in prompt
    assert "nghiên cứu sâu" not in prompt.lower()
    assert len(prompt) <= 395


def test_search_now_uses_quick_search_prompt_and_does_not_digest_by_default():
    answer = "Giá hiện tại cần xem theo nguồn cập nhật.\nNguồn: https://example.test/gold"
    daemon, backend, digest = _daemon(answer=answer, persist=False, max_words=180)

    result = daemon.search_now("giá vàng hôm nay", context="search bình thường")

    assert result
    assert digest.calls == 0
    assert len(backend.questions) == 1
    assert "search web nhanh" in backend.questions[0].text
    assert "example.test" in result


def test_coordinator_routes_explicit_normal_search_with_quick_mode():
    from types import SimpleNamespace
    from runtime.coordinator import RuntimeCoordinator

    class _Probe:
        _maybe_tutor_on_unclear_user = RuntimeCoordinator._maybe_tutor_on_unclear_user
        _resolve_tutor_research_topic = RuntimeCoordinator._resolve_tutor_research_topic
        _is_tutor_delegation_only = RuntimeCoordinator._is_tutor_delegation_only
        _normalize_marker_text = RuntimeCoordinator._normalize_marker_text

        def __init__(self):
            self.tutor_daemon = object()
            self.request_tutor_answer = lambda *a, **k: ""
            self.last_user_intent = "world_knowledge"
            self.last_user_text_for_semantics = ""
            self.calls = []

        def _ensure_session_turn_ledger(self):
            return SimpleNamespace(user_turns=lambda: [])

        def _research_can_start(self):
            return True

        def _fire_research_followup(self, topic, *, context="", mode="research"):
            self.calls.append((topic, context, mode))

    owner = _Probe()
    frame = SimpleNamespace(meaning_layer=SimpleNamespace(meaning="fresh web question"))
    owner._maybe_tutor_on_unclear_user("tra cứu giá vàng hôm nay giúp tôi", frame)

    assert owner._research_pending is True
    assert len(owner.calls) == 1
    assert owner.calls[0][2] == "quick_search"
    assert "Search nhanh" in owner.calls[0][1]


def test_oblique_status_question_routes_quick_search_without_search_word():
    from runtime.tutor_research_policy import score_tutor_delegation

    decision = score_tutor_delegation("Workspace này bị ban à hay chỉ lỗi giao diện?", intent="unclear")
    assert decision.should_delegate is True
    assert decision.mode == "quick_search"
    assert decision.reason == "implicit_verification_risk"


def test_oblique_api_policy_question_routes_quick_search():
    from runtime.tutor_research_policy import score_tutor_delegation

    decision = score_tutor_delegation("Nghe nói Gemini đổi policy API rồi đúng không?", intent="world_knowledge")
    assert decision.should_delegate is True
    assert decision.mode == "quick_search"
    assert decision.reason == "implicit_verification_risk"


def test_stable_trick_question_does_not_auto_search_without_sensitive_domain():
    from runtime.tutor_research_policy import score_tutor_delegation

    decision = score_tutor_delegation("Có phải nước sôi ở 100 độ C không?", intent="world_knowledge")
    assert decision.should_delegate is False


def test_self_search_bridge_detects_assistant_promise_and_selects_quick_search():
    from runtime.tutor_self_search_bridge import detect_self_search_request

    decision = detect_self_search_request(
        "Workspace này bị ban à hay lỗi giao diện?",
        "Đợi em kiểm tra web chút rồi em nhắn lại.",
    )

    assert decision.should_start is True
    assert decision.mode == "quick_search"
    assert decision.reason == "assistant_self_search_promise"


def test_self_search_bridge_rejects_explicit_no_search():
    from runtime.tutor_self_search_bridge import detect_self_search_request

    decision = detect_self_search_request(
        "Có cần web không?",
        "Không cần search web, cái này là kiến thức ổn định.",
    )

    assert decision.should_start is False
    assert decision.reason == "explicit_no_search"


def test_coordinator_turns_self_declared_search_into_background_followup():
    from types import SimpleNamespace
    from domain import Decision
    from runtime.coordinator import RuntimeCoordinator

    class _Probe:
        _maybe_start_self_declared_tutor_search = RuntimeCoordinator._maybe_start_self_declared_tutor_search
        _resolve_tutor_research_topic = RuntimeCoordinator._resolve_tutor_research_topic
        _is_tutor_delegation_only = RuntimeCoordinator._is_tutor_delegation_only
        _normalize_marker_text = RuntimeCoordinator._normalize_marker_text
        _join_debug_trace = RuntimeCoordinator._join_debug_trace

        def __init__(self):
            self._research_pending = False
            self._research_in_flight = False
            self._research_topic = ""
            self.request_tutor_answer = lambda *a, **k: ""
            self.last_user_text_for_semantics = ""
            self.calls = []
            self.logger = SimpleNamespace(warning=lambda *a, **k: None)

        def _ensure_session_turn_ledger(self):
            return SimpleNamespace(user_turns=lambda: [])

        def _research_can_start(self):
            return True

        def _fire_research_followup(self, topic, *, context="", mode="research"):
            self.calls.append((topic, context, mode))

    owner = _Probe()
    raw = Decision(
        text="Đợi em kiểm tra web chút rồi em nhắn lại.",
        animation="stand",
        intent="world_knowledge",
        action="answer",
        confidence=0.86,
    )

    out = owner._maybe_start_self_declared_tutor_search(
        raw,
        user_text="Workspace này bị ban à hay chỉ lỗi giao diện?",
        frame=SimpleNamespace(debug_notes=[]),
    )

    assert owner._research_pending is True
    assert owner._research_topic == "Workspace này bị ban à hay chỉ lỗi giao diện?"
    assert owner.calls and owner.calls[0][2] == "quick_search"
    assert out.action == "tutor_self_search_wait"
    assert "Đợi tôi search nhanh" in out.text
    assert "tutor_self_declared_wait" in out.reasoning_tags


def test_coordinator_self_declared_search_does_not_duplicate_existing_worker():
    from types import SimpleNamespace
    from domain import Decision
    from runtime.coordinator import RuntimeCoordinator

    class _Probe:
        _maybe_start_self_declared_tutor_search = RuntimeCoordinator._maybe_start_self_declared_tutor_search
        _resolve_tutor_research_topic = RuntimeCoordinator._resolve_tutor_research_topic
        _is_tutor_delegation_only = RuntimeCoordinator._is_tutor_delegation_only
        _normalize_marker_text = RuntimeCoordinator._normalize_marker_text
        _join_debug_trace = RuntimeCoordinator._join_debug_trace

        def __init__(self):
            self._research_pending = False
            self._research_in_flight = True
            self.request_tutor_answer = lambda *a, **k: ""
            self.calls = []
            self.logger = SimpleNamespace(warning=lambda *a, **k: None)

        def _ensure_session_turn_ledger(self):
            return SimpleNamespace(user_turns=lambda: [])

        def _research_can_start(self):
            return True

        def _fire_research_followup(self, topic, *, context="", mode="research"):
            self.calls.append((topic, context, mode))

    owner = _Probe()
    raw = Decision(
        text="Đợi em kiểm tra web chút rồi em nhắn lại.",
        animation="stand",
        intent="world_knowledge",
        action="answer",
        confidence=0.86,
    )

    out = owner._maybe_start_self_declared_tutor_search(
        raw,
        user_text="Gemini đổi policy API rồi đúng không?",
        frame=None,
    )

    assert out is raw
    assert owner.calls == []


def test_secret_scrubber_catches_bare_provider_keys_and_labeled_tokens():
    from cortex.tutor.secret_scrubber import contains_secret_like, scrub_secrets

    raw = (
        "OpenAI sk-proj-abcdefghijklmnopqrstuvwxyz1234567890 "
        "Google AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ123456 "
        "GitHub ghp_abcdefghijklmnopqrstuvwxyz1234567890 "
        "Codex agt_codex_kqOXnEHZd4bPNaBtx7evUY29223GI3BS "
        "token=abc.def.ghi"
    )
    clean = scrub_secrets(raw)

    assert "sk-proj" not in clean
    assert "AIza" not in clean
    assert "ghp_" not in clean
    assert "agt_codex_" not in clean
    assert "abc.def.ghi" not in clean
    assert contains_secret_like(clean) is False


def test_search_prompt_scrubs_secrets_before_tutor():
    from cortex.tutor.research_relay import build_gemini_search_prompt

    prompt = build_gemini_search_prompt(
        "check key sk-proj-abcdefghijklmnopqrstuvwxyz1234567890 còn sống không",
        context="token=supersecretvalue",
    )

    assert "sk-proj" not in prompt
    assert "supersecretvalue" not in prompt
    assert "[redacted-secret]" in prompt


def test_research_relay_builds_evidence_bundle_and_verification():
    from cortex.tutor.research_relay import analyze_tutor_research_answer

    raw = (
        "Kết luận: Godot 4.6 là bản mới trong nhánh 4.x theo tài liệu chính thức. "
        "Điểm chưa chắc: lịch release phụ thuộc kênh tải.\n"
        "Nguồn: https://godotengine.org/releases"
    )
    relay = analyze_tutor_research_answer("Godot 4.6 mới chưa?", raw, mode="quick_search")

    assert relay.evidence_bundle is not None
    bundle = relay.evidence_bundle.to_dict()
    assert bundle["sources"]
    assert bundle["claims"]
    assert bundle["verification"]["overall_status"] in {"passed", "passed_with_warnings"}
    assert "godotengine.org" in relay.answer_text


def test_search_now_exposes_research_thread_artifact_on_daemon():
    answer = "Kết luận có thể kiểm qua nguồn.\nNguồn: https://ai.google.dev/gemini-api/docs/rate-limits"
    daemon, backend, digest = _daemon(answer=answer, persist=False, max_words=180)

    result = daemon.search_now("Gemini rate limit hiện tại", context="quick verify")

    assert result
    assert daemon.last_research_bundle.get("bundle_id")
    assert daemon.last_research_thread.get("provider_path") == "tutor_gemini_web_quick_search"
    assert daemon.last_research_thread.get("evidence_bundle_id") == daemon.last_research_bundle.get("bundle_id")


def test_verification_handlers_report_source_policy_and_anchor_consistency():
    from cortex.tutor.research_evidence import build_evidence_bundle

    raw = (
        "Godot 4.6 release notes nói bản này thuộc nhánh 4.x và có thay đổi engine. "
        "Nguồn: https://godotengine.org/releases/4.6"
    )
    bundle = build_evidence_bundle(query="Godot 4.6 release notes", raw_answer=raw, mode="quick_search")
    data = bundle.to_dict()
    handlers = data["verification"]["handler_results"]

    assert any(item["name"] == "verify_source_allowlist" for item in handlers)
    assert any(item["name"] == "verify_anchor_consistency" for item in handlers)
    assert data["verification"]["overall_status"] in {"passed", "passed_with_warnings"}
    assert data["verification"]["surface_caution"] in {True, False}


def test_research_metrics_and_thread_record_are_exposed():
    answer = (
        "Kết luận: Gemini API có rate limit theo tier và có thể trả RESOURCE_EXHAUSTED. "
        "Nguồn: https://ai.google.dev/gemini-api/docs/rate-limits"
    )
    daemon, backend, digest = _daemon(answer=answer, persist=False, max_words=180)

    result = daemon.search_now("Gemini API rate limit mới nhất", context="quick verify")

    assert result
    assert daemon.last_research_metrics.get("source_count", 0) >= 1
    assert "verification_status" in daemon.last_research_metrics
    assert "open_questions" in daemon.last_research_thread
    assert "source_policy_pass" in daemon.last_research_thread


def test_tutor_research_status_events_include_verification_payload():
    from runtime.tutor_daemon import TutorStageEmitter

    class _Transport:
        def __init__(self):
            self.payloads = []

        def send_json(self, payload):
            self.payloads.append(payload)

    answer = "Kết luận có nguồn. Nguồn: https://godotengine.org/releases"
    daemon, backend, digest = _daemon(answer=answer, persist=False, max_words=120)
    transport = _Transport()
    daemon.emitter = TutorStageEmitter(transport=transport, logger=None)

    assert daemon.search_now("Godot release mới nhất")
    research_events = [payload for payload in transport.payloads if payload.get("research")]

    assert [payload["research"]["stage"] for payload in research_events][:2] == ["queued", "asking_tutor"]
    assert any(payload["research"]["stage"] == "verified" for payload in research_events)
    verified = [payload for payload in research_events if payload["research"]["stage"] == "verified"][-1]
    assert verified["research"]["verification"].get("overall_status") in {"passed", "passed_with_warnings", "failed"}


def test_gemma_critic_prompt_is_json_contract_and_does_not_ask_to_search():
    from cortex.tutor.gemma_research_critic import build_gemma_critic_prompt

    prompt = build_gemma_critic_prompt(
        "kiểm chứng model mới",
        "Kết luận chắc: A. Nguồn: https://example.com/doc",
        max_chars=900,
    )
    assert len(prompt) <= 900
    assert "KHÔNG search web" in prompt
    assert '"supported_points"' in prompt
    assert "Tutor/Gemini trả lời" in prompt


def test_gemma_critic_parser_accepts_fenced_json():
    from cortex.tutor.gemma_research_critic import parse_gemma_critic_response

    critique = parse_gemma_critic_response(
        '''```json
        {
          "usable_summary": "A dùng được nhưng cần nguồn.",
          "supported_points": ["A có nguồn"],
          "weak_points": ["B thiếu nguồn"],
          "contradictions": ["C mâu thuẫn với D"],
          "sources_seen": ["https://example.com/a"],
          "confidence": "medium",
          "caution": "Không chốt mạnh"
        }
        ```'''
    )
    assert critique is not None
    assert critique.usable_summary.startswith("A dùng")
    assert critique.confidence == "medium"
    assert critique.contradictions
    assert critique.sources_seen == ["https://example.com/a"]


def test_relay_uses_structured_gemma_critic_and_marks_conflict():
    from cortex.tutor.research_relay import analyze_tutor_research_answer

    def critic(prompt: str) -> str:
        assert '"contradictions"' in prompt
        return '''{
          "usable_summary": "Theo nguồn Tutor đưa, chính sách A đang áp dụng nhưng cần dè dặt.",
          "supported_points": ["Chính sách A đang áp dụng"],
          "weak_points": ["Chưa thấy ngày cập nhật rõ"],
          "contradictions": ["Một đoạn nói áp dụng, đoạn khác nói chưa triển khai"],
          "sources_seen": ["https://example.com/policy"],
          "confidence": "medium",
          "caution": "Có dấu hiệu mâu thuẫn"
        }'''

    relay = analyze_tutor_research_answer(
        "policy A hiện tại",
        "Kết luận: A đang áp dụng. Tuy nhiên có nguồn khác nói chưa triển khai. Nguồn: https://example.com/policy",
        critic_fn=critic,
    )
    assert "Theo nguồn Tutor đưa" in relay.answer_text
    assert relay.contradictions
    assert "Mâu thuẫn" in relay.answer_text
    assert relay.confidence in {"low", "medium"}
    assert relay.evidence_bundle is not None
    assert relay.evidence_bundle.verification.contested_claim_count >= 1


def test_gemma_critic_heuristic_fallback_flags_missing_sources():
    from cortex.tutor.gemma_research_critic import run_gemma_research_critic

    critique = run_gemma_research_critic(
        "thông tin mới",
        "Có thể đã đổi chính sách, nhưng chưa xác minh được nguồn rõ ràng.",
        critic_fn=None,
    )
    assert critique.confidence == "low"
    assert critique.weak_points
    assert "nguồn" in critique.caution.lower()
