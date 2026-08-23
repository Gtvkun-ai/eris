# -*- coding: utf-8 -*-
"""Đường chạy production của kiến trúc C.

File này cố ý không gọi Ni/Ti/Fe/appraisal/repair legacy trước main model. Những
thứ cần cho continuity đến từ StateReducer, những thứ cần cho sự thật đến từ
grounding/runtime. Main model không phải đi qua một phiên họp trước khi nói.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Mapping

from failure_meta import build_failure_meta

from runtime.no_fallback_policy import no_fallback_mode_enabled
from runtime.grounding_surface_gate import evaluate_grounded_surface, is_grounding_correction
from runtime.claim_domain_contract import validate_claim_manifest
from runtime.self_biography_guard import embodied_self_history_without_evidence
from runtime.cognition.turn_anchor import anchor_from_semantic_frame
from runtime.social_stance_policy import guard_subjective_stance_payload
from runtime.companion_model_routing import route_companion_turn
from runtime.public_reply_context import compile_public_reply_context
from runtime.affective_voice_state import project_affective_voice_state
from runtime.reply_obligation import enforce_reply_obligation
from runtime.subject_initiative_runtime import build_initiative_runtime_context
from runtime.observability import ensure_observability
from runtime.runtime_status import emit_runtime_status
from runtime.chess.surface import (
    authoritative_chess_answer_text,
    chess_move_question,
    chess_surface_text_grounded,
    chess_turn_relevant,
)
from runtime.discourse_state import assistant_proposition_link
from runtime.discourse_surface import DiscourseSurface, DiscourseSurfaceRenderer
from runtime.json_boundary import public_payload
from runtime.semantic_frame import (
    AssistantAct,
    SemanticFrame,
    validate_assistant_act,
    validate_semantic_frame,
)
from semantic_authority import SemanticAuthorityPolicy

from .contracts import AI_RUNTIME_VERSION, IntentionPlan, StateEvent
from .identity import PendingStrategyUse, PRIMARY_RELATIONSHIP_ID
from .self_turn_pipeline import SelfTurnPipeline
from .startup_grounding import (
    build_startup_fallback_text,
    build_startup_greeting_frame,
    choose_startup_text,
    collect_startup_grounding,
    ensure_grounded_startup_plan,
    ensure_startup_greeting_payload,
    select_startup_persona_preset,
)
from .opening_director import OpeningDirector
from .opening_input_assembler import build_opening_input
from .opening_history import OpeningHistoryStore
from .opening_safety import validate_opening_surface
from .self_context import build_autonomous_self_context


_LOG = logging.getLogger(__name__)


def _orchestrator_boundary_note(host: Any, operation: str, exc: Exception) -> None:
    logger = getattr(host, "logger", None)
    method = getattr(logger, "debug", None)
    if callable(method):
        try:
            method("[ai orchestrator] %s degraded: %s", operation, exc)
            return
        except Exception as log_exc:
            _LOG.debug("AI orchestrator logger failed: %s", log_exc, exc_info=log_exc)
    _LOG.debug("[ai orchestrator] %s degraded: %s", operation, exc, exc_info=exc)


def _merge_previous_public_context(grounding_context: str, previous_public_context: str) -> str:
    """Keep the reply-window public turn visible to chat planning/writing."""

    return "\n\n".join(
        part for part in (str(grounding_context or ""), str(previous_public_context or ""))
        if part.strip()
    )



class _ChatLatencyTrace:
    def __init__(self, host: Any, *, cycle_start: float, user_text: str = "") -> None:
        self.host = host
        self.user_len = len(str(user_text or ""))
        self.turn_id = ""
        self.started_perf = time.perf_counter()
        self.last_perf = self.started_perf
        try:
            self.started_wall = float(cycle_start)
        except (TypeError, ValueError):
            self.started_wall = time.time()
        self.spans: list[tuple[str, float]] = []
        self.finished = False
        try:
            raw = os.environ.get("ERIS_CHAT_LATENCY_SLOW_SPAN_MS", "750")
            self.slow_span_ms = max(0.0, float(raw))
        except (TypeError, ValueError):
            self.slow_span_ms = 750.0

    def set_turn(self, turn_id: str) -> None:
        value = str(turn_id or "").strip()
        if value:
            self.turn_id = value

    def mark(self, name: str) -> None:
        now = time.perf_counter()
        elapsed_ms = max(0.0, (now - self.last_perf) * 1000.0)
        self.last_perf = now
        label = str(name or "unknown").strip() or "unknown"
        self.spans.append((label, elapsed_ms))
        if self.slow_span_ms > 0.0 and elapsed_ms >= self.slow_span_ms:
            logger = getattr(self.host, "logger", None)
            if logger is not None:
                try:
                    logger.warning(
                        "[chat latency slow] turn=%s span=%s elapsed=%.0fms",
                        self.turn_id or "unknown",
                        label,
                        elapsed_ms,
                    )
                except Exception:
                    pass

    def finish(self, *, status: str = "ok") -> None:
        if self.finished:
            return
        self.finished = True
        total_ms = max(0.0, (time.perf_counter() - self.started_perf) * 1000.0)
        wall_ms = max(0.0, (time.time() - self.started_wall) * 1000.0)
        collapsed: dict[str, float] = {}
        for name, value in self.spans:
            collapsed[name] = collapsed.get(name, 0.0) + value
        ordered = " ".join(
            f"{name}={value:.0f}ms"
            for name, value in collapsed.items()
            if value >= 0.5
        )
        slow = ",".join(
            name
            for name, value in collapsed.items()
            if self.slow_span_ms > 0.0 and value >= self.slow_span_ms
        ) or "none"
        logger = getattr(self.host, "logger", None)
        if logger is not None:
            try:
                logger.info(
                    "[chat latency] turn=%s status=%s %s total=%.0fms e2e=%.0fms slow=%s user_chars=%d",
                    self.turn_id or "unknown",
                    str(status or "ok"),
                    ordered,
                    total_ms,
                    wall_ms,
                    slow,
                    self.user_len,
                )
            except Exception:
                pass
        try:
            from runtime.observability import GLOBAL_OBSERVABILITY

            GLOBAL_OBSERVABILITY.observe(
                "chat_orchestrator_latency_ms",
                total_ms,
                tags={"status": str(status or "ok")},
                fields={
                    "turn_id": self.turn_id,
                    "e2e_ms": round(wall_ms, 2),
                    "spans": {name: round(value, 2) for name, value in collapsed.items()},
                    "slow_spans": slow,
                },
            )
            for name, value in collapsed.items():
                GLOBAL_OBSERVABILITY.observe(
                    "chat_orchestrator_span_ms",
                    value,
                    tags={"span": name, "status": str(status or "ok")},
                    fields={"turn_id": self.turn_id},
                )
        except Exception:
            pass


def _opening_telemetry(
    host: Any,
    name: str,
    *,
    tags: Mapping[str, Any] | None = None,
    fields: Mapping[str, Any] | None = None,
    status: str = "ok",
) -> None:
    """Phát event nhỏ đã redaction; telemetry không được làm hỏng startup."""

    try:
        ensure_observability(host).log(name, tags=tags or {}, fields=fields or {}, status=status)
    except Exception as exc:
        _orchestrator_boundary_note(host, f"telemetry.{name}", exc)


def _opening_hook_subject_class(source: str, subject: str) -> str:
    """Lưu loại hook, không lưu raw OCR/URL vào history."""

    source_key = str(source or "none").strip().lower()
    text = str(subject or "").strip().lower()
    if source_key == "continuity":
        return "continuity_loop"
    if source_key == "runtime":
        return "runtime_status"
    if any(token in text for token in ("facebook", "instagram", "twitter", "x.com", "tiktok", "zalo")):
        return "social_media"
    if any(token in text for token in ("code", "python", "visual studio", "github", "terminal", "repo")):
        return "development_tool"
    return "screen_application" if source_key == "screen" else "none"


def architecture_c_enabled() -> bool:
    """Cortex V2 là kiến trúc production duy nhất.

    Không còn cờ môi trường để âm thầm quay về legacy pipeline. Bootstrap lỗi
    phải lộ rõ và dừng lượt, thay vì đổi sang một bộ contract nhận thức khác.
    """
    return True


def _deepseek_web_authority_mode() -> bool:
    provider = str(os.getenv("ERIS_REMOTE_PROVIDER", "") or "").strip().lower().replace("-", "_")
    return provider in {"deepseek_web", "ds2api", "whale2api", "whale"}


def _runtime_language() -> str:
    """Ngôn ngữ câu public của Main AI.

    Không đọc ``tts.language``: giọng/locale là tầng phát âm, không có quyền đổi
    ngôn ngữ suy nghĩ của Eris. Bản cũ ghép hai contract này nên ``auto`` ở Body
    bị chuẩn hóa thành ``ja`` và startup đột nhiên nói tiếng Nhật.
    """
    try:
        from runtime.runtime_settings_store import runtime_text
        raw = str(runtime_text("chat", "language", default="vi") or "vi").strip().lower()
    except Exception:
        raw = "vi"
    aliases = {
        "": "vi", "auto": "vi", "vn": "vi", "vi-vn": "vi", "vietnamese": "vi",
        "jp": "ja", "ja-jp": "ja", "japanese": "ja",
        "en-us": "en", "english": "en",
    }
    language = aliases.get(raw, raw)
    return language if language in {"vi", "ja", "en"} else "vi"


def _runtime_speech_language() -> str:
    """Ngôn ngữ transcript TTS do cùng semantic authority render."""
    try:
        from runtime.runtime_settings_store import runtime_text
        raw = str(runtime_text("tts", "language", default="ja") or "ja").strip().lower()
    except Exception:
        raw = "ja"
    aliases = {
        "": "ja", "auto": "ja", "jp": "ja", "ja-jp": "ja", "japanese": "ja",
        "vn": "vi", "vi-vn": "vi", "vietnamese": "vi",
        "en-us": "en", "english": "en",
    }
    language = aliases.get(raw, raw)
    return language if language in {"vi", "ja", "en"} else "ja"


def _next_ai_turn_seq(host: Any, *, fallback: int = 1) -> int:
    lock = getattr(host, "_ai_turn_seq_lock", None)
    if lock is None:
        return max(1, int(fallback or 1))
    with lock:
        host._ai_turn_seq = max(
            int(getattr(host, "_ai_turn_seq", 0) or 0),
            int(host.ai_state_reducer.snapshot().last_applied_turn_seq or 0),
        ) + 1
        return int(host._ai_turn_seq)


def _chat_commit_idempotency_key(host: Any, turn_id: str) -> str:
    """Tạo khóa commit duy nhất cho đúng một lượt chat trong đúng một phiên chạy.

    ``SessionTurnLedger`` đánh số lại từ 1 sau mỗi lần khởi động, trong khi receipt
    durable của public-turn sống qua nhiều phiên. Chỉ dùng ``session_turn:<n>`` sẽ
    làm lượt mới đụng receipt cũ và bỏ qua toàn bộ side effect UI/TTS. Khóa vì thế
    phải mang cả runtime session và lifecycle turn nhận từ transport.
    """

    runtime_session_id = str(getattr(host, "runtime_session_id", "") or "").strip()
    lifecycle_turn_id = str(
        getattr(host, "_active_public_lifecycle_turn_id", "") or ""
    ).strip()
    logical_turn_id = str(turn_id or "session_turn:unknown").strip()

    parts = ["chat"]
    if runtime_session_id:
        parts.append(runtime_session_id)
    if lifecycle_turn_id:
        parts.append(lifecycle_turn_id)
    parts.extend((logical_turn_id, "assistant"))
    return ":".join(parts)


def _typed_startup_persona_plan(*, reason: str = "typed_persona_startup") -> IntentionPlan:
    return IntentionPlan.from_mapping(
        {
            "speak": True,
            "motive": "startup_opening",
            "strategy": "persona_opening",
            "value_focus": "warm_relational_presence",
            "topic": "Offer one ordinary, warm-guarded opening with a small dry edge; no manifesto.",
            "importance": 0.72,
            "intrusion_risk": 0.05,
            "confidence": 0.74,
            "performance_hint": "soft",
            "evidence_refs": [],
            "semantics": {
                "turn_kind": "startup",
                "speech_act": "warm_session_opening",
                "subject_key": "session_arrival",
                "evidence_scope": "persona",
                "continuation_key": "none",
            },
            "notes": reason,
        },
        channel="startup",
    )


def _submit_local_startup_plan(host: Any, plan: IntentionPlan, *, turn_seq: int) -> None:
    reducer = getattr(host, "ai_state_reducer", None)
    if reducer is None or not callable(getattr(reducer, "submit", None)):
        return
    try:
        snapshot = reducer.snapshot() if callable(getattr(reducer, "snapshot", None)) else None
        base_version = int(getattr(snapshot, "version", 0) or 0)
        reducer.submit(
            StateEvent.from_intention(
                plan,
                turn_seq=turn_seq,
                base_version=base_version,
            )
        )
    except Exception as exc:
        _orchestrator_boundary_note(host, "startup_plan.submit", exc)


class _StaticIntentionPlanner:
    def __init__(self, plan: IntentionPlan) -> None:
        self.plan = plan

    def plan_autonomous(self, _snapshot: Mapping[str, Any], *, turn_seq: int = 0) -> IntentionPlan:
        return self.plan



def _serializable_public_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Chuẩn hóa payload public trước JSON và bỏ cache object typed nội bộ."""

    return public_payload(payload)


def _activate_social_plan_after_public_commit(
    host: Any,
    payload: Mapping[str, Any] | None,
    *,
    source_turn_id: str,
    source_text: str,
    source_turn_seq: int,
) -> dict[str, Any]:
    from .social_plan_commit import activate_social_plan_after_public_commit

    return activate_social_plan_after_public_commit(
        host,
        payload,
        source_turn_id=source_turn_id,
        source_text=source_text,
        source_turn_seq=source_turn_seq,
    )


def _authoritative_chess_result_text(report: Any, user_text: str) -> str:
    """Lấy tool result có thẩm quyền cho câu hỏi nước đi trực tiếp.

    Không dùng cho autonomous và không giả lập banter. Chỉ structured chess
    state có provenance mới được phép trả một nước analyzer đã tính.
    """

    if str(getattr(report, "structured_kind", "") or "") != "chess":
        return ""
    state = getattr(report, "structured_state", None) or {}
    if not state or not chess_turn_relevant(user_text, engagement_active=True):
        return ""
    return authoritative_chess_answer_text(state, user_text=user_text)


def _previous_active_proposition_root(ledger: Any) -> int:
    """Lấy root đang active mà không coi acknowledgement là proposition mới."""

    try:
        turns = ledger.all_turns()
    except Exception:
        return 0
    for turn in reversed(turns):
        if getattr(turn, "role", "") != "assistant":
            continue
        discourse = dict(getattr(turn, "meta", {}).get("discourse", {}) or {})
        root = int(
            discourse.get("active_proposition_root_turn_index", 0)
            or discourse.get("proposition_root_turn_index", 0)
            or 0
        )
        if root:
            return root
    return 0


def _decision_from_discourse_surface(host: Any, surface: DiscourseSurface, *, user_text: str):
    payload = {
        "text": surface.text,
        "should_speak": bool(surface.text),
        "animation": "stand",
        "next_animation": "stand",
        "direction": 0,
        "target_x": -1.0,
        "bounce_action": "",
        "system_action": "",
        "action_input": "",
        "delivery_hint": "focused",
        "performance_hint": surface.performance_hint,
    }
    decision = host.parser.parse(json.dumps(payload, ensure_ascii=False), user_hint=user_text)
    decision.intent = surface.intent
    decision.parse_mode = "typed_discourse"
    decision.reasoning_tags = ("answer_first", "typed_discourse", surface.intent)
    return decision


