# -*- coding: utf-8 -*-
"""
cortex/private_mind/inner_diary_renderer.py

Hiển thị trạng thái nội tâm cho người dùng xem — ngắn gọn, tiếng Việt.
Không expose raw prompt, không bịa thought ngoài digest.
"""

from __future__ import annotations

from typing import Any, Mapping


def _short(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _pct(value: Any) -> str:
    try:
        return f"{float(value or 0) * 100:.0f}%"
    except Exception:
        return "—"


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


class InnerDiaryRenderer:

    def render(self, digest: Mapping[str, Any]) -> dict[str, Any]:
        menu = _as_dict(digest.get("menu"))
        current = _as_dict(menu.get("current_thought") or digest.get("current"))
        temporary = _as_dict(menu.get("temporary_thoughts") or digest.get("temporary"))
        retained = _as_dict(menu.get("retained_thoughts") or digest.get("retained"))
        surface_queue = _as_list(menu.get("surface_queue") or digest.get("surface_queue"))
        concerns = _as_list(menu.get("open_concerns") or _as_dict(retained).get("concerns"))

        sections: list[dict[str, Any]] = []

        # Đang nghĩ gì
        dominant = _short(current.get("dominant_judgment"), 160)
        if dominant:
            sections.append({
                "title": "Đang nghĩ",
                "lines": [dominant],
            })

        # Đang bận tâm gì (từ concerns — nguồn bền vững nhất)
        concern_lines: list[str] = []
        for item in [_as_dict(c) for c in concerns[:3]]:
            theme = _short(item.get("theme"), 120)
            if theme:
                concern_lines.append(f"- {theme}")
        if concern_lines:
            sections.append({"title": "Đang bận tâm", "lines": concern_lines})

        # Vừa nhận ra điều gì (fragment claims mới nhất)
        notice_lines: list[str] = []
        for item in [_as_dict(f) for f in _as_list(temporary.get("fragments"))[:3]]:
            claim = _short(item.get("claim"), 120)
            if claim:
                notice_lines.append(f"- {claim}")
        if notice_lines:
            sections.append({"title": "Vừa nhận ra", "lines": notice_lines})

        # Có muốn nói gì không
        if surface_queue:
            seed = _short(
                _as_dict(surface_queue[0]).get("topic_seed")
                or _as_dict(surface_queue[0]).get("text")
                or "",
                120,
            )
            surface_line = seed if seed else "Có điều muốn nói."
            sections.append({"title": "Muốn nói", "lines": [surface_line]})

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
        }
