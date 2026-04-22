from dataclasses import dataclass


@dataclass(slots=True)
class Decision:
    text: str
    animation: str
    extracted_fact: str = ""
    direction: int = 0
    next_animation: str = ""
    target_x: float = -1.0
    bounce_action: str = ""
    debug_trace: str = ""
    parser_trace: str = ""
    parse_mode: str = "json"
    system_action: str = ""
    action_input: str = ""

    def to_payload(self) -> dict:
        return {
            "text": self.text,
            "animation": self.animation,
            "direction": self.direction,
            "target_x": self.target_x,
            "bounce_action": self.bounce_action,
            "next_animation": self.next_animation,
            "debug_trace": self.debug_trace,
            "parser_trace": self.parser_trace,
            "parse_mode": self.parse_mode,
            "system_action": self.system_action,
            "action_input": self.action_input,
        }
