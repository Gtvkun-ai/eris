from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Mapping


_AXIS_LABELS = {
    "warmth_temperature": ("warmer", "cooler"),
    "preferred_distance": ("more distance", "closer"),
    "read_boldness": ("bolder reading", "more reserved reading"),
    "attachment_visibility": ("more visible attachment", "more hidden attachment"),
}

_TIME_OF_DAY = (
    (5, 12, "morning"),
    (12, 18, "afternoon"),
    (18, 24, "evening"),
    (0, 5, "late_night"),
)

_SIGNAL_TEXT = {
    "tom_read": "updated user-reading",
    "expanded": "expanded a thought thread",
    "interior": "shifted inward",
    "surface": "prepared a surface line",
    "private_mind": "private-mind tick landed",
}

_SECTION_ALIASES = {
    "bang cam xuc": "emotion_board",
    "suy nghi hien tai": "current",
    "suy nghi tuong lai": "future",
    "dang ban tam": "concern",
    "phan tich gan day": "analysis",
    "muon noi": "surface",
    "da nguoi": "settled",
}

_PRIORITY_DEFS = (
    ("technical", "Architecture / Technical"),
    ("humor", "Humor / Playfulness"),
    ("repair", "Repair / Help"),
    ("emotional", "Emotional Reading"),
    ("casual", "Small Talk / Casual"),
)

_PRIORITY_KEYWORDS = {
    "technical": (
        "architecture",
        "technical",
        "code",
        "debug",
        "runtime",
        "schema",
        "panel",
        "ui",
        "backend",
        "test",
        "refactor",
        "implement",
    ),
    "humor": ("humor", "playful", "banter", "joke", "tease", "fun"),
    "repair": ("repair", "help", "fix", "issue", "error", "failing", "broken", "support", "unblock"),
    "emotional": ("emotion", "affect", "feeling", "mood", "comfort", "worry", "concern", "gentle"),
    "casual": ("casual", "small talk", "hello", "hi", "idle", "light", "chat"),
}


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _text(value: Any, *, limit: int = 180) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp01(value: Any, default: float = 0.0) -> float:
    return max(0.0, min(1.0, _float(value, default)))


def _clamp_signed(value: Any, default: float = 0.0) -> float:
    return max(-1.0, min(1.0, _float(value, default)))


