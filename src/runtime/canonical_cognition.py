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
    """Tập adapter deterministic cho các stage còn lại của canonical frame."""

    def temporal(self, frame: Any, *, idle_seconds: Optional[float] = None, legacy_frame: Any = None) -> TemporalFrame:
        now = float(_get(frame, "timestamp", time.time()) or time.time())
        timestamps = [float(_get(ev, "timestamp", now) or now) for ev in (_get(frame, "evidence", []) or [])]
        duration = max(0.0, now - min(timestamps)) if timestamps else 0.0
        idle = max(0.0, float(idle_seconds or 0.0))
        user_text = str(_get(frame, "user_text", "") or "").strip()
        old_notes = " ".join(str(x) for x in (_get(legacy_frame, "debug_notes", []) or [])).lower()
        repeat = 0.7 if "repeat" in old_notes else 0.0
        if idle >= 90:
            rhythm = "idle"
        elif repeat > 0.5:
            rhythm = "repetitive"
        elif "correction" in old_notes or "rupture" in old_notes:
            rhythm = "escalating"
        elif len(user_text) > 220:
            rhythm = "focused"
        else:
            rhythm = "focused"
        turn_count = int(_first(legacy_frame, ("cycle_index", "turn_index"), 0) or 0)
        if turn_count <= 1:
            arc = "opening"
        elif idle > 240:
            arc = "closing"
        elif len(user_text) > 300:
            arc = "deep_work"
        else:
            arc = "building"
        return TemporalFrame(
            recency=_clamp(1.0 - min(duration, 300.0) / 300.0),
            duration=_clamp(duration / 300.0),
            rhythm=rhythm,  # type: ignore[arg-type]
            recurrence=repeat,
            session_arc=arc,  # type: ignore[arg-type]
            unfinished_time_pressure=_clamp(0.35 if "unfinished" in old_notes else 0.0),
            meaning_debt=_clamp(0.45 if "correction" in old_notes else 0.0),
            waiting_pressure=_clamp(idle / 600.0),
            repetition_fatigue=_clamp(repeat * 0.75),
        )

    def spatial(self, frame: Any, *, snapshot: Any = None, legacy_frame: Any = None) -> SpatialFrame:
        x = float(_first(snapshot, ("inferred_pos_x", "body_x", "position_x"), 0.5) or 0.5)
        x = max(0.0, min(1.0, x))
        active = str(_first(snapshot, ("active_window", "active_app", "focus_summary"), "") or "").strip()
        idle = float(_first(snapshot, ("idle_seconds",), 0.0) or 0.0)
        posture = "idle" if idle >= 30 else "attentive"
        relation = "parallel" if active else "unknown"
        return SpatialFrame(
            body_position=(x, 0.5),
            gaze_target=active or ("user" if _get(frame, "channel", "") == "chat" else None),
            posture=posture,  # type: ignore[arg-type]
            distance_to_focus=0.35 if active else 0.5,
            shared_space_relation=relation,  # type: ignore[arg-type]
            approach_affordance=0.55 if idle < 15 else 0.30,
            withdrawal_affordance=0.35 if idle < 15 else 0.60,
            body_interaction_meaning="attend_to_active_focus" if active else None,
        )

    def homeostasis(self, frame: Any, *, legacy_frame: Any = None) -> HomeostaticState:
        state = _first(legacy_frame, ("internal_state_before", "internal_state_after"), None)
        energy = _clamp(_first(state, ("energy", "energy_budget", "vitality"), 0.65), 0.65)
        cognitive_load = _clamp(_first(state, ("cognitive_load", "cognitive_tension", "load"), 0.25), 0.25)
        social_load = _clamp(_first(state, ("social_load", "social_pressure"), 0.20), 0.20)
        exposure = _clamp(_first(state, ("exposure_load", "exposure_recoil"), 0.10), 0.10)
        curiosity = _clamp(_first(state, ("curiosity_pressure", "curiosity"), 0.25), 0.25)
        attachment = _clamp(_first(state, ("attachment_pressure", "attachment"), 0.15), 0.15)
        irritation = _clamp(_first(state, ("irritation_pressure", "irritation"), 0.05), 0.05)
        tenderness = _clamp(_first(state, ("tenderness_pressure", "tenderness"), 0.10), 0.10)
        silence_need = _clamp(max(0.0, cognitive_load - 0.55) + max(0.0, social_load - 0.60))
        speech_cost = _clamp(0.15 + cognitive_load * 0.45 + social_load * 0.25)
        readiness = _clamp(energy * (1.0 - cognitive_load * 0.55))
        if irritation > 0.72 and _get(frame, "channel", "") == "chat":
            policy = "short_grounded"
        elif cognitive_load > 0.78:
            policy = "short_grounded"
        elif social_load > 0.78:
            policy = "reduce_speech"
        elif exposure > 0.78:
            policy = "withdraw"
        elif _get(frame, "channel", "") == "chat":
            policy = "act_practically"
        else:
            policy = "normal"
        return HomeostaticState(
            energy_budget=energy,
            cognitive_load=cognitive_load,
            social_load=social_load,
            exposure_load=exposure,
            curiosity_pressure=curiosity,
            attachment_pressure=attachment,
            irritation_pressure=irritation,
            tenderness_pressure=tenderness,
            silence_recovery_need=silence_need,
            speech_cost=speech_cost,
            action_readiness=readiness,
            regulation_policy=policy,  # type: ignore[arg-type]
        )

    def affect(self, frame: Any, homeostasis: HomeostaticState, *, legacy_frame: Any = None) -> AffectiveState:
        state = _first(legacy_frame, ("internal_state_before", "internal_state_after"), None)
        arousal = _clamp(_first(state, ("arousal",), 0.30), 0.30)
        tension = _clamp(_first(state, ("tension", "cognitive_tension"), homeostasis.cognitive_load), homeostasis.cognitive_load)
        restraint = _clamp(_first(state, ("restraint", "restraint_pressure"), 0.45), 0.45)
        continuity = _clamp(_first(state, ("continuity_anxiety", "continuity_pressure"), 0.10), 0.10)
        return AffectiveState(
            energy=homeostasis.energy_budget,
            fatigue=_clamp(1.0 - homeostasis.energy_budget),
            arousal=arousal,
            tension=tension,
            curiosity=homeostasis.curiosity_pressure,
            restraint=restraint,
            attachment_pressure=homeostasis.attachment_pressure,
            irritation=homeostasis.irritation_pressure,
            tenderness=homeostasis.tenderness_pressure,
            exposure_recoil=homeostasis.exposure_load,
            continuity_anxiety=continuity,
            affective_residue={
                "tension": tension,
                "irritation": homeostasis.irritation_pressure,
                "tenderness": homeostasis.tenderness_pressure,
            },
        )

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
        salience = _get(frame, "salience", None)
        contradiction = 0.0
        for ev in _get(frame, "evidence", []) or []:
            tags = {str(x).lower() for x in (_get(ev, "tags", []) or [])}
            if "contradiction" in tags or "correction" in tags:
                contradiction = max(contradiction, _confidence(ev, 0.5))
        user_rel = _clamp(_first(salience, ("user_relevance", "broadcast_priority"), 0.5), 0.5)
        gap = max(meaning.ambiguity, 1.0 - meaning.confidence)
        intrusion = _clamp(tom.global_overread_risk * 0.7 + 0.15)
        return EpistemicDrive(
            curiosity_pressure=_clamp(_get(_get(frame, "homeostasis", None), "curiosity_pressure", 0.2), 0.2),
            knowledge_gap=_clamp(gap),
            contradiction_pressure=contradiction,
            worldview_tension=_clamp(contradiction * 0.5),
            user_relevance=user_rel,
            identity_relevance=_clamp(_first(salience, ("identity_relevance",), 0.0)),
            inquiry_urgency=_clamp(gap * user_rel + contradiction * 0.45),
            intrusion_risk=intrusion,
        )

    def inquiry(self, frame: Any, drive: EpistemicDrive, meaning: CanonicalMeaningReport) -> InquiryPlan:
        text = str(_get(frame, "user_text", "") or "").lower()
        asks_current = any(marker in text for marker in ("mới nhất", "hiện tại", "hôm nay", "latest", "current", "giá bao nhiêu"))
        if drive.intrusion_risk > 0.65 and drive.knowledge_gap < 0.75:
            action = "suppress_inquiry"
            reason = "Overread/intrusion risk cao hơn giá trị câu hỏi phụ."
        elif asks_current and drive.knowledge_gap > 0.45:
            action = "search_web"
            reason = "Yêu cầu có dấu hiệu phụ thuộc dữ liệu hiện tại."
        elif meaning.needs_clarification:
            action = "ask_user"
            reason = "Nghĩa chi phối chưa đủ chắc để cam kết hành động."
        elif drive.contradiction_pressure > 0.55:
            action = "compare_patterns"
            reason = "Có contradiction/correction cần đối chiếu."
        elif drive.knowledge_gap > 0.55:
            action = "search_memory"
            reason = "Thiếu context nhưng chưa cần làm phiền user."
        else:
            action = "infer_quietly"
            reason = "Đủ evidence để tiếp tục mà không đào sâu thêm."
        return InquiryPlan(
            action=action,  # type: ignore[arg-type]
            reason=reason,
            expected_value=_clamp(drive.inquiry_urgency),
            privacy_cost=_clamp(drive.intrusion_risk),
            interruption_cost=0.35 if action == "ask_user" else 0.05,
        )

    def memory_packet(self, frame: Any, *, legacy_frame: Any = None) -> CanonicalMemoryPacket:
        workspace = _get(frame, "workspace", None)
        selected = [str(x) for x in (_get(workspace, "selected_memory", []) or []) if str(x).strip()]
        resonance = _get(legacy_frame, "memory_resonance", None)
        episodic = list(selected)
        semantic: list[str] = []
        relational: list[str] = []
        for attr, target in (("episodic", episodic), ("semantic", semantic), ("relational", relational)):
            values = _get(resonance, attr, []) or []
            if isinstance(values, str):
                values = [values]
            target.extend(str(x) for x in values if str(x).strip())
        budget = {"fast": 180, "normal": 420, "deep": 760, "reflection": 620}.get(str(_get(frame, "budget_mode", "normal")), 420)
        return CanonicalMemoryPacket(
            episodic=list(dict.fromkeys(episodic))[:6],
            semantic=list(dict.fromkeys(semantic))[:6],
            relational=list(dict.fromkeys(relational))[:4],
            confidence_notes=["Chỉ memory đã qua GlobalWorkspace được surface vào packet."],
            token_budget=budget,
        )

    def belief(self, frame: Any, meaning: CanonicalMeaningReport) -> BeliefReport:
        active: list[Belief] = []
        candidates: list[Belief] = []
        contradictions: list[str] = []
        for ev in (_get(frame, "evidence", []) or [])[:12]:
            claim = _summary(ev)
            if not claim:
                continue
            eid = str(_first(ev, ("id", "evidence_id"), ""))
            conf = _confidence(ev, 0.5)
            raw = str(_get(ev, "raw_or_inferred", "raw")) == "raw"
            belief = Belief(
                id=f"belief:{eid or hashlib.sha1(claim.encode('utf-8')).hexdigest()[:10]}",
                claim=claim,
                domain="user" if str(_get(ev, "source", "")) == "user_chat" else "world",
                confidence=conf,
                source_ids=[eid] if eid else [],
                status="active" if raw and conf >= 0.72 else "tentative",
            )
            (active if belief.status == "active" else candidates).append(belief)
            tags = {str(x).lower() for x in (_get(ev, "tags", []) or [])}
            if "contradiction" in tags:
                contradictions.append(claim)
        open_questions = []
        if meaning.needs_clarification:
            open_questions.append("Ý định chính của user còn mơ hồ; cần clarification hoặc hành động reversible.")
        return BeliefReport(active_beliefs=active, candidate_beliefs=candidates, contradictions=contradictions, open_questions=open_questions)

    def relation(self, frame: Any, *, legacy_frame: Any = None) -> RelationalState:
        state = _first(legacy_frame, ("internal_state_before", "internal_state_after"), None)
        rel = _first(state, ("relationship_dynamics", "relationship_state"), None)
        trust = _clamp(_first(rel, ("trust", "trust_score"), 0.5), 0.5)
        familiarity = _clamp(_first(rel, ("familiarity", "familiarity_score", "closeness"), 0.5), 0.5)
        rupture = _clamp(_first(rel, ("rupture", "rupture_score", "distance_pressure"), 0.0), 0.0)
        repair = _clamp(_first(rel, ("repair_need", "repair_pressure"), rupture), rupture)
        return RelationalState(
            trust=trust,
            familiarity=familiarity,
            rupture=rupture,
            repair_need=repair,
            preferred_distance=_clamp(0.65 - familiarity * 0.35 + rupture * 0.25),
            attachment_visibility=_clamp(_first(rel, ("attachment_visibility",), familiarity * 0.35), familiarity * 0.35),
            dignity_defense=_clamp(_first(rel, ("dignity_defense",), 0.55), 0.55),
            teasing_permission=_clamp(trust * 0.55 + familiarity * 0.25 - rupture * 0.8),
            privacy_sensitivity=_clamp(_first(rel, ("privacy_sensitivity",), 0.55), 0.55),
            overread_correction=_clamp(_first(rel, ("overread_correction",), 0.55), 0.55),
            user_specific_rhythm=str(_first(rel, ("user_specific_rhythm", "last_event"), "unknown") or "unknown"),
            cultural_boundary=0.5,
        )

    def permission(self, frame: Any, tom: CanonicalTheoryOfMindReport, relation: RelationalState, inquiry: InquiryPlan) -> PermissionReport:
        evidence = list(_get(frame, "evidence", []) or [])
        privacy_levels = {str(_get(ev, "privacy_level", "normal")) for ev in evidence}
        sensitive = bool(privacy_levels & {"private", "sensitive"})
        overread = tom.global_overread_risk
        max_intensity = _clamp(0.72 - overread * 0.38 - relation.rupture * 0.22)
        allowed_search = inquiry.action == "search_web" and not sensitive
        allowed_tease = relation.teasing_permission >= 0.45 and relation.rupture < 0.30 and overread < 0.55
        public = not (sensitive and _get(frame, "channel", "") != "chat")
        return PermissionReport(
            public_sayable=public,
            prompt_sayable=not sensitive,
            memory_storable=not sensitive,
            raw_evidence_storable=False,
            allowed_reaction=["answer", "clarify", "practical_help", "repair"] + (["tease"] if allowed_tease else []),
            allowed_body_action=["none", "face_user", "look_at_focus", "stillness", "idle_shift"],
            allowed_search=allowed_search,
            allowed_tease=allowed_tease,
            allowed_proactivity=relation.trust > 0.62 and relation.rupture < 0.20,
            max_intensity=max_intensity,
            reason="Giới hạn theo privacy, overread risk và trạng thái quan hệ; permission chỉ thu hẹp action space.",
        )

    def values(self, frame: Any, inquiry: InquiryPlan, permission: PermissionReport, relation: RelationalState) -> ValueResolutionReport:
        conflicts: list[ValueConflict] = []
        if inquiry.action in {"ask_user", "search_web"} and inquiry.privacy_cost > 0.45:
            conflicts.append(ValueConflict("privacy_conflict", ["curiosity", "privacy"], inquiry.privacy_cost, "privacy thắng; giảm hoặc hoãn inquiry"))
        if relation.repair_need > 0.45:
            conflicts.append(ValueConflict("relational_conflict", ["dignity", "relationship_trust"], relation.repair_need, "acknowledge ngắn rồi sửa hành vi"))
        winner = "privacy" if any(c.conflict_type == "privacy_conflict" for c in conflicts) else "truthfulness"
        return ValueResolutionReport(
            conflicts=conflicts,
            winning_value=winner,
            suppressed_values=["dramatic_effect"] + (["curiosity"] if winner == "privacy" else []),
            max_allowed_intensity=permission.max_intensity,
            reason="Grounding và autonomy được ưu tiên; continuity chỉ thắng khi vô hại.",
        )

    def simulations(self, frame: Any, inquiry: InquiryPlan, permission: PermissionReport, relation: RelationalState) -> list[SimulatedActionOutcome]:
        channel = str(_get(frame, "channel", "") or "")
        chat = channel == "chat"
        actions = ["practical_help", "ask", "stay_silent", "body_only"]
        if permission.allowed_search:
            actions.append("search")
        result: list[SimulatedActionOutcome] = []
        for action in actions:
            usefulness = {
                "practical_help": 0.92 if chat else 0.45,
                "ask": 0.75 if inquiry.action == "ask_user" else 0.42,
                "search": 0.82,
                "stay_silent": 0.15 if chat else 0.68,
                "body_only": 0.10 if chat else 0.55,
            }.get(action, 0.4)
            social_risk = 0.12 if action == "practical_help" else (0.35 if action == "ask" else 0.08)
            privacy_risk = inquiry.privacy_cost if action in {"ask", "search"} else 0.02
            relationship_cost = 0.55 if chat and action in {"stay_silent", "body_only"} else social_risk * 0.4
            continuity_gain = 0.72 if action == "practical_help" else (0.48 if action == "stay_silent" else 0.42)
            result.append(SimulatedActionOutcome(
                action_type=action,
                expected_user_reaction="nhận được tiến triển cụ thể" if action == "practical_help" else "phản ứng phụ thuộc ngữ cảnh",
                usefulness=_clamp(usefulness),
                social_risk=_clamp(social_risk + relation.rupture * 0.2),
                privacy_risk=_clamp(privacy_risk),
                relationship_cost=_clamp(relationship_cost),
                continuity_gain=_clamp(continuity_gain),
                confidence=0.72,
            ))
        return result

    def arbitration(self, simulations: list[SimulatedActionOutcome], inquiry: InquiryPlan, permission: PermissionReport) -> ArbitrationResult:
        def utility(item: SimulatedActionOutcome) -> float:
            return item.usefulness + item.continuity_gain * 0.45 - item.social_risk * 0.55 - item.privacy_risk * 0.8 - item.relationship_cost * 0.5
        allowed = [x for x in simulations if not (x.action_type == "search" and not permission.allowed_search)]
        winner = max(allowed, key=utility, default=None)
        action = winner.action_type if winner else "stay_silent"
        drive_map = {"practical_help": "practical_help", "ask": "curiosity", "search": "knowledge_acquisition", "stay_silent": "restraint", "body_only": "presence"}
        winning_drive = drive_map.get(action, action)
        return ArbitrationResult(
            competing_drives=[drive_map.get(x.action_type, x.action_type) for x in allowed],
            winning_drive=winning_drive,
            suppressed_drives=[drive_map.get(x.action_type, x.action_type) for x in allowed if x is not winner],
            compromise_action="answer_directly_no_intrusive_probe" if action == "practical_help" and inquiry.privacy_cost > 0.35 else action,
            reason=f"Utility cao nhất sau risk/privacy/relationship cost: {action}.",
            confidence=_clamp(winner.confidence if winner else 0.3),
        )

    def agency(self, arbitration: ArbitrationResult, inquiry: InquiryPlan) -> ActionCommitment:
        mapping = {"practical_help": "speak", "curiosity": "ask", "knowledge_acquisition": "search", "restraint": "stay_silent", "presence": "body_only"}
        intent = mapping.get(arbitration.winning_drive, "speak")
        return ActionCommitment(
            intent=intent,  # type: ignore[arg-type]
            goal_preserved="giải quyết yêu cầu hiện tại mà không overread",
            commitment_strength=arbitration.confidence,
            reversibility=0.95 if intent in {"ask", "stay_silent", "body_only"} else 0.72,
            reason=arbitration.reason,
        )

    def noise(self, frame: Any) -> NoiseFrame:
        seed = hashlib.sha256(str(_get(frame, "frame_id", "")).encode("utf-8")).digest()
        vals = [(b / 255.0) * 0.12 for b in seed[:7]]
        return NoiseFrame(*vals)

    def speech_opportunity(self, frame: Any, agency: ActionCommitment, homeostasis: HomeostaticState, permission: PermissionReport) -> SpeechOpportunity:
        channel = str(_get(frame, "channel", "") or "")
        if not permission.public_sayable:
            return SpeechOpportunity(mode="silence", speech_allowed=False, reason_to_stay_silent="Privacy boundary chặn public surface.", urgency=0.0, interruption_cost=0.0)
        if agency.intent == "stay_silent":
            return SpeechOpportunity(mode="silence", speech_allowed=False, reason_to_stay_silent="Arbitration chọn restraint.", urgency=0.1, interruption_cost=0.0)
        if agency.intent == "body_only":
            return SpeechOpportunity(mode="body_only_reaction", speech_allowed=False, reason_to_stay_silent="Body-only presence có utility cao hơn speech.", urgency=0.2, interruption_cost=0.0)
        mode = "direct_answer" if channel == "chat" else "reengagement"
        if homeostasis.regulation_policy in {"short_grounded", "reduce_speech"}:
            mode = "practical_help"
        return SpeechOpportunity(
            mode=mode,  # type: ignore[arg-type]
            speech_allowed=True,
            reason_to_speak="Có yêu cầu trực tiếp và practical utility cao.",
            reason_to_stay_silent="Speech cost/interrupt cost có thể thắng nếu state xấu đi.",
            urgency=_clamp(0.7 if channel == "chat" else 0.35),
            interruption_cost=_clamp(homeostasis.speech_cost * (0.25 if channel == "chat" else 0.75)),
        )

    def speech_plan(self, frame: Any, opportunity: SpeechOpportunity, meaning: CanonicalMeaningReport, relation: RelationalState, permission: PermissionReport) -> SpeechPlan:
        text = str(_get(frame, "user_text", "") or "").strip().lower()
        technical = any(x in text for x in ("code", "file", "fix", "lỗi", "bug", "repo", "src", "pipeline", "kiến trúc", "json", "python"))
        correction = any(x in text for x in ("không phải", "chưa", "sai", "tôi nhớ là", "ý tôi"))
        if not opportunity.speech_allowed:
            act = "compress"
        elif correction or relation.repair_need > 0.48:
            act = "repair"
        elif meaning.needs_clarification:
            act = "clarify"
        elif technical:
            act = "technical_diagnosis"
        else:
            act = "answer"
        return SpeechPlan(
            speech_act=act,  # type: ignore[arg-type]
            tone="cold_soft" if relation.rupture < 0.4 else "restrained_repair",
            warmth=_clamp(0.20 + relation.trust * 0.32),
            restraint=_clamp(0.35 + (1.0 - permission.max_intensity) * 0.55),
            directness=0.90 if technical or correction else 0.72,
            tease_level=0.18 if permission.allowed_tease and not technical and not correction else 0.0,
            technical_depth=0.88 if technical else 0.35,
            emotional_visibility=_clamp(relation.attachment_visibility * 0.55),
            must_include=["answer-first", "state uncertainty where needed"] + (["acknowledge correction"] if correction else []),
            must_avoid=list(_get(_get(frame, "tom", None), "forbidden_assumptions", []) or []) + ["unsupported current-state claims"],
        )

    def body_plan(self, frame: Any, opportunity: SpeechOpportunity, spatial: SpatialFrame, permission: PermissionReport) -> BodyActionPlan:
        if not permission.allowed_body_action:
            return BodyActionPlan()
        if opportunity.mode == "silence":
            action = "stillness"
        elif spatial.gaze_target and spatial.gaze_target != "user":
            action = "look_at_focus"
        elif str(_get(frame, "channel", "")) == "chat":
            action = "face_user"
        else:
            action = "idle_shift"
        return BodyActionPlan(
            action=action,  # type: ignore[arg-type]
            gaze_target=spatial.gaze_target,
            posture="attentive" if opportunity.speech_allowed else "neutral",
            movement=action,
            intensity=0.35 if opportunity.speech_allowed else 0.15,
            timing_delay_ms=80 if opportunity.speech_allowed else 180,
        )

    def modality(self, speech: SpeechPlan, body: BodyActionPlan, spatial: SpatialFrame, permission: PermissionReport, *, system_action: str = "") -> ModalitySyncFrame:
        notes: list[str] = []
        contradiction = 0.0
        if speech.speech_act in {"support", "repair"} and body.action in {"withdraw", "turn_away_softly"}:
            contradiction = 0.72
            notes.append("Repair/support không được đi cùng withdrawal mạnh.")
        if body.action not in permission.allowed_body_action:
            contradiction = max(contradiction, 0.85)
            notes.append("Body action ngoài permission; fallback stillness.")
            body = BodyActionPlan(action="stillness", posture="neutral", intensity=0.1)
        safety = _clamp(1.0 - spatial.obstruction_risk)
        return ModalitySyncFrame(
            speech_plan=speech,
            body_plan=body,
            system_action=system_action or None,
            emotional_congruence=_clamp(1.0 - contradiction * 0.65),
            spatial_safety=safety,
            contradiction_risk=contradiction,
            final_delay_ms=max(0, int(body.timing_delay_ms)),
            correction_notes=notes,
        )

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
        lines = ["[V3_COGNITIVE_PLAN]"]
        if dominant:
            lines.append(f"meaning={dominant[:180]}")
        lines.append(f"meaning_confidence={_get(meaning, 'confidence', 0.0):.2f}; ambiguity={_get(meaning, 'ambiguity', 1.0):.2f}")
        lines.append(f"tom_confidence={_get(tom, 'global_confidence', 0.0):.2f}; overread_risk={_get(tom, 'global_overread_risk', 1.0):.2f}")
        lines.append(f"agency={_get(agency, 'intent', 'observe')}; speech_allowed={bool(_get(opportunity, 'speech_allowed', False))}; mode={_get(opportunity, 'mode', 'silence')}")
        lines.append(f"speech_act={_get(speech, 'speech_act', 'answer')}; tone={_get(speech, 'tone', 'cold_soft')}; directness={_get(speech, 'directness', 0.7):.2f}; technical_depth={_get(speech, 'technical_depth', 0.3):.2f}")
        lines.append(f"max_intensity={_get(permission, 'max_intensity', 0.5):.2f}; allowed_tease={bool(_get(permission, 'allowed_tease', False))}")
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
