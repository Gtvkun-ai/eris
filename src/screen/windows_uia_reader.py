from __future__ import annotations

"""Đọc text có cấu trúc từ Windows UI Automation.

UIA luôn được ưu tiên hơn OCR vì text sạch hơn và giữ được ranh giới control.
Các cửa sổ chat/mail nhạy cảm bị chặn mặc định.
"""

import hashlib
import os
import re
import time

from .evidence_models import ActiveWindowInfo, ScreenTextBlock

try:  # pragma: no cover - chỉ chạy trên Windows thật
    import uiautomation as auto  # type: ignore
except Exception:  # pragma: no cover
    auto = None  # type: ignore

_SENSITIVE = ("discord", "telegram", "zalo", "messenger", "gmail", "outlook", "slack", "teams", "meet", "zoom")


class WindowsUIAReader:
    def __init__(self) -> None:
        self.enabled = os.getenv("ERIS_SCREEN_UIA_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}
        self.max_nodes = max(20, int(os.getenv("ERIS_SCREEN_UIA_MAX_NODES", "180") or 180))
        self.max_chars = max(300, int(os.getenv("ERIS_SCREEN_UIA_MAX_CHARS", "5000") or 5000))
        self.allow_sensitive = os.getenv("ERIS_SCREEN_TEXT_ALLOW_SENSITIVE", "0").strip().lower() in {"1", "true", "yes", "on"}

    def is_sensitive(self, title: str) -> bool:
        lowered = str(title or "").lower()
        return any(token in lowered for token in _SENSITIVE)

    def read(self, window: ActiveWindowInfo) -> tuple[ScreenTextBlock, ...]:
        if not self.enabled or auto is None:
            return ()
        if self.is_sensitive(window.title) and not self.allow_sensitive:
            return ()
        try:
            root = auto.GetForegroundControl()
            blocks: list[ScreenTextBlock] = []
            seen: set[str] = set()
            total = 0
            now = time.time()
            for item, depth in auto.WalkTree(root, maxDepth=8):
                del depth
                if len(blocks) >= self.max_nodes or total >= self.max_chars:
                    break
                try:
                    if bool(getattr(item, "IsPassword", False)):
                        continue
                    name = str(getattr(item, "Name", "") or "").strip()
                    value = ""
                    try:
                        pattern = item.GetValuePattern()
                        value = str(getattr(pattern, "Value", "") or "").strip()
                    except Exception:
                        pass
                    text = " ".join(part for part in (name, value) if part)
                    text = re.sub(r"\s+", " ", text).strip()
                    if len(text) < 2 or text.lower() in seen:
                        continue
                    seen.add(text.lower())
                    total += len(text)
                    digest = hashlib.sha1(f"uia|{window.title}|{text}".encode("utf-8", "ignore")).hexdigest()[:16]
                    blocks.append(ScreenTextBlock(digest, text[:800], "uia", 0.86, window.title, now))
                except Exception:
                    continue
            return tuple(blocks)
        except Exception:
            return ()
