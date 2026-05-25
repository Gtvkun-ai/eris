from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import traceback
import unicodedata
from dataclasses import dataclass, replace

from cortex.contracts import (
    AgentSpeechCore,
    AttentionCandidate,
    CognitiveActionPlan,
    CognitiveAppraisal,
    CognitiveBroadcast,
    CognitiveDisturbance,
    CognitiveFrame,
    InnerThought,
    CognitiveMemoryUpdate,
    MeaningLayerResult,
    PersonalityLensResult,
    PerceptEvent,
    SessionRitualReport,
    SilenceState,
    SubconsciousReport,
    ThoughtStreamReport,
    TiPolicyReport,
)
from cortex.internal_state import PersistentInternalState
from cortex.relationship_dynamics import RelationshipTurnEvent
from core.evidence import EvidenceItem, RawSignal
from cortex.modes import QUIET_MODES
from cortex.ni import NiStateMachine
from domain import Decision
from runtime.body_bias import BodyBiasProjector
from runtime.presence_controller import SocialPresenceEvent
from runtime.speech_pipeline import SpeechIntentDecision


class StateCommitServiceMixin:
    def _load_memory_state(self):
        core = getattr(self, "memory_core", None)
        loader = getattr(core, "load", None)
        if not callable(loader):
            return None
        try:
            return loader()
        except Exception as exc:
            self.logger.warning("Memory state load error: %s", exc)
            return None
    def _has_structured_memory_core(self) -> bool:
        core = getattr(self, "memory_core", None)
        return callable(getattr(core, "commit", None))
    def _ensure_internal_state(self) -> None:
        if self.memory_state is None:
            return
        if isinstance(self.memory_state, dict):
            self.memory_state.setdefault("internal_state", self._load_internal_state_payload())
            return
        # Nếu có memory nhưng chưa có internal state:
        if getattr(self.memory_state, "internal_state", None) is None:
            self.memory_state.internal_state = PersistentInternalState()
    def _get_internal_state(self) -> PersistentInternalState:
        if isinstance(self.memory_state, dict):
            payload = self.memory_state.get("internal_state") or self._load_internal_state_payload()
            if isinstance(payload, dict):
                try:
                    return PersistentInternalState.from_dict(payload)
                except Exception:
                    return PersistentInternalState()
        if self.memory_state is not None and getattr(self.memory_state, "internal_state", None) is not None:
            return self.memory_state.internal_state
        # Nếu không có thì tạo state tạm:
        return PersistentInternalState()
    def _set_internal_state(self, state: PersistentInternalState) -> None:
        # Không có memory thì không set.
        if self.memory_state is None:
            return
        # Dùng lock để tránh nhiều thread sửa state cùng lúc.
        with self._state_lock:
            if isinstance(self.memory_state, dict):
                self.memory_state["internal_state"] = state.to_dict() if callable(getattr(state, "to_dict", None)) else dict(getattr(state, "__dict__", {}) or {})
                self._save_memory_state()
                return
            self.memory_state.internal_state = state
            self._save_memory_state()
    def _load_internal_state_payload(self) -> dict[str, object]:
        core = getattr(self, "memory_core", None)
        active_loader = getattr(core, "load_active_state", None)
        if callable(active_loader):
            try:
                active = active_loader()
                metadata = getattr(active, "metadata", {}) or {}
                payload = metadata.get("internal_state")
                return dict(payload) if isinstance(payload, dict) else {}
            except Exception:
                return {}
        return {}
    def _send_decision_to_body(self, decision: Decision) -> None:
        payload = decision.to_payload()
        payload.update(self._build_body_bias_payload())
        self.transport.send_json(payload)
    def _build_body_bias_payload(self) -> dict[str, object]:
        return self.body_bias_projector.build_payload()
    def _body_bias_clamp(value: object) -> float:
        return BodyBiasProjector.clamp(value)
    def _normalize_body_focus_kind(value: str) -> str:
        return BodyBiasProjector.normalize_focus_kind(value)
    def _save_memory_state(self) -> None:
        if self.memory_state is None:
            return
        saver = getattr(getattr(self, "memory_core", None), "save", None)
        if not callable(saver):
            return
        try:
            saver(self.memory_state)
        except Exception as exc:
            self.logger.warning("Memory state save error: %s", exc)
    def _memory_recall_texts(self, *, snapshot=None) -> list[str]:
        recall = getattr(getattr(self, "memory_core", None), "recall", None)
        if callable(recall):
            try:
                packet = recall(self._memory_query_from_snapshot(snapshot))
                texts: list[str] = []
                for name in ("repair", "procedural", "semantic", "relational", "affective_residue", "episodic"):
                    texts.extend(str(item) for item in getattr(packet, name, ()) or ())
                return texts
            except Exception as exc:
                self.logger.warning("Memory recall error: %s", exc)
        return list(getattr(self, "long_term_memory", []) or []) 
    def _recall_memory_resonance(
        self,
        *,
        snapshot=None,
        user_text: str = "",
        channel: str = "",
        fragments: tuple[str, ...] = (),
    ):
        recall = getattr(getattr(self, "memory_core", None), "recall", None)
        if not callable(recall):
            self.active_memory_resonance = None
            return None
        try:
            query = " ".join(str(item) for item in (channel, user_text, *tuple(fragments or ()), self._memory_query_from_snapshot(snapshot)) if str(item or "").strip())
            report = recall(query)
        except Exception as exc:
            self.logger.warning("Memory resonance activation error: %s", exc)
            self.active_memory_resonance = None
            return None
        self.active_memory_resonance = report
        return report
    def _memory_attention_lines(self) -> tuple[str, ...]:
        report = getattr(self, "active_memory_resonance", None)
        to_attention_lines = getattr(report, "to_attention_lines", None)
        if not callable(to_attention_lines):
            return ()
        try:
            return tuple(to_attention_lines())
        except Exception as exc:
            self.logger.warning("Memory resonance attention render error: %s", exc)
            return ()
    def _norm_deviation_texts(self, snapshot) -> tuple[str, ...]:
        return ()
    def _note_norm_observation(self, snapshot) -> None:
        return
    def _memory_query_from_snapshot(self, snapshot) -> str:
        if snapshot is None:
            return ""
        parts = []
        for attr in ("focus_summary", "active_window_kind", "active_app", "active_window"):
            value = str(getattr(snapshot, attr, "") or "").strip()
            if value:
                parts.append(value)
        return " ".join(parts)
    def _event_timestamp(self, snapshot, *, started_at: float | None = None) -> str:
        captured_at = str(getattr(snapshot, "captured_at", "") or getattr(snapshot, "time", "") or "").strip()
        if captured_at:
            return captured_at
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started_at or time.time()))
    def _commit_chat_decision(self, decision: Decision, fe_plan, *, frame: CognitiveFrame | None = None) -> None:
        self.fe_style_memory = self.fe_renderer.remember_style(
            self.fe_style_memory,
            plan=fe_plan,
            rendered_text=decision.text,
        )
        self.last_chat_answer = decision.text
        self.last_system_action = decision.system_action
        self._append_chat_history("assistant", decision.text)
        if len(self.chat_history) > 32:
            self.chat_history = self.chat_history[-32:]

        self._apply_position_update(decision)
        if frame is not None:
            frame.final_decision = self._decision_to_frame_dict(decision)
            grounding = getattr(frame, "source_grounding", None) or getattr(frame, "grounding", None)
            if grounding is not None:
                frame.final_decision["grounding_source"] = str(getattr(grounding, "grounding_source", "unknown") or "unknown")
                frame.final_decision["grounding_preempt_mode"] = str(getattr(grounding, "preempt_mode", "") or "")
                frame.final_decision["grounding_missing_evidence"] = list(getattr(grounding, "missing_evidence", ()) or ())
            self._set_cognitive_memory_update(frame, decision=decision, notes=("chat_commit",))
            self._commit_internal_state_for_frame(frame)
            self._finalize_cognitive_frame(frame)
        self.logger.info("ERIS: %s", decision.text)
        self.logger.info("[chat debug] parse_mode=%s | trace=%s", decision.parse_mode, decision.debug_trace or "<empty>")
        self.logger.info("[chat parser] %s", decision.parser_trace or "<empty>")
        self._send_decision_to_body(decision)

    def _apply_position_update(self, decision: Decision) -> None:
        intent = decision.resolve_motion_intent()
        tx = decision.resolve_motion_target_x()
        facing = decision.resolve_motion_facing()

        if intent in {"walk_to", "climb_to_top"} and 0.0 <= tx <= 1.0:
            self.inferred_pos_x = tx
        elif intent == "walk" and facing == -1:
            self.inferred_pos_x = max(0.0, self.inferred_pos_x - 0.4)
        elif intent == "walk" and facing == 1:
            self.inferred_pos_x = min(1.0, self.inferred_pos_x + 0.4)
    def _build_silent_motion_decision(self, ti_report: TiPolicyReport) -> Decision | None:
        motion_intent = str(getattr(ti_report, "motion_intent_hint", "") or "").strip()
        motion_target_x = float(getattr(ti_report, "motion_target_x_hint", -1.0) or -1.0)
        motion_facing = int(getattr(ti_report, "motion_facing_hint", 0) or 0)
        if not motion_intent:
            return None
        if motion_target_x < 0.0 and motion_facing == 0:
            return None
        return Decision(
            text="",
            animation=str(getattr(ti_report, "animation_hint", "") or "stand"),
            should_speak=False,
            confidence=0.54,
            parse_mode="motion_only",
            debug_trace=f"silent_motion; ti_mode={getattr(ti_report, 'mode', '')}",
            motion_intent=motion_intent,
            motion_target_x=motion_target_x,
            motion_facing=motion_facing,
        )
    def _build_direct_action_decision(self, user_text: str, ti_report, snapshot, *, repeat_count: int = 1) -> Decision | None:
        if self.action_router is None or self.action_executor is None:
            return None

        routed = self.action_router.route_chat(user_text, last_action=self.last_system_action)
        if not routed:
            return None

        action_name, action_input = routed
        result = self.action_executor.execute(action_name, action_input)
        text = self._action_result_to_text(result)
        if action_name == "get_now_playing" and not result.success:
            text = self._resolve_now_playing_text(snapshot) or text
        if repeat_count == 2:
            text = f"Ngài đang hỏi lại cùng một ý. {text}"
        elif repeat_count >= 3:
            text = f"Ngài đang spam cùng một ý. {text}"

        decision = Decision(
            text=text,
            animation=self._action_animation_hint(action_name, ti_report.animation_hint),
            debug_trace=f"Direct action route: {action_name}",
            parse_mode="direct_action",
            system_action=action_name,
            action_input=action_input,
        )
        if action_name in {"open_url", "focus_window", "launch_app"}:
            decision.motion_intent = "walk_to"
            decision.motion_target_x = 0.5
        return self.ti_governor.enforce_decision(decision, ti_report, user_hint=user_text)
    def _execute_system_action(self, decision: Decision, *, snapshot) -> Decision:
        if self.action_executor is None or not decision.system_action:
            return decision

        result = self.action_executor.execute(decision.system_action, decision.action_input)
        action_trace = f"action={decision.system_action}:{'ok' if result.success else 'fail'}"
        if decision.debug_trace:
            decision.debug_trace = f"{decision.debug_trace} | {action_trace}"[:240]
        else:
            decision.debug_trace = action_trace
        if not decision.text.strip():
            decision.text = self._action_result_to_text(result)
        elif decision.system_action in {"search_web", "get_weather"}:
            decision.text = self._action_result_to_text(result)
        if decision.system_action == "get_now_playing" and "media session" in decision.text.lower():
            decision.text = self._resolve_now_playing_text(snapshot) or decision.text
        return decision
    def _action_animation_hint(self, action_name: str, fallback: str) -> str:
        if action_name == "get_now_playing":
            return "read"
        if action_name in {"open_url", "focus_window", "launch_app"}:
            return "stand_walk"
        if action_name in {"copy_text", "set_volume", "play_pause_media"}:
            return "stand"
        return fallback or "stand"
    def _action_result_to_text(self, result) -> str:
        if result.action_name == "get_now_playing":
            title = result.data.get("title", "")
            artist = result.data.get("artist", "")
            if result.success and title and artist:
                return f"Tôi thấy bài đang phát là {title} của {artist}."
            if result.success and title:
                return f"Tôi thấy bài đang phát là {title}."
            return "Tôi chưa đọc được tên bài đang phát từ media session hiện tại."

        if result.action_name == "search_web":
            if not result.success:
                return result.message
            answer = (result.data.get("answer", "") or result.message or "").strip()
            query = (result.action_input or "một chủ đề lạ mặt").strip()
            if answer:
                return f"Tôi vừa kéo về một mẩu thế giới quanh {query}. {answer}"
            return f"Tôi vừa lục lại mạng cho chủ đề {query}, nhưng thứ kéo về vẫn còn quá ít để nói cho ra hồn."
        if result.action_name == "open_url":
            return f"Tôi đã gửi yêu cầu mở {result.data.get('url', result.action_input)}."
        if result.action_name == "focus_window":
            matched = result.data.get("matched_title", result.action_input)
            if result.success:
                return f"Tôi đã đưa cửa sổ {matched} lên foreground."
            return f"Tôi chưa tìm thấy cửa sổ khớp với {result.action_input}."
        if result.action_name == "set_volume":
            level = result.data.get("level", result.action_input or "mức yêu cầu")
            return f"Tôi đã gửi yêu cầu chỉnh âm lượng về khoảng {level} phần trăm." if result.success else result.message
        if result.action_name == "play_pause_media":
            return "Tôi đã gửi phím play/pause cho media session hiện tại." if result.success else result.message
        if result.action_name == "copy_text":
            return "Tôi đã đưa nội dung bạn yêu cầu vào clipboard." if result.success else result.message
        if result.action_name == "launch_app":
            command = result.data.get("command", result.action_input)
            return f"Tôi đã yêu cầu Windows mở {command}." if result.success else result.message
        return result.message or "Action đã được xử lý."
    def _resolve_now_playing_text(self, snapshot) -> str | None:
        title = self._extract_media_title_from_snapshot(snapshot)
        if not title:
            return None
        return f"Tôi thấy tab media hiện tại là {title}."
    def _extract_media_title_from_snapshot(self, snapshot) -> str:
        candidates = [snapshot.active_window, *snapshot.browser_tabs, *snapshot.open_windows]
        for candidate in candidates:
            title = self._extract_media_title(candidate)
            if title:
                return title
        return ""
    def _extract_media_title(self, raw_title: str) -> str:
        title = (raw_title or "").strip()
        if not title:
            return ""

        lowered = title.lower()
        if "youtube" in lowered:
            cleaned = title
            for suffix in (
                " - YouTube - Brave",
                " - YouTube - Google Chrome",
                " - YouTube - Microsoft Edge",
                " - YouTube",
                " - Brave",
                " - Google Chrome",
                " - Microsoft Edge",
            ):
                if cleaned.endswith(suffix):
                    cleaned = cleaned[: -len(suffix)]
            cleaned = cleaned.strip(" -|")
            if cleaned and cleaned.lower() != "youtube":
                return cleaned

        if "spotify" in lowered:
            cleaned = title
            for suffix in (
                " - Spotify Premium",
                " - Spotify",
                " - Brave",
                " - Google Chrome",
                " - Microsoft Edge",
            ):
                if cleaned.endswith(suffix):
                    cleaned = cleaned[: -len(suffix)]
            cleaned = cleaned.strip(" -|")
            if cleaned and cleaned.lower() != "spotify":
                return cleaned

        return ""
