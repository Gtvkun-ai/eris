from dataclasses import dataclass, field


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

    def to_machine_context(self) -> dict[str, object]:
        context: dict[str, object] = {
            "time": self.captured_at,
            "active_app": self.active_app or self.active_window,
            "idle_seconds": int(self.idle_seconds),
            "recent_events": list(self.recent_events),
            "user_signals": self.user_signals.to_dict(),
            "evidence": list(self.evidence),
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
