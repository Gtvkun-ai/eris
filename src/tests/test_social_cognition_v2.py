from __future__ import annotations

from dataclasses import dataclass

from domain import Decision
from runtime.social_act import ChatAct, classify_chat_act_with_confidence
from runtime.social_cognition_v2 import SocialCognitionEngine, SocialHypothesis, SocialOutcomeMemory


class _MemoryNoDisk(SocialOutcomeMemory):
    def __init__(self):
        self.stats = {}
        import threading
        self._lock = threading.RLock()

    def _save(self):
        return None


def _engine() -> SocialCognitionEngine:
    return SocialCognitionEngine(outcome_memory=_MemoryNoDisk())


def test_specific_repair_keeps_failed_claim_and_never_surfaces_frame():
    engine = _engine()
    engine.record_public_response("Tôi nghĩ bạn đang gây chuyện rồi.", move="natural_reply")

    contract = engine.analyze(
        "không phải em gây chuyện hả",
        previous_assistant_text="Tôi nghĩ bạn đang gây chuyện rồi.",
    )
    assert contract.response_move == "specific_repair"
    assert "gây chuyện" in contract.failed_claim_text

    decision = Decision(text="Ừ, tôi hiểu sai. Tôi bỏ frame đó.", animation="stand", should_speak=True)
    fixed = engine.apply_surface_policy(decision, user_text="em hiểu sai cái gì nè")
    assert "frame" not in fixed.text.lower()
    assert "gây chuyện" in fixed.text


def test_refer_back_question_keeps_same_challenged_claim():
    engine = _engine()
    engine.record_public_response("Bạn đang cố gây chuyện với tôi.")
    first = engine.analyze("không phải em gây chuyện hả")
    # Giả lập câu repair đã surface; ledger vẫn phải giữ claim gốc cho follow-up.
    engine.record_public_response(engine.deterministic_repair_text(first), move="specific_repair")
    second = engine.analyze("em hiểu sai cái gì nè")
    third = engine.analyze("là phần nào cơ")
    assert first.failed_claim_id
    assert second.failed_claim_id == first.failed_claim_id
    assert third.failed_claim_id == first.failed_claim_id


def test_profanity_math_is_question_not_hard_insult():
    act, confidence = classify_chat_act_with_confidence("1 mẹ mày béo + 1 mẹ mày béo ra gì")
    assert act == ChatAct.DIRECT_QUESTION
    assert confidence >= 0.7

    engine = _engine()
    contract = engine.analyze("1 mẹ mày béo + 1 mẹ mày béo ra gì")
    intents = {item.intent for item in contract.hypotheses}
    assert "wordplay_math_question" in intents
    assert contract.response_move == "answer_with_tease"
    assert contract.must_answer_literal is True


def test_counting_1_to_100_has_agency_progression():
    engine = _engine()
    one = engine.analyze("đếm từ 1 đến 100 đi Eris")
    two = engine.analyze("đếm từ 1 đến 100 đi Eris")
    three = engine.analyze("đếm từ 1 đến 100 đi Eris")
    assert one.response_move == "playful_resistance"
    assert two.response_move == "partial_compliance"
    assert three.response_move == "comply_with_attitude"


def test_counting_for_tts_test_complies_immediately():
    engine = _engine()
    contract = engine.analyze("đếm từ 1 đến 100 để test TTS")
    assert contract.response_move == "comply_with_attitude"
    assert contract.task.technical_test_value == 1.0


def test_light_correction_does_not_create_full_anger():
    engine = _engine()
    engine.record_public_response("Bạn đang né chuyện đó.")
    contract = engine.analyze("không phải, ý tôi là chuyện khác")
    assert contract.social_state["anger_level"] == 0
    assert contract.social_state["rupture"] < 0.2


def test_too_cold_feedback_increases_warmth_and_move_memory():
    engine = _engine()
    engine.record_public_response("Đỡ phí nhịp của cả hai.", move="dry_observation")
    before = engine.state.warmth
    engine.analyze("nói lạnh quá em")
    assert engine.state.warmth > before
    assert engine.outcome_memory.stats["dry_observation"].too_cold == 1


def test_post_director_empty_answer_is_repaired_for_relational_request():
    engine = _engine()
    contract = engine.analyze("nói gần gũi là nói như nào nè")
    assert contract.response_move == "restrained_warmth"
    decision = Decision(text="", animation="stand", should_speak=False)
    fixed = engine.apply_surface_policy(decision, user_text="nói gần gũi là nói như nào nè", after_director=True)
    assert fixed.should_speak is True
    assert fixed.text


def test_low_irritation_does_not_allow_extreme_abuse():
    engine = _engine()
    contract = engine.analyze("mẹ mày béo")
    assert contract.social_state["anger_level"] <= 1
    review = engine.review_text("Câm mồm đi, đồ rác rưởi.", contract=contract)
    assert review.pass_check is False
    assert "anger_overreaction" in review.issues

class _ParserThatForgetsCorrection:
    def refine_hypotheses(self, **kwargs):
        return (SocialHypothesis("normal_chat", 1.0, source="bad_parser"),)

    def deliberate(self, **kwargs):
        return {}


def test_small_parser_cannot_erase_deterministic_correction_anchor():
    engine = SocialCognitionEngine(
        outcome_memory=_MemoryNoDisk(),
        model_router=_ParserThatForgetsCorrection(),
    )
    engine.record_public_response("Tôi nghĩ bạn đang gây chuyện rồi.")
    contract = engine.analyze("không phải em gây chuyện hả")
    intents = {item.intent for item in contract.hypotheses}
    assert "correction_repair" in intents
    assert contract.response_move == "specific_repair"
    assert contract.failed_claim_text
