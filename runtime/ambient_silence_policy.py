# -*- coding: utf-8 -*-
"""Shared ambient-silence / muse policy for the autonomous idle loop.

``coordinator.py`` and ``autonomous_cycle.py`` historically duplicated this
logic; both now delegate here so the two drivers cannot drift. The key change
for the liveliness redesign: a ``pattern_muse`` directive (the cognition layer
granting permission to pull its own topic) must not be suppressed purely by the
standard ambient-silence cooldown.
"""

from __future__ import annotations


def muse_directive_active(ti_report) -> bool:
    """True when cognition granted self-initiated topic permission."""

    return str(getattr(ti_report, "mode", "") or "") == "pattern_muse"


def ambient_silence_cooldown_seconds(snapshot, ti_report) -> int:
    """Cooldown window (seconds) for ambient-silence pacing by mode/focus."""

    mode = str(getattr(ti_report, "mode", "") or "")
    kind = str(getattr(snapshot, "active_window_kind", "") or "")

    if mode == "resource_guard":
        return 0
    if mode == "pattern_muse":
        return 60
    if kind in {"coding", "documentation"}:
        return 60   # Eris vẫn nói khi bạn đang code, nhưng ít hơn
    if kind == "communication":
        return 40
    if kind == "entertainment":
        return 50
    if mode in {"system_watch", "pattern_watch", "social_watch"}:
        return 50
    return 40  # default: nói lại sau 40s


def should_hold_ambient_silence(
    *,
    snapshot,
    ti_report,
    last_text: str,
    last_autonomous_spoken_at: float,
    speech_intent: str = "",
    now: float | None = None,
) -> tuple[bool, str]:
    """Decide whether to hold this cycle for ambient pacing.

    Returns ``(held, reason)``. ``reason`` is structured for the DecisionRecord:
    ``"cooldown=<n>s"`` when held, or an empty string when not held. A
    ``pattern_muse`` directive is never held solely on cooldown (Req 4.2).
    """

    import time as _time

    if speech_intent in {"system_warning", "user_requested"}:
        return False, ""
    if not last_text or float(last_autonomous_spoken_at or 0.0) <= 0.0:
        return False, ""
    # Proactive muse must be allowed to fire; do not hold it on cooldown alone.
    if muse_directive_active(ti_report):
        return False, "muse_exempt"

    cooldown = ambient_silence_cooldown_seconds(snapshot, ti_report)
    if cooldown <= 0:
        return False, ""

    current_time = _time.time() if now is None else now
    if (current_time - float(last_autonomous_spoken_at)) < cooldown:
        return True, f"cooldown={cooldown}s"
    return False, ""