class AIChatOrchestrator:
    def __init__(self, host: Any) -> None:
        self.host = host

    def run(
        self,
        user_text: str,
        *,
        cycle_start: float,
        previous_public_context: str = "",
        previous_public_turn: Any | None = None,
        speech_interrupt_context: str = "",
        speech_interrupt_event: Any | None = None,
        speech_interrupt_reaction: Any | None = None,
    ) -> None:
        # PDF annotation, pages 7 and 19-20: a user turn is a cancellation
        # scope. Entering it preempts queued optional lanes and prevents new
        # background requests from competing with the public reply.
        from runtime.inference_broker import GLOBAL_INFERENCE_BROKER

        scope = f"user_turn:{int(float(cycle_start) * 1000)}:{id(self):x}"
        with GLOBAL_INFERENCE_BROKER.user_turn(scope):
            preempt_background = getattr(self.host, "_preempt_background_for_chat", None)
            if callable(preempt_background):
                try:
                    preempt_background("user_turn")
                except Exception as exc:
                    logger = getattr(self.host, "logger", None)
                    if logger is not None:
                        try:
                            logger.debug("background preempt failed: %s", exc)
                        except Exception:
                            pass
            result = self._run_unscoped(
                user_text,
                cycle_start=cycle_start,
                previous_public_context=previous_public_context,
                previous_public_turn=previous_public_turn,
                speech_interrupt_context=speech_interrupt_context,
                speech_interrupt_event=speech_interrupt_event,
                speech_interrupt_reaction=speech_interrupt_reaction,
            )
            frame = dict(getattr(self.host, "last_semantic_frame", {}) or {})
            act = str(frame.get("user_act", "") or "").strip().lower()
            category = (
                "small_talk"
                if act in {
                    "greeting",
                    "acknowledgement",
                    "relational_check_in",
                    "closeness_bid",
                    "repair_request",
                }
                else "tool_or_action"
                if str(frame.get("tool_intent", "none") or "none").strip().lower() not in {"", "none"}
                else "general_chat"
                if frame
                else "unknown"
            )
            GLOBAL_INFERENCE_BROKER.set_user_turn_category(scope, category)
            return result

    def _run_unscoped(
        self,
        user_text: str,
        *,
        cycle_start: float,
        previous_public_context: str = "",
        previous_public_turn: Any | None = None,
        speech_interrupt_context: str = "",
        speech_interrupt_event: Any | None = None,
        speech_interrupt_reaction: Any | None = None,
    ) -> None:
        host = self.host
        latency_trace = _ChatLatencyTrace(host, cycle_start=cycle_start, user_text=user_text)
        # Discourse resolution for fallbacks / failed turns: if previous turn failed or used repair obligation,
        # and user asks "nói lại", "gửi lại", etc., retry the specific cached failed turn text rather than
        # treating "nói lại" as a generic/new proposition.
        cached_failed_turn = getattr(host, "_cached_failed_user_turn", "")
        clean_user_text = str(user_text or "").strip().lower()
        repair_keywords = {
            "nói lại", "nhắc lại", "gửi lại", "nói lại đi", "nhắc lại xem", "nói tiếp đi",
            "gửi lại câu đó", "nói lại câu đó", "lại đi", "lại nào", "lại", "say again", "repeat",
        }
        if cached_failed_turn and (clean_user_text in repair_keywords or any(k in clean_user_text for k in ("nói lại", "nhắc lại", "gửi lại"))):
            host.logger.info(
                "[discourse resolution] User requested repair (%r); substituting with cached failed turn: %r",
                user_text,
                cached_failed_turn,
            )
            user_text = cached_failed_turn
            latency_trace.user_len = len(str(user_text or ""))
        latency_trace.mark("ingress")
        # Avoid carrying a previous turn's semantic category into telemetry when
        # the current authority call fails before producing a frame.
        host.last_semantic_frame = {}
        semantic_policy = SemanticAuthorityPolicy.from_env()
        snapshot = host.telemetry_service.capture_snapshot(
            mood_score=host.mood_score,
            inferred_pos_x=host.inferred_pos_x,
        )
        telemetry_payload = (
            snapshot.to_machine_context()
            if callable(getattr(snapshot, "to_machine_context", None))
            else {}
        )
        latency_trace.mark("snapshot")
        engagement_runtime = getattr(host, "ai_engagement_runtime", None)
        engagement_context: dict[str, Any] = {"active": False}
        engagement_prompt_context = "active_engagement: none"
        if engagement_runtime is not None:
            try:
                active_app = str(telemetry_payload.get("active_app", "") or "").strip()
                active_title = str(
                    telemetry_payload.get("active_window_title", "")
                    or telemetry_payload.get("window_title", "")
                    or ""
                ).strip()
                engagement_runtime.observe_user_message(
                    user_text,
                    now=cycle_start,
                    binding={"app": active_app, "window_title": active_title},
                )
                engagement_context = engagement_runtime.planner_context(now=cycle_start)
                engagement_prompt_context = engagement_runtime.prompt_context(now=cycle_start)
            except Exception as exc:
                host.logger.debug("[engagement] chat observation failed: %s", exc)
        latency_trace.mark("engagement")

        user_meta: dict[str, Any] = {
            "channel": "chat",
            "architecture": AI_RUNTIME_VERSION,
            "cognitive_observation_pending": True,
        }
        if speech_interrupt_event is not None and callable(getattr(speech_interrupt_event, "to_meta", None)):
            user_meta["speech_interrupt"] = speech_interrupt_event.to_meta()
        if speech_interrupt_reaction is not None and callable(getattr(speech_interrupt_reaction, "to_meta", None)):
            user_meta["speech_interrupt_reaction"] = speech_interrupt_reaction.to_meta()
        user_turn = host._ensure_session_turn_ledger().record_user(
            user_text,
            timestamp=cycle_start,
            meta=user_meta,
        )
        turn_seq = _next_ai_turn_seq(
            host,
            fallback=max(1, int(getattr(user_turn, "index", 0) or 0)),
        )
        turn_id = str(getattr(user_turn, "turn_id", "") or f"session_turn:{turn_seq}")
        latency_trace.set_turn(turn_id)
        user_meta["ai_turn_seq"] = turn_seq
        latency_trace.mark("ledger")

        # V27.1: user turn là outcome thật của một Subject intention đã được nói.
        # Chỉ đóng/revise lifecycle; không suy đoán cảm xúc hay ý định của user.
        subject_service = getattr(host, "subject_service", None)
        note_initiative_outcome = getattr(subject_service, "note_initiative_user_outcome", None)
        if callable(note_initiative_outcome):
            try:
                initiative_receipt = note_initiative_outcome(
                    user_text, now=cycle_start, evidence_ref=turn_id, persist=True,
                )
                waiting = [
                    item for item in initiative_receipt.get("pending_intentions", ())
                    if isinstance(item, Mapping) and str(item.get("status") or "") in {"satisfied", "revised"}
                    and float(item.get("last_outcome_at", 0.0) or 0.0) == float(cycle_start)
                ] if isinstance(initiative_receipt, Mapping) else []
                if waiting:
                    host.logger.info(
                        "[subject initiative] user outcome resolved=%s statuses=%s",
                        len(waiting),
                        ",".join(str(item.get("status") or "") for item in waiting),
                    )
            except Exception as exc:
                host.logger.debug("[subject initiative] user outcome update failed: %s", exc)
        latency_trace.mark("initiative_outcome")

        # V69: user turn là outcome của semantic expression gần nhất. Cập nhật
        # receptivity/completion trước khi planner tạo desire mới. Đây là state
        # transition, không phải keyword blacklist và không veto một commitment
        # đã tồn tại.
        consummation_runtime = getattr(host, "expression_consummation_runtime", None)
        observe_consumption = getattr(consummation_runtime, "observe_user_turn", None)
        if callable(observe_consumption):
            try:
                consume_outcome = observe_consumption(user_text, now=cycle_start)
                if isinstance(consume_outcome, Mapping) and consume_outcome.get("matched"):
                    host.logger.info(
                        "[expression consummation] applied user outcome=%s trace=%s",
                        consume_outcome.get("outcome", "neutral"),
                        consume_outcome.get("trace_id", ""),
                    )
            except Exception as exc:
                host.logger.debug("[expression consummation] user outcome degraded: %s", exc)

        # User taking the floor invalidates reserved short beats immediately and
        # updates long-horizon social outcomes before the next plan is written.
        social_continuation_runtime = getattr(host, "ai_social_continuation_runtime", None)
        if social_continuation_runtime is not None:
            try:
                social_continuation_runtime.observe_user_signal(
                    signal="text_response",
                    text=user_text,
                    now=cycle_start,
                )
            except Exception as exc:
                host.logger.debug("[social continuation] user signal failed: %s", exc)
        social_agenda_store = getattr(host, "ai_social_agenda_store", None)
        if social_agenda_store is not None:
            try:
                social_agenda_store.observe_user_turn(user_text=user_text, now=cycle_start)
            except Exception as exc:
                host.logger.debug("[social agenda] user outcome failed: %s", exc)
        random_chat_seed_reservoir = getattr(host, "ai_random_chat_seed_reservoir", None)
        if random_chat_seed_reservoir is not None:
            try:
                random_chat_seed_reservoir.observe_user_turn(now=cycle_start)
            except Exception as exc:
                host.logger.debug("[random chat seed] reservoir invalidation failed: %s", exc)
        random_chat_seed_store = getattr(host, "ai_random_chat_seed_store", None)
        if random_chat_seed_store is not None:
            try:
                seed_outcome = random_chat_seed_store.observe_user_turn(
                    user_text,
                    user_turn_id=turn_id,
                    now=cycle_start,
                )
                if seed_outcome is not None:
                    host.logger.info(
                        "[random chat seed] outcome seed=%s class=%s score=%.2f explicit=%s promoted=%s",
                        seed_outcome.seed_id,
                        seed_outcome.classification,
                        seed_outcome.score,
                        int(seed_outcome.explicit),
                        len(seed_outcome.promoted_paths),
                    )
            except Exception as exc:
                host.logger.debug("[random chat seed] user outcome failed: %s", exc)
        latency_trace.mark("agenda")

        # Một public arc phải nhường lời ngay khi user chen vào. Runtime trả lại
        # mục tiêu/beat còn dang dở cho main writer để nó thích nghi theo câu mới,
        # thay vì autonomous cố đọc punchline cũ lên đầu người dùng.
        arc_interruption_context: dict[str, Any] = {}
        conversation_arc_runtime = getattr(host, "ai_conversation_arc_runtime", None)
        if conversation_arc_runtime is not None:
            try:
                arc_interruption_context = dict(
                    conversation_arc_runtime.observe_user_turn(
                        user_text=user_text,
                        user_turn_seq=turn_seq,
                        now=cycle_start,
                    )
                    or {}
                )
            except Exception as exc:
                host.logger.debug("[conversation arc] user-turn yield failed: %s", exc)
        latency_trace.mark("arc")

        # Grounding quyết định nguồn sự thật, không quyết định cảm xúc hay wording.
        pre_grounding = host._build_chat_source_grounding_report(
            user_text=user_text,
            frame=None,
            snapshot=snapshot,
            memory_resonance=None,
            screen_image_data_uri="",
        )
        host.last_grounding_context = pre_grounding
        latency_trace.mark("pre_grounding")
        if pre_grounding is not None and not bool(getattr(pre_grounding, "memory_answer_allowed", True)):
            host.long_term_memory = []
            memory_resonance = None
            memory_context = host._filter_memory_context_for_grounding("")
            host.active_memory_resonance = None
            latency_trace.mark("memory_context")
        else:
            host.long_term_memory = host._memory_recall_texts(snapshot=snapshot)
            latency_trace.mark("memory_recall")
            memory_resonance = host._recall_memory_resonance(
                snapshot=snapshot,
                user_text=user_text,
                channel="chat",
                fragments=tuple(host._chat_history_for_llm(limit=2)) if host.chat_history else (),
            )
            latency_trace.mark("memory_resonance")
            memory_context = host._build_memory_context(snapshot, memory_resonance=memory_resonance)
            latency_trace.mark("memory_context")

        host.chat_mode = True
        host._chat_last_activity_at = time.time()
        host.logger.info("Người dùng: %s", user_text)
        latency_trace.mark("user_log")
        prior_public_history = tuple(host._chat_history_for_llm(limit=16))
        if previous_public_context and not prior_public_history:
            prior_public_history = ({"role": "assistant", "content": previous_public_context},)
        previous_assistant_for_repair = ""
        for _item in reversed(prior_public_history):
            if isinstance(_item, Mapping) and str(_item.get("role", "") or "").lower() == "assistant":
                previous_assistant_for_repair = str(_item.get("content", "") or "").strip()
                if previous_assistant_for_repair:
                    break
        grounding_correction = is_grounding_correction(user_text, previous_assistant_for_repair)

        # Unified Agent Harness: direct chat may start a multi-step execution task,
        # but only after the user turn is recorded and immediate public context is
        # known. The worker runs in parallel; the foreground reply stays Eris.
        agent_execution_route: dict[str, Any] = {
            "action": "none", "goal": "", "reason": "not_evaluated",
            "confidence": 0.0, "clarification": "",
        }
        route_agent_turn = getattr(host, "route_agent_user_turn", None)
        if callable(route_agent_turn):
            try:
                candidate = route_agent_turn(
                    user_text,
                    previous_assistant_text=previous_assistant_for_repair,
                    turn_id=turn_id,
                )
                if isinstance(candidate, Mapping):
                    agent_execution_route = dict(candidate)
                host.logger.info(
                    "[agent-route] action=%s reason=%s confidence=%.2f task=%s",
                    str(agent_execution_route.get("action", "none") or "none"),
                    str(agent_execution_route.get("reason", "") or ""),
                    float(agent_execution_route.get("confidence", 0.0) or 0.0),
                    str(agent_execution_route.get("task_id", "") or ""),
                )
            except Exception as exc:
                host.logger.warning("[agent-route] degraded: %s", exc)

        # V71: cập nhật trạng thái "hai người đang ở đâu" NGAY khi user turn vào.
        # Đây là state causal/continuity trước Subject+Neuro, không đợi post-observer
        # vài chục giây rồi mới biết câu user có thể là phản ứng với chính lời ERIS.
        from runtime.conversation_handoff import ensure_conversation_handoff_runtime
        from runtime.public_topic_boundary import ensure_public_topic_boundary_store
        topic_boundary_store = ensure_public_topic_boundary_store(host)
        # If the user themselves brings a previously closed topic back, that is an
        # explicit reopen. Do this before handoff classifies the new turn.
        try:
            topic_boundary_store.note_user_turn(user_text, now=cycle_start)
        except Exception as exc:
            host.logger.debug("[topic boundary] user reopen check degraded: %s", exc)
        handoff_runtime = ensure_conversation_handoff_runtime(host)
        # V75: trajectory giữ semantic spine riêng với pending question. User turn
        # mới resolve câu hỏi cũ nhưng không xóa chủ đề, để seed/autonomous còn
        # một anchor phát triển tiếp thay vì rơi về random social prompt.
        from runtime.conversation_trajectory import ensure_conversation_trajectory_runtime
        trajectory_runtime = ensure_conversation_trajectory_runtime(host)
        trajectory_state = trajectory_runtime.observe_user_turn(
            user_text,
            turn_ref=turn_id,
            turn_index=user_turn.index,
            previous_assistant_text=previous_assistant_for_repair,
            now=cycle_start,
        )
        from runtime.conversation_courtesy import ensure_conversation_courtesy
        from runtime.life_horizon import ensure_life_horizon_manager
        courtesy_runtime = ensure_conversation_courtesy(host)
        courtesy_runtime.observe_user_turn(turn_ref=turn_id, now=cycle_start)
        life_horizon_manager = ensure_life_horizon_manager(host)
        life_horizon_manager.observe_user_turn(turn_ref=turn_id, now=cycle_start)
        # V76: cập nhật state cá thể/nhịp tương tác ngay khi user có turn.
        from runtime.persistent_individual import ensure_persistent_individual_runtime
        persistent_individual_runtime = ensure_persistent_individual_runtime(host)
        persistent_individual_runtime.observe_user_turn(
            user_text, turn_ref=turn_id, context_key="direct_chat",
            trajectory=trajectory_state.to_dict(), now=cycle_start
        )
        _ledger_for_handoff = host._ensure_session_turn_ledger()
        _prior_turns_for_handoff = _ledger_for_handoff.recent_turns(
            before_index=user_turn.index, limit=8
        )
        _previous_assistant_turn = next(
            (item for item in reversed(_prior_turns_for_handoff) if item.role == "assistant"),
            None,
        )
        handoff_state = handoff_runtime.observe_user_turn(
            user_text,
            turn_ref=turn_id,
            turn_index=user_turn.index,
            previous_assistant_text=(
                str(getattr(_previous_assistant_turn, "text", "") or "").strip()
                or previous_assistant_for_repair
            ),
            previous_assistant_turn_ref=(
                f"session-turn:{getattr(_previous_assistant_turn, 'index', 0)}"
                if _previous_assistant_turn is not None else ""
            ),
            previous_assistant_turn_index=int(
                getattr(_previous_assistant_turn, "index", 0) or 0
            ),
            now=cycle_start,
        )
        if bool(getattr(handoff_state, "topic_closed", False)):
            # User explicitly closed/moved past the current topic. Persist a small
            # topic fingerprint so restart cannot resurrect the same public thread.
            # Private cognition stays intact; only public projection is bounded.
            try:
                topic_boundary_store.close_topic(
                    user_text,
                    context_text=(
                        str(getattr(_previous_assistant_turn, "text", "") or "").strip()
                        or previous_assistant_for_repair
                    ),
                    reason="user_topic_closure",
                    now=cycle_start,
                )
            except Exception as exc:
                host.logger.debug("[topic boundary] persist closure degraded: %s", exc)
            for _runtime_name in ("mental_material_runtime", "expression_urge_runtime"):
                _runtime = getattr(host, _runtime_name, None)
                _boundary = getattr(_runtime, "mark_conversation_boundary", None)
                if callable(_boundary):
                    try:
                        _boundary(now=cycle_start, reason="user_topic_closure")
                    except Exception as exc:
                        host.logger.debug("[conversation rhythm] %s boundary failed: %s", _runtime_name, exc)

        # V43: user turn là affect event THẬT trước public writer. Không đợi
        # post-observer vài giây rồi để câu hiện tại vẫn dùng mood cũ. Event ID
        # theo turn_id nên retry cùng lượt không làm state nhảy lần hai.
        previous_user_for_affect = ""
        for _item in reversed(prior_public_history):
            if isinstance(_item, Mapping) and str(_item.get("role", "") or "").lower() in {"user", "human"}:
                previous_user_for_affect = str(_item.get("content", "") or "").strip()
                if previous_user_for_affect:
                    break
        affect_runtime = getattr(host, "affective_dynamics_runtime", None)
        affect_ingest = getattr(affect_runtime, "ingest_user_turn", None)
        if callable(affect_ingest):
            try:
                affect_ingest(
                    user_text,
                    turn_id=turn_id,
                    previous_assistant_text=previous_assistant_for_repair,
                    previous_user_text=previous_user_for_affect,
                    now=cycle_start,
                )
            except Exception as exc:
                host.logger.debug("[affect-v43] user event degraded: %s", exc)
        latency_trace.mark("prior_history")
        host._append_chat_history("user", user_text)
        latency_trace.mark("append_history")
        ingest_hot = getattr(host, "_ingest_user_turn_memory_hot_path", None)
        if callable(ingest_hot):
            try:
                ingest_hot(user_text, turn_id=turn_id)
            except Exception as exc:
                host.logger.warning("[memory hot path] user turn ingest failed: %s", exc)
        latency_trace.mark("hot_memory")
        merge_addressing = getattr(host, "_merge_user_addressing_context", None)
        if callable(merge_addressing):
            memory_context = merge_addressing(memory_context)
        latency_trace.mark("addressing_merge")

        host._chat_snapshot_for_vision = snapshot
        try:
            screen_image_data_uri = host._capture_screen_frame_for_chat(
                user_text,
                previous_public_turn=previous_public_turn,
            )
        finally:
            host._chat_snapshot_for_vision = None
        latency_trace.mark("screen")
        grounding_report = host._build_chat_source_grounding_report(
            user_text=user_text,
            frame=None,
            snapshot=snapshot,
            memory_resonance=memory_resonance,
            screen_image_data_uri=screen_image_data_uri,
        )
        host.last_grounding_context = grounding_report
        if grounding_report is not None and not bool(getattr(grounding_report, "memory_answer_allowed", True)):
            memory_context = host._filter_memory_context_for_grounding(memory_context)
        try:
            host._log_chat_source_grounding(grounding_report)
        except Exception as exc:
            _orchestrator_boundary_note(host, "chat_grounding.log", exc)
        latency_trace.mark("grounding")

        # Nạp scene vào DeepSeek Semantic Tutor theo sự kiện. Chat chỉ chờ một
        # budget rất nhỏ; nếu packet chưa xong thì nhận raw OCR/structured facts
        # an toàn, không đứng khựng giữa câu vì một worker nền đang suy nghĩ.
        semantic_prompt_context = ""
        semantic_tutor = getattr(host, "semantic_tutor_runtime", None)
        if semantic_tutor is not None:
            try:
                screen_snapshot = None
                screen_store = getattr(host, "screen_evidence_store", None)
                if screen_store is not None and callable(getattr(screen_store, "snapshot", None)):
                    screen_snapshot = screen_store.snapshot()
                chess_state = {}
                chess_bridge = getattr(host, "chess_bridge_service", None)
                if chess_bridge is not None and callable(getattr(chess_bridge, "current_surface_state", None)):
                    chess_state = chess_bridge.current_surface_state()
                explicit_screen = False
                screen_request = getattr(host, "_looks_like_screen_vision_request", None)
                if callable(screen_request):
                    explicit_screen = bool(screen_request(user_text))
                semantic_tutor.observe(
                    channel="chat",
                    telemetry=telemetry_payload,
                    screen_context=screen_snapshot,
                    vision_facts=tuple(getattr(host, "vision_facts", ()) or ()),
                    chess_state=chess_state,
                    user_text=user_text,
                    explicit=explicit_screen,
                )
                semantic_prompt_context = semantic_tutor.prompt_context(channel="chat")
            except Exception as exc:
                host.logger.debug("[semantic-tutor] chat context failed: %s", exc)
        latency_trace.mark("semantic_tutor")

        # Đảm bảo pending strategy của lượt trước đã vào single-writer trước khi
        # observer dùng phản ứng user hiện tại để chấm hậu quả.
        host.ai_state_reducer.wait_idle(0.15)
        mind_state = host.ai_state_reducer.snapshot()
        latency_trace.mark("state_wait")

        # Semantic authority phải phân loại conversation act trước khi runtime
        # quyết định dùng session ledger hay long-term memory. Không còn bước
        # regex đứng trước model, vì chính bước đó từng biến vài câu mới thành
        # một cuộc săn marker vô tận.
        discourse_context = ""
        build_discourse_context = getattr(host, "_build_discourse_prompt_context", None)
        if callable(build_discourse_context):
            try:
                discourse_context = str(
                    build_discourse_context(current_turn_index=user_turn.index) or ""
                )
            except Exception as exc:
                host.logger.debug("[typed discourse] prompt context failed: %s", exc)
        if arc_interruption_context:
            arc_prompt = (
                "CONVERSATION_ARC_INTERRUPTION:\n"
                + json.dumps(arc_interruption_context, ensure_ascii=False, separators=(",", ":"))
            )
            discourse_context = "\n\n".join(
                part for part in (discourse_context, arc_prompt) if str(part).strip()
            )

        # Handoff là discourse authority bổ sung, không nhét vào grounding/evidence.
        # Nó nói "đang nợ lượt nào / reaction có thể do ai gây ra", không nói
        # current-world fact. Public writer nhận cùng object mà Subject/Neuro sẽ nhận.
        discourse_context = "\n\n".join(
            part for part in (
                discourse_context,
                handoff_runtime.prompt_context(),
                life_horizon_manager.prompt_context(now=cycle_start),
            )
            if str(part).strip()
        )

        # V39: mood sống phải tới được public writer. Personality chỉ là shape;
        # affective voice state mới là authority cho cường độ/hướng cảm xúc.
        # Đặt block này TRƯỚC personality summary để hard-budget vẫn giữ được
        # state động thay vì cắt nó rồi chỉ còn personality tĩnh.
        affective_voice = project_affective_voice_state(
            host,
            mind_state=mind_state,
            channel="chat",
            now=cycle_start,
        )
        personality_context = "\n\n".join(
            part for part in (
                affective_voice.prompt_context(),
                mind_state.personality_prompt_context(),
            )
            if str(part).strip()
        )
        host.logger.info(
            "[affective voice] channel=chat version=%s valence=%+.2f arousal=%.2f curiosity=%.2f social=%.2f delight=%.2f play=%.2f irritation=%.2f sadness=%.2f expressive=%.2f trajectory=%.2f",
            affective_voice.version,
            affective_voice.valence,
            affective_voice.arousal,
            affective_voice.curiosity,
            affective_voice.social_energy,
            affective_voice.delight,
            affective_voice.playfulness,
            affective_voice.irritation,
            affective_voice.sadness,
            affective_voice.expressive_drive,
            affective_voice.trajectory_strength,
        )
        relationship_context = mind_state.relationship.prompt_summary()
        if social_agenda_store is not None:
            try:
                agenda_prompt_context = social_agenda_store.prompt_context(now=cycle_start)
            except Exception as exc:
                agenda_prompt_context = ""
                host.logger.debug("[social agenda] prompt context failed: %s", exc)
            if agenda_prompt_context:
                relationship_context = "\n\n".join(
                    part for part in (relationship_context, agenda_prompt_context) if str(part).strip()
                )
        grounding_context = str(getattr(grounding_report, "prompt_context", "") or "")
        grounding_context = _merge_previous_public_context(grounding_context, previous_public_context)
        build_agent_runtime_context = getattr(host, "_agent_execution_prompt_context", None)
        if callable(build_agent_runtime_context):
            try:
                agent_runtime_context = str(build_agent_runtime_context() or "")
            except Exception as exc:
                agent_runtime_context = ""
                host.logger.debug("[agent-harness] prompt context failed: %s", exc)
            if agent_runtime_context:
                grounding_context = "\n\n".join(
                    part for part in (grounding_context, agent_runtime_context) if str(part).strip()
                )
        agent_action = str(agent_execution_route.get("action", "none") or "none").strip().lower()
        if agent_action in {"execute", "consult"}:
            task_id_for_public = str(agent_execution_route.get("task_id", "") or "")
            start_status = str(agent_execution_route.get("start_status", "") or "")
            is_consult = agent_action == "consult"
            grounding_context = "\n\n".join(part for part in (
                grounding_context,
                "AGENT_EXECUTION_V2: " + json.dumps({
                    "action": "started" if start_status == "started" else "unavailable",
                    "mode": "inspect" if is_consult else "execute",
                    "task_id": task_id_for_public,
                    "goal": str(agent_execution_route.get("goal", "") or "")[:1600],
                    "reason": str(agent_execution_route.get("reason", "") or ""),
                    "rule": (
                        "A backstage Gemini/LangGraph inspect-only consultation has started. Acknowledge briefly; do not claim it changed files. "
                        "The Agent Console shows live evidence and Eris remains the frontstage speaker."
                        if is_consult else
                        "A backstage Gemini/LangGraph execution task has been started in parallel. "
                        "Acknowledge briefly and honestly; do not claim completion yet. The Agent Console shows live progress. "
                        "Do not launch a duplicate runtime capability for the same multi-step task."
                    ),
                }, ensure_ascii=False, separators=(",", ":")),
            ) if str(part).strip())
        elif agent_action == "clarify":
            grounding_context = "\n\n".join(part for part in (
                grounding_context,
                "AGENT_AMBIGUITY_GATE_V1: " + json.dumps({
                    "action": "ask_user_before_execution",
                    "goal": str(agent_execution_route.get("goal", "") or "")[:1600],
                    "reason": str(agent_execution_route.get("reason", "") or ""),
                    "clarification_guidance": str(agent_execution_route.get("clarification", "") or "")[:1800],
                    "rule": (
                        "Do not execute or pretend to choose a branch. Ask one compact, concrete clarification that exposes the materially different paths. "
                        "Prefer 2-4 meaningful options based on the immediately preceding conversation instead of a generic 'what do you want?'."
                    ),
                }, ensure_ascii=False, separators=(",", ":")),
            ) if str(part).strip())
        capability_self_context = str(agent_execution_route.get("self_model_context", "") or "").strip()
        if capability_self_context:
            grounding_context = "\n\n".join(
                part for part in (grounding_context, capability_self_context) if str(part).strip()
            )
        if semantic_prompt_context:
            grounding_context = "\n\n".join(
                part for part in (grounding_context, semantic_prompt_context) if str(part).strip()
            )
        vision_status_context = ""
        build_vision_status = getattr(host, "_chat_vision_status_prompt_context", None)
        if callable(build_vision_status):
            try:
                vision_status_context = str(
                    build_vision_status(screen_image_data_uri=screen_image_data_uri) or ""
                )
            except Exception as exc:
                host.logger.debug("[vision status] prompt context failed: %s", exc)
        if vision_status_context:
            # PATCH: source grounding có thể nói “có frame”, nhưng nếu grounded_claims=0
            # public writer phải giữ stance trung thực, không mở bằng “đang nhìn đây”.
            grounding_context = "\n\n".join(
                part for part in (grounding_context, vision_status_context) if str(part).strip()
            )
        preference_context = str(
            getattr(host, "_expression_boundary_preference_context", "") or ""
        ).strip()
        if preference_context:
            grounding_context = "\n\n".join(
                part for part in (grounding_context, preference_context) if str(part).strip()
            )
        if grounding_correction:
            grounding_context = "\n\n".join((
                grounding_context,
                "DETERMINISTIC_GROUNDING_REPAIR: User is correcting a current-world/perception claim from ERIS's immediately previous line. "
                "Treat this as factual/perception repair, not subjective disagreement. Briefly concede the unsupported claim, do not defend it, "
                "state the corrected epistemic stance, then answer naturally without inventing new sensory evidence.",
            ))
        # V6 Public Writer Recovery: semantic_frame từ writer vẫn là authority khi
        # có mặt và hợp lệ, nhưng nó là soft metadata ở availability boundary.
        # Một metadata lỗi không còn quyền xóa câu public; runtime sẽ sanitize về
        # typed default rồi observer hậu kỳ tiếp tục cập nhật continuity.
        latency_trace.mark("context")
        user_meta["semantic_authority"] = "semantic_frame.v1"
        discovery_runtime = getattr(host, "ai_discovery_runtime", None)
        discovery_context = (
            discovery_runtime.planner_context(telemetry_payload)
            if discovery_runtime is not None
            else {}
        )
        try:
            from runtime.environment_awareness import ensure_environment_awareness_hub
            _environment_awareness = ensure_environment_awareness_hub(host).refresh(
                machine_snapshot=snapshot,
                now=cycle_start,
                source="chat_planning",
            )
        except Exception as exc:
            host.logger.debug("[environment awareness] chat planning refresh failed: %s", exc)
            _environment_awareness = None
        planning_snapshot = {
            "event_kind": "chat",
            "user_text": user_text,
            "recent_public_history": host._chat_history_for_llm(limit=8)[:-1],
            "personality_summary": personality_context,
            "affective_voice_state": affective_voice.to_dict(),
            "affective_voice_context": affective_voice.prompt_context(),
            "identity": mind_state.identity.panel_view(),
            "identity_summary": mind_state.identity_prompt_context(),
            "relationship_summary": relationship_context,
            "grounding_context": grounding_context,
            "environment_awareness": _environment_awareness.to_dict(now=cycle_start) if _environment_awareness is not None else {},
            "environment_awareness_context": _environment_awareness.prompt_context(now=cycle_start) if _environment_awareness is not None else "",
            "memory_available": bool(str(memory_context or "").strip()),
            "interrupt_context": speech_interrupt_context,
            "discovery": discovery_context,
            "engagement_context": engagement_context,
            "discourse_context": discourse_context,
            "conversation_handoff": handoff_state.to_dict(),
            "conversation_trajectory": trajectory_state.to_dict(),
            "conversation_courtesy": courtesy_runtime.runtime_context(now=cycle_start),
            "life_horizon": life_horizon_manager.refresh_from_runtime(now=cycle_start).to_dict(),
            "persistent_individual": persistent_individual_runtime.projection_for_host(
                host, now=cycle_start, context_key="direct_chat"
            ),
            "causal_discourse": {
                "self_caused_reaction_probability": handoff_state.self_caused_reaction_probability,
                "repair_needed": handoff_state.repair_needed,
                "hypotheses": [item.to_dict() for item in handoff_state.causal_hypotheses],
            },
            "conversation_repair_proposal": handoff_runtime.repair_action_proposal() or {},
            "conversation_arc_interruption": arc_interruption_context,
            "user_addressing": (
                host._user_addressing_snapshot()
                if callable(getattr(host, "_user_addressing_snapshot", None))
                else {}
            ),
            "shared_semantic_context": (
                semantic_tutor.planner_context()
                if semantic_tutor is not None and callable(getattr(semantic_tutor, "planner_context", None))
                else {}
            ),
        }
        # V40: direct chat cũng đọc cùng ActiveConcern projection với autonomous.
        # Concern chỉ tạo continuity context; user turn vẫn là foreground authority.
        concern_runtime = getattr(host, "active_concern_runtime", None)
        concern_snapshot = getattr(concern_runtime, "snapshot", None)
        if callable(concern_snapshot):
            try:
                active_concerns = tuple(concern_snapshot(now=cycle_start, limit=8) or ())
                planning_snapshot["active_concerns"] = [dict(item) for item in active_concerns]
            except Exception as exc:
                host.logger.debug("[active concern] chat projection failed: %s", exc)

        # V26: chat và self-turn dùng cùng motive context. User turn không reset
        # pending intention; nó chỉ là một observation origin=user đi vào MindLoop.
        try:
            planning_snapshot["initiative_runtime_context"] = build_initiative_runtime_context(host)
        except Exception as exc:
            host.logger.debug("[subject initiative] chat context unavailable: %s", exc)
            planning_snapshot["initiative_runtime_context"] = {}

        # Đồng bộ open-loop/shared-goal thật vào cùng handoff. Nếu user vừa tạo
        # repair thì repair giữ foreground; shared goal vẫn nằm ở field riêng để
        # autonomous tiếp tục sau khi sửa hiểu lầm.
        _initiative_ctx = planning_snapshot.get("initiative_runtime_context")
        _initiative_ctx = _initiative_ctx if isinstance(_initiative_ctx, Mapping) else {}
        handoff_state = handoff_runtime.refresh_shared_goal(
            _initiative_ctx.get("active_goal_text", ""),
            evidence_refs=tuple(_initiative_ctx.get("active_goal_evidence_refs", ()) or ()),
            now=cycle_start,
        )
        planning_snapshot["conversation_handoff"] = handoff_state.to_dict()
        # Refresh sau build_initiative_runtime_context để mọi lane đọc cùng revision.
        trajectory_state = trajectory_runtime.snapshot(now=cycle_start)
        planning_snapshot["conversation_trajectory"] = trajectory_state.to_dict()
        planning_snapshot["conversation_courtesy"] = courtesy_runtime.runtime_context(now=cycle_start)
        planning_snapshot["life_horizon"] = life_horizon_manager.refresh_from_runtime(now=cycle_start).to_dict()
        planning_snapshot["persistent_individual"] = persistent_individual_runtime.projection_for_host(
            host, now=cycle_start, context_key="direct_chat"
        )
        planning_snapshot["causal_discourse"] = {
            "self_caused_reaction_probability": handoff_state.self_caused_reaction_probability,
            "repair_needed": handoff_state.repair_needed,
            "hypotheses": [item.to_dict() for item in handoff_state.causal_hypotheses],
        }
        planning_snapshot["conversation_repair_proposal"] = (
            handoff_runtime.repair_action_proposal() or {}
        )
        # Cập nhật lại prompt sau refresh để writer và Neuro không đọc hai state lệch revision.
        _handoff_marker = "CONVERSATION_HANDOFF_V71"
        if _handoff_marker not in discourse_context:
            discourse_context = "\n\n".join(
                part for part in (discourse_context, handoff_runtime.prompt_context()) if str(part).strip()
            )
        else:
            # prompt cũ đã được append trước active-goal refresh; thay block bằng
            # state mới một cách đơn giản bằng cách lấy phần typed discourse trước marker.
            discourse_context = discourse_context.split(_handoff_marker, 1)[0].rstrip()
            discourse_context = "\n\n".join(
                part for part in (discourse_context, handoff_runtime.prompt_context()) if str(part).strip()
            )
        planning_snapshot["discourse_context"] = discourse_context

        temporal = getattr(host, "temporal_mind", None)
        temporal_prompt = ""
        render_temporal = getattr(temporal, "prompt_context", None)
        if callable(render_temporal):
            try:
                temporal_prompt = str(render_temporal(now=cycle_start) or "")
            except Exception as exc:
                host.logger.debug("[temporal mind] prompt projection failed: %s", exc)
        if temporal_prompt:
            # Giữ timing projection ở field riêng. Không nhét nó vào grounding_context
            # vì nhịp không phải evidence và không được giả dạng nguồn sự thật.
            planning_snapshot["temporal_mind"] = temporal_prompt
            planning_snapshot["timing_context"] = temporal_prompt

        # Subject Core chuẩn bị nền; Executive cam kết coalition; Subject Core
        # mới materialize MindDecision và authorship. Planner phía sau chỉ realize,
        # không được dựng một động cơ thứ hai vì con người đã có đủ hội đồng rồi.
        latency_trace.mark("planning_context")
        subject_ingress = getattr(host, "subject_ingress", None)
        if subject_ingress is None:
            raise RuntimeError("Subject Core ingress is required")
        subject_decision = subject_ingress.observe_user_turn(
            user_text,
            created_at=cycle_start,
            turn_id=turn_id,
            planning_context=planning_snapshot,
        )
        subject_payload = subject_decision.to_dict()
        planning_snapshot["subject_decision"] = subject_payload

        # V56: appraisal theo goal đã có authority ở Subject Core thì phải thật sự
        # điều tiết current affect, thay vì nằm trong log rồi bị quên. Social event
        # gốc đã chạy trước đó; bước này chỉ thêm một delta nhỏ, idempotent theo
        # appraisal_id và không suy diễn cảm xúc của user.
        subject_service = getattr(host, "subject_service", None)
        latest_appraisals = getattr(subject_service, "latest_appraisals", None)
        affect_goal_ingest = getattr(affect_runtime, "ingest_subject_appraisal", None)
        if callable(latest_appraisals) and callable(affect_goal_ingest):
            try:
                for _appraisal in tuple(latest_appraisals() or ())[:4]:
                    affect_goal_ingest(_appraisal, now=cycle_start)
            except Exception as exc:
                host.logger.debug("[affect-v56] subject appraisal modulation degraded: %s", exc)

        parallel_state_fn = getattr(subject_ingress, "parallel_cognition_state", None)
        parallel_state = (
            parallel_state_fn(turn_id)
            if callable(parallel_state_fn)
            else {"deep_thought_running": False, "may_follow_up": False, "policy": "parallel_nonblocking"}
        )
        planning_snapshot["parallel_cognition"] = dict(parallel_state or {})
        latency_trace.mark("subject")
        if bool((parallel_state or {}).get("deep_thought_running", False)):
            grounding_context = "\n\n".join(part for part in (
                grounding_context,
                "PARALLEL COGNITION STATUS: a bounded deep review is running for this same turn. "
                "Do not wait for it and do not withhold the useful answer available now. Give the best provisional answer now. "
                "Only when the issue is genuinely consequential may you naturally mention that you are still considering it and may follow up. "
                "Never expose worker/model/Neuro implementation details and never ask the user to wait for routine conversation.",
            ) if str(part).strip())
            planning_snapshot["grounding_context"] = grounding_context
        subject_inner_view = {}
        inner_view_fn = getattr(subject_service, "inner_view", None)
        if callable(inner_view_fn):
            try:
                candidate = inner_view_fn()
                if isinstance(candidate, Mapping):
                    subject_inner_view = dict(candidate)
            except Exception:
                subject_inner_view = {}
        planning_snapshot["subject_inner_state"] = subject_inner_view
        action_executor = getattr(host, "action_executor", None)
        set_parent_decision = getattr(action_executor, "set_subject_parent_decision", None)
        if callable(set_parent_decision):
            set_parent_decision(subject_decision)
        subject_context = (
            "SUBJECT/EXECUTIVE COMMIT (authoritative internal record): "
            + json.dumps(subject_payload, ensure_ascii=False, separators=(",", ":"))
            + ". BOUNDED INNER STATE: "
            + json.dumps(subject_inner_view, ensure_ascii=False, separators=(",", ":"))
            + ". Preserve semantic commitments, value/need pressure and action authorship. "
              "Do not invent a different motive merely to improve wording. "
              "The inner state is a projection, not a factual claim about the user."
        )
        grounding_context = "\n\n".join(
            part for part in (grounding_context, subject_context) if str(part).strip()
        )
        planning_snapshot["grounding_context"] = grounding_context

        # The capability selector is execution-facing only. Subject Core owns
        # the internal decision; the selector may choose an exact live tool that
        # realizes it, never a second motive or personality trajectory.
        executive_directive = None
        # HOTFIX V20.1/V24.1: resolve Executive tại đúng scope của chat cycle.
        # Dòng binding này từng tồn tại ở V16 nhưng bị rơi mất trong refactor V17,
        # khiến nhánh interactive capability selector đọc một local chưa được gán.
        executive = getattr(host, "ai_executive_cortex", None)
        agent_action_for_planner = str(agent_execution_route.get("action", "none") or "none").strip().lower()
        if agent_action_for_planner in {"execute", "consult", "clarify"}:
            executive_directive = None
        elif executive is not None and bool(getattr(executive, "enabled", False)):
            try:
                executive_directive = executive.plan_interactive(
                    user_text, snapshot=planning_snapshot
                )
            except Exception as exc:
                host.logger.warning("[executive] interactive planning failed closed: %s", exc)
        directive_payload = (
            executive_directive.to_dict()
            if executive_directive is not None
            and callable(getattr(executive_directive, "to_dict", None))
            else {
                "schema": "eris.interactive_executive_directive.v2",
                "status": "unavailable",
                "capability_id": "",
                "capability_arguments": {},
                "semantic_goal": "",
                "reason": (
                    "agent_harness_owns_execution" if agent_action_for_planner == "execute"
                    else "agent_harness_owns_consult" if agent_action_for_planner == "consult"
                    else "agent_ambiguity_requires_user" if agent_action_for_planner == "clarify"
                    else "executive_unavailable"
                ),
                "confidence": 0.0,
            }
        )
        planning_snapshot["executive_directive"] = directive_payload
        directive_context = (
            "EXECUTIVE CAPABILITY DIRECTIVE (runtime authority): "
            + json.dumps(directive_payload, ensure_ascii=False)
            + ". Do not invent, rename, or deny a capability beyond this directive. "
              "When status=unavailable, state uncertainty rather than claiming ERIS cannot perform it."
        )
        grounding_context = "\n\n".join(
            part for part in (grounding_context, directive_context) if str(part).strip()
        )
        planning_snapshot["grounding_context"] = grounding_context

        latency_trace.mark("executive")
        chat_plan = host.ai_intention_planner.plan_chat(
            planning_snapshot,
            turn_seq=turn_seq,
        )
        plan_data = chat_plan.to_dict()
        if str(directive_payload.get("status", "") or "") == "selected":
            plan_data["tool_intent"] = str(directive_payload.get("capability_id", "") or "")
            # Typed arguments stay typed until ActionExecutor.execute_capability.
            # Public wording models never receive authority to reinterpret them.
            plan_data["tool_input"] = ""
        else:
            # No second semantic authority: legacy planner tool guesses are removed.
            plan_data["tool_intent"] = ""
            plan_data["tool_input"] = ""
        plan_data["notes"] = (
            str(plan_data.get("notes", "") or "")
            + f"; capability_planner={directive_payload.get('status', 'unavailable')}:"
              f"{directive_payload.get('reason', '')}"
        ).strip("; ")
        chat_plan = IntentionPlan.from_mapping(plan_data, channel="chat")
        discovery_id = ""
        if discovery_runtime is not None:
            chat_plan, discovery_grounding, discovery_id = discovery_runtime.bind_plan(chat_plan)
            if discovery_grounding:
                grounding_context = "\n".join(part for part in (grounding_context, discovery_grounding) if part)
            elif str(getattr(chat_plan, "strategy", "") or "").strip().lower() == "share_discovery":
                data = chat_plan.to_dict()
                data.update({
                    "strategy": "direct_answer",
                    "topic": (
                        "Answer honestly that no verified discovery is ready yet, or use a real current activity if present. "
                        "Do not invent a fact merely because the user asked for something interesting."
                    ),
                    "evidence_refs": [],
                })
                chat_plan = IntentionPlan.from_mapping(data, channel="chat")
        latency_trace.mark("planner")
        user_message = host.parser.build_chat_user_message(
            user_message=user_text,
            last_chat_answer=host.last_chat_answer,
        )
        history = host._chat_history_for_llm(limit=16)[:-1]
        route_decision = route_companion_turn(user_text, recent_history=history)
        use_escalation = bool(route_decision.use_pro and not _deepseek_web_authority_mode())
        reasoning_effort = route_decision.reasoning_effort
        thinking_mode = route_decision.thinking_mode
        routing_context = route_decision.prompt_context()
        host.last_companion_model_route = route_decision.to_dict()

        # V73: positive evidence enrichment for foreground chat too. Memory/user
        # facts are selected first with provenance; the public writer then gets
        # both the semantic inventory and the exact refs it may cite.
        chat_evidence_bundle: dict[str, Any] = {}
        chat_enriched_refs: tuple[str, ...] = ()
        chat_enriched_domains: tuple[str, ...] = ()
        try:
            from runtime.evidence_enrichment import compiler_for
            chat_bundle = compiler_for(host).compile(
                speech_act=str(getattr(getattr(chat_plan, "semantics", None), "speech_act", "") or "direct_reply"),
                semantic_goal=str(getattr(chat_plan, "motive", "") or ""),
                topic=str(getattr(chat_plan, "topic", "") or ""),
                current_user_text=user_text,
                recent_history=history,
            )
            chat_evidence_bundle = chat_bundle.to_dict()
            chat_enriched_refs = chat_bundle.evidence_refs
            chat_enriched_domains = chat_bundle.claim_domains
            host.logger.info(
                "[evidence enrichment] channel=chat user_facts=%s episodes=%s self_facts=%s",
                len(chat_bundle.user_facts), len(chat_bundle.shared_episodes), len(chat_bundle.self_facts),
            )
        except Exception as exc:
            host.logger.debug("[evidence enrichment] chat compile failed: %s", exc)

        # V42: public writer được quyền viết tự nhiên nhưng không được tự mở thêm
        # miền sự thật. Contract này là typed provenance, không phải blacklist từ.
        chat_claim_domains = {
            "user_statement", "conversation_history", "internal_state",
            "opinion", "hypothetical", "self_capability", "self_preference",
        }
        chat_claim_domains.update(chat_enriched_domains)
        chat_claim_evidence_refs = set(
            str(item) for item in (getattr(grounding_report, "evidence_ids", ()) or ())
            if str(item or "").strip()
        )
        chat_claim_evidence_refs.update(chat_enriched_refs)
        # The foreground user message is real evidence, but give it a typed ref
        # so user_statement is no longer an evidence-exempt escape hatch.
        chat_claim_evidence_refs.add("user-statement:current-turn")
        chat_claim_evidence_refs.update(
            str(item) for item in (getattr(grounding_report, "runtime_evidence_ids", ()) or ())
            if str(item or "").strip()
        )
        chat_claim_evidence_refs.update(
            str(item) for item in (getattr(grounding_report, "structured_evidence_ids", ()) or ())
            if str(item or "").strip()
        )
        chat_claim_evidence_refs.update(
            str(item) for item in (getattr(chat_plan, "evidence_refs", ()) or ())
            if str(item or "").strip()
        )
        if bool(str(memory_context or "").strip()) and bool(getattr(grounding_report, "memory_allowed", True)):
            chat_claim_domains.add("memory")
        if bool(getattr(grounding_report, "screen_evidence_present", False)):
            chat_claim_domains.add("grounded_environment")
        if tuple(getattr(grounding_report, "runtime_evidence_ids", ()) or ()):
            chat_claim_domains.update({"verified_runtime_clock", "grounded_environment"})
        if tuple(getattr(grounding_report, "structured_evidence_ids", ()) or ()):
            chat_claim_domains.add("engagement_state")
        if discovery_id:
            chat_claim_domains.add("discovery_artifact")
        grounding_context = "\n\n".join(part for part in (
            grounding_context,
            ("EVIDENCE_ENRICHMENT_V73: " + json.dumps(chat_evidence_bundle, ensure_ascii=False, separators=(",", ":")))
            if chat_evidence_bundle else "",
            "CLAIM_DOMAIN_CONTRACT_V42: " + json.dumps({
                "allowed_domains": sorted(chat_claim_domains),
                "allowed_evidence_refs": sorted(chat_claim_evidence_refs),
                "rule": (
                    "Every factual/sensory/memory/runtime claim added to public wording must be listed in claim_manifest. "
                    "Current-environment and runtime-clock claims require an allowed evidence ref. "
                    "Do not create a new claim domain merely to make the sentence vivid."
                ),
            }, ensure_ascii=False, separators=(",", ":")),
        ) if str(part).strip())

        compiled_context = compile_public_reply_context(
            route=route_decision,
            personality=personality_context,
            relationship=relationship_context,
            grounding=grounding_context,
            memory=memory_context,
            interrupt=speech_interrupt_context,
            engagement=engagement_prompt_context,
            routing=routing_context,
            discourse=discourse_context,
        )
        host.last_public_context_compilation = compiled_context.to_dict()
        latency_trace.mark("writer_context")
        payload: dict[str, Any] = {}
        host._set_background_memory_digest_remote_inflight(True)
        try:
            payload = host.ai_model_router.generate_public_reply(
                chat_history=history,
                user_text=user_message,
                memory_context=compiled_context.memory,
                grounding_context=compiled_context.grounding,
                relationship_context=compiled_context.relationship,
                personality_context=compiled_context.personality,
                interrupt_context=compiled_context.interrupt,
                engagement_context=compiled_context.engagement,
                routing_context=compiled_context.routing,
                discourse_context=compiled_context.discourse,
                use_escalation=use_escalation,
                reasoning_effort=reasoning_effort,
                thinking_mode=thinking_mode,
                allow_fallback=False,
                language_hint=_runtime_language(),
                speech_language_hint=_runtime_speech_language(),
                planned_intention=chat_plan,
            )
            if (
                not payload
                and not no_fallback_mode_enabled()
                and not _deepseek_web_authority_mode()
            ):
                payload = host.ai_model_router.generate_public_reply(
                    chat_history=history,
                    user_text=user_message,
                    memory_context=compiled_context.memory,
                    grounding_context=compiled_context.grounding,
                    relationship_context=compiled_context.relationship,
                    personality_context=compiled_context.personality,
                    interrupt_context=compiled_context.interrupt,
                    engagement_context=compiled_context.engagement,
                    routing_context=compiled_context.routing,
                    discourse_context=compiled_context.discourse,
                    use_escalation=use_escalation,
                    reasoning_effort=reasoning_effort,
                    thinking_mode=thinking_mode,
                    allow_fallback=True,
                    language_hint=_runtime_language(),
                    speech_language_hint=_runtime_speech_language(),
                    planned_intention=chat_plan,
                    )
        finally:
            host._set_background_memory_digest_remote_inflight(False)
        latency_trace.mark("writer")

        # The public writer has finished its remote generation. Only now may the
        # queued slow Neuro review start, so it cannot steal provider capacity
        # from the reply on the human-facing critical path.
        neuro_continuation_runtime = getattr(host, "neuro_continuation_runtime", None)
        if payload:
            release_neuro = getattr(neuro_continuation_runtime, "release", None)
            if callable(release_neuro):
                try:
                    release_neuro(turn_id)
                except Exception as exc:
                    host.logger.debug("[neuro-continuation] release failed: %s", exc)
        else:
            cancel_neuro = getattr(neuro_continuation_runtime, "cancel_turn", None)
            if callable(cancel_neuro):
                try:
                    cancel_neuro(turn_id)
                except Exception as exc:
                    host.logger.debug("[neuro-continuation] cancel after empty public reply failed: %s", exc)
        latency_trace.mark("neuro_release")

        discourse_resolution = None
        assistant_discourse_meta: dict[str, Any] = {}
        deterministic_decision = None
        deterministic_source = ""
        typed_frame: SemanticFrame | None = None
        assistant_act: AssistantAct = AssistantAct()
        discourse_surface = DiscourseSurface()

        if payload:
            payload = guard_subjective_stance_payload(payload)
            typed_frame = payload.get("_typed_semantic_frame")
            if not isinstance(typed_frame, SemanticFrame):
                typed_frame = validate_semantic_frame(payload.get("semantic_frame", {})).frame
            typed_assistant_act = payload.get("_typed_assistant_act")
            if isinstance(typed_assistant_act, AssistantAct):
                assistant_act = typed_assistant_act
            else:
                assistant_act = validate_assistant_act(payload.get("assistant_act", {})).act

            if grounding_correction:
                # Trường hợp hẹp nhưng có hậu quả lớn: user đang sửa một claim
                # tri giác/current-world của ERIS. Không cho semantic frame gọi
                # nó là "bất đồng ấn tượng" rồi mở đường cho câu phòng thủ.
                corrected = typed_frame.to_dict()
                corrected.update({
                    "user_act": "correction_or_challenge",
                    "discourse_relation": "challenge_assistant_assumption",
                    "target": "assistant",
                    "ambiguity_owner": "assistant",
                    "tool_intent": "none",
                })
                obligation_data = dict(corrected.get("reply_obligation", {}) or {})
                obligation_data.update({
                    "must_answer": True,
                    "must_not_broad_clarify": True,
                    "must_not_call_tool": True,
                })
                corrected["reply_obligation"] = obligation_data
                typed_frame = validate_semantic_frame(corrected).frame
                payload["semantic_frame"] = typed_frame.to_dict()
                payload["_typed_semantic_frame"] = typed_frame

            semantic_frame = typed_frame.to_dict()
            host.last_semantic_frame = semantic_frame
            user_meta["semantic_frame"] = semantic_frame
            try:
                from runtime.observability import GLOBAL_OBSERVABILITY
                GLOBAL_OBSERVABILITY.log(
                    "semantic_frame_v1",
                    tags={
                        "user_act": typed_frame.user_act or "unknown",
                        "target": typed_frame.target or "unknown",
                        "relation": typed_frame.discourse_relation or "unknown",
                    },
                    fields={"turn_seq": turn_seq, "frame": semantic_frame},
                )
            except Exception as exc:
                _orchestrator_boundary_note(host, "semantic_frame.observability", exc)

            try:
                host._ensure_session_turn_ledger().merge_turn_meta(
                    user_turn.index,
                    {"semantic_frame": semantic_frame},
                )
            except Exception as exc:
                host.logger.debug("[typed discourse] user frame commit failed: %s", exc)

            resolve_discourse = getattr(host, "_resolve_discourse_frame", None)
            if callable(resolve_discourse):
                try:
                    discourse_resolution = resolve_discourse(
                        typed_frame,
                        current_user_turn_index=user_turn.index,
                    )
                    assistant_discourse_meta = discourse_resolution.assistant_meta(
                        user_turn_index=user_turn.index
                    )
                    assistant_discourse_meta["assistant_act"] = assistant_act.to_dict()
                    discourse_surface = DiscourseSurfaceRenderer().render(
                        discourse_resolution.action,
                        model_text=str(payload.get("text", "") or ""),
                    )
                    if discourse_surface.deterministic and discourse_surface.text:
                        deterministic_decision = _decision_from_discourse_surface(
                            host,
                            discourse_surface,
                            user_text=user_text,
                        )
                        assistant_discourse_meta["assistant_act"] = {
                            "kind": "answer",
                            "proposition_mode": "new",
                            "confidence": 1.0,
                        }
                        deterministic_source = "typed_discourse"
                except Exception as exc:
                    host.logger.debug("[typed discourse] resolution failed: %s", exc)

            # Memory query đã được semantic authority chuẩn hóa thành object typed.
            # Không gọi compiler trên raw user text thêm lần nữa.
            if (
                deterministic_decision is None
                and discourse_resolution is not None
                and discourse_resolution.memory_recall_requested
                and (grounding_report is None or bool(getattr(grounding_report, "memory_answer_allowed", True)))
            ):
                build_memory_recall = getattr(host, "_build_typed_memory_recall_decision", None)
                if callable(build_memory_recall):
                    try:
                        deterministic_decision = build_memory_recall(
                            discourse_resolution.memory_query,
                            raw_text=user_text,
                        )
                        if deterministic_decision is not None:
                            deterministic_source = "memory_recall"
                    except Exception as exc:
                        host.logger.debug("[memory recall] typed fulfillment failed: %s", exc)

            if deterministic_decision is not None:
                user_meta[f"{deterministic_source}_answer"] = True
                host.logger.info(
                    "[%s] deterministic fulfillment parse_mode=%s",
                    deterministic_source.replace("_", " "),
                    str(getattr(deterministic_decision, "parse_mode", "") or deterministic_source),
                )
                host.ai_stage_planner.apply(
                    deterministic_decision,
                    "neutral",
                    state=mind_state,
                    channel="chat",
                )
                deterministic_decision = host._execute_system_action(
                    deterministic_decision,
                    snapshot=snapshot,
                    frame=None,
                )
                public_text, assistant_meta = self._commit(
                    deterministic_decision,
                    assistant_meta_extra=assistant_discourse_meta,
                    idempotency_key=_chat_commit_idempotency_key(host, turn_id),
                )
                host.last_user_text_for_semantics = user_text
                recent_history = tuple(host._chat_history_for_llm(limit=8))
                observer_state = mind_state.to_dict()
                observer_state["semantic_frame"] = semantic_frame
                host.ai_post_turn_observer.submit(
                    turn_id=turn_id,
                    turn_seq=turn_seq,
                    user_text=user_text,
                    assistant_text=public_text,
                    recent_history=recent_history,
                    mechanical_outcomes=[],
                    state_summary=observer_state,
                    user_meta=user_meta,
                    assistant_meta=assistant_meta,
                    event_kind="chat",
                )
                latency_trace.mark("deterministic_commit")
                latency_trace.finish(status="deterministic")
                return

            if discourse_surface.text and not str(payload.get("text", "") or "").strip():
                payload["text"] = discourse_surface.text
                payload["should_speak"] = True
                payload["performance_hint"] = discourse_surface.performance_hint

            obligation = enforce_reply_obligation(
                payload,
                user_text=user_text,
                frame=typed_frame,
                language_hint=_runtime_language(),
                direct_user_turn=True,
            )
            payload = obligation.payload
            if obligation.repaired:
                host.logger.warning(
                    "[reply obligation] repaired turn=%s reason=%s",
                    turn_seq,
                    obligation.reason,
                )
                assistant_act = validate_assistant_act(payload.get("assistant_act", {})).act
                payload["_typed_assistant_act"] = assistant_act
                assistant_discourse_meta["assistant_act"] = assistant_act.to_dict()

            if grounding_correction and str(getattr(getattr(assistant_act, "kind", None), "value", "") or "") != "repair":
                # Prompt đã được neo repair từ trước; nếu writer vẫn chọn một act
                # khác (ví dụ "disagreement" -> "Không. Tôi vẫn nghĩ vậy."),
                # ép wording-only retry. Nếu provider lại hỏng thì dùng một câu
                # repair deterministic hẹp, không bịa thêm fact mới.
                repair_retry = host.ai_model_router.generate_public_reply(
                    chat_history=history,
                    user_text=user_message,
                    memory_context=compiled_context.memory,
                    grounding_context=compiled_context.grounding,
                    relationship_context=compiled_context.relationship,
                    personality_context=compiled_context.personality,
                    interrupt_context=compiled_context.interrupt,
                    engagement_context=compiled_context.engagement,
                    routing_context=compiled_context.routing,
                    discourse_context=compiled_context.discourse,
                    use_escalation=use_escalation,
                    reasoning_effort=reasoning_effort,
                    thinking_mode=thinking_mode,
                    allow_fallback=False,
                    language_hint=_runtime_language(),
                    speech_language_hint=_runtime_speech_language(),
                    planned_intention=chat_plan,
                    retry_instruction=(
                        "This is a factual/perception repair. Briefly concede that the previous current-world claim lacked evidence. "
                        "Do not defend the old claim, do not turn it into a subjective disagreement, and do not invent replacement sensory facts."
                    ),
                    locked_semantic_frame=typed_frame.to_dict(),
                )
                repair_text = str(repair_retry.get("text", "") or "").strip() if isinstance(repair_retry, Mapping) else ""
                if repair_text:
                    for _key in (
                        "text", "display_language", "speech_text", "speech_language",
                        "performance_hint", "performance_intensity", "nonverbal_cue",
                        "delivery_priority", "interruptible", "utterance_turn_id", "utterance",
                        "should_speak", "claim_manifest",
                    ):
                        if _key in repair_retry:
                            payload[_key] = repair_retry[_key]
                else:
                    from runtime.utterance_spec import degrade_surface_payload
                    payload = degrade_surface_payload(
                        payload,
                        text="Ừ, câu trước của tôi khẳng định quá tay. Tôi không có bằng chứng hiện tại để nói như vậy.",
                        language=_runtime_language(),
                        reason="grounding_correction_fail_closed",
                        performance_preset="repair",
                        should_speak=True,
                    )
                assistant_act = validate_assistant_act({
                    "kind": "repair",
                    "proposition_mode": "continue",
                    "confidence": 1.0,
                }).act
                payload["assistant_act"] = assistant_act.to_dict()
                payload["_typed_assistant_act"] = assistant_act
                assistant_discourse_meta["assistant_act"] = assistant_act.to_dict()
                host.logger.warning("[grounding repair] forced factual repair turn=%s", turn_seq)

            draft_text = str(payload.get("text", "") or "")
            if (
                str(getattr(grounding_report, "structured_kind", "") or "") == "chess"
                and draft_text
                and not chess_surface_text_grounded(
                    draft_text,
                    getattr(grounding_report, "structured_state", None) or {},
                    suggestion_only=chess_move_question(user_text),
                )
            ):
                authoritative_text = _authoritative_chess_result_text(grounding_report, user_text)
                if authoritative_text:
                    payload["text"] = authoritative_text
                    payload["should_speak"] = True
                    payload["source"] = "authoritative_chess_guard"
                    draft_text = authoritative_text
                    host.logger.warning("[chat chess] replaced invented coordinate move with authoritative suggestion")
                else:
                    payload["text"] = ""
                    payload["should_speak"] = False
                    draft_text = ""
                    host.logger.warning("[chat chess] suppressed invented coordinate move without authoritative suggestion")
            grounding_engine = getattr(host, "source_grounding_engine", None)
            claim_domain_decision = validate_claim_manifest(
                payload.get("claim_manifest") if "claim_manifest" in payload else None,
                allowed_domains=sorted(chat_claim_domains),
                allowed_evidence_refs=sorted(chat_claim_evidence_refs),
                text_present=bool(draft_text),
            )
            if claim_domain_decision.manifest_missing:
                host.logger.debug("[chat claims] writer payload missing claim_manifest; legacy compatibility path")
            grounding_verdict = evaluate_grounded_surface(
                grounding_engine, draft_text, report=grounding_report
            )
            grounding_annotations = grounding_verdict.annotations
            self_history_blocked = embodied_self_history_without_evidence(
                draft_text,
                claim_manifest=payload.get("claim_manifest") if "claim_manifest" in payload else None,
                allowed_evidence_refs=sorted(chat_claim_evidence_refs),
            )
            if self_history_blocked:
                host.logger.warning(
                    "[chat claims] blocked unsupported embodied self-history turn=%s text=%s",
                    turn_seq,
                    draft_text[:180],
                )
            if not grounding_verdict.allowed or not claim_domain_decision.allowed or self_history_blocked:
                violation_codes = []
                if not grounding_verdict.allowed:
                    violation_codes.append("UNGROUNDED_PERCEPTION_OR_ACTION_CLAIM")
                if not claim_domain_decision.allowed:
                    violation_codes.append("CLAIM_DOMAIN_OUTSIDE_INTENT")
                if self_history_blocked:
                    violation_codes.append("UNSUPPORTED_EMBODIED_SELF_HISTORY")
                retry_instruction = grounding_verdict.retry_instruction()
                if not claim_domain_decision.allowed:
                    retry_instruction += (
                        " V42 typed claim repair: remove or rewrite every claim whose domain/evidence is outside "
                        f"allowed_domains={sorted(chat_claim_domains)} and allowed_evidence_refs={sorted(chat_claim_evidence_refs)}. "
                        "Return a fresh claim_manifest matching the rewritten text."
                    )
                if self_history_blocked:
                    retry_instruction += (
                        " Remove autobiographical physical-habit claims about ERIS (for example claiming ERIS usually drinks/eats/does a bodily activity). "
                        "You may express a non-embodied preference as self_preference, but do not invent physical lived history."
                    )
                # Grounding là safety/integrity boundary: đã biết claim không có
                # evidence thì không được phát nguyên văn. Thử wording-only đúng
                # một lần; semantic frame/assistant act vẫn giữ nguyên authority.
                retry_payload = host.ai_model_router.generate_public_reply(
                    chat_history=history,
                    user_text=user_message,
                    memory_context=compiled_context.memory,
                    grounding_context=compiled_context.grounding,
                    relationship_context=compiled_context.relationship,
                    personality_context=compiled_context.personality,
                    interrupt_context=compiled_context.interrupt,
                    engagement_context=compiled_context.engagement,
                    routing_context=compiled_context.routing,
                    discourse_context=compiled_context.discourse,
                    use_escalation=use_escalation,
                    reasoning_effort=reasoning_effort,
                    thinking_mode=thinking_mode,
                    allow_fallback=False,
                    language_hint=_runtime_language(),
                    speech_language_hint=_runtime_speech_language(),
                    planned_intention=chat_plan,
                    retry_instruction=retry_instruction,
                    locked_semantic_frame=typed_frame.to_dict() if typed_frame is not None else payload.get("semantic_frame", {}),
                )
                retry_text = str(retry_payload.get("text", "") or "").strip() if isinstance(retry_payload, Mapping) else ""
                retry_verdict = evaluate_grounded_surface(
                    grounding_engine, retry_text, report=grounding_report
                ) if retry_text else None
                retry_claim_decision = validate_claim_manifest(
                    retry_payload.get("claim_manifest") if isinstance(retry_payload, Mapping) and "claim_manifest" in retry_payload else None,
                    allowed_domains=sorted(chat_claim_domains),
                    allowed_evidence_refs=sorted(chat_claim_evidence_refs),
                    text_present=bool(retry_text),
                )
                retry_self_history_blocked = embodied_self_history_without_evidence(
                    retry_text,
                    claim_manifest=retry_payload.get("claim_manifest") if isinstance(retry_payload, Mapping) else None,
                    allowed_evidence_refs=sorted(chat_claim_evidence_refs),
                ) if retry_text else False
                if (
                    retry_text
                    and retry_verdict is not None
                    and retry_verdict.allowed
                    and retry_claim_decision.allowed
                    and not retry_self_history_blocked
                ):
                    for _key in (
                        "text", "display_language", "speech_text", "speech_language",
                        "performance_hint", "performance_intensity", "nonverbal_cue",
                        "delivery_priority", "interruptible", "utterance_turn_id", "utterance",
                        "should_speak", "claim_manifest",
                    ):
                        if _key in retry_payload:
                            payload[_key] = retry_payload[_key]
                    payload["grounding_risk"] = {
                        "allowed": True,
                        "violations": violation_codes,
                        "annotations": [
                            item.to_dict() if callable(getattr(item, "to_dict", None)) else str(item)
                            for item in grounding_annotations
                        ],
                        "policy": "rewrite_then_revalidate",
                    }
                    draft_text = retry_text
                    host.logger.warning(
                        "[cortex v2 gate] turn=%s violations=%s; rewritten and revalidated",
                        turn_seq,
                        ",".join(violation_codes),
                    )
                else:
                    # Retry hỏng vẫn fail closed. Im một lượt tốt hơn phát một
                    # claim mà runtime vừa chứng minh là không có căn cứ.
                    payload["text"] = ""
                    payload["speech_text"] = ""
                    payload["should_speak"] = False
                    payload["grounding_risk"] = {
                        "allowed": False,
                        "violations": violation_codes,
                        "annotations": [
                            item.to_dict() if callable(getattr(item, "to_dict", None)) else str(item)
                            for item in grounding_annotations
                        ],
                        "policy": "fail_closed_after_rewrite",
                    }
                    host.logger.warning(
                        "[cortex v2 gate] turn=%s violations=%s; suppressed after failed rewrite",
                        turn_seq,
                        ",".join(violation_codes),
                    )
                payload["claim_domain_trace"] = {
                    "version": "eris.claim_domains.v42.typed_surface",
                    "allowed_domains": sorted(chat_claim_domains),
                    "added_claims": int(
                        (retry_claim_decision.added_claim_count if 'retry_claim_decision' in locals() else claim_domain_decision.added_claim_count)
                    ),
                    "violations": list(violation_codes),
                }
                payload["grounding_confidence_cap"] = min(
                    float(payload.get("grounding_confidence_cap", 1.0) or 1.0),
                    float(getattr(grounding_report, "confidence_cap", 0.45) or 0.45),
                )


        if payload:
            try:
                from runtime.capability_claim_guard import guard_public_capability_claims

                claim_guard = guard_public_capability_claims(
                    payload,
                    owner=host,
                    executive_directive=directive_payload,
                )
                payload = dict(claim_guard.payload)
                user_meta["capability_claim_guard"] = {
                    "allowed": bool(claim_guard.allowed),
                    "violations": list(claim_guard.violations),
                }
                if not claim_guard.allowed:
                    host.logger.warning(
                        "[capability claim guard] failed closed violations=%s",
                        ",".join(claim_guard.violations),
                    )
            except Exception as exc:
                host.logger.warning("[capability claim guard] unavailable; failing closed: %s", exc)
                payload = dict(payload)
                payload["should_speak"] = False
                payload["text"] = ""
                payload["speech_text"] = ""

        if not payload:
            authoritative_text = _authoritative_chess_result_text(grounding_report, user_text)
            if authoritative_text:
                # Đây là kết quả analyzer có provenance, không phải Surface
                # fallback. Chỉ dùng khi user hỏi thẳng nước nào và bridge đã có
                # suggestion. Không thêm banter local; banter thuộc model.
                payload = enforce_reply_obligation(
                    {"text": authoritative_text, "should_speak": True},
                    user_text=user_text,
                    frame=typed_frame,
                    language_hint=_runtime_language(),
                    direct_user_turn=True,
                ).payload
                payload.update({
                    "animation": "stand",
                    "next_animation": "",
                    "direction": 0,
                    "target_x": -1.0,
                    "bounce_action": "",
                    "system_action": "",
                    "action_input": "",
                    "delivery_hint": "direct",
                    "nonverbal_cue": "focused",
                    "stage_motion": "",
                    "performance_hint": "focused",
                    "source": "authoritative_chess_analyzer",
                })
                decision = host.parser.parse(
                    json.dumps(_serializable_public_payload(payload), ensure_ascii=False),
                    user_hint=user_text,
                )
                decision.parse_mode = "authoritative_chess_result"
                host.logger.info("[chat chess] emitted authoritative analyzer result; surface unavailable")
            elif str(getattr(grounding_report, "structured_kind", "") or "") == "chess" and chess_turn_relevant(user_text, engagement_active=True):
                # Có chess state nhưng không có suggestion đủ thẩm quyền: im.
                # Không dựng câu local, không đọc telemetry, không giả banter.
                payload = {
                    "text": "",
                    "should_speak": False,
                    "animation": "stand",
                    "performance_hint": "focused",
                }
                decision = host.parser.parse(
                    json.dumps(_serializable_public_payload(payload), ensure_ascii=False),
                    user_hint=user_text,
                )
                decision.parse_mode = "chess_surface_unavailable"
                host.logger.info("[chat chess] surface unavailable; no authoritative move, local text fallback disabled")
            else:
                # Compatibility cho chat phi-chess. Chess tuyệt đối không đi qua
                # nhánh discourse fallback này.
                seed_text = str(discourse_surface.text or "").strip()
                fallback_payload = enforce_reply_obligation(
                    {"text": seed_text, "should_speak": bool(seed_text)},
                    user_text=user_text,
                    frame=typed_frame,
                    language_hint=_runtime_language(),
                    direct_user_turn=True,
                ).payload
                fallback_payload.update({
                    "animation": "stand",
                    "next_animation": "",
                    "direction": 0,
                    "target_x": -1.0,
                    "bounce_action": "",
                    "system_action": "",
                    "action_input": "",
                    "delivery_hint": "",
                    "nonverbal_cue": "",
                    "stage_motion": "",
                    "performance_hint": str(fallback_payload.get("performance_hint", "neutral") or "neutral"),
                })
                decision = host.parser.parse(
                    json.dumps(_serializable_public_payload(fallback_payload), ensure_ascii=False),
                    user_hint=user_text,
                )
                decision.parse_mode = "typed_discourse_fallback"
                decision.failure_meta = build_failure_meta(
                    kind="format_violation",
                    stage="ai_chat_orchestrator",
                    origin="main_model",
                    public_surface="typed_discourse_fallback",
                    recoverable=True,
                )
        else:
            public_payload = _serializable_public_payload(payload)
            raw = json.dumps(public_payload, ensure_ascii=False)
            host._log_raw_llm_output("chat_ai", raw)
            decision = host.parser.parse(raw, user_hint=user_text)
        latency_trace.mark("post_writer")

        if str(directive_payload.get("status", "") or "") == "selected":
            decision.system_action = str(directive_payload.get("capability_id", "") or "")
            decision.action_input = ""
            decision.capability_arguments = dict(
                directive_payload.get("capability_arguments", {}) or {}
            )
        else:
            decision.capability_arguments = None

        if not str(getattr(decision, "utterance_turn_id", "") or "").strip():
            decision.utterance_turn_id = str(
                getattr(host, "_active_public_lifecycle_turn_id", "") or turn_id
            )

        if (
            not payload
            or getattr(decision, "parse_mode", "") == "typed_discourse_fallback"
            or bool(getattr(decision, "failure_meta", None))
        ) and getattr(decision, "parse_mode", "") not in {
            "authoritative_chess_result",
            "chess_surface_unavailable",
        }:
            setattr(host, "_cached_failed_user_turn", user_text)
        elif hasattr(host, "_cached_failed_user_turn") and getattr(host, "_cached_failed_user_turn", ""):
            setattr(host, "_cached_failed_user_turn", "")

        # Main model chỉ nêu hint; StagePlanner làm phần cơ học. Legacy stage fields
        # vẫn được chấp nhận để không làm frontend gãy, nhưng không cần thiết.
        hint = str(getattr(decision, "performance_hint", "") or "").strip().lower()
        if not hint or hint == "neutral":
            hint = str(getattr(chat_plan, "performance_hint", "") or "neutral")
        host.ai_stage_planner.apply(decision, hint, state=mind_state, channel="chat")
        decision = host._execute_system_action(decision, snapshot=snapshot, frame=None)
        latency_trace.mark("stage_action")
        commit_started = time.monotonic()
        public_text, assistant_meta = self._commit(
            decision,
            assistant_meta_extra=assistant_discourse_meta,
            idempotency_key=_chat_commit_idempotency_key(host, turn_id),
        )
        # Foreground chat consumed this exact user event. Keep any later
        # associative material private instead of letting it become a second reply.
        # This MUST live in the chat scope where user_text/turn_id actually exist.
        if public_text:
            material_runtime = getattr(host, "mental_material_runtime", None)
            mark_answered = getattr(material_runtime, "mark_user_event_answered", None)
            if callable(mark_answered):
                try:
                    mark_answered(user_text, turn_id=turn_id, now=time.time())
                except Exception as exc:
                    host.logger.debug("[mental material] user event consume failed: %s", exc)
        if public_text:
            try:
                # Subject speech_act là ownership semantic thật của lượt. AssistantAct
                # ở Surface có thể chỉ còn nhãn chung kiểu "answer"; dùng nó trước
                # sẽ làm causal-repair receipt mất identity và handoff tưởng repair
                # chưa từng xảy ra (hoặc ngược lại, clear quá sớm).
                _subject_speech_act = str(
                    (getattr(subject_decision, "arguments", {}) or {}).get("speech_act", "")
                    if isinstance(getattr(subject_decision, "arguments", {}), Mapping)
                    else ""
                ).strip()
                _assistant_act_value = str(
                    _subject_speech_act
                    or getattr(getattr(assistant_act, "kind", None), "value", "")
                    or getattr(decision, "speech_act", "")
                    or "answer"
                )
                _assistant_turn_index = 0
                _ledger_turns = host._ensure_session_turn_ledger().assistant_turns()
                if _ledger_turns:
                    _assistant_turn_index = int(_ledger_turns[-1].index)
                _assistant_ref = (f"session-turn:{_assistant_turn_index}" if _assistant_turn_index else turn_id)
                handoff_runtime.observe_assistant_commit(
                    public_text,
                    turn_ref=_assistant_ref,
                    turn_index=_assistant_turn_index,
                    speech_act=_assistant_act_value,
                    now=time.time(),
                )
                _individual_receipt = persistent_individual_runtime.observe_assistant_commit(
                    public_text, speech_act=_assistant_act_value, autonomous=False,
                    context_key="direct_chat", now=time.time(),
                )
                _response_expectation = str(_individual_receipt.get("response_expectation", "") or "")
                trajectory_runtime.observe_assistant_commit(
                    public_text,
                    turn_ref=_assistant_ref,
                    turn_index=_assistant_turn_index,
                    speech_act=_assistant_act_value,
                    response_expectation=_response_expectation,
                    autonomous=False,
                    now=time.time(),
                )
                handoff_runtime.note_self_commitment(public_text, now=time.time())
                courtesy_runtime.observe_assistant_commit(
                    public_text, speech_act=_assistant_act_value, response_expectation=_response_expectation,
                    turn_ref=_assistant_ref, now=time.time()
                )
                life_horizon_manager.observe_assistant_commit(
                    speech_act=_assistant_act_value, turn_ref=_assistant_ref, now=time.time()
                )
            except Exception as exc:
                host.logger.debug("[conversation handoff v71] chat commit receipt degraded: %s", exc)
        # V69: nếu Eris vừa tự nói "tôi sẽ đổi chủ đề", lời đó trở thành
        # self-commitment của chính semantic family vừa gây satiation.
        if public_text:
            consummation_runtime = getattr(host, "expression_consummation_runtime", None)
            note_public_text = getattr(consummation_runtime, "note_public_text", None)
            if callable(note_public_text):
                try:
                    note_public_text(public_text, now=time.time())
                except Exception as exc:
                    host.logger.debug("[expression consummation] self-commitment degraded: %s", exc)
        latency_trace.mark("commit")
        try:
            from runtime.observability import GLOBAL_OBSERVABILITY
            GLOBAL_OBSERVABILITY.observe(
                "public_writer_commit_ms",
                max(0.0, (time.monotonic() - commit_started) * 1000.0),
                tags={"usable": str(bool(public_text)).lower()},
            )
        except Exception:
            pass
        # Commit semantic social plans only after the first public line succeeds.
        # The model appraises; runtime owns IDs, deadlines, leases and cancellation.
        social_plan = payload.get("social_plan") if isinstance(payload, Mapping) else None
        try:
            from .social_execution import accept_full_social_plan

            social_plan = accept_full_social_plan(
                social_plan if isinstance(social_plan, Mapping) else None
            )
        except Exception as exc:
            # Normalization failure must fail closed to an all-none plan. It must
            # not revive the retired top-level conversation_arc field.
            from .social_plan import empty_social_plan

            social_plan = empty_social_plan()
            host.logger.debug("[social execution] normalization failed: %s", exc)
        valid_social_commit = bool(
            public_text
            and assistant_meta is not None
            and str(getattr(decision, "parse_mode", "") or "") not in {
                "typed_discourse_fallback",
                "authoritative_chess_result",
                "chess_surface_unavailable",
            }
            and not bool(getattr(decision, "failure_meta", None))
        )
        if valid_social_commit:
            semantic_payload = typed_frame.to_dict() if typed_frame is not None else {}
            assistant_act_payload = assistant_act.to_dict() if callable(getattr(assistant_act, "to_dict", None)) else dict(assistant_act or {})
            commit_now = time.time()
            if social_continuation_runtime is not None:
                try:
                    social_continuation_runtime.schedule_from_social_plan(
                        social_plan,
                        source_turn_id=turn_id,
                        source_text=public_text,
                        source_turn_seq=turn_seq,
                        semantic_frame=semantic_payload,
                        assistant_act=assistant_act_payload,
                        now=commit_now,
                    )
                except Exception as exc:
                    host.logger.debug("[social continuation] schedule failed: %s", exc)
            if social_agenda_store is not None:
                try:
                    agenda_update = social_plan.get("agenda_update", {})
                    social_agenda_store.apply_update(
                        agenda_update if isinstance(agenda_update, Mapping) else {},
                        source_turn_id=turn_id,
                        now=commit_now,
                    )
                except Exception as exc:
                    host.logger.debug("[social agenda] update failed: %s", exc)
            arc_payload = social_plan.get("conversation_arc")
            scheduled_arc = False
            if isinstance(arc_payload, Mapping) and conversation_arc_runtime is not None:
                try:
                    scheduled_arc = conversation_arc_runtime.schedule_from_model(
                        arc_payload,
                        source_turn_id=turn_id,
                        source_text=public_text,
                        source_turn_seq=turn_seq,
                        semantic_frame=semantic_payload,
                        assistant_act=assistant_act_payload,
                        now=commit_now,
                    )
                except Exception as exc:
                    host.logger.debug("[conversation arc] schedule failed: %s", exc)

            # If very short audio completed before commit returned, catch both
            # short and long continuation runtimes up to the real playback clock.
            clock = getattr(host, "interaction_clock", None)
            if clock is not None:
                audio_finished_at = float(getattr(clock, "audio_finished_at", 0.0) or 0.0)
                assistant_text_at = float(getattr(clock, "assistant_text_at", 0.0) or 0.0)
                playback_already_done = bool(
                    audio_finished_at > 0.0
                    and audio_finished_at >= assistant_text_at
                    and not bool(getattr(clock, "audio_active", False))
                )
                if playback_already_done:
                    if social_continuation_runtime is not None:
                        try:
                            social_continuation_runtime.notify_audio_finished(
                                audio_finished_at,
                                source_turn_id=turn_id,
                            )
                        except Exception as exc:
                            host.logger.debug("[social continuation] audio catch-up failed: %s", exc)
                    if scheduled_arc and conversation_arc_runtime is not None:
                        try:
                            conversation_arc_runtime.notify_audio_finished(audio_finished_at)
                        except Exception as exc:
                            host.logger.debug("[conversation arc] audio catch-up failed: %s", exc)
        if public_text and discovery_id and discovery_runtime is not None:
            discovery_runtime.mark_spoken(discovery_id, public_text)
        host.last_user_text_for_semantics = user_text

        if public_text and chat_plan.strategy:
            pending_strategy = PendingStrategyUse(
                strategy_use_id=f"strategy:{turn_id}",
                turn_seq=turn_seq,
                strategy=chat_plan.strategy,
                goal=chat_plan.topic,
                context=tuple(
                    item
                    for item in (chat_plan.motive, chat_plan.value_focus, "chat")
                    if str(item or "").strip()
                ),
                assistant_text=public_text,
                relationship_scope=PRIMARY_RELATIONSHIP_ID,
            )
            host.ai_state_reducer.submit(
                StateEvent.from_pending_strategy(
                    pending_strategy,
                    base_version=host.ai_state_reducer.snapshot().version,
                )
            )

        mechanical: list[Mapping[str, Any]] = []
        if isinstance(getattr(decision, "action_result_meta", None), Mapping):
            action_outcome = dict(decision.action_result_meta)
            mechanical.append(action_outcome)
            host.ai_state_reducer.submit(
                StateEvent.from_mechanical_outcome(
                    action_outcome,
                    turn_seq=turn_seq,
                    turn_id=turn_id,
                    base_version=host.ai_state_reducer.snapshot().version,
                )
            )
        recent_history = tuple(host._chat_history_for_llm(limit=8))
        observer_state = mind_state.to_dict()
        # PDF annotation, pages 12-13 and 20: post-turn analysis receives the
        # same validated semantic authority frame instead of rebuilding meaning
        # through the retired discourse/social regex stack.
        observer_state["semantic_frame"] = dict(user_meta.get("semantic_frame", {}) or {})
        host.ai_post_turn_observer.submit(
            turn_id=turn_id,
            turn_seq=turn_seq,
            user_text=user_text,
            assistant_text=public_text,
            recent_history=recent_history,
            mechanical_outcomes=mechanical,
            state_summary=observer_state,
            user_meta=user_meta,
            assistant_meta=assistant_meta,
            event_kind="chat",
        )
        latency_trace.mark("post_commit")
        latency_trace.finish(status="ok")

    def _commit(
        self,
        decision: Any,
        *,
        assistant_meta_extra: Mapping[str, Any] | None = None,
        idempotency_key: str = "",
    ) -> tuple[str, dict[str, Any] | None]:
        from runtime.public_turn_transaction import registry_for

        return registry_for(self.host).run_once(
            idempotency_key,
            lambda: self._commit_once(
                decision,
                assistant_meta_extra=assistant_meta_extra,
                idempotency_key=idempotency_key,
            ),
        )

    def _commit_once(
        self,
        decision: Any,
        *,
        assistant_meta_extra: Mapping[str, Any] | None = None,
        idempotency_key: str = "",
    ) -> tuple[str, dict[str, Any] | None]:
        host = self.host
        if idempotency_key and not str(getattr(decision, "director_trace_id", "") or "").strip():
            decision.director_trace_id = str(idempotency_key)
        try:
            from runtime.public_surface_commit import GLOBAL_PUBLIC_SURFACE_COMMITTER
            surfaces = GLOBAL_PUBLIC_SURFACE_COMMITTER.build(decision.text)
            public_text = surfaces.display_text
            memory_text = surfaces.memory_text
        except Exception:
            public_text = str(getattr(decision, "text", "") or "").strip()
            memory_text = public_text
        decision.text = public_text
        if public_text:
            chess_bridge = getattr(host, "chess_bridge_service", None)
            record_suggestion = getattr(chess_bridge, "record_public_suggestion", None)
            if callable(record_suggestion):
                try:
                    record_suggestion(
                        public_text,
                        authoritative=str(getattr(decision, "parse_mode", "") or "") in {
                            "authoritative_chess_result",
                            "authoritative_chess_guard",
                        },
                    )
                except Exception as exc:
                    host.logger.debug("[chess] public suggestion record failed: %s", exc)
            engagement_runtime = getattr(host, "ai_engagement_runtime", None)
            if engagement_runtime is not None:
                try:
                    engagement_runtime.observe_assistant_output(public_text, now=time.time())
                except Exception as exc:
                    host.logger.debug("[engagement] assistant output observation failed: %s", exc)
        try:
            from runtime.final_speech_authority import GLOBAL_FINAL_SPEECH_AUTHORITY
            decision = GLOBAL_FINAL_SPEECH_AUTHORITY.seal(decision)
        except Exception as exc:
            _orchestrator_boundary_note(host, "chat_surface.seal", exc)

        host.last_chat_answer = public_text
        host.last_system_action = str(getattr(decision, "system_action", "") or "")
        if public_text:
            temporal = getattr(host, "temporal_mind", None)
            note_public = getattr(temporal, "note_public_act", None)
            if callable(note_public):
                try:
                    note_public(
                        now=time.time(),
                        focus_key=str(getattr(host, "active_conversational_topic", "") or "direct_chat"),
                    )
                except Exception as exc:
                    host.logger.debug("[temporal mind] chat public-act update failed: %s", exc)
            note_relational = getattr(getattr(host, "subject_service", None), "note_relational_public_act", None)
            if callable(note_relational):
                try:
                    note_relational(
                        now=time.time(),
                        outreach=False,
                        sharing=False,
                        evidence_ref=str(getattr(decision, "turn_id", "") or getattr(decision, "idempotency_key", "") or "chat_public"),
                        persist=True,
                    )
                except Exception as exc:
                    host.logger.debug("[relational] chat public-act update failed: %s", exc)
        clock = getattr(host, "interaction_clock", None)
        if clock is not None and public_text:
            clock.mark_assistant_text()
            # PDF annotation, pages 17-18: time-to-first-visible-text is a
            # first-class load-test metric, not something reconstructed from
            # screenshots after the fact.
            try:
                started_at = float(getattr(clock, "generation_started_at", 0.0) or 0.0)
                if started_at > 0.0:
                    from runtime.observability import GLOBAL_OBSERVABILITY

                    frame = dict(getattr(host, "last_semantic_frame", {}) or {})
                    act = str(frame.get("user_act", "") or "").strip().lower()
                    category = (
                        "small_talk"
                        if act in {
                            "greeting",
                            "acknowledgement",
                            "relational_check_in",
                            "closeness_bid",
                            "repair_request",
                        }
                        else "general_chat"
                    )
                    GLOBAL_OBSERVABILITY.observe(
                        "ttft_ms",
                        max(0.0, (time.time() - started_at) * 1000.0),
                        tags={"channel": "chat", "turn_category": category},
                    )
            except Exception as exc:
                _orchestrator_boundary_note(host, "chat_ttft.observe", exc)
        if memory_text:
            host._append_chat_history("assistant", memory_text, invalid=False)
        assistant_meta: dict[str, Any] | None = None
        if bool(getattr(decision, "should_speak", False)) and public_text:
            assistant_meta = {
                "architecture": AI_RUNTIME_VERSION,
                "system_action": host.last_system_action,
                "parse_mode": str(getattr(decision, "parse_mode", "") or "json"),
                "idempotency_key": str(idempotency_key or ""),
                # Assistant turn không mang semantic frame của user. Chỉ giữ version
                # để debug protocol, còn user_meta đã lưu frame đúng chủ thể.
                "incoming_user_frame_version": str(
                    dict(getattr(host, "last_semantic_frame", {}) or {}).get("version", "") or ""
                ),
            }
            extra = dict(assistant_meta_extra or {})
            for key, value in extra.items():
                if key == "discourse" and isinstance(value, Mapping):
                    merged_discourse = dict(assistant_meta.get("discourse", {}) or {})
                    merged_discourse.update(dict(value))
                    assistant_meta["discourse"] = merged_discourse
                else:
                    assistant_meta[key] = value

            assistant_act = validate_assistant_act(assistant_meta.get("assistant_act", {})).act
            assistant_meta["assistant_act"] = assistant_act.to_dict()
            discourse = dict(assistant_meta.get("discourse", {}) or {})
            ledger = host._ensure_session_turn_ledger()
            previous_active_root = _previous_active_proposition_root(ledger)
            assistant_turn = ledger.record_assistant(public_text, meta=assistant_meta)
            proposition_root, active_root = assistant_proposition_link(
                assistant_act=assistant_act,
                assistant_turn_index=assistant_turn.index,
                referenced_root_turn_index=int(
                    discourse.get("active_proposition_root_turn_index", 0) or 0
                ),
                previous_active_root_turn_index=previous_active_root,
            )
            discourse["proposition_root_turn_index"] = proposition_root
            discourse["active_proposition_root_turn_index"] = active_root
            assistant_meta["discourse"] = discourse
            ledger.merge_turn_meta(
                assistant_turn.index,
                {
                    "assistant_act": assistant_act.to_dict(),
                    "discourse": discourse,
                },
            )
        if len(host.chat_history) > 32:
            host.chat_history = host.chat_history[-32:]
        host._apply_position_update(decision)
        if public_text or str(getattr(decision, "system_action", "") or "").strip():
            host._send_decision_to_body(decision, channel="chat")
        if public_text:
            host.logger.info("ERIS: %s", public_text)
        else:
            host.logger.info("[cortex v2 gate] public surface suppressed without canned fallback")
        return public_text, assistant_meta


