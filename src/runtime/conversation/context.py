# -*- coding: utf-8 -*-
"""Helpers cho plain-text conversation note."""
from __future__ import annotations


def normalize_note(note: str) -> str:
    # Giữ line-break do agent viết; chỉ cắt runaway payload.
    return str(note or "").strip()[:12000]


__all__ = ["normalize_note"]
