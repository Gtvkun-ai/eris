from __future__ import annotations

"""Router quyết định none -> text evidence -> vision escalation."""

import re
import time
import unicodedata

from .evidence_models import ScreenRouteDecision
from .screen_evidence_store import ScreenEvidenceStore


def _norm(text: str) -> str:
    value = unicodedata.normalize("NFD", str(text or "").lower()).replace("đ", "d")
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9_#+.\-]+", " ", value).strip()


def _has_marker(normalized: str, marker: str) -> bool:
    marker = _norm(marker)
    if not marker:
        return False
    return f" {marker} " in f" {normalized} "


class ScreenRelevanceRouter:
    SCREEN_MARKERS = ("man hinh", "screen", "tren man", "cua so nay", "nhin man hinh", "xem man hinh", "xem di", "ban xem di", "dang hien gi", "toi dang code gi", "doan dang mo", "file dang mo", "loi nay tren man hinh")
    TEXT_MARKERS = ("chu", "text", "dong", "log", "terminal", "console", "code", "traceback", "exception", "error", "loi", "thong bao", "ghi gi", "doc", "file", "ham", "class")
    VISUAL_MARKERS = ("mau", "bo cuc", "layout", "icon", "anh nay", "hinh anh", "giao dien", "ui", "dep", "xau", "vi tri", "can le", "kich thuoc", "bieu do", "chart")
    STRONG_MARKERS = ("chinh xac", "xac nhan", "evidence", "bang chung", "doc dung", "kiem tra ky", "verify")

    def __init__(self, store: ScreenEvidenceStore) -> None:
        self.store = store

    def route(self, user_text: str) -> ScreenRouteDecision:
        normalized = _norm(user_text)
        references = any(_has_marker(normalized, marker) for marker in self.SCREEN_MARKERS)
        if not references:
            return ScreenRouteDecision(mode="none", reason="no_screen_reference")
        needs_visual = any(_has_marker(normalized, marker) for marker in self.VISUAL_MARKERS)
        requires_strong = any(_has_marker(normalized, marker) for marker in self.STRONG_MARKERS)
        text_task = any(_has_marker(normalized, marker) for marker in self.TEXT_MARKERS)
        generic = references and not text_task and not needs_visual
        evidence = self.store.query(user_text, generic_screen_request=generic)
        confidence = max((block.confidence for block in evidence), default=0.0)
        stale = bool(evidence and time.time() - max(block.captured_at for block in evidence) > 8.0)

        if needs_visual:
            return ScreenRouteDecision("vision", True, True, requires_strong, "visual_layout_or_image_requested", evidence, confidence, stale)
        if evidence and confidence >= 0.72 and not stale:
            return ScreenRouteDecision("text_evidence", True, False, requires_strong, "fresh_screen_text_available", evidence, confidence, False)
        if evidence and confidence >= 0.48:
            if requires_strong:
                return ScreenRouteDecision("vision", True, False, True, "screen_text_not_strong_enough", evidence, confidence, stale)
            return ScreenRouteDecision("text_evidence_soft", True, False, False, "screen_text_available_but_soft", evidence, confidence, stale)
        return ScreenRouteDecision("vision", True, False, requires_strong, "no_usable_screen_text_escalate_vision", (), 0.0, False)
