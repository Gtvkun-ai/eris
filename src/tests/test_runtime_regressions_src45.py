from __future__ import annotations

from types import SimpleNamespace

from cortex.conversation_dynamics import ConversationDynamicsReport, ConversationDynamicsState, ConversationFailure
from cortex.fe import FeRenderer
from cortex.grounding_guard import GroundingGuardEngine
from cortex.inquiry_planner import InquiryPlannerEngine
from cortex.turn_semantics import TurnSemanticsEngine
from domain import Decision
from memory.memory_commit_policy import MemoryCommitPolicy
from memory.memory_query_slot_parser import MemoryQuerySlotParser
from parser_grounding.decision import ParserGroundingMixin
from runtime.chat_cycle import ChatCycleMixin
from runtime.coordinator import RuntimeCoordinator
from runtime.stage_performance_planner import PerformanceRequestPlanner
from runtime.source_grounding import SourceGroundingEngine
from runtime.stage_transformers import StageMarks, StageTextSurfaces
from runtime.state_commit_service import StateCommitServiceMixin


def test_v3_grounding_guard_accepts_production_dict():
    frame = SimpleNamespace(permission=None, speech_opportunity=None, modality=None, evidence=[])
    decision, report = GroundingGuardEngine().check(
        frame,
        {
            "text": "V3_COGNITIVE_PLAN là hidden state. Phần sửa hữu ích vẫn giữ.",
            "animation": "stand",
            "should_speak": True,
            "reasoning_tags": [],
        },
    )
    assert isinstance(decision, Decision)
    assert "hidden state" not in decision.text.lower()
    assert "Phần sửa hữu ích" in decision.text
    assert report.unsupported_claims


def test_name_association_question_is_not_stolen_by_memory_recall():
    parser = MemoryQuerySlotParser()
    association = parser.parse("Em liên tưởng tên tôi với cái gì?")
    assert not any(h.ir.intercept_permission for h in association.hypotheses)

    recall = parser.parse("Tên tôi là gì?")
    assert any(h.ir.intercept_permission and h.ir.target.fact_key == "user.name" for h in recall.hypotheses)


def test_full_name_variants_commit_exact_surface():
    policy = MemoryCommitPolicy()
    for text in (
        "Tên đầy đủ của tôi là Cao Nguyễn Yên Hoà",
        "Tôi tên đầy đủ là Cao Nguyễn Yên Hoà",
        "Tên thật đầy đủ của tôi là Cao Nguyễn Yên Hoà",
    ):
        decisions = policy.decide_from_user_turn(text, turn_id="turn-name")
        assert decisions, text
        assert decisions[0].metadata["fact_key"] == "user.name"
        assert decisions[0].surface == "Cao Nguyễn Yên Hoà"


def test_laugh_act_does_not_override_refusal_content():
    planner = PerformanceRequestPlanner()
    surfaces = StageTextSurfaces(
        raw_text="Tôi không thể cười nhạo người đó.",
        display_text="Tôi không thể cười nhạo người đó.",
        tts_text="Tôi không thể cười nhạo người đó.",
        memory_text="Tôi không thể cười nhạo người đó.",
        marks=StageMarks(text="Tôi không thể cười nhạo người đó."),
    )
    result = planner.apply(
        surfaces,
        user_text="Cười người trên Meet đi",
        nonverbal_cue="audible_laugh_soft",
        extracted_actions=("audible_laugh_soft",),
    )
    assert not result.tts_text.startswith("Hah")
    assert result.performance_act is None
    assert "audible_laugh_soft" not in result.actions


def test_investigation_words_route_to_web_search():
    plan = InquiryPlannerEngine().plan(
        SimpleNamespace(user_text="Điều tra và kiểm chứng vụ điểm thi này", channel="chat"),
        SimpleNamespace(intrusion_risk=0.1, contradiction_pressure=0.0, knowledge_gap=0.5, inquiry_urgency=0.4),
        SimpleNamespace(needs_clarification=False),
    )
    assert plan.action == "search_web"


def test_stale_failure_does_not_force_every_clean_turn_into_repair():
    state = ConversationDynamicsState(mode="settled", last_failure=ConversationFailure(type="misread"))
    report = ConversationDynamicsReport(state=state, failure_detected=False)
    pressure = TurnSemanticsEngine()._prior_failure_pressure("Câu trả lời bình thường.", report)
    assert pressure == 0.0


class _ParserProbe(ParserGroundingMixin):
    fallback = {"text": "fallback", "animation": "stand"}

    def _apply_cognition_action_defaults(self, payload, user_hint=""):
        return dict(payload)

    @staticmethod
    def _normalize_salvaged_text(value):
        return str(value or "").strip()

    @staticmethod
    def _coerce_bool(value, fallback=True):
        return bool(value) if value is not None else fallback

    @staticmethod
    def _infer_structured_action(text, user_hint=""):
        return {
            "animation": "stand",
            "direction": 0,
            "next_animation": "",
            "target_x": -1.0,
            "bounce_action": "",
        }


