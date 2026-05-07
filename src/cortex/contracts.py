from dataclasses import dataclass, field

from .internal_state import PersistentInternalState


@dataclass(slots=True)
class UserSignals:
    typing_speed: str = "unknown"
    window_switching: str = "unknown"
    focus_pattern: str = "unknown"

    def to_dict(self) -> dict[str, str]:
        return {
            "typing_speed": self.typing_speed,
            "window_switching": self.window_switching,
            "focus_pattern": self.focus_pattern,
        }


@dataclass(slots=True)
class TelemetrySnapshot:
    captured_at: str
    active_window: str
    active_window_kind: str
    focus_summary: str
    active_app: str = ""
    browser_url: str = ""
    browser_tabs: tuple[str, ...] = ()
    open_windows: tuple[str, ...] = ()
    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    mood_score: int = 50
    mood_label: str = "neutral"
    inferred_pos_x: float = 0.5
    position_label: str = "center"
    idle_seconds: float = 0.0
    idle_label: str = "active"
    recent_events: tuple[str, ...] = ()
    user_signals: UserSignals = field(default_factory=UserSignals)
    evidence: tuple[str, ...] = ()
    claim_style: str = "soft_grounded"
    vision_facts: tuple[str, ...] = ()

    def to_machine_context(self) -> dict[str, object]:
        context: dict[str, object] = {
            "time": self.captured_at,
            "active_app": self.active_app or self.active_window,
            "idle_seconds": int(self.idle_seconds),
            "recent_events": list(self.recent_events),
            "user_signals": self.user_signals.to_dict(),
            "evidence": list(self.evidence),
            "vision_facts": list(self.vision_facts),
            "claim_style": self.claim_style,
            "active_window_kind": self.active_window_kind,
            "focus_summary": self.focus_summary,
            "browser_url": self.browser_url,
            "browser_tabs": list(self.browser_tabs),
            "open_windows": list(self.open_windows),
            "cpu_percent": round(self.cpu_percent, 1),
            "ram_percent": round(self.ram_percent, 1),
            "mood_score": self.mood_score,
            "mood_label": self.mood_label,
            "inferred_pos_x": round(self.inferred_pos_x, 3),
            "position_label": self.position_label,
            "idle_label": self.idle_label,
        }
        return context


@dataclass(slots=True)
class GoalDriftReport:
    similarity: float
    drift_score: float
    drift_level: str
    confidence: float = 0.0
    should_raise_guard: bool = False
    reason_span: str = ""
    prompt_context: str = ""
    evidence: tuple[str, ...] = ()
    vector_method: str = "attention_signal_local"


@dataclass(slots=True)
class TiPolicyReport:
    mode: str
    focus_label: str
    reason: str
    prompt_context: str
    hard_rules: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    animation_hint: str = "stand"
    direction_hint: int = 0
    target_x_hint: float = -1.0
    motion_intent_hint: str = ""
    motion_facing_hint: int = 0
    motion_target_x_hint: float = -1.0
    force_animation: bool = False
    allow_idle_variation: bool = True


@dataclass(slots=True)
class FeStylePlan:
    mode: str
    tone_label: str
    style_context: str
    intent_label: str = "ordinary_dialogue"
    session_arc: str = "quiet_observation"
    transition_note: str = ""
    evidence: tuple[str, ...] = ()
    sarcasm_level: float = 0.0
    warmth_level: float = 0.0
    brevity_bias: str = "medium"


@dataclass(slots=True)
class FeStyleMemory:
    recent_modes: tuple[str, ...] = ()
    recent_tones: tuple[str, ...] = ()
    recent_intents: tuple[str, ...] = ()
    recent_topic_tags: tuple[str, ...] = ()
    last_mode: str = ""
    last_tone_label: str = ""
    last_intent: str = ""
    last_response_excerpt: str = ""
    repeated_topic_tag: str = ""
    repeated_topic_streak: int = 0
    session_arc: str = "quiet_observation"
    sarcasm_level: float = 0.30
    warmth_level: float = 0.25
    brevity_bias: str = "medium"
    continuity_strength: float = 0.0
    session_turn_count: int = 0
    arc_strength: float = 0.0
    technical_pull: float = 0.20
    discipline_pull: float = 0.20
    attachment_pull: float = 0.20
    neutral_pull: float = 0.20


