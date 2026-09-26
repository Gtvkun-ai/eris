"""Durable scheduling adapter for the pure pedagogical controller."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import math
import threading
import time
from typing import Any, Callable, Iterator, Mapping

from runtime.ai_orchestrated.atomic_state import SQLiteAtomicStateStore, SQLiteStateTransaction
from runtime.pedagogical_contracts import TeachingDirective, TeachingEpisode, TeachingReceipt, normalize_episode
from runtime.runtime_settings_store import runtime_bool
from runtime.pedagogical_controller import (
    ControllerResult,
    expire_if_needed,
    note_audio_finished,
    note_public_commit,
    observe_user_turn,
    select_next_action,
)


PEDAGOGY_RUNTIME_SCHEMA = "eris.pedagogy.v1"
DWELL_SECONDS = 1.0
CLAIM_LEASE_SECONDS = 2.0
MAX_ID = 120


def _timestamp(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) and 0.0 <= number <= 10**12 else default


def _identifier(value: Any) -> str:
    return str(value or "").strip()[:MAX_ID]


def _counter(value: Any) -> int:
    try:
        return max(0, min(1_000_000_000, int(value)))
    except (TypeError, ValueError, OverflowError):
        return 0


def _empty_state() -> dict[str, Any]:
    return {
        "schema": PEDAGOGY_RUNTIME_SCHEMA,
        "version": 0,
        "episode": None,
        "dwell_anchor_at": 0.0,
        "dwell_due_at": 0.0,
        "claim_owner": "",
        "claim_until": 0.0,
        "claim_token": "",
        "committed_turn_id": "",
        "cancel_reason": "",
    }


def _state_from_mapping(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    data = payload if isinstance(payload, Mapping) else {}
    episode_data = data.get("episode")
    episode = normalize_episode(episode_data) if isinstance(episode_data, Mapping) else None
    state = _empty_state()
    state.update(
        version=_counter(data.get("version", 0)),
        episode=episode.to_dict() if episode is not None else None,
        dwell_anchor_at=_timestamp(data.get("dwell_anchor_at")),
        dwell_due_at=_timestamp(data.get("dwell_due_at")),
        claim_owner=_identifier(data.get("claim_owner")),
        claim_until=_timestamp(data.get("claim_until")),
        claim_token=_identifier(data.get("claim_token")),
        committed_turn_id=_identifier(data.get("committed_turn_id")),
        cancel_reason=_identifier(data.get("cancel_reason")),
    )
    return state


class PedagogicalRuntime:
    """Owns SQLite persistence, dwell scheduling, and worker claims."""

    def __init__(
        self,
        store: SQLiteAtomicStateStore,
        *,
        state_key: str = "eris.pedagogy",
        clock: Callable[[], float] | None = None,
        timer_factory: Callable[..., Any] | None = None,
        wake_callback: Callable[[str], None] | None = None,
    ) -> None:
        if not isinstance(store, SQLiteAtomicStateStore):
            raise TypeError("store must be a SQLiteAtomicStateStore")
        self._store = store
        self._state_key = _identifier(state_key) or "eris.pedagogy"
        self._clock = clock or time.time
        self._timer_factory = timer_factory or threading.Timer
        self._wake_callback = wake_callback
        self._lock = threading.RLock()
        self._timer: Any | None = None
        self._atomic_tx: SQLiteStateTransaction | None = None
        record = self._store.ensure(self._state_key, _empty_state())
        self._state = _state_from_mapping(record.payload)
        with self._lock, self._transaction():
            self._settle_locked(self._now())
            self._arm_timer_locked()

    def start_episode(self, episode: TeachingEpisode) -> bool:
        if not isinstance(episode, TeachingEpisode) or not episode.episode_id or not episode.pending_chunk:
            return False
        current = self._now()
        with self._lock, self._transaction():
            self._cancel_timer_locked()
            self._state = _empty_state()
            self._state["episode"] = episode.to_dict()
            if episode.status == "dwelling":
                self._set_dwell_locked(current)
            self._stage_locked()
            self._arm_timer_locked()
        return True

    def snapshot(self, now: float | None = None) -> dict[str, Any]:
        current = self._now(now)
        with self._lock, self._transaction():
            self._settle_locked(current)
            episode = self._episode_locked()
            claimed = bool(self._state["claim_owner"] and self._state["claim_until"] > current)
            due = bool(
                episode is not None
                and episode.status == "dwelling"
                and episode.pending_chunk is not None
                and not claimed
                and current >= self._state["dwell_due_at"]
            )
            return {
                "schema": PEDAGOGY_RUNTIME_SCHEMA,
                "version": self._state["version"],
                "active_episode": episode.to_dict() if episode is not None else None,
                "pending": bool(episode and episode.pending_chunk),
                "claimed": claimed,
                "due": due,
                "dwell_anchor_at": self._state["dwell_anchor_at"],
                "dwell_due_at": self._state["dwell_due_at"],
                "seconds_until_due": max(0.0, self._state["dwell_due_at"] - current)
                if episode is not None and episode.status == "dwelling" else 0.0,
            }

    def observe_user_turn(
        self,
        user_text: str,
        *,
        evidence: tuple[str, ...] = (),
        now: float | None = None,
    ) -> ControllerResult:
        current = self._now(now)
        with self._lock, self._transaction():
            self._settle_locked(current)
            episode = self._episode_locked()
            if episode is None:
                failed = TeachingEpisode("", "", "", (), 0.0, 0.0, status="failed")
                return ControllerResult(failed, select_next_action(failed, now=current), ())
            self._cancel_timer_locked()
            if episode.status == "dwelling":
                episode = replace(episode, status="observing")
            self._clear_dwell_locked(reason="user_turn")
            result = observe_user_turn(episode, user_text, evidence=tuple(evidence), now=current)
            self._set_episode_locked(result.episode)
            self._stage_locked()
            self._arm_timer_locked()
            return result

    def claim_due(
        self,
        *,
        worker_id: str,
        now: float | None = None,
        lease_seconds: float = CLAIM_LEASE_SECONDS,
    ) -> TeachingDirective | None:
        current = self._now(now)
        owner = _identifier(worker_id) or "anonymous"
        try:
            lease = max(0.25, min(120.0, float(lease_seconds)))
        except (TypeError, ValueError, OverflowError):
            lease = CLAIM_LEASE_SECONDS
        with self._lock, self._transaction():
            self._settle_locked(current)
            episode = self._episode_locked()
            if (
                episode is None
                or episode.status != "dwelling"
                or episode.pending_chunk is None
                or current < self._state["dwell_due_at"]
                or self._state["claim_until"] > current
            ):
                self._arm_timer_locked()
                return None
            action = select_next_action(episode, now=current)
            directive = action.directive
            if directive is None:
                return None
            self._state["claim_owner"] = owner
            self._state["claim_until"] = current + lease
            self._state["claim_token"] = _identifier(
                f"{episode.episode_id}:{episode.plan_revision}:{episode.pending_chunk.chunk_id}:{owner}"
            )
            self._stage_locked()
            self._arm_timer_locked()
            return directive

    def commit_receipt(self, receipt: TeachingReceipt, *, now: float | None = None) -> bool:
        if not isinstance(receipt, TeachingReceipt) or not receipt.successful:
            return False
        current = self._now(now)
        ledger_key = "pedagogy:" + ":".join((receipt.episode_id, str(receipt.plan_revision), receipt.chunk_id))
        claim = self._store.claim_idempotency(
            ledger_key, owner="pedagogy_runtime", lease_seconds=CLAIM_LEASE_SECONDS, now=current,
        )
        if claim.state != "acquired":
            return False
        committed = False
        try:
            with self._lock, self._transaction():
                self._settle_locked(current)
                episode = self._episode_locked()
                if episode is None:
                    return False
                receipt_episode = episode
                if episode.status == "dwelling":
                    # A dwell lease proves this exact chunk was selected for a
                    # public attempt. Convert only this transient projection to
                    # the controller's receipt-valid state; the stored episode
                    # remains dwelling until a successful receipt consumes it.
                    if not self._state["claim_owner"] or self._state["claim_until"] <= current:
                        return False
                    receipt_episode = replace(episode, status="ready")
                updated = note_public_commit(receipt_episode, receipt)
                if updated == receipt_episode:
                    return False
                self._set_episode_locked(updated)
                self._clear_dwell_locked(reason="public_commit")
                self._state["committed_turn_id"] = _identifier(receipt.turn_id)
                self._stage_locked()
                self._arm_timer_locked()
                committed = True
            return True
        finally:
            if committed:
                self._store.complete_idempotency(
                    ledger_key, owner="pedagogy_runtime", result=True, now=current,
                )
            else:
                self._store.abandon_idempotency(ledger_key, owner="pedagogy_runtime")

    def release_claim(
        self,
        reason: str,
        *,
        now: float | None = None,
        delay_seconds: float = 0.0,
    ) -> bool:
        """Release a live autonomous lease without consuming its teaching chunk."""
        current = self._now(now)
        try:
            delay = max(0.0, min(300.0, float(delay_seconds)))
        except (TypeError, ValueError, OverflowError):
            delay = 0.0
        with self._lock, self._transaction():
            self._settle_locked(current)
            episode = self._episode_locked()
            if (
                episode is None
                or episode.status != "dwelling"
                or episode.pending_chunk is None
                or not self._state["claim_owner"]
            ):
                return False
            self._state["claim_owner"] = ""
            self._state["claim_until"] = 0.0
            self._state["claim_token"] = ""
            self._state["dwell_due_at"] = max(self._state["dwell_due_at"], current + delay)
            self._state["cancel_reason"] = _identifier(reason)
            self._stage_locked()
            self._arm_timer_locked()
            return True

    def notify_audio_finished(self, timestamp: float, *, source_turn_id: str = "") -> None:
        current = self._now(timestamp)
        source_id = _identifier(source_turn_id)
        with self._lock, self._transaction():
            self._settle_locked(current)
            episode = self._episode_locked()
            if episode is None or (source_id and source_id != self._state["committed_turn_id"]):
                return
            updated = note_audio_finished(episode, now=current)
            if updated.status == "waiting_user" and updated.pending_chunk is not None:
                updated = replace(updated, status="dwelling")
                self._set_episode_locked(updated)
                self._set_dwell_locked(max(current, self._state["dwell_anchor_at"]))
                self._stage_locked()
                self._arm_timer_locked()

    def cancel_dwell(self, reason: str, *, now: float | None = None) -> None:
        current = self._now(now)
        with self._lock, self._transaction():
            self._settle_locked(current)
            episode = self._episode_locked()
            self._cancel_timer_locked()
            if episode is not None and episode.status == "dwelling":
                self._set_episode_locked(replace(episode, status="waiting_user"))
            self._clear_dwell_locked(reason=reason)
            self._stage_locked()

    def shutdown(self) -> None:
        with self._lock:
            self._cancel_timer_locked()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._store.transaction(self._state_key, self._state) as tx:
            self._atomic_tx = tx
            self._state = _state_from_mapping(tx.payload)
            try:
                yield
            finally:
                self._atomic_tx = None

    def _now(self, value: float | None = None) -> float:
        return _timestamp(self._clock() if value is None else value)

    def _episode_locked(self) -> TeachingEpisode | None:
        payload = self._state.get("episode")
        return normalize_episode(payload) if isinstance(payload, Mapping) else None

    def _set_episode_locked(self, episode: TeachingEpisode) -> None:
        self._state["episode"] = episode.to_dict()

    def _set_dwell_locked(self, anchor: float) -> None:
        anchor = _timestamp(anchor)
        self._state["dwell_anchor_at"] = anchor
        self._state["dwell_due_at"] = anchor + DWELL_SECONDS
        self._state["claim_owner"] = ""
        self._state["claim_until"] = 0.0
        self._state["claim_token"] = ""
        self._state["cancel_reason"] = ""

    def _clear_dwell_locked(self, *, reason: str) -> None:
        self._state["dwell_anchor_at"] = 0.0
        self._state["dwell_due_at"] = 0.0
        self._state["claim_owner"] = ""
        self._state["claim_until"] = 0.0
        self._state["claim_token"] = ""
        self._state["cancel_reason"] = _identifier(reason)

    def _settle_locked(self, now: float) -> None:
        episode = self._episode_locked()
        changed = False
        if episode is not None:
            updated = expire_if_needed(episode, now=now)
            if updated != episode:
                self._set_episode_locked(updated)
                self._clear_dwell_locked(reason="episode_expired")
                changed = True
        if self._state["claim_until"] and self._state["claim_until"] <= now:
            self._state["claim_owner"] = ""
            self._state["claim_until"] = 0.0
            self._state["claim_token"] = ""
            changed = True
        if changed:
            self._stage_locked()

    def _stage_locked(self) -> None:
        self._state["schema"] = PEDAGOGY_RUNTIME_SCHEMA
        self._state["version"] = min(1_000_000_000, int(self._state["version"]) + 1)
        if self._atomic_tx is not None:
            self._atomic_tx.stage(self._state)

    def _arm_timer_locked(self) -> None:
        self._cancel_timer_locked()
        if self._wake_callback is None:
            return
        episode = self._episode_locked()
        if episode is None or episode.status != "dwelling" or episode.pending_chunk is None:
            return
        now = self._now()
        target = self._state["claim_until"] if self._state["claim_until"] > now else self._state["dwell_due_at"]
        if target <= 0.0:
            return

        def wake() -> None:
            try:
                self._wake_callback("pedagogical_dwell_due")
            except TypeError:
                self._wake_callback(reason="pedagogical_dwell_due")
            except Exception:
                pass

        try:
            timer = self._timer_factory(max(0.05, target - now), wake)
            timer.daemon = True
            timer.start()
            self._timer = timer
        except Exception:
            self._timer = None

    def _cancel_timer_locked(self) -> None:
        timer, self._timer = self._timer, None
        cancel = getattr(timer, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                pass


def _host_feature_enabled(host: Any) -> bool:
    explicit = getattr(host, "pedagogical_controller_enabled", None)
    if explicit is not None:
        return bool(explicit)
    settings = getattr(getattr(host, "runtime_policy_settings", None), "pedagogy", None)
    if settings is not None and hasattr(settings, "enabled"):
        return bool(settings.enabled)
    return runtime_bool("pedagogy", "enabled", default=False)


def ensure_pedagogical_runtime(host: Any) -> PedagogicalRuntime | None:
    """Attach one runtime to an enabled host without creating an extra store."""
    if host is None or not _host_feature_enabled(host):
        return None
    for name in ("ai_pedagogical_runtime", "pedagogical_runtime"):
        existing = getattr(host, name, None)
        if isinstance(existing, PedagogicalRuntime):
            return existing
    store = next(
        (
            getattr(host, name, None)
            for name in ("ai_social_atomic_store", "pedagogical_atomic_store", "atomic_store")
            if isinstance(getattr(host, name, None), SQLiteAtomicStateStore)
        ),
        None,
    )
    if store is None:
        return None
    runtime = PedagogicalRuntime(
        store,
        clock=getattr(host, "_runtime_clock", None) if callable(getattr(host, "_runtime_clock", None)) else None,
        wake_callback=getattr(host, "_wake_autonomous_loop", None),
    )
    try:
        setattr(host, "ai_pedagogical_runtime", runtime)
        setattr(host, "pedagogical_runtime", runtime)
    except Exception:
        pass
    return runtime


__all__ = ["PEDAGOGY_RUNTIME_SCHEMA", "PedagogicalRuntime", "ensure_pedagogical_runtime"]
