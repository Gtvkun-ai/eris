# -*- coding: utf-8 -*-
from types import SimpleNamespace

from actions.contracts import VALID_SYSTEM_ACTIONS
from actions.router import ActionRouter
from cortex.inquiry_planner import InquiryPlannerEngine
from domain import Decision
from runtime.v3_authority import V3AuthorityController


def _drive(**overrides):
    values = dict(
        curiosity_pressure=0.4,
        knowledge_gap=0.2,
        contradiction_pressure=0.0,
        inquiry_urgency=0.3,
        intrusion_risk=0.1,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _meaning(**overrides):
    values = dict(ambiguity=0.1, confidence=0.9, needs_clarification=False)
    values.update(overrides)
    return SimpleNamespace(**values)


def test_search_web_is_not_a_runtime_action_anymore():
    assert "search_web" not in VALID_SYSTEM_ACTIONS


def test_router_does_not_turn_chat_or_explicit_words_into_direct_web_tool():
    router = ActionRouter()
    assert router.route_chat("có gì vui hôm nay không eris") is None
    assert router.route_chat("search web vụ này") is None


def test_inquiry_planner_does_not_treat_hom_nay_as_web_permission():
    frame = SimpleNamespace(user_text="có gì vui hôm nay không eris", channel="chat")
    plan = InquiryPlannerEngine().plan(frame, _drive(), _meaning())
    assert plan.action != "search_web"


def test_v3_authority_preserves_chat_text_when_legacy_frame_contains_search_web():
    permission = SimpleNamespace(
        public_sayable=True, allowed_tease=True, allowed_search=False, max_intensity=0.6
    )
    v3_frame = SimpleNamespace(
        agency=SimpleNamespace(intent="speak"),
        permission=permission,
        speech_opportunity=SimpleNamespace(speech_allowed=True),
        speech_plan=SimpleNamespace(),
        body_plan=SimpleNamespace(action="none"),
        modality=SimpleNamespace(system_action="search_web", contradiction_risk=0.0),
        metadata={
            "knowledge_acquisition": SimpleNamespace(
                system_action="search_web", deferred=True, succeeded=False, query="hôm nay"
            )
        },
        user_text="có gì vui hôm nay không eris",
    )
    original = Decision(text="Có chứ, hôm nay bớt nhạt một chút rồi.", animation="stand", system_action="search_web", action_input="hôm nay")
    governed = V3AuthorityController().apply_to_decision(original, v3_frame=v3_frame, channel="chat")
    assert governed.text == original.text
    assert governed.system_action == ""
    assert governed.action_input == ""
    assert "retired_search_web" in governed.debug_trace