@dataclass(slots=True)
class PerceptEvent:
    kind: str
    content: str
    evidence: tuple[str, ...] = ()
    confidence: float = 1.0
    source: str = "runtime"
    timestamp: str = ""
    privacy_level: str = "internal"
    novelty_hint: str = "routine"

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "content": self.content,
            "evidence": list(self.evidence),
            "confidence": round(float(self.confidence), 3),
            "source": self.source,
            "timestamp": self.timestamp,
            "privacy_level": self.privacy_level,
            "novelty_hint": self.novelty_hint,
        }


CognitivePercept = PerceptEvent


@dataclass(slots=True)
class AttentionCandidate:
    label: str
    content: str
    score: float
    source: str = "runtime"
    reason: str = ""
    evidence: tuple[str, ...] = ()
    privacy_level: str = "internal"
    novelty_hint: str = "routine"
    score_parts: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "content": self.content,
            "score": round(float(self.score), 3),
            "source": self.source,
            "reason": self.reason,
            "evidence": list(self.evidence),
            "privacy_level": self.privacy_level,
            "novelty_hint": self.novelty_hint,
            "score_parts": {
                key: round(float(value), 3)
                for key, value in self.score_parts.items()
            },
        }


@dataclass(slots=True)
class CognitiveBroadcast:
    label: str = ""
    content: str = ""
    score: float = 0.0
    source: str = ""
    reason: str = ""
    evidence: tuple[str, ...] = ()
    items: tuple[AttentionCandidate, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "content": self.content,
            "score": round(float(self.score), 3),
            "source": self.source,
            "reason": self.reason,
            "evidence": list(self.evidence),
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(slots=True)
class CognitiveAppraisal:
    state_type: str = "expressive_appraisal_state"
    stance: str = "grounded"
    valence: float = 0.0
    arousal: float = 0.0
    certainty: float = 0.0
    agency: float = 0.0
    controllability: float = 0.0
    intimacy: float = 0.0
    threat: float = 0.0
    protectiveness: float = 0.0
    jealousy_lite: float = 0.0
    amusement: float = 0.0
    fatigue: float = 0.0
    tenderness: float = 0.0
    summary: str = ""
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "state_type": self.state_type,
            "stance": self.stance,
            "valence": round(float(self.valence), 3),
            "arousal": round(float(self.arousal), 3),
            "certainty": round(float(self.certainty), 3),
            "agency": round(float(self.agency), 3),
            "controllability": round(float(self.controllability), 3),
            "intimacy": round(float(self.intimacy), 3),
            "threat": round(float(self.threat), 3),
            "protectiveness": round(float(self.protectiveness), 3),
            "jealousy_lite": round(float(self.jealousy_lite), 3),
            "amusement": round(float(self.amusement), 3),
            "fatigue": round(float(self.fatigue), 3),
            "tenderness": round(float(self.tenderness), 3),
            "summary": self.summary,
            "evidence": list(self.evidence),
        }


@dataclass(slots=True)
class CognitiveActionPlan:
    should_speak: bool = False
    speech_intent: str = "no_speech"
    speech_act: str = "no_speech"
    reason_to_speak: str = ""
    reason: str = ""
    animation_hint: str = "stand"
    system_action: str = ""
    risk_flags: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        reason = self.reason_to_speak or self.reason
        return {
            "should_speak": self.should_speak,
            "speech_intent": self.speech_intent,
            "speech_act": self.speech_act,
            "reason_to_speak": reason,
            "reason": reason,
            "animation_hint": self.animation_hint,
            "system_action": self.system_action,
            "risk_flags": list(self.risk_flags),
            "notes": list(self.notes),
        }