def _memory_core_dir() -> Path:
    raw = str(os.getenv("ERIS_MEMORY_CORE_DIR", "") or "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[2] / "memory_core"


def _read_json(name: str) -> Any:
    try:
        return json.loads((_memory_core_dir() / name).read_text(encoding="utf-8"))
    except Exception:
        return None


def _development_summary() -> dict[str, Any]:
    data = _read_json("development_profile.json")
    axes_out: list[dict[str, Any]] = []
    if isinstance(data, dict):
        axes = data.get("axes") or {}
        if isinstance(axes, dict):
            for name, payload in axes.items():
                delta = _float(_dict(payload).get("delta"), 0.0)
                if abs(delta) < 1e-6:
                    continue
                pos, neg = _AXIS_LABELS.get(name, (f"{name}+", f"{name}-"))
                axes_out.append(
                    {
                        "axis": str(name),
                        "label": pos if delta > 0 else neg,
                        "delta": round(delta, 3),
                    }
                )
    attachment = _attachment_summary()
    return {
        "live": bool(axes_out),
        "axes": axes_out,
        "sentence": (
            "A little has shifted since the beginning."
            if axes_out
            else "Almost unchanged from the beginning."
        ),
        "attachment": attachment,
    }


def _attachment_summary() -> dict[str, Any]:
    data = _read_json("anchor_state.json")
    value = _float(_dict(data).get("attachment_longarc"), 0.0) if isinstance(data, dict) else 0.0
    return {"live": isinstance(data, dict), "value": round(value, 3)}


def _signal_snapshot(max_age_s: float = 120.0) -> dict[str, Any]:
    data = _read_json("panel_snapshot.json")
    if not isinstance(data, dict):
        return {}
    ts = _float(data.get("ts"), 0.0)
    if ts <= 0.0:
        return {}
    if (time.time() - ts) > max_age_s:
        return {}
    return data


def _context_tags(now: float | None = None) -> list[str]:
    tm = time.localtime(now if now is not None else time.time())
    for start, end, label in _TIME_OF_DAY:
        if start <= tm.tm_hour < end:
            return [label, "quiet", "just_you"]
    return ["quiet", "just_you"]


def _parse_tom_confidence(text: str) -> float:
    match = re.search(r"~\s*([01](?:\.\d+)?)", str(text or ""))
    return _float(match.group(1), 0.0) if match else 0.0


def _normalize_title(title: str) -> str:
    raw = str(title or "").replace("đ", "d").replace("Đ", "D")
    stripped = "".join(ch for ch in unicodedata.normalize("NFD", raw) if not unicodedata.combining(ch))
    return " ".join(stripped.split()).casefold()


def _extract_sections(private_mind_digest: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    digest = _dict(private_mind_digest)
    diary = _dict(digest.get("inner_diary"))
    sections: list[dict[str, Any]] = []
    for raw_section in _list(diary.get("sections"))[:8]:
        section = _dict(raw_section)
        title = _text(section.get("title"), limit=80)
        if not title:
            continue
        items: list[dict[str, str]] = []
        for raw_item in _list(section.get("items"))[:6]:
            item = _dict(raw_item)
            text = _text(item.get("text"), limit=220)
            badge = _text(item.get("badge"), limit=80)
            if text:
                items.append({"text": text, "badge": badge})
        if not items:
            continue
        sections.append({"title": title, "kind": _SECTION_ALIASES.get(_normalize_title(title), "section"), "items": items})
    return sections


def _section_map(sections: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(section.get("kind") or ""): section for section in sections if section.get("kind")}


def _emotion_board(private_mind_digest: Mapping[str, Any] | None) -> dict[str, Any]:
    digest = _dict(private_mind_digest)
    board = _dict(_dict(digest.get("inner_diary")).get("emotion_board"))
    affect = _dict(digest.get("affect"))
    center = _dict(board.get("center"))
    quadrants = _dict(board.get("quadrants"))
    valence = _clamp_signed(affect.get("valence"), 0.0)
    arousal = _clamp01(affect.get("arousal"), 0.0)
    tenderness = _clamp01(affect.get("tenderness"), 0.0)
    irritation = _clamp01(affect.get("irritation"), 0.0)

    if not center:
        mood = "steady"
        if irritation >= 0.45 or valence <= -0.18:
            mood = "tense"
        elif arousal >= 0.6:
            mood = "energized"
        elif valence >= 0.18:
            mood = "light"
        center = {"label": mood, "subtext": "live affect fallback"}

    orbit = []
    for pos in ("top", "left", "right", "bottom"):
        item = _dict(quadrants.get(pos))
        label = _text(item.get("label"), limit=40) or pos
        intensity = _clamp01(item.get("intensity"), 0.22)
        orbit.append({"slot": pos, "label": label, "intensity": round(intensity, 3)})

    return {
        "headline": _text(center.get("label"), limit=80) or "steady",
        "subtext": _text(center.get("subtext"), limit=120) or "listening quietly",
        "orbit": orbit,
        "metrics": {
            "valence": round(valence, 3),
            "arousal": round(arousal, 3),
            "tenderness": round(tenderness, 3),
            "irritation": round(irritation, 3),
            "stability": round(_clamp01((1.0 - arousal) * 0.65 + (1.0 - irritation) * 0.35), 3),
            "positive_bias": round(_clamp01((valence + 1.0) * 0.5), 3),
        },
    }


def _history_point(*, ts: float, affect_card: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _dict(affect_card.get("metrics"))
    return {
        "ts": round(ts, 3),
        "value": round(_clamp01(metrics.get("positive_bias"), 0.5), 3),
        "stability": round(_clamp01(metrics.get("stability"), 0.5), 3),
        "label": _text(affect_card.get("headline"), limit=48) or "steady",
    }


def _roll_affect_history(
    existing: list[dict[str, Any]] | None,
    *,
    affect_card: Mapping[str, Any],
    now: float,
    limit: int = 32,
) -> list[dict[str, Any]]:
    history = [item for item in _list(existing) if isinstance(item, Mapping)]
    point = _history_point(ts=now, affect_card=affect_card)
    if history:
        last = _dict(history[-1])
        if abs(_float(last.get("value"), 0.0) - point["value"]) < 0.01 and abs(_float(last.get("stability"), 0.0) - point["stability"]) < 0.01:
            history[-1] = point
            return history[-limit:]
    history.append(point)
    return history[-limit:]


def _priority_sources(
    private_mind_digest: Mapping[str, Any] | None,
    *,
    tom_text: str,
    expression_gate: Mapping[str, Any] | None,
) -> list[str]:
    digest = _dict(private_mind_digest)
    menu = _dict(digest.get("menu"))
    current = _dict(menu.get("current_thought") or digest.get("current"))
    future_bias = _dict(menu.get("future_bias"))
    speech_bias = _dict(future_bias.get("speech_bias"))
    sources = [
        _text(current.get("dominant_judgment"), limit=220),
        _text(tom_text, limit=220),
        _text(speech_bias.get("intent"), limit=220),
        _text(speech_bias.get("next_move"), limit=220),
        _text(speech_bias.get("stance"), limit=220),
        _text(speech_bias.get("tone"), limit=220),
    ]
    for item in _list(future_bias.get("inquiry_plan"))[:4]:
        data = _dict(item)
        sources.append(_text(data.get("question") or data.get("text") or data.get("topic") or data.get("theme"), limit=220))
    for item in _list(menu.get("open_concerns"))[:4]:
        sources.append(_text(_dict(item).get("theme"), limit=220))
    for item in _list(menu.get("surface_queue"))[:4]:
        data = _dict(item)
        sources.append(_text(data.get("topic_seed") or data.get("text"), limit=220))
    gate = _dict(expression_gate)
    if gate:
        sources.append(_text(gate.get("stance"), limit=120))
    return [src for src in sources if src]


def _derive_priorities(
    private_mind_digest: Mapping[str, Any] | None,
    *,
    tom_text: str,
    expression_gate: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    sources = _priority_sources(private_mind_digest, tom_text=tom_text, expression_gate=expression_gate)
    joined = " ".join(sources).casefold()
    gate = _dict(expression_gate)
    want = _clamp01(gate.get("want_to_say"), 0.0)
    allowed = _clamp01(gate.get("allowed_expression"), 0.0)
    concerns = _list(_dict(_dict(private_mind_digest).get("menu")).get("open_concerns"))
    priorities: list[dict[str, Any]] = []

    for key, label in _PRIORITY_DEFS:
        score = 0.12 if key != "casual" else 0.15
        hits = 0
        for token in _PRIORITY_KEYWORDS.get(key, ()):
            if token in joined:
                score += 0.12
                hits += 1
        if key == "technical" and hits:
            score += 0.18 + allowed * 0.18
        if key == "repair" and ("error" in joined or "fix" in joined or "failing" in joined):
            score += 0.20
        if key == "emotional" and tom_text:
            score += 0.22
        if key == "humor" and "banter" in joined:
            score += 0.10
        if key == "casual" and not hits:
            score += 0.05 + max(0.0, 0.20 - len(sources) * 0.01)
        if key in {"technical", "repair"} and concerns:
            score += min(0.14, len(concerns) * 0.03)
        if key in {"technical", "repair", "emotional"}:
            score += want * 0.08
        priorities.append(
            {
                "key": key,
                "label": label,
                "score": round(_clamp01(score), 3),
                "reason": _priority_reason(key, sources),
            }
        )

    priorities.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return priorities


def _priority_reason(key: str, sources: list[str]) -> str:
    keywords = _PRIORITY_KEYWORDS.get(key, ())
    for source in sources:
        lower = source.casefold()
        if any(token in lower for token in keywords):
            return _text(source, limit=120)
    return ""


def _focus_mode(priorities: list[dict[str, Any]]) -> str:
    if not priorities:
        return "attentive"
    top = priorities[0]
    key = str(top.get("key") or "")
    score = _clamp01(top.get("score"), 0.0)
    if key == "technical" and score >= 0.55:
        return "deep_work"
    if key == "repair" and score >= 0.55:
        return "repair"
    if key == "emotional" and score >= 0.55:
        return "emotional_presence"
    if key == "humor" and score >= 0.55:
        return "playful"
    return "attentive"


def _journal_entries(
    *,
    now: float,
    sections_by_kind: Mapping[str, dict[str, Any]],
    signal_snapshot: Mapping[str, Any],
    tom_text: str,
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    time_text = time.strftime("%H:%M:%S", time.localtime(now))
    for kind in ("current", "concern", "analysis", "future", "surface", "settled"):
        section = _dict(sections_by_kind.get(kind))
        items = _list(section.get("items"))
        if not items:
            continue
        entries.append(
            {
                "time": time_text,
                "source": kind,
                "text": _text(_dict(items[0]).get("text"), limit=140),
            }
        )
    if tom_text:
        entries.append({"time": time_text, "source": "tom", "text": _text(tom_text, limit=140)})
    for raw_signal in _list(_dict(signal_snapshot).get("signal_log"))[:4]:
        item = _dict(raw_signal)
        kind = _text(item.get("kind"), limit=32)
        label = _SIGNAL_TEXT.get(kind, kind.replace("_", " "))
        if not label:
            continue
        entries.append(
            {
                "time": _text(item.get("time"), limit=16) or time_text,
                "source": "signal",
                "text": label,
            }
        )
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in entries:
        text = _text(item.get("text"), limit=140)
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        deduped.append({"time": _text(item.get("time"), limit=16), "source": _text(item.get("source"), limit=24), "text": text})
    return deduped[:8]


def build_depth_v2_state(
    *,
    private_mind_digest: Mapping[str, Any] | None,
    flags: Mapping[str, Any] | None,
    expression_gate: Mapping[str, Any] | None,
    tom_read: str,
    identity: Mapping[str, Any] | None,
    affect_history: list[dict[str, Any]] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    ts = float(now if now is not None else time.time())
    sections = _extract_sections(private_mind_digest)
    sections_by_kind = _section_map(sections)
    signal_snapshot = _signal_snapshot()
    affect_card = _emotion_board(private_mind_digest)
    history = _roll_affect_history(affect_history, affect_card=affect_card, now=ts)
    priorities = _derive_priorities(private_mind_digest, tom_text=tom_read, expression_gate=expression_gate)
    dev = _development_summary()
    gate = _dict(expression_gate)
    identity_block = dict(_dict(identity))
    identity_block.setdefault("name", "ERIS")
    identity_block["last_tick_at"] = round(_float(_dict(private_mind_digest).get("last_tick_at"), 0.0), 3)

    return {
        "version": 2,
        "ts": round(ts, 3),
        "identity": identity_block,
        "status": {
            "headline": _text(affect_card.get("headline"), limit=80) or "listening",
            "subtext": _text(affect_card.get("subtext"), limit=140) or "thinking quietly",
            "focus_mode": _focus_mode(priorities),
        },
        "affect": affect_card,
        "tom": {
            "live": bool(_text(tom_read)),
            "text": _text(tom_read, limit=220),
            "confidence": round(_parse_tom_confidence(tom_read), 3),
        },
        "expression": {
            "want": round(_clamp01(gate.get("want_to_say"), 0.0), 3),
            "suppress": round(_clamp01(gate.get("suppression_pressure"), 0.0), 3),
            "allowed": round(_clamp01(gate.get("allowed_expression"), 0.0), 3),
            "stance": _text(gate.get("stance"), limit=80),
        },
        "priorities": priorities,
        "interiority": {
            "sections": sections,
            "current": _dict(sections_by_kind.get("current")),
            "future": _dict(sections_by_kind.get("future")),
            "concern": _dict(sections_by_kind.get("concern")),
            "analysis": _dict(sections_by_kind.get("analysis")),
            "surface": _dict(sections_by_kind.get("surface")),
            "settled": _dict(sections_by_kind.get("settled")),
        },
        "n2": dev,
        "journal": _journal_entries(now=ts, sections_by_kind=sections_by_kind, signal_snapshot=signal_snapshot, tom_text=tom_read),
        "signal_log": [
            {
                "time": _text(_dict(item).get("time"), limit=16),
                "kind": _text(_dict(item).get("kind"), limit=24),
                "text": _SIGNAL_TEXT.get(_text(_dict(item).get("kind"), limit=24), _text(_dict(item).get("kind"), limit=24).replace("_", " ")),
            }
            for item in _list(signal_snapshot.get("signal_log"))[:8]
            if _dict(item)
        ],
        "context": {
            "tags": _context_tags(ts),
            "focus_mode": _focus_mode(priorities),
        },
        "flags": dict(_dict(flags)),
        "affect_history": history,
    }
