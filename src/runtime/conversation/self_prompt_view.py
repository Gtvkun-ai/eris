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


def compact_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Lossless defaults/aliases; keep every record, value and metadata qualifier.

    No semantic filtering: even free-text metadata.reason is retained because it
    may contain conditions not repeated in value. Exceptions stay on each row.
    """
    result = deepcopy(dict(profile))
    records = result.get("records")
    if not isinstance(records, list) or not records or not all(isinstance(row, dict) for row in records):
        return result
    if result.get("projection_schema") == "eris.root_profile.v1":
        return result
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
    aliases: dict[str, str] = {}
    for source, target in (("updated_at", "last_confirmed_at"), ("created_at", "valid_from")):
        if all(source in row and target in row for row in records):
            aliases[source] = target
            for row in records:
                if _same_json(row[source], row[target]):
                    del row[source]
    result.update(projection_schema="eris.root_profile.v1", defaults=defaults, aliases=aliases)
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
        # Source windows belong to the Gemini memory lane, not every Root
        # bootstrap. Root retains the episode summary and its evidence refs.
        for episode in living.get("recent_episodes", ()):
            if isinstance(episode, dict) and isinstance(episode.get("metadata"), dict):
                episode["metadata"].pop("source_turns", None)
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