@dataclass(slots=True)
class InnerThought:
    intent: str = ""
    motive: str = ""
    topic_seed: str = ""
    evidence_anchor: str = ""
    certainty: float = 0.0
    should_surface: bool = False
    risk_flags: tuple[str, ...] = ()
    cooldown_seconds: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent,
            "motive": self.motive,
            "topic_seed": self.topic_seed,
            "evidence_anchor": self.evidence_anchor,
            "certainty": round(float(self.certainty), 3),
            "should_surface": self.should_surface,
            "risk_flags": list(self.risk_flags),
            "cooldown_seconds": int(self.cooldown_seconds),
        }


@dataclass(slots=True)
class AgentSpeechCore:
    perception: tuple[str, ...] = ()
    mood: str = "neutral"
    impulse: str = "silent"
    utterance_type: str = "no_speech"
    grounding: str = "none"
    speech_source: str = "none"
    reason: str = ""
    should_speak: bool = False
    safety_flags: tuple[str, ...] = ()
    delivery: str = "silence"
    inner_thought: InnerThought = field(default_factory=InnerThought)

    def to_dict(self) -> dict[str, object]:
        return {
            "perception": list(self.perception),
            "mood": self.mood,
            "impulse": self.impulse,
            "utterance_type": self.utterance_type,
            "grounding": self.grounding,
            "speech_source": self.speech_source,
            "reason": self.reason,
            "should_speak": self.should_speak,
            "safety_flags": list(self.safety_flags),
            "delivery": self.delivery,
            "inner_thought": self.inner_thought.to_dict(),
        }


@dataclass(slots=True)
class CognitiveMemoryUpdate:
    remembered_fact: str = ""
    remembered_style_excerpt: str = ""
    last_text: str = ""
    system_action: str = ""
    notes: tuple[str, ...] = ()
    working_summary: str = ""
    episodic_summary: str = ""
    semantic_fact: str = ""
    norm_deviation: str = ""
    relationship_reflection: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "remembered_fact": self.remembered_fact,
            "remembered_style_excerpt": self.remembered_style_excerpt,
            "last_text": self.last_text,
            "system_action": self.system_action,
            "notes": list(self.notes),
            "working_summary": self.working_summary,
            "episodic_summary": self.episodic_summary,
            "semantic_fact": self.semantic_fact,
            "norm_deviation": self.norm_deviation,
            "relationship_reflection": self.relationship_reflection,
        }


@dataclass(slots=True)
class CognitiveFrame:
    cycle_id: str
    channel: str
    started_at: float
    percepts: tuple[PerceptEvent, ...] = ()
    attention_candidates: tuple[AttentionCandidate, ...] = ()
    broadcast: CognitiveBroadcast = field(default_factory=CognitiveBroadcast)
    appraisal: CognitiveAppraisal = field(default_factory=CognitiveAppraisal)
    speech_core: AgentSpeechCore = field(default_factory=AgentSpeechCore)
    inner_thought: InnerThought = field(default_factory=InnerThought)
    action_plan: CognitiveActionPlan = field(default_factory=CognitiveActionPlan)
    final_decision: dict[str, object] = field(default_factory=dict)
    memory_update: CognitiveMemoryUpdate = field(default_factory=CognitiveMemoryUpdate)
    internal_state_before: PersistentInternalState | None = None
    internal_state_after: PersistentInternalState | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "cycle_id": self.cycle_id,
            "channel": self.channel,
            "started_at": round(float(self.started_at), 3),
            "percepts": [item.to_dict() for item in self.percepts],
            "attention_candidates": [item.to_dict() for item in self.attention_candidates],
            "broadcast": self.broadcast.to_dict(),
            "appraisal": self.appraisal.to_dict(),
            "speech_core": self.speech_core.to_dict(),
            "inner_thought": self.inner_thought.to_dict(),
            "action_plan": self.action_plan.to_dict(),
            "final_decision": dict(self.final_decision),
            "memory_update": self.memory_update.to_dict(),
            "internal_state_before": self.internal_state_before.to_dict() if self.internal_state_before is not None else None,
            "internal_state_after": self.internal_state_after.to_dict() if self.internal_state_after is not None else None,
        }
