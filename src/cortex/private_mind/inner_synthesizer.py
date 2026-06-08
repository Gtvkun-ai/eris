# -*- coding: utf-8 -*-
"""
cortex/private_mind/inner_synthesizer.py
=======================================

GemmaInnerSynthesizer gom ThoughtFragment thành InternalJudgment.

Vai trò đúng: thẩm phán nội tâm.
Vai trò sai: thợ viết caption cho đồng hồ biết buồn.

Nếu model adapter không sẵn sàng, synthesizer có deterministic fallback để runtime
vẫn có concern/mutation. API là gia tốc, không phải cái nạng triết học.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from .contracts import (
    EvidenceDossier,
    InternalJudgment,
    RankedHypothesis,
    StateMutation,
    SurfaceCandidate,
    ThoughtFragment,
    clamp01,
    compact_text,
)


class InnerSynthesizerModelAdapter(Protocol):
    def synthesize_judgment(self, dossier: EvidenceDossier, fragments: tuple[ThoughtFragment, ...]) -> Mapping[str, Any] | None:
        ...


class GemmaInnerSynthesizer:
    """Synthesize fragments thành phán quyết nội tâm."""

    def __init__(self, *, model_adapter: Any = None, min_fragments_for_model: int = 3) -> None:
        self.model_adapter = model_adapter
        self.min_fragments_for_model = max(1, int(min_fragments_for_model or 3))

    def synthesize(
        self,
        *,
        dossier: EvidenceDossier,
        fragments: tuple[ThoughtFragment, ...],
    ) -> InternalJudgment | None:
        strong = tuple(f for f in fragments if f.claim and f.score >= 0.32)
        if not strong:
            return None
        return self._try_model(dossier, strong)

    def _try_model(self, dossier: EvidenceDossier, fragments: tuple[ThoughtFragment, ...]) -> InternalJudgment | None:
        if self.model_adapter is None or len(fragments) < self.min_fragments_for_model:
            return None
        # Nếu là pool, dùng synthesis_adapter riêng để streak không bị fragment reset
        adapter = self.model_adapter
        synthesis_specific = getattr(adapter, "synthesis_adapter", None)
        if synthesis_specific is not None:
            adapter = synthesis_specific
        fn = getattr(adapter, "synthesize_judgment", None)
        if not callable(fn):
            return None
        try:
            raw = fn(dossier, fragments)
        except Exception:
            return None
        if not isinstance(raw, Mapping):
            return None
        judgment = InternalJudgment.from_mapping({"source": "gemma_inner_synthesizer", **dict(raw)})
        if not judgment.dominant_judgment or judgment.confidence < 0.25:
            return None
        # Model không được viện evidence ngoài dossier. Nếu có, cắt.
        allowed = set(dossier.evidence_ids)
        if allowed:
            judgment.evidence_ids = tuple(eid for eid in judgment.evidence_ids if eid in allowed) or dossier.evidence_ids[:12]
            for mutation in judgment.state_mutations:
                mutation.evidence_ids = tuple(eid for eid in mutation.evidence_ids if eid in allowed) or judgment.evidence_ids[:8]
        return judgment

    def _fallback(self, dossier: EvidenceDossier, fragments: tuple[ThoughtFragment, ...]) -> InternalJudgment | None:
        return None

    def _rank_hypotheses(self, fragments: tuple[ThoughtFragment, ...], evidence_ids: tuple[str, ...]) -> tuple[RankedHypothesis, ...]:
        candidates: list[RankedHypothesis] = []
        for fragment in fragments:
            candidates.extend(fragment.hypotheses)
        if not candidates:
            candidates = [
                RankedHypothesis(
                    label="nhận_thức_nền_chưa_đủ_sâu",
                    description="Nhận định mạnh nhất: nhận thức nền cảm thấy nông vì concern chưa được duy trì và judgment chưa tạo ra thay đổi hành vi.",
                    confidence=max(f.confidence for f in fragments),
                    pressure=max(f.pressure for f in fragments),
                    evidence_ids=evidence_ids,
                )
            ]
        merged: dict[str, RankedHypothesis] = {}
        for hyp in candidates:
            key = hyp.label.lower()
            old = merged.get(key)
            if old is None:
                merged[key] = hyp
            else:
                merged[key] = RankedHypothesis(
                    label=old.label,
                    description=old.description or hyp.description,
                    confidence=max(old.confidence * 0.96, hyp.confidence),
                    pressure=max(old.pressure * 0.94, hyp.pressure),
                    evidence_ids=tuple(dict.fromkeys((*old.evidence_ids, *hyp.evidence_ids)))[:16] or evidence_ids[:8],
                    rejected=old.rejected and hyp.rejected,
                    reason=old.reason or hyp.reason,
                )
        return tuple(sorted((h for h in merged.values() if not h.rejected), key=lambda h: h.score, reverse=True)[:8])

    def _rejected_hypotheses(self, fragments: tuple[ThoughtFragment, ...], evidence_ids: tuple[str, ...]) -> tuple[RankedHypothesis, ...]:
        rejected = [h for f in fragments for h in f.hypotheses if h.rejected]
        if not rejected:
            rejected = [
                RankedHypothesis(
                    label="gọi_api_nhiều_mà_không_có_mutation",
                    description="Chỉ tăng số lần gọi API mà không có concern/state mutation sẽ chỉ tạo thêm ghi chú nội tâm, không có tác động hành vi.",
                    confidence=0.78,
                    pressure=0.72,
                    evidence_ids=evidence_ids,
                    rejected=True,
                    reason="Tăng API call mà không đi kèm mutation là lãng phí.",
                )
            ]
        return tuple(sorted(rejected, key=lambda h: h.score, reverse=True)[:6])

    def _collect_mutations(self, fragments: tuple[ThoughtFragment, ...], evidence_ids: tuple[str, ...]) -> tuple[StateMutation, ...]:
        mutations: list[StateMutation] = []
        for fragment in fragments:
            for raw in tuple(fragment.metadata.get("state_mutations") or ()):  # type: ignore[arg-type]
                if isinstance(raw, Mapping):
                    mutation = StateMutation.from_mapping(raw)
                    if not mutation.evidence_ids:
                        mutation.evidence_ids = evidence_ids[:8]
                    mutations.append(mutation)
        if not any(m.target == "speech_bias" for m in mutations):
            mutations.append(
                StateMutation(
                    target="speech_bias",
                    operation="prefer",
                    value="chẩn_đoán_kiến_trúc_trực_tiếp",
                    confidence=0.74,
                    evidence_ids=evidence_ids[:8],
                    reason="Concern nội tâm chính là chiều sâu kiến trúc, không phải trấn an cảm xúc.",
                    priority=0.70,
                )
            )
        if not any(m.target == "private_concern" for m in mutations):
            mutations.append(
                StateMutation(
                    target="private_concern",
                    operation="merge",
                    value={"bias": "concern_must_persist_before_surface"},
                    confidence=0.70,
                    evidence_ids=evidence_ids[:8],
                    reason="Giữ concern sống để các tick sau không quên.",
                    priority=0.62,
                )
            )
        return tuple(sorted(mutations, key=lambda m: (m.priority, m.confidence), reverse=True)[:12])

    def _surface_candidate_if_useful(
        self,
        dossier: EvidenceDossier,
        fragments: tuple[ThoughtFragment, ...],
        *,
        confidence: float,
        pressure: float,
        evidence_ids: tuple[str, ...],
    ) -> SurfaceCandidate | None:
        wake = dossier.runtime_state.get("wake", {}) if isinstance(dossier.runtime_state, Mapping) else {}
        interrupt = clamp01(wake.get("interrupt_cost", 0.25) if isinstance(wake, Mapping) else 0.25)
        user_text_present = bool("".join(str(t.get("text") or "") for t in dossier.recent_user_turns).strip())
        metadata = dict(getattr(dossier, "metadata", {}) or {})
        api_status = self._adapter_api_status()
        api_invalid_json = bool(metadata.get("api_invalid_json")) or bool(api_status.get("api_invalid_json"))
        api_degraded = bool(metadata.get("api_degraded")) or bool(api_status.get("api_degraded"))
        usefulness = clamp01(0.42 + pressure * 0.34 + (0.18 if user_text_present else 0.0))
        candidate_confidence = confidence
        if api_invalid_json:
            usefulness = min(usefulness, 0.42)
            candidate_confidence = min(candidate_confidence, 0.48)
        if usefulness < 0.55 or confidence < 0.55 or interrupt > 0.60:
            return None
        top = fragments[0]
        seed = compact_text(top.claim, 260)
        return SurfaceCandidate(
            kind="private_mind_surface",
            topic_seed=seed,
            usefulness=usefulness,
            confidence=candidate_confidence,
            interrupt_cost=interrupt,
            evidence_ids=evidence_ids[:12],
            reason="Private judgment is useful enough to bias low-level surface, but raw judgment stays private.",
            metadata={
                "source": "fallback",
                "source_fragment": top.id,
                "novelty": clamp01(metadata.get("novelty", 0.0)),
                "repetition": clamp01(metadata.get("repetition", 0.0)),
                "has_recent_user_turn": bool(metadata.get("has_recent_user_turn", user_text_present)),
                "user_turn_age_sec": metadata.get("user_turn_age_sec"),
                "public_anchor_count": int(metadata.get("public_anchor_count", 0) or 0),
                "evidence_strength": clamp01(metadata.get("evidence_strength", 0.0)),
                "api_degraded": api_degraded,
                "api_invalid_json": api_invalid_json,
                "semantic_family": "private_mind_continuity_filler",
            },
        )

    def _adapter_api_status(self) -> dict[str, bool | str]:
        status_fn = getattr(self.model_adapter, "debug_status", None)
        if not callable(status_fn):
            return {"api_degraded": False, "api_invalid_json": False, "last_error": ""}
        try:
            status = status_fn()
        except Exception:
            return {"api_degraded": True, "api_invalid_json": False, "last_error": "debug_status_failed"}
        last_error = str(status.get("last_error", "") or "") if isinstance(status, Mapping) else ""
        return {
            "api_degraded": bool(last_error),
            "api_invalid_json": "invalid_json" in last_error,
            "last_error": last_error,
        }
