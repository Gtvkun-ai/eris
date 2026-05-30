from __future__ import annotations

"""
runtime.background_memory_digest_kernel
=======================================

Worker nền semantic digestion dùng MemoryKernel.

Khác với worker cũ tự cầm MemoryCommitPolicy + StateCommitter:
- Worker này không biết claim_builder/worthiness/store nằm ở đâu.
- Worker chỉ enqueue job rồi gọi memory_kernel.ingest(mode="semantic_digest").
- MemoryKernel chịu trách nhiệm policy, commit, candidate và debug.

Mục tiêu:
- Remote API đang pending thì local model có việc làm: phân rã trí nhớ.
- Hot path chat không phải chờ model local xử lý memory.
- Model local chỉ đọc nghĩa, không tự quyết trí nhớ cuối cùng.

Một con worker biết thân phận của mình. Hiếm, nhưng nên có.
"""

import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Mapping, Optional

try:
    from memory.memory_kernel import MemoryKernel
except Exception:  # pragma: no cover - khi chạy rời trong IDE
    from ..memory.memory_kernel import MemoryKernel  # type: ignore

DigestRole = Literal["user", "assistant", "system"]
DigestSource = Literal["chat_turn", "assistant_turn", "candidate_retry", "session_end", "idle_reflection"]
DigestPriority = Literal["high", "normal", "low"]


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


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except Exception:
        return default


@dataclass(frozen=True, slots=True)
class BackgroundMemoryDigestKernelConfig:
    """Config worker nền.

    enabled=True chỉ có nghĩa là worker được phép chạy.
    Builder vẫn nên kiểm tra có MemoryKernel và parser/model thật trước khi start.
    """

    enabled: bool = field(default_factory=lambda: _env_flag("ERIS_BACKGROUND_MEMORY_DIGEST", True))
    max_queue_size: int = field(default_factory=lambda: _env_int("ERIS_MEMORY_DIGEST_MAX_QUEUE", 64))
    worker_idle_sleep: float = field(default_factory=lambda: _env_float("ERIS_MEMORY_DIGEST_IDLE_SLEEP", 0.08))
    skip_if_older_seconds: float = field(default_factory=lambda: _env_float("ERIS_MEMORY_DIGEST_SKIP_OLDER_SEC", 240.0))
    pause_on_user_input: bool = field(default_factory=lambda: _env_flag("ERIS_MEMORY_DIGEST_PAUSE_ON_USER_INPUT", True))
    user_input_pause_seconds: float = field(default_factory=lambda: _env_float("ERIS_MEMORY_DIGEST_USER_INPUT_PAUSE_SEC", 0.35))
    idle_only: bool = field(default_factory=lambda: _env_flag("ERIS_MEMORY_DIGEST_IDLE_ONLY", True))
    idle_quiet_seconds: float = field(default_factory=lambda: _env_float("ERIS_MEMORY_DIGEST_IDLE_QUIET_SEC", 1.50))
    avoid_remote_inflight: bool = field(default_factory=lambda: _env_flag("ERIS_MEMORY_DIGEST_AVOID_REMOTE_INFLIGHT", True))
    only_when_remote_inflight: bool = field(default_factory=lambda: _env_flag("ERIS_MEMORY_DIGEST_ONLY_REMOTE_INFLIGHT", False))
    requeue_delay_seconds: float = field(default_factory=lambda: _env_float("ERIS_MEMORY_DIGEST_REQUEUE_DELAY_SEC", 0.35))
    max_defer_count: int = field(default_factory=lambda: _env_int("ERIS_MEMORY_DIGEST_MAX_DEFER", 240))
    storage_permission: bool = field(default_factory=lambda: _env_flag("ERIS_MEMORY_DIGEST_STORAGE_PERMISSION", True))


@dataclass(frozen=True, slots=True)
class MemoryDigestKernelJob:
    """Một job tiêu hóa memory nền.

    Worker không surface job ra user. Job chỉ là nguyên liệu cho MemoryKernel.ingest().
    """

    text: str
    turn_id: str = ""
    evidence_ids: tuple[str, ...] = ()
    role: DigestRole = "user"
    source: DigestSource = "chat_turn"
    priority: DigestPriority = "normal"
    context: Mapping[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    not_before: float = 0.0
    defer_count: int = 0
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(slots=True)
class MemoryDigestKernelStats:
    """Stats nhỏ cho dev/debug."""

    enqueued: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    committed: int = 0
    last_error: str = ""
    last_job_id: str = ""
    last_result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enqueued": self.enqueued,
            "processed": self.processed,
            "skipped": self.skipped,
            "failed": self.failed,
            "committed": self.committed,
            "last_error": self.last_error,
            "last_job_id": self.last_job_id,
            "last_result": dict(self.last_result),
        }