def test_valid_optional_empty_json_fields_are_not_hard_repair():
    payload = {
        "text": "Câu trả lời hợp lệ.",
        "intent": "answer",
        "action": "answer",
        "reasoning_tags": [],
        "should_speak": True,
        "confidence": 0.8,
        "animation": "stand",
        "extracted_fact": "",
        "direction": 0,
        "next_animation": "",
        "target_x": -1.0,
        "bounce_action": "",
        "debug_trace": "",
        "system_action": "",
        "action_input": "",
        "motion_intent": "",
        "motion_target_x": -1.0,
        "motion_facing": 0,
        "delivery_hint": "",
        "nonverbal_cue": "",
        "stage_motion": "",
        "parse_mode": "json",
    }
    _, patched = _ParserProbe()._patch_missing_decision_fields(payload, parse_mode="json")
    assert patched is False


class _Logger:
    def warning(self, *args, **kwargs):
        pass


class _MemoryOwner(StateCommitServiceMixin):
    def __init__(self, result):
        self.logger = _Logger()
        self.memory_kernel = SimpleNamespace(ingest=lambda *args, **kwargs: result)

    def _user_turn_memory_evidence_id(self, *, frame=None, turn_id=None):
        return turn_id or "turn:test"


class _IngestResult:
    def __init__(self, committed_count):
        self.accepted = committed_count > 0
        self.committed_count = committed_count
        self.decisions = []

    def to_dict(self):
        return {"accepted": self.accepted, "committed_count": self.committed_count}


def test_hot_memory_ingest_only_reports_success_after_real_commit():
    empty_frame = SimpleNamespace(permission=None, frame_id="f1", channel="chat", memory_ingest_receipt={})
    assert _MemoryOwner(_IngestResult(0))._ingest_user_turn_via_memory_kernel(empty_frame, "ghi nhớ đi") is False
    assert empty_frame.memory_ingest_receipt["committed_count"] == 0

    committed_frame = SimpleNamespace(permission=None, frame_id="f2", channel="chat", memory_ingest_receipt={})
    assert _MemoryOwner(_IngestResult(1))._ingest_user_turn_via_memory_kernel(committed_frame, "Tôi tên Hoà") is True
    assert committed_frame.memory_ingest_receipt["committed_count"] == 1


class _CoordinatorProbe:
    _MEMORY_SUCCESS_CLAIM_MARKERS = RuntimeCoordinator._MEMORY_SUCCESS_CLAIM_MARKERS
    _normalize_marker_text = ChatCycleMixin._normalize_marker_text
    _apply_memory_commit_truth_guard = RuntimeCoordinator._apply_memory_commit_truth_guard
    _is_tutor_delegation_only = RuntimeCoordinator._is_tutor_delegation_only
    _resolve_tutor_research_topic = RuntimeCoordinator._resolve_tutor_research_topic
    _looks_like_screen_vision_request = RuntimeCoordinator._looks_like_screen_vision_request

    def __init__(self):
        self.last_user_text_for_semantics = "Điều tra vụ điểm thi vừa công bố"

    @staticmethod
    def _ensure_session_turn_ledger():
        return SimpleNamespace(user_turns=lambda: [])


def test_memory_success_claim_is_rewritten_without_commit_receipt():
    owner = _CoordinatorProbe()
    decision = Decision(text="Tôi đã cập nhật ký ức rồi.", animation="stand")
    guarded = owner._apply_memory_commit_truth_guard(decision, frame=SimpleNamespace(memory_ingest_receipt={"committed_count": 0}))
    assert "chưa xác nhận thành công" in guarded.text
    assert "memory_ack_suppressed_unconfirmed" in guarded.reasoning_tags


def test_tutor_delegation_reuses_previous_substantive_topic():
    owner = _CoordinatorProbe()
    current = "Hỏi sư phụ Gemini đi"
    assert owner._is_tutor_delegation_only(current)
    assert owner._resolve_tutor_research_topic(current) == "Điều tra vụ điểm thi vừa công bố"


def test_coordinator_uses_smart_vision_gate_not_broad_web_keyword():
    owner = _CoordinatorProbe()
    assert owner._looks_like_screen_vision_request("xem lại web logic này") is False
    assert owner._looks_like_screen_vision_request("xem màn hình đi") is True


def test_fe_and_source_grounding_recognize_investigation_without_misrouting_code_search():
    assert FeRenderer._is_world_knowledge_question("Điều tra và kiểm chứng vụ điểm thi này") is True
    assert FeRenderer._is_world_knowledge_question("Tìm bug trong code này") is False
    report = SourceGroundingEngine().analyze("Điều tra và kiểm chứng vụ điểm thi này")
    assert report.primary_source == "web"
    assert "web_access_or_search_result" in report.missing_evidence


class _TiPassThrough:
    @staticmethod
    def enforce_decision(decision, *args, **kwargs):
        return decision


def test_identity_fast_path_answers_only_the_name():
    owner = _CoordinatorProbe()
    owner.ti_governor = _TiPassThrough()
    owner.action_router = None
    owner.action_executor = None
    decision = RuntimeCoordinator._build_direct_action_decision(
        owner, "Em tên gì?", SimpleNamespace(animation_hint="stand"), SimpleNamespace(), repeat_count=1
    )
    assert decision is not None
    assert decision.text == "Em là Eris."
    assert decision.parse_mode == "direct_identity"
