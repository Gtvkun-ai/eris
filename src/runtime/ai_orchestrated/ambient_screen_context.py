# -*- coding: utf-8 -*-
"""Ngữ cảnh màn hình nền cho self-initiated turn.

UIA/OCR vốn đã chạy nền nhưng trước đây autonomous chỉ nhận ``vision_facts`` và
telemetry tên cửa sổ. Module này biến snapshot màn hình thành một contract nhỏ,
có provenance, độ tươi và *delta* rõ ràng. Nó không kết luận người dùng đang làm
gì; nó chỉ cho Main AI đủ dữ kiện để hỏi hoặc trêu ở mức rủi ro thấp.
"""

from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


def _norm(text: Any) -> str:
    value = unicodedata.normalize("NFD", str(text or "").lower()).replace("đ", "d")
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9_#+.\-]+", " ", value).strip()


def _compact(text: Any, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value if len(value) <= limit else value[: max(0, limit - 3)].rstrip() + "..."


def _hash_text(text: str) -> str:
    return hashlib.sha1(_norm(text).encode("utf-8", "ignore")).hexdigest()[:16]


_GAME_MARKERS = (
    "steam", "epic games", "mini world", "minecraft", "roblox", "valorant",
    "league of legends", "lien quan", "genshin", "honkai", "game client",
    "inventory", "stamina", "mana", "health", "hp ", " mp ", "quest",
    "respawn", "victory", "defeat", "score", "match", "level up",
)
_CODE_MARKERS = (
    "godot", "visual studio", "vscode", "pycharm", "rider", "terminal",
    "powershell", "traceback", "exception", "debugger", "script", ".gd",
    ".py", "class ", "func ", "extends ", "error", "warning",
)
_MEDIA_MARKERS = (
    "youtube", "tiktok", "spotify", "netflix", "vlc", "now playing",
    "pause", "playback", "subtitle", "channel", "playlist",
)
_CHAT_MARKERS = (
    "discord", "telegram", "zalo", "messenger", "gmail", "outlook", "slack",
    "teams", "zoom", "meet",
)
_BROWSER_MARKERS = ("chrome", "edge", "firefox", "brave", "opera", "browser")


def _contains_any(blob: str, markers: Sequence[str]) -> bool:
    padded = f" {blob} "
    return any(marker in blob or f" {marker.strip()} " in padded for marker in markers)


def _infer_scene_kind(*, window_title: str, process_name: str, text_blob: str) -> tuple[str, float, tuple[str, ...]]:
    window_blob = _norm(f"{window_title} {process_name}")
    content_blob = _norm(text_blob)
    joined = f"{window_blob} {content_blob}".strip()
    evidence: list[str] = []

    # Nội dung OCR/UIA có trọng lượng cao hơn tên process. Một cửa sổ Chrome có
    # thể đang chạy game web, xem video hoặc đọc tài liệu, loài người vốn thích
    # nhét cả đời mình vào một tab nên không được phân loại chỉ bằng executable.
    if _contains_any(content_blob, _GAME_MARKERS):
        evidence.append("screen_text:game_markers")
        return "game_likely", 0.82, tuple(evidence)
    if _contains_any(window_blob, _GAME_MARKERS):
        evidence.append("window:game_marker")
        return "game_possible", 0.62, tuple(evidence)
    if _contains_any(joined, _CODE_MARKERS):
        evidence.append("screen_or_window:code_markers")
        return "development", 0.78 if _contains_any(content_blob, _CODE_MARKERS) else 0.64, tuple(evidence)
    if _contains_any(joined, _MEDIA_MARKERS):
        evidence.append("screen_or_window:media_markers")
        return "media", 0.72, tuple(evidence)
    if _contains_any(joined, _CHAT_MARKERS):
        evidence.append("screen_or_window:private_communication")
        return "communication", 0.72, tuple(evidence)
    if _contains_any(window_blob, _BROWSER_MARKERS):
        evidence.append("window:browser_marker")
        return "browser", 0.52, tuple(evidence)
    return "unknown", 0.25 if window_blob else 0.0, ()


@dataclass(frozen=True, slots=True)
class AmbientScreenContext:
    revision: int = 0
    window_title: str = ""
    process_name: str = ""
    backend: str = ""
    ocr_active: bool = False
    privacy_blocked: bool = False
    age_seconds: float = 9999.0
    changed_ratio: float = 0.0
    window_changed: bool = False
    content_changed: bool = False
    scene_kind: str = "unknown"
    scene_confidence: float = 0.0
    visible_text: tuple[str, ...] = ()
    changed_text: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    scene_evidence: tuple[str, ...] = ()

    @property
    def fresh(self) -> bool:
        return self.age_seconds <= 12.0 and not self.privacy_blocked

    @property
    def meaningful_delta(self) -> bool:
        return self.fresh and (self.window_changed or self.content_changed or self.changed_ratio >= 0.035)

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "window_title": self.window_title,
            "process_name": self.process_name,
            "backend": self.backend,
            "ocr_active": self.ocr_active,
            "privacy_blocked": self.privacy_blocked,
            "fresh": self.fresh,
            "age_seconds": round(self.age_seconds, 2),
            "changed_ratio": round(self.changed_ratio, 4),
            "window_changed": self.window_changed,
            "content_changed": self.content_changed,
            "meaningful_delta": self.meaningful_delta,
            "scene_kind": self.scene_kind,
            "scene_confidence": round(self.scene_confidence, 3),
            "visible_text": list(self.visible_text),
            "changed_text": list(self.changed_text),
            "evidence_refs": list(self.evidence_refs),
            "scene_evidence": list(self.scene_evidence),
            "epistemic_note": (
                "scene_kind is a low-risk classification, not proof of user intent. "
                "Use visible_text/changed_text for direct claims; otherwise ask or hedge."
            ),
        }

    def prompt_context(self) -> str:
        if self.privacy_blocked:
            return "screen_context: privacy-blocked; do not mention or infer screen contents."
        lines = [
            "screen_context:",
            f"- window_title: {self.window_title or '<unknown>'}",
            f"- process_name: {self.process_name or '<unknown>'}",
            f"- backend: {self.backend or '<unknown>'}; ocr_active={str(self.ocr_active).lower()}",
            f"- fresh={str(self.fresh).lower()}; age_seconds={self.age_seconds:.2f}",
            f"- scene_kind={self.scene_kind}; scene_confidence={self.scene_confidence:.2f}",
            f"- window_changed={str(self.window_changed).lower()}; content_changed={str(self.content_changed).lower()}; changed_ratio={self.changed_ratio:.4f}",
        ]
        if self.changed_text:
            lines.append("- changed_screen_text:")
            lines.extend(f"  - {item}" for item in self.changed_text)
        elif self.visible_text:
            lines.append("- visible_screen_text:")
            lines.extend(f"  - {item}" for item in self.visible_text)
        lines.extend(
            (
                "epistemic_contract:",
                "- Directly mention only fresh visible/changed text or the literal app/window name.",
                "- scene_kind is only a hypothesis. Ask or hedge; never assert the user's intent, mood, success, failure, or exact activity from it.",
                "- A game-like scene may justify a natural question about what is happening on screen, not a claim that the user is definitely playing.",
                "- Do not surface private communication content.",
            )
        )
        return "\n".join(lines)


