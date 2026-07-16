# -*- coding: utf-8 -*-
"""Pragmatic/repair tests lấy thẳng các lỗi trong log thực chiến."""

from __future__ import annotations

from runtime.response_contract import build_response_contract
from runtime.turn_frame import build_turn_frame


def test_arithmetic_wordplay_beats_profanity_boundary() -> None:
    frame = build_turn_frame(user_text="1 mẹ mày béo + 1 mẹ mày béo ra gì")
    contract = build_response_contract(frame)

    assert frame.has_relation("ARITHMETIC_WORDPLAY")
    assert not frame.has_relation("PROVOCATION")
    assert contract.fallback_text.startswith("Ra 2.")
    assert any(item.kind == "ANSWER_ARITHMETIC_WORDPLAY_FIRST" for item in contract.obligations)


def test_orc_is_confirmed_as_possible_ocr_before_memory_commit() -> None:
    frame = build_turn_frame(user_text="dùng orc đi eris chan")
    contract = build_response_contract(frame)

    assert frame.has_relation("AMBIGUOUS_TECH_TERM")
    assert contract.fallback_text == "OCR ấy à? Nếu đúng thì tôi chuyển sang dùng OCR."
    assert any(item.kind == "CONFIRM_AMBIGUOUS_TECH_TERM" for item in contract.obligations)


def test_soft_correction_uses_semantic_misread_not_fake_encoding_story() -> None:
    frame = build_turn_frame(
        user_text="ơ. tôi hỏi ra gì mà",
        previous_user_text="1 mẹ mày béo + 1 mẹ mày béo ra gì",
        previous_assistant_text="Câu đó cũ rồi; đổi bài đi.",
    )
    contract = build_response_contract(frame)
    prompt = contract.to_prompt_block().lower()

    assert frame.repair_reason == "semantic_misread"
    assert "lỗi mã hóa" in prompt
    assert "do not say" in prompt
    assert "frame" in " ".join(contract.prohibited_markers)


def test_runtime_capability_inquiry_is_detected() -> None:
    frame = build_turn_frame(user_text="Eris có đọc được telemetry và thấy Meet không?")
    assert frame.has_relation("CAPABILITY_INQUIRY")
