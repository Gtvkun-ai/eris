# -*- coding: utf-8 -*-
"""Canonical stage adapters cho ERIS Cognitive Pipeline V3.

File này không dựng thêm một "bộ não thứ ba". Nó làm việc ít hào nhoáng hơn nhưng
cần thiết hơn: chuyển các state/module hiện có của ERIS thành đúng contract trong
Grand Architecture, để một ``core.CognitiveFrame`` có thể đi hết từ time/affect
đến agency/modality và được khép vòng sau execution.

Các adapter đều:
- đọc ``workspace``/evidence đã chọn thay vì đọc raw world tùy tiện;
- deterministic, không gọi LLM hoặc I/O;
- degrade về state ``unknown`` thay vì ném exception vào hot path;
- giữ output có cấu trúc để prompt/body/memory dùng chung một nguồn sự thật.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
import hashlib
import re
import time
from typing import Any, Iterable, Literal, Optional


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return max(0.0, min(1.0, default))


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _first(obj: Any, names: Iterable[str], default: Any = None) -> Any:
    for name in names:
        value = _get(obj, name, None)
        if value is not None and value != "":
            return value
    return default


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return _plain(to_dict())
        except Exception:
            pass
    if is_dataclass(value):
        return _plain(asdict(value))
    return repr(value)


def _ids(items: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for item in items or ():
        value = _first(item, ("id", "evidence_id", "inference_id", "hypothesis_id"), "")
        if value:
            result.append(str(value))
    return list(dict.fromkeys(result))


def _confidence(item: Any, default: float = 0.0) -> float:
    return _clamp(_first(item, ("confidence", "score", "probability"), default), default)


def _summary(item: Any) -> str:
    value = _first(item, ("summary", "description", "claim", "label", "text", "content"), "")
    return re.sub(r"\s+", " ", str(value or "")).strip()


class _Serializable:
    def to_dict(self) -> dict[str, Any]:
        return _plain(asdict(self))


@dataclass(slots=True)
class TemporalFrame(_Serializable):
    # Clock context: thời gian địa phương thật, không chỉ nhịp/TTL kỹ thuật.
    timezone: str = "Asia/Ho_Chi_Minh"
    now_iso: str = ""
    local_date: str = ""
    local_time: str = ""
    weekday: str = ""
    weekday_vi: str = ""
    time_of_day: str = ""
    time_of_day_vi: str = ""
    is_weekend: bool = False
    session_elapsed_seconds: float = 0.0
    since_last_user_turn_seconds: float | None = None
    since_last_assistant_turn_seconds: float | None = None
    since_last_session_seconds: float | None = None
    calendar_relation: str = ""

    # Conversation rhythm: phần temporal cũ vẫn giữ nguyên để tương thích.
    recency: float = 1.0
    duration: float = 0.0
    rhythm: Literal["idle", "focused", "fragmented", "repetitive", "escalating", "cooling"] = "focused"
    recurrence: float = 0.0
    session_arc: Literal["opening", "building", "deep_work", "fatigue", "closing", "unknown"] = "unknown"
    unfinished_time_pressure: float = 0.0
    meaning_debt: float = 0.0
    waiting_pressure: float = 0.0
    repetition_fatigue: float = 0.0


@dataclass(slots=True)
class SpatialFrame(_Serializable):
    body_position: tuple[float, float] = (0.5, 0.5)
    facing_direction: tuple[float, float] = (0.0, 1.0)
    gaze_target: Optional[str] = None
    posture: Literal["neutral", "attentive", "withdrawn", "idle", "approaching", "leaving"] = "neutral"
    distance_to_focus: float = 0.5
    obstruction_risk: float = 0.0
    shared_space_relation: Literal["near", "far", "blocking", "parallel", "unknown"] = "unknown"
    approach_affordance: float = 0.4
    withdrawal_affordance: float = 0.4
    body_interaction_meaning: Optional[str] = None


@dataclass(slots=True)
class HomeostaticState(_Serializable):
    energy_budget: float = 0.65
    cognitive_load: float = 0.25
    social_load: float = 0.20
    exposure_load: float = 0.10
    curiosity_pressure: float = 0.25
    attachment_pressure: float = 0.15
    irritation_pressure: float = 0.05
    tenderness_pressure: float = 0.10
    silence_recovery_need: float = 0.10
    speech_cost: float = 0.20
    action_readiness: float = 0.65
    regulation_policy: Literal[
        "normal", "reduce_speech", "short_grounded", "withdraw", "repair", "observe_only", "act_practically"
    ] = "normal"


@dataclass(slots=True)
class AffectiveState(_Serializable):
    energy: float = 0.65
    fatigue: float = 0.20
    arousal: float = 0.30
    tension: float = 0.20
    curiosity: float = 0.25
    restraint: float = 0.45
    attachment_pressure: float = 0.15
    irritation: float = 0.05
    tenderness: float = 0.10
    exposure_recoil: float = 0.10
    continuity_anxiety: float = 0.10
    affective_residue: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class CanonicalMeaningReport(_Serializable):
    hypotheses: list[Any] = field(default_factory=list)
    pragmatic_intents: list[Any] = field(default_factory=list)
    surfaced: list[Any] = field(default_factory=list)
    withheld: list[Any] = field(default_factory=list)
    dominant_hypothesis: Any = None
    ambiguity: float = 1.0
    needs_clarification: bool = False
    confidence: float = 0.0


@dataclass(slots=True)
class CanonicalTheoryOfMindReport(_Serializable):
    mental_states: list[Any] = field(default_factory=list)
    alternatives: list[Any] = field(default_factory=list)
    forbidden_assumptions: list[str] = field(default_factory=list)
    allowed_surface_expression: list[str] = field(default_factory=list)
    global_confidence: float = 0.0
    global_overread_risk: float = 1.0


@dataclass(slots=True)
class EpistemicDrive(_Serializable):
    curiosity_pressure: float = 0.0
    knowledge_gap: float = 0.0
    contradiction_pressure: float = 0.0
    worldview_tension: float = 0.0
    user_relevance: float = 0.0
    identity_relevance: float = 0.0
    inquiry_urgency: float = 0.0
    intrusion_risk: float = 0.0


@dataclass(slots=True)
class InquiryPlan(_Serializable):
    action: Literal[
        "observe_more", "ask_user", "search_memory", "search_web", "compare_patterns", "infer_quietly", "suppress_inquiry"
    ] = "infer_quietly"
    reason: str = ""
    expected_value: float = 0.0
    privacy_cost: float = 0.0
    interruption_cost: float = 0.0


@dataclass(slots=True)
class Belief(_Serializable):
    id: str
    claim: str
    domain: str = "world"
    confidence: float = 0.0
    source_ids: list[str] = field(default_factory=list)
    status: str = "tentative"
    last_updated: float = field(default_factory=time.time)
    contradiction_ids: list[str] = field(default_factory=list)
    emotional_weight: float = 0.0


@dataclass(slots=True)
class BeliefReport(_Serializable):
    active_beliefs: list[Belief] = field(default_factory=list)
    candidate_beliefs: list[Belief] = field(default_factory=list)
    rejected_beliefs: list[Belief] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CanonicalMemoryPacket(_Serializable):
    episodic: list[str] = field(default_factory=list)
    semantic: list[str] = field(default_factory=list)
    relational: list[str] = field(default_factory=list)
    affective_residue: list[str] = field(default_factory=list)
    procedural: list[str] = field(default_factory=list)
    temporal: list[str] = field(default_factory=list)
    spatial: list[str] = field(default_factory=list)
    worldview: list[str] = field(default_factory=list)
    confidence_notes: list[str] = field(default_factory=list)
    token_budget: int = 0


@dataclass(slots=True)
class ValueConflict(_Serializable):
    conflict_type: str
    values_in_conflict: list[str]
    severity: float
    proposed_resolution: str


@dataclass(slots=True)
class ValueResolutionReport(_Serializable):
    conflicts: list[ValueConflict] = field(default_factory=list)
    winning_value: str = "truthfulness"
    suppressed_values: list[str] = field(default_factory=list)
    max_allowed_intensity: float = 0.6
    reason: str = ""


@dataclass(slots=True)
class SimulatedActionOutcome(_Serializable):
    action_type: str
    expected_user_reaction: str
    usefulness: float
    social_risk: float
    privacy_risk: float
    relationship_cost: float
    continuity_gain: float
    confidence: float


@dataclass(slots=True)
class ArbitrationResult(_Serializable):
    competing_drives: list[str] = field(default_factory=list)
    winning_drive: str = "practical_help"
    suppressed_drives: list[str] = field(default_factory=list)
    compromise_action: str = "answer_directly"
    reason: str = ""
    confidence: float = 0.0


@dataclass(slots=True)
class ActionCommitment(_Serializable):
    intent: Literal[
        "speak", "stay_silent", "observe", "ask", "search", "remember", "forget", "move", "repair", "withdraw", "body_only"
    ] = "speak"
    goal_preserved: str = "respond usefully"
    commitment_strength: float = 0.5
    reversibility: float = 0.9
    reason: str = ""


@dataclass(slots=True)
class RelationalState(_Serializable):
    trust: float = 0.5
    familiarity: float = 0.5
    rupture: float = 0.0
    repair_need: float = 0.0
    preferred_distance: float = 0.5
    attachment_visibility: float = 0.2
    dignity_defense: float = 0.5
    teasing_permission: float = 0.35
    privacy_sensitivity: float = 0.5
    overread_correction: float = 0.5
    user_specific_rhythm: str = "unknown"
    cultural_boundary: float = 0.5


@dataclass(slots=True)
class PermissionReport(_Serializable):
    public_sayable: bool = True
    prompt_sayable: bool = True
    memory_storable: bool = True
    raw_evidence_storable: bool = False
    allowed_reaction: list[str] = field(default_factory=list)
    allowed_body_action: list[str] = field(default_factory=list)
    allowed_search: bool = False
    allowed_tease: bool = False
    allowed_proactivity: bool = False
    max_intensity: float = 0.5
    reason: str = ""


@dataclass(slots=True)
class NoiseFrame(_Serializable):
    timing_jitter: float = 0.0
    attention_drift: float = 0.0
    wording_asymmetry: float = 0.0
    affective_jitter: float = 0.0
    memory_oddness: float = 0.0
    preference_drift: float = 0.0
    micro_hesitation: float = 0.0


@dataclass(slots=True)
class SpeechOpportunity(_Serializable):
    mode: Literal[
        "silence", "private_bias", "micro_tease", "soft_support", "practical_help", "memory_update_only",
        "body_only_reaction", "reengagement", "direct_answer"
    ] = "direct_answer"
    speech_allowed: bool = True
    reason_to_speak: str = ""
    reason_to_stay_silent: str = ""
    urgency: float = 0.5
    interruption_cost: float = 0.0


@dataclass(slots=True)
class SpeechPlan(_Serializable):
    speech_act: Literal[
        "answer", "clarify", "tease", "warn", "repair", "support", "technical_diagnosis", "compress", "reflect", "decline"
    ] = "answer"
    tone: str = "cold_soft"
    warmth: float = 0.3
    restraint: float = 0.5
    directness: float = 0.8
    tease_level: float = 0.0
    technical_depth: float = 0.4
    emotional_visibility: float = 0.15
    must_include: list[str] = field(default_factory=list)
    must_avoid: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BodyActionPlan(_Serializable):
    action: Literal[
        "none", "face_user", "look_at_focus", "step_closer", "step_back", "idle_shift", "stillness",
        "turn_away_softly", "approach_focus", "withdraw"
    ] = "none"
    gaze_target: Optional[str] = None
    posture: Optional[str] = None
    movement: Optional[str] = None
    intensity: float = 0.0
    timing_delay_ms: int = 0


@dataclass(slots=True)
class ModalitySyncFrame(_Serializable):
    speech_plan: Optional[SpeechPlan] = None
    body_plan: Optional[BodyActionPlan] = None
    system_action: Optional[str] = None
    emotional_congruence: float = 1.0
    spatial_safety: float = 1.0
    contradiction_risk: float = 0.0
    final_delay_ms: int = 0
    correction_notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LLMWordingResult(_Serializable):
    raw_text: str = ""
    parsed_text: Optional[str] = None
    parser_ok: bool = True
    violations: list[str] = field(default_factory=list)
    deferred: bool = True


@dataclass(slots=True)
class GroundingReport(_Serializable):
    factual_risk: float = 0.0
    unsupported_claims: list[str] = field(default_factory=list)
    overcertainty_risk: float = 0.0
    tone_violation: float = 0.0
    permission_violation: float = 0.0
    body_action_mismatch: float = 0.0
    repair_action: Optional[str] = None
    final_text: Optional[str] = None


@dataclass(slots=True)
class ExecutionReport(_Serializable):
    status: str = "planned"
    speech_executed: bool = False
    body_executed: bool = False
    system_action_executed: bool = False
    memory_commit_deferred: bool = True
    details: dict[str, Any] = field(default_factory=dict)


class CanonicalStageSuite:
    """Canonical stage facade backed by dedicated V3 engines.

    Contracts remain in this module for compatibility, while decisions now live
    in independent modules matching the Grand Architecture. The old single-file
    heuristic blob was convenient in the same way a drawer full of loose wires
    is convenient: only until someone needs to debug it.
    """

    def __init__(self) -> None:
        # Local imports avoid a contracts/import cycle: engine modules consume
        # the dataclasses re-exported by this compatibility module.
        from cortex.temporal_perception import TemporalPerceptionEngine
        from cortex.spatial_proprioception import SpatialProprioceptionEngine
        from cortex.homeostasis import HomeostasisEngine
        from cortex.affective_substrate import AffectiveSubstrateEngine
        from cortex.epistemic_drive import EpistemicDriveEngine
        from cortex.inquiry_planner import InquiryPlannerEngine
        from cortex.relational_dynamics import RelationalDynamicsEngine
        from cortex.permission_engine import PermissionEngine
        from cortex.value_resolution import ValueResolutionEngine
        from cortex.predictive_simulation import PredictiveSimulationEngine
        from cortex.cognitive_arbitration import CognitiveArbitrationEngine
        from cortex.agency_engine import AgencyEngine
        from cortex.speech_opportunity import SpeechOpportunityEngine
        from cortex.modality_sync import ModalitySyncEngine
        from cortex.memory_cognition_adapter import MemoryCognitionAdapterEngine
        from cortex.belief_core import BeliefCoreEngine
        from cortex.calculated_noise import CalculatedNoiseEngine
        from cortex.speech_planner import SpeechPlannerEngine
        from cortex.body_action_planner import BodyActionPlannerEngine

        self.temporal_engine = TemporalPerceptionEngine()
        self.spatial_engine = SpatialProprioceptionEngine()
        self.homeostasis_engine = HomeostasisEngine()
        self.affect_engine = AffectiveSubstrateEngine()
        self.epistemic_engine = EpistemicDriveEngine()
        self.inquiry_engine = InquiryPlannerEngine()
        self.relation_engine = RelationalDynamicsEngine()
        self.permission_engine = PermissionEngine()
        self.value_engine = ValueResolutionEngine()
        self.simulation_engine = PredictiveSimulationEngine()
        self.arbitration_engine = CognitiveArbitrationEngine()
        self.agency_engine = AgencyEngine()
        self.speech_opportunity_engine = SpeechOpportunityEngine()
        self.modality_engine = ModalitySyncEngine()
        self.memory_engine = MemoryCognitionAdapterEngine()
        self.belief_engine = BeliefCoreEngine()
        self.noise_engine = CalculatedNoiseEngine()
        self.speech_planner_engine = SpeechPlannerEngine()
        self.body_planner_engine = BodyActionPlannerEngine()

    def temporal(self, frame: Any, *, idle_seconds: Optional[float] = None, legacy_frame: Any = None) -> TemporalFrame:
        return self.temporal_engine.evaluate(frame, idle_seconds=idle_seconds, legacy_frame=legacy_frame)

    def spatial(self, frame: Any, *, snapshot: Any = None, legacy_frame: Any = None) -> SpatialFrame:
        return self.spatial_engine.evaluate(frame, snapshot=snapshot, legacy_frame=legacy_frame)

    def homeostasis(self, frame: Any, *, legacy_frame: Any = None) -> HomeostaticState:
        return self.homeostasis_engine.evaluate(frame, legacy_frame=legacy_frame)

    def affect(self, frame: Any, homeostasis: HomeostaticState, *, legacy_frame: Any = None) -> AffectiveState:
        return self.affect_engine.evaluate(frame, homeostasis, legacy_frame=legacy_frame)

    def meaning(self, phase2: Any, frame: Any = None) -> CanonicalMeaningReport:
        hypotheses = list(_get(phase2, "meaning_hypotheses", []) or [])
        intents = list(_get(phase2, "pragmatic_intents", []) or [])
        surfaced = list(_get(phase2, "surfaced", []) or [])
        withheld = list(_get(phase2, "withheld", []) or [])
        dominant = max(hypotheses, key=_confidence, default=None)
        conf = _confidence(dominant, 0.0)

        # Phase2 semantic fallback cố ý bảo thủ, nhưng câu yêu cầu trực tiếp không
        # phải một bí ẩn tâm lý. Khi model embedding không có, giữ một hypothesis
        # surface-grounded từ chính user_text để pipeline không kết luận "không đủ
        # evidence" trước câu "fix file rồi gửi tôi". Chỉ mô tả speech act, tuyệt
        # đối không gán cảm xúc ẩn.
        user_text = str(_get(frame, "user_text", "") or "").strip()
        low_signal = (not dominant) or conf < 0.35 or "insufficient evidence" in _summary(dominant).lower()
        if user_text and low_signal:
            lowered = user_text.lower()
            is_correction = any(token in lowered for token in ("tôi nhớ là", "không phải", "chưa nối", "sai", "ý tôi"))
            is_execute = any(token in lowered for token in ("làm đi", "fix", "sửa", "nối", "gửi file", "gửi cho tôi"))
            label = "direct_correction_request" if is_correction else ("direct_execution_request" if is_execute else "direct_user_request")
            description = (
                "User trực tiếp yêu cầu kiểm tra phần đã nối, hoàn thiện phần còn thiếu và trả artifact/file."
                if is_execute else "User đưa ra một yêu cầu trực tiếp cần được trả lời bám sát bề mặt."
            )
            grounded = {
                "label": label,
                "description": description,
                "confidence": 0.86 if is_execute else 0.72,
                "ambiguity": 0.08 if is_execute else 0.22,
                "overread_risk": 0.04,
                "evidence_ids": _ids(_get(frame, "evidence", []) or []),
                "surface_grounded": True,
            }
            hypotheses.append(grounded)
            surfaced.append(grounded)
            dominant = grounded
            conf = float(grounded["confidence"])

        ambiguity_values = [_clamp(_first(x, ("ambiguity", "overread_risk"), 0.0)) for x in hypotheses]
        ambiguity = max(max(ambiguity_values, default=0.0), max(0.0, 1.0 - conf))
        return CanonicalMeaningReport(
            hypotheses=hypotheses,
            pragmatic_intents=intents,
            surfaced=surfaced,
            withheld=withheld,
            dominant_hypothesis=dominant,
            ambiguity=ambiguity,
            needs_clarification=bool(ambiguity > 0.68 and not surfaced),
            confidence=conf,
        )

    def tom(self, phase2: Any, workspace: Any, frame: Any = None) -> CanonicalTheoryOfMindReport:
        states = list(_get(phase2, "mental_states", []) or [])
        user_text = str(_get(frame, "user_text", "") or "").strip()
        if user_text and not any(_confidence(x) >= 0.45 and _clamp(_get(x, "overread_risk", 1.0), 1.0) < 0.55 for x in states):
            # Đây là intent đọc từ câu nói trực tiếp, không phải đoán cảm xúc.
            lowered = user_text.lower()
            if any(token in lowered for token in ("làm đi", "fix", "sửa", "nối", "gửi file", "gửi cho tôi")):
                states.insert(0, {
                    "label": "explicit_task_intent",
                    "description": "User muốn hệ thống hoàn thành thay đổi kỹ thuật và trả file dùng được.",
                    "confidence": 0.88,
                    "overread_risk": 0.05,
                    "evidence_ids": _ids(_get(frame, "evidence", []) or []),
                    "surface_grounded": True,
                })
        confidences = [_confidence(x) for x in states]
        allowed = [_summary(x) for x in states if _confidence(x) >= 0.58 and _clamp(_get(x, "overread_risk", 1.0), 1.0) < 0.55]
        dominant = max(states, key=_confidence, default=None)
        dominant_confidence = _confidence(dominant, 0.0)
        dominant_risk = _clamp(_get(dominant, "overread_risk", 1.0), 1.0) if dominant is not None else 1.0
        # Global risk đi theo estimate chi phối, không lấy max của mọi alternative.
        # Nếu không, một fallback bị withheld với risk=1.0 sẽ bóp chết một intent
        # explicit confidence=0.88. Alternatives vẫn được giữ để audit.
        return CanonicalTheoryOfMindReport(
            mental_states=states,
            alternatives=[x for x in states if x is not dominant],
            forbidden_assumptions=list(_get(workspace, "forbidden_assumptions", []) or []),
            allowed_surface_expression=[x for x in allowed if x][:4],
            global_confidence=dominant_confidence,
            global_overread_risk=dominant_risk,
        )

    def epistemic(self, frame: Any, meaning: CanonicalMeaningReport, tom: CanonicalTheoryOfMindReport) -> EpistemicDrive:
        return self.epistemic_engine.evaluate(frame, meaning, tom)

    def inquiry(self, frame: Any, drive: EpistemicDrive, meaning: CanonicalMeaningReport) -> InquiryPlan:
        return self.inquiry_engine.plan(frame, drive, meaning)

    def memory_packet(self, frame: Any, *, legacy_frame: Any = None, runtime_owner: Any = None, knowledge: Any = None) -> CanonicalMemoryPacket:
        return self.memory_engine.build(
            frame, legacy_frame=legacy_frame, runtime_owner=runtime_owner, knowledge=knowledge
        )

    def belief(self, frame: Any, meaning: CanonicalMeaningReport, *, knowledge: Any = None) -> BeliefReport:
        return self.belief_engine.evaluate(frame, meaning, knowledge=knowledge)

    def relation(self, frame: Any, *, legacy_frame: Any = None) -> RelationalState:
        return self.relation_engine.evaluate(frame, legacy_frame=legacy_frame)

    def permission(self, frame: Any, tom: CanonicalTheoryOfMindReport, relation: RelationalState, inquiry: InquiryPlan, *, knowledge: Any = None) -> PermissionReport:
        return self.permission_engine.evaluate(frame, tom, relation, inquiry, knowledge=knowledge)

    def values(self, frame: Any, inquiry: InquiryPlan, permission: PermissionReport, relation: RelationalState) -> ValueResolutionReport:
        return self.value_engine.resolve(frame, inquiry, permission, relation)

    def simulations(self, frame: Any, inquiry: InquiryPlan, permission: PermissionReport, relation: RelationalState) -> list[SimulatedActionOutcome]:
        return self.simulation_engine.simulate(frame, inquiry, permission, relation)

    def arbitration(self, simulations: list[SimulatedActionOutcome], inquiry: InquiryPlan, permission: PermissionReport) -> ArbitrationResult:
        return self.arbitration_engine.resolve(simulations, inquiry, permission)

    def agency(self, arbitration: ArbitrationResult, inquiry: InquiryPlan) -> ActionCommitment:
        return self.agency_engine.commit(arbitration, inquiry)

    def noise(self, frame: Any) -> NoiseFrame:
        return self.noise_engine.generate(frame)

    def speech_opportunity(self, frame: Any, agency: ActionCommitment, homeostasis: HomeostaticState, permission: PermissionReport) -> SpeechOpportunity:
        return self.speech_opportunity_engine.evaluate(frame, agency, homeostasis, permission)

    def speech_plan(self, frame: Any, opportunity: SpeechOpportunity, meaning: CanonicalMeaningReport, relation: RelationalState, permission: PermissionReport) -> SpeechPlan:
        return self.speech_planner_engine.plan(frame, opportunity, meaning, relation, permission)

    def body_plan(self, frame: Any, opportunity: SpeechOpportunity, spatial: SpatialFrame, permission: PermissionReport) -> BodyActionPlan:
        return self.body_planner_engine.plan(frame, opportunity, spatial, permission)

    def modality(self, speech: SpeechPlan, body: BodyActionPlan, spatial: SpatialFrame, permission: PermissionReport, *, system_action: str = "") -> ModalitySyncFrame:
        return self.modality_engine.sync(speech, body, spatial, permission, system_action=system_action)

    def deferred_wording(self) -> LLMWordingResult:
        return LLMWordingResult(raw_text="", parsed_text=None, parser_ok=True, violations=[], deferred=True)

    def baseline_grounding(self, frame: Any, permission: PermissionReport, modality: ModalitySyncFrame) -> GroundingReport:
        return GroundingReport(
            factual_risk=0.0,
            unsupported_claims=[],
            overcertainty_risk=0.0,
            tone_violation=0.0,
            permission_violation=0.0 if permission.public_sayable else 1.0,
            body_action_mismatch=modality.contradiction_risk,
            repair_action="suppress_or_reduce_intensity" if not permission.public_sayable else None,
            final_text=None,
        )

    def planned_execution(self, agency: ActionCommitment, modality: ModalitySyncFrame) -> ExecutionReport:
        return ExecutionReport(
            status="planned",
            speech_executed=False,
            body_executed=False,
            system_action_executed=False,
            memory_commit_deferred=True,
            details={"agency_intent": agency.intent, "body_action": _get(modality.body_plan, "action", "none")},
        )

    def render_prompt_context(self, frame: Any) -> str:
        """Projection compact cho wording layer cũ.

        Chỉ đưa các quyết định canonical đã qua workspace/permission; không nhét
        cả CognitiveFrame vào prompt như một tang lễ token thu nhỏ.
        """
        meaning = _get(frame, "meaning", None)
        dominant = _summary(_get(meaning, "dominant_hypothesis", None))
        tom = _get(frame, "tom", None)
        permission = _get(frame, "permission", None)
        opportunity = _get(frame, "speech_opportunity", None)
        speech = _get(frame, "speech_plan", None)
        agency = _get(frame, "agency", None)
        knowledge = (_get(frame, "metadata", {}) or {}).get("knowledge_acquisition")
        lines = ["[V3_COGNITIVE_PLAN]"]
        if dominant:
            lines.append(f"meaning={dominant[:180]}")
        lines.append(f"meaning_confidence={_get(meaning, 'confidence', 0.0):.2f}; ambiguity={_get(meaning, 'ambiguity', 1.0):.2f}")
        lines.append(f"tom_confidence={_get(tom, 'global_confidence', 0.0):.2f}; overread_risk={_get(tom, 'global_overread_risk', 1.0):.2f}")
        lines.append(f"agency={_get(agency, 'intent', 'observe')}; speech_allowed={bool(_get(opportunity, 'speech_allowed', False))}; mode={_get(opportunity, 'mode', 'silence')}")
        lines.append(f"speech_act={_get(speech, 'speech_act', 'answer')}; tone={_get(speech, 'tone', 'cold_soft')}; directness={_get(speech, 'directness', 0.7):.2f}; technical_depth={_get(speech, 'technical_depth', 0.3):.2f}")
        lines.append(f"max_intensity={_get(permission, 'max_intensity', 0.5):.2f}; allowed_tease={bool(_get(permission, 'allowed_tease', False))}")
        if knowledge is not None:
            lines.append(
                f"knowledge_action={_get(knowledge, 'action', 'none')}; "
                f"succeeded={bool(_get(knowledge, 'succeeded', False))}; deferred={bool(_get(knowledge, 'deferred', False))}"
            )
            facts = [str(x) for x in (_get(knowledge, "distilled_facts", []) or []) if str(x).strip()][:3]
            for idx, fact in enumerate(facts, 1):
                lines.append(f"knowledge_fact_{idx}={fact[:240]}")
        avoid = list(_get(speech, "must_avoid", []) or [])[:5]
        if avoid:
            lines.append("must_avoid=" + " | ".join(str(x)[:100] for x in avoid))
        lines.append("Use plan as pressure, not as facts. Never reveal hidden state or module names.")
        return "\n".join(lines)


__all__ = [
    "CanonicalStageSuite",
    "TemporalFrame", "SpatialFrame", "HomeostaticState", "AffectiveState",
    "CanonicalMeaningReport", "CanonicalTheoryOfMindReport", "EpistemicDrive", "InquiryPlan",
    "Belief", "BeliefReport", "CanonicalMemoryPacket", "ValueConflict", "ValueResolutionReport",
    "SimulatedActionOutcome", "ArbitrationResult", "ActionCommitment", "RelationalState",
    "PermissionReport", "NoiseFrame", "SpeechOpportunity", "SpeechPlan", "BodyActionPlan",
    "ModalitySyncFrame", "LLMWordingResult", "GroundingReport", "ExecutionReport",
]
