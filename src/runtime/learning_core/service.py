"""LearningService - bien gioi deterministic cua he hoc tap Eris.

VAI TRO CUA MODULE NAY
----------------------
Day la *mot cua vao duy nhat* de runtime ghi/duyet su that hoc tap ben vung:

- LearningEvidence: user da the hien bang chung gi?
- MasteryRecord: muc do nam vung duoc tinh lai tu evidence.
- LearningPath / KnowledgePoint: dang hoc path/concept nao.
- PendingInteraction: cau hoi nao dang cho user tra loi.
- ReviewItem: khi nao can on lai theo scheduler.

NHUNG GI MODULE NAY CO QUYEN QUYET
----------------------------------
1. Evidence nao duoc append vao store.
2. Mastery duoc recompute deterministic ra sao.
3. Gate hoc tap co pass hay chua.
4. Review nao den han.
5. TutorStep ke tiep theo policy deterministic la gi.

NHUNG GI MODULE NAY *KHONG* DUOC QUYET
--------------------------------------
1. Khong tu bat tutor trong mot cuoc tro chuyen.
2. Khong chon Eris nen noi bao nhieu cau trong turn hien tai.
3. Khong viet public text, khong goi TTS, khong so huu conversation pacing.
4. Khong tu suy dien user da hieu chi vi Eris vua giai thich xong.
5. Khong duoc nhan raw chain-of-thought cua model lam evidence.

OWNER KHI PHOI HOP VOI AGENT LOOP
----------------------------------
TurnAgentLoop         -> root lifecycle cua moi user turn.
TutorRole/TutorReasoner -> de xuat pedagogical intent (probe/teach/practice/assess).
ConversationDirector -> quyet dinh turn nay tiet lo bao nhieu va dung o dau.
LearningService       -> chi commit su that hoc tap deterministic.

Quy tac cot loi: "LLM de xuat; deterministic kernel commit". Nho boundary nay,
DeepTutor-derived logic chi la learning kernel ben trong Eris, khong tro thanh
mot agent thu hai tranh quyen voi root TurnAgentLoop.

Thread safety: mot RLock cho moi LearningService instance; production nen dung
mot instance/process va inject xuong cac adapter thay vi tu tao service moi.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from typing import Any, Sequence

from runtime.learning_core.contracts import (
    LearnerProfile,
    LearningEvidence,
    LearningPath,
    MasteryRecord,
    PendingInteraction,
    ReviewItem,
)
from runtime.learning_core.records import AssessmentAttempt, digest, evidence_metadata
from runtime.learning_core import retention
from runtime.learning_core.belief_model import LearnerBeliefState, compute_belief
from runtime.learning_core.mastery import (
    DEFAULT_POLICY,
    MasteryPolicy,
    compute_mastery,
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
    due_items,
)
from runtime.learning_core.store import LearningStore
from runtime.learning_core.review_memory import (
    retrievability as review_retrievability,
    update_review_memory,
    with_current_risk,
)


class LearningService:
    """Orchestrates the full learning kernel for one Eris instance."""

    def __init__(
        self,
        store: LearningStore | None = None,
        *,
        mastery_policy: MasteryPolicy = DEFAULT_POLICY,
        nav_policy: NavigationPolicy = DEFAULT_NAV_POLICY,
        scheduler: ReviewScheduler = DEFAULT_SCHEDULER,
        retention_mode: str = "shadow",
        logger: Any = None,
    ) -> None:
        self._store = store or LearningStore()
        self._mastery_policy = mastery_policy
        self._nav_policy = nav_policy
        self._scheduler = scheduler
        if retention_mode not in {"shadow", "fsrs", "heuristic"}:
            raise ValueError("invalid_retention_mode")
        self._retention_mode = retention_mode
        self._logger = logger
        self._lock = threading.RLock()
        # In-memory session state (ephemeral)
        self._ledger = PendingInteractionLedger()
        self._session_counts: dict[str, _KPSession] = {}  # kp_id → _KPSession
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
            review_items = self._scheduled_review_items(list(path.kp_ids), now=ts)
            overdue = due_items(review_items, now=ts, max_items=3)

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
        review_recall: bool = False,
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
            review_recall=bool(review_recall),
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
            db_interaction = self._store.load_interaction(interaction_id)
            if db_interaction is None or db_interaction.status != "pending":
                return None
            self._ledger.restore_from_store(db_interaction)
            result = self._ledger.resolve(interaction_id, user_answer, turn_id=turn_id, now=ts)
            if result is None:
                return None

            # Commit evidence for deterministically graded items
            if result.interaction.interaction_type in {"multiple_choice", "true_false"}:
                evidence_id = (
                    f"ev:interaction:{hashlib.sha256((interaction_id + chr(124) + turn_id).encode()).hexdigest()[:32]}"
                )
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
                    metadata=json.dumps({"review_recall": True, "hint_count": 0})
                    if result.interaction.review_recall
                    else "",
                )
                if not self._commit_evidence_locked(evidence, ts, interaction_update=interaction_id):
                    return None
                # Update session counter
                kp_id = result.interaction.kp_id
                session = self._session_counts.get(kp_id, _KPSession())
                self._session_counts[kp_id] = session.assessed(
                    result.grading.correct and self._store.assistance_for(interaction_id)["assistance"] == "independent"
                )
            else:
                self._store.resolve_interaction(
                    interaction_id, status=result.interaction.status, turn_id=turn_id, answered_at=ts
                )

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
        correct: bool | None = None,
        interaction_id: str = "",
        turn_id: str = "",
        error_code: str = "",
        review_recall: bool = False,
        hint_count: int = 0,
        assistance: str = "independent",
        answer_revealed: bool = False,
        result: str = "",
        item_family_id: str = "",
        rubric_version: str = "legacy-v1",
        assessor_version: str = "semantic-v1",
        source_refs: tuple[str, ...] = (),
        rating: int = 0,
        now: float | None = None,
    ) -> LearningEvidence | None:
        """Compatibility entry point; every new semantic event also has an attempt."""
        ts = float(now if now is not None else time.time())
        if not (interaction_id or turn_id):
            return None
        if correct is None:
            correct = evidence_type not in {"quiz_incorrect", "feynman_fail", "misconception"}
        state = self._store.assistance_for(interaction_id)
        from runtime.learning_core.records import ASSISTANCE

        assistance = ASSISTANCE[max(ASSISTANCE.index(assistance), ASSISTANCE.index(state["assistance"]))]
        hint_count = max(hint_count, state.get("hint_count", 0))
        attempt = AssessmentAttempt(
            attempt_id="attempt:" + digest([kp_id, interaction_id, turn_id])[:32],
            kp_id=kp_id,
            result=result or ("correct" if correct else "incorrect"),
            evidence_type=evidence_type,
            strength=strength,
            interaction_id=interaction_id,
            turn_id=turn_id,
            path_id=self._active_path_id,
            item_family_id=item_family_id or interaction_id,
            assistance=assistance,
            hint_count=hint_count,
            answer_revealed=answer_revealed,
            rubric_version=rubric_version,
            assessor_version=assessor_version,
            source_refs=source_refs,
            recorded_at=ts,
            review_recall=review_recall,
            rating=rating,
            error_code=error_code,
            phase="review" if review_recall else "practice",
        )
        evidence = self._evidence_for_attempt(attempt)
        with self._lock:
            if self._commit_evidence_locked(evidence, ts, attempt=attempt):
                if evidence_type in {"feynman_pass", "feynman_fail"}:
                    session = self._session_counts.get(kp_id, _KPSession())
                    session = (
                        session.feynman_passed().assessed(True)
                        if attempt.independently_correct
                        else session.assessed(False)
                    )
                    self._session_counts[kp_id] = session
                return evidence
        return None

    @staticmethod
    def _evidence_for_attempt(attempt):
        return LearningEvidence(
            evidence_id="ev:attempt:" + digest(attempt.attempt_id)[:32],
            kp_id=attempt.kp_id,
            evidence_type=attempt.evidence_type,
            strength=attempt.strength,
            correct=attempt.result in {"correct", "partial"},
            interaction_id=attempt.interaction_id,
            turn_id=attempt.turn_id,
            recorded_at=attempt.recorded_at,
            error_code=attempt.error_code,
            metadata=attempt.evidence_metadata(),
        )

    def record_attempt(self, attempt: AssessmentAttempt) -> bool:
        from runtime.learning_core.contracts import EVIDENCE_TYPES

        if attempt.evidence_type not in EVIDENCE_TYPES:
            raise ValueError("unsupported_evidence_type")
        for ref in attempt.source_refs if attempt.result != "ungraded" else ():
            span = self._store.source_span(ref)
            path = self._store.load_path(attempt.path_id) if attempt.path_id else None
            if span is None or span["stale"] or (path and path.domain_id and span["domain_id"] != path.domain_id):
                raise ValueError("stale_or_out_of_scope_source")
        evidence = None if attempt.result == "ungraded" else self._evidence_for_attempt(attempt)
        projection_time = max(attempt.recorded_at, attempt.corrected_at)
        with self._lock:
            committed = self._store.commit_assessment(
                attempt, evidence, self._projection(attempt.kp_id, projection_time), now=projection_time
            )
            if committed:
                self._session_counts.pop(attempt.kp_id, None)
            return committed

    def forget_attempt(self, attempt_id: str, *, now=None) -> bool:
        attempt = self._store.load_attempt(attempt_id)
        if attempt is None:
            return False
        ts = float(now if now is not None else time.time())
        with self._lock:
            result = self._store.forget_attempt(attempt_id, self._projection(attempt.kp_id, ts), now=ts)
            self._session_counts.pop(attempt.kp_id, None)
            return result

    def attempts(self, kp_id="", *, limit=32, include_superseded=False):
        return self._store.load_attempts(kp_id, limit=limit, include_superseded=include_superseded)

    def retention_snapshot(self, kp_id=""):
        return {
            "readiness": {**retention.readiness(), "mode": self._retention_mode},
            "selected_mode": self._retention_mode,
            "items": self._store.retention_snapshot(kp_id),
        }

    def _scheduled_review_items(self, kp_ids=None, *, now):
        items = self._store.load_review_items(kp_ids)
        memories = self._store.load_review_memory_batch([x.kp_id for x in items])
        selected = {x.kp_id: with_current_risk(x, memories.get(x.kp_id), now=now) for x in items}
        if self._retention_mode == "fsrs":
            views = retention.schedule_view(self._store.retention_snapshot(kp_ids=kp_ids), now=now)
            for kp_id, view in views.items():
                if kp_ids is not None and kp_id not in kp_ids:
                    continue
                selected[kp_id] = ReviewItem(
                    kp_id, view["due_at"], 1.0 - view["retrievability"], interval_days=view["interval_days"]
                )
        return list(selected.values())

    def register_domain(self, domain):
        return self._store.register_domain(domain)

    def import_source_spans(self, spans):
        return self._store.import_spans(spans)

    def search_sources(self, query, *, domain_id="", source_ids=(), limit=6):
        path = self.active_path()
        scope = domain_id or (path.domain_id if path else "")
        return self._store.search_sources(scope, query, source_ids=source_ids, limit=limit) if scope else []

    def curriculum_snapshot(self, path_id=""):
        path = self._store.load_path(path_id) if path_id else self.active_path()
        return {
            "path": path.to_dict() if path else None,
            "revision": self._store.path_revision(path.path_id) if path else "",
            "history": self._store.curriculum_history(path.path_id) if path else [],
        }

    def revise_path(self, path, *, base_revision, reason, source_refs=(), now=None):
        with self._lock:
            revision = self._store.revise_path(
                path, base_revision=base_revision, reason=reason, source_refs=source_refs, now=now
            )
            if path.path_id == self._active_path_id and self._active_kp_id not in path.kp_ids:
                self._active_kp_id = path.kp_ids[0]
                self._session_counts = {}
                self._persist_runtime_state_locked()
            return revision

    def preview_curriculum(self, path, *, source_refs=(), reason=""):
        from runtime.learning_core.catalog import validate_path, revision_for, exact_diff

        validate_path(path)
        previous = self._store.load_path(path.path_id)
        if previous is None or previous.domain_id != path.domain_id:
            raise ValueError("revision_requires_existing_domain_path")
        before = {p.kp_id: p.to_dict() for p in previous.knowledge_points}
        after = {p.kp_id: p.to_dict() for p in path.knowledge_points}
        added = sorted(after.keys() - before.keys())
        if added and not source_refs:
            raise ValueError("new_curriculum_objectives_require_sources")
        for ref in source_refs:
            span = self._store.source_span(ref)
            if span is None or span["stale"] or span["domain_id"] != path.domain_id:
                raise ValueError("curriculum_source_stale_or_out_of_scope")
        return {
            "schema": "eris.curriculum.revision.v1",
            "base_revision": revision_for(previous),
            "proposed_revision": revision_for(path),
            "exact_diff": exact_diff(previous.to_dict(), path.to_dict()),
            "path": path.to_dict(),
            "source_refs": list(source_refs),
            "reason": reason,
            "changes": {
                "added": added,
                "removed": sorted(before.keys() - after.keys()),
                "changed": [key for key in sorted(before.keys() & after.keys()) if before[key] != after[key]],
                "order_before": list(previous.kp_ids),
                "order_after": list(path.kp_ids),
                "title": {"before": previous.title, "after": path.title},
                "goal": {"before": previous.goal, "after": path.goal},
            },
        }

    def evaluation_report(self):
        from runtime.learning_core.evaluation import evaluate_attempts

        rows = self.attempts(limit=500)
        return {**evaluate_attempts(rows), "sample_window": "latest_500_effective_attempts"}

    def correct_attempt(self, attempt_id, *, correction_id, result="ungraded", now=None):
        from dataclasses import replace

        if result not in {"correct", "incorrect", "ungraded"}:
            raise ValueError("unsupported_correction_result")
        original = self._store.load_attempt(attempt_id)
        if original is None:
            raise ValueError("unknown_attempt")
        evidence_type = (
            ("quiz_correct" if result == "correct" else "quiz_incorrect") if result != "ungraded" else "exposure"
        )
        return self.record_attempt(
            replace(
                original,
                attempt_id=correction_id,
                supersedes_attempt_id=attempt_id,
                result=result,
                evidence_type=evidence_type,
                strength=1.0 if result == "correct" else 0.0,
                corrected_at=float(now if now is not None else time.time()),
                assessor_version="user-correction-v1",
            )
        )

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

    def recent_evidence(self, kp_id: str, *, limit: int = 16) -> tuple[LearningEvidence, ...]:
        """Read-only bounded ledger phục vụ adaptive teaching.

        Không trả raw chat, không tự ghi evidence hoặc nhận phán đoán của Root.
        ID ổn định giúp phân biệt các câu hỏi độc lập để tránh quá tự tin.
        """
        with self._lock:
            rows = self._store.load_recent_evidence(kp_id, limit=max(1, min(32, int(limit))))
        return tuple(rows)

    # ------------------------------------------------------------------
    # Review items
    # ------------------------------------------------------------------

    def due_review_items(self, *, now: float | None = None) -> list[ReviewItem]:
        ts = float(now if now is not None else time.time())
        with self._lock:
            path = self._store.load_path(self._active_path_id) if self._active_path_id else None
            kp_ids = list(path.kp_ids) if path else None
            items = self._scheduled_review_items(kp_ids, now=ts)
        return due_items(items, now=ts, max_items=3)

    def review_snapshot(self, kp_ids: Sequence[str] | None = None) -> dict[str, dict]:
        """Projection chỉ-đọc cho adapter/debug; scheduler/DB vẫn thuộc service."""
        ts = time.time()
        with self._lock:
            items = self._scheduled_review_items(list(kp_ids) if kp_ids is not None else None, now=ts)
        memories = self._store.load_review_memory_batch([x.kp_id for x in items])
        fsrs_items = (
            retention.schedule_view(self._store.retention_snapshot(kp_ids=kp_ids), now=ts)
            if self._retention_mode == "fsrs"
            else {}
        )
        return {
            item.kp_id: {
                **item.to_dict(),
                "scheduler_owner": "fsrs" if item.kp_id in fsrs_items else "heuristic",
                "memory": memories[item.kp_id].to_dict() if item.kp_id in memories else None,
                "retrievability_heuristic": round(review_retrievability(memories[item.kp_id], now=ts), 4)
                if item.kp_id in memories
                else None,
            }
            for item in items
        }

    def review_memory(self, kp_id: str) -> dict[str, Any] | None:
        """D/S/R heuristic chỉ đọc; có thể truy vấn lại sau restart."""
        with self._lock:
            memory = self._store.load_review_memory(kp_id)
        if memory is None:
            return None
        return {**memory.to_dict(), "retrievability_now": round(review_retrievability(memory, now=time.time()), 4)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _projection(self, kp_id, ts):
        def project(ledger, _current_review, _old_memory):
            # Replay from effective evidence also makes correction/forget retract
            # stale mastery and retention instead of appending a compensating score.
            mastery = compute_mastery(kp_id, ledger, now=ts, policy=self._mastery_policy)
            review = memory = None
            seen_interactions, seen_turns = set(), set()
            from dataclasses import replace

            for ev in ledger:
                meta = evidence_metadata(ev)
                correlated = (ev.interaction_id and ev.interaction_id in seen_interactions) or (
                    ev.turn_id and ev.turn_id in seen_turns
                )
                scheduled = replace(ev, metadata=json.dumps({**meta, "review_recall": False})) if correlated else ev
                review, memory = update_review_memory(
                    scheduled, review, memory, now=ev.recorded_at, max_interval_days=self._scheduler.max_interval_days
                )
                if meta.get("review_recall") is True:
                    if ev.interaction_id:
                        seen_interactions.add(ev.interaction_id)
                    if ev.turn_id:
                        seen_turns.add(ev.turn_id)
            if review is not None:
                mastery = replace(
                    mastery,
                    next_review_at=review.due_at,
                    retrievability=review_retrievability(memory, now=ts) if memory else 0.0,
                )
            return mastery, review, compute_belief(kp_id, ledger), memory, retention.replay(ledger)

        return project

    def _commit_evidence_locked(self, evidence, ts, *, attempt=None, interaction_update=None) -> bool:
        if attempt is None:
            meta = evidence_metadata(evidence)
            attempt = AssessmentAttempt(
                attempt_id="attempt:" + digest([evidence.kp_id, evidence.interaction_id, evidence.turn_id])[:32],
                kp_id=evidence.kp_id,
                result="correct" if evidence.correct else "incorrect",
                evidence_type=evidence.evidence_type,
                strength=evidence.strength,
                interaction_id=evidence.interaction_id,
                turn_id=evidence.turn_id,
                path_id=self._active_path_id,
                item_family_id=evidence.interaction_id,
                recorded_at=ts,
                review_recall=meta.get("review_recall") is True,
                assistance=self._store.assistance_for(evidence.interaction_id)["assistance"],
                hint_count=self._store.assistance_for(evidence.interaction_id).get("hint_count", 0),
            )
            from dataclasses import replace

            evidence = replace(evidence, metadata=attempt.evidence_metadata())
        return self._store.commit_evidence_bundle(
            evidence,
            self._projection(evidence.kp_id, ts),
            now=ts,
            attempt=attempt,
            interaction_update=interaction_update,
        )

    def repeated_error_patterns(self, kp_id: str, *, min_independent: int = 2) -> list[dict[str, Any]]:
        """Bằng chứng lỗi tái diễn, chưa phải nhãn tâm lý hay chứng minh hiểu sai.

        Đọc từ ledger SQLite nguyên bản, không từ nhận định tự thuật của model.
        """
        with self._lock:
            return self._store.repeated_error_patterns(kp_id, min_independent=min_independent)

    def learner_belief(self, kp_id: str) -> LearnerBeliefState:
        """Read-model cho Root/Tutor: belief chưa hiệu chỉnh, không được ghi trực tiếp."""
        with self._lock:
            return self._store.load_belief(kp_id)

    def learner_belief_snapshot(self, kp_ids: Sequence[str] | None = None) -> dict[str, dict]:
        with self._lock:
            path = self._store.load_path(self._active_path_id) if self._active_path_id else None
            ids = list(kp_ids) if kp_ids is not None else (list(path.kp_ids) if path else [])
            return {kp_id: self._store.load_belief(kp_id).to_dict() for kp_id in ids[:32]}

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
