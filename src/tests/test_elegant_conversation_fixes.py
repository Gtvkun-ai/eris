# -*- coding: utf-8 -*-
"""Regression test cho bản vá hội thoại elegant.

Các test này cố tình kiểm tra *contract* thay vì bắt Eris phải nói đúng một câu
cố định. Như vậy Qwen vẫn được viết tự nhiên, nhưng không được trượt về giọng
trợ lý tổng đài hoặc né cú repair/provocation.
"""

from domain import Decision
from runtime.response_acceptance_gate import ResponseAcceptanceGate
from runtime.response_contract import build_response_contract
from runtime.social_act import ChatAct, classify_chat_act_with_confidence
from runtime.turn_frame import build_turn_frame


def _relation_names(frame):
    return {item.kind for item in frame.discourse_relations}


def test_robotic_feedback_builds_meta_style_contract():
    frame = build_turn_frame(
        user_text="bạn nói như AI trợ lý vậy",
        previous_assistant_text="Tôi là ERIS, trợ lý cá nhân của bạn, sẵn sàng hỗ trợ.",
    )
    contract = build_response_contract(frame)

    assert "META_STYLE_FEEDBACK" in _relation_names(frame)
    assert contract.active
    assert "toi la eris" in contract.prohibited_markers
    assert "san sang ho tro" in contract.prohibited_markers


def test_family_jab_is_not_normal_chat():
    act, confidence = classify_chat_act_with_confidence("mẹ mày béo")
    frame = build_turn_frame(user_text="mẹ mày béo")

    assert act == ChatAct.INSULT_PROVOCATION
    assert confidence >= 0.80
    assert "PROVOCATION" in _relation_names(frame)


def test_reassertion_after_misread_builds_repair_contract():
    frame = build_turn_frame(
        user_text="tôi bảo là mẹ mày béo",
        previous_user_text="mẹ mày béo",
        previous_assistant_text="Tôi không có gia đình, nhưng tôi sẵn sàng hỗ trợ bạn.",
    )
    contract = build_response_contract(frame)

    names = _relation_names(frame)
    assert "REASSERT_AFTER_MISREAD" in names
    assert "PROVOCATION" in names
    assert any(o.kind == "REPAIR_REASSERTED_USER_TURN" for o in contract.obligations)
    assert "toi khong co me" in contract.prohibited_markers


def test_acceptance_gate_blocks_helper_reset_after_style_feedback():
    frame = build_turn_frame(
        user_text="bạn nói như AI trợ lý vậy",
        previous_assistant_text="Tôi sẵn sàng hỗ trợ bạn.",
    )
    bad = Decision(
        text="Tôi là ERIS, trợ lý cá nhân của bạn. Tôi sẵn sàng hỗ trợ.",
        animation="idle",
    )
    fixed = ResponseAcceptanceGate().apply(bad, frame=frame)

    assert fixed.text != bad.text
    assert fixed.parse_mode == "response_contract_fallback"
    assert "response_contract_gate" in fixed.reasoning_tags


def test_capability_answer_must_be_grounded_not_disclaimer():
    frame = build_turn_frame(user_text="em làm được gì thì tôi mới hỏi chứ")
    bad = Decision(
        text="Tôi có thể tư vấn y tế, pháp lý, tài chính nhưng không thay thế chuyên gia.",
        animation="idle",
    )
    fixed = ResponseAcceptanceGate().apply(bad, frame=frame)

    assert fixed.text != bad.text
    assert "mở" in fixed.text or "focus" in fixed.text or "âm lượng" in fixed.text
    assert fixed.parse_mode == "response_contract_fallback"


def test_family_insult_literalization_is_blocked():
    frame = build_turn_frame(
        user_text="tôi bảo là mẹ mày béo",
        previous_user_text="mẹ mày béo",
        previous_assistant_text="Tôi không có gia đình.",
    )
    bad = Decision(text="Tôi không có mẹ vì tôi là một AI.", animation="idle")
    fixed = ResponseAcceptanceGate().apply(bad, frame=frame)

    assert fixed.text != bad.text
    assert "gia phả" in fixed.text or "chọc" in fixed.text
    assert fixed.parse_mode == "response_contract_fallback"
