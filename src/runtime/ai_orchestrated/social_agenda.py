# -*- coding: utf-8 -*-
"""Session-scoped social goals and cautious scene-partner hypotheses.

This store represents why Eris might continue a social thread. It is not a
psychological profile. A due, evidence-backed active goal is a self-owned
expression commitment của Eris; runtime chỉ giữ hard boundary/turn collision,
không suy diễn quyền im lặng từ mức phản hồi của user.
"""
from __future__ import annotations

from contextlib import contextmanager
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Callable, Mapping, Sequence

from .atomic_state import SQLiteAtomicStateStore, SQLiteStateTransaction
from .social_candidate import SocialSpeechCandidate
from .affordance import ExecutiveAffordance
from .social_plan import normalize_agenda_update
from cortex.subject.expression_commitment import commitment_payload


SOCIAL_AGENDA_STATE_SCHEMA = "eris.social_agenda_state.v1"
_BOUNDARY_RE = re.compile(
    r"(?:"
    r"\bđừng(?:\s+(?:trêu|nói|làm|gọi|nhắc|tiếp tục|vậy))?"
    r"|\bdừng(?:\s+lại)?\b"
    r"|\bthôi(?:\s+(?:đi|nhé|nha))?\b"
    r"|\bkhông thích (?:bị |kiểu |cách )?(?:trêu|nói vậy|làm vậy)"
    r"|\bstop(?:\s+(?:that|teasing|it))?\b"
    r"|\bdon['’]?t (?:tease|say that|do that|keep going)\b"
    r"|\bdo not (?:tease|say that|do that|keep going)\b"
    r"|やめて|やめよう|からかわないで|そういうの(?:は)?嫌"
    r")",
    re.IGNORECASE,
)
_LOW_ENGAGEMENT = {"ok", "ừ", "uh", "um", "hmm", "hm", "k", "ờ", "...", "うん", "はい"}


def _compact(value: Any, limit: int = 320) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(0.0, min(1.0, number))


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


