"""SQLite-backed durable store for the learning kernel.

Schema: learning.sqlite3 (separate from eris.sqlite3 / eris_social.sqlite3).
One DB file per Eris home dir: <eris_home>/mentor/learning.sqlite3

Tables:
  learning_paths    – LearningPath definitions (JSON)
  knowledge_points  – KnowledgePoint definitions (JSON)
  mastery_records   – Per-KP mastery snapshots
  learning_evidence – Append-only evidence ledger
  review_items      – SRS queue (one row per KP per path)
  interactions      – PendingInteraction lifecycle

This module only handles persistence and simple queries.
All mastery computation lives in mastery.py / policy.py / scheduler.py.

Thread safety: one RLock per store instance; SQLite WAL mode.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from runtime.learning_core.belief_model import LearnerBeliefState
from runtime.learning_core.contracts import (
    KnowledgePoint,
    LearnerProfile,
    LearningEvidence,
    LearningPath,
    MasteryRecord,
    PendingInteraction,
    ReviewItem,
)


_SCHEMA_VERSION = 1
_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learning_paths (
    path_id     TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    goal        TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'user',
    payload     TEXT NOT NULL,           -- full JSON
    created_at  REAL NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS knowledge_points (
    kp_id       TEXT PRIMARY KEY,
    path_id     TEXT NOT NULL,
    title       TEXT NOT NULL,
    kp_type     TEXT NOT NULL DEFAULT 'concept',
    payload     TEXT NOT NULL,
    FOREIGN KEY (path_id) REFERENCES learning_paths(path_id)
);

CREATE TABLE IF NOT EXISTS mastery_records (
    kp_id              TEXT PRIMARY KEY,
    mastery            REAL NOT NULL DEFAULT 0,
    confidence         REAL NOT NULL DEFAULT 0,
    stage              TEXT NOT NULL DEFAULT 'unknown',
    attempt_count      INTEGER NOT NULL DEFAULT 0,
    correct_count      INTEGER NOT NULL DEFAULT 0,
    last_evidence_at   REAL NOT NULL DEFAULT 0,
    next_review_at     REAL NOT NULL DEFAULT 0,
    retrievability     REAL NOT NULL DEFAULT 1,
    error_codes        TEXT NOT NULL DEFAULT '[]',
    updated_at         REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS learning_evidence (
    evidence_id     TEXT PRIMARY KEY,
    kp_id           TEXT NOT NULL,
    evidence_type   TEXT NOT NULL,
    strength        REAL NOT NULL DEFAULT 0.5,
    correct         INTEGER NOT NULL DEFAULT 1,
    interaction_id  TEXT NOT NULL DEFAULT '',
    turn_id         TEXT NOT NULL DEFAULT '',
    recorded_at     REAL NOT NULL,
    error_code      TEXT NOT NULL DEFAULT '',
    metadata        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_evidence_kp ON learning_evidence(kp_id, recorded_at);

-- BKT shadow state: KHÔNG thay mastery_records khi chưa được hiệu chỉnh.
CREATE TABLE IF NOT EXISTS learner_beliefs (
    kp_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    evidence_seq INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS review_items (
    kp_id           TEXT PRIMARY KEY,
    due_at          REAL NOT NULL,
    forgetting_risk REAL NOT NULL DEFAULT 0,
    interval_days   REAL NOT NULL DEFAULT 1,
    ease_factor     REAL NOT NULL DEFAULT 2.5
);

CREATE TABLE IF NOT EXISTS interactions (
    interaction_id  TEXT PRIMARY KEY,
    path_id         TEXT NOT NULL,
    kp_id           TEXT NOT NULL,
    interaction_type TEXT NOT NULL,
    question_text   TEXT NOT NULL,
    expected_answer TEXT NOT NULL,
    options         TEXT NOT NULL DEFAULT '[]',
    correct_index   INTEGER NOT NULL DEFAULT -1,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      REAL NOT NULL DEFAULT 0,
    expires_at      REAL NOT NULL DEFAULT 0,
    answered_at     REAL NOT NULL DEFAULT 0,
    turn_id         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_interaction_kp ON interactions(path_id, kp_id, status);
"""


