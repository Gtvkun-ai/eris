# -*- coding: utf-8 -*-
"""Surface Worker duy nhất cho lời chủ động của ERIS.

Kiến trúc V18 tách quyền rất rõ:

- Social Initiative Worker đề xuất desire/topic bằng candidate typed;
- Runtime Initiative Governor quyết định NO_OP / BODY_ONLY / SPEECH;
- Surface Worker chỉ hiện thực hóa một ``SpeechIntent`` đã được duyệt;
- Grounding Validator kiểm tra provenance trước và sau câu model viết.

Phần ``deliberate`` cũ còn giữ như compatibility shim cho test/plugin cũ, nhưng
production self-turn không dùng nó để quyết định có nói hay không nữa.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .contracts import IntentionPlan, StateEvent
from .cognitive_blackboard import TypedCognitiveBlackboard
from .initiative import SpeechIntent
from .semantic_contracts import compact, semantic_key
from runtime.utterance_spec import UtteranceSpec


SURFACE_MODES: tuple[str, ...] = (
    "silence",
    "small_talk",
    "dry_tease",
    "soft_tease",
    "inner_thought",
    "random_chat",
    "continuation",
    "memory_callback",
    "task_followup",
    "screen_comment",
    "semantic_scene",
    "discovery_share",
)


def _flag(name: str, default: bool = True) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    return raw not in {"0", "false", "no", "off", "disabled"}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def _anchor_topic(blackboard: TypedCognitiveBlackboard, kind: str) -> str:
    for anchor in blackboard.anchors:
        if str(anchor.kind or "") == kind and str(anchor.topic_seed or "").strip():
            return str(anchor.topic_seed).strip()
    return ""


def _surface_languages() -> tuple[str, str]:
    try:
        from runtime.runtime_settings_store import runtime_text
        display = str(runtime_text("chat", "language", default="vi") or "vi").strip().lower()
        speech = str(runtime_text("tts", "language", default="ja") or "ja").strip().lower()
    except Exception:
        display, speech = "vi", "ja"
    aliases = {
        "": "vi", "auto": "vi", "vn": "vi", "vi-vn": "vi", "vietnamese": "vi",
        "jp": "ja", "ja-jp": "ja", "japanese": "ja", "en-us": "en", "english": "en",
    }
    display = aliases.get(display, display)
    speech_aliases = dict(aliases)
    speech_aliases.update({"": "ja", "auto": "ja"})
    speech = speech_aliases.get(speech, speech)
    return (
        display if display in {"vi", "ja", "en"} else "vi",
        speech if speech in {"vi", "ja", "en"} else "ja",
    )


@dataclass(frozen=True, slots=True)
class SurfaceTurn:
    """Kết quả typed dùng trực tiếp trong autonomous pipeline."""

    plan: IntentionPlan
    public_payload: Mapping[str, Any]
    mode: str
    reason: str = ""
    source: str = "surface_worker"


class SurfaceIntentEngine:
    """Hiện thực hóa lời nói; không sở hữu quyết định initiative."""

    def __init__(self, router: Any, reducer: Any, *, logger: Any | None = None) -> None:
        self.router = router
        self.reducer = reducer
        self.logger = logger

    @property
    def enabled(self) -> bool:
        return bool(
            _flag("ERIS_SURFACE_INTENT_ENABLED", True)
            and getattr(self.router, "surface_client", None) is not None
        )

    def realize(
        self,
        intent: SpeechIntent,
        blackboard: TypedCognitiveBlackboard,
        *,
        snapshot: Mapping[str, Any] | None = None,
    ) -> SurfaceTurn | None:
        """Gọi Surface Worker đúng một lần để viết câu từ SpeechIntent.

        Model không được trả ``silence`` hay đổi mode. Nếu provider/schema lỗi,
        trả ``None`` ngay. Với chess, caller bắt buộc im/body-only; không có local
        text fallback giả làm bình luận viên.
        """

        if not self.enabled:
            return None
        display_language, speech_language = _surface_languages()
        request = {
            "speech_intent": intent.to_dict(),
            "blackboard": blackboard.public_view(),
            "recent_public_history": list(_sequence(_mapping(snapshot or {}).get("recent_public_history"))[-6:]),
            "surface_contract": {
                "authority": "wording_only",
                "fixed_mode": intent.mode,
                "fixed_anchor_type": intent.anchor_type,
                "fixed_anchor_id": intent.anchor_id,
                "allowed_evidence_refs": list(intent.evidence_refs),
                "max_sentences": intent.max_sentences,
                "display_language": display_language,
                "speech_language": speech_language,
                "rule": (
                    f"Write one concise public line in {display_language} (display) and provide its {speech_language} translation (speech). "
                    "Do not decide speak/silence, change the topic owner, invent evidence, or mention internal contracts."
                ),
            },
        }
        if intent.anchor_type == "semantic_scene":
            semantic = blackboard.public_view().get("shared_semantic_context", {})
            request["surface_contract"]["domain_rules"] = [
                "Use shared_semantic_context as the stable scene baseline; do not reinterpret raw OCR or window inventory.",
                "Facts may be stated directly. bounded_inferences must remain tentative. unknowns must not be filled by invention.",
                "Choose between screen analysis, screen-related small talk, cross-context connection, or silence according to response_mode_scores and the approved SpeechIntent.",
                "Develop the topic naturally instead of reciting the packet fields or mentioning Tutor/scene IDs.",
                "Do not claim the user likes, wants, intends, feels, or will buy/do something unless that claim is a direct fact.",
                f"Current semantic activity: {semantic.get('activity', '')}; foreground: {semantic.get('foreground', '')}.",
            ]

        if blackboard.engagement_kind == "chess":
            # Chess có state typed và event snapshot riêng. Surface phải thật sự
            # bàn luận từ thế/nước, không đọc field như telemetry và không dùng
            # câu hard-code. Provider lỗi thì pipeline im, nên đây là nơi duy nhất
            # tạo banter/mỉa mai công khai cho autonomous chess.
            chess_state = dict(blackboard.engagement_state or {})
            companion_mode = str(chess_state.get("companion_mode") or "companion")
            commentary_focus = str(chess_state.get("commentary_focus") or "").strip()
            request["chess_typed_state"] = chess_state
            request["surface_contract"]["domain_rules"] = [
                "Use chess_typed_state as authoritative board context. Ignore OCR/window inventory while chess owns foreground focus.",
                "Comment on the concrete move, positional consequence, tactical motif, or plan.",
                "For advantage wording, use evaluation_cp_user/user_position only when user_side is known. Legacy evaluation_cp/evaluation_label and *_white are from White's perspective, not automatically the user's perspective.",
                "If user_side is unknown, name White or Black explicitly from advantage_side; never say the user is better/worse.",
                "Light dry teasing is allowed only when supported by the move or evaluation.",
                "Any specific move must exactly match suggested_move_san/uci. Phrase it naturally in Vietnamese, such as 'mã lên e4', rather than exposing raw UCI like e2e4.",
                "When user_followed_previous_suggestion=true, remember that the user played ERIS's delivered recommendation; acknowledge that causal link and never deny having suggested it.",
                "Never say telemetry such as board detected, current suggestion, tracking the task, or following the thread.",
                f"Companion mode is {companion_mode}; preserve that role instead of inventing a different chess relationship.",
                f"Latest chess speech reason is {chess_state.get('speech_reason', '')}; actor is {chess_state.get('actor', '')}.",
                commentary_focus or "Use only the latest meaningful structured chess event.",
                "In spectator mode, do not volunteer a best move, hint, or coaching unless the user explicitly asks.",
                "Use shared_semantic_context only for the human situation around the game (focus, likely stuck state, session context, related foreground); chess_typed_state remains authoritative for board facts.",
                "Do not output a generic progress check. If the state is too weak to say something specific, return no usable payload.",
            ]

        writer = getattr(self.router, "realize_surface_speech", None)
        if not callable(writer):
            return None
        raw = writer(request)
        if not isinstance(raw, Mapping) or not raw:
            return None
        utterance = UtteranceSpec.from_mapping(
            raw,
            default_display_language=display_language,
            default_speech_language=speech_language,
            fallback_preset=intent.plan.performance_hint or "neutral",
            turn_id=intent.plan.plan_id,
        )
        text = compact(utterance.display.text, 520)
        confidence = _clamp01(raw.get("confidence", 0.0))
        if not text or not utterance.speech.text or confidence < 0.25:
            return None
        returned_refs = tuple(
            ref for ref in (compact(value, 120) for value in _sequence(raw.get("evidence_refs"))[:6]) if ref
        )
        # Filter out common LLM filler words for empty lists before validating
        actual_refs = [r for r in returned_refs if r.lower() not in {"none", "null", "unknown", "n/a", "[]"}]
        unknown_refs = [ref for ref in actual_refs if ref not in set(intent.evidence_refs)]
        if unknown_refs:
            self._log("warning", "[surface worker] stripped unknown evidence refs mode=%s. Refs: %s", intent.mode, unknown_refs)
        performance_hint = compact(
            utterance.performance.preset or intent.plan.performance_hint or "neutral", 60
        ).lower() or intent.plan.performance_hint or "neutral"
        plan_data = intent.plan.to_dict()
        plan_data["performance_hint"] = performance_hint
        plan = IntentionPlan.from_mapping(plan_data, channel="autonomous")
        try:
            payload = self.router.build_surface_public_payload(
                utterance=utterance.to_dict(),
                plan=plan,
                mode=intent.mode,
                display_language=display_language,
                speech_language=speech_language,
            )
        except TypeError as exc:
            # External/test routers may still expose the previous wording-only
            # signature. Production keeps the typed bilingual path above.
            if "utterance" not in str(exc):
                raise
            payload = self.router.build_surface_public_payload(
                text=text,
                plan=plan,
                mode=intent.mode,
            )
        reason = compact(raw.get("reason", "surface_realized"), 180) or "surface_realized"
        self._log(
            "info",
            "[surface worker] realized mode=%s confidence=%.2f anchor=%s",
            intent.mode,
            confidence,
            intent.anchor_type,
        )
        return SurfaceTurn(
            plan=plan,
            public_payload=payload,
            mode=intent.mode,
            reason=reason,
            source="surface_worker",
        )

    def fallback_payload(
        self,
        intent: SpeechIntent,
        blackboard: TypedCognitiveBlackboard,
        *,
        avoid_text: str = "",
        language: str = "vi",
    ) -> Mapping[str, Any] | None:
        """Local text fallback đã bị vô hiệu hóa toàn cục.

        Candidate typed có thể do runtime route để giữ một event/cadence, nhưng
        câu public luôn phải do DeepSeek Surface viết. Provider unavailable thì
        caller im/body-only và thử lại sau; đây là thất bại rõ ràng, không phải
        một câu canned đội tóc giả AI.
        """
        return None

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass

    def deliberate(self, snapshot: Mapping[str, Any], *, turn_seq: int) -> SurfaceTurn | None:
        """Gọi worker surface đúng một lần; ``None`` nghĩa là dùng planner cũ.

        Một output JSON hợp lệ, kể cả ``silence``, là quyết định thật của lane
        surface. Chỉ lỗi provider/schema mới trả ``None`` để fallback.
        """

        if not self.enabled:
            return None
        allowed_modes = self._allowed_modes(snapshot)
        request = dict(snapshot)
        request["surface_contract"] = {
            "allowed_modes": list(allowed_modes),
            "rule": (
                "Choose exactly one allowed mode. If speaking, provide one concise public line and a concrete topic. "
                "Do not invent screen, memory, task or user-state evidence."
            ),
        }
        raw = self.router.plan_surface_intent(request)
        if not isinstance(raw, Mapping) or not raw:
            return None

        decision = str(raw.get("decision", "silence") or "silence").strip().lower()
        mode = semantic_key(raw.get("mode", "silence"), fallback="silence", limit=48)
        reason = compact(raw.get("reason", ""), 180)
        anchor_type = semantic_key(raw.get("anchor_type", "none"), fallback="none", limit=32)
        if decision != "speak" or mode == "silence":
            return self._silence(turn_seq=turn_seq, reason=reason or "surface_model_silence")
        if mode not in allowed_modes:
            return self._silence(turn_seq=turn_seq, reason=f"surface_mode_not_allowed:{mode}")

        display_language, speech_language = _surface_languages()
        utterance = UtteranceSpec.from_mapping(
            raw,
            default_display_language=display_language,
            default_speech_language=speech_language,
            fallback_preset="neutral",
        )
        text = compact(utterance.display.text or raw.get("text", ""), 520)
        topic = compact(raw.get("topic", ""), 240)
        confidence = _clamp01(raw.get("confidence", 0.0))
        if not text or not topic or confidence < 0.35:
            return self._silence(turn_seq=turn_seq, reason="surface_incomplete_or_low_confidence")

        available_refs = self._available_evidence_refs(snapshot)
        evidence_refs = tuple(
            ref for ref in (
                compact(value, 120) for value in _sequence(raw.get("evidence_refs"))[:6]
            )
            if ref and ref in available_refs
        )
        if mode == "screen_comment" and not self._screen_grounded(snapshot):
            return self._silence(turn_seq=turn_seq, reason="surface_screen_without_evidence")
        if mode == "task_followup" and not bool(_mapping(snapshot.get("engagement_context")).get("active", False)):
            return self._silence(turn_seq=turn_seq, reason="surface_task_without_engagement")
        if mode == "inner_thought" and not bool(_mapping(snapshot.get("self_context")).get("has_public_seed", False)):
            return self._silence(turn_seq=turn_seq, reason="surface_inner_without_public_seed")
        expected_anchor = {
            "small_talk": {"idle", "conversation", "none"},
            "dry_tease": {"idle", "conversation", "none"},
            "soft_tease": {"idle", "conversation", "none"},
            "random_chat": {"idle", "conversation", "none"},
            "inner_thought": {"self"},
            "continuation": {"conversation"},
            "memory_callback": {"memory", "conversation"},
            "task_followup": {"task"},
            "screen_comment": {"screen"},
        }.get(mode, {"none"})
        if anchor_type not in expected_anchor:
            return self._silence(turn_seq=turn_seq, reason=f"surface_anchor_mismatch:{mode}:{anchor_type}")

        plan = self._build_plan(
            mode=mode,
            topic=topic,
            confidence=confidence,
            performance_hint=compact(utterance.performance.preset or raw.get("performance_hint", "neutral"), 60).lower() or "neutral",
            evidence_refs=evidence_refs,
            snapshot=snapshot,
            reason=reason,
        )
        self._submit(plan, turn_seq=turn_seq)
        try:
            payload = self.router.build_surface_public_payload(
                utterance=utterance.to_dict() if utterance.display.text else None,
                text=text,
                plan=plan,
                mode=mode,
                display_language=display_language,
                speech_language=speech_language,
            )
        except TypeError as exc:
            # Compatibility for external/test routers that still implement the
            # pre-UtteranceSpec method. Production router always takes the typed
            # bilingual commit; this branch does not add another model call.
            if "utterance" not in str(exc):
                raise
            payload = self.router.build_surface_public_payload(
                text=text,
                plan=plan,
                mode=mode,
            )
        if self.logger is not None:
            try:
                self.logger.info(
                    "[surface intent] decision=speak mode=%s confidence=%.2f topic=%s",
                    mode,
                    confidence,
                    topic,
                )
            except Exception:
                pass
        return SurfaceTurn(plan=plan, public_payload=payload, mode=mode, reason=reason)

    def _silence(self, *, turn_seq: int, reason: str) -> SurfaceTurn:
        plan = IntentionPlan.silence(channel="autonomous", reason=reason)
        self._submit(plan, turn_seq=turn_seq)
        if self.logger is not None:
            try:
                self.logger.info("[surface intent] decision=silence reason=%s", reason)
            except Exception:
                pass
        return SurfaceTurn(plan=plan, public_payload={}, mode="silence", reason=reason)

    def _submit(self, plan: IntentionPlan, *, turn_seq: int) -> None:
        try:
            state = self.reducer.snapshot()
            self.reducer.submit(
                StateEvent.from_intention(
                    plan,
                    turn_seq=turn_seq,
                    base_version=getattr(state, "version", -1),
                )
            )
        except Exception as exc:  # telemetry/persistence không được làm gãy lời public
            if self.logger is not None:
                try:
                    self.logger.debug("[surface intent] reducer submit failed: %s", exc)
                except Exception:
                    pass

    @staticmethod
    def _screen_grounded(snapshot: Mapping[str, Any]) -> bool:
        screen = _mapping(snapshot.get("screen_context"))
        if bool(screen.get("privacy_blocked", False)) or not bool(screen.get("fresh", False)):
            return False
        return bool(
            screen.get("evidence_refs")
            or screen.get("visible_text")
            or screen.get("changed_text")
            or snapshot.get("vision_facts")
        )

    @staticmethod
    def _available_evidence_refs(snapshot: Mapping[str, Any]) -> frozenset[str]:
        refs: set[str] = set()
        screen = _mapping(snapshot.get("screen_context"))
        refs.update(compact(value, 120) for value in _sequence(screen.get("evidence_refs")) if compact(value, 120))
        self_context = _mapping(snapshot.get("self_context"))
        for group in ("agenda", "private_mind_surface", "private_life_surface"):
            for item in _sequence(self_context.get(group)):
                data = _mapping(item)
                item_id = compact(data.get("id", ""), 120)
                if item_id:
                    refs.add(item_id)
                refs.update(
                    compact(value, 120)
                    for value in _sequence(data.get("evidence_refs"))
                    if compact(value, 120)
                )
        refs.update(f"vision:fact:{index}" for index, _ in enumerate(_sequence(snapshot.get("vision_facts"))[:6]))
        return frozenset(refs)

    def _allowed_modes(self, snapshot: Mapping[str, Any]) -> tuple[str, ...]:
        baton = _mapping(snapshot.get("conversation_baton"))
        telemetry = _mapping(snapshot.get("telemetry"))
        engagement = _mapping(snapshot.get("engagement_context"))
        self_context = _mapping(snapshot.get("self_context"))
        commentary = _mapping(snapshot.get("commentary_expectation"))
        user_busy = bool(
            telemetry.get("user_busy", False)
            or telemetry.get("interaction_busy", False)
            or baton.get("reply_expected", False)
        )
        modes: list[str] = ["silence"]
        if bool(baton.get("assistant_may_continue", False)) and bool(baton.get("thread_fresh", False)):
            modes.append("continuation")
        if self._screen_grounded(snapshot):
            modes.append("screen_comment")
        if bool(engagement.get("active", False)):
            modes.append("task_followup")
            # Engagement đang chạy thì không cho model bỏ nhiệm vụ để tán dóc.
            return tuple(dict.fromkeys(modes))
        if user_busy:
            return tuple(dict.fromkeys(modes))
        if bool(self_context.get("has_public_seed", False)):
            modes.append("inner_thought")
        if snapshot.get("open_loops") or snapshot.get("recent_public_history"):
            modes.append("memory_callback")
        if bool(commentary.get("due", False)) or float(snapshot.get("seconds_since_assistant", 0.0) or 0.0) >= 90.0:
            modes.extend(("small_talk", "soft_tease", "dry_tease", "random_chat"))
        return tuple(dict.fromkeys(modes))

    @staticmethod
    def _build_plan(
        *,
        mode: str,
        topic: str,
        confidence: float,
        performance_hint: str,
        evidence_refs: tuple[str, ...],
        snapshot: Mapping[str, Any],
        reason: str,
    ) -> IntentionPlan:
        baton = _mapping(snapshot.get("conversation_baton"))
        thread_key = semantic_key(baton.get("thread_key", "none"), fallback="none", limit=96)
        config = {
            "small_talk": ("idle_companion", "small_talk", "relational_presence", "presence", "small_talk", "idle_companion", "persona", "none", 0.48, 0.14),
            "dry_tease": ("playful_presence", "dry_tease", "playful_safety", "presence", "playful_tease", "shared_quiet", "persona", "none", 0.52, 0.18),
            "soft_tease": ("playful_presence", "soft_tease", "warmth_expression", "presence", "soft_tease", "shared_quiet", "persona", "none", 0.52, 0.14),
            "inner_thought": ("private_mind_surface", "share_inner_thought", "self_coherence", "internal", "share_public_safe_thought", "current_public_self_seed", "self_context", "none", 0.56, 0.12),
            "random_chat": ("idle_companion", "random_chat", "curiosity", "presence", "random_chat", "idle_companion", "persona", "none", 0.45, 0.16),
            "continuation": ("useful_followup", "continue_thread", "continuity", "continuation", "carry_open_thread", thread_key or "open_conversation", "conversation", thread_key, 0.62, 0.08),
            "memory_callback": ("useful_followup", "memory_callback", "continuity", "continuation", "recall_shared_context", "shared_context", "conversation_memory", thread_key, 0.58, 0.12),
            "task_followup": ("important_open_loop", "task_followup", "helpfulness", "activity_event", "follow_active_engagement", "active_engagement", "engagement", "none", 0.70, 0.10),
            "screen_comment": ("meaningful_environment_change", "screen_comment", "grounded_curiosity", "environment", "comment_current_surface", "current_screen", "screen_current", "none", 0.60, 0.16),
        }[mode]
        motive, strategy, value_focus, kind, act, subject, scope, continuation, importance, intrusion = config
        return IntentionPlan.from_mapping(
            {
                "speak": True,
                "motive": motive,
                "strategy": strategy,
                "value_focus": value_focus,
                "topic": topic,
                "importance": importance,
                "intrusion_risk": intrusion,
                "confidence": confidence,
                "performance_hint": performance_hint,
                "evidence_refs": list(evidence_refs),
                "semantics": {
                    "turn_kind": kind,
                    "speech_act": act,
                    "subject_key": subject,
                    "evidence_scope": scope,
                    "continuation_key": continuation,
                },
                "notes": compact(f"surface_mode={mode}; {reason}", 220),
            },
            channel="autonomous",
        )


__all__ = ["SURFACE_MODES", "SurfaceIntentEngine", "SurfaceTurn"]