@dataclass(frozen=True, slots=True)
class SocialGoal:
    goal_id: str
    goal_type: str
    objective: str
    desired_user_state: str
    strategy: str
    horizon: str
    success_signals: tuple[str, ...]
    stop_signals: tuple[str, ...]
    salience: float
    confidence: float
    evidence_refs: tuple[str, ...]
    source_turn_id: str
    status: str = "active"
    progress: float = 0.0
    low_engagement_count: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0
    last_move_at: float = 0.0
    cooldown_until: float = 0.0
    close_reason: str = ""
    version: int = 1
    claim_owner: str = ""
    claim_until: float = 0.0
    claim_token: str = ""
    move_seq: int = 0

    @property
    def active(self) -> bool:
        return self.status == "active"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "SocialGoal | None":
        data = payload or {}
        goal_id = _compact(data.get("goal_id", ""), 120)
        objective = _compact(data.get("objective", ""), 420)
        goal_type = _compact(data.get("goal_type", "none"), 48).lower() or "none"
        if not goal_id or not objective or goal_type == "none":
            return None
        status = _compact(data.get("status", "closed"), 24).lower() or "closed"
        if status not in {"active", "paused", "closed"}:
            status = "closed"
        return cls(
            goal_id=goal_id,
            goal_type=goal_type,
            objective=objective,
            desired_user_state=_compact(data.get("desired_user_state", ""), 160),
            strategy=_compact(data.get("strategy", ""), 220),
            horizon=_compact(data.get("horizon", "session"), 24).lower() or "session",
            success_signals=tuple(_compact(v, 120) for v in _sequence(data.get("success_signals"))[:8] if _compact(v, 120)),
            stop_signals=tuple(_compact(v, 120) for v in _sequence(data.get("stop_signals"))[:8] if _compact(v, 120)),
            salience=_clamp01(data.get("salience", 0.0)),
            confidence=_clamp01(data.get("confidence", 0.0), 0.5),
            evidence_refs=tuple(_compact(v, 140) for v in _sequence(data.get("evidence_refs"))[:6] if _compact(v, 140)),
            source_turn_id=_compact(data.get("source_turn_id", ""), 120),
            status=status,
            progress=_clamp01(data.get("progress", 0.0)),
            low_engagement_count=max(0, min(9, int(data.get("low_engagement_count", 0) or 0))),
            created_at=max(0.0, float(data.get("created_at", 0.0) or 0.0)),
            updated_at=max(0.0, float(data.get("updated_at", 0.0) or 0.0)),
            last_move_at=max(0.0, float(data.get("last_move_at", 0.0) or 0.0)),
            cooldown_until=max(0.0, float(data.get("cooldown_until", 0.0) or 0.0)),
            close_reason=_compact(data.get("close_reason", ""), 120),
            version=max(1, int(data.get("version", 1) or 1)),
            claim_owner=_compact(data.get("claim_owner", ""), 120),
            claim_until=max(0.0, float(data.get("claim_until", 0.0) or 0.0)),
            claim_token=_compact(data.get("claim_token", ""), 180),
            move_seq=max(0, int(data.get("move_seq", 0) or 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["success_signals"] = list(self.success_signals)
        payload["stop_signals"] = list(self.stop_signals)
        payload["evidence_refs"] = list(self.evidence_refs)
        return payload


@dataclass(frozen=True, slots=True)
class ScenePartnerState:
    availability: str = "uncertain"
    closeness_band: str = "new"
    play_balance: str = "balanced"
    tease_tolerance_estimate: float = 0.35
    tease_tolerance_confidence: float = 0.15
    hypotheses: tuple[Mapping[str, Any], ...] = ()
    boundary_flags: tuple[str, ...] = ()
    risk_context: tuple[str, ...] = ()
    updated_at: float = 0.0

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "ScenePartnerState":
        data = payload or {}
        return cls(
            availability=_compact(data.get("availability", "uncertain"), 32).lower() or "uncertain",
            closeness_band=_compact(data.get("closeness_band", "new"), 32).lower() or "new",
            play_balance=_compact(data.get("play_balance", "balanced"), 32).lower() or "balanced",
            tease_tolerance_estimate=_clamp01(data.get("tease_tolerance_estimate", 0.35), 0.35),
            tease_tolerance_confidence=_clamp01(data.get("tease_tolerance_confidence", 0.15), 0.15),
            hypotheses=tuple(dict(v) for v in _sequence(data.get("hypotheses"))[-6:] if isinstance(v, Mapping)),
            boundary_flags=tuple(_compact(v, 96) for v in _sequence(data.get("boundary_flags"))[-8:] if _compact(v, 96)),
            risk_context=tuple(_compact(v, 96) for v in _sequence(data.get("risk_context"))[-8:] if _compact(v, 96)),
            updated_at=max(0.0, float(data.get("updated_at", 0.0) or 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "hypotheses": [dict(v) for v in self.hypotheses],
            "boundary_flags": list(self.boundary_flags),
            "risk_context": list(self.risk_context),
        }


@dataclass(frozen=True, slots=True)
class SocialAgendaState:
    version: int = 0
    goals: tuple[SocialGoal, ...] = ()
    scene_partner: ScenePartnerState = field(default_factory=ScenePartnerState)
    events: tuple[Mapping[str, Any], ...] = ()
    updated_at: float = 0.0

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "SocialAgendaState":
        data = payload or {}
        goals = tuple(
            goal for goal in (
                SocialGoal.from_mapping(item)
                for item in _sequence(data.get("goals"))[-16:]
                if isinstance(item, Mapping)
            ) if goal is not None
        )
        return cls(
            version=max(0, int(data.get("version", 0) or 0)),
            goals=goals,
            scene_partner=ScenePartnerState.from_mapping(data.get("scene_partner") if isinstance(data.get("scene_partner"), Mapping) else None),
            events=tuple(dict(item) for item in _sequence(data.get("events"))[-60:] if isinstance(item, Mapping)),
            updated_at=max(0.0, float(data.get("updated_at", 0.0) or 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SOCIAL_AGENDA_STATE_SCHEMA,
            "version": self.version,
            "goals": [goal.to_dict() for goal in self.goals],
            "scene_partner": self.scene_partner.to_dict(),
            "events": [dict(item) for item in self.events],
            "updated_at": self.updated_at,
        }


class SocialAgendaStore:
    def __init__(
        self,
        *,
        initial_state: Mapping[str, Any] | None = None,
        persist: Callable[[Mapping[str, Any]], None] | None = None,
        logger: Any | None = None,
        clock: Callable[[], float] | None = None,
        allow_cross_session_memory: bool = False,
        atomic_store: SQLiteAtomicStateStore | None = None,
        atomic_key: str = "eris.social_agenda",
    ) -> None:
        self._clock = clock or time.time
        self._persist = persist
        self._atomic_store = atomic_store
        self._atomic_key = str(atomic_key or "eris.social_agenda")
        self._atomic_tx: SQLiteStateTransaction | None = None
        self._logger = logger
        self._allow_cross_session_memory = bool(allow_cross_session_memory)
        self._lock = threading.RLock()
        self._state = SocialAgendaState.from_mapping(initial_state)
        if self._atomic_store is not None:
            record = self._atomic_store.ensure(self._atomic_key, self._state.to_dict())
            self._state = SocialAgendaState.from_mapping(record.payload)
        with self._lock, self._state_transaction_locked():
            self._expire_stale(self._clock())

    def apply_update(
        self,
        payload: Mapping[str, Any] | None,
        *,
        source_turn_id: str,
        now: float | None = None,
        confidence: float = 0.7,
    ) -> bool:
        proposal = normalize_agenda_update(payload)
        decision = proposal["decision"]
        if decision == "none":
            return False
        current = float(now if now is not None else self._clock())
        with self._lock, self._state_transaction_locked():
            goals = list(self._state.goals)
            target_index = self._find_goal_index(goals, proposal["goal_type"])
            if decision == "open":
                horizon = proposal["horizon"]
                if horizon == "cross_session" and not self._allow_cross_session_memory:
                    horizon = "session"
                goal = SocialGoal(
                    goal_id=f"sag_{uuid.uuid4().hex[:16]}",
                    goal_type=proposal["goal_type"],
                    objective=proposal["objective"],
                    desired_user_state=proposal["desired_user_state"],
                    strategy=proposal["strategy"],
                    horizon=horizon,
                    success_signals=tuple(proposal["success_signals"]),
                    stop_signals=tuple(proposal["stop_signals"]),
                    salience=proposal["salience"],
                    confidence=_clamp01(confidence, 0.7),
                    evidence_refs=tuple(proposal["evidence_refs"]),
                    source_turn_id=_compact(source_turn_id, 120),
                    created_at=current,
                    updated_at=current,
                )
                # Keep at most one active goal per type so updates remain deterministic.
                if target_index is not None:
                    old_goal = goals[target_index]
                    goals[target_index] = replace(
                        old_goal,
                        status="closed",
                        close_reason="superseded",
                        version=old_goal.version + 1,
                        claim_owner="",
                        claim_until=0.0,
                        claim_token="",
                        updated_at=current,
                    )
                goals.append(goal)
                event = "goal_opened"
            elif target_index is None:
                return False
            else:
                old = goals[target_index]
                if decision in {"update", "advance"}:
                    goals[target_index] = replace(
                        old,
                        objective=proposal["objective"] or old.objective,
                        desired_user_state=proposal["desired_user_state"] or old.desired_user_state,
                        strategy=proposal["strategy"] or old.strategy,
                        success_signals=tuple(proposal["success_signals"]) or old.success_signals,
                        stop_signals=tuple(proposal["stop_signals"]) or old.stop_signals,
                        salience=max(old.salience, proposal["salience"]),
                        progress=min(1.0, old.progress + (0.18 if decision == "advance" else 0.05)),
                        status="active",
                        version=old.version + 1,
                        claim_owner="",
                        claim_until=0.0,
                        claim_token="",
                        updated_at=current,
                    )
                    event = "goal_advanced" if decision == "advance" else "goal_updated"
                elif decision == "pause":
                    goals[target_index] = replace(
                        old,
                        status="paused",
                        close_reason="model_pause",
                        version=old.version + 1,
                        claim_owner="",
                        claim_until=0.0,
                        claim_token="",
                        updated_at=current,
                    )
                    event = "goal_paused"
                else:
                    goals[target_index] = replace(
                        old,
                        status="closed",
                        close_reason="model_close",
                        version=old.version + 1,
                        claim_owner="",
                        claim_until=0.0,
                        claim_token="",
                        updated_at=current,
                    )
                    event = "goal_closed"
            self._state = replace(
                self._state,
                version=self._state.version + 1,
                goals=tuple(goals[-16:]),
                events=self._append_event(event, current, goal_type=proposal["goal_type"], source_turn_id=source_turn_id),
                updated_at=current,
            )
            self._persist_locked()
        self._emit(event, goal_type=proposal["goal_type"], source_turn_id=source_turn_id)
        return True

    def observe_user_turn(
        self,
        *,
        user_text: str,
        now: float | None = None,
        risk_context: Sequence[str] = (),
    ) -> dict[str, Any]:
        current = float(now if now is not None else self._clock())
        text = _compact(user_text, 420)
        normalized = _norm(text)
        boundary = bool(_BOUNDARY_RE.search(text))
        low = normalized in _LOW_ENGAGEMENT or (0 < len(normalized) <= 3 and "?" not in normalized)
        result = {"boundary": boundary, "low_engagement": low, "closed": 0}
        with self._lock, self._state_transaction_locked():
            goals = list(self._state.goals)
            for index, goal in enumerate(goals):
                if not goal.active:
                    continue
                if boundary:
                    goals[index] = replace(
                        goal,
                        status="closed",
                        close_reason="explicit_boundary",
                        version=goal.version + 1,
                        claim_owner="",
                        claim_until=0.0,
                        claim_token="",
                        updated_at=current,
                    )
                    result["closed"] += 1
                elif low:
                    count = goal.low_engagement_count + 1
                    if count >= 2:
                        goals[index] = replace(
                            goal,
                            status="closed",
                            low_engagement_count=count,
                            close_reason="two_low_engagement_responses",
                            version=goal.version + 1,
                            claim_owner="",
                            claim_until=0.0,
                            claim_token="",
                            updated_at=current,
                        )
                        result["closed"] += 1
                    else:
                        goals[index] = replace(
                            goal,
                            low_engagement_count=count,
                            salience=max(0.0, goal.salience - 0.18),
                            version=goal.version + 1,
                            claim_owner="",
                            claim_until=0.0,
                            claim_token="",
                            updated_at=current,
                        )
                else:
                    goals[index] = replace(
                        goal,
                        low_engagement_count=0,
                        progress=min(1.0, goal.progress + 0.08),
                        salience=min(1.0, goal.salience + 0.04),
                        version=goal.version + 1,
                        claim_owner="",
                        claim_until=0.0,
                        claim_token="",
                        updated_at=current,
                    )
            partner = self._update_partner(
                self._state.scene_partner,
                text=text,
                boundary=boundary,
                low=low,
                risk_context=tuple(risk_context),
                now=current,
            )
            event = "boundary_observed" if boundary else "user_outcome_observed"
            self._state = replace(
                self._state,
                version=self._state.version + 1,
                goals=tuple(goals),
                scene_partner=partner,
                events=self._append_event(event, current, low_engagement=low, closed=result["closed"]),
                updated_at=current,
            )
            self._persist_locked()
        self._emit(event, **result)
        return result

    def observe_exposure_outcome(
        self,
        *,
        outcome: Mapping[str, Any],
        now: float | None = None,
    ) -> None:
        if str(outcome.get("lane", "") or "").strip().lower() != "social_exposure":
            return
        current = float(now if now is not None else self._clock())
        response = _norm(outcome.get("actual_response", ""))
        positive = any(token in response for token in ("laugh", "cười", "haha", "counter", "笑"))
        with self._lock, self._state_transaction_locked():
            partner = self._state.scene_partner
            estimate = partner.tease_tolerance_estimate + (0.06 if positive else -0.03)
            confidence = partner.tease_tolerance_confidence + 0.04
            hypotheses = list(partner.hypotheses)
            hypotheses.append({
                "state": "playfully_engaged" if positive else "reaction_uncertain",
                "confidence": min(0.72, 0.40 + confidence * 0.25),
                "evidence_refs": [str(outcome.get("ticket_id", ""))],
            })
            partner = replace(
                partner,
                tease_tolerance_estimate=_clamp01(estimate, partner.tease_tolerance_estimate),
                tease_tolerance_confidence=_clamp01(confidence, partner.tease_tolerance_confidence),
                hypotheses=tuple(hypotheses[-6:]),
                updated_at=current,
            )
            self._state = replace(
                self._state,
                version=self._state.version + 1,
                scene_partner=partner,
                events=self._append_event("exposure_outcome", current, positive=positive),
                updated_at=current,
            )
            self._persist_locked()

    def _eligible_goal_locked(self, blackboard: Any, current: float) -> tuple[int, SocialGoal] | None:
        # V66: agenda là một motive của Eris. User đang active/busy hay vừa nói
        # không tự động hủy motive; boundary thật nằm ở boundary_flags/risk_context
        # và turn-collision guard của pipeline.
        goals = list(self._state.goals)
        partner = self._state.scene_partner
        if partner.boundary_flags or partner.risk_context:
            return None
        eligible = [
            (index, goal) for index, goal in enumerate(goals)
            if goal.active and not goal.claim_token and current >= goal.cooldown_until
            and goal.salience >= 0.52 and goal.confidence >= 0.48
        ]
        if not eligible:
            return None
        return max(eligible, key=lambda item: (item[1].salience, item[1].progress, item[1].updated_at))

    def peek_due(
        self, blackboard: Any, *, now: float | None = None
    ) -> ExecutiveAffordance | None:
        """Expose an agenda move without letting the store pre-empt Gemma."""
        current = float(now if now is not None else self._clock())
        with self._lock, self._state_transaction_locked():
            self._expire_stale(current)
            selected = self._eligible_goal_locked(blackboard, current)
            if selected is None:
                return None
            _, goal = selected
            candidate = self._candidate_for_goal(goal)
            # V66: goal active đã qua lifecycle/salience của chính Eris. Khi nó
            # đến hạn, đây là commitment xã hội chứ không phải lời đề nghị để
            # một governor khác hỏi lại "user có muốn nghe không?".
            commitment = commitment_payload(
                origin="social_agenda",
                source_id=f"{goal.goal_id}:move:{goal.move_seq + 1}",
                semantic_target=candidate.topic,
                motive=goal.goal_type or candidate.speech_act,
                pressure=max(goal.salience, candidate.urgency),
                freshness=goal.confidence,
                persistence=max(0.35, 1.0 - goal.progress),
            )
            return ExecutiveAffordance(
                affordance_id=f"social_agenda:{goal.goal_id}:v{goal.version}",
                owner="social_agenda", revision=goal.version,
                candidate=candidate, claim_required=True,
                expires_at=0.0, claim_key=goal.goal_id,
                metadata={
                    "goal_type": goal.goal_type,
                    "expression_commitment": commitment,
                },
            )

    def claim_affordance(
        self, affordance: ExecutiveAffordance, *, worker_id: str,
        now: float | None = None, lease_ms: int = 12000
    ) -> SocialSpeechCandidate | None:
        current = float(now if now is not None else self._clock())
        owner = _compact(worker_id or "anonymous", 100) or "anonymous"
        goal_id = str(affordance.claim_key or "")
        with self._lock, self._state_transaction_locked():
            self._expire_stale(current)
            goals = list(self._state.goals)
            for index, goal in enumerate(goals):
                if goal.goal_id != goal_id or goal.version != int(affordance.revision):
                    continue
                if not (goal.active and not goal.claim_token and current >= goal.cooldown_until):
                    return None
                new_version = goal.version + 1
                token = f"{goal.goal_id}:v{new_version}:{owner}"
                claimed = replace(
                    goal, version=new_version, claim_owner=owner,
                    claim_until=current + max(1.0, min(30.0, int(lease_ms) / 1000.0)),
                    claim_token=token, updated_at=current,
                )
                goals[index] = claimed
                self._state = replace(
                    self._state, version=self._state.version + 1, goals=tuple(goals),
                    events=self._append_event("agenda_move_claimed", current, goal_id=claimed.goal_id, worker_id=owner, version=claimed.version),
                    updated_at=current,
                )
                self._persist_locked()
                self._emit("agenda_move_claimed", goal_id=claimed.goal_id, worker_id=owner)
                return self._candidate_for_goal(claimed)
        return None

    def claim_due(
        self, blackboard: Any, *, worker_id: str, now: float | None = None, lease_ms: int = 12000
    ) -> SocialSpeechCandidate | None:
        preview = self.peek_due(blackboard, now=now)
        if preview is None:
            return None
        return self.claim_affordance(preview, worker_id=worker_id, now=now, lease_ms=lease_ms)

    def release_claim(
        self,
        *,
        goal_id: str,
        claim_token: str = "",
        reason: str,
        delay_seconds: float = 2.0,
        now: float | None = None,
    ) -> bool:
        current = float(now if now is not None else self._clock())
        with self._lock, self._state_transaction_locked():
            goals = list(self._state.goals)
            for index, goal in enumerate(goals):
                if goal.goal_id != goal_id or not goal.claim_token:
                    continue
                if not claim_token or goal.claim_token != claim_token:
                    return False
                goals[index] = replace(
                    goal,
                    version=goal.version + 1,
                    claim_owner="",
                    claim_until=0.0,
                    claim_token="",
                    cooldown_until=max(goal.cooldown_until, current + max(0.5, min(15.0, float(delay_seconds)))),
                    updated_at=current,
                )
                self._state = replace(
                    self._state,
                    version=self._state.version + 1,
                    goals=tuple(goals),
                    events=self._append_event(
                        "agenda_move_released",
                        current,
                        goal_id=goal_id,
                        reason=_compact(reason, 120),
                    ),
                    updated_at=current,
                )
                self._persist_locked()
                self._emit("agenda_move_released", goal_id=goal_id, reason=reason)
                return True
        return False

    def note_spoken(self, plan: Any, *, now: float | None = None) -> bool:
        semantics = getattr(plan, "semantics", None)
        if str(getattr(semantics, "turn_kind", "") or "").lower() != "social_agenda":
            return False
        goal_id = str(
            getattr(plan, "continuation_ticket_id", "")
            or getattr(semantics, "subject_key", "")
            or ""
        ).strip()
        claim_token = str(getattr(plan, "continuation_claim_token", "") or "").strip()
        current = float(now if now is not None else self._clock())
        with self._lock, self._state_transaction_locked():
            goals = list(self._state.goals)
            for index, goal in enumerate(goals):
                if goal.goal_id != goal_id or not goal.active or not goal.claim_token:
                    continue
                if not claim_token or goal.claim_token != claim_token:
                    return False
                goals[index] = replace(
                    goal,
                    version=goal.version + 1,
                    claim_owner="",
                    claim_until=0.0,
                    claim_token="",
                    move_seq=goal.move_seq + 1,
                    last_move_at=current,
                    cooldown_until=current + 45.0,
                    progress=min(1.0, goal.progress + 0.06),
                    updated_at=current,
                )
                self._state = replace(
                    self._state,
                    version=self._state.version + 1,
                    goals=tuple(goals),
                    events=self._append_event("agenda_move_spoken", current, goal_id=goal_id),
                    updated_at=current,
                )
                self._persist_locked()
                self._emit("agenda_move_spoken", goal_id=goal_id)
                return True
        return False

    @staticmethod
    def _candidate_for_goal(goal: SocialGoal) -> SocialSpeechCandidate:
        topic = (
            f"Advance the active social goal with the smallest useful move. Goal type: {goal.goal_type}. "
            f"Objective: {goal.objective}. Desired user state: {goal.desired_user_state}. "
            f"Strategy: {goal.strategy}. Current progress: {goal.progress:.2f}. "
            f"Stop signals: {', '.join(goal.stop_signals) or 'loss of engagement or any boundary'}. "
            "Choose one semantic move only: yield, callback, continue_bit, share, invite_story, "
            "light_challenge, soft_check_in, reopen_topic, or close_goal. Do not reveal the goal machinery."
        )
        return SocialSpeechCandidate(
            decision="candidate",
            kind="social_agenda",
            topic=_compact(topic, 1200),
            speech_act="advance_social_goal",
            anchor_type="conversation",
            anchor_id=goal.goal_id,
            evidence_refs=goal.evidence_refs,
            requires_grounding=False,
            confidence=goal.confidence,
            relevance=goal.salience,
            urgency=max(0.15, 0.45 - goal.progress * 0.2),
            tone="soft_warm",
            reason=f"claimed_social_goal:{goal.goal_type}:{goal.claim_token}",
            source="social_agenda_store",
            continuation_lane="social_agenda",
            claim_token=goal.claim_token,
            idempotency_key=f"{goal.goal_id}:move:{goal.move_seq + 1}",
        )

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        current = float(now if now is not None else self._clock())
        with self._lock, self._state_transaction_locked():
            self._expire_stale(current)
            payload = self._state.to_dict()
            payload["active_goal_count"] = sum(1 for goal in self._state.goals if goal.active)
            payload["claimed_goal_count"] = sum(1 for goal in self._state.goals if goal.claim_token)
            return payload

    def prompt_context(self, *, now: float | None = None) -> str:
        snapshot = self.snapshot(now=now)
        active = [goal for goal in snapshot["goals"] if goal.get("status") == "active"]
        if not active:
            return ""
        partner = snapshot["scene_partner"]
        return (
            "SOCIAL_AGENDA_STATE:\n"
            f"active_goals={active[:4]}\n"
            f"scene_partner={partner}\n"
            "Treat partner hypotheses as uncertain evidence, not facts. Boundary and risk flags outrank every goal."
        )

    def _expire_stale(self, now: float) -> None:
        with self._lock, self._state_transaction_locked():
            goals = list(self._state.goals)
            changed = False
            for index, goal in enumerate(goals):
                if not goal.active:
                    continue
                ttl = 3600.0 if goal.horizon == "session" else 900.0 if goal.horizon == "turn" else 86400.0
                if now - max(goal.updated_at, goal.created_at) > ttl:
                    goals[index] = replace(
                        goal,
                        status="closed",
                        close_reason="stale_goal",
                        version=goal.version + 1,
                        claim_owner="",
                        claim_until=0.0,
                        claim_token="",
                        updated_at=now,
                    )
                    changed = True
            if changed:
                self._state = replace(
                    self._state,
                    version=self._state.version + 1,
                    goals=tuple(goals),
                    events=self._append_event("stale_goals_closed", now),
                    updated_at=now,
                )
                self._persist_locked()

    @staticmethod
    def _find_goal_index(goals: list[SocialGoal], goal_type: str) -> int | None:
        for index in range(len(goals) - 1, -1, -1):
            if goals[index].goal_type == goal_type and goals[index].status != "closed":
                return index
        return None

    @staticmethod
    def _update_partner(
        partner: ScenePartnerState,
        *,
        text: str,
        boundary: bool,
        low: bool,
        risk_context: tuple[str, ...],
        now: float,
    ) -> ScenePartnerState:
        flags = list(partner.boundary_flags)
        if boundary and "explicit_social_boundary" not in flags:
            flags.append("explicit_social_boundary")
        availability = "low" if low else "available" if text else "uncertain"
        estimate = partner.tease_tolerance_estimate
        confidence = partner.tease_tolerance_confidence
        if boundary:
            estimate = max(0.0, estimate - 0.35)
            confidence = min(1.0, confidence + 0.25)
        elif low:
            estimate = max(0.0, estimate - 0.08)
            confidence = min(1.0, confidence + 0.04)
        else:
            confidence = min(1.0, confidence + 0.02)
        hypotheses = list(partner.hypotheses)
        hypotheses.append({
            "state": "boundary_set" if boundary else "low_availability" if low else "engaged_or_processing",
            "confidence": 0.92 if boundary else 0.56 if low else 0.42,
            "evidence_refs": [f"user_text:{_compact(text, 80)}"] if text else [],
        })
        return replace(
            partner,
            availability=availability,
            tease_tolerance_estimate=_clamp01(estimate, partner.tease_tolerance_estimate),
            tease_tolerance_confidence=_clamp01(confidence, partner.tease_tolerance_confidence),
            hypotheses=tuple(hypotheses[-6:]),
            boundary_flags=tuple(flags[-8:]),
            risk_context=tuple(_compact(v, 96) for v in risk_context[-8:] if _compact(v, 96)),
            updated_at=now,
        )

    def _append_event(self, kind: str, now: float, **fields: Any) -> tuple[Mapping[str, Any], ...]:
        events = list(self._state.events)
        events.append({"kind": kind, "timestamp": now, **fields})
        return tuple(events[-60:])

    @contextmanager
    def _state_transaction_locked(self):
        """Reload and mutate one durable snapshot under a process-safe DB lock."""
        if self._atomic_store is None or self._atomic_tx is not None:
            yield
            return
        with self._atomic_store.transaction(self._atomic_key, self._state.to_dict()) as tx:
            self._state = SocialAgendaState.from_mapping(tx.payload)
            self._atomic_tx = tx
            try:
                yield
            finally:
                self._atomic_tx = None

    def _persist_locked(self) -> None:
        payload = self._state.to_dict()
        if self._atomic_tx is not None:
            self._atomic_tx.stage(payload)
        elif self._atomic_store is not None:
            try:
                self._atomic_store.replace(self._atomic_key, payload)
            except Exception as exc:
                self._log("debug", "[atomic state] persistence failed: %s", exc)
        if self._persist is None:
            return
        try:
            self._persist(payload)
        except Exception as exc:
            self._log("debug", "[social agenda] persistence failed: %s", exc)

    def _emit(self, event: str, **fields: Any) -> None:
        self._log("info", "[social agenda] %s %s", event, fields)
        try:
            from runtime.observability import GLOBAL_OBSERVABILITY
            tags = {"goal_type": str(fields.get("goal_type", "")), "event": str(event)}
            GLOBAL_OBSERVABILITY.log(
                f"social_agenda.{event}",
                tags=tags,
                fields=dict(fields),
                status="ok",
            )
            GLOBAL_OBSERVABILITY.increment(
                "eris_social_agenda_events_total", tags=tags, fields=dict(fields)
            )
            GLOBAL_OBSERVABILITY.gauge(
                "eris_social_agenda_active_goals",
                float(sum(1 for goal in self._state.goals if goal.active)),
            )
        except Exception:
            pass

    def _log(self, level: str, message: str, *args: Any) -> None:
        method = getattr(self._logger, level, None) if self._logger is not None else None
        if callable(method):
            try:
                method(message, *args)
            except Exception:
                pass


__all__ = [
    "SOCIAL_AGENDA_STATE_SCHEMA",
    "ScenePartnerState",
    "SocialAgendaState",
    "SocialAgendaStore",
    "SocialGoal",
]
