from dataclasses import dataclass


@dataclass(slots=True)
class TelemetrySnapshot:
    captured_at: str
    active_window: str
    active_window_kind: str
    focus_summary: str
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


@dataclass(slots=True)
class GoalDriftReport:
    similarity: float
    drift_score: float
    drift_level: str
    prompt_context: str
    evidence: tuple[str, ...] = ()
    should_raise_guard: bool = False
    vector_method: str = "token_cosine_local"


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
