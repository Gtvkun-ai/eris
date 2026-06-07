# -*- coding: utf-8 -*-
"""
cortex/private_mind/inner_diary_renderer.py
==========================================

Human-readable renderer for private_mind_digest.

This is deliberately a debug/private view. It does not create public speech,
does not expose raw prompts, and does not invent thoughts outside the digest.
"""

from __future__ import annotations

from typing import Any, Mapping


def _short(value: Any, limit: int = 220) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


class InnerDiaryRenderer:
    """Render private_mind_digest into a compact inner-diary debug panel."""

    def render(self, digest: Mapping[str, Any]) -> dict[str, Any]:
        menu = _as_dict(digest.get("menu"))
        current = _as_dict(menu.get("current_thought") or digest.get("current"))
        temporary = _as_dict(menu.get("temporary_thoughts") or digest.get("temporary"))
        retained = _as_dict(menu.get("retained_thoughts") or digest.get("retained"))
        judgment = _as_dict(menu.get("inner_judgment"))
        mutations = _as_dict(menu.get("state_mutations"))
        future_bias = _as_dict(menu.get("future_bias"))
        silence_reason = _as_dict(menu.get("speech_silence_reason"))
        surface_queue = _as_list(menu.get("surface_queue") or digest.get("surface_queue"))
        concerns = _as_list(menu.get("open_concerns") or retained.get("concerns"))

        sections: list[dict[str, Any]] = []

        dominant = _short(current.get("dominant_judgment"), 320)
        if dominant:
            confidence = current.get("confidence", 0.0)
            pressure = current.get("pressure", 0.0)
            sections.append(
                {
                    "title": "Hiện tại",
                    "lines": [
                        f"Eris đang nghiêng về nhận định: {dominant}",
                        f"Độ chắc: {confidence}. Áp lực xử lý: {pressure}.",
                    ],
                }
            )

        why_lines: list[str] = []
        for fragment in _as_list(temporary.get("fragments"))[:4]:
            item = _as_dict(fragment)
            source = _short(item.get("source") or "unknown", 64)
            claim = _short(item.get("claim"), 220)
            score = item.get("score", 0.0)
            if claim:
                why_lines.append(f"- {source}: {claim} | score={score}")
        if why_lines:
            sections.append({"title": "Vì sao", "lines": why_lines})

        hyp_lines: list[str] = []
        for item in _as_list(judgment.get("ranked_hypotheses"))[:3]:
            hyp = _as_dict(item)
            label = _short(hyp.get("label"), 150)
            confidence = hyp.get("confidence", 0.0)
            if label:
                hyp_lines.append(f"- Đang xét: {label} | confidence={confidence}")
        for item in _as_list(judgment.get("rejected_hypotheses"))[:2]:
            hyp = _as_dict(item)
            label = _short(hyp.get("label"), 150)
            reason = _short(hyp.get("reason") or hyp.get("description"), 160)
            if label:
                hyp_lines.append(f"- Bị loại: {label}. Lý do: {reason}")
        if hyp_lines:
            sections.append({"title": "Giả thuyết", "lines": hyp_lines})

        concern_lines: list[str] = []
        for concern in concerns[:4]:
            item = _as_dict(concern)
            theme = _short(item.get("theme"), 220)
            if not theme:
                continue
            status = item.get("status", "open")
            pressure = item.get("pressure", 0.0)
            uncertainty = item.get("uncertainty", 0.0)
            concern_lines.append(f"- {theme} | status={status}, pressure={pressure}, uncertainty={uncertainty}")
        if concern_lines:
            sections.append({"title": "Bận tâm còn mở", "lines": concern_lines})

        mutation_lines: list[str] = []
        requested = _as_list(mutations.get("requested"))
        applied = _as_list(mutations.get("applied"))
        if requested:
            mutation_lines.append(f"Requested mutations: {len(requested)}.")
        if applied:
            mutation_lines.append(f"Applied mutations: {len(applied)}.")
        speech_bias = future_bias.get("speech_bias")
        thought_pressure = future_bias.get("thought_pressure")
        if speech_bias:
            mutation_lines.append(f"Speech bias: {_short(speech_bias, 220)}")
        if thought_pressure is not None:
            mutation_lines.append(f"Thought pressure: {thought_pressure}")
        if mutation_lines:
            sections.append({"title": "Ảnh hưởng tiếp theo", "lines": mutation_lines})

        surface_lines = [
            f"Có {len(surface_queue)} surface item đang chờ." if surface_queue else "Không có surface item cần nói ra ngay."
        ]
        if silence_reason:
            surface_lines.append(f"Lý do im/lọc: {_short(silence_reason, 220)}")
        sections.append({"title": "Bề mặt", "lines": surface_lines})

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
