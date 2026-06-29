from __future__ import annotations

import os
import sys
import types


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

class _DummyResponse:
    status_code = 0
    reason = ""
    url = ""
    text = ""


class _DummyHTTPError(Exception):
    def __init__(self, *args, response=None, **kwargs):
        super().__init__(*args)
        self.response = response


sys.modules.setdefault(
    "requests",
    types.SimpleNamespace(
        Response=_DummyResponse,
        HTTPError=_DummyHTTPError,
        RequestException=Exception,
        post=lambda *args, **kwargs: _DummyResponse(),
    ),
)

from runtime.speech_delivery_planner import AffectSignals, SpeechDeliveryPlanner
from runtime.stage_contracts import StageFrameBuilder
from runtime.stage_transformers import StageTransformerChain
from domain import Decision
from parser_grounding.service import DecisionParser


class _Appraisal:
    stance = "playful"
    arousal = 0.42


class _InternalState:
    curiosity = 0.2
    restraint = 0.62
    attachment = 0.4
    overload = 0.0
    tension = 0.1
    fatigue = 0.0


class _Frame:
    appraisal = _Appraisal()
    internal_state = _InternalState()


class _Decision:
    text = "(cười khẽ) **Ngài lại vá bằng băng keo à?** [look_away] emotion=teasing"
    intent = "playful_aside"
    animation = "stand"
    should_speak = True

    def resolve_motion_intent(self) -> str:
        return ""


def test_stage_transformer_removes_action_tags_from_text_surfaces():
    surfaces = StageTransformerChain().transform(
        "(cười khẽ) **Ngài lại vá bằng băng keo à?** [look_away] emotion=teasing"
    )

    assert surfaces.display_text == "Ngài lại vá bằng băng keo à?"
    assert surfaces.tts_text == "Ngài lại vá bằng băng keo à?"
    assert surfaces.memory_text == "Ngài lại vá bằng băng keo à?"
    assert "laugh_soft" in surfaces.marks.actions
    assert "look_away" in surfaces.marks.actions
    assert surfaces.marks.emotion_hint == "teasing"


def test_delivery_planner_turns_affect_into_stage_actions_not_text_tags():
    plan = SpeechDeliveryPlanner().plan(
        "Ngài lại vá bằng băng keo à?",
        intent="playful_aside",
        affect=AffectSignals(valence=0.22, arousal=0.42, restraint=0.66, stance="playful"),
    )

    assert plan.voice_style == "dry_tease"
    assert plan.emotion == "dry_tease"
    assert "laugh_soft" in plan.pre_speech_actions
    assert plan.motion in {"look_away", "small_smile"}
    assert "(cười" not in plan.prosody_notes


def test_stage_frame_builder_exposes_display_tts_memory_and_delivery():
    frame = StageFrameBuilder().build(
        _Decision(),
        payload={
            "text": _Decision.text,
            "should_speak": True,
            "emotion_debug": {"summary": {"valence": 0.22}},
        },
        channel="presence",
        frame=_Frame(),
        turn_id="turn-test",
    )

    assert frame.display_text == "Ngài lại vá bằng băng keo à?"
    assert frame.tts_text == "Ngài lại vá bằng băng keo à?"
    assert frame.memory_text == "Ngài lại vá bằng băng keo à?"
    assert frame.emotion in {"dry_tease", "mischief_soft"}
    assert "laugh_soft" in frame.actions
    assert frame.delivery["voice_style"] in {"dry_tease", "soft_tease"}
    payload = frame.to_payload_patch()
    assert payload["display_text"] == "Ngài lại vá bằng băng keo à?"
    assert payload["stage"]["actions"]


def test_llm_structured_stage_fields_survive_parser_and_drive_stage():
    parser = DecisionParser(fallback=Decision(text="", animation="stand"))
    raw = """
    {
      "text": "Ngài lại vá bằng băng keo à?",
      "intent": "playful_aside",
      "action": {"type":"none"},
      "animation": "stand",
      "reasoning_tags": ["stage_delivery"],
      "should_speak": true,
      "confidence": 0.72,
      "direction": 0,
      "target_x": -1.0,
      "bounce_action": "",
      "extracted_fact": "",
      "debug_trace": "structured_stage",
      "next_animation": "",
      "system_action": "",
      "action_input": "",
      "delivery_hint": "dry_tease",
      "nonverbal_cue": "cuoi_khe",
      "stage_motion": "look_away"
    }
    """
    decision = parser.parse(raw)
    assert decision.text == "Ngài lại vá bằng băng keo à?"
    assert decision.delivery_hint == "dry_tease"
    assert decision.nonverbal_cue == "laugh_soft"
    assert decision.stage_motion == "look_away"

    frame = StageFrameBuilder().build(
        decision,
        payload=decision.to_payload(),
        channel="chat",
        frame=_Frame(),
        turn_id="turn-structured",
    )
    assert frame.tts_text == "Ngài lại vá bằng băng keo à?"
    assert "laugh_soft" in frame.actions
    assert frame.motion == "look_away"
    assert frame.delivery["voice_style"] == "dry_tease"


if __name__ == "__main__":
    test_stage_transformer_removes_action_tags_from_text_surfaces()
    test_delivery_planner_turns_affect_into_stage_actions_not_text_tags()
    test_stage_frame_builder_exposes_display_tts_memory_and_delivery()
    test_llm_structured_stage_fields_survive_parser_and_drive_stage()
