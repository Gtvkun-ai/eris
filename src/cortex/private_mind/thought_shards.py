# -*- coding: utf-8 -*-
"""Persistent micro-thought shards + deep-reflection ledger for Inner Diary V80.

Phân vai rõ ràng:
- Gemma cập nhật 5 mảnh sống (now/next/concern/reflection/want) từ state/evidence đã có.
- DeepSeek KHÔNG điền 5 ô. Nó chỉ thỉnh thoảng tổng hợp lịch sử shard thành một
  deep reflection có dẫn chiếu nguồn và các candidate học dài hạn chưa được apply.

Module này chỉ giữ state/provenance. Quyền public speech vẫn ở pipeline/Neuro.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


SHARD_SLOTS = ("now", "next", "concern", "reflection", "want")


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


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, "") or default))
    except (TypeError, ValueError):
        return int(default)


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return max(0.0, min(1.0, float(default)))


def _short(value: Any, limit: int = 360) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _norm(value: Any) -> str:
    return " ".join(str(value or "").casefold().split()).strip()


def _stable_id(prefix: str, *parts: object) -> str:
    blob = "\x1f".join(str(x or "") for x in parts)
    return f"{prefix}:{hashlib.sha1(blob.encode('utf-8')).hexdigest()[:20]}"


@dataclass(slots=True)
class ThoughtShardConfig:
    enabled: bool = field(default_factory=lambda: _env_flag("ERIS_INNER_DIARY_THOUGHT_SHARDS_ENABLED", True))
    path: str = field(default_factory=lambda: str(os.getenv(
        "ERIS_INNER_DIARY_SHARDS_PATH",
        os.path.join(os.getenv("ERIS_MEMORY_CORE_DIR", "memory_core"), "inner_diary_thought_shards.json"),
    ) or "memory_core/inner_diary_thought_shards.json"))
    refresh_min_seconds: float = field(default_factory=lambda: max(5.0, _env_float("ERIS_INNER_DIARY_SHARD_MIN_REFRESH_SEC", 25.0)))
    active_seconds: float = field(default_factory=lambda: max(120.0, _env_float("ERIS_INNER_DIARY_SHARD_ACTIVE_SEC", 1200.0)))
    fading_seconds: float = field(default_factory=lambda: max(600.0, _env_float("ERIS_INNER_DIARY_SHARD_FADING_SEC", 7200.0)))
    max_history: int = field(default_factory=lambda: max(20, _env_int("ERIS_INNER_DIARY_SHARD_HISTORY_MAX", 72)))
    max_reflections: int = field(default_factory=lambda: max(4, _env_int("ERIS_INNER_DIARY_DEEP_REFLECTION_MAX", 20)))
    reflection_min_seconds: float = field(default_factory=lambda: max(120.0, _env_float("ERIS_INNER_DIARY_DEEP_REFLECTION_MIN_SEC", 1200.0)))
    reflection_max_seconds: float = field(default_factory=lambda: max(600.0, _env_float("ERIS_INNER_DIARY_DEEP_REFLECTION_MAX_SEC", 3600.0)))
    reflection_urgent_seconds: float = field(default_factory=lambda: max(60.0, _env_float("ERIS_INNER_DIARY_DEEP_REFLECTION_URGENT_SEC", 300.0)))
    reflection_min_new_shards: int = field(default_factory=lambda: max(2, _env_int("ERIS_INNER_DIARY_DEEP_REFLECTION_MIN_SHARDS", 6)))
    urgent_salience: float = field(default_factory=lambda: _clamp01(_env_float("ERIS_INNER_DIARY_DEEP_REFLECTION_URGENT_SALIENCE", 0.82)))


class ThoughtShardStore:
    """State bền cho 5 mảnh Gemma và các episode DeepSeek sâu hơn."""

    def __init__(self, *, config: ThoughtShardConfig | None = None, logger: Any = None) -> None:
        self.config = config or ThoughtShardConfig()
        self.logger = logger
        self._lock = threading.RLock()
        self._slots: dict[str, dict[str, Any]] = {}
        self._history: list[dict[str, Any]] = []
        self._reflections: list[dict[str, Any]] = []
        self._last_signature = ""
        self._last_refresh_at = 0.0
        self._last_reflection_at = 0.0
        self._last_shard_writer: dict[str, Any] = {}
        self._last_reflection_writer: dict[str, Any] = {}
        self._loaded = False
        self._load()

    @classmethod
    def from_env(cls, *, logger: Any = None) -> "ThoughtShardStore":
        return cls(config=ThoughtShardConfig(), logger=logger)

    # ------------------------------------------------------------ shard lane

    def should_refresh(self, *, signature: str, now: float | None = None, urgent: bool = False) -> bool:
        if not self.config.enabled:
            return False
        current = time.time() if now is None else float(now)
        with self._lock:
            changed = bool(signature and signature != self._last_signature)
            missing = not any(_short(x.get("text")) for x in self._slots.values())
            elapsed = current - float(self._last_refresh_at or 0.0)
            if missing and elapsed >= min(8.0, self.config.refresh_min_seconds):
                return True
            if urgent and changed and elapsed >= min(10.0, self.config.refresh_min_seconds):
                return True
            return changed and elapsed >= self.config.refresh_min_seconds

    def note_refresh_attempt(self, *, signature: str, now: float | None = None) -> None:
        current = time.time() if now is None else float(now)
        with self._lock:
            self._last_refresh_at = current
            if signature:
                self._last_signature = str(signature)
            self._persist_locked()

    def apply_shard_output(
        self,
        output: Mapping[str, Any] | None,
        *,
        packet: Mapping[str, Any],
        writer_meta: Mapping[str, Any] | None = None,
        signature: str = "",
        now: float | None = None,
    ) -> int:
        """Apply partial Gemma updates nhưng chỉ khi mỗi shard cite atom thật."""
        if not self.config.enabled or not isinstance(output, Mapping):
            return 0
        current = time.time() if now is None else float(now)
        atoms = [dict(x) for x in (packet.get("atoms") or []) if isinstance(x, Mapping)]
        atom_index = {str(x.get("id") or ""): x for x in atoms if str(x.get("id") or "")}
        updates = list(output.get("updates") or [])
        applied = 0
        with self._lock:
            for raw in updates[:10]:
                if not isinstance(raw, Mapping):
                    continue
                slot = str(raw.get("slot") or "").strip().lower()
                if slot not in SHARD_SLOTS:
                    continue
                text = _short(raw.get("text"), 260)
                if not text:
                    continue
                atom_ids = [str(x) for x in (raw.get("atom_ids") or raw.get("source_ids") or []) if str(x) in atom_index][:12]
                # Gemma là micro-cognition owner, nhưng không được dựng thought từ hư không.
                if not atom_ids:
                    continue
                source_ids: list[str] = []
                salience = _clamp01(raw.get("salience"), 0.5)
                for atom_id in atom_ids:
                    atom = atom_index[atom_id]
                    source_ids.extend(str(x) for x in (atom.get("source_ids") or []) if str(x))
                    salience = max(salience, _clamp01(atom.get("salience"), 0.0))
                confidence = _clamp01(raw.get("confidence"), 0.68)
                previous = self._slots.get(slot, {})
                changed = _norm(previous.get("text")) != _norm(text)
                shard_id = _stable_id("shard", slot, _norm(text))
                entry = {
                    "id": shard_id,
                    "slot": slot,
                    "text": text,
                    "created_at": float(previous.get("created_at", current) or current) if not changed else round(current, 3),
                    "updated_at": round(current, 3),
                    "last_reinforced_at": round(current, 3),
                    "confidence": round(confidence, 3),
                    "salience": round(salience, 3),
                    "atom_ids": atom_ids,
                    "source_ids": list(dict.fromkeys(source_ids))[:24],
                    "state": "active",
                    "writer": dict(writer_meta or {}),
                    "provenance": "gemma_micro_cognition",
                }
                self._slots[slot] = entry
                if changed:
                    self._history.append(dict(entry))
                    applied += 1
                else:
                    # reinforcement không làm phình history nhưng vẫn giữ shard sống.
                    self._slots[slot]["created_at"] = float(previous.get("created_at", current) or current)
                    applied += 1
            self._last_refresh_at = current
            if signature:
                self._last_signature = str(signature)
            self._last_shard_writer = dict(writer_meta or {})
            self._trim_locked(current)
            self._persist_locked()
        return applied

    # ------------------------------------------------------ DeepSeek reflection

    def reflection_due(self, *, now: float | None = None) -> bool:
        if not self.config.enabled:
            return False
        current = time.time() if now is None else float(now)
        with self._lock:
            new_rows = [x for x in self._history if float(x.get("updated_at", 0.0) or 0.0) > self._last_reflection_at]
            if len(new_rows) < 2:
                return False
            elapsed = current - float(self._last_reflection_at or 0.0)
            if self._last_reflection_at <= 0.0:
                return len(new_rows) >= self.config.reflection_min_new_shards
            high = max((_clamp01(x.get("salience"), 0.0) for x in new_rows), default=0.0)
            if high >= self.config.urgent_salience and elapsed >= self.config.reflection_urgent_seconds:
                return True
            if len(new_rows) >= self.config.reflection_min_new_shards and elapsed >= self.config.reflection_min_seconds:
                return True
            return len(new_rows) >= 3 and elapsed >= self.config.reflection_max_seconds

    def reflection_packet(self, *, context: Mapping[str, Any] | None = None, now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        with self._lock:
            self._age_slots_locked(current)
            slots = [dict(self._slots[x]) for x in SHARD_SLOTS if x in self._slots and self._slots[x].get("state") in {"active", "fading"}]
            history = [dict(x) for x in self._history[-28:]]
            previous = [dict(x) for x in self._reflections[-3:]]
        evidence_refs: list[str] = []
        for row in history:
            evidence_refs.append(str(row.get("id") or ""))
            evidence_refs.extend(str(x) for x in (row.get("atom_ids") or []) if str(x))
            evidence_refs.extend(str(x) for x in (row.get("source_ids") or []) if str(x))
        return {
            "schema": "eris.inner_diary.deep_reflection.packet.v80",
            "rule": (
                "Synthesize causal meaning across actual Gemma thought-shard history. "
                "Do not invent events. Learning outputs are candidates only and must not be auto-applied."
            ),
            "now": round(current, 3),
            "slots": slots,
            "history": history,
            "previous_reflections": previous,
            "context": dict(context or {}),
            "evidence_refs": list(dict.fromkeys(x for x in evidence_refs if x))[:120],
        }

    def record_deep_reflection(
        self,
        output: Mapping[str, Any] | None,
        *,
        packet: Mapping[str, Any],
        writer_meta: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        if not self.config.enabled or not isinstance(output, Mapping):
            return None
        current = time.time() if now is None else float(now)
        allowed = {str(x) for x in (packet.get("evidence_refs") or []) if str(x)}
        refs = [str(x) for x in (output.get("evidence_refs") or output.get("source_ids") or []) if str(x) in allowed][:24]
        insight = _short(output.get("insight"), 700)
        if not insight or not refs:
            return None
        confidence = _clamp01(output.get("confidence"), 0.65)
        candidate_raw = output.get("self_model_candidate")
        candidate: dict[str, Any] = {}
        if isinstance(candidate_raw, Mapping):
            trait = _short(candidate_raw.get("trait"), 100)
            direction = _short(candidate_raw.get("direction"), 48)
            c_refs = [str(x) for x in (candidate_raw.get("evidence_refs") or []) if str(x) in allowed][:16]
            if trait and direction and c_refs:
                candidate = {
                    "trait": trait,
                    "direction": direction,
                    "confidence": round(_clamp01(candidate_raw.get("confidence"), confidence), 3),
                    "evidence_refs": c_refs,
                    "status": "candidate_only",
                }
        entry = {
            "id": _stable_id("deep_reflection", _norm(insight), int(current // 300)),
            "insight": insight,
            "unresolved_tension": _short(output.get("unresolved_tension"), 420),
            "hypothesis": _short(output.get("hypothesis"), 420),
            "relational_lesson": _short(output.get("relational_lesson"), 420),
            "future_direction": _short(output.get("future_direction"), 420),
            "self_model_candidate": candidate,
            "confidence": round(confidence, 3),
            "evidence_refs": refs,
            "created_at": round(current, 3),
            "writer": dict(writer_meta or {}),
            "status": "retained",
            "contract": "reflection_only; learning candidates are not auto-applied",
        }
        with self._lock:
            self._reflections.append(entry)
            self._last_reflection_at = current
            self._last_reflection_writer = dict(writer_meta or {})
            self._trim_locked(current)
            self._persist_locked()
        return dict(entry)

    def note_reflection_attempt(self, *, now: float | None = None) -> None:
        # Không đẩy last_reflection_at khi model lỗi; nhưng giữ timestamp riêng qua
        # writer throttle. Method tồn tại để API rõ nghĩa và tương lai dễ mở rộng.
        _ = time.time() if now is None else float(now)

    # --------------------------------------------------------------- projection

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        with self._lock:
            self._age_slots_locked(current)
            slots = {
                slot: dict(item)
                for slot, item in self._slots.items()
                if item.get("state") in {"active", "fading"}
            }
            latest = dict(self._reflections[-1]) if self._reflections else {}
            return {
                "schema": "eris.inner_diary.thought_shards.v80",
                "slots": slots,
                "history": [dict(x) for x in self._history[-20:]],
                "deep_reflection": latest,
                "deep_reflections": [dict(x) for x in self._reflections[-6:]],
                "last_refresh_at": round(float(self._last_refresh_at or 0.0), 3),
                "last_reflection_at": round(float(self._last_reflection_at or 0.0), 3),
                "shard_writer": dict(self._last_shard_writer),
                "reflection_writer": dict(self._last_reflection_writer),
            }

    # ---------------------------------------------------------------- internal

    def _age_slots_locked(self, now: float) -> None:
        for item in self._slots.values():
            age = max(0.0, now - float(item.get("last_reinforced_at", item.get("updated_at", now)) or now))
            if age <= self.config.active_seconds:
                item["state"] = "active"
            elif age <= self.config.fading_seconds:
                item["state"] = "fading"
            else:
                item["state"] = "expired"

    def _trim_locked(self, now: float) -> None:
        self._age_slots_locked(now)
        if len(self._history) > self.config.max_history:
            self._history = self._history[-self.config.max_history :]
        if len(self._reflections) > self.config.max_reflections:
            self._reflections = self._reflections[-self.config.max_reflections :]

    def _load(self) -> None:
        if self._loaded or not self.config.enabled:
            return
        self._loaded = True
        try:
            if not os.path.isfile(self.config.path):
                return
            with open(self.config.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, Mapping):
                return
            self._slots = {str(k): dict(v) for k, v in (data.get("slots") or {}).items() if str(k) in SHARD_SLOTS and isinstance(v, Mapping)}
            self._history = [dict(x) for x in data.get("history", []) if isinstance(x, Mapping)][-self.config.max_history :]
            self._reflections = [dict(x) for x in data.get("reflections", []) if isinstance(x, Mapping)][-self.config.max_reflections :]
            self._last_signature = str(data.get("last_signature") or "")
            self._last_refresh_at = float(data.get("last_refresh_at", 0.0) or 0.0)
            self._last_reflection_at = float(data.get("last_reflection_at", 0.0) or 0.0)
            self._last_shard_writer = dict(data.get("last_shard_writer") or {}) if isinstance(data.get("last_shard_writer"), Mapping) else {}
            self._last_reflection_writer = dict(data.get("last_reflection_writer") or {}) if isinstance(data.get("last_reflection_writer"), Mapping) else {}
        except Exception as exc:
            self._log("warning", "Thought shard store load failed, starting fresh: %s", exc)
            self._slots, self._history, self._reflections = {}, [], []

    def _persist_locked(self) -> None:
        if not self.config.enabled:
            return
        payload = {
            "schema": "eris.inner_diary.thought_shards.v80",
            "updated_at": round(time.time(), 3),
            "last_signature": self._last_signature,
            "last_refresh_at": round(float(self._last_refresh_at or 0.0), 3),
            "last_reflection_at": round(float(self._last_reflection_at or 0.0), 3),
            "last_shard_writer": dict(self._last_shard_writer),
            "last_reflection_writer": dict(self._last_reflection_writer),
            "slots": self._slots,
            "history": self._history,
            "reflections": self._reflections,
        }
        directory = os.path.dirname(self.config.path) or "."
        try:
            os.makedirs(directory, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(prefix=".inner_shards_", suffix=".tmp", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, ensure_ascii=False, indent=2)
                os.replace(tmp_path, self.config.path)
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
        except Exception as exc:
            self._log("warning", "Thought shard store persist failed: %s", exc)

    def _log(self, level: str, msg: str, *args: Any) -> None:
        fn = getattr(self.logger, level, None) if self.logger is not None else None
        if callable(fn):
            try:
                fn(msg, *args)
            except Exception:
                pass


__all__ = ["SHARD_SLOTS", "ThoughtShardConfig", "ThoughtShardStore"]
