# -*- coding: utf-8 -*-
"""
runtime/shadow_pipeline.py

Shadow mode cho CognitivePipeline (V3).

Ý tưởng:
    Runtime thật vẫn chạy frame cũ (cortex/contracts.CognitiveFrame) qua
    coordinator/chat_cycle như thường. Song song đó, ta dựng RawSignal từ ĐÚNG
    cùng input (user_text, snapshot, vision_facts), chạy CognitivePipeline V3,
    rồi render debug_trace cả hai bên để so.

    Shadow = chỉ quan sát. Nó KHÔNG được phép:
        - đổi quyết định của frame cũ
        - ném exception ra hot path
        - làm chậm runtime đáng kể khi tắt

    Mục tiêu là tích lũy bằng chứng "V3 chọn focus/budget giống hay khác frame cũ"
    trước khi dám chuyển tải. Chuyển tải mù là cách tốt để biến một refactor thành
    một đám tang production.

Bật/tắt:
    - env ERIS_SHADOW_PIPELINE=1, hoặc
    - self.shadow_pipeline_enabled = True

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


class ShadowPipelineMixin:
    """Trộn vào RuntimeCoordinator để chạy V3 pipeline ở chế độ shadow."""

    # ------------------------------------------------------------------
    # Gate + lazy engine
    # ------------------------------------------------------------------

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

        if not self._shadow_pipeline_enabled():
            return None

        try:
            started = time.time()
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
            )
            elapsed_ms = (time.time() - started) * 1000.0

            shadow_trace = result.debug_trace
            old_trace = self._safe_render_trace(old_frame)
            comparison = self._compare_traces(
                v3_trace=shadow_trace,
                old_trace=old_trace,
                elapsed_ms=elapsed_ms,
                channel=channel,
            )

            self.last_shadow_pipeline_result = result
            self.last_shadow_trace = shadow_trace
            self.last_shadow_comparison = comparison
            self._log_shadow_comparison(comparison, shadow_trace, old_trace)
            return result
        except Exception as exc:  # shadow không bao giờ được làm chết hot path
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.warning("[shadow pipeline] error (nuốt, runtime thật tiếp tục): %r", exc)
            self.last_shadow_pipeline_result = None
            self.last_shadow_trace = {}
            self.last_shadow_comparison = {"error": repr(exc)}
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
