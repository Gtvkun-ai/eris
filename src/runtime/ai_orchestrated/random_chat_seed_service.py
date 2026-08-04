# -*- coding: utf-8 -*-
"""Background random-chat seed generation for autonomous ERIS speech.

The seed worker has its own DeepSeek role and DS2API port. It never writes
public wording and it never runs on the autonomous speech critical path.
Instead, it keeps a small, diverse reservoir of typed premises. When the
initiative governor later opens an idle social lane, runtime leases one seed
atomically and Surface only realizes that already-approved premise.

The queue itself is intentionally session-local. Learned affinity and ERIS
interest remain persisted by :mod:`random_chat_seed`; transient premises do not
survive a restart and wake up in a different conversation like confused ghosts.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .random_chat_seed import RandomChatSeed, RandomChatSeedAffinityStore


RANDOM_CHAT_SEED_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "decision", "seed_id", "mode", "premise", "source_kind", "source_refs",
        "topic_tags", "opening_move", "desired_response", "eris_motive", "risk",
        "estimated_fit", "confidence", "tone", "ttl_seconds",
    ],
    "properties": {
        "decision": {"type": "string", "enum": ["seed", "none"]},
        "seed_id": {"type": "string"},
        "mode": {"type": "string", "enum": ["user_led", "shared", "eris_led", "experimental"]},
        "premise": {"type": "string"},
        "source_kind": {
            "type": "string",
            "enum": ["user_memory", "recent_shared_context", "eris_self_memory", "weak_association"],
        },
        "source_refs": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "topic_tags": {"type": "array", "items": {"type": "string"}, "minItems": 0, "maxItems": 8},
        "opening_move": {"type": "string"},
        "desired_response": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "eris_motive": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "why_now", "personal_stake", "authenticity"],
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": [
                        "want_to_share", "want_to_express", "want_to_test",
                        "want_to_connect", "want_to_amuse",
                    ],
                },
                "why_now": {"type": "string"},
                "personal_stake": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "authenticity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
        },
        "risk": {
            "type": "object",
            "additionalProperties": False,
            "required": ["daring", "uncertainty", "intrusion_risk", "face_risk", "recovery_available"],
            "properties": {
                "daring": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "uncertainty": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "intrusion_risk": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "face_risk": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "recovery_available": {"type": "boolean"},
            },
        },
        "estimated_fit": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "tone": {"type": "string"},
        "ttl_seconds": {"type": "number", "minimum": 60.0, "maximum": 1800.0},
    },
}


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off", "disabled", "none"}


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _compact(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _token_set(text: str) -> set[str]:
    import re

    return {
        token
        for token in re.findall(r"[\w\u00c0-\u024f\u1e00-\u1eff]+", str(text or "").lower())
        if len(token) >= 3
    }


def _similarity(left: str, right: str) -> float:
    a, b = _token_set(left), _token_set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def _fingerprint(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:20]


class RandomChatSeedGenerator:
    """Own the seed prompt while a shared invoker owns transport mechanics."""

    def __init__(
        self,
        client: Any,
        *,
        invoke_structured: Callable[..., Mapping[str, Any]],
        logger: Any | None = None,
    ) -> None:
        self.client = client
        self.invoke_structured = invoke_structured
        self.logger = logger

    @property
    def enabled(self) -> bool:
        return self.client is not None and callable(self.invoke_structured)

    @staticmethod
    def prompt() -> str:
        return (
            "Bạn là RANDOM_CHAT_SEED_WORKER của ERIS. Bạn chạy nền trên lane riêng và KHÔNG viết câu public. "
            "Hãy tạo đúng một premise typed đủ bền để Surface dùng vài phút sau. Đọc user_memory, "
            "recent_public_history, eris_self_memory, seed_learning và reservoir_context. Một seed tốt có một "
            "đối tượng hoặc ý cụ thể, một góc nhìn thật của ERIS, một social move và phản ứng mong đợi nhưng "
            "không bắt buộc. Cân bằng ba lực: user affinity, ERIS ego và daring. ERIS ego nghĩa là ERIS được "
            "phép nói vì muốn chia sẻ, biểu đạt hoặc thử, không chỉ vì dự đoán user sẽ thích. requested_mode là "
            "mode ưu tiên để reservoir đa dạng; nếu mode đó không có premise thật thì trả decision=none, đừng "
            "bịa cho đủ kho. Daring là thử sai xã hội có chủ đích, không phải tăng độ kỳ quặc. Không dùng memory "
            "private/sensitive, không suy diễn cảm xúc, kế hoạch hay tâm lý user, không tạo presence/check-in "
            "chung chung, không hỏi user đưa chủ đề, không tạo câu chỉ để lấp im lặng. Không lặp queued_seeds "
            "hoặc recent_seeds. Phản hồi âm chỉ hạ user/strategy fit, không xóa ERIS interest. Tôn trọng "
            "daring_ceiling và intrusion risk. ttl_seconds nên 180-900 giây tùy độ phụ thuộc context; seed từ "
            "recent_shared_context phải ngắn hơn seed từ user_memory hoặc eris_self_memory. Nếu không đủ cụ thể "
            "và có động cơ thật, trả decision=none với field còn lại rỗng/an toàn. Return exactly one JSON object."
        )

    def generate(self, request: Mapping[str, Any]) -> RandomChatSeed:
        if not self.enabled:
            return RandomChatSeed()
        timeout = _env_float(
            "ERIS_RANDOM_CHAT_SEED_WORKER_TIMEOUT_SEC",
            35.0,
            minimum=6.0,
            maximum=120.0,
        )
        try:
            raw = self.invoke_structured(
                self.client,
                system=self.prompt(),
                payload=request,
                schema=RANDOM_CHAT_SEED_OUTPUT_SCHEMA,
                name="eris_random_chat_seed_background",
                max_tokens=560,
                reasoning_effort=None,
                inference_tier="subconscious_4b",
                priority=18,
                timeout_seconds=timeout,
            )
        except Exception as exc:  # transport errors must not touch public speech
            self._log("warning", "[random chat seed] background worker failed: %s", exc)
            return RandomChatSeed()
        return RandomChatSeed.from_mapping(raw)

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass


@dataclass(frozen=True, slots=True)
class SeedReservoirPreview:
    seed: RandomChatSeed
    generated_at: float
    expires_at: float
    context_revision: int

@dataclass(frozen=True, slots=True)
class SeedReservoirLease:
    token: str
    seed: RandomChatSeed
    generated_at: float
    expires_at: float
    context_revision: int


@dataclass(slots=True)
class _SeedEntry:
    seed: RandomChatSeed
    generated_at: float
    expires_at: float
    context_revision: int
    user_epoch: int
    context_fingerprint: str


@dataclass(slots=True)
class _LeaseEntry:
    entry: _SeedEntry
    leased_at: float
    lease_expires_at: float


class RandomChatSeedReservoir:
    """Background producer plus atomic in-memory reservoir.

    `update_context()` is cheap and may be called every autonomous tick. The
    DeepSeek call occurs only in this service's daemon thread. `claim()` never
    calls a model, so speech latency no longer includes seed generation.
    """

    def __init__(
        self,
        generator: RandomChatSeedGenerator,
        *,
        seed_store: RandomChatSeedAffinityStore | None = None,
        wake_callback: Callable[[], Any] | None = None,
        logger: Any | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.generator = generator
        self.seed_store = seed_store
        self.wake_callback = wake_callback
        self.logger = logger
        self.clock = clock
        self.enabled = bool(
            generator.enabled
            and _env_bool("ERIS_RANDOM_CHAT_SEED_RESERVOIR_ENABLED", True)
        )
        self.target_size = _env_int("ERIS_RANDOM_CHAT_SEED_TARGET_SIZE", 4, minimum=1, maximum=12)
        self.max_size = max(
            self.target_size,
            _env_int("ERIS_RANDOM_CHAT_SEED_MAX_SIZE", 7, minimum=1, maximum=20),
        )
        self.min_generate_interval = _env_float(
            "ERIS_RANDOM_CHAT_SEED_GENERATE_INTERVAL_SEC", 12.0, minimum=1.0, maximum=600.0
        )
        self.none_backoff = _env_float(
            "ERIS_RANDOM_CHAT_SEED_NONE_BACKOFF_SEC", 24.0, minimum=2.0, maximum=900.0
        )
        self.error_backoff = _env_float(
            "ERIS_RANDOM_CHAT_SEED_ERROR_BACKOFF_SEC", 40.0, minimum=2.0, maximum=900.0
        )
        self.default_ttl = _env_float(
            "ERIS_RANDOM_CHAT_SEED_RESERVOIR_TTL_SEC", 600.0, minimum=90.0, maximum=1800.0
        )
        self.lease_ttl = _env_float(
            "ERIS_RANDOM_CHAT_SEED_LEASE_TTL_SEC", 45.0, minimum=5.0, maximum=180.0
        )
        self._condition = threading.Condition(threading.RLock())
        self._entries: list[_SeedEntry] = []
        self._leases: dict[str, _LeaseEntry] = {}
        self._context_request: dict[str, Any] = {}
        self._context_fingerprint = ""
        self._context_revision = 0
        self._user_epoch = 0
        self._last_generate_at = 0.0
        self._next_generate_at = 0.0
        self._last_claimed_mode = ""
        self._stop = False
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if not self.enabled:
            self._log("info", "[random chat seed] reservoir disabled: seed worker unavailable or feature off")
            return False
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return True
            self._stop = False
            self._thread = threading.Thread(
                target=self._run,
                name="eris-random-chat-seed-reservoir",
                daemon=True,
            )
            self._thread.start()
        self._log(
            "info",
            "[random chat seed] reservoir started target=%d max=%d port_owner=seed",
            self.target_size,
            self.max_size,
        )
        return True

    def shutdown(self) -> None:
        with self._condition:
            self._stop = True
            self._condition.notify_all()
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._log("info", "[random chat seed] reservoir stopped")

    def update_context(self, snapshot: Mapping[str, Any], *, now: float | None = None) -> bool:
        """Publish a compact public-safe generation context without model work."""

        if not self.enabled:
            return False
        current = float(now if now is not None else self.clock())
        request = self._context_from_snapshot(snapshot)
        fingerprint = _fingerprint(self._fingerprint_projection(request))
        with self._condition:
            changed = fingerprint != self._context_fingerprint
            self._context_request = request
            if changed:
                self._context_fingerprint = fingerprint
                self._context_revision += 1
                self._prune_locked(current)
            self._condition.notify_all()
        return changed

    def observe_user_turn(self, *, now: float | None = None) -> None:
        """Invalidate transient scene seeds; durable memory/self seeds may survive."""

        current = float(now if now is not None else self.clock())
        with self._condition:
            self._user_epoch += 1
            self._context_revision += 1
            # Pause production until SelfTurnPipeline publishes a fresh post-user
            # snapshot. Otherwise the background lane could happily stock a
            # scene seed from the conversation that just became stale.
            self._context_request = {}
            self._context_fingerprint = ""
            self._entries = [
                entry
                for entry in self._entries
                if entry.expires_at > current
                and entry.seed.source_kind in {"user_memory", "eris_self_memory"}
            ]
            self._condition.notify_all()

    def peek(self, *, now: float | None = None) -> SeedReservoirPreview | None:
        """Return the best ready seed without leasing or removing it."""
        if not self.enabled:
            return None
        current = float(now if now is not None else self.clock())
        with self._condition:
            self._prune_locked(current)
            candidates = [entry for entry in self._entries if self._entry_compatible_locked(entry)]
            if not candidates:
                self._condition.notify_all()
                return None
            chosen = max(candidates, key=lambda entry: self._score_entry(entry, current))
            return SeedReservoirPreview(
                seed=chosen.seed, generated_at=chosen.generated_at, expires_at=chosen.expires_at,
                context_revision=chosen.context_revision,
            )

    def claim_seed(
        self, seed_id: str, *, context_revision: int, now: float | None = None
    ) -> SeedReservoirLease | None:
        """Lease exactly the seed selected by the Executive."""
        if not self.enabled or not seed_id:
            return None
        current = float(now if now is not None else self.clock())
        with self._condition:
            self._prune_locked(current)
            chosen = next((
                entry for entry in self._entries
                if entry.seed.seed_id == str(seed_id)
                and entry.context_revision == int(context_revision)
                and self._entry_compatible_locked(entry)
            ), None)
            if chosen is None:
                return None
            self._entries.remove(chosen)
            token = "seedlease_" + secrets.token_hex(10)
            self._leases[token] = _LeaseEntry(
                entry=chosen, leased_at=current, lease_expires_at=current + self.lease_ttl
            )
            self._last_claimed_mode = chosen.seed.mode
            self._condition.notify_all()
            return SeedReservoirLease(
                token=token, seed=chosen.seed, generated_at=chosen.generated_at,
                expires_at=chosen.expires_at, context_revision=chosen.context_revision,
            )

    def claim(self, *, now: float | None = None) -> SeedReservoirLease | None:
        """Compatibility wrapper over peek + exact claim."""
        preview = self.peek(now=now)
        if preview is None:
            return None
        return self.claim_seed(
            preview.seed.seed_id, context_revision=preview.context_revision, now=now
        )

    def release(self, token: str, *, reason: str = "deferred", now: float | None = None) -> bool:
        """Return a leased seed when the governor or Surface did not publish it."""

        if not token:
            return False
        current = float(now if now is not None else self.clock())
        with self._condition:
            leased = self._leases.pop(str(token), None)
            if leased is None:
                return False
            entry = leased.entry
            if entry.expires_at > current and self._entry_compatible_locked(entry):
                self._entries.append(entry)
                self._entries = self._entries[-self.max_size :]
            self._condition.notify_all()
        self._log("debug", "[random chat seed] lease released seed=%s reason=%s", entry.seed.seed_id, reason)
        return True

    def commit(self, token: str) -> bool:
        """Consume a lease after a successful public commit."""

        if not token:
            return False
        with self._condition:
            leased = self._leases.pop(str(token), None)
            self._condition.notify_all()
        if leased is None:
            return False
        self._log("debug", "[random chat seed] lease committed seed=%s", leased.entry.seed.seed_id)
        return True

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        current = float(now if now is not None else self.clock())
        with self._condition:
            self._prune_locked(current)
            return {
                "schema": "eris.random_chat_seed_reservoir.v1",
                "enabled": self.enabled,
                "worker_role": "seed",
                "target_size": self.target_size,
                "max_size": self.max_size,
                "ready": len(self._entries),
                "leased": len(self._leases),
                "context_revision": self._context_revision,
                "context_fingerprint": self._context_fingerprint,
                "user_epoch": self._user_epoch,
                "modes": {
                    mode: sum(1 for entry in self._entries if entry.seed.mode == mode)
                    for mode in ("shared", "user_led", "eris_led", "experimental")
                },
                "seeds": [
                    {
                        "seed_id": entry.seed.seed_id,
                        "mode": entry.seed.mode,
                        "source_kind": entry.seed.source_kind,
                        "topic_tags": list(entry.seed.topic_tags),
                        "generated_at": entry.generated_at,
                        "expires_at": entry.expires_at,
                    }
                    for entry in self._entries
                ],
            }

    def _run(self) -> None:
        while True:
            with self._condition:
                current = float(self.clock())
                self._prune_locked(current)
                while not self._stop and not self._ready_to_generate_locked(current):
                    wait_for = self._wait_seconds_locked(current)
                    self._condition.wait(timeout=wait_for)
                    current = float(self.clock())
                    self._prune_locked(current)
                if self._stop:
                    return
                request = self._generation_request_locked()
                context_revision = self._context_revision
                user_epoch = self._user_epoch
                context_fingerprint = self._context_fingerprint
                self._last_generate_at = current
                self._next_generate_at = current + self.min_generate_interval

            try:
                seed = self.generator.generate(request)
            except Exception as exc:  # last-resort containment
                self._log("warning", "[random chat seed] producer crashed softly: %s", exc)
                seed = RandomChatSeed()
                failed = True
            else:
                failed = False

            current = float(self.clock())
            wake = False
            with self._condition:
                if failed:
                    self._next_generate_at = max(self._next_generate_at, current + self.error_backoff)
                elif not seed.available:
                    self._next_generate_at = max(self._next_generate_at, current + self.none_backoff)
                else:
                    allowed, reason = self._validate_generated_locked(seed, current)
                    if allowed:
                        was_empty = not self._entries
                        effective_ttl = min(
                            self.default_ttl,
                            max(120.0, float(seed.ttl_seconds or self.default_ttl)),
                        )
                        self._entries.append(
                            _SeedEntry(
                                seed=seed,
                                generated_at=current,
                                expires_at=current + effective_ttl,
                                context_revision=context_revision,
                                user_epoch=user_epoch,
                                context_fingerprint=context_fingerprint,
                            )
                        )
                        self._entries = self._entries[-self.max_size :]
                        wake = was_empty
                        self._log(
                            "info",
                            "[random chat seed] stocked seed=%s mode=%s source=%s ready=%d",
                            seed.seed_id,
                            seed.mode,
                            seed.source_kind,
                            len(self._entries),
                        )
                    else:
                        self._log("debug", "[random chat seed] generated seed rejected reason=%s", reason)
                self._condition.notify_all()

            if wake and callable(self.wake_callback):
                try:
                    self.wake_callback()
                except Exception:
                    pass

    def _context_from_snapshot(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        raw_self = snapshot.get("self_context") if isinstance(snapshot.get("self_context"), Mapping) else {}
        raw_commentary = (
            snapshot.get("commentary_expectation")
            if isinstance(snapshot.get("commentary_expectation"), Mapping)
            else {}
        )
        # Keep public self material, not the full attention telemetry ticker. The
        # latter changes every few seconds and would make every stocked seed look
        # stale before Surface gets a chance to use it.
        eris_self_memory = {
            "agenda": [dict(item) for item in _sequence(raw_self.get("agenda"))[-6:] if isinstance(item, Mapping)],
            "private_mind_surface": [
                dict(item) for item in _sequence(raw_self.get("private_mind_surface"))[-6:] if isinstance(item, Mapping)
            ],
            "private_life_surface": [
                dict(item) for item in _sequence(raw_self.get("private_life_surface"))[-6:] if isinstance(item, Mapping)
            ],
            "has_public_seed": bool(raw_self.get("has_public_seed", False)),
            "strongest_seed_score": round(float(raw_self.get("strongest_seed_score", 0.0) or 0.0), 1),
        }
        return {
            "user_memory": _compact(snapshot.get("memory_context", ""), 2800),
            "recent_public_history": [
                {
                    "role": _compact(item.get("role", ""), 24),
                    "text": _compact(item.get("text", item.get("content", "")), 520),
                }
                if isinstance(item, Mapping)
                else {"role": "", "text": _compact(item, 360)}
                for item in _sequence(snapshot.get("recent_public_history"))[-8:]
            ],
            "eris_self_memory": eris_self_memory,
            "personality_summary": _compact(snapshot.get("personality_summary", ""), 1000),
            "identity_summary": _compact(snapshot.get("identity_summary", ""), 1000),
            "relationship": snapshot.get("relationship", {}) if isinstance(snapshot.get("relationship"), Mapping) else {},
            "shared_semantic_context": (
                snapshot.get("shared_semantic_context", {})
                if isinstance(snapshot.get("shared_semantic_context"), Mapping)
                else {}
            ),
            "commentary_expectation": {
                "enabled": bool(raw_commentary.get("enabled", True)),
                "due": bool(raw_commentary.get("due", False)),
                "required": bool(raw_commentary.get("required", False)),
                "reason": _compact(raw_commentary.get("reason", ""), 80),
                "anchor_kind": _compact(raw_commentary.get("anchor_kind", ""), 80),
                "policy_action": _compact(raw_commentary.get("policy_action", "wait"), 40),
            },
        }

    @staticmethod
    def _fingerprint_projection(request: Mapping[str, Any]) -> dict[str, Any]:
        shared = request.get("shared_semantic_context") if isinstance(request.get("shared_semantic_context"), Mapping) else {}
        packet = shared.get("packet") if isinstance(shared.get("packet"), Mapping) else {}
        self_memory = request.get("eris_self_memory") if isinstance(request.get("eris_self_memory"), Mapping) else {}
        def stable_surface(items: Any) -> list[dict[str, Any]]:
            return [
                {
                    "id": _compact(item.get("id", ""), 80),
                    "kind": _compact(item.get("kind", ""), 80),
                    "summary": _compact(item.get("summary", item.get("topic_seed", "")), 260),
                    "evidence_refs": list(_sequence(item.get("evidence_refs")))[:5],
                }
                for item in _sequence(items)
                if isinstance(item, Mapping)
            ]
        return {
            "user_memory": request.get("user_memory", ""),
            "recent_public_history": request.get("recent_public_history", ()),
            "eris_self_memory": {
                "agenda": stable_surface(self_memory.get("agenda")),
                "private_mind_surface": stable_surface(self_memory.get("private_mind_surface")),
                "private_life_surface": stable_surface(self_memory.get("private_life_surface")),
                "has_public_seed": bool(self_memory.get("has_public_seed", False)),
            },
            "personality_summary": request.get("personality_summary", ""),
            "identity_summary": request.get("identity_summary", ""),
            "relationship": request.get("relationship", {}),
            "semantic_scene": {
                "scene_id": shared.get("scene_id", packet.get("scene_id", "")),
                "version": shared.get("version", packet.get("version", "")),
                "foreground": packet.get("foreground", shared.get("foreground", "")),
            },
            "commentary_expectation": request.get("commentary_expectation", {}),
        }

    def _generation_request_locked(self) -> dict[str, Any]:
        learning = (
            self.seed_store.selection_context(now=self.clock())
            if self.seed_store is not None
            else {
                "adaptive_daring": 0.46,
                "daring_ceiling": 0.56,
                "user_affinities": [],
                "eris_interests": [],
                "recent_seeds": [],
                "exploration_mix": {
                    "shared": 0.42, "user_led": 0.23, "eris_led": 0.25, "experimental": 0.10,
                },
            }
        )
        requested_mode = self._requested_mode_locked(learning)
        queued = [
            {
                "seed_id": entry.seed.seed_id,
                "mode": entry.seed.mode,
                "premise": entry.seed.premise,
                "topic_tags": list(entry.seed.topic_tags),
                "source_kind": entry.seed.source_kind,
            }
            for entry in self._entries
        ]
        return {
            **dict(self._context_request),
            "seed_learning": learning,
            "reservoir_context": {
                "requested_mode": requested_mode,
                "target_size": self.target_size,
                "ready_size": len(self._entries),
                "queued_seeds": queued,
                "context_revision": self._context_revision,
                "rule": (
                    "Produce one durable semantic seed for the requested mode. Surface owns wording. "
                    "A reservoir seed may be used later, so avoid references that expire within seconds."
                ),
            },
            "seed_contract": {
                "authority": "semantic_seed_only",
                "surface_owns_wording": True,
                "must_be_specific": True,
                "must_allow_no_reply": True,
                "requested_mode": requested_mode,
                "modes": ["shared", "user_led", "eris_led", "experimental"],
            },
        }

    def _requested_mode_locked(self, learning: Mapping[str, Any]) -> str:
        mix = learning.get("exploration_mix") if isinstance(learning.get("exploration_mix"), Mapping) else {}
        modes = ("shared", "user_led", "eris_led", "experimental")
        counts = {mode: sum(1 for entry in self._entries if entry.seed.mode == mode) for mode in modes}
        weights = {
            "shared": float(mix.get("shared", 0.42) or 0.42),
            "user_led": float(mix.get("user_led", 0.23) or 0.23),
            "eris_led": float(mix.get("eris_led", 0.25) or 0.25),
            "experimental": float(mix.get("experimental", 0.10) or 0.10),
        }
        # Largest quota deficit wins. This keeps a stock with ego and exploration,
        # rather than four near-identical user-pleasing seeds wearing different IDs.
        return max(
            modes,
            key=lambda mode: (weights[mode] * self.target_size - counts[mode], weights[mode]),
        )

    def _validate_generated_locked(self, seed: RandomChatSeed, now: float) -> tuple[bool, str]:
        if not seed.available:
            return False, "seed_incomplete"
        if self.seed_store is not None:
            allowed, reason = self.seed_store.validate_seed(seed, now=now)
            if not allowed:
                return False, reason
        elif seed.generic or seed.intrusion_risk > 0.46 or seed.daring > 0.86:
            return False, "seed_policy_rejected"
        for entry in self._entries:
            if _similarity(seed.premise, entry.seed.premise) >= 0.68:
                return False, "reservoir_duplicate"
            if set(seed.topic_tags) == set(entry.seed.topic_tags) and seed.topic_tags:
                return False, "reservoir_topic_duplicate"
        for leased in self._leases.values():
            if _similarity(seed.premise, leased.entry.seed.premise) >= 0.68:
                return False, "leased_duplicate"
        return True, "allowed"

    def _ready_to_generate_locked(self, now: float) -> bool:
        return bool(
            self.enabled
            and self._context_request
            and len(self._entries) + len(self._leases) < self.target_size
            and now >= self._next_generate_at
        )

    def _wait_seconds_locked(self, now: float) -> float:
        if self._stop:
            return 0.05
        if not self._context_request or len(self._entries) + len(self._leases) >= self.target_size:
            return 15.0
        return max(0.25, min(15.0, self._next_generate_at - now))

    def _entry_compatible_locked(self, entry: _SeedEntry) -> bool:
        drift = max(0, self._context_revision - entry.context_revision)
        if entry.seed.source_kind == "recent_shared_context":
            return entry.user_epoch == self._user_epoch and drift <= 2
        if entry.seed.source_kind == "weak_association":
            return entry.user_epoch == self._user_epoch and drift <= 3
        if entry.seed.source_kind == "user_memory":
            return drift <= 8
        if entry.seed.source_kind == "eris_self_memory":
            return drift <= 10
        return False

    def _score_entry(self, entry: _SeedEntry, now: float) -> float:
        seed = entry.seed
        lifetime = max(1.0, entry.expires_at - entry.generated_at)
        freshness = max(0.0, min(1.0, (entry.expires_at - now) / lifetime))
        mode_novelty = 0.07 if seed.mode != self._last_claimed_mode else 0.0
        return (
            0.28 * seed.estimated_fit
            + 0.24 * seed.personal_stake
            + 0.18 * seed.authenticity
            + 0.12 * seed.confidence
            + 0.08 * seed.daring
            + 0.10 * freshness
            + mode_novelty
        )

    def _prune_locked(self, now: float) -> None:
        self._entries = [
            entry
            for entry in self._entries
            if entry.expires_at > now and self._entry_compatible_locked(entry)
        ]
        expired_tokens = [
            token for token, leased in self._leases.items()
            if leased.lease_expires_at <= now
        ]
        for token in expired_tokens:
            leased = self._leases.pop(token)
            entry = leased.entry
            if entry.expires_at > now and self._entry_compatible_locked(entry):
                self._entries.append(entry)
        if len(self._entries) > self.max_size:
            self._entries = sorted(
                self._entries,
                key=lambda entry: self._score_entry(entry, now),
                reverse=True,
            )[: self.max_size]

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass


__all__ = [
    "RANDOM_CHAT_SEED_OUTPUT_SCHEMA",
    "RandomChatSeedGenerator",
    "RandomChatSeedReservoir",
    "SeedReservoirPreview",
    "SeedReservoirLease",
]
