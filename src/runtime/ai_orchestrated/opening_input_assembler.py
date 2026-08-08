# -*- coding: utf-8 -*-
"""Lắp OpeningInput từ state/runtime hiện có.

Assembler chỉ gom và chuẩn hóa dữ liệu. Nó không quyết định nói gì, cũng không
biến hypothesis thành fact. Tách việc này ra giúp Opening Director không phải
thò tay vào nửa tá object host vốn đã đủ giống một ngăn kéo dây sạc rối.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Mapping, Sequence

from .opening_contracts import OpeningInput
from .opening_history import OpeningHistoryStore
from .opening_reentry import build_session_reentry_context


def _runtime_value(section: str, key: str, default: Any) -> Any:
    try:
        from runtime.runtime_settings_store import runtime_setting

        return runtime_setting(section, key, default=default)
    except Exception:
        return default


def _time_of_day(now: float) -> str:
    hour = datetime.fromtimestamp(now).hour
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 23:
        return "evening"
    return "late_night"


def _weekday_vi(now: float) -> str:
    labels = ("Thứ hai", "Thứ ba", "Thứ tư", "Thứ năm", "Thứ sáu", "Thứ bảy", "Chủ nhật")
    return labels[datetime.fromtimestamp(now).weekday()]


def _history_store_for(host: Any) -> OpeningHistoryStore:
    current = getattr(host, "ai_opening_history_store", None)
    if isinstance(current, OpeningHistoryStore):
        return current
    store = OpeningHistoryStore()
    try:
        setattr(host, "ai_opening_history_store", store)
    except Exception:
        pass
    return store


def _scene_partner(host: Any) -> Mapping[str, Any]:
    store = getattr(host, "ai_social_agenda_store", None)
    snapshot = getattr(store, "snapshot", None)
    if callable(snapshot):
        try:
            payload = snapshot()
            if isinstance(payload, Mapping) and isinstance(payload.get("scene_partner"), Mapping):
                return payload["scene_partner"]
        except Exception:
            pass
    return {}


def _compact_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _cross_session_continuity(host: Any, *, current_session_id: str) -> tuple[tuple[str, ...], str]:
    """Lấy một anchor công khai, gần nhất mà không gọi model ở startup.

    Living-user episode đã là recap được hợp nhất từ public conversation. Ta chỉ
    đọc episode không-private, bỏ đúng session hiện tại và lấy tối đa ba open
    loop cùng một summary ngắn. Startup vì thế có ký ức thật mà không phải chờ
    seed reservoir/model dựng lại cùng dữ liệu sau khi lời chào đã phát xong.
    """

    memory = getattr(host, "memory_kernel", None) or getattr(host, "memory_core", None)
    summary_fn = getattr(memory, "user_memory_summary", None)
    if not callable(summary_fn):
        return (), ""
    try:
        payload = summary_fn(include_sensitive=False)
    except TypeError:
        try:
            payload = summary_fn()
        except Exception:
            return (), ""
    except Exception:
        return (), ""
    if not isinstance(payload, Mapping):
        return (), ""

    rows = payload.get("recent_episodes")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        return (), ""
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        episode_session = str(raw.get("session_id", "") or "").strip()
        if current_session_id and episode_session and episode_session == current_session_id:
            continue
        scope = raw.get("scope") if isinstance(raw.get("scope"), Mapping) else {}
        if str(scope.get("kind", "") or "").strip().lower() in {"private", "temporary"}:
            continue

        loops = tuple(
            _compact_text(item, 220)
            for item in (raw.get("open_loops") or ())
            if _compact_text(item, 220)
        )[:3]
        title = _compact_text(raw.get("title", ""), 120)
        summary = _compact_text(raw.get("summary", ""), 420)
        if not loops and not title and not summary:
            continue
        if title and summary and title.casefold() != summary.casefold():
            recap = f"{title} — {summary}"
        else:
            recap = title or summary
        return loops, _compact_text(recap, 600)
    return (), ""


def _evidence_payloads(grounding: Any, *, now: float) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in tuple(getattr(grounding, "evidence", ()) or ())[:8]:
        if not isinstance(raw, Mapping):
            continue
        block_id = str(raw.get("id", "") or "").strip()
        if not block_id:
            continue
        text = str(raw.get("text", "") or "").strip()
        items.append(
            {
                "evidence_id": f"screen:{block_id}",
                "kind": str(raw.get("source", "screen_text") or "screen_text"),
                "subject": str(raw.get("window_title", "") or text),
                "claim": text,
                "confidence": float(raw.get("confidence", 0.0) or 0.0),
                "captured_at": float(raw.get("captured_at", 0.0) or 0.0),
                "privacy_class": "ordinary_ui",
                "allowed_for_surface": not bool(getattr(grounding, "privacy_blocked", False)),
                "source": "screen",
            }
        )
    for raw in tuple(getattr(grounding, "runtime_opening_evidence", ()) or ())[:6]:
        if not isinstance(raw, Mapping):
            continue
        signal_id = str(raw.get("id", "") or "").strip()
        if not signal_id:
            continue
        text = str(raw.get("text", "") or "").strip()
        items.append(
            {
                "evidence_id": f"runtime:{signal_id}",
                "kind": str(raw.get("kind", "runtime_event") or "runtime_event"),
                "subject": text,
                "claim": text,
                "confidence": float(raw.get("confidence", 0.0) or 0.0),
                "captured_at": float(raw.get("captured_at", now) or now),
                "privacy_class": "runtime_status",
                "allowed_for_surface": True,
                "source": "runtime",
            }
        )
    return items


def build_opening_input(
    host: Any,
    *,
    state: Any,
    grounding: Any,
    recent_history: Sequence[Mapping[str, Any]] = (),
    force_startup_speech: bool = True,
    now: float | None = None,
) -> OpeningInput:
    current = float(now if now is not None else time.time())
    history_store = _history_store_for(host)
    scene_partner = dict(_scene_partner(host))
    user_vocative = ""
    addressing_snapshot = getattr(host, "_user_addressing_snapshot", None)
    if callable(addressing_snapshot):
        try:
            user_vocative = str((addressing_snapshot() or {}).get("user_vocative", "") or "")
        except Exception:
            user_vocative = ""

    session_id = str(
        getattr(host, "session_id", "")
        or getattr(host, "_session_id", "")
        or f"runtime-{int(current)}"
    )
    state_open_loops = tuple(
        _compact_text(item, 240)
        for item in tuple(getattr(state, "open_loops", ()) or ())[:6]
        if _compact_text(item, 240)
    )
    last_session_at = float(getattr(host, "last_session_at", 0.0) or 0.0)
    seconds_since = max(0.0, current - last_session_at) if last_session_at > 0 else 0.0
    runtime_health = "normal"
    health_registry = getattr(host, "health_registry", None)
    if health_registry is not None:
        status = getattr(health_registry, "status", None)
        if callable(status):
            try:
                runtime_health = str(status() or "normal").lower()
            except Exception:
                runtime_health = "normal"

    allow_profile_personalization = bool(
        _runtime_value("opening_director", "cross_session_personalization", False)
    )
    startup_memory_callback = bool(
        _runtime_value("opening_director", "startup_memory_callback", True)
    )
    allow_cross_session = bool(allow_profile_personalization or startup_memory_callback)
    memory_open_loops: tuple[str, ...] = ()
    last_session_summary = ""
    if allow_cross_session:
        memory_open_loops, last_session_summary = _cross_session_continuity(
            host,
            current_session_id=session_id,
        )
    open_loops = tuple(dict.fromkeys((*state_open_loops, *memory_open_loops)))[:6]
    age_band = str(_runtime_value("opening_director", "age_band", "unknown") or "unknown")

    # V27: opening bắt đầu từ appraisal tái nhập phiên, không từ một template chào.
    # Cùng state hiện có sẽ tạo boost khác nhau: reconnect, callback, scene comment,
    # probe user, share nội sinh... mà không cần random seed.
    evidence_payloads = _evidence_payloads(grounding, now=current)
    reentry = build_session_reentry_context(
        host,
        now=current,
        seconds_since_last_session=seconds_since,
        restart_detected=bool(getattr(host, "restart_detected", False)),
        greeted_recently=bool(getattr(host, "greeted_recently", False)),
        open_loops=open_loops,
        last_session_summary=last_session_summary,
        evidence_payloads=evidence_payloads,
        scene_partner=scene_partner,
        time_of_day=_time_of_day(current),
    )
    # boundary_flags trong SocialAgenda là forensic history. Safety chỉ được hard
    # block bởi boundary còn hiện hành; boundary cũ vẫn nằm trong reentry để tăng
    # risk/cắt playful_protest, chứ không bắt Eris im đến tận thế.
    opening_scene_partner = dict(scene_partner)
    if not bool(reentry.get("current_boundary_active", False)):
        opening_scene_partner["boundary_flags"] = []

    payload = {
        "schema": "opening_input.v1",
        "event": {
            "kind": "startup",
            "session_id": session_id,
            "timestamp": current,
            "seconds_since_last_session": seconds_since,
            "restart_detected": bool(getattr(host, "restart_detected", False)),
            "greeted_recently": bool(getattr(host, "greeted_recently", False)),
        },
        "screen_evidence": evidence_payloads,
        "continuity": {
            "consent_scope": "cross_session" if allow_cross_session else "session_only",
            "active_goal": open_loops[0] if open_loops else "",
            "open_loops": list(open_loops),
            "recent_public_history": [dict(item) for item in recent_history[-8:] if isinstance(item, Mapping)],
            "last_session_summary": last_session_summary,
        },
        "session_state": {
            "time_of_day": _time_of_day(current),
            "weekday_vi": _weekday_vi(current),
            "chat_mode": bool(getattr(host, "chat_mode", False) or getattr(host, "_chat_processing", False)),
            "user_speaking": bool(getattr(host, "user_speaking", False) or getattr(host, "vad_active", False)),
            "public_turn_busy": bool(getattr(host, "_active_public_lifecycle_turn_id", "")),
            "startup_force_speak": bool(force_startup_speech),
            "runtime_health": runtime_health,
        },
        "recent_moves": history_store.recent_moves_payload(),
        "user_signals": {
            "availability": scene_partner.get("availability", "uncertain"),
            "recent_laugh": False,
            "recent_counter_tease": False,
            "recent_low_engagement": bool(scene_partner.get("recent_low_engagement", False)),
            "explicit_boundary": bool(reentry.get("current_boundary_active", False)),
            "recent_barge_in": bool(getattr(host, "startup_recent_barge_in", False)),
        },
        "scene_partner": opening_scene_partner,
        "reentry": reentry,
        "policy": {
            "age_band": age_band,
            "romantic_flirt_allowed": bool(_runtime_value("opening_director", "allow_romantic_flirt", False)),
            "romantic_flirt_opt_in": bool(_runtime_value("opening_director", "romantic_flirt_opt_in", False)),
            "sexual_content_allowed": bool(_runtime_value("opening_director", "allow_sexual_content", True)),
            "cross_session_personalization_allowed": allow_cross_session,
            "speech_allowed": True,
            "allow_screen_hook": bool(_runtime_value("opening_director", "allow_screen_hook", True)),
            "allow_continuity_hook": bool(_runtime_value("opening_director", "allow_continuity_hook", True)),
            "prefer_continuity_hook": bool(
                _runtime_value("opening_director", "prefer_continuity_hook", True)
            ),
            "allow_anime_moves": bool(_runtime_value("opening_director", "allow_anime_moves", True)),
            "require_adult_flirt_opt_in": bool(
                _runtime_value("opening_director", "require_adult_flirt_opt_in", True)
            ),
            "max_beats": int(_runtime_value("opening_director", "max_beats", 3) or 3),
            "max_questions": int(_runtime_value("opening_director", "max_questions", 1) or 1),
            "blocked_topics": [],
        },
        "addressing": {"user_vocative": user_vocative},
    }
    return OpeningInput.from_mapping(payload, now=current)


__all__ = ["build_opening_input"]
