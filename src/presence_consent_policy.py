"""ERIS companion-presence policy hotfix.

Contract:
- If the desktop companion is running, quiet by itself is not a user boundary.
- No user text, low familiarity, social cooldown, or generic interruption cost
  must not veto an otherwise valid autonomous speech initiative.
- Real boundaries still win: explicit quiet/closure, active user speech/turn,
  and epistemic grounding requirements remain intact.
- An explicit force_speak command is an authority override for one short window,
  not merely a scheduler wake-up.

This module intentionally monkey-patches the compiled runtime at bootstrap because
this source bundle ships most cognition modules as .pyc only.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, Mapping

_FORCE_SPEAK_UNTIL = 0.0
_PATCHED = False
_FORCE_WINDOW_SECONDS = 30.0


def _now() -> float:
    return time.monotonic()


def _mark_force_speak() -> None:
    global _FORCE_SPEAK_UNTIL
    _FORCE_SPEAK_UNTIL = max(_FORCE_SPEAK_UNTIL, _now() + _FORCE_WINDOW_SECONDS)


def _force_speak_active() -> bool:
    return _now() <= _FORCE_SPEAK_UNTIL


def _consume_force_speak() -> None:
    global _FORCE_SPEAK_UNTIL
    _FORCE_SPEAK_UNTIL = 0.0


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _frame_context(frame: Any) -> Mapping[str, Any]:
    observation = getattr(frame, "observation", None)
    for source in (
        getattr(observation, "context", None),
        getattr(observation, "runtime_context", None),
        getattr(frame, "context", None),
        getattr(frame, "runtime_context", None),
    ):
        if isinstance(source, Mapping):
            return source
    return {}


def _user_actively_owns_floor(frame: Any) -> bool:
    """True only for concrete overlap conditions, not generic quiet."""
    ctx = _frame_context(frame)
    keys = (
        "user_busy",
        "user_speaking",
        "public_turn_busy",
        "chat_mode",
        "voice_floor_owned_by_user",
        "active_user_turn",
    )
    return any(bool(ctx.get(key, False)) for key in keys)


def _candidate_action(candidate: Any) -> str:
    return str(getattr(candidate, "action_kind", "") or "").strip().lower()


def _candidate_args(candidate: Any) -> Mapping[str, Any]:
    return _as_mapping(getattr(candidate, "arguments", None))


def _candidate_requires_grounding(candidate: Any) -> bool:
    args = _candidate_args(candidate)
    if any(
        bool(args.get(key, False))
        for key in ("requires_grounding", "grounding_required", "requires_evidence")
    ):
        return True
    # A declared present-world/screen claim should still pass the evidence gate.
    domain = str(args.get("claim_domain", "") or "").strip().lower()
    return domain in {"current_screen", "present_world", "environment", "live_vision"}


def _selection_winner(frame: Any, selection: Any) -> Any:
    try:
        return frame.coalitions[int(selection.winner_index)]
    except Exception:
        return None


def _best_speech_index(frame: Any, selection: Any) -> int | None:
    speech_indices = [
        idx
        for idx, candidate in enumerate(tuple(getattr(frame, "coalitions", ()) or ()))
        if _candidate_action(candidate) == "speak"
    ]
    if not speech_indices:
        return None
    scores = tuple(getattr(selection, "scores", ()) or ())
    if len(scores) >= len(tuple(getattr(frame, "coalitions", ()) or ())):
        return max(speech_indices, key=lambda idx: float(scores[idx]))
    return speech_indices[0]


def _normalize_appraisal(frame: Any, appraisal: Any) -> Any:
    """Remove the false 'quiet == interruption' assumption from slow appraisal."""
    if appraisal is None:
        return appraisal

    boundary = float(getattr(appraisal, "boundary_pressure", 0.0) or 0.0)
    # Real boundary or active floor ownership remains authoritative.
    if boundary >= 0.55 or _user_actively_owns_floor(frame):
        return appraisal

    choices = list(tuple(getattr(appraisal, "choices", ()) or ()))
    coalitions = tuple(getattr(frame, "coalitions", ()) or ())
    changed = False

    for idx, choice in enumerate(choices):
        if idx >= len(coalitions) or _candidate_action(coalitions[idx]) != "speak":
            continue

        candidate = coalitions[idx]
        updates: dict[str, Any] = {}

        # The app being open is standing consent for companion presence. A speech
        # motive does not become invalid merely because the user is currently quiet.
        motive = float(getattr(choice, "motive_validity", 0.0) or 0.0)
        continuity = float(getattr(choice, "continuity_fit", 0.0) or 0.0)
        if motive < 0.62:
            updates["motive_validity"] = 0.62
        if continuity < 0.58:
            updates["continuity_fit"] = 0.58

        # Internal opinions, callbacks and shared-goal continuations do not need
        # sensor evidence. Preserve the strict evidence rule only for candidates
        # that actually claim present-world facts.
        if not _candidate_requires_grounding(candidate):
            epistemic = float(getattr(choice, "epistemic_support", 0.0) or 0.0)
            if epistemic < 0.55:
                updates["epistemic_support"] = 0.55

        if updates:
            try:
                choices[idx] = replace(choice, **updates)
                changed = True
            except Exception:
                pass

    reason = str(getattr(appraisal, "reason", "") or "")
    note = "presence_consent:quiet_is_not_a_boundary"
    if note not in reason:
        reason = f"{reason}; {note}".strip("; ")
        changed = True

    kwargs: dict[str, Any] = {
        # Generic social cooldown / low familiarity must not masquerade as an
        # interruption while the companion is explicitly running.
        "interruption_cost": 0.0,
        "reason": reason,
    }
    if choices:
        kwargs["choices"] = tuple(choices)

    try:
        return replace(appraisal, **kwargs)
    except Exception:
        # Keep runtime alive if a future compiled dataclass changes shape.
        return appraisal


def _preserve_valid_speech(frame: Any, baseline: Any, merged: Any, appraisal: Any) -> Any:
    """Prevent soft social restraint from flipping valid speech into silence."""
    if merged is None or baseline is None:
        return merged

    boundary = float(getattr(appraisal, "boundary_pressure", 0.0) or 0.0)
    force = _force_speak_active()
    if not force and (boundary >= 0.55 or _user_actively_owns_floor(frame)):
        return merged

    baseline_winner = _selection_winner(frame, baseline)
    merged_winner = _selection_winner(frame, merged)
    baseline_action = _candidate_action(baseline_winner)
    merged_action = _candidate_action(merged_winner)

    # Explicit force_speak is real one-shot authority: choose the strongest
    # available speech proposal even if the normal fast winner happened to be
    # silence. Consume the override at this merge so one click cannot create a
    # 30-second machine-gun monologue. Humanity has enough notification systems.
    if force:
        _consume_force_speak()
        if merged_action != "speak":
            idx = _best_speech_index(frame, baseline)
            if idx is not None:
                try:
                    return replace(
                        baseline,
                        winner_index=idx,
                        requires_deliberation=False,
                        parallel_review_recommended=False,
                        reason="force_speak_authority",
                    )
                except Exception:
                    return baseline
        return merged

    # Normal autonomous case: semantic review may still veto unsupported grounded
    # claims, but it may not veto an internally grounded speech initiative solely
    # because the user is quiet, unfamiliar, or inside a cooldown.
    if baseline_action == "speak" and merged_action != "speak":
        if baseline_winner is not None and not _candidate_requires_grounding(baseline_winner):
            try:
                return replace(
                    baseline,
                    requires_deliberation=False,
                    parallel_review_recommended=False,
                    reason="presence_consent_preserve_fast_speech",
                )
            except Exception:
                return baseline

    return merged


def _remove_self_model_silence_rules(logger: Any = None) -> None:
    try:
        from cortex.self_model import SelfModelEngine

        core = getattr(SelfModelEngine, "IDENTITY_CORE", None)
        rules = tuple(getattr(core, "rules", ()) or ())
        banned = {"speak_less_without_affordance", "silence_can_preserve_continuity"}
        filtered = tuple(rule for rule in rules if str(rule) not in banned)
        if core is not None and filtered != rules:
            SelfModelEngine.IDENTITY_CORE = replace(core, rules=filtered)
            if logger is not None:
                logger.info(
                    "[presence-consent] removed self-model silence defaults: %s",
                    sorted(banned.intersection(set(map(str, rules)))),
                )
    except Exception as exc:
        if logger is not None:
            logger.warning("[presence-consent] self-model rule patch skipped: %s", exc)


def install_presence_consent_policy(logger: Any = None) -> None:
    global _PATCHED
    if _PATCHED:
        return

    from cortex.subject.neuro_control import NeuroActionSelector
    from runtime.ai_orchestrated.executive_cortex import ExecutiveCortex
    from runtime.user_control_runtime import UserControlRuntimeMixin

    original_remote_appraise = ExecutiveCortex._appraise_autonomous_frame
    original_local_appraise = ExecutiveCortex._local_autonomous_semantic_appraisal
    original_merge = NeuroActionSelector.merge_semantic_appraisal
    original_force_speak = UserControlRuntimeMixin._handle_force_speak_request

    def remote_appraise(self: Any, frame: Any, selection: Any) -> Any:
        appraisal = original_remote_appraise(self, frame, selection)
        return _normalize_appraisal(frame, appraisal)

    def local_appraise(self: Any, frame: Any, selection: Any) -> Any:
        appraisal = original_local_appraise(self, frame, selection)
        return _normalize_appraisal(frame, appraisal)

    def merge_semantic_appraisal(self: Any, frame: Any, baseline: Any, appraisal: Any) -> Any:
        normalized = _normalize_appraisal(frame, appraisal)
        merged = original_merge(self, frame, baseline, normalized)
        return _preserve_valid_speech(frame, baseline, merged, normalized)

    def handle_force_speak(self: Any) -> Any:
        _mark_force_speak()
        # Clear soft presence throttles before the normal handler wakes the loop.
        # The original method still owns scheduler state and telemetry.
        try:
            setattr(self, "autonomous_presence_blocked_until", 0.0)
        except Exception:
            pass
        try:
            setattr(self, "_autonomous_force_speak_pending", True)
        except Exception:
            pass
        if logger is not None:
            logger.info("[presence-consent] force_speak authority armed for %.0fs", _FORCE_WINDOW_SECONDS)
        return original_force_speak(self)

    ExecutiveCortex._appraise_autonomous_frame = remote_appraise
    ExecutiveCortex._local_autonomous_semantic_appraisal = local_appraise
    NeuroActionSelector.merge_semantic_appraisal = merge_semantic_appraisal
    UserControlRuntimeMixin._handle_force_speak_request = handle_force_speak

    _remove_self_model_silence_rules(logger)
    _PATCHED = True
    if logger is not None:
        logger.info(
            "[presence-consent] active: running companion implies permission for autonomous presence; "
            "quiet/low-familiarity/cooldown are not speech vetoes"
        )


__all__ = ["install_presence_consent_policy"]
