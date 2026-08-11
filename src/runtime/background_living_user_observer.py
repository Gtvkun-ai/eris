from __future__ import annotations

"""Dedicated background lane for living-user/profile observation.

This service deliberately owns no public response path. User turns are queued and
processed by ``LivingUserMemoryService.observe_turn`` on a daemon worker so profile
extraction, curator inference, JSON persistence, and trace writes never block the
chat writer.
"""

import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


@dataclass(frozen=True, slots=True)
class BackgroundLivingUserObserverConfig:
    enabled: bool = field(default_factory=lambda: _env_flag("ERIS_BACKGROUND_LIVING_USER_OBSERVER", True))
    max_queue_size: int = field(default_factory=lambda: max(1, _env_int("ERIS_LIVING_USER_OBSERVER_MAX_QUEUE", 64)))


@dataclass(frozen=True, slots=True)
class LivingUserObservationJob:
    text: str
    evidence_ids: tuple[str, ...]
    turn_id: str = ""
    source: str = "chat_turn"
    context: Mapping[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(slots=True)
class BackgroundLivingUserObserverStats:
    enqueued: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    applied: int = 0
    rejected: int = 0
    last_error: str = ""
    last_job_id: str = ""
    last_latency_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "enqueued": self.enqueued,
            "processed": self.processed,
            "skipped": self.skipped,
            "failed": self.failed,
            "applied": self.applied,
            "rejected": self.rejected,
            "last_error": self.last_error,
            "last_job_id": self.last_job_id,
            "last_latency_s": self.last_latency_s,
        }


class BackgroundLivingUserObserverService:
    """Single-owner curator lane for per-turn living-user observation."""

    def __init__(self, living_user: Any, *, logger: Any = None, config: BackgroundLivingUserObserverConfig | None = None) -> None:
        self.living_user = living_user
        self.logger = logger
        self.config = config or BackgroundLivingUserObserverConfig()
        self.enabled = bool(self.config.enabled and living_user is not None)
        self.stats = BackgroundLivingUserObserverStats()
        self._queue: queue.Queue[LivingUserObservationJob] = queue.Queue(maxsize=self.config.max_queue_size)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.enabled:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ERIS-LivingUserCurator", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 1.5) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def enqueue_user_turn(
        self,
        text: str,
        *,
        turn_id: str = "",
        evidence_ids: tuple[str, ...] | list[str] | None = None,
        source: str = "chat_turn",
        context: Mapping[str, Any] | None = None,
    ) -> bool:
        raw = str(text or "").strip()
        ids = tuple(str(x) for x in (evidence_ids or ()) if str(x).strip())
        if not ids and str(turn_id or "").strip():
            ids = (str(turn_id).strip(),)
        if not self.enabled or not raw or not ids:
            self.stats.skipped += 1
            return False
        job = LivingUserObservationJob(
            text=raw,
            turn_id=str(turn_id or "").strip(),
            evidence_ids=ids,
            source=str(source or "chat_turn"),
            context=dict(context or {}),
        )
        try:
            self._queue.put_nowait(job)
            self.stats.enqueued += 1
            return True
        except queue.Full:
            self.stats.skipped += 1
            self._log("warning", "living_user_observer_queue_full")
            return False

    def drain_once_for_tests(self) -> int:
        processed = 0
        while True:
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                return processed
            try:
                self._process(job)
                processed += 1
            finally:
                self._queue.task_done()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=0.20)
            except queue.Empty:
                continue
            try:
                self._process(job)
            except Exception as exc:  # pragma: no cover - background lane must not kill runtime
                self.stats.failed += 1
                self.stats.last_error = f"{type(exc).__name__}:{exc}"
                self._log("exception", "background_living_user_observer_failed", exc_info=exc)
            finally:
                try:
                    self._queue.task_done()
                except Exception:
                    pass

    def _process(self, job: LivingUserObservationJob) -> None:
        started = time.perf_counter()
        result = self.living_user.observe_turn(
            job.text,
            evidence_ids=job.evidence_ids,
            context={
                **dict(job.context or {}),
                "source": job.source,
                "background_job_id": job.job_id,
                "background_lane": "curator",
            },
        )
        self.stats.processed += 1
        self.stats.applied += int(getattr(result, "applied", 0) or 0)
        self.stats.rejected += int(getattr(result, "rejected", 0) or 0)
        self.stats.last_job_id = job.job_id
        self.stats.last_latency_s = max(0.0, time.perf_counter() - started)
        self._log(
            "debug",
            "living_user_observer_processed:%s:applied=%s:latency=%.3fs",
            job.job_id,
            int(getattr(result, "applied", 0) or 0),
            self.stats.last_latency_s,
        )

    def _log(self, level: str, message: str, *args: Any, **kwargs: Any) -> None:
        logger = self.logger
        fn = getattr(logger, level, None) if logger is not None else None
        if callable(fn):
            try:
                fn(message, *args, **kwargs)
            except Exception:
                pass


def build_background_living_user_observer_service(
    *, living_user: Any, logger: Any = None, config: BackgroundLivingUserObserverConfig | None = None
) -> BackgroundLivingUserObserverService | None:
    service = BackgroundLivingUserObserverService(living_user, logger=logger, config=config)
    if not service.enabled:
        return None
    service.start()
    return service


__all__ = [
    "BackgroundLivingUserObserverConfig",
    "BackgroundLivingUserObserverService",
    "BackgroundLivingUserObserverStats",
    "LivingUserObservationJob",
    "build_background_living_user_observer_service",
]