class BackgroundMemoryDigestKernelService:
    """Thread worker nền cho MemoryKernel semantic digestion."""

    def __init__(
        self,
        memory_kernel: MemoryKernel,
        *,
        config: BackgroundMemoryDigestKernelConfig | None = None,
        logger: Any = None,
        idle_probe: Any = None,
    ) -> None:
        self.memory_kernel = memory_kernel
        self.config = config or BackgroundMemoryDigestKernelConfig()
        self.enabled = bool(self.config.enabled and self.memory_kernel is not None)
        self.logger = logger
        self.idle_probe = idle_probe
        self.stats = MemoryDigestKernelStats()
        self._queue: queue.Queue[MemoryDigestKernelJob] = queue.Queue(maxsize=max(1, self.config.max_queue_size))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._remote_inflight = threading.Event()
        self._last_user_input_at = 0.0

    def start(self) -> None:
        """Start worker nếu chưa chạy."""

        if not self.config.enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ERIS-MemoryDigestKernel", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 1.5) -> None:
        """Stop worker nhẹ nhàng."""

        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def mark_remote_inflight(self, value: bool) -> None:
        """Runtime gọi True trước remote API, False sau khi nhận response."""

        if value:
            self._remote_inflight.set()
        else:
            self._remote_inflight.clear()

    def notify_remote_inflight(self, inflight: bool) -> None:
        """Compat với service cũ."""

        self.mark_remote_inflight(bool(inflight))

    def notify_user_input(self) -> None:
        """Báo worker biết user vừa nhập, để tránh tranh tài nguyên ngay lập tức."""

        self._last_user_input_at = time.time()

    def enqueue(
        self,
        text: str,
        *,
        turn_id: str = "",
        evidence_ids: list[str] | tuple[str, ...] | None = None,
        role: DigestRole = "user",
        source: DigestSource = "chat_turn",
        priority: DigestPriority = "normal",
        context: Mapping[str, Any] | None = None,
    ) -> bool:
        """Đưa job vào queue. Trả False nếu queue đầy hoặc text rỗng."""

        raw = str(text or "").strip()
        if not raw:
            self.stats.skipped += 1
            return False
        now = time.time()
        job = MemoryDigestKernelJob(
            text=raw,
            turn_id=str(turn_id or ""),
            evidence_ids=tuple(str(x) for x in (evidence_ids or ()) if str(x).strip()),
            role=role,
            source=source,
            priority=priority,
            context=dict(context or {}),
            not_before=now + (self.config.idle_quiet_seconds if self.config.idle_only else 0.0),
        )
        try:
            self._queue.put_nowait(job)
            self.stats.enqueued += 1
            return True
        except queue.Full:
            self.stats.skipped += 1
            self._log("warning", "memory_digest_queue_full")
            return False

    def enqueue_user_turn(
        self,
        text: str,
        *,
        turn_id: str = "",
        source: DigestSource = "chat_turn",
        priority: DigestPriority = "normal",
        context: Mapping[str, Any] | None = None,
    ) -> bool:
        """Compat với worker cũ: enqueue job user-turn và ghi nhận input mới."""

        self.notify_user_input()
        evidence_ids = [str(turn_id)] if str(turn_id or "").strip() else None
        return self.enqueue(
            text,
            turn_id=turn_id,
            evidence_ids=evidence_ids,
            role="user",
            source=source,
            priority=priority,
            context=context,
        )

    def drain_once_for_tests(self) -> int:
        """Chạy đồng bộ queue để test không cần thread nền."""

        processed = 0
        while True:
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                return processed
            try:
                action = self._gate_job(job)
                if action == "skip":
                    self.stats.skipped += 1
                    continue
                if action == "defer":
                    self._defer_job(job, reason="test_gate")
                    return processed
                self._process(job)
                processed += 1
            finally:
                try:
                    self._queue.task_done()
                except Exception:
                    pass
        return processed

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=self.config.worker_idle_sleep)
            except queue.Empty:
                continue
            try:
                action = self._gate_job(job)
                if action == "skip":
                    self.stats.skipped += 1
                    continue
                if action == "defer":
                    self._defer_job(job, reason="idle_gate")
                    time.sleep(min(max(float(self.config.worker_idle_sleep), 0.02), 0.50))
                    continue
                self._process(job)
            except Exception as exc:  # pragma: no cover - worker không được giết runtime
                self.stats.failed += 1
                self.stats.last_error = f"{type(exc).__name__}:{exc}"
                self._log("exception", "background_memory_digest_failed", exc_info=exc)
            finally:
                try:
                    self._queue.task_done()
                except Exception:
                    pass

    def _gate_job(self, job: MemoryDigestKernelJob) -> str:
        now = time.time()
        age = now - float(job.created_at)
        if age > self.config.skip_if_older_seconds:
            self._log("debug", f"memory_digest_skip_stale:{job.job_id}")
            return "skip"
        if int(job.defer_count) >= int(self.config.max_defer_count):
            self._log("debug", f"memory_digest_skip_too_many_defers:{job.job_id}")
            return "skip"
        if float(job.not_before or 0.0) > now:
            return "defer"
        if self.config.only_when_remote_inflight and not self._remote_inflight.is_set():
            self._log("debug", f"memory_digest_defer_not_remote_inflight:{job.job_id}")
            return "defer"
        if self.config.avoid_remote_inflight and self._remote_inflight.is_set():
            self._log("debug", f"memory_digest_defer_remote_inflight:{job.job_id}")
            return "defer"
        if self.config.pause_on_user_input and now - self._last_user_input_at < self.config.user_input_pause_seconds:
            self._log("debug", f"memory_digest_defer_recent_user_input:{job.job_id}")
            return "defer"
        if self.config.idle_only and not self._runtime_idle_enough(now):
            self._log("debug", f"memory_digest_defer_runtime_busy:{job.job_id}")
            return "defer"
        return "process"

    def _runtime_idle_enough(self, now: float | None = None) -> bool:
        now = time.time() if now is None else float(now)
        quiet_for = now - float(self._last_user_input_at or 0.0)
        if quiet_for < self.config.idle_quiet_seconds:
            return False
        probe = self.idle_probe
        if callable(probe):
            try:
                return bool(probe(quiet_for=quiet_for, now=now))
            except TypeError:
                try:
                    return bool(probe())
                except Exception:
                    return False
            except Exception:
                return False
        return True

    def _requeue(self, job: MemoryDigestKernelJob) -> None:
        self._queue.put_nowait(job)

    def _defer_job(self, job: MemoryDigestKernelJob, *, reason: str = "") -> bool:
        delay = max(0.05, float(self.config.requeue_delay_seconds))
        if self.config.idle_only:
            delay = max(delay, float(self.config.idle_quiet_seconds) * 0.25)
        try:
            self._requeue(
                replace(
                    job,
                    defer_count=int(job.defer_count) + 1,
                    not_before=time.time() + delay,
                )
            )
            return True
        except queue.Full:
            self.stats.skipped += 1
            self._log("warning", f"memory_digest_requeue_full:{job.job_id}:{reason}")
            return False

    def _process(self, job: MemoryDigestKernelJob) -> None:
        self.stats.last_job_id = job.job_id
        result = self.memory_kernel.ingest(
            job.text,
            evidence_ids=list(job.evidence_ids),
            turn_id=job.turn_id,
            source=job.source,
            mode="semantic_digest",
            allow_candidate=True,
            storage_permission=self.config.storage_permission,
            permission_required=False,
            context={
                **dict(job.context or {}),
                "background_job_id": job.job_id,
                "background_role": job.role,
                "background_priority": job.priority,
            },
        )
        self.stats.processed += 1
        self.stats.committed += result.committed_count
        self.stats.last_result = result.to_dict()
        self._log("debug", f"memory_digest_processed:{job.job_id}:{result.committed_count}")

    def _log(self, level: str, message: str, **kwargs: Any) -> None:
        logger = self.logger
        if logger is None:
            return
        method = getattr(logger, level, None) or getattr(logger, "info", None)
        if callable(method):
            try:
                method(message, **kwargs)
            except TypeError:
                method(message)


__all__ = [
    "BackgroundMemoryDigestKernelConfig",
    "MemoryDigestKernelJob",
    "MemoryDigestKernelStats",
    "BackgroundMemoryDigestKernelService",
]
