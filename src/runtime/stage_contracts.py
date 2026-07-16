# -*- coding: utf-8 -*-
"""stage_contracts.py — hợp đồng sân khấu giữa Decision, UI, TTS và body.

``Decision`` là kết quả của não: ERIS định nói gì, animation nào, action nào.
``StageFrame`` là một lát biểu diễn: UI hiện gì, TTS đọc gì, mặt/động tác gì,
có cho ngắt không, và trace về lượt nói.

Tầng này cố ý nhỏ.  Mục tiêu là tách string public khỏi string TTS trước đã; sau
này có Live2D/expression chi tiết thì chỉ cần map thêm vào ``emotion``/``motion``
chứ không phải nhét "(cười khẽ)" vào text.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import Any

from runtime.autonomous_performance import AutonomousPerformancePlanner
from runtime.autonomous_surface_anchor import AutonomousSurfaceAnchorGuard
from runtime.intention_authority import IntentionAuthorityGate
from runtime.prosody_director import ProsodyDirector
from runtime.speech_delivery_planner import SpeechDeliveryPlanner, affect_signals_from
from runtime.speech_contract import SpeechContractResolver
from runtime.stage_performance_planner import PerformanceRequestPlanner
from runtime.stage_transformers import StageTransformerChain
from runtime.stage_show_runtime import StageShowRuntime


@dataclass(frozen=True, slots=True)
class StageFrame:
    """Một lát output sân khấu, có default để caller cũ không vỡ contract.

    ``stage_act`` là contract nhịp trung tính cho autonomous performer. Nó không
    chứa hotkey/parameter của Live2D; avatar 3D sau này chỉ việc map intent.
    """

    turn_id: str = ""
    segment_id: int = 0
    display_text: str = ""
    tts_text: str = ""
    memory_text: str = ""
    emotion: str = "neutral"
    motion: str = "none"
    actions: tuple[str, ...] = ()
    prosody_style: str = "neutral"
    prosody_notes: str = ""
    delivery: dict[str, Any] = field(default_factory=dict)
    stage_act: dict[str, Any] = field(default_factory=dict)
    show_plan: dict[str, Any] = field(default_factory=dict)
    speech_contract: dict[str, Any] = field(default_factory=dict)
    interruptible: bool = True
    body_only: bool = False
    source: str = "unknown"
    # Metadata preset audio. Rỗng với mọi câu nói động bình thường.
    speech_act: str = ""
    preset_id: str = ""
    audio_asset: str = ""

    def to_payload_patch(self) -> dict[str, Any]:
        """Patch gắn vào payload cũ mà không phá Godot/client hiện tại."""
        return {
            "display_text": self.display_text,
            "stage": {
                "turn_id": self.turn_id,
                "segment_id": self.segment_id,
                "emotion": self.emotion,
                "motion": self.motion,
                "actions": list(self.actions),
                "prosody_style": self.prosody_style,
                "delivery": self.delivery,
                "stage_act": self.stage_act,
                "show_plan": self.show_plan,
                "speech_contract": self.speech_contract,
                "interruptible": self.interruptible,
                "body_only": self.body_only,
                "source": self.source,
                "speech_act": self.speech_act,
                "preset_id": self.preset_id,
                "audio_asset": self.audio_asset,
            },
        }


_TRANSFORMERS = StageTransformerChain()


def clean_display_text(text: str) -> str:
    """Text cho UI: giữ nội dung, chỉ dọn whitespace/markdown thô."""
    return _TRANSFORMERS.transform(text).display_text


def clean_tts_source(text: str) -> str:
    """Text nguồn cho TTS: không đọc markdown, URL, code, hay tag diễn xuất."""
    return _TRANSFORMERS.transform(text).tts_text


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _emotion_from_payload(payload: dict[str, Any], frame: Any = None) -> str:
    """Rút emotion thô cho stage từ appraisal/envelope hiện có.

    Đây chỉ là nhãn sân khấu, không phải claim "ERIS có cảm xúc người".
    """
    appraisal = getattr(frame, "appraisal", None) if frame is not None else None
    stance = str(getattr(appraisal, "stance", "") or "").strip().lower()
    if stance:
        return stance

    mood = {}
    emotion_debug = payload.get("emotion_debug")
    if isinstance(emotion_debug, dict):
        raw_mood = emotion_debug.get("summary")
        if isinstance(raw_mood, dict):
            mood = raw_mood

    valence = _safe_float(mood.get("valence"), 0.0) if isinstance(mood, dict) else 0.0
    arousal = _safe_float(getattr(appraisal, "arousal", 0.3), 0.3)
    if valence > 0.25 and arousal > 0.35:
        return "warm_playful"
    if valence > 0.12:
        return "warm_soft"
    if valence < -0.25 and arousal > 0.45:
        return "tense"
    if valence < -0.15:
        return "quiet_low"
    if arousal > 0.62:
        return "focused"
    return "neutral"


def _prosody_numbers(payload: dict[str, Any], frame: Any = None) -> tuple[float, float, str]:
    """Trích valence/arousal/stance cho prosody mà không bắt stage biết cognition."""
    appraisal = getattr(frame, "appraisal", None) if frame is not None else None
    emotion_debug = payload.get("emotion_debug")
    mood = {}
    if isinstance(emotion_debug, dict) and isinstance(emotion_debug.get("summary"), dict):
        mood = emotion_debug.get("summary") or {}
    valence = _safe_float(mood.get("valence"), 0.0) if isinstance(mood, dict) else 0.0
    arousal = _safe_float(getattr(appraisal, "arousal", 0.3), 0.3)
    stance = str(getattr(appraisal, "stance", "") or "")
    return valence, arousal, stance


def _motion_from_decision(decision: Any) -> str:
    resolver = getattr(decision, "resolve_motion_intent", None)
    if callable(resolver):
        motion = str(resolver() or "").strip()
        if motion:
            return motion
    animation = str(getattr(decision, "animation", "") or "").strip()
    return animation or "none"


class StageFrameBuilder:
    """Dịch ``Decision`` thành ``StageFrame``.

    Localizer được inject để test/offline dễ hơn.  Nếu không có localizer, TTS đọc
    câu đã clean bằng chính ngôn ngữ gốc.
    """

    def __init__(self, *, localizer: Any = None, language_hint: str = "auto") -> None:
        self.localizer = localizer
        self.language_hint = language_hint or "auto"
        self.speech_contract_resolver = SpeechContractResolver(default_language=self.language_hint)
        self.prosody_director = ProsodyDirector()
        self.transformers = StageTransformerChain()
        self.delivery_planner = SpeechDeliveryPlanner()
        self.performance_planner = PerformanceRequestPlanner()
        self.autonomous_performance_planner = AutonomousPerformancePlanner()
        self.autonomous_anchor_guard = AutonomousSurfaceAnchorGuard()
        self.intention_authority_gate = IntentionAuthorityGate()
        self.show_runtime = StageShowRuntime()

    def build(
        self,
        decision: Any,
        *,
        payload: dict[str, Any],
        channel: str | None = None,
        frame: Any = None,
        turn_id: str | None = None,
        segment_id: int = 0,
    ) -> StageFrame:
        raw_text = str(payload.get("text", getattr(decision, "text", "")) or "")
        if str(channel or "").strip().lower() == "autonomous":
            plan_payload = payload.get("autonomous_plan") if isinstance(payload.get("autonomous_plan"), dict) else None
            verdict = self.autonomous_anchor_guard.validate(raw_text, plan_payload)
            payload["autonomous_anchor"] = verdict.to_payload()
            raw_text = verdict.text

            # Phase 11: neo nội dung chưa đủ. Một câu như "tôi sẽ rà lại ký
            # ức" còn ngầm hứa có target, handler và result. Nếu runtime không
            # có execution contract thật, hạ nó thành trạng thái trung thực hoặc
            # body-only. Siêu nhận thức dùng trước khi nói sẽ rẻ hơn xin lỗi sau.
            opportunity = (
                plan_payload.get("selected_opportunity")
                if isinstance(plan_payload, dict) and isinstance(plan_payload.get("selected_opportunity"), dict)
                else {}
            )
            intention_context = {
                "kind": str(opportunity.get("kind", "") or payload.get("intent", "")),
                "evidence_refs": tuple(opportunity.get("evidence_refs") or ()),
                "system_action": payload.get("system_action", ""),
                "action": payload.get("action", ""),
                "action_input": payload.get("action_input", ""),
                "action_result": payload.get("action_result") if isinstance(payload.get("action_result"), dict) else {},
                "execution_handler": payload.get("execution_handler", ""),
                "handler_available": payload.get("handler_available"),
                "result_event": payload.get("result_event", ""),
                "observable_result": payload.get("observable_result", ""),
                "target_ref": payload.get("intent_target", ""),
            }
            intention_verdict = self.intention_authority_gate.validate(raw_text, intention_context)
            payload["intention_authority"] = intention_verdict.to_payload()
            raw_text = intention_verdict.text
            if not raw_text:
                payload["should_speak"] = False
        surfaces = self.transformers.transform(raw_text)
        user_text = str(payload.get("user_text", "") or "")
        delivery_hint = str(payload.get("delivery_hint", getattr(decision, "delivery_hint", "")) or "").strip()
        nonverbal_cue = str(payload.get("nonverbal_cue", getattr(decision, "nonverbal_cue", "")) or "").strip()
        stage_motion = str(payload.get("stage_motion", getattr(decision, "stage_motion", "")) or "").strip()
        performance = self.performance_planner.apply(
            surfaces,
            user_text=user_text,
            intent=str(getattr(decision, "intent", "") or ""),
            delivery_hint=delivery_hint,
            nonverbal_cue=nonverbal_cue,
            stage_motion=stage_motion,
            extracted_actions=surfaces.marks.actions,
        )

        tts_source = performance.tts_text
        speech_contract = self.speech_contract_resolver.resolve(payload, text=tts_source)
        if self.localizer is not None and tts_source and speech_contract.can_translate:
            try:
                tts_text = str(
                    self.localizer.localize(
                        tts_source,
                        language_hint=speech_contract.language,
                        prosody_style=performance.delivery_hint,
                    ) or ""
                ).strip()
            except Exception:
                tts_text = tts_source
        else:
            tts_text = tts_source

        should_speak = bool(payload.get("should_speak", getattr(decision, "should_speak", True)))
        affect = affect_signals_from(payload, frame=frame)
        preset_emotion = str(payload.get("preset_emotion", getattr(decision, "preset_emotion", "")) or "").strip()
        base_emotion = preset_emotion or surfaces.marks.emotion_hint or _emotion_from_payload(payload, frame=frame)
        explicit_motion = _motion_from_decision(decision)
        delivery = self.delivery_planner.plan(
            performance.display_text or performance.tts_text,
            intent=str(getattr(decision, "intent", "") or ""),
            delivery_hint=performance.delivery_hint,
            explicit_emotion=base_emotion,
            explicit_motion=performance.stage_motion or surfaces.marks.motion_hint,
            extracted_actions=performance.actions,
            affect=affect,
        )
        # Preset đã được art-direct sẵn; delivery planner không được tự đổi mặt.
        emotion = preset_emotion or delivery.emotion or base_emotion
        motion = performance.stage_motion or (explicit_motion if explicit_motion and explicit_motion != "none" else delivery.motion)
        valence, arousal, stance = _prosody_numbers(payload, frame=frame)
        prosody_notes = delivery.prosody_notes
        delivery_payload = delivery.to_payload()
        if performance.performance_act is not None:
            act_payload = performance.performance_act.to_payload()
            delivery_payload["performance_act"] = act_payload
            if performance.performance_act.prosody_note:
                prosody_notes = f"{prosody_notes} {performance.performance_act.prosody_note}".strip()

        # Autonomous không chỉ có text. Dựng opening hold, speech beat và closing
        # settle từ plan đã được SpeakGate cấp quyền. LLM không được tự bịa nhịp.
        autonomous_act = None
        if str(channel or "").strip().lower() == "autonomous":
            autonomous_act = self.autonomous_performance_planner.plan(
                tts_text,
                autonomous_plan=payload.get("autonomous_plan") if isinstance(payload.get("autonomous_plan"), dict) else None,
                performance_context=payload.get("performance_context") if isinstance(payload.get("performance_context"), dict) else None,
                emotion=emotion,
                motion=motion or "none",
                tts_style=delivery.voice_style,
            )
            if autonomous_act is not None:
                delivery_payload["autonomous_act"] = autonomous_act.to_payload()
                prosody_notes = f"{prosody_notes} {autonomous_act.director_note}".strip()

        prosody = self.prosody_director.plan(
            tts_text,
            emotion=emotion,
            intent=str(getattr(decision, "intent", "") or ""),
            stance=stance,
            valence=valence,
            arousal=arousal,
            style_hint=delivery.voice_style,
            notes_hint=prosody_notes,
        )
        stage_frame = StageFrame(
            turn_id=str(turn_id or uuid.uuid4().hex),
            segment_id=int(segment_id),
            display_text=performance.display_text,
            tts_text=tts_text,
            memory_text=performance.memory_text,
            emotion=emotion,
            motion=motion or "none",
            actions=delivery.pre_speech_actions,
            prosody_style=prosody.style,
            prosody_notes=prosody.director_notes,
            delivery=delivery_payload,
            stage_act=autonomous_act.to_payload() if autonomous_act is not None else {},
            speech_contract=speech_contract.to_payload(),
            interruptible=bool(should_speak and str(channel or "").strip().lower() not in {"system_warning"}),
            body_only=bool(not should_speak and (motion or performance.actions)),
            source=f"decision:{str(getattr(decision, 'intent', '') or channel or 'unknown')}",
            speech_act=str(payload.get("speech_act", getattr(decision, "speech_act", "")) or ""),
            preset_id=str(payload.get("preset_id", getattr(decision, "preset_id", "")) or ""),
            audio_asset=str(payload.get("audio_asset", getattr(decision, "audio_asset", "")) or ""),
        )
        show_plan = self.show_runtime.compile(stage_frame)
        return replace(stage_frame, show_plan=show_plan.to_payload())


__all__ = [
    "StageFrame",
    "StageFrameBuilder",
    "clean_display_text",
    "clean_tts_source",
]