class LearningStore:
    """Thread-safe SQLite store for the learning kernel."""

    def __init__(self, path: Path | None = None) -> None:
        from runtime.workspace_manager import default_eris_home
        self._path = path or (default_eris_home() / "mentor" / "learning.sqlite3")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._connect()

    # ------------------------------------------------------------------
    # Connection / schema
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        conn = sqlite3.connect(str(self._path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(_DDL)
        conn.commit()
        self._conn = conn

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            self._connect()
        assert self._conn is not None
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    # ------------------------------------------------------------------
    # Small runtime metadata
    # ------------------------------------------------------------------

    def set_meta(self, key: str, value: Any) -> None:
        """Persist một JSON value nhỏ trong ``schema_meta``.

        Dùng cho con trỏ runtime như active_path/active_kp. Không dùng bảng này
        để lưu evidence hoặc mastery; hai loại dữ liệu đó có bảng authoritative riêng.
        """
        meta_key = str(key or "").strip()[:120]
        if not meta_key:
            raise ValueError("meta key is required")
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._db().execute(
                """
                INSERT INTO schema_meta(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (meta_key, payload),
            )
            self._db().commit()

    def get_meta(self, key: str, default: Any = None) -> Any:
        meta_key = str(key or "").strip()[:120]
        if not meta_key:
            return default
        with self._lock:
            row = self._db().execute(
                "SELECT value FROM schema_meta WHERE key = ?", (meta_key,)
            ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return default

    # ------------------------------------------------------------------
    # LearningPath CRUD
    # ------------------------------------------------------------------

    def upsert_path(self, path: LearningPath, *, now: float | None = None) -> None:
        ts = float(now if now is not None else time.time())
        payload = json.dumps(path.to_dict(), ensure_ascii=False)
        with self._lock:
            db = self._db()
            db.execute(
                """
                INSERT INTO learning_paths (path_id, title, goal, source, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path_id) DO UPDATE SET
                    title=excluded.title, goal=excluded.goal, source=excluded.source,
                    payload=excluded.payload, updated_at=excluded.updated_at
                """,
                (path.path_id, path.title, path.goal, path.source, payload, ts, ts),
            )
            for kp in path.knowledge_points:
                kp_payload = json.dumps(kp.to_dict(), ensure_ascii=False)
                db.execute(
                    """
                    INSERT INTO knowledge_points (kp_id, path_id, title, kp_type, payload)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(kp_id) DO UPDATE SET
                        title=excluded.title, kp_type=excluded.kp_type, payload=excluded.payload
                    """,
                    (kp.kp_id, path.path_id, kp.title, kp.kp_type, kp_payload),
                )
            db.commit()

    def load_path(self, path_id: str) -> LearningPath | None:
        with self._lock:
            row = self._db().execute(
                "SELECT payload FROM learning_paths WHERE path_id = ?", (path_id,)
            ).fetchone()
        if row is None:
            return None
        try:
            d = json.loads(row["payload"])
            return LearningPath(
                path_id=d["path_id"],
                title=d["title"],
                goal=d["goal"],
                knowledge_points=tuple(KnowledgePoint.from_mapping(kp) for kp in d.get("knowledge_points", [])),
                source=d.get("source", "user"),
            )
        except Exception:
            return None

    def list_path_ids(self) -> list[str]:
        with self._lock:
            rows = self._db().execute("SELECT path_id FROM learning_paths ORDER BY updated_at DESC").fetchall()
        return [r["path_id"] for r in rows]

    # ------------------------------------------------------------------
    # MasteryRecord CRUD
    # ------------------------------------------------------------------

    def load_mastery(self, kp_id: str) -> MasteryRecord:
        with self._lock:
            row = self._db().execute(
                "SELECT * FROM mastery_records WHERE kp_id = ?", (kp_id,)
            ).fetchone()
        if row is None:
            return MasteryRecord.blank(kp_id)
        return self._row_to_mastery(row)

    def load_mastery_batch(self, kp_ids: Sequence[str]) -> dict[str, MasteryRecord]:
        if not kp_ids:
            return {}
        placeholders = ",".join("?" * len(kp_ids))
        with self._lock:
            rows = self._db().execute(
                f"SELECT * FROM mastery_records WHERE kp_id IN ({placeholders})", list(kp_ids)
            ).fetchall()
        result = {kp_id: MasteryRecord.blank(kp_id) for kp_id in kp_ids}
        for row in rows:
            result[row["kp_id"]] = self._row_to_mastery(row)
        return result

    def save_mastery(self, record: MasteryRecord, *, now: float | None = None) -> None:
        ts = float(now if now is not None else time.time())
        with self._lock:
            self._db().execute(
                """
                INSERT INTO mastery_records
                    (kp_id, mastery, confidence, stage, attempt_count, correct_count,
                     last_evidence_at, next_review_at, retrievability, error_codes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(kp_id) DO UPDATE SET
                    mastery=excluded.mastery, confidence=excluded.confidence,
                    stage=excluded.stage, attempt_count=excluded.attempt_count,
                    correct_count=excluded.correct_count,
                    last_evidence_at=excluded.last_evidence_at,
                    next_review_at=excluded.next_review_at,
                    retrievability=excluded.retrievability,
                    error_codes=excluded.error_codes,
                    updated_at=excluded.updated_at
                """,
                (
                    record.kp_id, record.mastery, record.confidence, record.stage,
                    record.attempt_count, record.correct_count,
                    record.last_evidence_at, record.next_review_at, record.retrievability,
                    json.dumps(list(record.error_codes)),
                    ts,
                ),
            )
            self._db().commit()

    @staticmethod
    def _row_to_mastery(row: sqlite3.Row) -> MasteryRecord:
        try:
            error_codes = tuple(json.loads(row["error_codes"]) or [])
        except Exception:
            error_codes = ()
        return MasteryRecord(
            kp_id=row["kp_id"],
            mastery=float(row["mastery"]),
            confidence=float(row["confidence"]),
            stage=row["stage"],
            attempt_count=int(row["attempt_count"]),
            correct_count=int(row["correct_count"]),
            last_evidence_at=float(row["last_evidence_at"]),
            next_review_at=float(row["next_review_at"]),
            retrievability=float(row["retrievability"]),
            error_codes=error_codes,
        )

    # ------------------------------------------------------------------
    # LearningEvidence (append-only ledger)
    # ------------------------------------------------------------------

    def append_evidence(self, evidence: LearningEvidence) -> bool:
        """Idempotent insert; returns False if evidence_id already exists."""
        with self._lock:
            existing = self._db().execute(
                "SELECT 1 FROM learning_evidence WHERE evidence_id = ?", (evidence.evidence_id,)
            ).fetchone()
            if existing:
                return False
            self._db().execute(
                """
                INSERT INTO learning_evidence
                    (evidence_id, kp_id, evidence_type, strength, correct,
                     interaction_id, turn_id, recorded_at, error_code, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.evidence_id, evidence.kp_id, evidence.evidence_type,
                    evidence.strength, int(evidence.correct),
                    evidence.interaction_id, evidence.turn_id, evidence.recorded_at,
                    evidence.error_code, evidence.metadata,
                ),
            )
            self._db().commit()
        return True

    def load_belief(self, kp_id: str) -> LearnerBeliefState:
        """Snapshot chỉ-đọc: xác suất BKT *chưa hiệu chỉnh*, không phải mastery chính thức."""
        with self._lock:
            row = self._db().execute(
                "SELECT payload FROM learner_beliefs WHERE kp_id=?", (kp_id,)
            ).fetchone()
        if row is None:
            return LearnerBeliefState(kp_id=kp_id)
        try:
            return LearnerBeliefState.from_mapping(json.loads(row["payload"]))
        except (TypeError, ValueError, KeyError):
            return LearnerBeliefState(kp_id=kp_id)

    def commit_evidence_bundle(
        self,
        evidence: LearningEvidence,
        project: Callable[[list[LearningEvidence], ReviewItem | None],
                          tuple[MasteryRecord, ReviewItem, LearnerBeliefState]],
        *,
        now: float,
    ) -> bool:
        """Một transaction giữ evidence, mastery, lịch ôn, BKT cùng một version.

        Transaction BEGIN IMMEDIATE giữ serialization xuyên nhiều LearningService
        dùng chung tệp SQLite. Callback chỉ tính toán thuần, không gọi LLM/I/O.
        Retry trùng evidence_id sẽ không tăng trạng thái thêm lần nữa.
        """
        with self._lock:
            db = self._db()
            db.execute("BEGIN IMMEDIATE")
            try:
                if db.execute(
                    "SELECT 1 FROM learning_evidence WHERE evidence_id=?",
                    (evidence.evidence_id,),
                ).fetchone():
                    db.rollback()
                    return False
                db.execute(
                    """INSERT INTO learning_evidence
                        (evidence_id, kp_id, evidence_type, strength, correct,
                         interaction_id, turn_id, recorded_at, error_code, metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (evidence.evidence_id, evidence.kp_id, evidence.evidence_type,
                     evidence.strength, int(evidence.correct), evidence.interaction_id,
                     evidence.turn_id, evidence.recorded_at, evidence.error_code, evidence.metadata),
                )
                rows = db.execute(
                    "SELECT * FROM learning_evidence WHERE kp_id=? "
                    "ORDER BY recorded_at ASC, evidence_id ASC", (evidence.kp_id,)
                ).fetchall()
                ledger = [self._row_to_evidence(row) for row in rows]
                old = db.execute(
                    "SELECT * FROM review_items WHERE kp_id=?", (evidence.kp_id,)
                ).fetchone()
                current = ReviewItem(
                    kp_id=old["kp_id"], due_at=float(old["due_at"]),
                    forgetting_risk=float(old["forgetting_risk"]),
                    interval_days=float(old["interval_days"]),
                    ease_factor=float(old["ease_factor"]),
                ) if old else None
                mastery, review, belief = project(ledger, current)
                if not (mastery.kp_id == review.kp_id == belief.kp_id == evidence.kp_id):
                    raise ValueError("Projection kp_id mismatch")
                db.execute(
                    """INSERT INTO mastery_records
                        (kp_id, mastery, confidence, stage, attempt_count, correct_count,
                         last_evidence_at, next_review_at, retrievability, error_codes, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(kp_id) DO UPDATE SET
                         mastery=excluded.mastery, confidence=excluded.confidence,
                         stage=excluded.stage, attempt_count=excluded.attempt_count,
                         correct_count=excluded.correct_count,
                         last_evidence_at=excluded.last_evidence_at,
                         next_review_at=excluded.next_review_at,
                         retrievability=excluded.retrievability,
                         error_codes=excluded.error_codes, updated_at=excluded.updated_at""",
                    (mastery.kp_id, mastery.mastery, mastery.confidence, mastery.stage,
                     mastery.attempt_count, mastery.correct_count, mastery.last_evidence_at,
                     mastery.next_review_at, mastery.retrievability,
                     json.dumps(list(mastery.error_codes)), now),
                )
                db.execute(
                    """INSERT INTO review_items(kp_id, due_at, forgetting_risk, interval_days, ease_factor)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(kp_id) DO UPDATE SET
                         due_at=excluded.due_at, forgetting_risk=excluded.forgetting_risk,
                         interval_days=excluded.interval_days, ease_factor=excluded.ease_factor""",
                    (review.kp_id, review.due_at, review.forgetting_risk,
                     review.interval_days, review.ease_factor),
                )
                db.execute(
                    """INSERT INTO learner_beliefs(kp_id, payload, evidence_seq, updated_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(kp_id) DO UPDATE SET payload=excluded.payload,
                        evidence_seq=excluded.evidence_seq, updated_at=excluded.updated_at""",
                    (belief.kp_id, json.dumps(belief.to_dict(), ensure_ascii=False),
                     belief.evidence_seq, now),
                )
                db.commit()
                return True
            except BaseException:
                db.rollback()
                raise

    def repeated_error_patterns(self, kp_id: str, *, min_independent: int = 2, limit: int = 4) -> list[dict[str, Any]]:
        """Thống kê lỗi tái diễn qua các câu hỏi; không xem nhãn lỗi là chẩn đoán.

        Nhóm theo interaction/turn để 3 retries hay 3 evidence cùng câu hỏi
        KHÔNG biến thành 3 lần người học mắc sai lầm độc lập.
        """
        with self._lock:
            rows = self._db().execute(
                """SELECT error_code,
                    COUNT(DISTINCT COALESCE(NULLIF(interaction_id, ''),
                                            NULLIF(turn_id, ''), evidence_id)) AS independent_count
                   FROM learning_evidence
                   WHERE kp_id = ? AND correct = 0 AND error_code <> ''
                   GROUP BY error_code
                   HAVING independent_count >= ?
                   ORDER BY independent_count DESC, error_code ASC LIMIT ?""",
                (kp_id, max(2, min(10, int(min_independent))), max(1, min(8, int(limit)))),
            ).fetchall()
        return [{"error_code": str(row["error_code"])[:80],
                 "independent_count": int(row["independent_count"]),
                 "status": "repeat_observed_not_diagnosis"} for row in rows]

    def load_evidence(self, kp_id: str, *, limit: int = 100) -> list[LearningEvidence]:
        with self._lock:
            rows = self._db().execute(
                "SELECT * FROM learning_evidence WHERE kp_id = ? ORDER BY recorded_at ASC LIMIT ?",
                (kp_id, limit),
            ).fetchall()
        return [self._row_to_evidence(r) for r in rows]

    @staticmethod
    def _row_to_evidence(row: sqlite3.Row) -> LearningEvidence:
        return LearningEvidence(
            evidence_id=row["evidence_id"],
            kp_id=row["kp_id"],
            evidence_type=row["evidence_type"],
            strength=float(row["strength"]),
            correct=bool(row["correct"]),
            interaction_id=row["interaction_id"],
            turn_id=row["turn_id"],
            recorded_at=float(row["recorded_at"]),
            error_code=row["error_code"],
            metadata=row["metadata"],
        )

    # ------------------------------------------------------------------
    # ReviewItems (SRS queue)
    # ------------------------------------------------------------------

    def upsert_review_item(self, item: ReviewItem) -> None:
        with self._lock:
            self._db().execute(
                """
                INSERT INTO review_items (kp_id, due_at, forgetting_risk, interval_days, ease_factor)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(kp_id) DO UPDATE SET
                    due_at=excluded.due_at, forgetting_risk=excluded.forgetting_risk,
                    interval_days=excluded.interval_days, ease_factor=excluded.ease_factor
                """,
                (item.kp_id, item.due_at, item.forgetting_risk, item.interval_days, item.ease_factor),
            )
            self._db().commit()

    def load_review_items(self, kp_ids: Sequence[str] | None = None) -> list[ReviewItem]:
        with self._lock:
            if kp_ids is None:
                rows = self._db().execute("SELECT * FROM review_items").fetchall()
            else:
                if not kp_ids:
                    return []
                placeholders = ",".join("?" * len(kp_ids))
                rows = self._db().execute(
                    f"SELECT * FROM review_items WHERE kp_id IN ({placeholders})", list(kp_ids)
                ).fetchall()
        return [
            ReviewItem(
                kp_id=r["kp_id"],
                due_at=float(r["due_at"]),
                forgetting_risk=float(r["forgetting_risk"]),
                interval_days=float(r["interval_days"]),
                ease_factor=float(r["ease_factor"]),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # PendingInteraction persistence
    # ------------------------------------------------------------------

    def upsert_interaction(self, interaction: PendingInteraction) -> bool:
        """Idempotent insert. Returns False if interaction_id already exists."""
        with self._lock:
            existing = self._db().execute(
                "SELECT status FROM interactions WHERE interaction_id = ?",
                (interaction.interaction_id,),
            ).fetchone()
            if existing is not None:
                return False
            # Cancel prior pending interaction for same (path, kp)
            self._db().execute(
                """
                UPDATE interactions SET status = 'cancelled'
                WHERE path_id = ? AND kp_id = ? AND status = 'pending'
                """,
                (interaction.path_id, interaction.kp_id),
            )
            self._db().execute(
                """
                INSERT INTO interactions
                    (interaction_id, path_id, kp_id, interaction_type, question_text,
                     expected_answer, options, correct_index, status,
                     created_at, expires_at, answered_at, turn_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    interaction.interaction_id, interaction.path_id, interaction.kp_id,
                    interaction.interaction_type, interaction.question_text,
                    interaction.expected_answer,
                    json.dumps(list(interaction.options)),
                    interaction.correct_index,
                    interaction.status,
                    interaction.created_at, interaction.expires_at,
                    interaction.answered_at, interaction.turn_id,
                ),
            )
            self._db().commit()
        return True

    def resolve_interaction(
        self, interaction_id: str, *, status: str, turn_id: str = "", answered_at: float = 0.0
    ) -> bool:
        with self._lock:
            res = self._db().execute(
                """
                UPDATE interactions SET status = ?, turn_id = ?, answered_at = ?
                WHERE interaction_id = ? AND status = 'pending'
                """,
                (status, turn_id[:120], answered_at, interaction_id),
            )
            self._db().commit()
        return res.rowcount > 0

    def load_pending_interaction(self, path_id: str, kp_id: str) -> PendingInteraction | None:
        with self._lock:
            row = self._db().execute(
                """
                SELECT * FROM interactions
                WHERE path_id = ? AND kp_id = ? AND status = 'pending'
                ORDER BY created_at DESC LIMIT 1
                """,
                (path_id, kp_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_interaction(row)

    def load_interaction(self, interaction_id: str) -> PendingInteraction | None:
        with self._lock:
            row = self._db().execute(
                "SELECT * FROM interactions WHERE interaction_id = ?", (interaction_id,)
            ).fetchone()
        return self._row_to_interaction(row) if row else None

    @staticmethod
    def _row_to_interaction(row: sqlite3.Row) -> PendingInteraction:
        try:
            options = tuple(json.loads(row["options"]) or [])
        except Exception:
            options = ()
        return PendingInteraction(
            interaction_id=row["interaction_id"],
            path_id=row["path_id"],
            kp_id=row["kp_id"],
            interaction_type=row["interaction_type"],
            question_text=row["question_text"],
            expected_answer=row["expected_answer"],
            options=options,
            correct_index=int(row["correct_index"]),
            status=row["status"],
            created_at=float(row["created_at"]),
            expires_at=float(row["expires_at"]),
            answered_at=float(row["answered_at"]),
            turn_id=row["turn_id"],
        )


__all__ = ["LearningStore"]