class AmbientScreenTracker:
    """Giữ delta giữa hai snapshot mà không ghi nội dung màn hình vào memory."""

    def __init__(self) -> None:
        self._last_revision = 0
        self._last_window_key = ""
        self._last_hashes: set[str] = set()

    def observe(
        self,
        screen_snapshot: Any,
        *,
        telemetry: Mapping[str, Any] | None = None,
        now: float | None = None,
        max_items: int = 8,
    ) -> AmbientScreenContext:
        now = time.time() if now is None else float(now)
        telemetry = telemetry if isinstance(telemetry, Mapping) else {}
        if screen_snapshot is None:
            return self._from_telemetry_only(telemetry, now=now)

        window = getattr(screen_snapshot, "window", None)
        window_title = _compact(
            getattr(window, "title", "")
            or telemetry.get("active_window_title", "")
            or telemetry.get("active_app", ""),
            220,
        )
        process_name = _compact(
            getattr(window, "process_name", "") or telemetry.get("active_app", ""),
            120,
        )
        privacy_blocked = bool(getattr(screen_snapshot, "privacy_blocked", False))
        captured_at = float(getattr(screen_snapshot, "captured_at", 0.0) or 0.0)
        age = max(0.0, now - captured_at) if captured_at > 0.0 else 9999.0
        revision = max(0, int(getattr(screen_snapshot, "revision", 0) or 0))
        backend = _compact(getattr(screen_snapshot, "backend", ""), 40)
        changed_ratio = max(0.0, min(1.0, float(getattr(screen_snapshot, "changed_ratio", 0.0) or 0.0)))
        window_key = _norm(f"{process_name}|{window_title}")
        window_changed = bool(self._last_window_key and window_key and window_key != self._last_window_key)

        selected: list[tuple[float, Any, str]] = []
        current_hashes: set[str] = set()
        if not privacy_blocked:
            for block in tuple(getattr(screen_snapshot, "blocks", ()) or ()):
                text = _compact(getattr(block, "text", ""), 320)
                if len(text) < 2:
                    continue
                block_age = max(0.0, now - float(getattr(block, "captured_at", 0.0) or 0.0))
                if block_age > 16.0:
                    continue
                source = str(getattr(block, "source", "screen_text") or "screen_text")
                confidence = max(0.0, min(1.0, float(getattr(block, "confidence", 0.0) or 0.0)))
                digest = str(getattr(block, "content_hash", "") or "") or _hash_text(text)
                current_hashes.add(digest)
                freshness = max(0.0, 1.0 - block_age / 16.0)
                semantic_bonus = 0.12 if len(text.split()) >= 3 else 0.0
                source_bonus = 0.10 if source == "ocr" else 0.08 if source == "uia" else 0.0
                selected.append((0.54 * confidence + 0.24 * freshness + semantic_bonus + source_bonus, block, digest))
        selected.sort(key=lambda item: item[0], reverse=True)
        selected = selected[: max(1, int(max_items))]

        visible_items = [_compact(getattr(block, "text", ""), 260) for _, block, _ in selected]
        changed_items = [
            _compact(getattr(block, "text", ""), 260)
            for _, block, digest in selected
            if revision > self._last_revision and (window_changed or digest not in self._last_hashes)
        ]
        evidence_refs_list = [
            f"screen:{str(getattr(block, 'block_id', '') or digest)}"
            for _, block, digest in selected
        ]

        # Telemetry content_metadata có thể chứa cache OCR/DOM/accessibility tươi
        # hơn worker foreground, nhất là game hoặc canvas nơi UIA gần như mù.
        # Store vẫn tồn tại trong trường hợp đó nên không được chỉ fallback khi
        # screen_snapshot=None.
        content_meta = telemetry.get("content_metadata", {})
        content_meta = content_meta if isinstance(content_meta, Mapping) else {}
        meta_privacy = _norm(content_meta.get("privacy_level", "normal")) in {"private", "sensitive"}
        meta_text = _compact(
            content_meta.get("visible_text_sample", "")
            or content_meta.get("caption_sample", "")
            or content_meta.get("title", ""),
            320,
        )
        meta_source = str(content_meta.get("source", "") or "")
        if meta_text and not privacy_blocked and not meta_privacy:
            meta_digest = _hash_text(meta_text)
            current_hashes.add(meta_digest)
            if meta_digest not in {_hash_text(item) for item in visible_items}:
                visible_items.append(meta_text)
                evidence_refs_list.append(f"screen_content:{meta_source or 'telemetry'}")
            if revision > self._last_revision and (window_changed or meta_digest not in self._last_hashes):
                changed_items.append(meta_text)

        visible_text = tuple(visible_items[: max(1, int(max_items))])
        changed_text = tuple(dict.fromkeys(changed_items[: max(1, int(max_items))]))
        content_changed = bool(changed_text) or bool(revision > self._last_revision and changed_ratio >= 0.025)
        text_blob = " ".join(visible_text)
        scene_kind, scene_confidence, scene_evidence = _infer_scene_kind(
            window_title=window_title,
            process_name=process_name,
            text_blob=text_blob,
        )
        evidence_refs = tuple(dict.fromkeys(evidence_refs_list))

        self._last_revision = max(self._last_revision, revision)
        self._last_window_key = window_key or self._last_window_key
        self._last_hashes = current_hashes

        return AmbientScreenContext(
            revision=revision,
            window_title=window_title,
            process_name=process_name,
            backend=backend,
            ocr_active=(backend not in {"", "none", "uia_only"}) or meta_source == "ocr_cache",
            privacy_blocked=privacy_blocked,
            age_seconds=age,
            changed_ratio=changed_ratio,
            window_changed=window_changed,
            content_changed=content_changed,
            scene_kind=scene_kind,
            scene_confidence=scene_confidence,
            visible_text=visible_text,
            changed_text=changed_text,
            evidence_refs=evidence_refs,
            scene_evidence=scene_evidence,
        )

    def _from_telemetry_only(self, telemetry: Mapping[str, Any], *, now: float) -> AmbientScreenContext:
        content = telemetry.get("content_metadata", {})
        content = content if isinstance(content, Mapping) else {}
        privacy = _norm(content.get("privacy_level", "normal")) in {"private", "sensitive"}
        visible = _compact(
            content.get("visible_text_sample", "")
            or content.get("caption_sample", "")
            or content.get("title", ""),
            320,
        )
        window_title = _compact(
            telemetry.get("active_window_title", "") or telemetry.get("active_app", ""),
            220,
        )
        process_name = _compact(telemetry.get("active_app", ""), 120)
        source = str(content.get("source", "") or "")
        scene_kind, scene_confidence, scene_evidence = _infer_scene_kind(
            window_title=window_title,
            process_name=process_name,
            text_blob=visible,
        )
        return AmbientScreenContext(
            window_title=window_title,
            process_name=process_name,
            backend=source,
            ocr_active=source == "ocr_cache",
            privacy_blocked=privacy,
            age_seconds=0.0 if visible else 9999.0,
            scene_kind=scene_kind,
            scene_confidence=scene_confidence,
            visible_text=(visible,) if visible and not privacy else (),
            evidence_refs=(f"screen_content:{source or 'telemetry'}",) if visible and not privacy else (),
            scene_evidence=scene_evidence,
        )


__all__ = ["AmbientScreenContext", "AmbientScreenTracker"]
