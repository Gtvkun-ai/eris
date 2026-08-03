# -*- coding: utf-8 -*-
"""Commit a model-appraised social plan after its public line succeeds.

The public writer owns wording. This module only turns semantic proposals into
runtime state after the source utterance has actually been committed, so failed
or cancelled speech cannot leave ghost afterbeats, arcs, or agendas behind.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Mapping

from .social_execution import accept_full_social_plan
from .social_plan import empty_social_plan

_LOG = logging.getLogger(__name__)


def activate_social_plan_after_public_commit(
    host: Any,
    payload: Mapping[str, Any] | None,
    *,
    source_turn_id: str,
    source_text: str,
    source_turn_seq: int,
) -> dict[str, Any]:
    raw_plan = payload.get("social_plan") if isinstance(payload, Mapping) else None
    try:
        social_plan = accept_full_social_plan(
            raw_plan if isinstance(raw_plan, Mapping) else None
        )
    except Exception as exc:
        social_plan = empty_social_plan()
        logger = getattr(host, "logger", _LOG)
        method = getattr(logger, "debug", None)
        if callable(method):
            method("[social execution] normalization failed: %s", exc)

    semantic_obj = payload.get("_typed_semantic_frame") if isinstance(payload, Mapping) else None
    assistant_obj = payload.get("_typed_assistant_act") if isinstance(payload, Mapping) else None
    semantic_payload = (
        semantic_obj.to_dict()
        if callable(getattr(semantic_obj, "to_dict", None))
        else dict(payload.get("semantic_frame", {}) or {}) if isinstance(payload, Mapping) else {}
    )
    assistant_payload = (
        assistant_obj.to_dict()
        if callable(getattr(assistant_obj, "to_dict", None))
        else dict(payload.get("assistant_act", {}) or {}) if isinstance(payload, Mapping) else {}
    )

    now = time.time()
    continuation = getattr(host, "ai_social_continuation_runtime", None)
    agenda = getattr(host, "ai_social_agenda_store", None)
    arc = getattr(host, "ai_conversation_arc_runtime", None)
    scheduled_arc = False

    if continuation is not None:
        try:
            continuation.schedule_from_social_plan(
                social_plan,
                source_turn_id=source_turn_id,
                source_text=source_text,
                source_turn_seq=source_turn_seq,
                semantic_frame=semantic_payload,
                assistant_act=assistant_payload,
                now=now,
            )
        except Exception as exc:
            host.logger.debug("[social continuation] schedule failed: %s", exc)

    if agenda is not None:
        try:
            proposal = social_plan.get("agenda_update", {})
            agenda.apply_update(
                proposal if isinstance(proposal, Mapping) else {},
                source_turn_id=source_turn_id,
                now=now,
            )
        except Exception as exc:
            host.logger.debug("[social agenda] update failed: %s", exc)

    if arc is not None:
        try:
            proposal = social_plan.get("conversation_arc", {})
            scheduled_arc = arc.schedule_from_model(
                proposal if isinstance(proposal, Mapping) else {},
                source_turn_id=source_turn_id,
                source_text=source_text,
                source_turn_seq=source_turn_seq,
                semantic_frame=semantic_payload,
                assistant_act=assistant_payload,
                now=now,
            )
        except Exception as exc:
            host.logger.debug("[conversation arc] schedule failed: %s", exc)

    # Very short audio can finish before the scheduling transaction returns.
    clock = getattr(host, "interaction_clock", None)
    if clock is not None:
        audio_finished_at = float(getattr(clock, "audio_finished_at", 0.0) or 0.0)
        assistant_text_at = float(getattr(clock, "assistant_text_at", 0.0) or 0.0)
        playback_already_done = bool(
            audio_finished_at > 0.0
            and audio_finished_at >= assistant_text_at
            and not bool(getattr(clock, "audio_active", False))
        )
        if playback_already_done:
            if continuation is not None:
                try:
                    continuation.notify_audio_finished(
                        audio_finished_at,
                        source_turn_id=source_turn_id,
                    )
                except Exception as exc:
                    host.logger.debug("[social continuation] audio catch-up failed: %s", exc)
            if scheduled_arc and arc is not None:
                try:
                    arc.notify_audio_finished(audio_finished_at)
                except Exception as exc:
                    host.logger.debug("[conversation arc] audio catch-up failed: %s", exc)

    decisions = {
        "afterbeat": str(dict(social_plan.get("afterbeat", {})).get("decision", "none")),
        "exposure": str(dict(social_plan.get("exposure", {})).get("decision", "none")),
        "agenda": str(dict(social_plan.get("agenda_update", {})).get("decision", "none")),
        "arc": str(dict(social_plan.get("conversation_arc", {})).get("decision", "none")),
    }
    if any(value != "none" for value in decisions.values()):
        try:
            host.logger.info(
                "[social plan commit] turn=%s afterbeat=%s exposure=%s agenda=%s arc=%s",
                source_turn_id,
                decisions["afterbeat"],
                decisions["exposure"],
                decisions["agenda"],
                decisions["arc"],
            )
        except Exception:
            pass
    return social_plan


__all__ = ["activate_social_plan_after_public_commit"]
