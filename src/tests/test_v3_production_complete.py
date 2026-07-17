from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from core.evidence import RawSignal
from domain import Decision
from runtime.cognitive_pipeline import CognitivePipeline
from runtime.knowledge_acquisition import KnowledgeAcquisitionEngine
from runtime.shadow_pipeline import ShadowPipelineMixin
from runtime.v3_authority import V3AuthorityController
from runtime.v3_consolidation import build_v3_daydream_packets


class DummyLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


@dataclass
class FakeActionResult:
    action_name: str = "search_web"
    action_input: str = ""
    success: bool = True
    message: str = "OpenAI vừa công bố một cập nhật đã được tool search xác nhận."
    data: dict | None = None


class DummyOwner(ShadowPipelineMixin):
    def __init__(self):
        self.logger = DummyLogger()
        self.v3_pipeline_enabled = True
        self.shadow_pipeline_enabled = False
        self.last_cognitive_frame = None


def run_pipeline(text: str = "hoàn thành pipeline V3"):
    pipeline = CognitivePipeline()
    result = pipeline.run_from_signals(
        [RawSignal.from_chat(text)],
        channel="chat",
        user_text=text,
    )
    return pipeline, result


def test_full_pipeline_populates_canonical_graph_and_commit_protocol():
    pipeline, result = run_pipeline("hoàn thành nốt pipeline V3 trong repo")
    frame = result.frame
    required = (
        "salience", "temporal", "spatial", "homeostasis", "affect",
        "working_memory", "workspace", "world_scene", "interpretation",
        "sociocultural", "meaning", "tom", "epistemic", "inquiry",
        "memory_packet", "belief", "value_resolution", "simulations",
        "arbitration", "agency", "relation", "permission", "noise",
        "speech_opportunity", "speech_plan", "body_plan", "modality",
        "wording", "grounding", "execution",
    )
    assert all(getattr(frame, name) is not None for name in required)
    assert "knowledge_acquisition" in frame.module_reports
    assert frame.metadata["canonical_planning_complete"] is True
    assert {req.target for req in frame.commit_requests} >= {"event_ledger", "active_state"}
    assert "[V3_COGNITIVE_PLAN]" in pipeline.render_prompt_context(frame)


def test_explicit_current_query_does_not_become_direct_web_action():
    pipeline, result = run_pipeline("tìm tin mới nhất về OpenAI")
    frame = result.frame
    knowledge = frame.metadata["knowledge_acquisition"]
    assert frame.inquiry.action != "search_web"
    assert frame.permission.allowed_search is False
    assert knowledge.deferred is False
    assert frame.modality.system_action in {None, ""}

    # Cache/model cũ còn nhả action đã nghỉ hưu cũng không được ghi đè lời chat.
    frame.modality.system_action = "search_web"
    frame.metadata["knowledge_acquisition"] = SimpleNamespace(
        system_action="search_web", deferred=True, succeeded=False, query="tìm tin mới nhất về OpenAI"
    )
    legacy = SimpleNamespace(v3_cognitive_frame=frame, v3_authority={})
    decision = Decision(
        text="Tôi chưa có dữ kiện trực tiếp để khẳng định tin mới.",
        animation="stand",
        should_speak=True,
        system_action="search_web",
        action_input="tìm tin mới nhất về OpenAI",
    )
    governed = V3AuthorityController().apply_to_decision(decision, legacy_frame=legacy, channel="chat")
    assert governed.text == decision.text
    assert governed.system_action == ""
    assert governed.action_input == ""


def test_retired_web_execution_result_is_not_promoted_to_belief():
    pipeline, result = run_pipeline("tìm tin mới nhất về OpenAI")
    frame = result.frame
    action_result = FakeActionResult(action_input="tìm tin mới nhất về OpenAI", data={"source": "fake"})
    final = Decision(
        text="Tôi chưa có dữ kiện trực tiếp để khẳng định tin mới.",
        animation="stand",
        should_speak=True,
        system_action="search_web",
        action_input=action_result.action_input,
    )
    finalized = pipeline.finalize_from_legacy(frame, final_decision=final, execution=action_result)
    knowledge = finalized.frame.metadata["knowledge_acquisition"]
    assert finalized.finalized is True
    assert knowledge.succeeded is False
    assert knowledge.deferred is False
    assert not knowledge.sources
    assert not any(req.target == "belief_core" and "tool_grounded" in req.tags for req in frame.commit_requests)


