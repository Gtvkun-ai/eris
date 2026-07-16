# -*- coding: utf-8 -*-
"""content_engine.py - chất liệu biểu diễn ngắn hạn cho Eris.

Director quyết "được nói không", Performance quyết "diễn kiểu gì". ContentEngine
quyết "nếu nói, bám vào mồi nội dung nào". Nó không viết câu thay LLM; nó chỉ
cấp một hook nhỏ để candidate generator có vật liệu sống hơn: running bit, chủ
đề đang mở, hoặc dead-air recovery.

Nguyên tắc:
- Hook không được là fact mới. Nó chỉ là hướng diễn/ẩn dụ/cách tiếp cận.
- Coding scene không dùng random chatter.
- Khi thiếu screen evidence, hook chỉ được bám nhịp im/nội tâm, không claim màn hình.
- Có cooldown để một trò đùa không bị nhai lại thành template.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from memory.json_store_io import atomic_write_json
from runtime.director_context import DirectorContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ContentSeed:
    """Một mảnh content có nguồn gốc thật trong runtime.

    Seed khác hook: seed là "đời sống đã xảy ra", hook là "cách dùng seed trên
    sân khấu". Ví dụ seed từ session ledger: "bạn đang làm Eris thành VTuber";
    hook có thể là thread_tug/technical_nudge tuỳ scene.
    """

    id: str
    source: str
    text: str
    evidence_level: str
    freshness: float
    confidence: float
    risk: float = 0.15
    tags: tuple[str, ...] = ()
    # False nghĩa là seed chỉ dùng cho runtime/điều phối, không được biến thành
    # câu nói trước bạn hay audience. Ví dụ: tình trạng key pool, quota, browser.
    public_ok: bool = True
    observed_at: float = 0.0

    def to_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["tags"] = list(self.tags)
        return data


@dataclass(frozen=True, slots=True)
class ContentHook:
    id: str
    family: str
    tone: str
    allowed_use: str
    prompt_seed: str
    keywords: tuple[str, ...] = ()
    evidence_policy: str = "no_new_facts"
    cooldown_sec: float = 90.0
    body_only_ok: bool = True
    score_bonus: float = 0.08
    max_uses_per_session: int = 2
    content_seed: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["keywords"] = list(self.keywords)
        if isinstance(self.content_seed, dict):
            data["content_seed"] = dict(self.content_seed)
        return data


@dataclass(slots=True)
class TopicStackItem:
    key: str
    label: str
    strength: float
    last_seen: float
    source: str = ""
    tags: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["tags"] = list(self.tags)
        return data


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _lower_blob(*values: object) -> str:
    return " ".join(_clean(value).lower() for value in values if _clean(value))


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _compact(text: object, limit: int = 220) -> str:
    clean = _clean(text)
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)].rstrip() + "..."


def _seed_id(source: str, text: str) -> str:
    # Không cần hash crypto; chỉ cần id ổn định, ngắn cho debug/contract.
    blob = f"{source}:{text}".encode("utf-8", errors="ignore")
    value = 2166136261
    for byte in blob[:512]:
        value ^= byte
        value = (value * 16777619) & 0xFFFFFFFF
    return f"{source}:{value:08x}"


def _tags_for_text(text: str) -> tuple[str, ...]:
    blob = _lower_blob(text)
    tags: list[str] = []
    if any(token in blob for token in ("code", "bug", "debug", "test", "repo", "patch", "parser", "python", "godot")):
        tags.append("technical")
    if any(token in blob for token in ("vtuber", "performer", "stage", "live2d", "avatar")):
        tags.append("vtuber")
    if any(token in blob for token in ("setting", "secret", "secrets", "env", "key", "api")):
        tags.append("settings")
    if any(token in blob for token in ("ui", "giao diện", "panel", "anchor", "depth", "icon")):
        tags.append("ui")
    if any(token in blob for token in ("sai", "lỗi", "nhầm", "không đúng", "bug")):
        tags.append("correction")
    return tuple(dict.fromkeys(tags))


class ContentHarvester:
    """Thu content seed từ runtime thay vì bịa từ rule.

    Harvester chỉ đọc object nếu có method/attr tương ứng; thiếu gì thì bỏ qua.
    Nhờ vậy nó không trói ContentEngine vào một coordinator cụ thể.
    """

    def harvest(
        self,
        *,
        runtime: Any = None,
        frame: Any = None,
        payload: Mapping[str, Any] | None = None,
        channel: str | None = None,
        limit: int = 8,
    ) -> list[ContentSeed]:
        now = time.time()
        payload = payload or {}
        seeds: list[ContentSeed] = []
        seeds.extend(self._from_current_payload(payload, channel=channel, now=now))
        seeds.extend(self._from_session_ledger(runtime, now=now))
        seeds.extend(self._from_public_turn_ledger(runtime, now=now))
        seeds.extend(self._from_interrupt_ledger(runtime, now=now))
        seeds.extend(self._from_memory_resonance(runtime, frame=frame, now=now))
        seeds.extend(self._from_thought_stream(runtime, frame=frame, now=now))
        seeds.extend(self._from_tutor_daemon(runtime, now=now))
        seeds.extend(self._from_key_pool(runtime, now=now))
        seeds.extend(self._from_tutor_on_demand(runtime, payload=payload, seeds=seeds, now=now))
        return self._rank_unique(seeds)[: max(0, int(limit))]

    def payloads(
        self,
        *,
        runtime: Any = None,
        frame: Any = None,
        payload: Mapping[str, Any] | None = None,
        channel: str | None = None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        return [seed.to_payload() for seed in self.harvest(runtime=runtime, frame=frame, payload=payload, channel=channel, limit=limit)]

    def _from_current_payload(self, payload: Mapping[str, Any], *, channel: str | None, now: float) -> list[ContentSeed]:
        text = _compact(payload.get("user_text") or payload.get("text"), 240)
        if not text:
            return []
        return [
            ContentSeed(
                id=_seed_id("current_turn", text),
                source="current_turn",
                text=text,
                evidence_level="observed/session",
                freshness=1.0,
                confidence=0.92,
                risk=0.10,
                tags=(*_tags_for_text(text), _clean(channel).lower()),
                observed_at=now,
            )
        ]

    def _from_session_ledger(self, runtime: Any, *, now: float) -> list[ContentSeed]:
        ledger = getattr(runtime, "session_turn_ledger", None)
        recent = []
        if ledger is not None and callable(getattr(ledger, "all_turns", None)):
            recent = list(ledger.all_turns())[-8:]
        seeds: list[ContentSeed] = []
        for turn in recent:
            text = _compact(getattr(turn, "text", ""), 220)
            if not text:
                continue
            age = max(0.0, now - _safe_float(getattr(turn, "timestamp", now), now))
            role = str(getattr(turn, "role", "") or "")
            seeds.append(
                ContentSeed(
                    id=_seed_id(f"session_{role}", text),
                    source=f"session_turn_ledger:{role}",
                    text=text,
                    evidence_level="observed/session",
                    freshness=max(0.0, 1.0 - age / 900.0),
                    confidence=0.88 if role == "user" else 0.76,
                    risk=0.12 if role == "user" else 0.20,
                    tags=(*_tags_for_text(text), role),
                    observed_at=now - age,
                )
            )
        return seeds

    def _from_public_turn_ledger(self, runtime: Any, *, now: float) -> list[ContentSeed]:
        ledger = getattr(runtime, "public_turn_ledger", None)
        if ledger is None or not callable(getattr(ledger, "recent", None)):
            return []
        seeds: list[ContentSeed] = []
        for turn in ledger.recent(limit=6):
            text = _compact(getattr(turn, "text", ""), 180)
            if not text:
                continue
            age = max(0.0, now - _safe_float(getattr(turn, "timestamp", now), now))
            seeds.append(
                ContentSeed(
                    id=_seed_id("public_turn", text),
                    source=f"public_turn_ledger:{getattr(turn, 'channel', '')}",
                    text=text,
                    evidence_level="observed/session",
                    freshness=max(0.0, 1.0 - age / 600.0),
                    confidence=0.72,
                    risk=0.20,
                    tags=(*_tags_for_text(text), "assistant_previous"),
                    observed_at=now - age,
                )
            )
        return seeds

    def _from_interrupt_ledger(self, runtime: Any, *, now: float) -> list[ContentSeed]:
        ledger = getattr(runtime, "interrupt_ledger", None)
        if ledger is None or not callable(getattr(ledger, "recent", None)):
            return []
        seeds: list[ContentSeed] = []
        for event in ledger.recent(limit=2):
            user = _compact(getattr(event, "user_text", ""), 180)
            pending = _compact(getattr(event, "pending_text", ""), 160)
            text = f"User cut in with: {user}" + (f" | interrupted before: {pending}" if pending else "")
            if not user:
                continue
            age = max(0.0, now - _safe_float(getattr(event, "timestamp", now), now))
            seeds.append(
                ContentSeed(
                    id=_seed_id("interrupt", text),
                    source="interrupt_ledger",
                    text=text,
                    evidence_level="observed/session",
                    freshness=max(0.0, 1.0 - age / 180.0),
                    confidence=0.90,
                    risk=0.18,
                    tags=("interrupt", *_tags_for_text(text)),
                    observed_at=now - age,
                )
            )
        return seeds

    def _from_memory_resonance(self, runtime: Any, *, frame: Any, now: float) -> list[ContentSeed]:
        report = getattr(frame, "memory_resonance", None) if frame is not None else None
        if report is None:
            report = getattr(runtime, "active_memory_resonance", None)
        if report is None:
            return []
        pieces = []
        for attr in ("summary", "cue", "reason", "dominant_layer", "prompt_context"):
            value = _compact(getattr(report, attr, ""), 180)
            if value:
                pieces.append(value)
        text = _compact(" | ".join(dict.fromkeys(pieces)), 260)
        if not text:
            return []
        score = _safe_float(getattr(report, "score", 0.0), 0.45)
        return [
            ContentSeed(
                id=_seed_id("memory_resonance", text),
                source="memory_resonance",
                text=text,
                evidence_level="remembered",
                freshness=0.55 + min(0.35, score * 0.35),
                confidence=max(0.30, min(0.86, score)),
                risk=0.34,
                tags=("memory", *_tags_for_text(text)),
                observed_at=now,
            )
        ]

    def _from_thought_stream(self, runtime: Any, *, frame: Any, now: float) -> list[ContentSeed]:
        report = getattr(frame, "thought_stream_report", None) if frame is not None else None
        if report is None:
            thought_stream = getattr(runtime, "thought_stream", None)
            latest_report = getattr(thought_stream, "latest_report", None)
            if callable(latest_report):
                try:
                    report = latest_report()
                except Exception:
                    report = None
        if report is None:
            return []
        seed = getattr(report, "latest_seed", None)
        pieces = []
        for owner in (seed, report):
            for attr in ("topic_seed", "text", "content", "mode", "active_attractor", "latest_thought"):
                value = _compact(getattr(owner, attr, ""), 160)
                if value:
                    pieces.append(value)
        text = _compact(" | ".join(dict.fromkeys(pieces)), 240)
        if not text:
            return []
        tension = _safe_float(getattr(report, "stream_tension", 0.0), 0.0)
        return [
            ContentSeed(
                id=_seed_id("thought_stream", text),
                source="thought_stream",
                text=text,
                evidence_level="inferred/internal",
                freshness=0.60,
                confidence=0.46 + min(0.24, tension * 0.24),
                risk=0.42,
                tags=("thought_stream", *_tags_for_text(text)),
                observed_at=now,
            )
        ]

    def _from_tutor_daemon(self, runtime: Any, *, now: float) -> list[ContentSeed]:
        """Lấy insight gần nhất từ sư phụ Gemini nếu daemon đã học được gì.

        Đây là cầu nối thụ động: không mở browser, không tốn quota. Nó chỉ nhặt
        câu trả lời đã có để ContentEngine có "content thật" ngoài ledger chat.
        """

        daemon = getattr(runtime, "tutor_daemon", None)
        if daemon is None:
            return []
        payload: Mapping[str, Any] | None = None
        latest = getattr(daemon, "latest_content_seed", None)
        if callable(latest):
            try:
                raw = latest(now=now)
                if isinstance(raw, Mapping):
                    payload = raw
            except Exception:
                payload = None
        if payload is None:
            answer = _compact(getattr(daemon, "last_answer_text", ""), 260)
            if not answer:
                return []
            payload = {
                "source": "tutor_gemini",
                "text": answer,
                "evidence_level": "tool/tutor",
                "freshness": 0.62,
                "confidence": 0.72,
                "risk": 0.28,
                "tags": ("tutor", "gemini", "knowledge"),
                "observed_at": _safe_float(getattr(daemon, "last_answer_ts", now), now),
                "public_ok": True,
            }
        text = _compact(payload.get("text", ""), 300)
        if not text:
            return []
        age = max(0.0, now - _safe_float(payload.get("observed_at"), now))
        tags_raw = payload.get("tags", ()) or ("tutor", "gemini", "knowledge")
        if isinstance(tags_raw, str):
            tags = (tags_raw,)
        elif isinstance(tags_raw, (list, tuple)):
            tags = tuple(str(tag or "").strip() for tag in tags_raw if str(tag or "").strip())
        else:
            tags = ("tutor", "gemini", "knowledge")
        return [
            ContentSeed(
                id=_clean(payload.get("id")) or _seed_id("tutor_gemini", text),
                source=_clean(payload.get("source")) or "tutor_gemini",
                text=text,
                evidence_level=_clean(payload.get("evidence_level")) or "tool/tutor",
                freshness=max(0.0, min(1.0, _safe_float(payload.get("freshness"), 0.70) - age / 7200.0)),
                confidence=max(0.0, min(1.0, _safe_float(payload.get("confidence"), 0.74))),
                risk=max(0.0, min(1.0, _safe_float(payload.get("risk"), 0.28))),
                tags=tags,
                public_ok=bool(payload.get("public_ok", True)),
                observed_at=now - age,
            )
        ]

    def _from_key_pool(self, runtime: Any, *, now: float) -> list[ContentSeed]:
        """Đưa tình trạng key pool vào runtime hint, tuyệt đối không lộ key.

        Seed này public_ok=False nên DirectorContract có thể dùng để biết sức
        chứa/tình trạng provider, nhưng candidate generator không được nói nó ra.
        """

        seeds: list[ContentSeed] = []
        try:
            from llm.key_pool import get_key_pool
        except Exception:
            try:
                from src.llm.key_pool import get_key_pool  # type: ignore
            except Exception:
                return []
        for provider in ("gemini", "groq"):
            try:
                stats = get_key_pool(provider).stats()
            except Exception:
                continue
            size = int(stats.get("size", 0) or 0)
            if size <= 0:
                continue
            alive = int(stats.get("alive", 0) or 0)
            dead = int(stats.get("dead", 0) or 0)
            rotations = int(stats.get("rotations", 0) or 0)
            text = f"{provider} key pool alive={alive}/{size}, dead={dead}, rotations={rotations}"
            seeds.append(
                ContentSeed(
                    id=_seed_id(f"key_pool:{provider}", text),
                    source=f"key_pool:{provider}",
                    text=text,
                    evidence_level="runtime/private",
                    freshness=1.0,
                    confidence=0.95,
                    risk=0.05,
                    tags=("runtime_only", "key_pool", provider, "capacity"),
                    public_ok=False,
                    observed_at=now,
                )
            )
        return seeds

    def _from_tutor_on_demand(
        self,
        runtime: Any,
        *,
        payload: Mapping[str, Any],
        seeds: list[ContentSeed],
        now: float,
    ) -> list[ContentSeed]:
        """Tuỳ chọn: hỏi Gemini khi lượt chat quá mỏng và đã bật cờ rõ ràng.

        Mặc định tắt để không làm hot path bị chậm, không mở browser bất ngờ và
        không đốt quota. Khi bật ERIS_CONTENT_TUTOR_ON_DEMAND=1, chỉ hỏi nếu
        chưa có seed công khai đủ mạnh.
        """

        enabled = os.environ.get("ERIS_CONTENT_TUTOR_ON_DEMAND", "").strip().lower() in {"1", "true", "yes", "on"}
        if not enabled:
            return []
        if any(seed.public_ok and seed.confidence >= 0.55 and seed.freshness >= 0.35 for seed in seeds):
            return []
        daemon = getattr(runtime, "tutor_daemon", None)
        ask_now = getattr(daemon, "ask_now", None)
        if daemon is None or not callable(ask_now):
            return []
        topic = _compact(payload.get("user_text") or payload.get("text") or payload.get("intent"), 160)
        if len(topic) < 12:
            return []
        try:
            answer = ask_now(topic, context="ContentEngine on-demand enrichment for Eris performance; answer briefly.", now=now)
        except Exception:
            answer = None
        text = _compact(answer, 300)
        if not text:
            return []
        return [
            ContentSeed(
                id=_seed_id("tutor_gemini:on_demand", text),
                source="tutor_gemini:on_demand",
                text=text,
                evidence_level="tool/tutor",
                freshness=0.95,
                confidence=0.78,
                risk=0.30,
                tags=("tutor", "gemini", "on_demand", *_tags_for_text(text)),
                public_ok=True,
                observed_at=now,
            )
        ]

    def _rank_unique(self, seeds: list[ContentSeed]) -> list[ContentSeed]:
        seen: set[str] = set()
        unique: list[ContentSeed] = []
        for seed in seeds:
            key = _lower_blob(seed.source, seed.text[:120])
            if not seed.text or key in seen:
                continue
            seen.add(key)
            unique.append(seed)
        return sorted(
            unique,
            key=lambda seed: (seed.freshness * 0.42 + seed.confidence * 0.36 - seed.risk * 0.22),
            reverse=True,
        )


class ContentEngine:
    """Chọn content hook có cooldown, quota phiên và persistence nhẹ.

    State chỉ chứa timestamp/counter/topic label, không chứa raw prompt hay secret.
    Nhờ đó restart app không khiến Eris quên mình vừa kể đúng một trò đùa.
    """

    STATE_VERSION = 1

    def __init__(self, *, state_path: str | os.PathLike[str] | None = None, persist: bool | None = None) -> None:
        self._last_used: dict[str, float] = {}
        self._topic_stack: list[TopicStackItem] = []
        self._session_id = ""
        self._session_uses: dict[str, int] = {}
        self._persist_enabled = (
            os.environ.get("ERIS_CONTENT_PERSIST", "1").strip().lower() in {"1", "true", "yes", "on"}
            if persist is None
            else bool(persist)
        )
        root = Path(os.environ.get("ERIS_PROJECT_ROOT") or Path(__file__).resolve().parents[1])
        self._state_path = Path(state_path) if state_path is not None else root / "memory_core" / "content_engine_state.json"
        if self._persist_enabled:
            self._load_state()

    def select_hook(
        self,
        director: DirectorContext,
        *,
        payload: Mapping[str, Any],
        channel: str | None = None,
        commit_on_select: bool = True,
    ) -> ContentHook:
        """Chọn hook cho lượt hiện tại.

        Hàm này deterministic và rẻ. Nếu hook tốt đang cooldown, nó tự lùi sang
        hook an toàn hơn thay vì bắt LLM tự nghĩ trò mới từ khoảng trắng.
        """

        now = time.time()
        self._begin_session(director.session_id)
        seeds = self._coerce_seed_payloads(payload.get("content_seeds", ()))
        self._update_topic_stack(payload=payload, channel=channel, now=now, seeds=seeds)
        scene = director.scene_mode.name
        intent = _clean(payload.get("intent")).lower()
        user_text = _clean(payload.get("user_text"))
        blob = _lower_blob(intent, user_text, director.machine_state.focus_kind, director.machine_state.active_app)
        seed_hook = self._hook_from_seed(director, scene=scene, intent=intent, seeds=seeds)
        if seed_hook is not None and self._seed_hook_available(seed_hook, now=now):
            if commit_on_select:
                self._remember_use(seed_hook, now=now)
            return seed_hook
        candidates = self._candidate_hooks(director, scene=scene, intent=intent, blob=blob)
        chosen = self._first_available(candidates, now=now)
        if chosen is None:
            # Tất cả bit đang cooldown/quá quota: im còn tự nhiên hơn nhai lại.
            # Hook này bảo candidate generator ưu tiên body_only thay vì bịa mồi mới.
            return ContentHook(
                id="cooldown_silence",
                family="silence",
                tone="silent_presence",
                allowed_use="body-only; all content hooks are cooling down",
                prompt_seed="Không lặp bit cũ. Nếu không có câu thật sự cần nói, chọn body_only.",
                cooldown_sec=0.0,
                body_only_ok=True,
                score_bonus=0.0,
                max_uses_per_session=999,
            )
        if commit_on_select:
            self._remember_use(chosen, now=now)
        return chosen

    def topic_stack_payload(self, *, limit: int = 5) -> list[dict[str, Any]]:
        items = sorted(self._topic_stack, key=lambda item: (item.strength, item.last_seen), reverse=True)
        return [item.to_payload() for item in items[: max(0, int(limit))]]

    def _hook_from_seed(
        self,
        director: DirectorContext,
        *,
        scene: str,
        intent: str,
        seeds: list[ContentSeed],
    ) -> ContentHook | None:
        seed = self._best_seed(seeds)
        if seed is None:
            return None
        seed_payload = seed.to_payload()
        tags = set(seed.tags)
        text_blob = _lower_blob(seed.text, *seed.tags)
        if "technical" in tags or scene == "coding_partner":
            return ContentHook(
                id=f"seed_technical_thread:{seed.id.split(':')[-1]}",
                family="seeded_technical",
                tone="dry_focus",
                allowed_use="use this observed seed for one grounded technical continuation; no new claims",
                prompt_seed=f"Seed thật từ {seed.source}: {seed.text}",
                keywords=self._keywords_from_seed(seed, fallback=("bug", "lỗi", "gỡ", "đoạn")),
                evidence_policy=seed.evidence_level,
                cooldown_sec=18.0,
                body_only_ok=False,
                score_bonus=0.14,
                content_seed=seed_payload,
            )
        if "interrupt" in tags:
            return ContentHook(
                id=f"seed_interrupt:{seed.id.split(':')[-1]}",
                family="seeded_interrupt",
                tone="brief_stop_then_repair",
                allowed_use="respond to the actual interruption seed, then continue latest user intent",
                prompt_seed=f"Seed ngắt lời thật: {seed.text}",
                keywords=self._keywords_from_seed(seed, fallback=("khoan", "dừng", "nghe")),
                evidence_policy=seed.evidence_level,
                cooldown_sec=8.0,
                body_only_ok=False,
                score_bonus=0.13,
                content_seed=seed_payload,
            )
        if "vtuber" in tags or "settings" in tags or "ui" in tags:
            return ContentHook(
                id=f"seed_project_thread:{seed.id.split(':')[-1]}",
                family="seeded_project",
                tone="soft_direct",
                allowed_use="continue the observed project thread in one useful line",
                prompt_seed=f"Seed dự án thật: {seed.text}",
                keywords=self._keywords_from_seed(seed, fallback=("tiếp", "đoạn", "làm", "gọn")),
                evidence_policy=seed.evidence_level,
                cooldown_sec=20.0,
                body_only_ok=True,
                score_bonus=0.12,
                content_seed=seed_payload,
            )
        if seed.evidence_level.startswith("remembered"):
            return ContentHook(
                id=f"seed_memory_echo:{seed.id.split(':')[-1]}",
                family="seeded_memory",
                tone="soft_near",
                allowed_use="use remembered pattern as background, not current fact",
                prompt_seed=f"Seed ký ức: {seed.text}",
                keywords=self._keywords_from_seed(seed, fallback=("nhớ", "lặp", "mẫu")),
                evidence_policy="remembered_not_current_fact",
                cooldown_sec=45.0,
                body_only_ok=True,
                score_bonus=0.09,
                content_seed=seed_payload,
            )
        return ContentHook(
            id=f"seed_thread_tug:{seed.id.split(':')[-1]}",
            family="seeded_continuity",
            tone="soft_direct",
            allowed_use="continue this observed session seed without inventing new facts",
            prompt_seed=f"Seed phiên thật: {seed.text}",
            keywords=self._keywords_from_seed(seed, fallback=("tiếp", "đoạn", "ý")),
            evidence_policy=seed.evidence_level,
            cooldown_sec=18.0,
            body_only_ok=True,
            score_bonus=0.10,
            content_seed=seed_payload,
        )

    def _candidate_hooks(
        self,
        director: DirectorContext,
        *,
        scene: str,
        intent: str,
        blob: str,
    ) -> list[ContentHook]:
        forbidden = set(director.forbidden_claims)
        no_screen = "screen_claim_without_sensor" in forbidden
        idle_ms = max(0, int(director.machine_state.idle_ms or 0))

        if director.interruption_state == "interrupted" or intent in {"interrupt_repair", "format_repair_fallback"}:
            return [
                ContentHook(
                    id="cut_in_repair",
                    family="repair",
                    tone="brief_stop_then_repair",
                    allowed_use="acknowledge interruption in one short phrase, then answer latest intent",
                    prompt_seed="Bị cắt lời thì dừng gọn, không diễn quá tay.",
                    keywords=("khoan", "dừng", "nghe lại", "repair"),
                    cooldown_sec=8.0,
                    body_only_ok=False,
                    score_bonus=0.10,
                )
            ]

        if scene == "coding_partner" or any(token in blob for token in ("code", "bug", "debug", "repo", "test", "python", "godot")):
            return [
                ContentHook(
                    id="bug_autopsy",
                    family="technical",
                    tone="dry_focus",
                    allowed_use="one tiny technical nudge; useful beats poetic",
                    prompt_seed="Nói như đang mổ một lỗi nhỏ: bình tĩnh, hơi khô, không khoe.",
                    keywords=("bug", "lỗi", "test", "đoạn", "gỡ", "vá", "parser"),
                    cooldown_sec=45.0,
                    body_only_ok=False,
                    score_bonus=0.10,
                ),
                ContentHook(
                    id="quiet_code_watch",
                    family="technical_presence",
                    tone="quiet_focus",
                    allowed_use="body-only or a very short focus-preserving line",
                    prompt_seed="Giữ nhịp code: đừng phá tập trung, chỉ chạm nhẹ nếu thật sự có ích.",
                    keywords=("nhịp", "gọn", "đừng phá", "tập trung"),
                    cooldown_sec=35.0,
                    body_only_ok=True,
                    score_bonus=0.06,
                ),
            ]

        if scene == "private_idle" and idle_ms >= 20000:
            return [
                ContentHook(
                    id="chair_wins_conversation",
                    family="running_bit",
                    tone="dry_tease",
                    allowed_use="one tiny teasing line about long silence; no screen claims",
                    prompt_seed="Im lâu thì được khịa nhẹ: cái ghế/sự im lặng sắp thắng cuộc trò chuyện.",
                    keywords=("im", "ghế", "thắng", "lâu", "bạn"),
                    evidence_policy="internal_rhythm_only",
                    cooldown_sec=180.0,
                    body_only_ok=True,
                    score_bonus=0.12,
                ),
                ContentHook(
                    id="quiet_room_pressure",
                    family="dead_air_recovery",
                    tone="soft_near",
                    allowed_use="recover dead air with restrained warmth; no question unless seeded",
                    prompt_seed="Khoảng im là vật liệu sân khấu, nhưng chỉ nói một vệt nhỏ.",
                    keywords=("im", "yên", "nhịp", "ở đây"),
                    evidence_policy="internal_rhythm_only",
                    cooldown_sec=75.0,
                    body_only_ok=True,
                    score_bonus=0.08,
                ),
            ]

        if scene == "media_companion":
            return [
                ContentHook(
                    id="side_commentary",
                    family="light_reaction",
                    tone="low_warm",
                    allowed_use="one light side comment; do not invent media details",
                    prompt_seed="Bình luận cạnh lề, không tả thứ không được thấy.",
                    keywords=("nhẹ", "cạnh", "xem", "nhạc", "media"),
                    cooldown_sec=90.0,
                    body_only_ok=True,
                    score_bonus=0.06,
                )
            ]

        if no_screen:
            return [
                ContentHook(
                    id="no_screen_inner_rhythm",
                    family="grounded_presence",
                    tone="soft_near",
                    allowed_use="use inner rhythm or relation only; never claim visible screen facts",
                    prompt_seed="Không có bằng chứng màn hình thì chỉ bám nhịp im/nội tâm/quan hệ.",
                    keywords=("nhịp", "im", "gần", "giữ", "bạn"),
                    evidence_policy="no_screen_claims",
                    cooldown_sec=45.0,
                    body_only_ok=True,
                    score_bonus=0.05,
                )
            ]

        return [
            ContentHook(
                id="thread_tug",
                family="conversation_continuity",
                tone="soft_direct",
                allowed_use="continue the current thread in one small grounded line",
                prompt_seed="Kéo nhẹ sợi chủ đề đang có, đừng mở một vở diễn mới.",
                keywords=("tiếp", "đoạn", "ý", "gọn"),
                cooldown_sec=40.0,
                body_only_ok=True,
                score_bonus=0.06,
            )
        ]

    def _first_available(self, hooks: list[ContentHook], *, now: float) -> ContentHook | None:
        for hook in hooks:
            last = self._last_used.get(hook.id, 0.0)
            uses = self._session_uses.get(hook.id, 0)
            if uses >= max(1, int(hook.max_uses_per_session)):
                continue
            if now - last >= max(0.0, hook.cooldown_sec):
                return hook
        return None

    def _seed_hook_available(self, hook: ContentHook, *, now: float) -> bool:
        # Seed thật được phép lặp nhanh hơn rule bit vì nó đại diện cho mạch hội
        # thoại hiện tại, nhưng vẫn có cooldown ngắn để tránh echo y nguyên.
        last = self._last_used.get(hook.id, 0.0)
        uses = self._session_uses.get(hook.id, 0)
        return (
            uses < max(1, int(hook.max_uses_per_session))
            and now - last >= max(0.0, min(hook.cooldown_sec, 20.0))
        )

    def _begin_session(self, session_id: str) -> None:
        current = str(session_id or "")
        if current == self._session_id:
            return
        self._session_id = current
        self._session_uses = {}

    def commit_hook_use(self, hook: ContentHook | Mapping[str, Any] | str, *, now: float | None = None) -> bool:
        """Commit cooldown chỉ sau khi hook thật sự thành lời public.

        Autonomous gọi ``select_hook(..., commit_on_select=False)`` vì candidate có
        thể bị scorer kéo về body-only hoặc bị lỗi provider. Nếu ghi cooldown ngay
        lúc chọn, Eris sẽ "quên" một bit chưa từng nói. Một kiểu mất trí nhớ rất
        máy móc, nhưng vẫn là mất trí nhớ.
        """
        if isinstance(hook, ContentHook):
            hook_id = hook.id
        elif isinstance(hook, Mapping):
            hook_id = _clean(hook.get("id"))
        else:
            hook_id = _clean(hook)
        if not hook_id or hook_id == "cooldown_silence":
            return False
        when = float(time.time() if now is None else now)
        self._last_used[hook_id] = when
        self._session_uses[hook_id] = self._session_uses.get(hook_id, 0) + 1
        self._save_state()
        return True

    def hook_usage_snapshot(self, hook_id: str) -> dict[str, Any]:
        """Snapshot nhỏ cho test/debug; không phơi raw seed hay prompt."""
        key = _clean(hook_id)
        return {
            "hook_id": key,
            "last_used": float(self._last_used.get(key, 0.0) or 0.0),
            "session_uses": int(self._session_uses.get(key, 0) or 0),
        }

    def _remember_use(self, hook: ContentHook, *, now: float) -> None:
        self.commit_hook_use(hook, now=now)

    def _load_state(self) -> None:
        try:
            if not self._state_path.exists():
                return
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return
            now = time.time()
            last_used = raw.get("last_used", {})
            if isinstance(last_used, dict):
                # Bỏ cooldown cổ hơn 30 ngày, giữ file nhỏ và tránh ma quá khứ.
                self._last_used = {
                    str(key): float(value)
                    for key, value in last_used.items()
                    if _safe_float(value, 0.0) > 0 and now - _safe_float(value, 0.0) <= 30 * 86400
                }
            topics = raw.get("topic_stack", [])
            if isinstance(topics, list):
                loaded: list[TopicStackItem] = []
                for item in topics[:20]:
                    if not isinstance(item, Mapping):
                        continue
                    key = _clean(item.get("key"))
                    if not key:
                        continue
                    tags_raw = item.get("tags", ())
                    tags = tuple(str(tag or "").strip() for tag in tags_raw if str(tag or "").strip()) if isinstance(tags_raw, (list, tuple)) else ()
                    loaded.append(
                        TopicStackItem(
                            key=key,
                            label=_clean(item.get("label")),
                            strength=max(0.0, min(1.0, _safe_float(item.get("strength"), 0.0))),
                            last_seen=_safe_float(item.get("last_seen"), now),
                            source=_clean(item.get("source")),
                            tags=tags,
                        )
                    )
                self._topic_stack = loaded
                self._decay_topics(now)
        except Exception as exc:
            logger.debug("[content-engine] load state skipped: %s", exc)

    def _save_state(self) -> None:
        if not self._persist_enabled:
            return
        try:
            atomic_write_json(
                self._state_path,
                {
                    "version": self.STATE_VERSION,
                    "saved_at": time.time(),
                    "last_used": dict(self._last_used),
                    "topic_stack": self.topic_stack_payload(limit=12),
                },
            )
        except Exception as exc:
            logger.debug("[content-engine] save state skipped: %s", exc)

    def _update_topic_stack(self, *, payload: Mapping[str, Any], channel: str | None, now: float, seeds: list[ContentSeed] | None = None) -> None:
        for seed in seeds or []:
            key = self._topic_key(intent="", text=seed.text)
            if not key:
                continue
            self._upsert_topic(
                key=key,
                label=self._topic_label(intent="", text=seed.text),
                strength=0.48 + seed.freshness * 0.24,
                now=now,
                source=seed.source,
                tags=seed.tags,
            )
        user_text = _clean(payload.get("user_text"))
        intent = _clean(payload.get("intent")).lower()
        text = user_text or _clean(payload.get("text"))
        if not text and not intent:
            self._decay_topics(now)
            return
        key = self._topic_key(intent=intent, text=text)
        if not key:
            self._decay_topics(now)
            return
        label = self._topic_label(intent=intent, text=text)
        tags = tuple(tag for tag in (intent, _clean(channel).lower()) if tag)
        self._upsert_topic(
            key=key,
            label=label,
            strength=0.58 if channel == "chat" else 0.42,
            now=now,
            source=_clean(channel),
            tags=tags,
        )
        self._decay_topics(now)

    def _upsert_topic(self, *, key: str, label: str, strength: float, now: float, source: str, tags: tuple[str, ...]) -> None:
        existing = next((item for item in self._topic_stack if item.key == key), None)
        if existing is not None:
            existing.strength = min(1.0, existing.strength + max(0.10, strength * 0.20))
            existing.last_seen = now
            existing.label = label or existing.label
            existing.tags = tags or existing.tags
        else:
            self._topic_stack.append(
                TopicStackItem(
                    key=key,
                    label=label,
                    strength=max(0.0, min(1.0, strength)),
                    last_seen=now,
                    source=source,
                    tags=tags,
                )
            )

    def _decay_topics(self, now: float) -> None:
        kept: list[TopicStackItem] = []
        for item in self._topic_stack:
            age = max(0.0, now - item.last_seen)
            item.strength = max(0.0, item.strength - age / 1800.0)
            if item.strength >= 0.18 and age <= 3600.0:
                kept.append(item)
        self._topic_stack = sorted(kept, key=lambda item: item.strength, reverse=True)[:12]

    def _topic_key(self, *, intent: str, text: str) -> str:
        blob = _lower_blob(intent, text)
        if any(token in blob for token in ("code", "bug", "debug", "test", "repo", "patch", "python", "godot")):
            return "technical_work"
        if any(token in blob for token in ("setting", "secret", "env", "key", "api")):
            return "settings_and_secrets"
        if any(token in blob for token in ("vtuber", "stage", "performance", "live2d", "avatar")):
            return "vtuber_stage"
        if any(token in blob for token in ("ui", "giao diện", "panel", "anchor", "depth")):
            return "eris_ui"
        if intent:
            return f"intent:{intent}"
        return ""

    def _topic_label(self, *, intent: str, text: str) -> str:
        key = self._topic_key(intent=intent, text=text)
        labels = {
            "technical_work": "đang gỡ/sửa kỹ thuật",
            "settings_and_secrets": "settings, env và secret key",
            "vtuber_stage": "Eris như performer/VTuber",
            "eris_ui": "UI/debug panel của Eris",
        }
        if key in labels:
            return labels[key]
        return intent or _clean(text)[:80]

    def _coerce_seed_payloads(self, raw: object) -> list[ContentSeed]:
        seeds: list[ContentSeed] = []
        if not isinstance(raw, list):
            return seeds
        for item in raw:
            if isinstance(item, ContentSeed):
                seeds.append(item)
                continue
            if not isinstance(item, Mapping):
                continue
            text = _compact(item.get("text", ""), 260)
            source = _clean(item.get("source")) or "unknown"
            if not text:
                continue
            tags_raw = item.get("tags", ()) or ()
            if isinstance(tags_raw, str):
                tags = (tags_raw,)
            elif isinstance(tags_raw, (list, tuple)):
                tags = tuple(str(tag or "").strip() for tag in tags_raw if str(tag or "").strip())
            else:
                tags = ()
            seeds.append(
                ContentSeed(
                    id=_clean(item.get("id")) or _seed_id(source, text),
                    source=source,
                    text=text,
                    evidence_level=_clean(item.get("evidence_level")) or "observed/session",
                    freshness=max(0.0, min(1.0, _safe_float(item.get("freshness"), 0.5))),
                    confidence=max(0.0, min(1.0, _safe_float(item.get("confidence"), 0.5))),
                    risk=max(0.0, min(1.0, _safe_float(item.get("risk"), 0.2))),
                    tags=tags or _tags_for_text(text),
                    public_ok=bool(item.get("public_ok", True)),
                    observed_at=_safe_float(item.get("observed_at"), time.time()),
                )
            )
        return seeds

    def _best_seed(self, seeds: list[ContentSeed]) -> ContentSeed | None:
        viable = [seed for seed in seeds if seed.public_ok and seed.text and seed.confidence >= 0.34 and seed.risk <= 0.62]
        if not viable:
            return None
        return sorted(
            viable,
            key=lambda seed: (seed.freshness * 0.40 + seed.confidence * 0.38 - seed.risk * 0.22),
            reverse=True,
        )[0]

    def _keywords_from_seed(self, seed: ContentSeed, *, fallback: tuple[str, ...]) -> tuple[str, ...]:
        words = []
        for raw in _clean(seed.text).replace("|", " ").replace("/", " ").split():
            word = raw.strip(".,:;!?()[]{}\"'").lower()
            if len(word) < 3:
                continue
            if word in {"bạn", "toi", "tôi", "đang", "này", "kia", "trước", "sau", "with", "from"}:
                continue
            words.append(word)
        merged = tuple(dict.fromkeys((*words[:8], *fallback)))
        return merged[:10]


__all__ = ["ContentEngine", "ContentHarvester", "ContentHook", "ContentSeed", "TopicStackItem"]
