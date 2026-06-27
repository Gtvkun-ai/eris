from __future__ import annotations

from dataclasses import dataclass

from runtime.stage_contracts import StageFrameBuilder, clean_tts_source


@dataclass
class DummyDecision:
    text: str
    animation: str = "stand"
    intent: str = "test"
    should_speak: bool = True

    def resolve_motion_intent(self) -> str:
        return "tilt_head"


def test_clean_tts_source_removes_stage_tag_and_markdown_noise():
    raw = "(cười khẽ) **Ừ**, xem `foo()` ở https://example.com đi."

    assert clean_tts_source(raw) == "Ừ, xem ở đi."


def test_stage_frame_separates_display_and_tts_text():
    decision = DummyDecision(text="(nhíu mắt) **Khoan.** Bug này không nằm ở TTS.")
    frame = StageFrameBuilder().build(
        decision,
        payload={"text": decision.text, "should_speak": True},
        channel="chat",
        turn_id="turn-test",
    )

    assert frame.turn_id == "turn-test"
    assert frame.display_text == "(nhíu mắt) **Khoan.** Bug này không nằm ở TTS."
    assert frame.tts_text == "Khoan. Bug này không nằm ở TTS."
    assert frame.motion == "tilt_head"
    assert frame.interruptible is True


def test_stage_frame_payload_patch_is_backward_safe():
    decision = DummyDecision(text="Ổn.")
    frame = StageFrameBuilder().build(
        decision,
        payload={"text": decision.text, "should_speak": True},
        channel="chat",
        turn_id="abc",
    )
    patch = frame.to_payload_patch()

    assert patch["display_text"] == "Ổn."
    assert patch["stage"]["turn_id"] == "abc"
    assert patch["stage"]["segment_id"] == 0
    assert "text" not in patch