def test_v3_authority_enforces_silence_and_body_plan():
    _, result = run_pipeline("hmm")
    frame = result.frame
    frame.agency.intent = "body_only"
    frame.speech_opportunity.speech_allowed = False
    frame.body_plan.action = "look_at_focus"
    legacy = SimpleNamespace(v3_cognitive_frame=frame, v3_authority={})
    decision = Decision(text="Một câu không nên phát.", animation="stand", should_speak=True)
    governed = V3AuthorityController().apply_to_decision(decision, legacy_frame=legacy, channel="autonomous")
    assert governed.text == ""
    assert governed.should_speak is False
    assert governed.stage_motion == "look_at_focus"
    assert governed.motion_intent == "pose"


def test_next_turn_feedback_updates_previous_outcome_and_repair_memory():
    pipeline, result = run_pipeline("tôi nghĩ file này đã xong")
    previous_v3 = result.frame
    pipeline.finalize_from_legacy(
        previous_v3,
        final_decision=Decision(text="Đã xong rồi.", animation="stand"),
    )
    previous = SimpleNamespace(
        v3_cognitive_frame=previous_v3,
        v3_feedback_resolved=False,
        commit_requests=[],
        debug_notes=[],
        outcome=None,
        self_observation=None,
    )
    owner = DummyOwner()
    owner._shadow_pipeline_instance = pipeline
    owner.last_cognitive_frame = previous
    current = SimpleNamespace(commit_requests=[])
    report = owner._resolve_v3_feedback_for_previous_turn(
        "không phải, ý tôi là vẫn còn thiếu phần authority",
        current_frame=current,
    )
    assert report is not None
    assert report.user_corrected is True
    assert previous.v3_feedback_resolved is True
    assert previous_v3.outcome.user_corrected is True
    assert any(getattr(req, "target", "") == "repair_memory" for req in previous.commit_requests)
    assert any(getattr(req, "target", "") == "repair_memory" for req in current.commit_requests)


def test_v3_frame_feeds_existing_daydream_scheduler_contract():
    pipeline, result = run_pipeline("ý tôi là phần authority còn thiếu")
    frame = result.frame
    pipeline.finalize_from_legacy(
        frame,
        final_decision=Decision(text="Tôi đã sửa authority.", animation="stand"),
    )
    packets = build_v3_daydream_packets(frame)
    assert packets
    assert all(packet.evidence_ids for packet in packets)
    assert all(packet.metadata.get("source") == "v3_cognitive_frame" for packet in packets)


def test_eager_acquisition_flag_cannot_reenable_direct_web_executor():
    class Executor:
        def __init__(self):
            self.calls = []

        def execute(self, action_name, action_input):
            self.calls.append((action_name, action_input))
            return FakeActionResult(action_input=action_input, data={"url": "source"})

    engine = KnowledgeAcquisitionEngine(eager_external_io=True)
    pipeline = CognitivePipeline(knowledge_acquisition=engine)
    executor = Executor()
    owner = SimpleNamespace(action_executor=executor)
    result = pipeline.run_from_signals(
        [RawSignal.from_chat("tra cứu tin mới nhất về OpenAI")],
        channel="chat",
        user_text="tra cứu tin mới nhất về OpenAI",
        runtime_owner=owner,
    )
    knowledge = result.frame.metadata["knowledge_acquisition"]
    assert executor.calls == []
    assert knowledge.succeeded is False
    assert knowledge.deferred is False


def test_authority_suppresses_retired_web_action_before_production_execution():
    from runtime.coordinator import RuntimeCoordinator

    class Executor:
        def __init__(self):
            self.calls = []

        def execute(self, action_name, action_input):
            self.calls.append((action_name, action_input))
            return FakeActionResult(
                action_input=action_input,
                message="Kết quả search production.",
                data={"answer": "Kết quả search production.", "sources": []},
            )

    class Owner(ShadowPipelineMixin):
        _execute_system_action = RuntimeCoordinator._execute_system_action
        _action_result_to_text = RuntimeCoordinator._action_result_to_text

        def __init__(self):
            self.logger = DummyLogger()
            self.action_executor = Executor()

    _, result = run_pipeline("tìm tin mới nhất về OpenAI")
    legacy = SimpleNamespace(
        channel="chat",
        v3_cognitive_frame=result.frame,
        v3_authority={},
        v3_tool_execution_result=None,
    )
    owner = Owner()
    decision = Decision(
        text="Tôi giữ câu trả lời hiện tại.",
        animation="stand",
        should_speak=True,
        system_action="search_web",
        action_input="tìm tin mới nhất về OpenAI",
    )
    executed = owner._execute_system_action(decision, snapshot=None, frame=legacy)
    assert owner.action_executor.calls == []
    assert executed.text == "Tôi giữ câu trả lời hiện tại."
    assert executed.system_action == ""
    assert legacy.v3_tool_execution_result is None
