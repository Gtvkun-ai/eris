# -*- coding: utf-8 -*-
"""
cortex/private_mind/inner_diary_writer.py

Biến dữ kiện nội tâm thô (judgment/concern/fragment/future/surface) thành nhật ký
giọng Eris (ngôi thứ nhất) thông qua một lời gọi LLM, có:
- throttle theo thời gian,
- chỉ gọi lại khi nội dung đổi (content signature),
- cache kết quả để UI luôn có giọng Eris giữa các lần refresh,
- fallback êm: lỗi/tắt → trả None để renderer dùng text thô.

Không bao giờ được làm chết tick. Mọi lỗi nuốt êm.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Mapping


def _env_flag(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off", "none"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return float(default)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _short(value: Any, limit: int = 200) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


class InnerDiaryWriter:
    """Viết nhật ký nội tâm giọng Eris từ digest, có throttle/cache."""

    def __init__(
        self,
        *,
        adapter: Any = None,
        fallback_adapter: Any = None,
        throttle_seconds: float | None = None,
        enabled: bool | None = None,
        logger: Any = None,
    ) -> None:
        self.adapter = adapter
        self.fallback_adapter = fallback_adapter
        self.enabled = _env_flag("ERIS_INNER_DIARY_AI", True) if enabled is None else bool(enabled)
        self.throttle_seconds = (
            max(15.0, _env_float("ERIS_INNER_DIARY_AI_SEC", 120.0))
            if throttle_seconds is None
            else max(0.0, float(throttle_seconds))
        )
        self.logger = logger
        self._last_call_at: float = 0.0
        self._last_signature: str = ""
        self._cached_voice: dict[str, Any] | None = None

    def maybe_write(self, digest: Mapping[str, Any], *, now: float | None = None) -> dict[str, Any] | None:
        """Trả diary voice hoặc None nếu renderer nên dùng fallback thô."""

        if not self.enabled or self.adapter is None:
            return None
        write_fn = getattr(self.adapter, "write_inner_diary", None)
        if not callable(write_fn):
            return None

        facts = self._build_facts(digest)
        if not facts.get("hien_tai"):
            # Chưa có judgment để mà tự sự thì khỏi gọi LLM.
            return self._cached_voice

        now = time.time() if now is None else float(now)
        signature = self._signature(facts)

        # Nội dung không đổi → giữ bản giọng Eris đã viết, không gọi lại.
        if signature == self._last_signature and self._cached_voice is not None:
            return self._cached_voice
        # Có đổi nhưng chưa hết throttle → vẫn dùng bản cũ cho mượt.
        if now - self._last_call_at < self.throttle_seconds:
            return self._cached_voice

        self._last_call_at = now
        try:
            voice = write_fn(facts)
        except Exception as exc:
            self._log("warning", "InnerDiaryWriter call failed: %s", exc)
            voice = None

        voice = self._sanitize(voice)
        if voice is None:
            # Adapter chính (Gemini) chết/lỗi JSON → thử adapter DỰ PHÒNG (vd qwen
            # qua aggregator) để diary không câm. Lỗi tiếp thì giữ bản cũ.
            voice = self._try_fallback(facts)
        if voice is None:
            # Hết cả chính lẫn dự phòng: giữ bản cũ, throttle đã đặt nên không hammer.
            return self._cached_voice

        self._cached_voice = voice
        self._last_signature = signature
        return voice

    def _try_fallback(self, facts: Mapping[str, Any]) -> dict[str, Any] | None:
        """Gọi adapter dự phòng cho diary. Nuốt mọi lỗi, trả None nếu không cứu được."""
        fb = self.fallback_adapter
        if fb is None:
            return None
        fb_fn = getattr(fb, "write_inner_diary", None)
        if not callable(fb_fn):
            return None
        try:
            voice = fb_fn(facts)
        except Exception as exc:
            self._log("warning", "InnerDiary fallback call failed: %s", exc)
            return None
        voice = self._sanitize(voice)
        if voice is not None:
            self._log("info", "InnerDiary rescued by fallback adapter")
        return voice

    # ----------------------------------------------------------------- internal

    def _build_facts(self, digest: Mapping[str, Any]) -> dict[str, Any]:
        menu = _as_dict(digest.get("menu"))
        current = _as_dict(menu.get("current_thought") or digest.get("current"))
        temporary = _as_dict(menu.get("temporary_thoughts") or digest.get("temporary"))
        retained = _as_dict(menu.get("retained_thoughts") or digest.get("retained"))
        future_bias = _as_dict(menu.get("future_bias") or digest.get("future_bias"))
        concerns = _as_list(menu.get("open_concerns") or _as_dict(retained).get("concerns"))
        surface_queue = _as_list(menu.get("surface_queue") or digest.get("surface_queue"))

        concern_lines = []
        for c in [_as_dict(x) for x in concerns[:4]]:
            theme = _short(c.get("theme"), 160)
            if theme:
                concern_lines.append(theme)

        fragment_lines = []
        for f in [_as_dict(x) for x in _as_list(temporary.get("fragments"))[:4]]:
            claim = _short(f.get("claim"), 160)
            if claim:
                fragment_lines.append(claim)

        future_lines = []
        for item in _as_list(future_bias.get("inquiry_plan"))[:3]:
            text = item.get("question") or item.get("text") or item.get("topic") if isinstance(item, Mapping) else item
            text = _short(text, 140)
            if text:
                future_lines.append(text)
        if not future_lines:
            sb = _as_dict(future_bias.get("speech_bias"))
            for key in ("intent", "next_move", "stance", "tone"):
                v = _short(sb.get(key), 140)
                if v:
                    future_lines.append(v)
                    break

        surface_lines = []
        for s in [_as_dict(x) for x in surface_queue[:3]]:
            seed = _short(s.get("topic_seed") or s.get("text") or s.get("seed"), 140)
            if seed:
                surface_lines.append(seed)

        dossier = _as_dict(menu.get("evidence_dossier") or digest.get("evidence_dossier"))
        memory_echoes: list[dict[str, str]] = []
        for hit in [_as_dict(x) for x in _as_list(dossier.get("memory_hits"))[:4]]:
            text = _short(hit.get("text") or hit.get("summary") or hit.get("claim"), 180)
            if not text:
                continue
            memory_echoes.append({
                "text": text,
                "evidence_id": _short(hit.get("evidence_id") or hit.get("id"), 120),
                "source": _short(hit.get("source"), 80),
            })

        return {
            "hien_tai": _short(current.get("dominant_judgment"), 240),
            "ban_tam": concern_lines,
            "phan_tich": fragment_lines,
            "tuong_lai": future_lines,
            "muon_noi": surface_lines,
            "memory_echoes": memory_echoes,
        }

    def _signature(self, facts: Mapping[str, Any]) -> str:
        blob = json.dumps(facts, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()

    def _sanitize(self, voice: Any) -> dict[str, Any] | None:
        if not isinstance(voice, Mapping):
            return None
        keys = ("hien_tai", "tuong_lai", "ban_tam", "phan_tich", "muon_noi", "memory_echo")
        out = {k: _short(voice.get(k), 240) for k in keys}
        writer = voice.get("_writer")
        if isinstance(writer, Mapping):
            out["_writer"] = {
                "owner": _short(writer.get("owner"), 64),
                "role": _short(writer.get("role"), 48),
                "provider": _short(writer.get("provider"), 48),
                "model": _short(writer.get("model"), 96),
                "configured": bool(writer.get("configured")),
            }
        if not any(out.get(k) for k in keys):
            return None
        return out

    def _log(self, level: str, msg: str, *args: Any) -> None:
        fn = getattr(self.logger, level, None) if self.logger is not None else None
        if callable(fn):
            try:
                fn(msg, *args)
            except Exception:
                pass
