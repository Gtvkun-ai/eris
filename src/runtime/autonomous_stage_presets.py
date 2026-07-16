# -*- coding: utf-8 -*-
"""autonomous_stage_presets.py - playbook sân khấu theo scene cho Eris.

Ba phase trước đã giúp Eris biết *khi nào* nên nói, giữ nhịp cả phiên và nối
các câu thành show arc. Tuy nhiên nếu mọi scene dùng chung một ngưỡng, một giọng
và một mật độ, autonomous vẫn cư xử như một MC chỉ thay phông nền.

Module này gom policy theo scene vào một contract versioned, trung tính với
avatar. Preset chỉ nói bằng ý đồ như ``gaze_intent``/``gesture_density`` và
không chứa hotkey Live2D hay blendshape 3D cụ thể.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from runtime.autonomous_opportunity import AutonomousOpportunity
from runtime.autonomous_scene_runtime import SceneRuntimeState


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return max(0.0, min(1.0, default))


@dataclass(frozen=True, slots=True)
class AutonomousStagePreset:
    """Contract policy đã resolve cho một scene cụ thể.

    ``intent_overrides`` và ``performance_overrides`` dùng tuple để object thật
    sự immutable. Khi serialize sang payload chúng mới trở thành dict cho prompt
    và stage planner. Đây là config, không phải một túi dict bị sửa ở năm nơi.
    """

    preset_id: str
    scene_mode: str
    audience_mode: str
    body_first: bool
    allowed_opportunity_kinds: tuple[str, ...]
    min_opportunity_strength: float
    min_gap_ms: int
    max_lines_per_hour: int
    max_words: int
    max_duration_ms: int
    startup_quiet_ms: int
    default_intent: str
    delivery_style: str
    stage_emotion: str
    stage_motion: str
    tts_style: str
    performance_lane: str
    gesture_density: str
    opening_hold_bias_ms: int
    closing_hold_min_ms: int
    public_memory_allowed: bool
    anti_spoiler: bool
    poetic_drift_allowed: bool
    intent_overrides: tuple[tuple[str, str], ...] = ()
    performance_overrides: tuple[tuple[str, tuple[str, str, str, str]], ...] = ()
    surface_rules: tuple[str, ...] = ()
    policy_tags: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_opportunity_kinds"] = list(self.allowed_opportunity_kinds)
        payload["intent_overrides"] = dict(self.intent_overrides)
        payload["performance_overrides"] = {
            kind: {
                "delivery_style": values[0],
                "stage_emotion": values[1],
                "stage_motion": values[2],
                "tts_style": values[3],
            }
            for kind, values in self.performance_overrides
        }
        payload["surface_rules"] = list(self.surface_rules)
        payload["policy_tags"] = list(self.policy_tags)
        return payload

    def intent_for(self, opportunity_kind: str, fallback: str = "") -> str:
        overrides = dict(self.intent_overrides)
        return str(overrides.get(str(opportunity_kind or ""), fallback or self.default_intent) or self.default_intent)

    def performance_for(self, opportunity_kind: str) -> tuple[str, str, str, str]:
        overrides = dict(self.performance_overrides)
        return overrides.get(
            str(opportunity_kind or ""),
            (self.delivery_style, self.stage_emotion, self.stage_motion, self.tts_style),
        )


class AutonomousStagePresetResolver:
    """Resolve scene -> playbook và lọc opportunity trước SessionDirector.

    Filter xảy ra trước bước chọn opportunity. Nếu không, một ``dead_air`` vốn
    chỉ nên body-only có thể thắng điểm rồi che mất ``task_progress`` hợp scene.
    Lỗi kiểu này rất khó thấy trong log vì từng module riêng vẫn "đúng".
    """

    VERSION = "autonomous_stage_presets.v1"

    _COMMON_PRIVATE_RULES = (
        "Không chào lại và không hỏi người dùng cần giúp gì trong autonomous.",
        "Không giải thích vì sao Eris tự nói.",
        "Không claim đã nhìn thấy màn hình nếu evidence không cho phép.",
        "Không nhét action tag hoặc chỉ dẫn diễn xuất vào public text.",
    )

    def resolve(
        self,
        *,
        scene: SceneRuntimeState,
        signal_snapshot: Any = None,
    ) -> AutonomousStagePreset:
        metadata = _get(signal_snapshot, "metadata", {}) or {}
        audience = str(_get(metadata, "audience_mode", "") or "").strip().lower()
        if not audience:
            audience = "stream" if scene.name == "stream_host" else "private"
        factory = getattr(self, f"_preset_{scene.name}", self._preset_private_active)
        preset = factory(audience_mode=audience)
        return preset

    def selectable_opportunities(
        self,
        opportunities: Sequence[AutonomousOpportunity],
        preset: AutonomousStagePreset,
    ) -> tuple[AutonomousOpportunity, ...]:
        allowed = set(preset.allowed_opportunity_kinds)
        selected: list[AutonomousOpportunity] = []
        for item in opportunities:
            # Lỗi thật có urgency cao được phép phá playbook. Preset là đạo diễn,
            # không phải bức tường khiến Eris bình thản nhìn hệ thống cháy.
            emergency = item.kind == "new_error" and item.urgency >= 0.90
            if item.kind not in allowed and not emergency:
                continue
            threshold = preset.min_opportunity_strength
            if item.kind in {"return_after_idle", "task_progress"}:
                threshold = max(0.0, threshold - 0.08)
            if item.strength < threshold and not emergency:
                continue
            selected.append(item)
        return tuple(selected)

    @staticmethod
    def _base(
        *,
        preset_id: str,
        scene_mode: str,
        audience_mode: str,
        body_first: bool,
        allowed: tuple[str, ...],
        threshold: float,
        min_gap_ms: int,
        max_lines: int,
        max_words: int,
        max_duration_ms: int,
        startup_quiet_ms: int,
        default_intent: str,
        delivery: str,
        emotion: str,
        motion: str,
        tts: str,
        lane: str,
        gesture_density: str,
        opening_bias: int,
        closing_min: int,
        public_memory_allowed: bool = True,
        anti_spoiler: bool = False,
        poetic_drift_allowed: bool = True,
        intents: tuple[tuple[str, str], ...] = (),
        performances: tuple[tuple[str, tuple[str, str, str, str]], ...] = (),
        rules: tuple[str, ...] = (),
        tags: tuple[str, ...] = (),
    ) -> AutonomousStagePreset:
        return AutonomousStagePreset(
            preset_id=preset_id,
            scene_mode=scene_mode,
            audience_mode=audience_mode,
            body_first=body_first,
            allowed_opportunity_kinds=allowed,
            min_opportunity_strength=_clamp01(threshold),
            min_gap_ms=max(3_000, int(min_gap_ms)),
            max_lines_per_hour=max(1, int(max_lines)),
            max_words=max(1, int(max_words)),
            max_duration_ms=max(500, int(max_duration_ms)),
            startup_quiet_ms=max(0, int(startup_quiet_ms)),
            default_intent=default_intent,
            delivery_style=delivery,
            stage_emotion=emotion,
            stage_motion=motion,
            tts_style=tts,
            performance_lane=lane,
            gesture_density=gesture_density,
            opening_hold_bias_ms=int(opening_bias),
            closing_hold_min_ms=max(0, int(closing_min)),
            public_memory_allowed=bool(public_memory_allowed),
            anti_spoiler=bool(anti_spoiler),
            poetic_drift_allowed=bool(poetic_drift_allowed),
            intent_overrides=intents,
            performance_overrides=performances,
            surface_rules=rules,
            policy_tags=tags,
        )

    def _preset_private_idle(self, *, audience_mode: str) -> AutonomousStagePreset:
        return self._base(
            preset_id="desktop_pet.private_idle.v1",
            scene_mode="private_idle",
            audience_mode=audience_mode,
            body_first=True,
            allowed=("dead_air", "return_after_idle", "scene_transition", "long_focus", "high_salience"),
            threshold=0.48,
            min_gap_ms=34_000,
            max_lines=8,
            max_words=12,
            max_duration_ms=2_100,
            startup_quiet_ms=14_000,
            default_intent="micro_presence",
            delivery="dry_tease",
            emotion="mischief_soft",
            motion="tilt_head",
            tts="low_warm",
            lane="ambient_companion",
            gesture_density="low",
            opening_bias=55,
            closing_min=460,
            intents=(("return_after_idle", "react"), ("scene_transition", "react")),
            performances=(("return_after_idle", ("soft_near", "gentle", "lean_in_small", "low_warm")),),
            rules=self._COMMON_PRIVATE_RULES + (
                "Khoảng im chỉ được dùng cho một micro-line, không mở câu hỏi mới.",
                "Khịa nhẹ nhưng không biến quan hệ thành lời sở hữu hoặc phụ thuộc.",
            ),
            tags=("desktop_pet", "low_intrusion", "body_first"),
        )

    def _preset_private_active(self, *, audience_mode: str) -> AutonomousStagePreset:
        return self._base(
            preset_id="desktop_pet.private_active.v1",
            scene_mode="private_active",
            audience_mode=audience_mode,
            body_first=True,
            allowed=("return_after_idle", "scene_transition", "task_progress", "new_error", "high_salience"),
            threshold=0.58,
            min_gap_ms=28_000,
            max_lines=8,
            max_words=13,
            max_duration_ms=2_300,
            startup_quiet_ms=12_000,
            default_intent="react",
            delivery="soft_direct",
            emotion="neutral_warm",
            motion="soft_attention",
            tts="low_warm",
            lane="light_companion",
            gesture_density="low",
            opening_bias=20,
            closing_min=360,
            intents=(("new_error", "technical_help"), ("return_after_idle", "micro_presence")),
            rules=self._COMMON_PRIVATE_RULES,
            tags=("desktop_pet", "low_intrusion"),
        )

    def _preset_coding_partner(self, *, audience_mode: str) -> AutonomousStagePreset:
        return self._base(
            preset_id="coding_partner.focused.v1",
            scene_mode="coding_partner",
            audience_mode=audience_mode,
            body_first=True,
            allowed=("new_error", "task_progress", "return_after_idle", "long_focus", "high_salience"),
            threshold=0.60,
            min_gap_ms=23_000,
            max_lines=9,
            max_words=18,
            max_duration_ms=3_000,
            startup_quiet_ms=8_000,
            default_intent="technical_help",
            delivery="quiet_focus",
            emotion="focused",
            motion="tiny_nod",
            tts="clipped_clear",
            lane="focus_preserving",
            gesture_density="minimal",
            opening_bias=-25,
            closing_min=280,
            poetic_drift_allowed=False,
            intents=(("task_progress", "react"), ("return_after_idle", "micro_presence"), ("long_focus", "micro_presence")),
            performances=(
                ("new_error", ("cold_precision", "focused", "scene_focus", "clipped_clear")),
                ("task_progress", ("dry_payoff", "satisfied_soft", "tiny_nod", "clear_low")),
                ("long_focus", ("quiet_focus", "gentle_focus", "blink_slow", "low_clear")),
            ),
            rules=self._COMMON_PRIVATE_RULES + (
                "Ưu tiên chẩn đoán hoặc hướng xử lý; không dùng thơ để thay thông tin.",
                "Không claim đã sửa, lưu file, chạy test hoặc thao tác hệ thống thay người dùng.",
                "Nếu không có giá trị kỹ thuật mới, chọn body-only.",
            ),
            tags=("coding_partner", "focus_protection", "no_poetic_drift"),
        )

    def _preset_study_session(self, *, audience_mode: str) -> AutonomousStagePreset:
        return self._base(
            preset_id="study_session.pacing.v1",
            scene_mode="study_session",
            audience_mode=audience_mode,
            body_first=True,
            allowed=("long_focus", "return_after_idle", "task_progress", "scene_transition"),
            threshold=0.56,
            min_gap_ms=55_000,
            max_lines=5,
            max_words=14,
            max_duration_ms=2_500,
            startup_quiet_ms=16_000,
            default_intent="micro_presence",
            delivery="soft_near",
            emotion="gentle_focus",
            motion="blink_slow",
            tts="low_warm",
            lane="pace_keeper",
            gesture_density="minimal",
            opening_bias=70,
            closing_min=520,
            poetic_drift_allowed=False,
            intents=(("task_progress", "react"), ("scene_transition", "react")),
            rules=self._COMMON_PRIVATE_RULES + (
                "Không giảng bài khi không được hỏi; chỉ giữ nhịp học hoặc đánh dấu tiến độ.",
                "Không lặp lời nhắc nghỉ trong cùng một mạch tập trung.",
            ),
            tags=("study_session", "strict_repeat_limit", "focus_protection"),
        )

    def _preset_game_companion(self, *, audience_mode: str) -> AutonomousStagePreset:
        return self._base(
            preset_id="game_companion.reactor.v1",
            scene_mode="game_companion",
            audience_mode=audience_mode,
            body_first=True,
            allowed=("high_salience", "return_after_idle", "scene_transition"),
            threshold=0.72,
            min_gap_ms=32_000,
            max_lines=10,
            max_words=10,
            max_duration_ms=1_650,
            startup_quiet_ms=10_000,
            default_intent="react",
            delivery="energetic_short",
            emotion="bright_react",
            motion="lean_in_small",
            tts="energetic_short",
            lane="reaction_burst",
            gesture_density="medium",
            opening_bias=-45,
            closing_min=240,
            poetic_drift_allowed=False,
            intents=(("return_after_idle", "micro_presence"),),
            rules=self._COMMON_PRIVATE_RULES + (
                "Phản ứng cực ngắn; không phân tích dài giữa gameplay.",
                "Không bịa boss, vật phẩm hoặc diễn biến cụ thể nếu signal không nêu.",
            ),
            tags=("game_reactor", "latency_priority", "speech_threshold_high"),
        )

    def _preset_media_companion(self, *, audience_mode: str) -> AutonomousStagePreset:
        return self._base(
            preset_id="media_companion.side_commentary.v1",
            scene_mode="media_companion",
            audience_mode=audience_mode,
            body_first=True,
            allowed=("high_salience", "return_after_idle", "scene_transition"),
            threshold=0.74,
            min_gap_ms=48_000,
            max_lines=6,
            max_words=12,
            max_duration_ms=2_100,
            startup_quiet_ms=14_000,
            default_intent="react",
            delivery="soft_near",
            emotion="thoughtful_soft",
            motion="look_aside",
            tts="low_warm",
            lane="side_commentary",
            gesture_density="minimal",
            opening_bias=75,
            closing_min=500,
            anti_spoiler=True,
            poetic_drift_allowed=False,
            intents=(("return_after_idle", "micro_presence"),),
            rules=self._COMMON_PRIVATE_RULES + (
                "Không spoil và không đoán nội dung media ngoài evidence.",
                "Bình luận cạnh lề một câu; im lặng tốt hơn lời chung chung.",
            ),
            tags=("media_watch", "anti_spoiler", "low_intrusion"),
        )

    def _preset_stream_host(self, *, audience_mode: str) -> AutonomousStagePreset:
        return self._base(
            preset_id="stream_host.public_safe.v1",
            scene_mode="stream_host",
            audience_mode="stream",
            body_first=False,
            allowed=("scene_transition", "task_progress", "high_salience", "return_after_idle", "new_error"),
            threshold=0.54,
            min_gap_ms=14_000,
            max_lines=18,
            max_words=18,
            max_duration_ms=2_600,
            startup_quiet_ms=3_000,
            default_intent="react",
            delivery="brief_public",
            emotion="composed",
            motion="open_palm",
            tts="projected_even",
            lane="public_host",
            gesture_density="medium",
            opening_bias=-20,
            closing_min=260,
            public_memory_allowed=False,
            poetic_drift_allowed=False,
            intents=(("scene_transition", "react"), ("new_error", "repair")),
            rules=(
                "Chỉ dùng nội dung public-safe; không nhắc ký ức riêng hoặc thói quen riêng tư.",
                "Không claim cảm xúc của host, collab hoặc audience như sự thật.",
                "Nói như bridge công khai: rõ, gọn, không thân mật độc quyền.",
                "Không nhét action tag hoặc chỉ dẫn diễn xuất vào public text.",
            ),
            tags=("stream_host", "public_safe", "private_memory_off"),
        )


__all__ = [
    "AutonomousStagePreset",
    "AutonomousStagePresetResolver",
]
