# -*- coding: utf-8 -*-
"""Bounded Cognitive Workspace cho một lượt chat.

Workspace không giữ state lâu dài và không viết câu public. Nó biến projection
thành các candidate có evidence, cho chúng cạnh tranh theo từng key, phát hiện
xung đột, chống đếm evidence lặp và chỉ xuất một brief nhỏ cho planner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from core.cognition import (
    CognitiveFrame,
    DiscourseProjection,
    EpistemicProjection,
    PreResponseCognitiveBrief,
    ProjectionFailure,
    SemanticProjection,
    SocialProjection,
    StyleProjection,
)


@dataclass(frozen=True, slots=True)
class WorkspaceBudget:
    max_candidates: int = 24
    max_evidence_refs: int = 10
    max_avoid_moves: int = 8
    max_notes: int = 6
    discourse_evidence_quota: int = 3
    semantic_evidence_quota: int = 2
    epistemic_evidence_quota: int = 2
    social_evidence_quota: int = 2
    style_evidence_quota: int = 1


@dataclass(frozen=True, slots=True)
class WorkspaceCandidate:
    key: str
    value: str
    lane: str
    confidence: float
    ambiguity: float
    relevance: float
    urgency: float
    authority: float
    evidence_ids: tuple[str, ...]
    source_module: str


@dataclass(frozen=True, slots=True)
class WorkspaceDecision:
    candidate: WorkspaceCandidate
    score: float
    margin: float
    conflict: str = ""


class CognitiveWorkspace:
    def __init__(self, budget: WorkspaceBudget | None = None) -> None:
        self.budget = budget or WorkspaceBudget()

    @staticmethod
    def _unique(values: Iterable[str], limit: int) -> tuple[str, ...]:
        result: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in result:
                result.append(text)
            if len(result) >= limit:
                break
        return tuple(result)

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    def _evidence_quality(
        self,
        candidate: WorkspaceCandidate,
        evidence_index: Mapping[str, object],
    ) -> tuple[float, float]:
        refs = tuple(dict.fromkeys(candidate.evidence_ids))
        if not refs:
            return 0.25, 0.0
        valid = [evidence_index[item] for item in refs if item in evidence_index]
        coverage = len(valid) / len(refs)
        if not valid:
            return 0.0, coverage
        quality = sum(float(getattr(item, "quality", 0.0) or 0.0) for item in valid) / len(valid)
        return self._clamp01(quality), self._clamp01(coverage)

    def _score(self, candidate: WorkspaceCandidate, evidence_index: Mapping[str, object]) -> tuple[float, float]:
        evidence_quality, coverage = self._evidence_quality(candidate, evidence_index)
        support = (
            0.48
            + 0.18 * candidate.relevance
            + 0.14 * candidate.urgency
            + 0.12 * evidence_quality
            + 0.08 * coverage
        )
        ambiguity_penalty = 1.0 - 0.58 * self._clamp01(candidate.ambiguity)
        score = candidate.confidence * candidate.authority * support * ambiguity_penalty
        return self._clamp01(score), coverage

    def _select(
        self,
        candidates: Sequence[WorkspaceCandidate],
        evidence_index: Mapping[str, object],
    ) -> tuple[dict[str, WorkspaceDecision], tuple[str, ...], float, float]:
        grouped: dict[str, list[tuple[WorkspaceCandidate, float, float]]] = {}
        for candidate in candidates[: self.budget.max_candidates]:
            score, coverage = self._score(candidate, evidence_index)
            grouped.setdefault(candidate.key, []).append((candidate, score, coverage))

        decisions: dict[str, WorkspaceDecision] = {}
        conflicts: list[str] = []
        margins: list[float] = []
        coverages: list[float] = []
        for key, entries in grouped.items():
            entries.sort(key=lambda item: (item[1], item[0].authority, item[0].confidence), reverse=True)
            winner, score, coverage = entries[0]
            second_score = entries[1][1] if len(entries) > 1 else 0.0
            margin = max(0.0, score - second_score)
            conflict = ""
            if len(entries) > 1:
                runner = entries[1][0]
                if runner.value != winner.value and second_score >= 0.38:
                    conflict = f"{key}:{winner.value}<->{runner.value}"
                    conflicts.append(conflict)
            decisions[key] = WorkspaceDecision(winner, score, margin, conflict)
            margins.append(margin if len(entries) > 1 else score)
            coverages.append(coverage)
        return (
            decisions,
            self._unique(conflicts, 8),
            min(margins) if margins else 0.0,
            sum(coverages) / len(coverages) if coverages else 0.0,
        )

    @staticmethod
    def _semantic_move(semantic: SemanticProjection) -> str:
        if semantic.user_act == "continuation_bid":
            return "self_elaborate"
        if semantic.user_act == "style_criticism":
            return "repair_previous_response"
        if semantic.user_act == "close_topic":
            return "acknowledge_close"
        if semantic.action_requested:
            return "execute_requested_action"
        if semantic.user_act == "greeting":
            return "greet"
        if semantic.literal_question:
            return "answer"
        return "respond_in_context"

    def _build_candidates(
        self,
        *,
        discourse: DiscourseProjection,
        semantic: SemanticProjection,
        epistemic: EpistemicProjection,
        social: SocialProjection,
        style: StyleProjection,
    ) -> tuple[WorkspaceCandidate, ...]:
        candidates: list[WorkspaceCandidate] = [
            WorkspaceCandidate(
                "discourse_relation", discourse.relation, "discourse", discourse.confidence,
                discourse.ambiguity, 1.0, 0.82, 1.0, discourse.evidence_ids, "discourse",
            ),
            WorkspaceCandidate(
                "ambiguity_owner", discourse.ambiguity_owner, "discourse", discourse.confidence,
                discourse.ambiguity, 1.0, 0.90, 1.0, discourse.evidence_ids, "discourse",
            ),
            WorkspaceCandidate(
                "response_move", discourse.expected_next_move or "answer", "discourse", discourse.confidence,
                discourse.ambiguity, 1.0, 0.96 if discourse.ambiguity_owner == "assistant" else 0.78,
                1.08 if discourse.ambiguity_owner == "assistant" else 1.0,
                discourse.evidence_ids, "discourse",
            ),
            WorkspaceCandidate(
                "response_move", self._semantic_move(semantic), "semantic", semantic.confidence,
                semantic.ambiguity, 0.92, 0.70, 0.86, semantic.evidence_ids, "semantic",
            ),
            WorkspaceCandidate(
                "primary_goal", semantic.task_goal, "semantic", semantic.confidence,
                semantic.ambiguity, 1.0, 0.76, 1.0, semantic.evidence_ids, "semantic",
            ),
            WorkspaceCandidate(
                "user_act", semantic.user_act, "semantic", semantic.confidence,
                semantic.ambiguity, 0.92, 0.62, 1.0, semantic.evidence_ids, "semantic",
            ),
            WorkspaceCandidate(
                "grounding_scope", ",".join(epistemic.grounding_scope), "epistemic", epistemic.confidence,
                epistemic.uncertainty, 0.94, 0.84 if epistemic.missing_evidence else 0.58,
                1.0, epistemic.evidence_ids, "epistemic",
            ),
            WorkspaceCandidate(
                "user_posture", social.user_posture, "social", social.confidence,
                social.ambiguity, 0.72, social.relational_stakes, 0.88, social.evidence_ids, "social",
            ),
            WorkspaceCandidate(
                "delivery", style.delivery, "style", style.confidence,
                social.ambiguity * 0.35, 0.70, 0.52, 0.82, style.evidence_ids, "style",
            ),
        ]
        if social.repair_pressure >= 0.65:
            candidates.append(
                WorkspaceCandidate(
                    "response_move", "repair_previous_response", "social", social.confidence,
                    social.ambiguity, 0.86, social.repair_pressure, 0.90,
                    social.evidence_ids, "social",
                )
            )
        return tuple(candidates)

    def _select_evidence(
        self,
        decisions: Mapping[str, WorkspaceDecision],
        evidence_index: Mapping[str, object],
    ) -> tuple[str, ...]:
        quota = {
            "discourse": self.budget.discourse_evidence_quota,
            "semantic": self.budget.semantic_evidence_quota,
            "epistemic": self.budget.epistemic_evidence_quota,
            "social": self.budget.social_evidence_quota,
            "style": self.budget.style_evidence_quota,
        }
        lane_refs: dict[str, list[str]] = {key: [] for key in quota}
        ordered = sorted(decisions.values(), key=lambda item: item.score, reverse=True)
        for decision in ordered:
            lane = decision.candidate.lane
            bucket = lane_refs.setdefault(lane, [])
            for evidence_id in decision.candidate.evidence_ids:
                if evidence_id in evidence_index and evidence_id not in bucket:
                    bucket.append(evidence_id)
                if len(bucket) >= quota.get(lane, 1):
                    break
        flattened: list[str] = []
        for lane in ("discourse", "semantic", "epistemic", "social", "style"):
            flattened.extend(lane_refs.get(lane, ()))
        return self._unique(flattened, self.budget.max_evidence_refs)

    def compile(
        self,
        *,
        frame: CognitiveFrame,
        discourse: DiscourseProjection,
        semantic: SemanticProjection,
        epistemic: EpistemicProjection,
        social: SocialProjection,
        style: StyleProjection,
        failures: Sequence[ProjectionFailure] = (),
    ) -> PreResponseCognitiveBrief:
        evidence_index = frame.evidence_by_id()
        candidates = self._build_candidates(
            discourse=discourse,
            semantic=semantic,
            epistemic=epistemic,
            social=social,
            style=style,
        )
        decisions, conflicts, decision_margin, candidate_coverage = self._select(candidates, evidence_index)

        def value(key: str, default: str) -> str:
            decision = decisions.get(key)
            return decision.candidate.value if decision is not None else default

        notes: list[str] = []
        if value("ambiguity_owner", discourse.ambiguity_owner) == "assistant":
            notes.append("ERIS must resolve ambiguity created by her own previous wording before asking anything broad.")
        if epistemic.overread_risk >= 0.40:
            notes.append("Keep social inference tentative; posture is not a fact about the user.")
        if epistemic.missing_evidence:
            notes.append("Do not claim missing mechanical or external evidence as completed fact.")
        if discourse.open_loop:
            notes.append("Use the immediately previous ERIS turn as the active open loop.")
        if conflicts:
            notes.append("Specialists disagreed; follow the selected move but keep interpretation narrow.")
        if failures:
            notes.append("One or more specialists degraded; do not turn weak inference into a hard claim.")

        critical = [
            decisions[key].score
            for key in ("discourse_relation", "ambiguity_owner", "response_move", "primary_goal", "user_act")
            if key in decisions
        ]
        confidence = sum(critical) / len(critical) if critical else 0.35
        evidence_ids = self._select_evidence(decisions, evidence_index)
        evidence_coverage = min(
            candidate_coverage,
            len(evidence_ids) / max(1, len({ref for item in candidates for ref in item.evidence_ids})),
        )
        failure_penalty = min(0.30, len(failures) * 0.08)
        conflict_penalty = min(0.18, len(conflicts) * 0.06)
        confidence = self._clamp01(confidence - failure_penalty - conflict_penalty)
        ambiguity = max(
            discourse.ambiguity * 0.62,
            semantic.ambiguity * 0.40,
            social.ambiguity * 0.28,
            epistemic.uncertainty * 0.42,
            0.58 if conflicts and decision_margin < 0.12 else 0.0,
            0.62 if any(item.module == "discourse" for item in failures) else 0.0,
        )
        needs_deep_inference = bool(
            ambiguity >= 0.56
            or (conflicts and decision_margin < 0.14)
            or any(item.module in {"discourse", "semantic"} for item in failures)
        )
        degraded_modules = self._unique((item.module for item in failures), 8)

        return PreResponseCognitiveBrief(
            trace_id=frame.trace_id,
            primary_goal=value("primary_goal", semantic.task_goal or "respond_to_current_turn"),
            discourse_relation=value("discourse_relation", discourse.relation),
            ambiguity_owner=value("ambiguity_owner", discourse.ambiguity_owner),
            response_move=value("response_move", discourse.expected_next_move or "answer"),
            user_act=value("user_act", semantic.user_act),
            user_posture=value("user_posture", social.user_posture),
            assistant_fault_probability=discourse.assistant_fault_probability,
            grounding_scope=epistemic.grounding_scope,
            missing_evidence=epistemic.missing_evidence,
            delivery=value("delivery", style.delivery),
            avoid_moves=self._unique(style.avoid_moves, self.budget.max_avoid_moves),
            confidence=confidence,
            ambiguity=self._clamp01(ambiguity),
            decision_margin=self._clamp01(decision_margin),
            evidence_coverage=self._clamp01(evidence_coverage),
            needs_deep_inference=needs_deep_inference,
            evidence_ids=evidence_ids,
            degraded_modules=degraded_modules,
            conflicts=conflicts,
            notes=self._unique(notes, self.budget.max_notes),
        )


__all__ = [
    "CognitiveWorkspace",
    "WorkspaceBudget",
    "WorkspaceCandidate",
    "WorkspaceDecision",
]
