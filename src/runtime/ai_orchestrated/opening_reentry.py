# -*- coding: utf-8 -*-
"""Appraisal tái nhập phiên cho Opening Director.

Module này KHÔNG viết lời chào và không tự quyết định phải nói. Nó chỉ gom các
nguồn đã có provenance (thời gian vắng mặt, continuity, scene grounding,
Subject initiative/relational state) thành các *motive boost tạm thời* cho lượt
mở đầu. Boost bị tiêu thụ cùng opening, không trở thành personality hay Need
bền vững. Nói cách khác: đây là cú hích "anh vừa quay lại" chứ không phải một
nhu cầu mới được nhét vào Eris chỉ vì chúng ta thấy câu chào hơi nhạt.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(0.0, min(1.0, number))


def _compact(value: Any, limit: int = 220) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text if len(text) <= limit else text[: max(0, limit - 3)].rstrip() + "..."


def _absence_profile(seconds: float, *, restart: bool, greeted_recently: bool) -> tuple[str, float]:
    """Trả về band + salience phi tuyến.

    Restart nhanh không được diễn giải như một cuộc chia ly. Vài giờ vắng mặt mới
    đủ tạo lực reconnect đáng kể; nhiều ngày tăng tiếp nhưng không bao giờ ép nói.
    """
    value = max(0.0, float(seconds or 0.0))
    if restart or greeted_recently or value <= 45.0:
        return "restart", 0.04
    if value <= 10 * 60:
        return "quick_reopen", 0.14
    if value <= 60 * 60:
        return "short_absence", 0.30
    if value <= 6 * 60 * 60:
        return "few_hours", 0.56
    if value <= 24 * 60 * 60:
        return "day_gap", 0.72
    return "long_absence", 0.84


def _subject_views(host: Any, *, now: float) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    service = getattr(host, "subject_service", None) or getattr(host, "ai_subject_service", None)
    if service is None:
        ingress = getattr(host, "subject_ingress", None) or getattr(host, "ai_subject_ingress", None)
        service = getattr(ingress, "service", None) or getattr(ingress, "subject", None)
    initiative: Mapping[str, Any] = {}
    relational: Mapping[str, Any] = {}
    if service is not None:
        fn = getattr(service, "initiative_view", None)
        if callable(fn):
            try:
                value = fn()
                if isinstance(value, Mapping):
                    initiative = value
            except Exception:
                pass
        fn = getattr(service, "relational_view", None)
        if callable(fn):
            try:
                value = fn(now=now)
                if isinstance(value, Mapping):
                    relational = value
            except TypeError:
                try:
                    value = fn()
                    if isinstance(value, Mapping):
                        relational = value
                except Exception:
                    pass
            except Exception:
                pass
    return initiative, relational


def _pending_by_kind(initiative: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    best: dict[str, Mapping[str, Any]] = {}
    for raw in initiative.get("pending_intentions", ()):
        if not isinstance(raw, Mapping) or str(raw.get("status") or "pending") != "pending":
            continue
        kind = str(raw.get("motive_kind") or "").strip().lower()
        if not kind:
            continue
        pressure = _clamp01(raw.get("pressure", 0.0))
        current = best.get(kind)
        if current is None or pressure > _clamp01(current.get("pressure", 0.0)):
            best[kind] = raw
    return best


def build_session_reentry_context(
    host: Any,
    *,
    now: float,
    seconds_since_last_session: float,
    restart_detected: bool,
    greeted_recently: bool,
    open_loops: Sequence[str],
    evidence_payloads: Sequence[Mapping[str, Any]],
    scene_partner: Mapping[str, Any],
    time_of_day: str,
) -> dict[str, Any]:
    """Tính các motive boost startup từ state thật, không cần random seed."""
    band, return_salience = _absence_profile(
        seconds_since_last_session,
        restart=restart_detected,
        greeted_recently=greeted_recently,
    )
    initiative, relational = _subject_views(host, now=now)
    pending = _pending_by_kind(initiative)

    connection = _clamp01(relational.get("connection_pressure", 0.0))
    opportunity = _clamp01(relational.get("opportunity", 0.45), 0.45)
    curiosity = _clamp01(relational.get("social_curiosity", 0.0))
    sharing = _clamp01(relational.get("sharing_pressure", 0.0))

    # Boundary cũ vẫn là bằng chứng về risk, nhưng chỉ boundary vừa cập nhật mới
    # có quyền hard-block startup. Cờ vĩnh viễn từng khiến một lần "thôi" biến
    # thành lời thề im lặng xuyên phiên, một cách khá máy móc để nhớ quan hệ.
    flags = tuple(str(item) for item in scene_partner.get("boundary_flags", ()) if str(item or "").strip())
    partner_updated_at = max(0.0, float(scene_partner.get("updated_at", 0.0) or 0.0))
    boundary_age = max(0.0, now - partner_updated_at) if partner_updated_at else float("inf")
    current_boundary = bool(flags and boundary_age <= 20 * 60)
    historical_boundary = bool(flags and not current_boundary)

    strongest_scene: Mapping[str, Any] | None = None
    strongest_scene_score = 0.0
    for item in evidence_payloads:
        if not isinstance(item, Mapping) or not bool(item.get("allowed_for_surface", True)):
            continue
        confidence = _clamp01(item.get("confidence", 0.0))
        freshness_ms = max(0, int(item.get("freshness_ms", 0) or 0))
        if confidence < 0.58 or freshness_ms > 12_000:
            continue
        score = confidence * (1.0 if str(item.get("source") or "screen") == "screen" else 0.84)
        if score > strongest_scene_score:
            strongest_scene_score = score
            strongest_scene = item

    continuity = 0.78 if open_loops else 0.0
    scene = _clamp01(strongest_scene_score * (1.08 if time_of_day == "morning" else 1.0))
    familiar = str(scene_partner.get("closeness_band") or "new").lower() in {"familiar", "close"}
    tease_est = _clamp01(scene_partner.get("tease_tolerance_estimate", 0.35), 0.35)
    tease_conf = _clamp01(scene_partner.get("tease_tolerance_confidence", 0.15), 0.15)

    def pending_pressure(kind: str) -> float:
        raw = pending.get(kind, {})
        return _clamp01(raw.get("pressure", 0.0)) * (0.65 + 0.35 * _clamp01(raw.get("commitment_strength", 0.0)))

    reconnect = _clamp01(return_salience * (0.62 + 0.38 * max(connection, 0.35)))
    playful = _clamp01(
        return_salience
        * (0.48 + 0.52 * connection)
        * tease_est
        * (0.45 + 0.55 * tease_conf)
        * (1.0 if familiar else 0.28)
    )
    if historical_boundary:
        playful *= 0.35
    if current_boundary:
        playful = 0.0

    boosts = {
        "reconnect": reconnect,
        "continue_thread": continuity,
        "scene_comment": scene,
        "social_probe": _clamp01(max(pending_pressure("understand_user"), 0.46 * curiosity + 0.24 * connection)),
        "share_internal": _clamp01(max(pending_pressure("share"), sharing * (0.55 + 0.45 * connection))),
        "recognition_bid": pending_pressure("seek_recognition"),
        "demonstration_bid": pending_pressure("demonstrate"),
        "playful_protest": playful,
        "quiet_acknowledgement": _clamp01(0.28 + 0.30 * return_salience),
    }
    if current_boundary:
        # Vẫn giữ quiet acknowledgement ở mức thấp cho trường hợp policy cho phép
        # nhưng safety hiện tại sẽ hard-block speech. Boost không được lách gate.
        boosts = {key: 0.0 for key in boosts}

    subjects: dict[str, str] = {}
    if open_loops:
        subjects["continue_thread"] = _compact(open_loops[0], 220)
    if strongest_scene is not None:
        subjects["scene_comment"] = _compact(strongest_scene.get("subject") or strongest_scene.get("claim"), 220)
    for source_kind, motive in (
        ("understand_user", "social_probe"),
        ("share", "share_internal"),
        ("seek_recognition", "recognition_bid"),
        ("demonstrate", "demonstration_bid"),
    ):
        raw = pending.get(source_kind)
        if raw:
            subjects[motive] = _compact(raw.get("semantic_goal"), 260)

    ranked = sorted(boosts.items(), key=lambda item: (item[1], item[0]), reverse=True)
    strongest_motive = ranked[0][0] if ranked and ranked[0][1] > 0 else "quiet_acknowledgement"
    refs: list[str] = [f"session-reentry:absence:{band}"]
    if strongest_scene is not None and strongest_scene.get("evidence_id"):
        refs.append(str(strongest_scene["evidence_id"]))
    refs.extend(str(item) for item in relational.get("evidence_refs", ()) if str(item or "").strip())

    return {
        "absence_band": band,
        "return_salience": return_salience,
        "connection_pressure": connection,
        "social_opportunity": opportunity,
        "current_boundary_active": current_boundary,
        "historical_boundary_present": historical_boundary,
        "strongest_motive": strongest_motive,
        "motive_boosts": boosts,
        "motive_subjects": subjects,
        "evidence_refs": list(dict.fromkeys(refs))[:12],
    }


__all__ = ["build_session_reentry_context"]
