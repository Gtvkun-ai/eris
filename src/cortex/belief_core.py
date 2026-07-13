# -*- coding: utf-8 -*-
"""Evidence-linked belief candidate engine for canonical V3."""
from __future__ import annotations

import hashlib
from typing import Any

from runtime.canonical_cognition import Belief, BeliefReport, CanonicalMeaningReport


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _first(obj: Any, names: tuple[str, ...], default: Any = None) -> Any:
    for name in names:
        value = _get(obj, name, None)
        if value is not None and value != "":
            return value
    return default


def _summary(obj: Any) -> str:
    for name in ("claim", "description", "content", "text", "summary"):
        value = _get(obj, name, None)
        if value is not None and str(value).strip():
            return " ".join(str(value).split())
    return ""


def _confidence(obj: Any, default: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(_first(obj, ("confidence", "reliability"), default))))
    except Exception:
        return default


class BeliefCoreEngine:
    module_name = "belief_core"

    def evaluate(self, frame: Any, meaning: CanonicalMeaningReport, *, knowledge: Any = None) -> BeliefReport:
        active: list[Belief] = []
        candidates: list[Belief] = []
        rejected: list[Belief] = []
        contradictions: list[str] = []

        for ev in list(_get(frame, "evidence", []) or [])[:16]:
            claim = _summary(ev)
            if not claim:
                continue
            eid = str(_first(ev, ("id", "evidence_id"), "") or "")
            conf = _confidence(ev, 0.5)
            raw = str(_get(ev, "raw_or_inferred", "raw") or "raw") == "raw"
            tags = {str(x).lower() for x in (_get(ev, "tags", []) or [])}
            status = "active" if raw and conf >= 0.72 and "contradiction" not in tags else "tentative"
            belief = Belief(
                id=f"belief:{eid or hashlib.sha1(claim.encode('utf-8')).hexdigest()[:10]}",
                claim=claim,
                domain="user" if str(_get(ev, "source", "")) == "user_chat" else "world",
                confidence=conf,
                source_ids=[eid] if eid else [],
                status=status,
            )
            (active if status == "active" else candidates).append(belief)
            if "contradiction" in tags:
                contradictions.append(claim)

        for idx, item in enumerate(list(_get(knowledge, "candidate_beliefs", []) or [])[:8]):
            claim = str(_get(item, "claim", "") or "").strip()
            if not claim:
                continue
            source_ids = [str(x) for x in (_get(item, "source_ids", []) or []) if str(x).strip()]
            conf = _confidence(item, 0.62)
            status = "tentative" if source_ids else "rejected"
            belief = Belief(
                id=f"knowledge_belief:{hashlib.sha1((claim + str(idx)).encode('utf-8')).hexdigest()[:12]}",
                claim=claim,
                domain=str(_get(item, "domain", "world") or "world"),
                confidence=conf,
                source_ids=source_ids,
                status=status,
            )
            (candidates if source_ids else rejected).append(belief)

        contradictions.extend(str(x) for x in (_get(knowledge, "conflicts", []) or []) if str(x).strip())
        open_questions: list[str] = []
        if bool(_get(meaning, "needs_clarification", False)):
            open_questions.append("Ý định chính còn mơ hồ; chỉ hành động reversible hoặc clarification.")
        if str(_get(knowledge, "error", "") or "").strip() and str(_get(knowledge, "action", "")) in {"search_web", "search_memory"}:
            open_questions.append("Knowledge acquisition chưa có nguồn đủ chắc; không nâng belief thành active.")
        return BeliefReport(
            active_beliefs=active,
            candidate_beliefs=candidates,
            rejected_beliefs=rejected,
            contradictions=list(dict.fromkeys(contradictions)),
            open_questions=open_questions,
        )


__all__ = ["BeliefCoreEngine"]
