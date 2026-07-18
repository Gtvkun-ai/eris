# -*- coding: utf-8 -*-
"""
runtime/shadow_pipeline.py

Bridge chuyển tải CognitivePipeline (V3) vào runtime production.

Ý tưởng:
    Production still exposes the compatibility frame (cortex/contracts.CognitiveFrame) qua
    coordinator/chat_cycle như thường. Song song đó, ta dựng RawSignal từ ĐÚNG
    cùng input (user_text, snapshot, vision_facts), chạy CognitivePipeline V3,
    rồi render debug_trace cả hai bên để so.

    V3 planning chạy mặc định trên mọi chat/autonomous/force_speak cycle, gắn
    canonical frame + prompt projection vào frame production, rồi được khép vòng
    sau execution. Shadow comparison vẫn là debug tùy chọn, không còn là gate khiến
    cả kiến trúc chỉ tồn tại trên giấy.

Bật/tắt:
    - ERIS_V3_PIPELINE=0 để tắt bridge V3 (mặc định bật)
    - ERIS_SHADOW_PIPELINE=1 để log thêm so sánh V3 với trace cũ

Kết quả lưu trên coordinator để test/inspect:
    - self.last_shadow_pipeline_result : PipelineResult | None
    - self.last_shadow_trace           : dict (trace V3)
    - self.last_shadow_comparison      : dict (so V3 vs frame cũ)
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional, Sequence

from core.evidence import RawSignal
from runtime.cognitive_pipeline import CognitivePipeline, PipelineResult
from runtime.debug_trace import render_frame_trace
from runtime.v3_authority import V3AuthorityController
from runtime.v3_consolidation import build_v3_daydream_packets


class ShadowPipelineMixin:
    """Trộn V3 canonical pipeline + production authority vào RuntimeCoordinator."""

    # ------------------------------------------------------------------
    # Gate + lazy engine
    # ------------------------------------------------------------------

    def _v3_pipeline_enabled(self) -> bool:
        """V3 đọc policy trực tiếp từ RuntimeSettingsStore mỗi lượt."""
        try:
            from runtime.runtime_settings_store import runtime_bool
            return runtime_bool("pipeline", "v3_enabled", default=True)
        except Exception:
            return bool(getattr(self, "v3_pipeline_enabled", True))

    def _shadow_pipeline_enabled(self) -> bool:
        if getattr(self, "shadow_pipeline_enabled", False):
            return True
        raw = os.getenv("ERIS_SHADOW_PIPELINE")
        if raw is None:
            return False
        return raw.strip().lower() in {"1", "true", "yes", "on", "y"}

    def _get_shadow_pipeline(self) -> CognitivePipeline:
        pipeline = getattr(self, "_shadow_pipeline_instance", None)
        if pipeline is None:
            pipeline = CognitivePipeline()
            self._shadow_pipeline_instance = pipeline
        return pipeline

    def _get_v3_authority(self) -> V3AuthorityController:
        controller = getattr(self, "_v3_authority_instance", None)
        if controller is None:
            controller = V3AuthorityController()
            self._v3_authority_instance = controller
        return controller

    # ------------------------------------------------------------------
    # Promotion: V3 thành xương sống cho vài path quan trọng
    # ------------------------------------------------------------------

    #: Các path V3 có thể nhận làm xương sống. "budget" có consumer thật ở tầng
    #: memory (MemoryCognitionCore._budget_from_frame) + global_workspace, nên là
    #: path promote an toàn nhất. "focus"/"evidence" hiện ghi advisory lên frame
    #: (không ghi đè broadcast cũ) để downstream/prompt có thể đọc khi muốn.
    _V3_PROMOTABLE_PATHS: frozenset[str] = frozenset({"budget", "focus", "evidence", "meaning", "tom", "agency", "permission", "speech", "body", "modality", "knowledge"})

    def _v3_promoted_paths(self) -> frozenset[str]:
        """Tập path V3 được phép ghi đè frame cũ.

        Nguồn: attr `self.v3_promoted_paths` (set/iterable/str) hoặc env
        `ERIS_V3_PROMOTE` (danh sách phẩy, hoặc "all"). Rỗng = không promote
        (shadow thuần). Giá trị lạ bị bỏ qua.
        """
        raw = getattr(self, "v3_promoted_paths", None)
        if raw is None:
            raw = os.getenv("ERIS_V3_PROMOTE", "")
        if isinstance(raw, str):
            tokens = [tok.strip().lower() for tok in raw.split(",") if tok.strip()]
        else:
            try:
                tokens = [str(tok).strip().lower() for tok in raw]
            except TypeError:
                return frozenset()
        if "all" in tokens:
            return self._V3_PROMOTABLE_PATHS
        return frozenset(tokens) & self._V3_PROMOTABLE_PATHS

    def _promote_v3_paths(
        self,
        result: Optional[PipelineResult],
        *,
        old_frame: Any,
        channel: str,
    ) -> dict[str, Any]:
        """Ghi quyết định V3 lên frame cũ cho các path đã bật. Không bao giờ raise.

        Trả dict audit (path -> giá trị đã promote). Lưu trên
        `self.last_v3_promotion` để test/inspect.
        """
        promotion: dict[str, Any] = {"channel": channel, "applied": {}}
        self.last_v3_promotion = promotion
        if result is None or old_frame is None:
            return promotion
        paths = self._v3_promoted_paths()
        if not paths:
            return promotion

        applied = promotion["applied"]
        trace = getattr(result, "debug_trace", {}) or {}

        if "budget" in paths:
            mode = str(getattr(result, "budget_mode", "") or "")
            if mode and mode != "unknown":
                if self._set_frame_attr(old_frame, "v3_budget_mode", mode):
                    decision = getattr(result, "budget_decision", None)
                    self._set_frame_metadata(
                        old_frame,
                        "v3_budget_decision",
                        decision.to_dict() if hasattr(decision, "to_dict") else mode,
                    )
                    applied["budget"] = mode

        if "focus" in paths:
            focus = trace.get("dominant_focus")
            if focus and self._set_frame_metadata(old_frame, "v3_dominant_focus", focus):
                applied["focus"] = focus

        if "evidence" in paths:
            evidence = trace.get("selected_evidence")
            if evidence and self._set_frame_metadata(old_frame, "v3_selected_evidence", list(evidence)):
                applied["evidence"] = list(evidence)

        v3 = getattr(result, "frame", None)
        for path, attr in (
            ("meaning", "meaning"), ("tom", "tom"), ("agency", "agency"),
            ("permission", "permission"), ("speech", "speech_plan"),
            ("body", "body_plan"), ("modality", "modality"),
        ):
            if path in paths and v3 is not None:
                value = getattr(v3, attr, None)
                if value is not None and self._set_frame_metadata(old_frame, f"v3_{attr}", value):
                    applied[path] = getattr(value, "to_dict", lambda: repr(value))()
        if "knowledge" in paths and v3 is not None:
            value = (getattr(v3, "metadata", {}) or {}).get("knowledge_acquisition")
            if value is not None and self._set_frame_attr(old_frame, "v3_knowledge", value):
                applied["knowledge"] = getattr(value, "to_dict", lambda: repr(value))()

        if applied:
            self._record_frame_note(old_frame, f"v3_promoted={','.join(sorted(applied))}")
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.info("[v3 promotion] channel=%s applied=%s", channel, applied)
        return promotion

    @staticmethod
    def _set_frame_attr(frame: Any, name: str, value: Any) -> bool:
        try:
            setattr(frame, name, value)
            return True
        except Exception:
            try:
                frame[name] = value  # type: ignore[index]
                return True
            except Exception:
                return False

    def _set_frame_metadata(self, frame: Any, key: str, value: Any) -> bool:
        metadata = getattr(frame, "metadata", None)
        if isinstance(metadata, dict):
            try:
                metadata[key] = value
                return True
            except Exception:
                pass
        return self._set_frame_attr(frame, key, value)

    @staticmethod
    def _record_frame_note(frame: Any, note: str) -> None:
        notes = getattr(frame, "debug_notes", None)
        if isinstance(notes, list):
            try:
                notes.append(note)
                return
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Entrypoint gọi từ chat_cycle / cognitive_cycle
    # ------------------------------------------------------------------

    def _run_shadow_cognitive_pipeline(
        self,
        *,
        channel: str,
        user_text: str = "",
        snapshot: Any = None,
        vision_facts: Sequence[str] = (),
        old_frame: Any = None,
        active_goal: Any = None,
    ) -> Optional[PipelineResult]:
        """Chạy V3 pipeline shadow và so trace với frame cũ.

        Trả PipelineResult nếu chạy được, None nếu tắt hoặc lỗi (đã nuốt).
        """

        if not self._v3_pipeline_enabled():
            return None

        try:
            started = time.time()
            if user_text:
                self._resolve_v3_feedback_for_previous_turn(user_text, current_frame=old_frame)
            raw_signals = self._build_shadow_raw_signals(
                user_text=user_text,
                snapshot=snapshot,
                vision_facts=vision_facts,
            )
            idle_seconds = self._shadow_idle_seconds(snapshot)
            pipeline = self._get_shadow_pipeline()
            result = pipeline.run_from_signals(
                raw_signals,
                channel=channel,
                user_text=user_text,
                active_goal=active_goal,
                idle_seconds=idle_seconds,
                legacy_frame=old_frame,
                snapshot=snapshot,
                runtime_owner=self,
            )
            elapsed_ms = (time.time() - started) * 1000.0

            shadow_trace = result.debug_trace

            # Gắn canonical frame vào frame production. Prompt projection là phần
            # V3 tác động thật lên wording; frame object được giữ để finalizer nối
            # Outcome/SelfObservation sau khi output đã thực thi.
            if old_frame is not None:
                self._set_frame_attr(old_frame, "v3_cognitive_frame", result.frame)
                self._set_frame_attr(old_frame, "v3_budget_mode", result.budget_mode)
                self._set_frame_attr(old_frame, "v3_prompt_context", pipeline.render_prompt_context(result.frame))
                knowledge = (getattr(result.frame, "metadata", {}) or {}).get("knowledge_acquisition")
                self._set_frame_attr(old_frame, "v3_knowledge", knowledge)
                projection = self._get_v3_authority().project_to_legacy(result.frame, old_frame)
                self._set_frame_attr(old_frame, "v3_authority", projection)
                self._record_frame_note(old_frame, f"v3_planning_complete={result.frame.frame_id}")

            self.last_shadow_pipeline_result = result
            self.last_shadow_trace = shadow_trace

            if self._shadow_pipeline_enabled():
                old_trace = self._safe_render_trace(old_frame)
                comparison = self._compare_traces(
                    v3_trace=shadow_trace,
                    old_trace=old_trace,
                    elapsed_ms=elapsed_ms,
                    channel=channel,
                )
                self.last_shadow_comparison = comparison
                self._log_shadow_comparison(comparison, shadow_trace, old_trace)
            else:
                self.last_shadow_comparison = {
                    "channel": channel,
                    "v3_frame_id": result.frame.frame_id,
                    "v3_budget": result.budget_mode,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "comparison_disabled": True,
                }

            # Giữ promotion flags cũ cho migration có kiểm soát; budget consumer
            # giờ đọc v3_budget_mode nên không còn setattr vào slot không tồn tại.
            self._promote_v3_paths(result, old_frame=old_frame, channel=channel)
            return result
        except Exception as exc:  # shadow không bao giờ được làm chết hot path
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.warning("[shadow pipeline] error (nuốt, runtime thật tiếp tục): %r", exc)
            self.last_shadow_pipeline_result = None
            self.last_shadow_trace = {}
            self.last_shadow_comparison = {"error": repr(exc)}
            return None

    def _apply_v3_authority_guard(
        self,
        decision: Any,
        *,
        frame: Any = None,
        channel: str = "",
    ) -> Any:
        """Cổng authoritative cuối trước execution/body."""
        from runtime.final_passthrough_policy import audit_only, final_passthrough_enabled
        if final_passthrough_enabled():
            return audit_only(decision, f"v3_authority:{channel}")
        try:
            governed = self._get_v3_authority().apply_to_decision(
                decision,
                legacy_frame=frame,
                v3_frame=getattr(frame, "v3_cognitive_frame", None) if frame is not None else None,
                channel=channel,
            )
            v3_frame = getattr(frame, "v3_cognitive_frame", None) if frame is not None else None
            if v3_frame is not None:
                pipeline = self._get_shadow_pipeline()
                governed, report = pipeline.grounding_guard.check(
                    v3_frame,
                    governed,
                    external_grounding=getattr(frame, "grounding", None),
                )
                try:
                    v3_frame.grounding = report
                    frame.v3_grounding_report = report
                except Exception:
                    pass
            return governed
        except Exception as exc:
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.warning("[v3 authority] lỗi, giữ decision cũ: %r", exc)
            return decision

    def _resolve_v3_feedback_for_previous_turn(self, user_text: str, *, current_frame: Any = None) -> Any:
        """Dùng turn N+1 để đóng outcome thật của canonical turn N."""
        previous = getattr(self, "last_cognitive_frame", None)
        if previous is None or previous is current_frame or bool(getattr(previous, "v3_feedback_resolved", False)):
            return None
        v3_frame = getattr(previous, "v3_cognitive_frame", None)
        if v3_frame is None or str(getattr(v3_frame, "status", "")) != "closed":
            return None
        try:
            pipeline = self._get_shadow_pipeline()
            report = pipeline.outcome_observer.observe_user_feedback_for_previous_frame(
                v3_frame, str(user_text or ""), attach_to_frame=True
            )
            v3_frame.outcome = report
            self_obs = pipeline.self_observer.reflect(v3_frame, outcome=report, attach_to_frame=False)
            v3_frame.self_observation = self_obs
            pipeline.self_observer.append_repair_commit_request(v3_frame, report=self_obs)
            # Outcome thật chỉ xuất hiện ở turn kế tiếp. Chạy lại scheduler ở đây
            # để correction/rupture không bị bỏ lỡ chỉ vì frame đã đóng trước đó.
            # LongTermUpdateEngine chỉ phát StateCommitRequest, không ghi thẳng store.
            try:
                pipeline.long_term_update.prepare(v3_frame)
            except Exception as exc:
                try:
                    v3_frame.add_warning(f"feedback long-term update failed: {exc!r}", actor="dream_consolidation")
                except Exception:
                    pass
            self._set_frame_attr(previous, "v3_feedback_resolved", True)
            self._set_frame_attr(previous, "outcome", report)
            self._set_frame_attr(previous, "self_observation", self_obs)
            new_requests = list(getattr(v3_frame, "commit_requests", []) or [])
            requests = getattr(previous, "commit_requests", None)
            if isinstance(requests, list):
                requests.extend(new_requests)
            # Previous frame đã commit xong. Repair từ phản hồi N+1 phải đi nhờ
            # current frame qua StateCommitter, nếu không nó chỉ nằm đẹp trong
            # một object đã đóng và chẳng bao giờ thành trí nhớ.
            current_requests = getattr(current_frame, "commit_requests", None)
            if isinstance(current_requests, list):
                existing = {
                    (str(getattr(req, "target", "")), str(getattr(req, "content", "")))
                    for req in current_requests
                }
                for req in new_requests:
                    key = (str(getattr(req, "target", "")), str(getattr(req, "content", "")))
                    if key not in existing:
                        current_requests.append(req)
                        existing.add(key)
            packets = build_v3_daydream_packets(v3_frame)
            queue = getattr(self, "v3_daydream_packets", None)
            if not isinstance(queue, list):
                queue = []
                self.v3_daydream_packets = queue
            queue.extend(packets)
            del queue[:-80]
            self._record_frame_note(previous, f"v3_feedback_resolved={getattr(report, 'tags', ())}")
            return report
        except Exception as exc:
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.warning("[v3 outcome feedback] lỗi: %r", exc)
            return None

    def _v3_prompt_context(self, frame: Any) -> str:
        return str(getattr(frame, "v3_prompt_context", "") or "") if frame is not None else ""

    def _merge_v3_prompt_context(self, base: str, frame: Any) -> str:
        v3 = self._v3_prompt_context(frame)
        base = str(base or "").strip()
        if not v3:
            return base
        return f"{base}\n\n{v3}".strip()

    def _finalize_v3_cognitive_frame(self, old_frame: Any) -> Optional[PipelineResult]:
        """Đưa kết quả production vào canonical frame và đóng vòng V3."""
        if old_frame is None or bool(getattr(old_frame, "v3_pipeline_finalized", False)):
            return None
        v3_frame = getattr(old_frame, "v3_cognitive_frame", None)
        if v3_frame is None:
            return None
        try:
            pipeline = self._get_shadow_pipeline()
            result = pipeline.finalize_from_production(
                v3_frame,
                legacy_frame=old_frame,
                final_decision=getattr(old_frame, "final_decision", None),
                grounding=getattr(old_frame, "grounding", None),
                execution=(getattr(old_frame, "v3_tool_execution_result", None) or getattr(old_frame, "execution", None)),
                outcome=getattr(old_frame, "outcome", None),
                self_observation=getattr(old_frame, "self_observation", None),
            )
            self._set_frame_attr(old_frame, "v3_pipeline_finalized", True)
            # Đưa commit request canonical sang cổng StateCommitter production.
            # Recorder sẽ dedupe trước commit, nên cùng một repair request không
            # nhân đôi chỉ vì hai frame cùng nhìn thấy lỗi.
            legacy_requests = getattr(old_frame, "commit_requests", None)
            if isinstance(legacy_requests, list):
                legacy_requests.extend(list(getattr(result.frame, "commit_requests", []) or []))
            knowledge = (getattr(result.frame, "metadata", {}) or {}).get("knowledge_acquisition")
            self._set_frame_attr(old_frame, "v3_knowledge", knowledge)
            packets = build_v3_daydream_packets(result.frame)
            self._set_frame_attr(old_frame, "v3_daydream_packets", packets)
            queue = getattr(self, "v3_daydream_packets", None)
            if not isinstance(queue, list):
                queue = []
                self.v3_daydream_packets = queue
            queue.extend(packets)
            del queue[:-80]
            self._record_frame_note(old_frame, f"v3_finalized={result.frame.frame_id}")
            self.last_shadow_pipeline_result = result
            self.last_shadow_trace = result.debug_trace
            return result
        except Exception as exc:
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.warning("[v3 pipeline] production finalization failed; compatibility runtime continues: %r", exc)
            self._record_frame_note(old_frame, f"v3_finalize_error={exc!r}")
            return None

    # ------------------------------------------------------------------
    # RawSignal builder từ input frame cũ
    # ------------------------------------------------------------------

    def _build_shadow_raw_signals(
        self,
        *,
        user_text: str,
        snapshot: Any,
        vision_facts: Sequence[str],
    ) -> list[RawSignal]:
        signals: list[RawSignal] = []

        if user_text:
            signals.append(RawSignal.from_chat(user_text))

        active_window = self._snap(snapshot, ("active_window", "active_app", "active_window_kind"))
        if active_window:
            signals.append(RawSignal.from_active_window(str(active_window)))

        focus_summary = self._snap(snapshot, ("focus_summary",))
        idle_seconds = self._shadow_idle_seconds(snapshot)
        recent_events = tuple(self._snap(snapshot, ("recent_events",), default=()) or ())
        evidence = tuple(self._snap(snapshot, ("evidence",), default=()) or ())
        telemetry: dict[str, Any] = {}
        if focus_summary:
            telemetry["focus_summary"] = str(focus_summary)
        if idle_seconds is not None:
            telemetry["idle_seconds"] = idle_seconds
        if recent_events:
            telemetry["recent_events"] = [str(e) for e in recent_events[:6]]
        if evidence:
            telemetry["evidence"] = [str(e) for e in evidence[:6]]
        if telemetry:
            signals.append(RawSignal.from_telemetry(telemetry))

        for fact in tuple(vision_facts or ())[:8]:
            text = str(fact or "").strip()
            if text:
                signals.append(RawSignal.from_vision(text))

        return signals

    @staticmethod
    def _snap(snapshot: Any, names: tuple[str, ...], default: Any = "") -> Any:
        for name in names:
            value = getattr(snapshot, name, None)
            if value:
                return value
        return default

    def _shadow_idle_seconds(self, snapshot: Any) -> Optional[float]:
        value = getattr(snapshot, "idle_seconds", None)
        if value is None:
            return None
        try:
            return float(value)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # So sánh trace V3 vs frame cũ
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_render_trace(frame: Any) -> dict[str, Any]:
        if frame is None:
            return {}
        try:
            return render_frame_trace(frame)
        except Exception as exc:
            return {"old_frame_trace_error": repr(exc)}

    def _compare_traces(
        self,
        *,
        v3_trace: dict[str, Any],
        old_trace: dict[str, Any],
        elapsed_ms: float,
        channel: str,
    ) -> dict[str, Any]:
        v3_focus = str(v3_trace.get("dominant_focus", "") or "")
        old_focus = str(old_trace.get("dominant_focus", "") or "")
        return {
            "channel": channel,
            "v3_frame_id": v3_trace.get("frame_id"),
            "old_frame_id": old_trace.get("frame_id"),
            "v3_budget": v3_trace.get("budget"),
            "v3_dominant_focus": v3_focus or None,
            "old_dominant_focus": old_focus or None,
            "focus_overlap": self._focus_overlap(v3_focus, old_focus),
            "v3_evidence_count": v3_trace.get("evidence_count"),
            "v3_selected_evidence": v3_trace.get("selected_evidence"),
            "elapsed_ms": round(elapsed_ms, 2),
        }

    @staticmethod
    def _focus_overlap(a: str, b: str) -> float:
        """Jaccard token nhẹ giữa hai focus, chỉ để cảm nhận độ trùng."""

        ta = {t for t in a.lower().split() if len(t) > 2}
        tb = {t for t in b.lower().split() if len(t) > 2}
        if not ta or not tb:
            return 0.0
        inter = len(ta & tb)
        union = len(ta | tb)
        return round(inter / union, 3) if union else 0.0

    def _log_shadow_comparison(
        self,
        comparison: dict[str, Any],
        v3_trace: dict[str, Any],
        old_trace: dict[str, Any],
    ) -> None:
        logger = getattr(self, "logger", None)
        if logger is None:
            return
        logger.info(
            "[shadow pipeline] budget=%s | v3_focus=%r | old_focus=%r | overlap=%.2f | ev=%s | %.1fms",
            comparison.get("v3_budget"),
            comparison.get("v3_dominant_focus"),
            comparison.get("old_dominant_focus"),
            float(comparison.get("focus_overlap", 0.0) or 0.0),
            comparison.get("v3_evidence_count"),
            float(comparison.get("elapsed_ms", 0.0) or 0.0),
        )


__all__ = ["ShadowPipelineMixin"]
