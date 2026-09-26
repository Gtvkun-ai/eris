"""Pure state transitions for bounded pedagogical conversations."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from runtime.cognition.normalization import normalize_vi
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
ACKNOWLEDGEMENTS = frozenset({
    "ok", "okay", "yes", "yeah", "yep", "yup", "uh", "uh huh", "mm hmm", "mhm", "hmm", "ừ",
    "got it", "i got it", "understood", "i understand", "makes sense", "that makes sense", "sure",
    "yes got it", "yeah got it", "yes understood", "ừ hiểu rồi", "hiểu rồi",
})
_USER_EVIDENCE_CODES = frozenset({
    "topic_change",
    "eris_corrected",
    "misconception_assertion",
    "focused_question",
    "user_paraphrase",
    "user_application",
})
_KEYED_MISCONCEPTION_PREFIXES = (
    "misconception:",
    "misconception_assertion:",
    "candidate_misconception:",
)


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


def _refresh_activity(episode: TeachingEpisode, now: float) -> TeachingEpisode:
    return replace(episode, last_activity_at=now, expires_at=now + EPISODE_SECONDS)


def _is_acknowledgement(user_text: str) -> bool:
    normalized = user_text.strip().casefold()
    canonical = " ".join(normalized.replace("-", " ").replace(",", " ").replace(".", " ")
                         .replace("!", " ").replace("?", " ").split())
    return not canonical or canonical in ACKNOWLEDGEMENTS


def infer_user_evidence(
    user_text: str,
    *,
    explicit_evidence: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """Infer only high-confidence controller evidence from one bounded user turn."""
    if explicit_evidence is not None:
        accepted: list[str] = []
        for item in explicit_evidence:
            code = str(item or "").strip()
            if code in _USER_EVIDENCE_CODES:
                accepted.append(code)
                continue
            prefix = next((value for value in _KEYED_MISCONCEPTION_PREFIXES if code.startswith(value)), "")
            key = code[len(prefix):].strip()[:120] if prefix else ""
            if key and all(character.isalnum() or character in {"-", "_", "."} for character in key):
                accepted.append(prefix + key)
        return tuple(dict.fromkeys(accepted))
    if _is_acknowledgement(user_text):
        return ()

    text = normalize_vi(user_text)
    if not text:
        return ()
    if any(marker in text for marker in (
        "change the topic", "new topic", "another topic", "something else",
        "chuyen chu de", "doi chu de", "chu de khac", "noi chuyen khac",
    )):
        return ("topic_change",)
    if any(marker in text for marker in (
        "you misunderstood", "you are wrong", "that is not what i meant",
        "you got it wrong", "ban hieu sai", "ban sai", "khong phai y minh",
    )):
        return ("eris_corrected",)
    if "?" in str(user_text) or any(marker in text for marker in (
        "why does", "what do you mean", "how does", "does that mean",
        "tai sao", "vi sao", "y la gi", "the nao", "co phai",
    )):
        return ("focused_question",)
    if any(marker in text for marker in (
        "just means", "only means", "is simply", "is the same",
        "chi la", "chi co nghia", "don gian la", "giong het",
    )):
        return ("misconception_assertion",)
    if any(marker in text for marker in (
        "if i understand", "if i got this right", "if im understanding",
        "neu minh hieu", "neu toi hieu",
    )):
        return ()
    if any(marker in text for marker in (
        "i would apply", "i can apply", "i will apply", "i would use",
        "i can use", "i will use", "i used this", "i tried this",
        "minh se ap dung", "toi se ap dung", "ap dung vao",
    )):
        return ("user_application",)
    if any(marker in text for marker in (
        "in other words", "what i understand", "so it means", "that means",
        "nghia la", "noi cach khac", "minh hieu la", "tuc la",
    )):
        return ("user_paraphrase",)
    return ()


def _misconception_key(evidence: set[str], episode: TeachingEpisode) -> str:
    for code in sorted(evidence):
        if code.startswith(_KEYED_MISCONCEPTION_PREFIXES):
            return code.split(":", 1)[1] or episode.comprehension.current_concept_id
    return episode.comprehension.current_concept_id


def _has_misconception_evidence(evidence: set[str]) -> bool:
    return "misconception_assertion" in evidence or any(
        code.startswith(_KEYED_MISCONCEPTION_PREFIXES) for code in evidence
    )


def _begin_repair(episode: TeachingEpisode, key: str) -> TeachingEpisode:
    is_new_candidate = key != episode.repair_concept_id
    return replace(
        episode,
        status="repairing",
        pending_chunk=_chunk_for(episode, episode.comprehension.current_concept_id),
        repair_attempts=0 if is_new_candidate else episode.repair_attempts,
        repair_concept_id=key,
        consecutive_stalls=0,
    )


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
    codes: list[str] = []
    acknowledgement = _is_acknowledgement(user_text)
    if acknowledgement:
        codes.append("silence" if not user_text.strip() else "self_report_understood")
    if "topic_change" in supplied:
        codes.append("topic_change")
        updated = replace(episode, status="abandoned", pending_chunk=None)
        return ControllerResult(updated, _action("abandon", "topic_changed", updated), tuple(codes))

    if not acknowledgement:
        episode = _refresh_activity(episode, now)

    if "eris_corrected" in supplied:
        updated = _begin_repair(episode, episode.comprehension.current_concept_id)
        codes.append("eris_corrected")
        return ControllerResult(updated, select_next_action(updated, now=now), tuple(codes))

    if _has_misconception_evidence(supplied):
        updated = _begin_repair(episode, _misconception_key(supplied, episode))
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
    "ControllerAction", "ControllerResult", "expire_if_needed", "infer_user_evidence", "note_audio_finished",
    "note_public_commit", "observe_user_turn", "select_next_action", "start_episode",
]
