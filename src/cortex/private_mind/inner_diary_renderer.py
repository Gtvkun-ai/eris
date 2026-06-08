# -*- coding: utf-8 -*-
"""
cortex/private_mind/inner_diary_renderer.py

Render a compact inner diary digest for UI display.
Keep it short and never expose raw prompt text.
"""

from __future__ import annotations

from typing import Any, Mapping


def _short(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


class InnerDiaryRenderer:
    EMOTION_RING = (
        ("hưng phấn", "joyful_excited", "top"),
        ("vui vẻ", "bright_content", "left"),
        ("bình tĩnh", "calm_centered", "bottom"),
        ("khó chịu", "tense_irritated", "right"),
    )

    def _future_thought(self, future_bias: Mapping[str, Any]) -> str:
        """Tóm tắt định hướng sắp tới từ future_bias (inquiry_plan / speech_bias).

        Không bịa: chỉ tóm tắt dữ liệu đã có trong digest.
        """
        if not isinstance(future_bias, Mapping):
            return ""

        plan_lines: list[str] = []
        for item in _as_list(future_bias.get("inquiry_plan"))[:3]:
            if isinstance(item, Mapping):
                text = (
                    item.get("question")
                    or item.get("text")
                    or item.get("topic")
                    or item.get("theme")
                    or ""
                )
            else:
                text = item
            text = _short(text, 120)
            if text:
                plan_lines.append(text)
        if plan_lines:
            return _short("; ".join(plan_lines), 200)

        speech_bias = _as_dict(future_bias.get("speech_bias"))
        for key in ("intent", "next_move", "stance", "tone"):
            val = _short(speech_bias.get(key), 160)
            if val:
                return val
        return ""

    def _emotion_board(self, digest: Mapping[str, Any]) -> dict[str, Any]:
        menu = _as_dict(digest.get("menu"))
        current = _as_dict(menu.get("current_thought") or digest.get("current"))
        retained = _as_dict(menu.get("retained_thoughts") or digest.get("retained"))
        concern = _as_list(menu.get("open_concerns") or _as_dict(retained).get("concerns"))
        future_bias = _as_dict(menu.get("future_bias") or digest.get("future_bias"))
        surface_queue = _as_list(menu.get("surface_queue") or digest.get("surface_queue"))

        center = _short(
            current.get("dominant_judgment")
            or digest.get("emotion_center")
            or digest.get("affect_summary")
            or "Ổn định",
            120,
        )
        if not center:
            center = "Ổn định"

        if any(str(item.get("theme") or "").strip() for item in concern):
            ring_hint = "ít căng thẳng"
        elif surface_queue:
            ring_hint = "có điều muốn nói"
        elif _future_thought := self._future_thought(future_bias):
            ring_hint = _future_thought
        else:
            ring_hint = "êm"

        quadrant_map: dict[str, dict[str, str]] = {}
        for label, key, position in self.EMOTION_RING:
            intensity = 0.22
            if key == "calm_centered":
                intensity = 0.84 if center == "Ổn định" else 0.76
            elif key == "tense_irritated":
                intensity = 0.68 if concern else 0.38
            elif key == "bright_content":
                intensity = 0.60 if surface_queue else 0.44
            elif key == "joyful_excited":
                intensity = 0.72 if future_bias else 0.50
            quadrant_map[position] = {"label": label, "key": key, "intensity": f"{intensity:.2f}"}

        return {
            "title": "Bảng cảm xúc",
            "shape": "circle",
            "center": {"label": center, "subtext": ring_hint},
            "quadrants": quadrant_map,
            "axes": ["vui vẻ", "hưng phấn", "khó chịu", "bình tĩnh"],
            "decor": {
                "style": "soft_pink_glow",
                "border": "rose",
                "markers": ["top", "left", "right", "bottom"],
                "style_hint": "reference_mockup",
            },
            "layout": {
                "type": "radial_board",
                "center_pulse": center,
                "orbit_labels": {
                    "top": "hưng phấn",
                    "left": "vui vẻ",
                    "right": "khó chịu",
                    "bottom": "bình tĩnh",
                },
                "accent": "pink_glass",
            },
        }

    def render(self, digest: Mapping[str, Any]) -> dict[str, Any]:
        menu = _as_dict(digest.get("menu"))
        current = _as_dict(menu.get("current_thought") or digest.get("current"))
        temporary = _as_dict(menu.get("temporary_thoughts") or digest.get("temporary"))
        retained = _as_dict(menu.get("retained_thoughts") or digest.get("retained"))
        surface_queue = _as_list(menu.get("surface_queue") or digest.get("surface_queue"))
        concerns = _as_list(menu.get("open_concerns") or _as_dict(retained).get("concerns"))
        future_bias = _as_dict(menu.get("future_bias") or digest.get("future_bias"))

        sections: list[dict[str, Any]] = []
        emotion_board = self._emotion_board(digest)
        quadrants = emotion_board["quadrants"]
        sections.append({
            "title": emotion_board["title"],
            "items": [
                {"text": emotion_board["center"]["label"], "badge": emotion_board["center"]["subtext"]},
                {"text": quadrants["top"]["label"], "badge": quadrants["top"]["intensity"]},
                {"text": quadrants["left"]["label"], "badge": quadrants["left"]["intensity"]},
                {"text": quadrants["right"]["label"], "badge": quadrants["right"]["intensity"]},
                {"text": quadrants["bottom"]["label"], "badge": quadrants["bottom"]["intensity"]},
            ],
            "lines": [emotion_board["center"]["label"], emotion_board["center"]["subtext"]],
        })

        dominant = _short(current.get("dominant_judgment"), 160)
        if dominant:
            sections.append({
                "title": "Suy nghi hien tai",
                "items": [{"text": dominant, "badge": ""}],
                "lines": [dominant],
            })

        future_text = self._future_thought(future_bias)
        if future_text:
            sections.append({
                "title": "Suy nghi tuong lai",
                "items": [{"text": future_text, "badge": ""}],
                "lines": [future_text],
            })

        concern_items: list[dict[str, str]] = []
        for item in [_as_dict(c) for c in concerns[:3]]:
            theme = _short(item.get("theme"), 120)
            if not theme:
                continue
            pressure = item.get("pressure")
            badge = ""
            try:
                badge = f"ap luc {float(pressure or 0):.2g}"
            except Exception:
                badge = ""
            concern_items.append({"text": theme, "badge": badge})
        if concern_items:
            sections.append({
                "title": "Dang ban tam",
                "items": concern_items,
                "lines": [f"- {item['text']}" for item in concern_items],
            })

        notice_items: list[dict[str, str]] = []
        for item in [_as_dict(f) for f in _as_list(temporary.get("fragments"))[:3]]:
            claim = _short(item.get("claim"), 120)
            if not claim:
                continue
            score = item.get("score")
            badge = ""
            try:
                badge = f"score {float(score or 0):.2f}"
            except Exception:
                badge = ""
            notice_items.append({"text": claim, "badge": badge})
        if notice_items:
            sections.append({
                "title": "Phan tich gan day",
                "items": notice_items,
                "lines": [f"- {item['text']}" for item in notice_items],
            })

        if surface_queue:
            seed = _short(
                _as_dict(surface_queue[0]).get("topic_seed")
                or _as_dict(surface_queue[0]).get("text")
                or "",
                120,
            )
            surface_line = seed if seed else "Co dieu muon noi."
            sections.append({
                "title": "Muon noi",
                "items": [{"text": surface_line, "badge": ""}],
                "lines": [surface_line],
            })

        text_parts: list[str] = []
        for section in sections:
            text_parts.append(str(section["title"]) + ":")
            text_parts.extend(str(line) for line in section.get("lines", ()))
            text_parts.append("")

        return {
            "mode": "debug_private",
            "title": "Inner Diary",
            "text": "\n".join(text_parts).strip(),
            "sections": sections,
            "emotion_board": emotion_board,
        }
