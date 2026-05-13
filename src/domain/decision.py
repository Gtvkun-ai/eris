from dataclasses import dataclass
from typing import Any
import re


@dataclass(slots=True)
class Decision:
    text: str
    animation: str
    extracted_fact: str = ""
    intent: str = ""
    action: Any = ""
    reasoning_tags: tuple[str, ...] = ()
    should_speak: bool = True
    confidence: float = 0.0
    direction: int = 0
    next_animation: str = ""
    target_x: float = -1.0
    bounce_action: str = ""
    debug_trace: str = ""
    parser_trace: str = ""
    parse_mode: str = "json"
    system_action: str = ""
    action_input: str = ""
    motion_intent: str = ""
    motion_target_x: float = -1.0
    motion_facing: int = 0

    def resolve_motion_intent(self) -> str:
        intent = (self.motion_intent or "").strip().lower()
        if intent:
            return intent

        if self.animation == "climb" and self.next_animation == "climb_top":
            return "climb_to_top"
        if self.animation == "climb_top":
            return "climb_to_top"
        if self.animation == "climb":
            return "climb_loop"
        if self.animation in {"air_swing_l", "air_swing_r"}:
            return "drop"
        if 0.0 <= self.target_x <= 1.0:
            return "walk_to"
        if self.animation == "stand_walk":
            return "walk"
        if self.direction in {-1, 1}:
            return "face"
        return ""

    def resolve_motion_target_x(self) -> float:
        if 0.0 <= self.motion_target_x <= 1.0:
            return self.motion_target_x
        if 0.0 <= self.target_x <= 1.0:
            return self.target_x
        return -1.0

    def resolve_motion_facing(self) -> int:
        if self.motion_facing in {-1, 1}:
            return self.motion_facing
        if self.direction in {-1, 1}:
            return self.direction
        if self.animation == "air_swing_l":
            return -1
        if self.animation == "air_swing_r":
            return 1
        return 0

    def _payload_text(self) -> tuple[str, bool]:
        text = str(self.text or "")
        normalized = re.sub(r"\s+", " ", text.strip()).lower()
        if normalized in {"...", "…", "hm", "hm.", "um", "um."}:
            return "", False
        return text, bool(self.should_speak)

    def to_payload(self) -> dict:
        text, should_speak = self._payload_text()
        return {
            "text": text,
            "intent": self.intent,
            "action": self.action,
            "animation": self.animation,
            "reasoning_tags": list(self.reasoning_tags),
            "should_speak": should_speak,
            "confidence": self.confidence,
            "direction": self.direction,
            "target_x": self.target_x,
            "bounce_action": self.bounce_action,
            "next_animation": self.next_animation,
            "debug_trace": self.debug_trace,
            "parser_trace": self.parser_trace,
            "parse_mode": self.parse_mode,
            "system_action": self.system_action,
            "action_input": self.action_input,
            "motion_intent": self.resolve_motion_intent(),
            "motion_target_x": self.resolve_motion_target_x(),
            "motion_facing": self.resolve_motion_facing(),
        }
