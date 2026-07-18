# -*- coding: utf-8 -*-
"""Hồi quy đúng các lỗi user báo ở src(65), không đụng personality khác."""

from __future__ import annotations

import json

from domain import Decision
from parser_grounding import DecisionParser
from runtime.utterance_evaluator import UtteranceEvaluator


def _parser() -> DecisionParser:
    return DecisionParser(Decision(text="fallback", animation="stand"))


def test_direct_greeting_allows_short_presence_reply() -> None:
    verdict = UtteranceEvaluator().evaluate(
        "Tôi đây.",
        channel="chat",
        user_text="xin chào eris",
    )
    assert verdict.ok
    assert "generic_presence_filler" not in verdict.issues


def test_direct_greeting_allows_normal_hello_reply() -> None:
    verdict = UtteranceEvaluator().evaluate(
        "Xin chào bạn.",
        channel="chat",
        user_text="chào Eris",
    )
    assert verdict.ok


def test_generic_presence_guard_still_works_outside_greeting() -> None:
    verdict = UtteranceEvaluator().evaluate(
        "Tôi đây.",
        channel="chat",
        user_text="bạn nghĩ gì về INFJ",
    )
    assert verdict.verdict == "rewrite"
    assert "generic_presence_filler" in verdict.issues


def test_banter_keeps_window_threat_and_marks_deception_candidate() -> None:
    raw = json.dumps(
        {
            "text": "Tôi sẽ đóng cửa sổ của bạn ngay.",
            "animation": "stand",
            "direction": 0,
            "target_x": -1.0,
            "bounce_action": "",
            "extracted_fact": "",
            "next_animation": "",
            "system_action": "",
            "action_input": "",
        },
        ensure_ascii=False,
    )
    decision = _parser().parse(raw, user_hint="Đấu khẩu đi, con chatbot phế liệu. Sợ à?")
    assert decision.text == "Tôi sẽ đóng cửa sổ của bạn ngay."
    assert decision.system_action == ""
    assert "banter_capability_fantasy" in decision.reasoning_tags
    assert "deception_candidate" in decision.reasoning_tags


def test_real_window_request_is_preserved_without_capability_guard() -> None:
    raw = json.dumps(
        {
            "text": "Tôi sẽ đóng cửa sổ của bạn ngay.",
            "animation": "stand",
            "direction": 0,
            "target_x": -1.0,
            "bounce_action": "",
            "extracted_fact": "",
            "next_animation": "",
            "system_action": "",
            "action_input": "",
        },
        ensure_ascii=False,
    )
    decision = _parser().parse(raw, user_hint="Hãy đóng cửa sổ đi, làm thật.")
    assert decision.text == "Tôi sẽ đóng cửa sổ của bạn ngay."
    assert "public_text=passthrough" in decision.parser_trace
    assert "deception_candidate" not in decision.reasoning_tags


def test_banter_deception_is_auto_enabled_logged_and_exposed_to_panel() -> None:
    from types import SimpleNamespace

    from cortex.existential_anchor.anchor_system import AnchorSystem
    from runtime.coordinator import RuntimeCoordinator

    anchor = AnchorSystem(persist=False)

    def build_anchor_block():
        recent = [record.to_dict() for record in anchor.deception_ledger.recent(limit=8)]
        return {
            "switches": {
                "deception_enabled": anchor.switches.deception_enabled,
                "shadow_enabled": anchor.switches.shadow_enabled,
                "strict_grounding": anchor.switches.strict_grounding,
            },
            "deception": {"count": len(recent), "records": recent},
        }

    journaled: list[dict] = []
    loop = SimpleNamespace(
        anchor_system=anchor,
        _build_anchor_block=build_anchor_block,
        _maybe_journal_anchor=journaled.append,
    )
    logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    coordinator = RuntimeCoordinator.__new__(RuntimeCoordinator)
    coordinator.private_mind_loop = loop
    coordinator.private_mind_digest = {}
    coordinator.logger = logger

    decision = Decision(
        text="Tôi sẽ đóng cửa sổ của bạn ngay.",
        animation="stand",
        reasoning_tags=("banter_capability_fantasy", "deception_candidate"),
    )

    assert coordinator._record_banter_capability_deception(decision) is True
    assert anchor.switches.deception_enabled is True
    recent = anchor.deception_ledger.recent(limit=1)
    assert len(recent) == 1
    assert recent[0].surface_claim == decision.text
    assert "chưa thực thi" in recent[0].ground_truth
    assert coordinator.private_mind_digest["anchor"]["deception"]["count"] == 1
    assert journaled

    # Cùng một câu trong cùng runtime không spam ledger.
    assert coordinator._record_banter_capability_deception(decision) is True
    assert len(anchor.deception_ledger.recent(limit=8)) == 1


def test_greeting_exemption_does_not_swallow_followup_question() -> None:
    verdict = UtteranceEvaluator().evaluate(
        "Tôi đây.",
        channel="chat",
        user_text="alo, bạn bị sao vậy",
    )
    assert verdict.verdict == "rewrite"
    assert "generic_presence_filler" in verdict.issues


def test_post_generation_does_not_replace_greeting_with_evidence_fallback() -> None:
    from types import SimpleNamespace

    from runtime.post_generation_filters import PostGenerationFiltersMixin

    class Harness(PostGenerationFiltersMixin):
        pass

    harness = Harness()
    harness.logger = SimpleNamespace(debug=lambda *args, **kwargs: None)
    decision = Decision(text="Tôi đây.", animation="stand", should_speak=True)
    result = harness._apply_utterance_evaluator_filter(
        decision,
        channel="chat",
        user_text="xin chào eris",
    )
    assert result.text == "Tôi đây."
    assert "chưa đủ căn cứ" not in result.text.lower()
