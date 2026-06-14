# -*- coding: utf-8 -*-
"""
runtime/tutor_daemon.py
=======================

Orchestrator vòng đời Tutor_Episode (ngoài hot path) + phát Popup_Event cho body.

Mọi exception bị bắt trong `run_once`: một lỗi của Tutor KHÔNG bao giờ được phép ném vào
CognitivePipeline/autonomous/chat.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

try:  # pragma: no cover
    from cortex.tutor.config import TutorConfig, TutorLogger, TutorRiskGuard, scrub_identity
    from cortex.tutor.contracts import TutorEpisode, TutorQuestion
except Exception:  # pragma: no cover
    from src.cortex.tutor.config import TutorConfig, TutorLogger, TutorRiskGuard, scrub_identity  # type: ignore
    from src.cortex.tutor.contracts import TutorEpisode, TutorQuestion  # type: ignore


_QUESTION_PREVIEW_LEN = 120


# =============================================================================
# Popup_Event emitter (UDP 4242 → body)
# =============================================================================

class TutorStageEmitter:
    """Gửi Popup_Event qua transport. Lỗi gửi không bao giờ chặn episode."""

    def __init__(self, transport: Any = None, logger: Optional[TutorLogger] = None) -> None:
        self._transport = transport
        self._logger = logger

    def emit(self, episode: TutorEpisode, stage: str) -> None:
        try:
            question_preview = ""
            if episode.question is not None:
                question_preview = scrub_identity(episode.question.text)[:_QUESTION_PREVIEW_LEN]
            payload = {
                "parse_mode": "tutor_event",
                "should_speak": False,
                "animation": "",
                "tutor": {
                    "episode_id": episode.episode_id,
                    "stage": stage,
                    "question_preview": question_preview,
                    "claims": int(episode.claims_committed),
                },
            }
            if self._logger is not None:
                self._logger.log_stage(episode.episode_id, stage)
            transport = self._transport
            if transport is None:
                return
            send = getattr(transport, "send_json", None)
            if callable(send):
                send(payload)
        except Exception:
            # Diễn cảnh là phụ; không được chặn việc học.
            try:
                if self._logger is not None:
                    self._logger.warn("popup emit failed")
            except Exception:
                pass


# =============================================================================
# Daemon
# =============================================================================

class TutorDaemon:
    """Chạy vòng đời một Tutor_Episode mỗi `run_once` khi đủ điều kiện."""

    def __init__(
        self,
        config: Optional[TutorConfig] = None,
        *,
        collector: Any,
        gate: Any,
        formulator: Any,
        backend: Any,
        digest: Any,
        share_impulse: Any = None,
        emitter: Optional[TutorStageEmitter] = None,
        risk_guard: Optional[TutorRiskGuard] = None,
        logger: Optional[TutorLogger] = None,
        drive_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.config = (config or TutorConfig()).normalized()
        self.collector = collector
        self.gate = gate
        self.formulator = formulator
        self.backend = backend
        self.digest = digest
        self.share_impulse = share_impulse
        self.emitter = emitter or TutorStageEmitter()
        self.risk_guard = risk_guard or TutorRiskGuard(self.config)
        self.logger = logger or TutorLogger()
        self._drive_fn = drive_fn

    # ------------------------------------------------------------------

    def run_once(self, *, idle: bool, now: Optional[float] = None) -> Optional[TutorEpisode]:
        if not self.config.enabled:
            return None
        now = float(now if now is not None else time.time())
        if self.risk_guard.is_paused(now):
            return None

        try:
            gap = self.gate.select(
                self.collector.drain_candidates(),
                idle=idle,
                now=now,
                drive_level=self._drive_level(),
            )
        except Exception:
            return None
        if gap is None:
            return None

        episode = TutorEpisode(gap=gap, started_ts=now)
        self.gate.note_started(now)
        self._emit(episode, "forming")

        # 1. Hình thành câu hỏi (không mở web nếu thất bại).
        try:
            question = self.formulator.formulate(gap)
        except Exception:
            question = None
        if question is None or not getattr(question, "is_valid", False):
            return self._fail(episode, "formulation_failed", now)
        episode.question = question

        # 2. Hỏi gia sư (backend tự emit opening/asking/reading qua callback).
        try:
            answer = self.backend.ask(question, on_stage=lambda s: self._emit(episode, s))
        except Exception:
            return self._fail(episode, "network_error", now)
        episode.answer = answer
        if answer is None or not getattr(answer, "ok", False) or not getattr(answer, "text", ""):
            reason = getattr(answer, "fail_reason", None) or "empty_answer"
            return self._fail(episode, reason, now)

        # 3. Tiêu hóa thành claim.
        self._emit(episode, "digesting")
        try:
            episode.claims_committed = self.digest.digest(episode)
        except Exception:
            episode.claims_committed = 0

        # 4. Giải quyết gap + khoe (nếu học được).
        if episode.claims_committed > 0:
            try:
                self.collector.resolve(gap)
            except Exception:
                pass
            if self.share_impulse is not None:
                try:
                    self.share_impulse.maybe_emit(episode, now=now)
                except Exception:
                    pass

        episode.stage = "done"
        episode.ended_ts = float(time.time())
        self._emit(episode, "done")
        self.logger.log_episode(episode.to_dict())
        self.risk_guard.note_success(now)
        return episode

    def stop(self) -> None:
        try:
            close = getattr(self.backend, "close", None)
            if callable(close):
                close()
        except Exception:
            pass

    # ------------------------------------------------------------------

    def _drive_level(self) -> float:
        if self._drive_fn is None:
            return 1.0
        try:
            return float(self._drive_fn())
        except Exception:
            return 1.0

    def _emit(self, episode: TutorEpisode, stage: str) -> None:
        episode.stage = stage  # type: ignore[assignment]
        self.emitter.emit(episode, stage)

    def _fail(self, episode: TutorEpisode, reason: str, now: float) -> TutorEpisode:
        episode.stage = "failed"
        episode.fail_reason = reason  # type: ignore[assignment]
        episode.ended_ts = float(time.time())
        if reason == "captcha_or_expired":
            self.risk_guard.note_captcha(now)
        else:
            self.risk_guard.note_failure(now, reason)
        self._emit(episode, "failed")
        self.logger.log_episode(episode.to_dict())
        return episode


__all__ = ["TutorDaemon", "TutorStageEmitter"]
