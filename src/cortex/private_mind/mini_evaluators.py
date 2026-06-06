# -*- coding: utf-8 -*-
"""
cortex/private_mind/mini_evaluators.py
======================================

Bốn mini-evaluator đáng gọi API:
- IntentEvaluator
- MemoryResonanceEvaluator
- RiskAndPermissionEvaluator
- FutureBiasEvaluator

Mỗi evaluator nhận cùng EvidenceDossier và trả ThoughtFragment. Chúng không được
trả lời user. Chúng không được tự commit memory. Chúng chỉ làm việc bẩn: nhìn
bằng chứng, nêu claim, gắn confidence/pressure. Vâng, nghĩ trước khi nói, một
ý tưởng cách mạng đối với phần mềm hội thoại.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol

from .contracts import EvidenceDossier, RankedHypothesis, ThoughtFragment, clamp01, compact_text


class MiniEvaluatorModelAdapter(Protocol):
    def evaluate_fragment(self, evaluator_name: str, dossier: EvidenceDossier) -> Mapping[str, Any] | None:
        ...


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _all_user_text(dossier: EvidenceDossier) -> str:
    return "\n".join(str(turn.get("text") or "") for turn in dossier.recent_user_turns)


def _evidence_ids(dossier: EvidenceDossier, *fallback: str) -> tuple[str, ...]:
    ids = list(dossier.evidence_ids[:16])
    for item in fallback:
        if item and item not in ids:
            ids.append(item)
    return tuple(ids[:16])


def _from_model_or_none(adapter: Any, evaluator_name: str, dossier: EvidenceDossier) -> ThoughtFragment | None:
    if adapter is None:
        return None
    fn = getattr(adapter, "evaluate_fragment", None)
    if not callable(fn):
        return None
    try:
        raw = fn(evaluator_name, dossier)
    except Exception:
        return None
    if not isinstance(raw, Mapping):
        return None
    fragment = ThoughtFragment.from_mapping({"source": evaluator_name, **dict(raw)})
    if not fragment.claim or fragment.confidence < 0.20:
        return None
    return fragment


@dataclass(slots=True)
class BaseMiniEvaluator:
    name: str
    model_adapter: Any = None
    min_model_confidence: float = 0.35

    def evaluate(self, dossier: EvidenceDossier) -> ThoughtFragment:
        model_fragment = _from_model_or_none(self.model_adapter, self.name, dossier)
        if model_fragment is not None and model_fragment.confidence >= self.min_model_confidence:
            return model_fragment
        return self.evaluate_rules(dossier)

    def evaluate_rules(self, dossier: EvidenceDossier) -> ThoughtFragment:  # pragma: no cover - abstract-ish
        return ThoughtFragment(source=self.name, claim="No strong private evaluation.", confidence=0.25, pressure=0.1)


class IntentEvaluator(BaseMiniEvaluator):
    def __init__(self, *, model_adapter: Any = None) -> None:
        super().__init__("intent_evaluator", model_adapter=model_adapter)

    def evaluate_rules(self, dossier: EvidenceDossier) -> ThoughtFragment:
        text = _norm(_all_user_text(dossier))
        wants_full_phase = any(key in text for key in ("full phase", "phase a", "phase b", "phase c", "phase d", "phase e", "làm full"))
        wants_architecture_rewrite = any(key in text for key in ("privateconcern", "statemutationbus", "surfacevalve", "mini-evaluator", "gemma inner", "đập lại"))
        wants_files = any(key in text for key in ("gửi file", "file có ghi chú", "sửa file", "vá", "copy"))
        confidence = 0.92 if wants_architecture_rewrite and wants_files else 0.72 if wants_architecture_rewrite else 0.48
        pressure = 0.88 if wants_full_phase and wants_files else 0.66 if wants_architecture_rewrite else 0.34
        claim = (
            "User wants a concrete architecture patch implementing PrivateConcern, mini-evaluators, inner synthesis, mutation bus and surface valve; not another decorative API layer."
            if wants_architecture_rewrite
            else "User likely expects practical private cognition work rather than broad explanation."
        )
        hypotheses = (
            RankedHypothesis(
                label="implementation_request",
                description="The user asks to edit the repo and send files, with Vietnamese comments.",
                confidence=confidence,
                pressure=pressure,
                evidence_ids=_evidence_ids(dossier),
            ),
            RankedHypothesis(
                label="discussion_only",
                description="Could be asking for architecture advice only, but upload + send-file wording makes this weak.",
                confidence=0.12 if wants_files else 0.28,
                pressure=0.12,
                evidence_ids=_evidence_ids(dossier),
                rejected=wants_files,
                reason="User supplied src.zip and asks to send patched files.",
            ),
        )
        return ThoughtFragment(
            source=self.name,
            claim=claim,
            confidence=confidence,
            evidence_ids=_evidence_ids(dossier),
            pressure=pressure,
            suggested_question="Which state mutations prove future behavior changed instead of merely logging inner thoughts?",
            hypotheses=hypotheses,
            metadata={
                "theme": "user demands real private background cognition architecture",
                "future_biases": ["prefer concrete repo patch over abstract reassurance"],
            },
        )


class MemoryResonanceEvaluator(BaseMiniEvaluator):
    def __init__(self, *, model_adapter: Any = None) -> None:
        super().__init__("memory_resonance_evaluator", model_adapter=model_adapter)

    def evaluate_rules(self, dossier: EvidenceDossier) -> ThoughtFragment:
        text = _norm(_all_user_text(dossier))
        memory_blob = _norm("\n".join(str(hit.get("text") or hit.get("summary") or "") for hit in dossier.memory_hits))
        repair_blob = _norm("\n".join(str(r.get("summary") or "") for r in dossier.prior_repair_failures))
        shallow_terms = ("vô dụng", "shallow", "nông", "đàn vẹt", "tốn key", "đồng hồ", "suy nghĩ ngầm", "state mutation")
        repeated_rejection = sum(1 for term in shallow_terms if term in text or term in memory_blob or term in repair_blob)
        confidence = clamp01(0.45 + repeated_rejection * 0.09)
        pressure = clamp01(0.42 + repeated_rejection * 0.08)
        claim = (
            "User repeatedly rejects shallow decorative cognition patches; memory resonance favors stateful concern and mutation effects over prettier thought logs."
            if repeated_rejection >= 2
            else "Memory context weakly suggests the user cares about background cognition being stateful rather than decorative."
        )
        return ThoughtFragment(
            source=self.name,
            claim=claim,
            confidence=confidence,
            evidence_ids=_evidence_ids(dossier, *[str(hit.get("evidence_id") or "") for hit in dossier.memory_hits[:4]]),
            pressure=pressure,
            suggested_question="What runtime state changed after the private judgment?",
            hypotheses=(
                RankedHypothesis(
                    label="stateful_cognition_needed",
                    description="The recurring concern is not quantity of API calls but whether private evaluations persist and bias future decisions.",
                    confidence=confidence,
                    pressure=pressure,
                    evidence_ids=_evidence_ids(dossier),
                ),
                RankedHypothesis(
                    label="more_llm_calls_needed",
                    description="More API calls alone would not satisfy the repeated complaint.",
                    confidence=0.18,
                    pressure=0.18,
                    evidence_ids=_evidence_ids(dossier),
                    rejected=True,
                    reason="User explicitly warns that many API workers create parrots wasting keys.",
                ),
            ),
            metadata={
                "theme": "user rejects decorative cognition and wants stateful private concerns",
                "future_biases": ["do not equate more API calls with deeper cognition"],
            },
        )


class RiskAndPermissionEvaluator(BaseMiniEvaluator):
    def __init__(self, *, model_adapter: Any = None) -> None:
        super().__init__("risk_and_permission_evaluator", model_adapter=model_adapter)

    def evaluate_rules(self, dossier: EvidenceDossier) -> ThoughtFragment:
        text = _norm(_all_user_text(dossier))
        mentions_api = any(k in text for k in ("api", "gemma", "key", "gọi"))
        mentions_private = any(k in text for k in ("private", "nội tâm", "suy nghĩ ngầm", "raw internal", "json"))
        leak_risk = 0.72 if mentions_private else 0.38
        cost_risk = 0.64 if mentions_api else 0.25
        confidence = 0.82 if mentions_private or mentions_api else 0.55
        pressure = max(leak_risk, cost_risk)
        claim = "Private mind must keep raw fragments/judgments private, expose only filtered surface candidates, and avoid API fan-out without concern/state mutation gates."
        return ThoughtFragment(
            source=self.name,
            claim=claim,
            confidence=confidence,
            evidence_ids=_evidence_ids(dossier),
            pressure=pressure,
            suggested_question="Which fields are public-safe and which must remain private-only?",
            hypotheses=(
                RankedHypothesis(
                    label="private_chain_leak_risk",
                    description="InternalJudgment and raw ThoughtFragments must not be surfaced as JSON or chain-of-thought-like text.",
                    confidence=leak_risk,
                    pressure=pressure,
                    evidence_ids=_evidence_ids(dossier),
                ),
                RankedHypothesis(
                    label="api_budget_risk",
                    description="Only four evaluators and the inner synthesizer deserve API budget; rules should fallback when API is unavailable.",
                    confidence=cost_risk,
                    pressure=cost_risk,
                    evidence_ids=_evidence_ids(dossier),
                ),
            ),
            metadata={
                "theme": "private mind needs permission and leak control",
                "future_biases": ["filter internal judgments through SurfaceValve before public speech"],
            },
        )


class FutureBiasEvaluator(BaseMiniEvaluator):
    def __init__(self, *, model_adapter: Any = None) -> None:
        super().__init__("future_bias_evaluator", model_adapter=model_adapter)

    def evaluate_rules(self, dossier: EvidenceDossier) -> ThoughtFragment:
        text = _norm(_all_user_text(dossier))
        architecture_terms = sum(1 for k in ("privateconcern", "statemutation", "surfacevalve", "evidence dossier", "mini-evaluator", "inner synthesizer") if k in text)
        confidence = clamp01(0.55 + architecture_terms * 0.07)
        pressure = clamp01(0.50 + architecture_terms * 0.08)
        mutations = [
            {
                "target": "speech_bias",
                "operation": "prefer",
                "value": "direct_architecture_diagnosis_over_reassurance",
                "confidence": confidence,
                "evidence_ids": list(_evidence_ids(dossier)),
                "reason": "User asks for concrete architecture patch, not comfort or aesthetic cognition.",
                "priority": pressure,
            },
            {
                "target": "agenda_stack",
                "operation": "append",
                "value": {
                    "kind": "technical_followup",
                    "summary": "Verify private_mind mutations actually affect future surface/arbitration behavior.",
                    "speech_value": 0.18,
                    "ttl_seconds": 7200,
                },
                "confidence": confidence,
                "evidence_ids": list(_evidence_ids(dossier)),
                "reason": "Private cognition should leave an actionable internal agenda item.",
                "priority": pressure,
            },
            {
                "target": "thought_stream_pressure",
                "operation": "increase",
                "value": {"reason": "private_concern_active", "amount": 0.12},
                "confidence": confidence,
                "evidence_ids": list(_evidence_ids(dossier)),
                "reason": "Open concerns should bias future internal review pressure.",
                "priority": 0.58,
            },
        ]
        return ThoughtFragment(
            source=self.name,
            claim="Future behavior should be biased toward direct architecture diagnosis, concern persistence, and mutation-backed learning rather than generic reassurance.",
            confidence=confidence,
            evidence_ids=_evidence_ids(dossier),
            pressure=pressure,
            suggested_question="Did the next response/action reflect the stored bias?",
            hypotheses=(
                RankedHypothesis(
                    label="mutation_bus_required",
                    description="A StateMutationBus is necessary so internal judgments affect agenda, speech bias and surface queue.",
                    confidence=confidence,
                    pressure=pressure,
                    evidence_ids=_evidence_ids(dossier),
                ),
            ),
            metadata={
                "theme": "private judgments must mutate future behavior",
                "state_mutations": mutations,
                "future_biases": ["prefer mutation-backed learning over private diary logging"],
            },
        )


class MiniEvaluatorPipeline:
    """Chạy đúng bốn evaluator đáng tiền.

    Không tự động thêm evaluator thứ năm vì nghe ngầu. Ngầu không phải requirement.
    """

    def __init__(self, *, model_adapter: Any = None, evaluators: Iterable[BaseMiniEvaluator] | None = None) -> None:
        self.model_adapter = model_adapter
        self.evaluators = tuple(
            evaluators
            if evaluators is not None
            else (
                IntentEvaluator(model_adapter=model_adapter),
                MemoryResonanceEvaluator(model_adapter=model_adapter),
                RiskAndPermissionEvaluator(model_adapter=model_adapter),
                FutureBiasEvaluator(model_adapter=model_adapter),
            )
        )

    def evaluate(self, dossier: EvidenceDossier) -> tuple[ThoughtFragment, ...]:
        fragments: list[ThoughtFragment] = []
        for evaluator in self.evaluators:
            try:
                fragment = evaluator.evaluate(dossier)
            except Exception as exc:
                fragment = ThoughtFragment(
                    source=getattr(evaluator, "name", evaluator.__class__.__name__),
                    claim=f"Evaluator failed safely: {type(exc).__name__}",
                    confidence=0.2,
                    pressure=0.1,
                    evidence_ids=dossier.evidence_ids[:8],
                    metadata={"error": str(exc)},
                )
            if fragment.claim and fragment.score >= 0.24:
                fragments.append(fragment)
        # Sort để synthesizer nhìn mảnh mạnh trước. Thứ tự cũng là một loại bias.
        return tuple(sorted(fragments, key=lambda f: f.score, reverse=True)[:8])
