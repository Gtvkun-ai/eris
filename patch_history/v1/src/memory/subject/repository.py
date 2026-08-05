# -*- coding: utf-8 -*-
"""SQLite source of truth for Subject Core events and projections."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .unit_of_work import UnitOfWork


class StaleRevisionError(RuntimeError):
    pass


class EventIntegrityError(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class StoredEvent:
    sequence: int
    event_id: str
    subject_id: str
    event_type: str
    created_at: float
    causal_refs: tuple[str, ...]
    payload: Mapping[str, Any]
    previous_hash: str
    payload_hash: str
    correlation_id: str


class SubjectRepository:
    """Single-writer friendly repository with deterministic replay primitives."""

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        *,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] | None = None,
        migration_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        self.database_path = str(database_path)
        self._clock = clock
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._configure(self._connection)
        self._migration_dir = Path(migration_dir) if migration_dir else Path(__file__).with_name("migrations")
        self.apply_migrations()

    @staticmethod
    def _configure(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 5000")

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def foreign_keys_enabled(self) -> bool:
        return bool(self._connection.execute("PRAGMA foreign_keys").fetchone()[0])

    def unit_of_work(self) -> UnitOfWork:
        return UnitOfWork(self._connection, self._lock)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def apply_migrations(self) -> None:
        files = sorted(self._migration_dir.glob("*.sql"))
        with self._lock:
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at REAL NOT NULL)"
            )
            for path in files:
                sql = path.read_text(encoding="utf-8")
                checksum = sha256_text(sql)
                existing = self._connection.execute(
                    "SELECT checksum FROM schema_migrations WHERE version = ?", (path.name,)
                ).fetchone()
                if existing:
                    if existing["checksum"] != checksum:
                        raise EventIntegrityError(f"migration checksum changed: {path.name}")
                    continue
                try:
                    self._connection.execute("BEGIN IMMEDIATE")
                    self._connection.executescript(sql)
                    self._connection.execute(
                        "INSERT INTO schema_migrations(version, checksum, applied_at) VALUES (?, ?, ?)",
                        (path.name, checksum, self._clock()),
                    )
                    self._connection.commit()
                except Exception:
                    self._connection.rollback()
                    raise

    def append_subject_event(
        self,
        *,
        subject_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        causal_refs: tuple[str, ...] = (),
        correlation_id: str = "",
        event_id: str | None = None,
        created_at: float | None = None,
    ) -> StoredEvent:
        event_id = event_id or self._id_factory()
        created_at = self._clock() if created_at is None else float(created_at)
        payload_json = canonical_json(payload)
        refs_json = canonical_json(list(causal_refs))
        with self.unit_of_work():
            existing = self._connection.execute(
                "SELECT * FROM subject_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            if existing:
                if existing["payload_json"] != payload_json or existing["event_type"] != event_type:
                    raise EventIntegrityError(f"event_id {event_id} already exists with different content")
                return self._row_to_event(existing)
            previous = self._connection.execute(
                "SELECT payload_hash FROM subject_events WHERE subject_id = ? ORDER BY sequence DESC LIMIT 1",
                (subject_id,),
            ).fetchone()
            previous_hash = previous["payload_hash"] if previous else "0" * 64
            envelope = canonical_json({
                "event_id": event_id,
                "subject_id": subject_id,
                "event_type": event_type,
                "created_at": created_at,
                "causal_refs": list(causal_refs),
                "payload": json.loads(payload_json),
                "previous_hash": previous_hash,
                "correlation_id": correlation_id,
            })
            payload_hash = sha256_text(envelope)
            cursor = self._connection.execute(
                """INSERT INTO subject_events(
                    event_id, subject_id, event_type, created_at, causal_refs_json,
                    payload_json, previous_hash, payload_hash, correlation_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event_id, subject_id, event_type, created_at, refs_json, payload_json, previous_hash, payload_hash, correlation_id),
            )
            sequence = int(cursor.lastrowid)
        return StoredEvent(sequence, event_id, subject_id, event_type, created_at, causal_refs, dict(payload), previous_hash, payload_hash, correlation_id)

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> StoredEvent:
        return StoredEvent(
            sequence=int(row["sequence"]),
            event_id=str(row["event_id"]),
            subject_id=str(row["subject_id"]),
            event_type=str(row["event_type"]),
            created_at=float(row["created_at"]),
            causal_refs=tuple(json.loads(row["causal_refs_json"])),
            payload=dict(json.loads(row["payload_json"])),
            previous_hash=str(row["previous_hash"]),
            payload_hash=str(row["payload_hash"]),
            correlation_id=str(row["correlation_id"]),
        )

    def events(self, *, subject_id: str, after_sequence: int = 0) -> tuple[StoredEvent, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM subject_events WHERE subject_id = ? AND sequence > ? ORDER BY sequence",
                (subject_id, after_sequence),
            ).fetchall()
        return tuple(self._row_to_event(row) for row in rows)

    def verify_event_chain(self, subject_id: str) -> bool:
        previous_hash = "0" * 64
        for event in self.events(subject_id=subject_id):
            if event.previous_hash != previous_hash:
                return False
            envelope = canonical_json({
                "event_id": event.event_id,
                "subject_id": event.subject_id,
                "event_type": event.event_type,
                "created_at": event.created_at,
                "causal_refs": list(event.causal_refs),
                "payload": dict(event.payload),
                "previous_hash": event.previous_hash,
                "correlation_id": event.correlation_id,
            })
            if sha256_text(envelope) != event.payload_hash:
                return False
            previous_hash = event.payload_hash
        return True

    def save_projection(
        self,
        *,
        subject_id: str,
        projection_type: str,
        projection_key: str,
        payload: Mapping[str, Any],
        expected_revision: int | None = None,
    ) -> int:
        payload_json = canonical_json(payload)
        payload_hash = sha256_text(payload_json)
        now = self._clock()
        with self.unit_of_work():
            row = self._connection.execute(
                """SELECT revision FROM projection_revisions
                   WHERE subject_id = ? AND projection_type = ? AND projection_key = ?""",
                (subject_id, projection_type, projection_key),
            ).fetchone()
            current_revision = int(row["revision"]) if row else 0
            if expected_revision is not None and expected_revision != current_revision:
                raise StaleRevisionError(
                    f"expected revision {expected_revision}, found {current_revision} for {projection_type}/{projection_key}"
                )
            new_revision = current_revision + 1
            self._connection.execute(
                """INSERT INTO projection_history(
                    subject_id, projection_type, projection_key, revision, payload_json, payload_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (subject_id, projection_type, projection_key, new_revision, payload_json, payload_hash, now),
            )
            self._connection.execute(
                """INSERT INTO projection_revisions(
                    subject_id, projection_type, projection_key, revision, payload_json, payload_hash, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(subject_id, projection_type, projection_key) DO UPDATE SET
                    revision=excluded.revision, payload_json=excluded.payload_json,
                    payload_hash=excluded.payload_hash, updated_at=excluded.updated_at""",
                (subject_id, projection_type, projection_key, new_revision, payload_json, payload_hash, now),
            )
        return new_revision

    def get_projection(self, *, subject_id: str, projection_type: str, projection_key: str) -> tuple[int, dict[str, Any]] | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT revision, payload_json FROM projection_revisions
                   WHERE subject_id = ? AND projection_type = ? AND projection_key = ?""",
                (subject_id, projection_type, projection_key),
            ).fetchone()
        if not row:
            return None
        return int(row["revision"]), dict(json.loads(row["payload_json"]))

    def record_idempotent(self, *, scope: str, idempotency_key: str, result: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        result_json = canonical_json(result)
        result_hash = sha256_text(result_json)
        with self.unit_of_work():
            row = self._connection.execute(
                "SELECT result_json FROM idempotency_keys WHERE scope = ? AND idempotency_key = ?",
                (scope, idempotency_key),
            ).fetchone()
            if row:
                return dict(json.loads(row["result_json"])), False
            self._connection.execute(
                "INSERT INTO idempotency_keys(scope, idempotency_key, result_json, result_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (scope, idempotency_key, result_json, result_hash, self._clock()),
            )
        return dict(result), True

    def append_authorship_event(self, *, authorship_id: str, action_id: str, decision_id: str, stage: str, payload: Mapping[str, Any]) -> None:
        payload_json = canonical_json(payload)
        with self.unit_of_work():
            self._connection.execute(
                """INSERT OR IGNORE INTO authorship_events(
                    authorship_id, action_id, decision_id, stage, payload_json, payload_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (authorship_id, action_id, decision_id, stage, payload_json, sha256_text(payload_json), self._clock()),
            )

    def append_world_outcome(self, *, outcome_id: str, action_id: str, decision_id: str, status: str, payload: Mapping[str, Any]) -> None:
        payload_json = canonical_json(payload)
        with self.unit_of_work():
            self._connection.execute(
                """INSERT OR IGNORE INTO world_outcomes(
                    outcome_id, action_id, decision_id, status, payload_json, payload_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (outcome_id, action_id, decision_id, status, payload_json, sha256_text(payload_json), self._clock()),
            )

    def projection_hash(self, *, subject_id: str) -> str:
        with self._lock:
            rows = self._connection.execute(
                """SELECT projection_type, projection_key, revision, payload_hash
                   FROM projection_revisions WHERE subject_id = ?
                   ORDER BY projection_type, projection_key""",
                (subject_id,),
            ).fetchall()
        return sha256_text(canonical_json([dict(row) for row in rows]))


class AsyncPersistenceActor:
    """A bounded single writer for async runtimes."""

    def __init__(self, repository: SubjectRepository, *, max_queue_size: int = 256) -> None:
        self.repository = repository
        self._queue: asyncio.Queue[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any], asyncio.Future[Any]] | None] = asyncio.Queue(maxsize=max_queue_size)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="subject-persistence-writer")

    async def stop(self) -> None:
        if self._task is None:
            return
        await self._queue.put(None)
        await self._task
        self._task = None

    async def call(self, method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if self._task is None:
            await self.start()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        await self._queue.put((method, args, kwargs, future))
        return await future

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            method, args, kwargs, future = item
            try:
                result = await asyncio.to_thread(method, *args, **kwargs)
            except Exception as exc:
                if not future.cancelled():
                    future.set_exception(exc)
            else:
                if not future.cancelled():
                    future.set_result(result)


__all__ = [
    "AsyncPersistenceActor", "EventIntegrityError", "StaleRevisionError", "StoredEvent",
    "SubjectRepository", "canonical_json", "sha256_text",
]
