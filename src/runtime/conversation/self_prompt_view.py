"""Pure transport views for Root; canonical stores and beliefs stay unchanged."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from typing import Any, Mapping


def _same_json(left: Any, right: Any) -> bool:
    # Python considers False == 0; a transport patch must preserve JSON types.
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same_json(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_same_json(a, b) for a, b in zip(left, right))
    return left == right


def state_difference(previous: Any, current: Any) -> Any:
    """Merge patch: dictionaries merge, arrays/scalars replace, explicit tombstones."""
    if _same_json(previous, current):
        return None
    if isinstance(previous, dict) and isinstance(current, dict):
        out = {key: {"__erased_from_self": True} for key in previous.keys() - current.keys()}
        for key, value in current.items():
            if key not in previous:
                out[key] = value
            else:
                diff = state_difference(previous[key], value)
                if diff is not None:
                    out[key] = diff
        return out or None
    return {"__value_now_null": True} if current is None else current


# Pure audit/provenance fields dropped from each profile record on the Root
# prompt path. They never steer a response and are the heaviest part of the
# block: evidence_ids (up to 96 ids/record) plus four raw epoch timestamps and
# the free-text metadata dict. The canonical store keeps them via to_dict();
# only this projection omits them. valid_until/expires_at are intentionally
# left for the defaults pass (they are retention qualifiers, not audit ids).
_PROFILE_AUDIT_FIELDS = (
    "evidence_ids", "metadata",
    "created_at", "updated_at", "last_confirmed_at", "valid_from",
)


def compact_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Transport projection for Root: drop audit/provenance, keep the telling.

    Keeps path/value and every lightweight qualifier (explicitness, scope,
    status, source, confidence...). Drops evidence_ids, the raw epoch
    timestamps and the metadata dict because no Root-prompt consumer reads
    them and they dominate the block size. Not lossless; the canonical store
    is untouched (store.save() uses ProfileRecord.to_dict(), not this).
    """
    result = deepcopy(dict(profile))
    records = result.get("records")
    if not isinstance(records, list) or not records or not all(isinstance(row, dict) for row in records):
        return result
    if result.get("projection_schema") == "eris.root_profile.v1":
        return result
    for row in records:
        for field in _PROFILE_AUDIT_FIELDS:
            row.pop(field, None)
    defaults: dict[str, Any] = {}
    for key in ("scope", "status", "sensitivity", "cardinality", "recurrence", "tier",
                "source", "value_type", "valid_until", "expires_at"):
        if not all(key in row for row in records):
            continue
        encoded = [json.dumps(row[key], ensure_ascii=False, sort_keys=True, separators=(",", ":")) for row in records]
        value, count = Counter(encoded).most_common(1)[0]
        if count < 2:
            continue
        defaults[key] = json.loads(value)
        for row in records:
            if _same_json(row[key], defaults[key]):
                del row[key]
    # Timestamp aliases are gone: both alias sources (updated_at, created_at)
    # and one target (valid_from) are now cut above, so no alias can form.
    result.update(projection_schema="eris.root_profile.v1", defaults=defaults, aliases={})
    return result


# Audit/provenance fields dropped from each episode on the Root prompt path.
# evidence_ids runs up to 128 ids/episode; session_id/source are internal
# plumbing; started_at/ended_at are raw epochs; metadata carried source_turns.
# The telling (title/summary/outcome and the signal lists) is kept intact.
_EPISODE_AUDIT_FIELDS = (
    "evidence_ids", "metadata", "started_at", "ended_at", "session_id", "source",
)


def compact_episode(episode: Mapping[str, Any]) -> dict[str, Any]:
    """Transport projection for one Root episode: drop audit, keep the telling.

    Keeps title/summary/outcome/topics/entities/decisions/open_loops/
    user_signals/importance/scope/id (length caps already applied by
    UserEpisode.__post_init__). Idempotent via a projection marker so
    state_difference never sees a phantom delta between turns.
    """
    if not isinstance(episode, Mapping):
        return episode  # type: ignore[return-value]
    result = deepcopy(dict(episode))
    if result.get("projection_schema") == "eris.root_episode.v1":
        return result
    for field in _EPISODE_AUDIT_FIELDS:
        result.pop(field, None)
    result["projection_schema"] = "eris.root_episode.v1"
    return result


def project_self_view(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Remove diagnostic views and exact clones, preserving differing source data."""
    result = deepcopy(dict(snapshot))
    memory = result.get("memory_state")
    if not isinstance(memory, dict):
        return result
    memory.pop("concept_graph", None)
    living = memory.get("living_user")
    if isinstance(living, dict):
        for key in ("replay", "last_dream_report", "pending_turns", "active_session_id"):
            living.pop(key, None)
        if isinstance(living.get("profile"), Mapping):
            living["profile"] = compact_profile(living["profile"])
        # Episodes carry audit refs (evidence_ids/source_turns), internal ids
        # and raw epochs that no Root-prompt consumer reads. Keep the telling
        # (title/summary/outcome/signal lists); drop the audit/provenance.
        episodes = living.get("recent_episodes")
        if isinstance(episodes, list):
            living["recent_episodes"] = [
                compact_episode(episode) if isinstance(episode, Mapping) else episode
                for episode in episodes
            ]
    active = memory.get("active_state")
    metadata = active.get("metadata") if isinstance(active, dict) else None
    if isinstance(metadata, dict) and "internal_state" in memory and _same_json(metadata.get("internal_state"), memory["internal_state"]):
        metadata.pop("internal_state", None)
    persisted = memory.get("ai_orchestrated_state")
    primary = result.get("mind_state")
    if isinstance(persisted, dict) and isinstance(primary, dict):
        differences = state_difference(primary, persisted)
        memory.pop("ai_orchestrated_state")
        if differences is not None:
            # Reducer remains authoritative. Keep unique persistence evidence as
            # a labelled alternative, not a second full current MindState.
            memory["persisted_mind_variants"] = differences
    return result


def project_runtime_context(context: Mapping[str, Any], self_view: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(context))
    status = result.get("conversation_status")
    mind = self_view.get("mind_state")
    if isinstance(status, dict) and isinstance(mind, dict) and "latest_observation" in status and "latest_observation" in mind:
        if _same_json(status["latest_observation"], mind["latest_observation"]):
            status.pop("latest_observation")
            status["latest_observation_ref"] = "mind_state.latest_observation"
    # Grounding/vision is deliberately untouched (step 5 is deferred).
    return result
