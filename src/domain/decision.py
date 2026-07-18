from dataclasses import dataclass
from typing import Any
import re

from failure_meta import normalize_failure_meta


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
    # Gợi ý sân khấu do LLM khai có cấu trúc. Không nhét "(cười khẽ)" vào text.
    delivery_hint: str = ""    # ví dụ: dry_tease, soft_tease, focused, low_quiet
    nonverbal_cue: str = ""    # ví dụ: laugh_soft, small_smile, sigh_soft
    stage_motion: str = ""     # ví dụ: look_away, tilt_head, blink_slow
    # Metadata audio preset. Các field này do runtime gắn, không yêu cầu LLM sinh.
    speech_act: str = ""
    preset_id: str = ""
    audio_asset: str = ""
    preset_emotion: str = ""
    failure_meta: dict[str, Any] | None = None
    # Dấu niêm phong của DirectorGenerationPipeline. Khi True, coordinator không
    # được chấm/repair lại cùng một câu ở precommit hoặc stage output.
    director_finalized: bool = False
    director_trace_id: str = ""
    director_meta: dict[str, Any] | None = None
    # Con dấu public cuối cùng. Director/guard có thể còn đánh giá candidate,
    # nhưng sau khi FinalSpeechAuthority khóa thì các tầng delivery chỉ được đọc.
    # Nếu một module hậu kỳ lỡ sửa câu, runtime sẽ phát hiện và khôi phục snapshot
    # đã khóa thay vì để một câu "ma" chui ra UI/TTS.
    final_speech_locked: bool = False
    final_speech_digest: str = ""
    final_speech_meta: dict[str, Any] | None = None
    # Bằng chứng action: request_sent khác observed_success.
    action_result_meta: dict[str, Any] | None = None
    # Tín hiệu quan sát hậu quả hành vi. Không phải guard và không có quyền sửa text.
    # Runtime dùng block này cho audit + context mềm ở lượt kế tiếp.
    behavior_observation_meta: dict[str, Any] | None = None

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
        payload = {
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
            "delivery_hint": self.delivery_hint,
            "nonverbal_cue": self.nonverbal_cue,
            "stage_motion": self.stage_motion,
            "speech_act": self.speech_act,
            "preset_id": self.preset_id,
            "audio_asset": self.audio_asset,
            "preset_emotion": self.preset_emotion,
        }
        payload["director_finalized"] = bool(self.director_finalized)
        payload["final_speech_locked"] = bool(self.final_speech_locked)
        if self.final_speech_digest:
            payload["final_speech_digest"] = self.final_speech_digest
        if self.director_trace_id:
            payload["director_trace_id"] = self.director_trace_id
        if self.action_result_meta:
            payload["action_result"] = dict(self.action_result_meta)
        # Không gửi toàn bộ observation journal sang Godot; chỉ expose summary gọn
        # khi cần debug panel. Semantic text vẫn là text đã khóa.
        if isinstance(self.behavior_observation_meta, dict):
            signals = [
                item for item in self.behavior_observation_meta.get("signals", ())
                if isinstance(item, dict)
            ]
            if signals:
                payload["behavior_observation"] = {
                    "policy": self.behavior_observation_meta.get("policy", "observe_only"),
                    "families": [str(item.get("family", "unknown")) for item in signals[-8:]],
                    "count": len(signals),
                }
        failure_meta = normalize_failure_meta(self.failure_meta)
        if failure_meta is not None:
            payload["failure_meta"] = failure_meta
        return payload
