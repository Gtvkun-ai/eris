# -*- coding: utf-8 -*-
"""Deep reflection writer cho Inner Diary V80.

V79 dùng DeepSeek để viết lại cả 5 ô. V80 cố ý bỏ việc đó:
- 5 thought-shard live do Gemma cập nhật thường xuyên;
- DeepSeek chỉ wake thưa hơn để tìm causal pattern, tension, relational lesson và
  candidate self-model dựa trên lịch sử shard thật.

Tên class giữ lại để không phá import cũ. Nó giờ là *deep reflection writer*.
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


def _short(value: Any, limit: int = 500) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


class InnerDiaryWriter:
    """DeepSeek reflection lane, có persistence qua ThoughtShardStore."""

    def __init__(
        self,
        *,
        adapter: Any = None,
        fallback_adapter: Any = None,
        state_store: Any = None,
        throttle_seconds: float | None = None,
        enabled: bool | None = None,
        logger: Any = None,
    ) -> None:
        self.adapter = adapter
        self.fallback_adapter = fallback_adapter
        self.state_store = state_store
        self.enabled = _env_flag("ERIS_INNER_DIARY_AI", True) if enabled is None else bool(enabled)
        self.throttle_seconds = (
            max(60.0, _env_float("ERIS_INNER_DIARY_DEEP_REFLECTION_RETRY_SEC", 180.0))
            if throttle_seconds is None
            else max(0.0, float(throttle_seconds))
        )
        self.logger = logger
        self.startup_grace_seconds = max(0.0, _env_float("ERIS_INNER_DIARY_STARTUP_GRACE_SEC", 20.0))
        self._created_at = time.time()
        self._last_call_at = 0.0
        self._last_signature = ""
        self._cached_voice: dict[str, Any] | None = None

    def maybe_write(self, digest: Mapping[str, Any], *, now: float | None = None) -> dict[str, Any] | None:
        """Trả deep-reflection gần nhất; chỉ gọi DeepSeek khi đủ material."""
        current = time.time() if now is None else float(now)
        # Compat V79 cho unit/plugin caller inject writer trực tiếp mà không có
        # ThoughtShardStore. Runtime V80 luôn có store nên không đi nhánh này.
        if self.state_store is None:
            return self._legacy_maybe_write(digest, now=current)

        latest = self._latest_voice(current)
        if latest is not None:
            self._cached_voice = latest
        if not self.enabled or self.adapter is None:
            return self._cached_voice
        if current - self._created_at < self.startup_grace_seconds:
            return self._cached_voice
        if current - self._last_call_at < self.throttle_seconds:
            return self._cached_voice

        store = self.state_store
        if store is not None:
            due_fn = getattr(store, "reflection_due", None)
            if callable(due_fn) and not bool(due_fn(now=current)):
                return self._cached_voice
            packet_fn = getattr(store, "reflection_packet", None)
            if not callable(packet_fn):
                return self._cached_voice
            packet = packet_fn(context=self._build_context(digest), now=current)
        else:
            # Compat test/caller cũ: vẫn có thể deep-reflect từ digest, nhưng không
            # có persistence hay trigger history thông minh.
            packet = self._legacy_packet(digest, now=current)
            if not packet.get("history"):
                return self._cached_voice

        self._last_call_at = current
        result = self._call(packet)
        if not isinstance(result, Mapping):
            return self._cached_voice
        clean = self._sanitize_reflection(result)
        if not clean.get("insight"):
            return self._cached_voice

        writer = _as_dict(result.get("_writer"))
        if store is not None:
            record_fn = getattr(store, "record_deep_reflection", None)
            if callable(record_fn):
                try:
                    recorded = record_fn(clean, packet=packet, writer_meta=writer, now=current)
                except Exception as exc:
                    self._log("warning", "Deep reflection store failed: %s", exc)
                    recorded = None
                if isinstance(recorded, Mapping):
                    self._cached_voice = self._voice_from_reflection(recorded)
                    return self._cached_voice
        # No store: output remains ephemeral but still useful for old callers.
        clean["writer"] = writer
        self._cached_voice = self._voice_from_reflection(clean)
        return self._cached_voice

    def _legacy_maybe_write(self, digest: Mapping[str, Any], *, now: float) -> dict[str, Any] | None:
        if not self.enabled or self.adapter is None:
            return None
        if now - self._created_at < self.startup_grace_seconds:
            return self._cached_voice
        facts = self._legacy_facts(digest)
        if not any(str(facts.get(key, "") or "").strip() for key in ("hien_tai", "ban_tam", "phan_tich", "tuong_lai", "muon_noi")):
            return self._cached_voice
        signature = hashlib.sha1(json.dumps(facts, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        if signature == self._last_signature and self._cached_voice is not None:
            return self._cached_voice
        if now - self._last_call_at < self.throttle_seconds:
            return self._cached_voice
        fn = getattr(self.adapter, "write_inner_diary", None)
        if not callable(fn):
            return self._cached_voice
        self._last_call_at = now
        try:
            raw = fn(facts)
        except Exception as exc:
            self._log("warning", "Legacy InnerDiary call failed: %s", exc)
            raw = None
        voice = self._legacy_sanitize(raw)
        if voice is None:
            return self._cached_voice
        self._cached_voice = voice
        self._last_signature = signature
        return voice

    def _legacy_facts(self, digest: Mapping[str, Any]) -> dict[str, Any]:
        menu = _as_dict(digest.get("menu"))
        current = _as_dict(menu.get("current_thought") or digest.get("current"))
        temporary = _as_dict(menu.get("temporary_thoughts") or digest.get("temporary"))
        retained = _as_dict(menu.get("retained_thoughts") or digest.get("retained"))
        future_bias = _as_dict(menu.get("future_bias") or digest.get("future_bias"))
        concerns = _as_list(menu.get("open_concerns") or retained.get("concerns"))
        surface_queue = _as_list(menu.get("surface_queue") or digest.get("surface_queue"))
        residue = _as_dict(menu.get("diary_residue") or digest.get("diary_residue"))
        entries = _as_list(retained.get("diary_entries") or residue.get("diary_entries"))
        by_kind: dict[str, list[str]] = {}
        for raw in entries[:10]:
            item = _as_dict(raw)
            text = _short(item.get("text"), 180)
            if text:
                by_kind.setdefault(str(item.get("kind") or "reflection").lower(), []).append(text)
        concern_lines = []
        for raw in concerns[:4]:
            theme = _short(_as_dict(raw).get("theme"), 160)
            if theme:
                concern_lines.append(theme)
        concern_lines.extend(x for x in by_kind.get("concern", [])[:2] if x not in concern_lines)
        fragment_lines = []
        for raw in _as_list(temporary.get("fragments"))[:4]:
            claim = _short(_as_dict(raw).get("claim"), 160)
            if claim:
                fragment_lines.append(claim)
        fragment_lines.extend(x for x in by_kind.get("reflection", [])[:3] if x not in fragment_lines)
        future_lines = []
        for raw in _as_list(future_bias.get("inquiry_plan"))[:3]:
            item = _as_dict(raw)
            text = _short(item.get("question") or item.get("text") or item.get("topic") if item else raw, 140)
            if text:
                future_lines.append(text)
        future_lines.extend(x for x in by_kind.get("future", [])[:2] if x not in future_lines)
        surface_lines = []
        for raw in surface_queue[:3]:
            item = _as_dict(raw)
            text = _short(item.get("topic_seed") or item.get("text") or item.get("seed"), 140)
            if text:
                surface_lines.append(text)
        surface_lines.extend(x for x in by_kind.get("desire", [])[:2] if x not in surface_lines)
        current_text = _short(current.get("dominant_judgment"), 240) or next(iter(by_kind.get("current", [])), "")
        return {
            "hien_tai": current_text,
            "ban_tam": concern_lines[:6],
            "phan_tich": fragment_lines[:7],
            "tuong_lai": future_lines[:5],
            "muon_noi": surface_lines[:5],
            "memory_echoes": [],
            "retained_entries": [
                {
                    "kind": str(_as_dict(item).get("kind") or "reflection"),
                    "text": _short(_as_dict(item).get("text"), 180),
                    "state": str(_as_dict(item).get("state") or "active"),
                    "provenance": _as_list(_as_dict(item).get("provenance"))[:4],
                }
                for item in entries[:8]
                if _short(_as_dict(item).get("text"), 180)
            ],
        }

    @staticmethod
    def _legacy_sanitize(raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, Mapping):
            return None
        keys = ("hien_tai", "tuong_lai", "ban_tam", "phan_tich", "muon_noi", "memory_echo")
        out = {key: _short(raw.get(key), 240) for key in keys}
        writer = raw.get("_writer")
        if isinstance(writer, Mapping):
            out["_writer"] = dict(writer)
        if not any(out.get(key) for key in keys):
            return None
        return out

    def _call(self, packet: Mapping[str, Any]) -> Mapping[str, Any] | None:
        fn = getattr(self.adapter, "deep_reflect_inner_diary", None)
        if not callable(fn):
            fn = getattr(self.adapter, "write_inner_diary", None)
        try:
            result = fn(packet) if callable(fn) else None
        except Exception as exc:
            self._log("warning", "Deep reflection call failed: %s", exc)
            result = None
        if isinstance(result, Mapping):
            # Compat adapter có thể trả {_deep_reflection:{...}, phan_tich:"..."}.
            nested = result.get("_deep_reflection")
            if isinstance(nested, Mapping):
                payload = dict(nested)
                if isinstance(result.get("_writer"), Mapping):
                    payload["_writer"] = dict(result.get("_writer") or {})
                return payload
            return dict(result)

        fb = self.fallback_adapter
        fb_fn = getattr(fb, "deep_reflect_inner_diary", None) if fb is not None else None
        if not callable(fb_fn) and fb is not None:
            fb_fn = getattr(fb, "write_inner_diary", None)
        if callable(fb_fn):
            try:
                return fb_fn(packet)
            except Exception as exc:
                self._log("warning", "Deep reflection fallback failed: %s", exc)
        return None

    def _latest_voice(self, now: float) -> dict[str, Any] | None:
        store = self.state_store
        snapshot_fn = getattr(store, "snapshot", None) if store is not None else None
        if not callable(snapshot_fn):
            return self._cached_voice
        try:
            snapshot = snapshot_fn(now=now)
        except Exception:
            return self._cached_voice
        reflection = _as_dict(snapshot.get("deep_reflection"))
        if not _short(reflection.get("insight"), 700):
            return self._cached_voice
        return self._voice_from_reflection(reflection)

    @staticmethod
    def _voice_from_reflection(reflection: Mapping[str, Any]) -> dict[str, Any]:
        writer = _as_dict(reflection.get("writer") or reflection.get("_writer"))
        return {
            "phan_tich": _short(reflection.get("insight"), 700),
            "_writer": writer,
            "_deep_reflection": dict(reflection),
        }

    @staticmethod
    def _sanitize_reflection(raw: Mapping[str, Any]) -> dict[str, Any]:
        candidate = _as_dict(raw.get("self_model_candidate"))
        return {
            "insight": _short(raw.get("insight") or raw.get("phan_tich"), 700),
            "unresolved_tension": _short(raw.get("unresolved_tension"), 420),
            "hypothesis": _short(raw.get("hypothesis"), 420),
            "relational_lesson": _short(raw.get("relational_lesson"), 420),
            "future_direction": _short(raw.get("future_direction"), 420),
            "confidence": raw.get("confidence", 0.65),
            "evidence_refs": [str(x) for x in _as_list(raw.get("evidence_refs") or raw.get("source_ids")) if str(x)][:24],
            "self_model_candidate": {
                "trait": _short(candidate.get("trait"), 100),
                "direction": _short(candidate.get("direction"), 48),
                "confidence": candidate.get("confidence", 0.0),
                "evidence_refs": [str(x) for x in _as_list(candidate.get("evidence_refs")) if str(x)][:16],
            } if candidate else {},
        }

    def _build_context(self, digest: Mapping[str, Any]) -> dict[str, Any]:
        menu = _as_dict(digest.get("menu"))
        current = _as_dict(menu.get("current_thought") or digest.get("current"))
        retained = _as_dict(menu.get("retained_thoughts") or digest.get("retained"))
        dossier = _as_dict(menu.get("evidence_dossier") or digest.get("evidence_dossier"))
        individual = _as_dict(digest.get("persistent_individual") or menu.get("persistent_individual"))
        continuous = _as_dict(individual.get("continuous_self"))
        concerns = []
        for raw in _as_list(menu.get("open_concerns") or retained.get("concerns"))[:5]:
            item = _as_dict(raw)
            theme = _short(item.get("theme"), 180)
            if theme:
                concerns.append({
                    "id": _short(item.get("id") or item.get("concern_id"), 120),
                    "theme": theme,
                    "pressure": item.get("pressure", item.get("activation", 0.0)),
                })
        return {
            "dominant_judgment": _short(current.get("dominant_judgment"), 260),
            "concerns": concerns,
            "continuous_self": {
                "orientation": _short(continuous.get("orientation"), 80),
                "dominant_motive": _short(continuous.get("dominant_motive"), 120),
                "top_concern": _as_dict(continuous.get("top_concern")),
                "active_commitment": _as_dict(continuous.get("active_commitment")),
                "tensions": _as_list(continuous.get("tensions"))[:4],
            },
            "surface_outcome": _as_dict(dossier.get("surface_outcome")),
        }

    def _legacy_packet(self, digest: Mapping[str, Any], *, now: float) -> dict[str, Any]:
        retained = _as_dict(digest.get("retained"))
        history = []
        refs = []
        for i, raw in enumerate(_as_list(retained.get("diary_entries"))[:16]):
            item = _as_dict(raw)
            text = _short(item.get("text"), 240)
            if not text:
                continue
            rid = _short(item.get("id"), 120) or f"legacy:{i}"
            history.append({"id": rid, "slot": str(item.get("kind") or "reflection"), "text": text})
            refs.append(rid)
        return {
            "schema": "eris.inner_diary.deep_reflection.legacy.v80",
            "now": now,
            "history": history,
            "slots": [],
            "previous_reflections": [],
            "context": self._build_context(digest),
            "evidence_refs": refs,
        }

    def _log(self, level: str, msg: str, *args: Any) -> None:
        fn = getattr(self.logger, level, None) if self.logger is not None else None
        if callable(fn):
            try:
                fn(msg, *args)
            except Exception:
                pass
