"""Pure state transitions for bounded pedagogical conversations."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from runtime.pedagogical_contracts import (
    ComprehensionState,
    TeachingChunk,
    TeachingDirective,
    TeachingEpisode,
    TeachingPlan,
    TeachingReceipt,
)


ActionKind = Literal[
    "answer_user", "teach_chunk", "repair", "probe", "advance", "wait", "complete", "abandon",
]
AUTONOMOUS_CHUNK_LIMIT = 2
REPAIR_LIMIT = 1
STALL_LIMIT = 2
EPISODE_SECONDS = 10 * 60
MASTERY_INCREMENT = 0.35


@dataclass(frozen=True, slots=True)
class ControllerAction:
    kind: ActionKind
    reason: str
    directive: TeachingDirective | None = None


@dataclass(frozen=True, slots=True)
class ControllerResult:
    episode: TeachingEpisode
    action: ControllerAction
    evidence_codes: tuple[str, ...] = ()


def _chunk_for(episode: TeachingEpisode, concept_id: str | None = None) -> TeachingChunk:
    concept = next((item for item in episode.concepts if item.concept_id == concept_id), episode.concepts[0])
    return TeachingChunk(
        chunk_id=f"{concept.concept_id}:r{episode.plan_revision}",
        concept_id=concept.concept_id,
        objective=concept.objective or concept.description,
        claim=concept.description,
        max_ideas=2,
        max_sentences=4,
    )


def _directive(episode: TeachingEpisode) -> TeachingDirective:
    chunk = episode.pending_chunk or _chunk_for(episode, episode.comprehension.current_concept_id)
    return TeachingDirective(
        episode_id=episode.episode_id,
        plan_revision=episode.plan_revision,
        chunk_id=chunk.chunk_id,
        global_goal=episode.global_goal,
        current_objective=chunk.objective,
        claim=chunk.claim,
        contrast=chunk.contrast,
        example_policy=chunk.example_policy,
        max_ideas=chunk.max_ideas,
        max_sentences=chunk.max_sentences,
        allow_question=True,
        stop_after_chunk=True,
        allow_autonomous_resume=episode.autonomous_chunks_used < AUTONOMOUS_CHUNK_LIMIT,
    )


def _action(kind: ActionKind, reason: str, episode: TeachingEpisode, *, directive: bool = False) -> ControllerAction:
    return ControllerAction(kind, reason, _directive(episode) if directive else None)


def start_episode(plan: TeachingPlan, now: float) -> TeachingEpisode:
    """Create a ready episode with a deterministic initial teaching chunk."""
    first = plan.concepts[0]
    episode = TeachingEpisode.new(
        episode_id=f"teaching:{first.concept_id}:{int(now)}",
        topic_key=first.concept_id,
        global_goal=plan.global_goal,
        concepts=plan.concepts,
        now=now,
        expires_at=now + EPISODE_SECONDS,
    )
    current = ComprehensionState(current_concept_id=first.concept_id)
    return replace(episode, status="ready", comprehension=current, pending_chunk=_chunk_for(episode, first.concept_id))


def expire_if_needed(episode: TeachingEpisode, *, now: float) -> TeachingEpisode:
    if episode.status not in {"completed", "abandoned", "expired"} and now >= episode.expires_at:
        return replace(episode, status="expired")
    return episode


def _next_concept_id(episode: TeachingEpisode) -> str | None:
    current = episode.comprehension.current_concept_id
    for index, concept in enumerate(episode.concepts):
        if concept.concept_id == current:
            return episode.concepts[index + 1].concept_id if index + 1 < len(episode.concepts) else None
    return None


def select_next_action(episode: TeachingEpisode, *, now: float) -> ControllerAction:
    episode = expire_if_needed(episode, now=now)
    if episode.status == "completed":
        return _action("complete", "all_concepts_mastered", episode)
    if episode.status in {"abandoned", "expired", "failed"}:
        return _action("abandon", "episode_expired" if episode.status == "expired" else "episode_unavailable", episode)
    # Selecting another autonomous action after one recorded stall would create
    # the second consecutive stall, so yield the floor before doing so.
    if episode.consecutive_stalls >= STALL_LIMIT - 1:
        return _action("wait", "stall_limit", episode)
    if episode.autonomous_chunks_used >= AUTONOMOUS_CHUNK_LIMIT:
        return _action("wait", "autonomous_budget_exhausted", episode)
    if episode.status == "repairing":
        if episode.repair_attempts >= REPAIR_LIMIT:
            return _action("wait", "repair_limit", episode)
        return _action("repair", "candidate_misconception", episode, directive=True)
    if episode.status == "speaking":
        return _action("wait", "audio_in_progress", episode)
    if episode.status in {"waiting_user", "observing", "dwelling"}:
        return _action("probe", "awaiting_demonstration", episode, directive=True)
    if episode.comprehension.estimated_mastery >= 0.8 and _next_concept_id(episode) is None:
        return _action("complete", "mastery_threshold", episode)
    return _action("teach_chunk", "current_concept_ready", episode, directive=True)


def observe_user_turn(
    episode: TeachingEpisode, user_text: str, *, evidence: tuple[str, ...], now: float,
) -> ControllerResult:
    episode = expire_if_needed(episode, now=now)
    if episode.status == "expired":
        return ControllerResult(episode, _action("abandon", "episode_expired", episode), ("episode_expired",))

    supplied = {str(code) for code in evidence}
    normalized = user_text.strip().casefold()
    codes: list[str] = []
    acknowledgement = not normalized or normalized in {"ok", "ừ", "uh", "hmm"} or "hiểu rồi" in normalized
    if acknowledgement:
        codes.append("silence" if not normalized else "self_report_understood")
    if "topic_change" in supplied:
        codes.append("topic_change")

    if "eris_corrected" in supplied:
        updated = replace(episode, status="repairing", consecutive_stalls=0)
        codes.append("eris_corrected")
        return ControllerResult(updated, select_next_action(updated, now=now), tuple(codes))

    if "misconception_assertion" in supplied:
        updated = replace(episode, status="repairing", consecutive_stalls=0)
        codes.append("candidate_misconception")
        return ControllerResult(updated, select_next_action(updated, now=now), tuple(codes))

    if "focused_question" in supplied:
        state = replace(episode.comprehension, confidence=max(0.0, episode.comprehension.confidence - 0.2))
        updated = replace(episode, status="waiting_user", comprehension=state, consecutive_stalls=episode.consecutive_stalls + 1)
        codes.append("repeated_focused_question")
        return ControllerResult(updated, select_next_action(updated, now=now), tuple(codes))

    if not acknowledgement and "topic_change" not in supplied and {"user_paraphrase", "user_application"} & supplied:
        state = replace(
            episode.comprehension,
            estimated_mastery=min(1.0, episode.comprehension.estimated_mastery + MASTERY_INCREMENT),
            confidence=min(1.0, episode.comprehension.confidence + 0.2),
        )
        next_id = _next_concept_id(episode)
        if next_id is None:
            updated = replace(episode, status="completed", comprehension=state, autonomous_chunks_used=0, consecutive_stalls=0)
        else:
            state = replace(state, current_concept_id=next_id)
            updated = replace(
                episode, status="ready", comprehension=state, pending_chunk=_chunk_for(episode, next_id),
                autonomous_chunks_used=0, consecutive_stalls=0,
            )
        codes.append("demonstrated_understanding")
        return ControllerResult(updated, _action("complete", "all_concepts_mastered", updated) if updated.status == "completed"
                                else _action("advance", "demonstrated_understanding", updated), tuple(codes))

    updated = replace(episode, status="waiting_user") if acknowledgement else episode
    return ControllerResult(updated, select_next_action(updated, now=now), tuple(codes))


def note_public_commit(episode: TeachingEpisode, receipt: TeachingReceipt) -> TeachingEpisode:
    """Accept a successful receipt only for the current pending chunk."""
    chunk = episode.pending_chunk
    if (
        chunk is None
        or episode.status not in {"ready", "repairing"}
        or not receipt.successful
        or receipt.episode_id != episode.episode_id
        or receipt.plan_revision != episode.plan_revision
        or receipt.chunk_id != chunk.chunk_id
    ):
        return episode
    if episode.status == "repairing":
        return replace(episode, status="speaking", repair_attempts=episode.repair_attempts + 1)
    return replace(episode, status="speaking", autonomous_chunks_used=episode.autonomous_chunks_used + 1)


def note_audio_finished(episode: TeachingEpisode, *, now: float) -> TeachingEpisode:
    episode = expire_if_needed(episode, now=now)
    if episode.status == "speaking":
        return replace(episode, status="waiting_user")
    return episode


__all__ = [
    "ControllerAction", "ControllerResult", "expire_if_needed", "note_audio_finished",
    "note_public_commit", "observe_user_turn", "select_next_action", "start_episode",
]
