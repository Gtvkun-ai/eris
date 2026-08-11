# -*- coding: utf-8 -*-
"""Runtime projection cho ActiveConcern V40.

Không sở hữu memory mới. Nguồn sự thật vẫn là ConcernStore/ThoughtStream/Agenda.
Class này chỉ:
1) hấp thụ random seed đủ chất lượng thành concern thật;
2) project concern đang sống cho planner + Neuro;
3) ghi receipt khi một concern thật sự được public surface.
"""
from __future__ import annotations

import time
from typing import Any, Mapping, Sequence

from cortex.active_concern import (
    agenda_concern_view, clamp01, compact, merge_concern_views,
    private_concern_view, thought_concern_view,
)
from cortex.private_mind.contracts import stable_id


class ActiveConcernRuntime:
    def __init__(self, host: Any, *, logger: Any | None = None) -> None:
        self.host = host
        self.logger = logger or getattr(host, "logger", None)
        self._last_activation: dict[str, float] = {}
        self._last_signature = ""

    def _store(self) -> Any | None:
        daemon = getattr(self.host, "private_mind_daemon", None)
        return getattr(daemon, "concern_store", None)

    def _interruption_cost(self) -> float:
        attention = getattr(self.host, "last_cortex_attention", None)
        return clamp01(getattr(attention, "interrupt_cost", 0.0), 0.0)

    def absorb_affordances(self, affordances: Sequence[Any], *, now: float | None = None) -> tuple[str, ...]:
        """Cho seed tốt nhập đời sống nhận thức trước khi Neuro quyết định nói/im.

        Seed chỉ tạo concern khi có premise cụ thể và quality đủ. Việc được nhập
        concern KHÔNG cấp quyền nói; đó chỉ là "ý này còn ở trong đầu".
        """
        store = self._store()
        if store is None:
            return ()
        current = float(now or time.time())
        created: list[str] = []
        for affordance in tuple(affordances or ()):
            candidate = getattr(affordance, "candidate", None)
            seed_id = str(getattr(candidate, "seed_id", "") or "").strip()
            premise = compact(getattr(candidate, "topic", ""), 360)
            quality = clamp01(getattr(candidate, "seed_quality_score", 0.0), 0.0)
            motive = clamp01(getattr(candidate, "seed_motive_strength", 0.0), 0.0)
            if not seed_id or not premise or quality < 0.58:
                continue
            event_kind = str(getattr(candidate, "seed_event_kind", "thought") or "thought").strip()
            concern_id = stable_id("concern", "seed", seed_id)
            evidence = tuple(dict.fromkeys((seed_id, *tuple(getattr(candidate, "evidence_refs", ()) or ()))))[:12]
            question = premise if event_kind in {"curiosity_question", "knowledge_gap"} else ""
            update = getattr(store, "update_from_judgment", None)
            if not callable(update):
                continue
            concern = update({
                "id": concern_id,
                "theme": premise,
                "evidence_ids": evidence,
                "open_questions": (question,) if question else (),
                "pressure": clamp01(0.18 + 0.30 * quality + 0.22 * motive),
                "uncertainty": clamp01(getattr(candidate, "uncertainty", 0.35), 0.35),
                "status": "open",
                "metadata": {
                    "created_from_seed": seed_id,
                    "seed_event_kind": event_kind,
                    "seed_family": str(getattr(candidate, "source_kind", "") or ""),
                    "last_seed_absorbed_at": current,
                },
            })
            if concern is None:
                continue
            # ConcernStore có semantic merge, nên ID trả về có thể khác seed ID nếu
            # đây chỉ là paraphrase của một concern đã sống từ trước. Chính xác là
            # điều ta muốn: một chuyện, một danh tính.
            actual_id = str(getattr(concern, "id", "") or concern_id)
            meta = dict(getattr(concern, "metadata", {}) or {})
            meta.setdefault("mutation_count", 0)
            meta.setdefault("reactivation_count", 0)
            meta.setdefault("surfaced_count", 0)
            meta.setdefault("last_mutation_at", current)
            meta.setdefault("last_reactivated_at", current)
            concern.metadata = meta
            store.add_or_update(concern)
            created.append(actual_id)
            self._log(
                "info",
                "[active concern] absorbed id=%s source=seed kind=%s premise=%s",
                actual_id, event_kind, premise,
            )
        return tuple(created)

    def snapshot(self, *, now: float | None = None, limit: int = 8) -> tuple[dict[str, Any], ...]:
        current = float(now or time.time())
        interruption = self._interruption_cost()
        projected = []

        # 1) PrivateConcern là nguồn persistent mạnh nhất.
        store = self._store()
        if store is not None:
            try:
                concerns = tuple(store.open_concerns(limit=max(12, limit * 2)) or ())
            except Exception:
                concerns = ()
            for concern in concerns:
                cid = str(getattr(concern, "id", "") or "")
                projected.append(private_concern_view(
                    concern,
                    now=current,
                    previous_activation=self._last_activation.get(cid),
                    interruption_cost=interruption,
                ))

        # 2) ThoughtStream có cognition chưa kịp/không cần nhập ConcernStore.
        thought_stream = getattr(self.host, "thought_stream", None)
        latest_report = getattr(thought_stream, "latest_report", None)
        if callable(latest_report):
            try:
                report = latest_report()
                thoughts = tuple(getattr(report, "recent_thoughts", ()) or ())
            except Exception:
                thoughts = ()
            for thought in thoughts[:8]:
                if bool(getattr(thought, "resolved", False)):
                    continue
                cid = f"thought:{str(getattr(thought, 'thought_id', '') or '')}"
                projected.append(thought_concern_view(
                    thought,
                    now=current,
                    previous_activation=self._last_activation.get(cid),
                    interruption_cost=interruption,
                ))

        # 3) InternalAgenda giữ open question/repair/technical follow-up có evidence.
        agenda = getattr(self.host, "internal_agenda", None)
        top_items = getattr(agenda, "top_items", None)
        if callable(top_items):
            try:
                items = tuple(top_items(limit=8) or ())
            except Exception:
                items = ()
            for item in items:
                if not tuple(getattr(item, "evidence_ids", ()) or ()):
                    continue
                cid = f"agenda:{str(getattr(item, 'id', '') or '')}"
                projected.append(agenda_concern_view(
                    item,
                    now=current,
                    previous_activation=self._last_activation.get(cid),
                    interruption_cost=interruption,
                ))

        # Dedupe semantic giữa ba nguồn. Không cộng score, vì ba subsystem cùng
        # nhắc một chuyện không biến nó thành ba bằng chứng độc lập.
        views = list(merge_concern_views(projected))
        new_activation: dict[str, float] = {}
        for view in views:
            new_activation[view.concern_id] = view.activation
        self._last_activation.update(new_activation)
        views.sort(key=lambda item: (item.speech_pressure, item.activation, item.persistence), reverse=True)
        payload = tuple(item.to_dict() for item in views[: max(0, int(limit))])
        signature = "|".join(
            f"{item['concern_id']}:{item['state']}:{round(float(item['activation']),1)}:{round(float(item['speech_pressure']),1)}"
            for item in payload[:3]
        )
        if signature and signature != self._last_signature:
            top = payload[0]
            self._log(
                "info",
                "[active concern] top id=%s state=%s activation=%.2f novelty=%.2f habituation=%.2f speech=%.2f trajectory=%s sources=%s",
                top.get("concern_id", ""), top.get("state", ""), float(top.get("activation", 0.0)),
                float(top.get("novelty", 0.0)), float(top.get("habituation", 0.0)),
                float(top.get("speech_pressure", 0.0)), top.get("trajectory", ""),
                ",".join(str(x) for x in tuple(top.get("source_kinds", ()) or ())[:4]),
            )
            self._last_signature = signature
        return payload

    def note_public_surface(self, concern_id: str, *, now: float | None = None, evidence_ref: str = "") -> bool:
        store = self._store()
        if store is None or not concern_id:
            return False
        concern = getattr(store, "get", lambda _x: None)(concern_id)
        if concern is None:
            return False
        current = float(now or time.time())
        meta = dict(getattr(concern, "metadata", {}) or {})
        meta["surfaced_count"] = int(meta.get("surfaced_count", 0) or 0) + 1
        meta["last_surfaced_at"] = current
        if evidence_ref:
            refs = list(getattr(concern, "evidence_ids", ()) or ())
            if evidence_ref not in refs:
                refs.append(evidence_ref)
                concern.evidence_ids = tuple(refs[:64])
        concern.metadata = meta
        concern.updated_at = current
        # Nói ra chỉ xả một phần pressure. Concern chưa "resolved" nếu chưa có
        # evidence/closure mới; như vậy thought có thể sống tiếp mà không spam.
        concern.pressure = clamp01(concern.pressure * 0.82)
        store.add_or_update(concern)
        self._log(
            "info", "[active concern] surfaced id=%s count=%s pressure=%.2f",
            concern_id, meta["surfaced_count"], concern.pressure,
        )
        return True

    def _log(self, level: str, message: str, *args: Any) -> None:
        logger = self.logger
        method = getattr(logger, level, None) if logger is not None else None
        if callable(method):
            try:
                method(message, *args)
            except Exception:
                pass


__all__ = ["ActiveConcernRuntime"]
