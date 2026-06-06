# -*- coding: utf-8 -*-
"""
cortex/private_mind/surface_valve.py
====================================

SurfaceValve lọc InternalJudgment thành SurfaceCandidate/SurfaceImpulse rất nhỏ.

Luật: không leak raw internal JSON, không lộ private chain, không đem phán quyết
nội tâm ra đọc như biên bản tòa. Public chỉ nên thấy một bias/seed đã lọc.
"""

from __future__ import annotations

import re
from typing import Any

from .contracts import InternalJudgment, SurfaceCandidate, clamp01, compact_text


_INTERNAL_MARKERS = (
    "thoughtfragment",
    "internaljudgment",
    "privateconcern",
    "state_mutation",
    "state mutation",
    "raw json",
    "chain of thought",
    "evidence_ids",
    "ranked_hypotheses",
    "dominant_judgment",
)


class SurfaceValve:
    def __init__(
        self,
        *,
        min_usefulness: float = 0.58,
        min_confidence: float = 0.55,
        max_interrupt_cost: float = 0.48,
    ) -> None:
        self.min_usefulness = clamp01(min_usefulness)
        self.min_confidence = clamp01(min_confidence)
        self.max_interrupt_cost = clamp01(max_interrupt_cost)

    def filter(self, judgment: InternalJudgment | None) -> SurfaceCandidate | None:
        if judgment is None or judgment.surface_candidate is None:
            return None
        candidate = judgment.surface_candidate
        candidate = self._apply_public_surface_gate(candidate, judgment=judgment)
        if candidate is None:
            return None
        if candidate.usefulness < self.min_usefulness:
            return None
        if candidate.confidence < self.min_confidence:
            return None
        if candidate.interrupt_cost > self.max_interrupt_cost:
            return None
        if self._looks_private(candidate.topic_seed) or self._looks_private(candidate.reason):
            # Cắt về seed public-safe hơn nếu còn hypothesis đủ sạch.
            seed = self._safe_seed_from_judgment(judgment)
            if not seed:
                return None
            candidate = SurfaceCandidate(
                kind=candidate.kind,
                topic_seed=seed,
                usefulness=candidate.usefulness,
                confidence=candidate.confidence,
                interrupt_cost=candidate.interrupt_cost,
                evidence_ids=candidate.evidence_ids,
                reason="private_mind_filtered_seed",
                channel=candidate.channel,
                metadata={**candidate.metadata, "surface_valve_rewritten": True},
            )
        return candidate if candidate.allowed else None

    def to_surface_impulse(self, candidate: SurfaceCandidate | None) -> Any | None:
        """Chuyển SurfaceCandidate sang SurfaceImpulse nếu module tồn tại."""

        if candidate is None:
            return None
        metadata = dict(getattr(candidate, "metadata", {}) or {})
        has_public_anchor = self._has_public_anchor(candidate)
        family = compact_text(
            metadata.get("detected_semantic_family")
            or metadata.get("semantic_family")
            or "private_mind_continuity_filler",
            96,
        )
        try:
            from cortex.surface_arbiter import SurfaceImpulse
        except Exception:  # pragma: no cover - fallback import layout
            try:
                from ..surface_arbiter import SurfaceImpulse  # type: ignore
            except Exception:
                return candidate
        return SurfaceImpulse(
            kind=candidate.kind,
            source="private_mind",
            confidence=candidate.confidence,
            pressure=candidate.usefulness,
            score=clamp01(0.55 * candidate.confidence + 0.45 * candidate.usefulness),
            topic_seed=candidate.topic_seed,
            speech_act="technical_diagnosis",
            family=family,
            evidence=tuple(candidate.evidence_ids),
            reason=candidate.reason,
            focus_family="architecture",
            body_action="hold_focus" if has_public_anchor else "quiet_observe",
            missing_evidence_ids=not has_public_anchor,
            is_presence=False,
            should_surface=True,
            needs_external_evidence=not has_public_anchor,
            root_source="private_mind_loop",
            llm_contract=(
                "Do not expose raw private judgment or JSON; use only this public-safe topic seed."
                if has_public_anchor
                else "No public speech: private mind lacks a fresh public anchor; body-only at most."
            ),
            raw=candidate.to_dict(),
        )

    def _apply_public_surface_gate(self, candidate: SurfaceCandidate, *, judgment: InternalJudgment) -> SurfaceCandidate | None:
        metadata = dict(getattr(candidate, "metadata", {}) or {})
        source = str(metadata.get("source") or judgment.source or "").strip().lower()
        is_fallback = source == "fallback" or "deterministic" in source
        api_invalid_json = bool(metadata.get("api_invalid_json"))
        api_degraded = bool(metadata.get("api_degraded")) or api_invalid_json
        novelty = clamp01(metadata.get("novelty", 0.0))
        repetition = clamp01(metadata.get("repetition", 0.0))
        evidence_strength = clamp01(metadata.get("evidence_strength", 0.0))
        semantic_family = compact_text(str(metadata.get("semantic_family") or "private_mind_continuity_filler"), 96)
        has_public_anchor = self._has_public_anchor(candidate)
        semantic_family_recently_used = bool(metadata.get("semantic_family_recently_used"))

        if api_invalid_json:
            candidate = self._copy_candidate(
                candidate,
                confidence=min(candidate.confidence, 0.48),
                usefulness=min(candidate.usefulness, 0.42),
                channel="none",
                metadata={
                    **metadata,
                    "api_invalid_json": True,
                    "public_surface_allowed": False,
                    "surface_valve_reject": "api_invalid_json",
                    "semantic_family": semantic_family,
                },
            )
            return None

        if semantic_family == "private_mind_continuity_filler" and repetition > 0.75:
            return None

        public_allowed = bool(
            has_public_anchor
            and evidence_strength >= 0.45
            and novelty >= 0.25
            and repetition <= 0.65
            and not api_degraded
            and not semantic_family_recently_used
        )
        if not is_fallback and candidate.channel == "surface_arbiter":
            public_allowed = public_allowed or bool(has_public_anchor and not semantic_family_recently_used)

        merged_metadata = {
            **metadata,
            "semantic_family": semantic_family,
            "has_public_anchor": has_public_anchor,
            "public_surface_allowed": public_allowed,
            "api_degraded": api_degraded,
        }
        if public_allowed:
            return self._copy_candidate(candidate, metadata=merged_metadata)

        if candidate.usefulness >= self.min_usefulness and candidate.confidence >= self.min_confidence:
            return self._copy_candidate(
                candidate,
                channel="body_only",
                metadata={**merged_metadata, "surface_valve_body_only": True},
            )
        return None

    def _has_public_anchor(self, candidate: SurfaceCandidate) -> bool:
        metadata = dict(getattr(candidate, "metadata", {}) or {})
        try:
            public_anchor_count = int(metadata.get("public_anchor_count", 0) or 0)
        except Exception:
            public_anchor_count = 0
        if public_anchor_count > 0:
            return True
        haystack = " ".join(str(item or "") for item in (*tuple(candidate.evidence_ids or ()), candidate.topic_seed)).lower()
        markers = (
            "dossier.user.",
            "user_chat",
            "vision_fact",
            "screen_fact",
            "scene_evidence",
            "ev.active_window",
            "ev.active_app",
            "runtime_event",
        )
        return any(marker in haystack for marker in markers)

    def _copy_candidate(self, candidate: SurfaceCandidate, **updates: Any) -> SurfaceCandidate:
        data = candidate.to_dict()
        data.update(updates)
        if "metadata" in updates:
            data["metadata"] = dict(updates["metadata"] or {})
        return SurfaceCandidate.from_mapping(data)

    def _safe_seed_from_judgment(self, judgment: InternalJudgment) -> str:
        for hyp in judgment.ranked_hypotheses:
            text = compact_text(hyp.description or hyp.label, 260)
            if text and not self._looks_private(text):
                return text
        text = re.sub(r"\b(ThoughtFragment|InternalJudgment|PrivateConcern|StateMutation)\b", "private layer", judgment.dominant_judgment)
        return "" if self._looks_private(text) else compact_text(text, 260)

    def _looks_private(self, text: str) -> bool:
        hay = str(text or "").lower()
        if not hay:
            return False
        if "{" in hay or "}" in hay or "[" in hay or "]" in hay:
            return True
        return any(marker in hay for marker in _INTERNAL_MARKERS)
