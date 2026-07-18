# -*- coding: utf-8 -*-
"""Single-writer reducer cho state AI của ERIS.

Observer, planner, chat và autonomous không được tự sửa state. Chúng nộp event
vào đây. Một worker duy nhất áp event theo thứ tự turn, bỏ event cũ và lưu snapshot
nguyên tử. Đây là phần ít hào nhoáng nhất nhưng ngăn cả repo tự ghi đè ký ức của
mình, một thói quen mà trước đây các thread thực hiện khá nhiệt tình.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import replace
from typing import Any, Callable, Mapping

from .contracts import (
    AppraisalState,
    CognitiveObservation,
    IntentionPlan,
    RelationshipState,
    RuntimeMindState,
    StateEvent,
    clamp01,
    compact,
)


PersistFn = Callable[[Mapping[str, Any]], None]
Subscriber = Callable[[RuntimeMindState, StateEvent, bool], None]


class StateReducer:
    def __init__(
        self,
        *,
        initial_state: RuntimeMindState | None = None,
        persist: PersistFn | None = None,
        logger: Any | None = None,
    ) -> None:
        self._state = initial_state or RuntimeMindState()
        self._persist = persist
        self._logger = logger
        self._queue: queue.Queue[StateEvent | None] = queue.Queue()
        self._lock = threading.RLock()
        self._subscribers: list[Subscriber] = []
        self._closed = False
        self._worker = threading.Thread(
            target=self._run,
            name="eris-state-reducer",
            daemon=True,
        )
        self._worker.start()

    def subscribe(self, callback: Subscriber) -> None:
        if callable(callback):
            with self._lock:
                self._subscribers.append(callback)

    def snapshot(self) -> RuntimeMindState:
        with self._lock:
            return RuntimeMindState.from_mapping(self._state.to_dict())

    def submit(self, event: StateEvent) -> bool:
        if self._closed:
            return False
        self._queue.put(event)
        return True

    def apply_now(self, event: StateEvent) -> bool:
        """Dùng cho test/boot migration. Production nên đi qua queue."""
        accepted = self._apply(event)
        self._notify(event, accepted)
        return accepted

    def wait_idle(self, timeout: float = 2.0) -> bool:
        deadline = time.time() + max(0.0, float(timeout or 0.0))
        while time.time() < deadline:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.01)
        return self._queue.unfinished_tasks == 0

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._queue.put(None)
        try:
            self._worker.join(timeout=1.5)
        except Exception:
            pass

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            try:
                if event is None:
                    return
                accepted = self._apply(event)
                self._notify(event, accepted)
            except Exception as exc:  # noqa: BLE001
                self._log("warning", "[state reducer] event failed kind=%s: %s", getattr(event, "kind", "?"), exc)
            finally:
                self._queue.task_done()

    def _apply(self, event: StateEvent) -> bool:
        with self._lock:
            state = self._state
            # Event observation cũ tuyệt đối không được quay lại viết đè lượt mới.
            # Intention autonomous có thể cùng turn_seq=0 nên được quản theo version.
            if event.kind == "cognitive_observation" and event.turn_seq <= state.last_applied_turn_seq:
                self._log(
                    "info",
                    "[state reducer] stale event dropped kind=%s turn=%s latest=%s",
                    event.kind,
                    event.turn_seq,
                    state.last_applied_turn_seq,
                )
                return False
            if event.base_version >= 0 and event.base_version > state.version:
                # Caller nhìn thấy một tương lai không tồn tại. Bỏ thay vì đoán.
                self._log(
                    "warning",
                    "[state reducer] future base_version dropped base=%s current=%s",
                    event.base_version,
                    state.version,
                )
                return False

            if event.kind == "cognitive_observation":
                new_state = self._reduce_observation(state, event)
            elif event.kind == "intention_plan":
                new_state = replace(
                    state,
                    version=state.version + 1,
                    latest_intention=dict(event.payload),
                    updated_at=time.time(),
                )
            elif event.kind == "mechanical_outcome":
                new_state = self._reduce_mechanical_outcome(state, event)
            else:
                self._log("debug", "[state reducer] unknown event ignored kind=%s", event.kind)
                return False

            self._state = new_state
            if self._persist is not None:
                try:
                    self._persist(new_state.to_dict())
                except Exception as exc:  # noqa: BLE001
                    self._log("warning", "[state reducer] persist failed: %s", exc)
            return True

    def _reduce_observation(self, state: RuntimeMindState, event: StateEvent) -> RuntimeMindState:
        observation = CognitiveObservation.from_mapping(
            event.payload,
            turn_id=event.turn_id,
            turn_seq=event.turn_seq,
            source=str(event.payload.get("source", event.source) or event.source),
            latency_ms=float(event.payload.get("latency_ms", 0.0) or 0.0),
        )
        # Confidence thấp được lưu telemetry nhưng không được bẻ state dài hạn.
        weight = observation.confidence if observation.confidence >= 0.55 else 0.0
        # Autonomous/startup không có user turn, nên observer không được tự sáng tác
        # một biến động quan hệ từ câu ERIS tự nói. Nó vẫn được cập nhật appraisal,
        # continuity và open-loop.
        relation_weight = weight if observation.event_kind in {"chat", "force_speak"} else 0.0
        relation = state.relationship

        def delta(current: float, proposed: float, cap: float) -> float:
            return clamp01(current + max(-cap, min(cap, proposed * relation_weight * cap)))

        relational_trust = delta(relation.relational_trust, observation.relational_delta, 0.035)
        competence_trust = delta(relation.competence_trust, observation.competence_delta, 0.045)
        factual_reliability = delta(relation.factual_reliability, observation.factual_delta, 0.050)
        boundary_safety = delta(relation.boundary_safety, observation.boundary_delta, 0.040)
        familiarity = delta(relation.familiarity, observation.familiarity_delta, 0.025)
        closeness = delta(relation.closeness, observation.closeness_delta, 0.030)
        playful_safety = delta(relation.playful_safety, observation.playful_safety_delta, 0.035)
        rupture = delta(relation.rupture, observation.rupture_delta, 0.045)
        repair_progress = relation.repair_progress
        if relation_weight > 0.0:
            if observation.repair_needed:
                repair_progress = clamp01(repair_progress - 0.025 * relation_weight)
            elif observation.relationship_meaning in {"acceptance", "repair_accepted"}:
                repair_progress = clamp01(repair_progress + 0.040 * relation_weight)
                rupture = clamp01(rupture - 0.030 * relation_weight)

        updated_relation = RelationshipState(
            relational_trust=relational_trust,
            competence_trust=competence_trust,
            factual_reliability=factual_reliability,
            boundary_safety=boundary_safety,
            familiarity=familiarity,
            closeness=closeness,
            playful_safety=playful_safety,
            rupture=rupture,
            repair_progress=repair_progress,
            last_event=f"observer:{observation.relationship_meaning or observation.user_act}",
            last_turn_seq=max(relation.last_turn_seq, observation.turn_seq),
        )

        appraisal = observation.appraisal
        if weight <= 0.0:
            appraisal = state.appraisal
        else:
            appraisal = AppraisalState(
                pleasantness=appraisal.pleasantness,
                curiosity=appraisal.curiosity,
                tenderness=appraisal.tenderness,
                embarrassment=appraisal.embarrassment,
                irritation=appraisal.irritation,
                pressure=appraisal.pressure,
                novelty=appraisal.novelty,
                last_turn_seq=observation.turn_seq,
            )

        loops = list(state.open_loops)
        if observation.open_loop and observation.confidence >= 0.65:
            loops = [x for x in loops if x.casefold() != observation.open_loop.casefold()]
            loops.append(observation.open_loop)
        if observation.relationship_meaning in {"repair_accepted", "closure"} and loops:
            loops = loops[-7:]

        candidates = list(state.memory_candidates)
        if observation.memory_worthy and observation.memory_candidate and observation.confidence >= 0.68:
            candidates.append({
                "turn_id": observation.turn_id,
                "turn_seq": observation.turn_seq,
                "text": observation.memory_candidate,
                "confidence": observation.confidence,
                "evidence": list(observation.evidence),
                "source": observation.source,
                "created_at": time.time(),
            })
            candidates = candidates[-12:]

        return RuntimeMindState(
            version=state.version + 1,
            last_applied_turn_seq=max(state.last_applied_turn_seq, observation.turn_seq),
            relationship=updated_relation,
            appraisal=appraisal,
            latest_observation=observation.to_dict(),
            latest_intention=state.latest_intention,
            open_loops=tuple(loops[-8:]),
            memory_candidates=tuple(candidates),
            updated_at=time.time(),
        )

    def _reduce_mechanical_outcome(self, state: RuntimeMindState, event: StateEvent) -> RuntimeMindState:
        payload = dict(event.payload)
        # Tool/TTS failure ảnh hưởng factual/competence, không tự biến thành rupture.
        relation = state.relationship
        success = bool(payload.get("success", False))
        kind = compact(payload.get("kind", "mechanical"), 60)
        shift = 0.010 if success else -0.018
        relation = replace(
            relation,
            competence_trust=clamp01(relation.competence_trust + shift),
            factual_reliability=clamp01(relation.factual_reliability + (0.008 if success else -0.012)),
            last_event=f"runtime:{kind}:{'ok' if success else 'failed'}",
        )
        return replace(
            state,
            version=state.version + 1,
            relationship=relation,
            updated_at=time.time(),
        )

    def _notify(self, event: StateEvent, accepted: bool) -> None:
        state = self.snapshot()
        with self._lock:
            callbacks = tuple(self._subscribers)
        for callback in callbacks:
            try:
                callback(state, event, accepted)
            except Exception as exc:  # noqa: BLE001
                self._log("debug", "[state reducer] subscriber failed: %s", exc)

    def _log(self, level: str, message: str, *args: Any) -> None:
        logger = self._logger
        if logger is None:
            return
        try:
            getattr(logger, level)(message, *args)
        except Exception:
            pass


__all__ = ["StateReducer"]
