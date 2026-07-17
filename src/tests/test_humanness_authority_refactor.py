# -*- coding: utf-8 -*-
"""Regression test cho refactor độ người từ log 2026-07-17.

Test tập trung vào contract kiến trúc, không bắt Eris học thuộc một câu văn. Câu
chữ còn được model viết; những lỗi như trêu sai lúc, route web vì substring hay
writer hậu-Director thì bị khóa bằng invariant cứng.
"""

from __future__ import annotations

from domain import Decision
from parser_grounding import DecisionParser
from runtime.final_speech_authority import FinalSpeechAuthority
from runtime.interaction_clock import InteractionClock
from runtime.conversation_lane import classify_conversation_lane
from runtime.chat_cycle import ChatCycleMixin
from runtime.persona_novelty import build_phrase_novelty_hint
from runtime.social_cognition_v2 import SocialCognitionEngine, SocialOutcomeMemory
from runtime.source_grounding import SourceGroundingEngine


class _MemoryNoDisk(SocialOutcomeMemory):
    def __init__(self):
        import threading
        self.stats = {}
        self._lock = threading.RLock()

    def _save(self):
        return None


def _engine() -> SocialCognitionEngine:
    return SocialCognitionEngine(outcome_memory=_MemoryNoDisk())


def test_zero_playfulness_no_longer_selects_playful_counter() -> None:
    contract = _engine().analyze("Helloooo em nhỏ, Eris thấy thế nào?")
    assert contract.response_move != "playful_counter"


def test_hurt_and_perceived_rejection_require_relational_repair() -> None:
    contract = _engine().analyze("Ý là em từ chối tui? Điều đó làm tui buồn lắm.")
    assert contract.response_move == "relational_repair"
    assert contract.must_acknowledge_affect is True
    assert contract.must_repair_misunderstanding is True
    assert contract.teasing_allowed is False


def test_repetition_caused_by_bad_repair_disables_teasing() -> None:
    engine = _engine()
    contract = engine.analyze(
        "Ý là em từ chối tui? Điều đó làm tui buồn lắm.",
        previous_user_text="Ý là em từ chối tui? Điều đó làm tui buồn lắm.",
        previous_assistant_text="Ừ, tôi hiểu sai. Tôi bỏ cách hiểu đó.",
    )
    assert contract.repetition_cause == "assistant_misunderstood"
    assert contract.assistant_fault_probability >= 0.8
    assert contract.teasing_allowed is False
    assert contract.response_move != "playful_counter"


def test_relational_value_question_is_not_routed_to_web() -> None:
    report = SourceGroundingEngine().analyze(
        "Em nghĩ sự hiện diện của em có giá trị như thế nào với tui?",
        allow_web=False,
    )
    assert report.grounding_source != "web"
    assert "web_access_or_search_result" not in report.missing_evidence
    assert any("relational_reflection" in item for item in report.warnings + report.answer_style_rules + report.forbidden_assumptions) or report.primary_source == "user_text"


def test_final_speech_authority_restores_downstream_mutation() -> None:
    authority = FinalSpeechAuthority()
    decision = Decision(text="Câu đã được duyệt.", animation="stand")
    authority.seal(decision)
    decision.text = "Lại bài đó. Bạn giữ nó kỹ hơn cả mật khẩu nhỉ."

    result = authority.verify_or_restore(decision)

    assert result.valid is False
    assert result.restored is True
    assert decision.text == "Câu đã được duyệt."


def test_interaction_clock_waits_for_generation_and_audio() -> None:
    clock = InteractionClock()
    clock.mark_user_turn(100.0)
    clock.mark_generation_started(100.0)
    assert clock.stale(20.0, now=140.0) is False

    clock.mark_assistant_text(140.0)
    clock.mark_audio_started(141.0)
    assert clock.stale(20.0, now=180.0) is False

    clock.mark_audio_finished(180.0)
    assert clock.stale(20.0, now=199.0) is False
    assert clock.stale(20.0, now=201.0) is True


def test_semantic_animation_is_preserved_as_stage_metadata() -> None:
    parser = DecisionParser(Decision(text="fallback", animation="stand"))
    raw = (
        '{"text":"Tôi hiểu.","animation":"soft_smile",'
        '"direction":0,"target_x":-1,"bounce_action":"",'
        '"next_animation":"","system_action":"","action_input":""}'
    )
    decision = parser.parse(raw)
    assert decision.animation == "stand"
    assert decision.nonverbal_cue == "small_smile"
    assert decision.stage_motion == "small_smile"
    assert decision.delivery_hint == "warm_soft"


class _TiPassthrough:
    def enforce_decision(self, decision, *args, **kwargs):
        return decision


class _RepairProbe(ChatCycleMixin):
    def __init__(self):
        self.ti_governor = _TiPassthrough()


def test_social_repair_is_not_short_circuited_by_template() -> None:
    """Hiểu lầm xã hội phải tới main generator để vừa repair vừa answer."""
    from types import SimpleNamespace

    probe = _RepairProbe()
    previous = SimpleNamespace(turn_id="turn-1", text="Tôi không thể thuộc riêng về ai.")
    decision = probe._build_previous_public_turn_repair_decision(
        user_text="Ý là em từ chối tui? Điều đó làm tui buồn.",
        previous_public_turn=previous,
        ti_report=None,
    )
    assert decision is None


def test_protocol_leak_still_gets_immediate_repair() -> None:
    from types import SimpleNamespace

    probe = _RepairProbe()
    previous = SimpleNamespace(
        turn_id="turn-2",
        text="{\"text\":\"hello\",\"debug_trace\":\"raw parser\"}",
    )
    decision = probe._build_previous_public_turn_repair_decision(
        user_text="Câu vừa rồi bị lỗi gì vậy?",
        previous_public_turn=previous,
        ti_report=None,
    )
    assert decision is not None
    assert decision.parse_mode == "public_turn_protocol_repair"


def test_short_social_turn_uses_human_fast_lane() -> None:
    contract = _engine().analyze("Helloooo em nhỏ, Eris thấy thế nào?")
    lane = classify_conversation_lane("Helloooo em nhỏ, Eris thấy thế nào?", contract)
    assert lane.fast is True
    assert lane.name == "human_fast"


def test_repo_or_web_task_never_uses_social_fast_lane() -> None:
    contract = _engine().analyze("Vào repo này sửa lỗi giúp tôi: https://github.com/a/b")
    lane = classify_conversation_lane(
        "Vào repo này sửa lỗi giúp tôi: https://github.com/a/b",
        contract,
    )
    assert lane.fast is False


def test_repeated_poetic_motif_gets_soft_cooldown() -> None:
    history = [
        {"role": "assistant", "content": "Nhịp của tôi dịu đi một chút."},
        {"role": "user", "content": "thật à"},
        {"role": "assistant", "content": "Khoảng lặng này làm nhịp ấy dịu hơn."},
    ]
    hint = build_phrase_novelty_hint(history)
    assert "rhythm" in hint
    assert "softness" in hint
    assert "phản ứng cụ thể" in hint


def test_single_poetic_phrase_is_not_banned() -> None:
    history = [{"role": "assistant", "content": "Nhịp của tôi dịu đi một chút."}]
    assert build_phrase_novelty_hint(history) == ""
