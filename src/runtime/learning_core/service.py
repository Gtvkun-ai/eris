"""LearningService: orchestrates the learning kernel for Eris.

This is the single entry-point that Eris runtime components call.
It owns:
- Loading/storing paths, mastery, evidence, reviews, interactions
- Recomputing mastery after each evidence commit
- Updating the SRS queue
- Providing the next TutorStep for the orchestrator

It does NOT:
- Generate LLM text (teach_chunk, quiz questions, Feynman prompts)
- Call TTS or public writer
- Access Eris companion/voice/autonomy subsystems directly

Those are in engineering_mentor.py / pedagogical_runtime.py; they call this
service and consume TutorStep to build directives.

Thread safety: one RLock per service instance.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Sequence

from runtime.learning_core.contracts import (
    KnowledgePoint,
    LearnerProfile,
    LearningEvidence,
    LearningPath,
    MasteryRecord,
    PendingInteraction,
    ReviewItem,
)
from runtime.learning_core.grading import GradingResult, grade_choice, quality_from_evidence_type
from runtime.learning_core.mastery import (
    DEFAULT_POLICY,
    MasteryPolicy,
    compute_mastery,
    gate_passed,
)
from runtime.learning_core.pending import PendingInteractionLedger, ResolutionResult
from runtime.learning_core.policy import (
    DEFAULT_NAV_POLICY,
    NavigationPolicy,
    TutorStep,
    next_step,
    _KPSession,
)
from runtime.learning_core.scheduler import (
    DEFAULT_SCHEDULER,
    ReviewScheduler,
    compute_retrievability,
    due_items,
    next_review_item,
)
from runtime.learning_core.store import LearningStore


class LearningService:
    """Orchestrates the full learning kernel for one Eris instance."""

    def __init__(
        self,
        store: LearningStore | None = None,
        *,
        mastery_policy: MasteryPolicy = DEFAULT_POLICY,
        nav_policy: NavigationPolicy = DEFAULT_NAV_POLICY,
        scheduler: ReviewScheduler = DEFAULT_SCHEDULER,
        logger: Any = None,
    ) -> None:
        self._store = store or LearningStore()
        self._mastery_policy = mastery_policy
        self._nav_policy = nav_policy
        self._scheduler = scheduler
        self._logger = logger
        self._lock = threading.RLock()
        # In-memory session state (ephemeral)
        self._ledger = PendingInteractionLedger()
        self._session_counts: dict[str, _KPSession] = {}   # kp_id → _KPSession
        self._active_path_id: str = ""
        self._active_kp_id: str = ""
        # Active learning pointer cần sống qua restart để TutorExecutive có thể
        # resume đúng bài đang dạy. Mastery/evidence vẫn được load từ bảng riêng.
        self._restore_runtime_state()

    # ------------------------------------------------------------------
    # Path management
    # ------------------------------------------------------------------

    def register_path(self, path: LearningPath, *, now: float | None = None) -> None:
        """Register or update a LearningPath. Does not change active path."""
        with self._lock:
            self._store.upsert_path(path, now=now)

    def activate_path(self, path_id: str) -> bool:
        """Set the active path. Returns False if path not found."""
        with self._lock:
            path = self._store.load_path(path_id)
            if path is None:
                return False
            self._active_path_id = path_id
            self._active_kp_id = path.knowledge_points[0].kp_id if path.knowledge_points else ""
            self._session_counts = {}
            self._persist_runtime_state_locked()
            return True

    def active_path(self) -> LearningPath | None:
        with self._lock:
            if not self._active_path_id:
                return None
            return self._store.load_path(self._active_path_id)

    # ------------------------------------------------------------------
    # Next tutor step
    # ------------------------------------------------------------------

    def next_tutor_step(
        self,
        *,
        learner: LearnerProfile | None = None,
        now: float | None = None,
    ) -> TutorStep | None:
        """Return the next step for the active path, or None if no path is active."""
        ts = float(now if now is not None else time.time())
        with self._lock:
            path = self._store.load_path(self._active_path_id) if self._active_path_id else None
            if path is None:
                return None

            # Load mastery for all KPs in path
            records = self._store.load_mastery_batch(list(path.kp_ids))

            # Load overdue reviews (scoped to this path's KPs)
            review_items = self._store.load_review_items(list(path.kp_ids))
            overdue = due_items(review_items, now=ts)

            return next_step(
                path,
                self._active_kp_id,
                records,
                due_reviews=overdue,
                session_counts=dict(self._session_counts),
                learner=learner,
                policy=self._nav_policy,
                now=ts,
            )

    # ------------------------------------------------------------------
    # Interaction lifecycle (server-side question management)
    # ------------------------------------------------------------------

    def pose_interaction(
        self,
        kp_id: str,
        interaction_type: str,
        question_text: str,
        expected_answer: str,
        *,
        options: tuple[str, ...] = (),
        correct_index: int = -1,
        expires_in_seconds: float = 300.0,
        now: float | None = None,
    ) -> PendingInteraction:
        """Create and persist a new pending interaction."""
        ts = float(now if now is not None else time.time())
        interaction_id = f"ix:{kp_id}:{uuid.uuid4().hex[:12]}"
        interaction = PendingInteraction(
            interaction_id=interaction_id,
            path_id=self._active_path_id,
            kp_id=kp_id,
            interaction_type=interaction_type,
            question_text=question_text,
            expected_answer=expected_answer,
            options=options,
            correct_index=correct_index,
            created_at=ts,
            expires_at=ts + max(30.0, float(expires_in_seconds)),
        )
        with self._lock:
            self._ledger.add(interaction)
            self._store.upsert_interaction(interaction)
        return interaction

    def resolve_interaction(
        self,
        interaction_id: str,
        user_answer: str | int,
        *,
        turn_id: str = "",
        now: float | None = None,
    ) -> ResolutionResult | None:
        """Grade a pending interaction. Commits evidence if deterministic."""
        ts = float(now if now is not None else time.time())
        with self._lock:
            result = self._ledger.resolve(interaction_id, user_answer, turn_id=turn_id, now=ts)
            if result is None:
                # Try rehydrating from DB (e.g. after restart)
                db_interaction = self._store.load_interaction(interaction_id)
                if db_interaction and db_interaction.status == "pending":
                    self._ledger.add(db_interaction)
                    result = self._ledger.resolve(interaction_id, user_answer, turn_id=turn_id, now=ts)
            if result is None:
                return None

            # Persist status update
            self._store.resolve_interaction(
                interaction_id,
                status=result.interaction.status,
                turn_id=turn_id,
                answered_at=ts,
            )

            # Commit evidence for deterministically graded items
            if result.interaction.interaction_type in {"multiple_choice", "true_false"}:
                evidence_id = f"ev:{interaction_id}:{turn_id[:20]}:{int(ts)}"
                evidence = LearningEvidence(
                    evidence_id=evidence_id,
                    kp_id=result.interaction.kp_id,
                    evidence_type=result.evidence_type,
                    strength=1.0 if result.grading.correct else 0.0,
                    correct=result.grading.correct,
                    interaction_id=interaction_id,
                    turn_id=turn_id,
                    recorded_at=ts,
                    error_code=result.grading.error_code,
                )
                self._commit_evidence_locked(evidence, ts)
                # Update session counter
                kp_id = result.interaction.kp_id
                session = self._session_counts.get(kp_id, _KPSession())
                self._session_counts[kp_id] = session.assessed(result.grading.correct)

        return result

    # ------------------------------------------------------------------
    # Evidence commitment (for semantic/qualitative assessments)
    # ------------------------------------------------------------------

    def commit_evidence(
        self,
        kp_id: str,
        evidence_type: str,
        *,
        strength: float = 0.5,
        correct: bool = True,
        interaction_id: str = "",
        turn_id: str = "",
        error_code: str = "",
        now: float | None = None,
    ) -> LearningEvidence | None:
        """Commit one piece of evidence from the caller (semantic assessor, etc.)."""
        ts = float(now if now is not None else time.time())
        evidence_id = f"ev:{kp_id}:{evidence_type}:{turn_id[:20]}:{int(ts)}"
        evidence = LearningEvidence(
            evidence_id=evidence_id,
            kp_id=kp_id,
            evidence_type=evidence_type,
            strength=strength,
            correct=correct,
            interaction_id=interaction_id,
            turn_id=turn_id,
            recorded_at=ts,
            error_code=error_code,
        )
        with self._lock:
            if self._commit_evidence_locked(evidence, ts):
                # Update session counter for teaching tracking
                if evidence_type in {"feynman_pass", "feynman_fail"}:
                    session = self._session_counts.get(kp_id, _KPSession())
                    if evidence_type == "feynman_pass":
                        session = session.feynman_passed().assessed(True)
                    else:
                        session = session.assessed(False)
                    self._session_counts[kp_id] = session
                return evidence
        return None

    def note_taught(self, kp_id: str) -> None:
        """Mark that one teach chunk was delivered for a KP (session counter)."""
        with self._lock:
            session = self._session_counts.get(kp_id, _KPSession())
            self._session_counts[kp_id] = session.taught()

    def advance_kp(self, kp_id: str) -> None:
        """Move active KP pointer forward after advance/complete step."""
        with self._lock:
            self._active_kp_id = kp_id
            self._persist_runtime_state_locked()

    # ------------------------------------------------------------------
    # Durable runtime pointer helpers
    # ------------------------------------------------------------------

    def _restore_runtime_state(self) -> None:
        """Restore active path/KP pointer; fail closed nếu metadata đã stale."""
        try:
            raw = self._store.get_meta("learning_runtime_v1", {})
        except Exception:
            raw = {}
        if not isinstance(raw, dict):
            return
        path_id = str(raw.get("active_path_id", "") or "").strip()[:120]
        kp_id = str(raw.get("active_kp_id", "") or "").strip()[:120]
        if not path_id:
            return
        try:
            path = self._store.load_path(path_id)
        except Exception:
            path = None
        if path is None:
            return
        valid_kps = set(path.kp_ids)
        self._active_path_id = path_id
        self._active_kp_id = kp_id if kp_id in valid_kps else (path.kp_ids[0] if path.kp_ids else "")

    def _persist_runtime_state_locked(self) -> None:
        try:
            self._store.set_meta(
                "learning_runtime_v1",
                {
                    "active_path_id": self._active_path_id,
                    "active_kp_id": self._active_kp_id,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger = self._logger
            if logger is not None:
                try:
                    logger.debug("[learning] runtime pointer persist degraded: %s", exc)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Mastery snapshot
    # ------------------------------------------------------------------

    def mastery_snapshot(self, kp_ids: Sequence[str] | None = None) -> dict[str, dict]:
        """Return a dict kp_id → MasteryRecord.to_dict() for display/debug."""
        with self._lock:
            path = self._store.load_path(self._active_path_id) if self._active_path_id else None
            ids = list(kp_ids) if kp_ids is not None else (list(path.kp_ids) if path else [])
            records = self._store.load_mastery_batch(ids)
        return {kp_id: rec.to_dict() for kp_id, rec in records.items()}

    def get_mastery(self, kp_id: str) -> MasteryRecord:
        with self._lock:
            return self._store.load_mastery(kp_id)

    # ------------------------------------------------------------------
    # Review items
    # ------------------------------------------------------------------

    def due_review_items(self, *, now: float | None = None) -> list[ReviewItem]:
        ts = float(now if now is not None else time.time())
        with self._lock:
            path = self._store.load_path(self._active_path_id) if self._active_path_id else None
            kp_ids = list(path.kp_ids) if path else None
            items = self._store.load_review_items(kp_ids)
        return due_items(items, now=ts)

    def review_snapshot(self, kp_ids: Sequence[str] | None = None) -> dict[str, dict]:
        """Projection chỉ-đọc cho adapter/debug; scheduler/DB vẫn thuộc service."""
        with self._lock:
            items = self._store.load_review_items(list(kp_ids) if kp_ids is not None else None)
        return {item.kp_id: item.to_dict() for item in items}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _commit_evidence_locked(self, evidence: LearningEvidence, ts: float) -> bool:
        """Append evidence, recompute mastery, update SRS. Caller holds _lock."""
        if not self._store.append_evidence(evidence):
            return False   # duplicate

        kp_id = evidence.kp_id
        # Recompute mastery from all evidence for this KP
        all_evidence = self._store.load_evidence(kp_id)
        new_record = compute_mastery(kp_id, all_evidence, now=ts, policy=self._mastery_policy)
        self._store.save_mastery(new_record, now=ts)

        # Update SRS queue
        quality = quality_from_evidence_type(evidence.evidence_type, evidence.correct)
        existing_reviews = self._store.load_review_items([kp_id])
        current_item = existing_reviews[0] if existing_reviews else None
        new_review = next_review_item(new_record, current_item, quality=quality, now=ts, scheduler=self._scheduler)
        self._store.upsert_review_item(new_review)
        return True

    def snapshot(self) -> dict:
        """Debug snapshot of service state."""
        with self._lock:
            return {
                "active_path_id": self._active_path_id,
                "active_kp_id": self._active_kp_id,
                "pending_interactions": self._ledger.snapshot(),
                "session_counts": {
                    kp_id: {
                        "teach_count": s.teach_count,
                        "assess_count": s.assess_count,
                        "consecutive_correct": s.consecutive_correct,
                        "has_feynman_pass": s.has_feynman_pass,
                    }
                    for kp_id, s in self._session_counts.items()
                },
            }


__all__ = ["LearningService"]