class AIAutonomousOrchestrator:
    def __init__(self, host: Any) -> None:
        self.host = host
        self._last_body_only_at = 0.0
        self._last_body_only_signature = ""
        self.self_turn_pipeline = SelfTurnPipeline(
            host,
            next_turn_seq=_next_ai_turn_seq,
            commit_public=self._commit_public,
            emit_body_only=self._emit_body_only,
        )
        # Alias chỉ để panel/test adapter cũ truy cập trace. Logic production nằm
        # trong SelfTurnPipeline, không còn phình ở orchestrator facade.
        self.trace_store = self.self_turn_pipeline.trace_store

    def _commit_public(self, decision: Any, *, channel: str, turn_seq: int) -> tuple[str, dict[str, Any] | None]:
        """Commit một public turn autonomous vào cùng lịch sử/ledger với chat.

        Planner và observer có thể thông minh đến đâu cũng vô ích nếu câu public
        không được ghi vào continuity. Hàm này chỉ vận chuyển surface, không viết
        lại lời model.
        """
        from runtime.public_turn_transaction import registry_for

        explicit_idempotency = str(getattr(decision, "director_trace_id", "") or "").strip()
        idempotency_key = explicit_idempotency or f"{str(channel or 'autonomous')}:{int(turn_seq)}:assistant"
        return registry_for(self.host).run_once(
            idempotency_key,
            lambda: self._commit_public_once(
                decision,
                channel=channel,
                turn_seq=turn_seq,
                idempotency_key=idempotency_key,
            ),
        )

    def _commit_public_once(
        self,
        decision: Any,
        *,
        channel: str,
        turn_seq: int,
        idempotency_key: str = "",
    ) -> tuple[str, dict[str, Any] | None]:
        host = self.host
        if idempotency_key and not str(getattr(decision, "director_trace_id", "") or "").strip():
            decision.director_trace_id = str(idempotency_key)
        try:
            from runtime.public_surface_commit import GLOBAL_PUBLIC_SURFACE_COMMITTER
            surfaces = GLOBAL_PUBLIC_SURFACE_COMMITTER.build(str(getattr(decision, "text", "") or ""))
            public_text = surfaces.display_text
            memory_text = surfaces.memory_text
        except Exception:
            public_text = str(getattr(decision, "text", "") or "").strip()
            memory_text = public_text
        decision.text = public_text
        if public_text:
            chess_bridge = getattr(host, "chess_bridge_service", None)
            record_suggestion = getattr(chess_bridge, "record_public_suggestion", None)
            if callable(record_suggestion):
                try:
                    record_suggestion(public_text, authoritative=False)
                except Exception as exc:
                    host.logger.debug("[chess] autonomous suggestion record failed: %s", exc)
            engagement_runtime = getattr(host, "ai_engagement_runtime", None)
            if engagement_runtime is not None:
                try:
                    engagement_runtime.observe_assistant_output(public_text, now=time.time())
                except Exception as exc:
                    host.logger.debug("[engagement] autonomous output observation failed: %s", exc)
        try:
            from runtime.final_speech_authority import GLOBAL_FINAL_SPEECH_AUTHORITY
            decision = GLOBAL_FINAL_SPEECH_AUTHORITY.seal(decision)
        except Exception as exc:
            _orchestrator_boundary_note(host, "autonomous_surface.seal", exc)
        if not public_text:
            return "", None
        clock = getattr(host, "interaction_clock", None)
        if (
            str(channel or "").strip().lower() == "autonomous"
            and clock is not None
            and bool(getattr(clock, "speech_floor_busy", False))
        ):
            host.logger.info(
                "[autonomous floor] speech deferred while public audio busy owner=%s text=%r",
                str(getattr(clock, "audio_floor_turn_id", "") or "<pending>"),
                public_text[:120],
            )
            return "", None
        host.last_text = public_text
        # Startup/autonomous là public assistant turn thật, không phải hiệu ứng
        # trang trí. Giữ cùng con trỏ gần nhất với chat để câu user kế tiếp có
        # thể hỏi "ý câu vừa rồi là gì" mà không bị Eris giả mất trí nhớ.
        host.last_chat_answer = public_text
        temporal = getattr(host, "temporal_mind", None)
        note_public = getattr(temporal, "note_public_act", None)
        if callable(note_public):
            try:
                note_public(now=time.time(), focus_key=str(channel or "autonomous"))
            except Exception as exc:
                host.logger.debug("[temporal mind] autonomous public-act update failed: %s", exc)
        clock = getattr(host, "interaction_clock", None)
        if clock is not None:
            try:
                clock.mark_assistant_text()
            except Exception as exc:
                _orchestrator_boundary_note(host, "autonomous_clock.mark", exc)
        if memory_text:
            host._append_chat_history("assistant", memory_text, invalid=False)
            if len(host.chat_history) > 32:
                host.chat_history = host.chat_history[-32:]
        meta = {
            "architecture": AI_RUNTIME_VERSION,
            "channel": channel,
            "ai_turn_seq": int(turn_seq),
            "system_action": str(getattr(decision, "system_action", "") or ""),
            "idempotency_key": str(idempotency_key or ""),
            # Typed public semantics are ledger data. They are not inferred later
            # from punctuation or remembered in a parallel follow-up state machine.
            "speech_act": str(getattr(decision, "speech_act", "") or ""),
            "autonomous_plan": dict(getattr(decision, "autonomous_plan", {}) or {}),
            "performance_context": dict(getattr(decision, "performance_context", {}) or {}),
        }
        _autonomous_assistant_turn = None
        try:
            _autonomous_assistant_turn = host._ensure_session_turn_ledger().record_assistant(public_text, meta=meta)
        except Exception:
            meta = None
        try:
            from runtime.conversation_handoff import ensure_conversation_handoff_runtime
            _handoff_runtime = ensure_conversation_handoff_runtime(host)
            _auto_turn_ref = (
                f"session-turn:{getattr(_autonomous_assistant_turn, 'index', 0)}"
                if _autonomous_assistant_turn is not None else str(idempotency_key or "")
            )
            _auto_turn_index = int(getattr(_autonomous_assistant_turn, "index", 0) or 0)
            _auto_speech_act = str(getattr(decision, "speech_act", "") or "")
            _handoff_runtime.observe_assistant_commit(
                public_text,
                turn_ref=_auto_turn_ref,
                turn_index=_auto_turn_index,
                speech_act=_auto_speech_act,
                now=time.time(),
            )
            from runtime.persistent_individual import ensure_persistent_individual_runtime
            _persistent_runtime = ensure_persistent_individual_runtime(host)
            _individual_receipt = _persistent_runtime.observe_assistant_commit(
                public_text, speech_act=_auto_speech_act, autonomous=True,
                context_key="autonomous", now=time.time(),
            )
            _response_expectation = str(_individual_receipt.get("response_expectation", "") or "")
            from runtime.conversation_trajectory import ensure_conversation_trajectory_runtime
            ensure_conversation_trajectory_runtime(host).observe_assistant_commit(
                public_text,
                turn_ref=_auto_turn_ref,
                turn_index=_auto_turn_index,
                speech_act=_auto_speech_act,
                response_expectation=_response_expectation,
                autonomous=True,
                now=time.time(),
            )
            _handoff_runtime.note_self_commitment(public_text, now=time.time())
            from runtime.conversation_courtesy import ensure_conversation_courtesy
            from runtime.life_horizon import ensure_life_horizon_manager
            _auto_ref = (
                f"session-turn:{getattr(_autonomous_assistant_turn, 'index', 0)}"
                if _autonomous_assistant_turn is not None else str(idempotency_key or "")
            )
            ensure_conversation_courtesy(host).observe_assistant_commit(
                public_text,
                speech_act=str(getattr(decision, "speech_act", "") or ""),
                response_expectation=_response_expectation,
                turn_ref=_auto_ref,
                now=time.time(),
            )
            ensure_life_horizon_manager(host).observe_assistant_commit(
                speech_act=str(getattr(decision, "speech_act", "") or ""),
                turn_ref=_auto_ref,
                now=time.time(),
            )
        except Exception as exc:
            host.logger.debug("[conversation handoff v71] autonomous commit receipt degraded: %s", exc)
        host._apply_position_update(decision)
        host._send_decision_to_body(decision, channel=channel)
        return public_text, meta

    def _emit_body_only(
        self,
        *,
        reason: str,
        activity_kind: str = "unknown",
        motion_hint: str = "",
        turn_seq: int,
        signature: str = "",
    ) -> bool:
        """Phát hiện diện phi ngôn ngữ sau deliberation của main planner.

        ``activity_kind`` chỉ là annotation typed từ planner. Motion lấy từ
        ``performance_hint``; runtime không phân loại game/code/media.
        """
        host = self.host
        now = time.time()
        signature = str(signature or f"{reason}:{motion_hint}")[:200]
        if now - self._last_body_only_at < 24.0 or (signature and signature == self._last_body_only_signature):
            return False
        try:
            from domain.decision import Decision
            hint = str(motion_hint or "").strip().lower()
            motion = {
                "focus": "focus",
                "curious": "tilt_head",
                "thinking": "blink_slow",
                "quiet_presence": "look_aside",
                "soft": "lean_in_small",
            }.get(hint, "tilt_head")
            decision = Decision(
                text="", animation="stand", should_speak=False, confidence=0.82,
                performance_hint="quiet_presence", stage_motion=motion, motion_intent=motion,
                nonverbal_cue="small_presence", debug_trace=f"body_only:{reason}",
            )
            host._send_decision_to_body(decision, channel="autonomous")
            self._last_body_only_at = now
            self._last_body_only_signature = signature
            self.trace_store.append("body_only", {
                "turn_seq": turn_seq, "activity_kind": activity_kind, "reason": reason,
                "motion_hint": hint, "result": "emitted", "body_only": True,
            }, now=now)
            return True
        except Exception as exc:
            _orchestrator_boundary_note(host, "body_only.emit", exc)
            return False

    def run_startup(self) -> bool:
        """Prime continuity state only; startup no longer fabricates public speech.

        V71 removes the historical startup-greeting path entirely. That path could
        log ``spoke`` and feed PostObserver even when no bubble/TTS/public receipt
        existed. A public act that the user never received must not become history.

        The normal autonomous/chat pipeline owns every real utterance after startup.
        If ERIS genuinely wants to greet or resume a thread, it must win Neuro and
        reach the same public commit path as every other sentence.
        """
        host = self.host
        if bool(getattr(host, "_ai_startup_ran", False)):
            return False
        host._ai_startup_ran = True

        try:
            state = host.ai_state_reducer.snapshot()
        except Exception as exc:
            _orchestrator_boundary_note(host, "startup.continuity_snapshot", exc)
            state = None
        try:
            recent_history = tuple(host._chat_history_for_llm(limit=8))
        except Exception as exc:
            _orchestrator_boundary_note(host, "startup.continuity_history", exc)
            recent_history = ()

        open_loops = tuple(getattr(state, "open_loops", ()) or ()) if state is not None else ()
        latest_observation = (
            dict(getattr(state, "latest_observation", {}) or {})
            if state is not None and isinstance(getattr(state, "latest_observation", {}), Mapping)
            else {}
        )
        try:
            from runtime.conversation_handoff import ensure_conversation_handoff_runtime

            handoff = ensure_conversation_handoff_runtime(host).prime_from_state(
                open_loops=open_loops,
                latest_observation=latest_observation,
                recent_history=recent_history,
                now=time.time(),
            )
            try:
                from runtime.conversation_trajectory import ensure_conversation_trajectory_runtime
                ensure_conversation_trajectory_runtime(host).prime_from_history(
                    recent_history, now=time.time()
                )
            except Exception as exc:
                _orchestrator_boundary_note(host, "startup.conversation_trajectory_prime", exc)
            # V76: startup là re-entry appraisal, tuyệt đối không tự chiếm một
            # public turn. State chỉ ghi khoảng cách từ lần mở trước + daypart để
            # autonomous planner có thể comment/mutter/silence theo ngữ cảnh sau đó.
            try:
                from runtime.persistent_individual import ensure_persistent_individual_runtime
                startup_view = ensure_persistent_individual_runtime(host).note_startup(now=time.time())
                host.logger.info(
                    "[persistent-individual-v76] startup gap=%.1fs late_night=%s short_return=%s opening=%s",
                    float(startup_view.get("reentry_gap_seconds", 0.0) or 0.0),
                    bool(startup_view.get("late_night", False)),
                    bool(startup_view.get("short_return", False)),
                    ",".join(startup_view.get("opening_modes", ()) or ()),
                )
            except Exception as exc:
                _orchestrator_boundary_note(host, "startup.persistent_individual_prime", exc)
            host.logger.info(
                "[architecture C startup] continuity primed rev=%s owner=%s pressure=%.2f pending=%s public_greeting=disabled",
                handoff.revision,
                handoff.next_move_owner,
                handoff.continuity_pressure,
                _compact(handoff.pending_shared_goal, 140) or "none",
            )
        except Exception as exc:
            _orchestrator_boundary_note(host, "startup.conversation_handoff_prime", exc)
            host.logger.info(
                "[architecture C startup] public_greeting=disabled continuity_prime=unavailable"
            )

        # Luôn False: startup không còn sở hữu một public turn. Không observer submit,
        # không relational public-act receipt, không TTS/bubble giả và không đặt mốc
        # _startup_greeting_spoken_at.
        return False

    def run_force_speak(self) -> None:
        host = self.host
        try:
            from llm.key_pool import reset_provider_circuits
            reset_provider_circuits()
        except Exception:
            pass
        snapshot = host.telemetry_service.capture_snapshot(
            mood_score=host.mood_score,
            inferred_pos_x=host.inferred_pos_x,
        )
        vision_facts = host._maybe_update_screen_facts()
        if vision_facts:
            try:
                host._attach_screen_facts(snapshot, vision_facts)
            except Exception as exc:
                _orchestrator_boundary_note(host, "force_speak.attach_screen_facts", exc)
        host.long_term_memory = host._memory_recall_texts(snapshot=snapshot)
        memory_resonance = host._recall_memory_resonance(
            snapshot=snapshot,
            channel="force_speak",
            fragments=tuple(vision_facts or ()),
        )
        memory_context = host._build_memory_context(snapshot, memory_resonance=memory_resonance)
        state = host.ai_state_reducer.snapshot()
        turn_seq = _next_ai_turn_seq(host)
        telemetry_payload = snapshot.to_machine_context() if callable(getattr(snapshot, "to_machine_context", None)) else {}
        planner_snapshot = {
            "event_kind": "force_speak",
            "explicit_user_pull": True,
            "telemetry": telemetry_payload,
            "vision_facts": list(vision_facts or ()),
            "personality": state.personality.panel_view(),
            "personality_summary": state.personality_prompt_context(),
            "identity": state.identity.panel_view(),
            "identity_summary": state.identity_prompt_context(),
            "relationship": state.relationship.to_dict(),
            "open_loops": list(state.open_loops),
            "latest_observation": dict(state.latest_observation),
            "recent_public_history": host._chat_history_for_llm(limit=8),
            "instruction": "Choose one grounded, worthwhile thing to say now. Do not invent context.",
        }
        discovery_runtime = getattr(host, "ai_discovery_runtime", None)
        if discovery_runtime is not None:
            planner_snapshot["discovery"] = discovery_runtime.planner_context(telemetry_payload)
        plan = host.ai_intention_planner.plan_autonomous(
            planner_snapshot,
            turn_seq=turn_seq,
        )
        discovery_id = ""
        discovery_grounding = ""
        if discovery_runtime is not None:
            plan, discovery_grounding, discovery_id = discovery_runtime.bind_plan(plan)
        if str(getattr(plan, "strategy", "") or "").strip().lower() == "share_discovery" and not discovery_grounding:
            plan = IntentionPlan.silence(channel="force_speak", reason="share_discovery_without_artifact")
        if not plan.speak or not plan.topic.strip():
            plan = IntentionPlan.from_mapping(
                {
                    "plan_id": f"force-speak-{int(time.time() * 1000)}",
                    "speak": True,
                    "motive": "user_force_speak",
                    "strategy": "direct_presence",
                    "value_focus": "continuity",
                    "topic": "Respond to the explicit request for presence with one short grounded line.",
                    "importance": 0.65,
                    "intrusion_risk": 0.05,
                    "confidence": 0.70,
                    "performance_hint": "neutral",
                    "tool_intent": "",
                    "tool_input": "",
                    "evidence_refs": [],
                    "semantics": {
                        "turn_kind": "force_speak",
                        "speech_act": "respond_explicit_presence_pull",
                        "subject_key": "explicit_user_pull",
                        "evidence_scope": "conversation",
                        "continuation_key": "current_public_turn",
                    },
                    "notes": "mechanical explicit user pull fallback",
                },
                channel="force_speak",
            )

        from runtime.public_lifecycle import lifecycle_for
        force_turn_id = str(plan.plan_id or f"force_speak:{turn_seq}")
        host._active_public_lifecycle_turn_id = force_turn_id
        lifecycle_for(host).begin(
            turn_id=force_turn_id,
            channel="force_speak",
            reason="force_speak_composing",
            received=False,
        )

        payload = host.ai_model_router.generate_autonomous_reply(
            plan=plan,
            personality_context=state.personality_prompt_context(),
            memory_context=memory_context,
            grounding_context="\n".join(
                part for part in (
                    "\n".join(str(item) for item in (vision_facts or ())[-6:]),
                    discovery_grounding,
                ) if part
            ),
            recent_history=host._chat_history_for_llm(limit=8),
            avoid_text="\n".join(
                str(item.get("content", "") or "").strip()
                for item in host._chat_history_for_llm(limit=6)
                if isinstance(item, Mapping) and str(item.get("role", "") or "") == "assistant"
            )[-1800:] or str(getattr(host, "last_text", "") or ""),
            allow_fallback=not no_fallback_mode_enabled(),
            language_hint=_runtime_language(),
            speech_language_hint=_runtime_speech_language(),
        )
        if not payload:
            lifecycle_for(host).transition(
                "DEGRADED", turn_id=force_turn_id, reason="semantic_deadline"
            )
            host.logger.warning("[architecture C force_speak] generation failed")
            return
        raw = json.dumps(_serializable_public_payload(payload), ensure_ascii=False)
        host._log_raw_llm_output("force_speak_ai", raw)
        decision = host.parser.parse(raw)
        if not str(getattr(decision, "utterance_turn_id", "") or "").strip():
            decision.utterance_turn_id = str(plan.plan_id or f"force_speak:{turn_seq}")
        host.ai_stage_planner.apply(decision, plan.performance_hint, state=state, channel="force_speak")
        decision = host._execute_system_action(decision, snapshot=snapshot, frame=None)
        text = str(getattr(decision, "text", "") or "").strip()
        if not text:
            lifecycle_for(host).transition(
                "DEGRADED", turn_id=force_turn_id, reason="empty_public_commit"
            )
            return
        turn_id = f"force_speak:{turn_seq}"
        text, assistant_meta = self._commit_public(
            decision,
            channel="force_speak",
            turn_seq=turn_seq,
        )
        if text and discovery_id and discovery_runtime is not None:
            discovery_runtime.mark_spoken(discovery_id, text)
        if not text:
            return
        host.last_autonomous_spoken_at = time.time()
        host._note_autonomous_spoken()
        initiative = getattr(host, "ai_initiative_controller", None)
        if initiative is not None:
            initiative.record_spoken(plan, now=host.last_autonomous_spoken_at, channel="force_speak")
        if plan.strategy:
            host.ai_state_reducer.submit(
                StateEvent.from_pending_strategy(
                    PendingStrategyUse(
                        strategy_use_id=f"strategy:{turn_id}",
                        turn_seq=turn_seq,
                        strategy=plan.strategy,
                        goal=plan.topic,
                        context=tuple(item for item in (plan.motive, plan.value_focus, "force_speak") if str(item or "").strip()),
                        assistant_text=text,
                    ),
                    base_version=host.ai_state_reducer.snapshot().version,
                )
            )
        if isinstance(getattr(decision, "action_result_meta", None), Mapping):
            host.ai_state_reducer.submit(
                StateEvent.from_mechanical_outcome(
                    dict(decision.action_result_meta),
                    turn_seq=turn_seq,
                    turn_id=turn_id,
                    base_version=host.ai_state_reducer.snapshot().version,
                )
            )
        host.ai_post_turn_observer.submit(
            turn_id=turn_id,
            turn_seq=turn_seq,
            user_text="[explicit force_speak request]",
            assistant_text=text,
            recent_history=tuple(host._chat_history_for_llm(limit=8)),
            mechanical_outcomes=(dict(decision.action_result_meta),)
                if isinstance(getattr(decision, "action_result_meta", None), Mapping)
                else (),
            state_summary=state.to_dict(),
            assistant_meta=assistant_meta,
            event_kind="force_speak",
        )
        host.logger.info("[architecture C force_speak] text=%s", text)

    def run_iteration(self) -> bool:
        """Facade mỏng; pipeline typed nằm trong ``self_turn_pipeline.py``."""
        # Adapter/test có thể thay trace_store trực tiếp trên facade. Đồng bộ lại
        # trước mỗi tick để không giữ hai sink debug khác nhau.
        self.self_turn_pipeline.trace_store = self.trace_store
        return self.self_turn_pipeline.run()


__all__ = [
    "AIChatOrchestrator",
    "AIAutonomousOrchestrator",
    "architecture_c_enabled",
]
