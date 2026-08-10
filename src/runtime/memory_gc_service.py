# -*- coding: utf-8 -*-
"""Daemon dọn memory định kỳ khi runtime rảnh.

Luồng mới:
1. Chạy maintenance deterministic/canonical hiện có.
2. Dùng DeepSeek worker ``critic`` để rà semantic memory.
3. Dọn Living User Memory:
   - rule deterministic xử lý null/open-loop đã xong;
   - Qwen embedding gom duplicate/near-duplicate;
   - DeepSeek critic đề xuất archive/weaken/merge;
   - validator trong UserProfileStore mới được áp dụng thật.
4. Thu gọn undo history và anchor journal.

Mặc định chạy mỗi 10 phút. Không chạy khi chat bận. Critic không có quyền sửa value,
tạo fact mới hoặc đụng vào memory do người dùng xác nhận trực tiếp. Một chút giới hạn
quyền lực chưa từng làm hại hệ thống lưu dữ liệu cá nhân nào cả.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

_DEFAULT_INTERVAL_SEC = 10 * 60  # 10 phút theo yêu cầu vận hành
_DEFAULT_ANCHOR_JOURNAL_MAX_MB = 50
_DEFAULT_DS_REVIEW_LIMIT = 80


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except Exception:
        return int(default)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


# ── Prompt semantic memory ────────────────────────────────────────────────────

_SEMANTIC_GC_SYSTEM = """You are the semantic-memory critic for ERIS.
Classify only the supplied entries. Output ONLY JSON.

Evidence rules:
- Model confidence is not evidence.
- KEEP facts with a canonical fact_key or direct durable evidence.
- DROP null/empty claims, transient greetings, one-off scene details, resolved tasks,
  unsupported emotional inference, and paraphrases that add no durable fact.
- When uncertain and evidence exists, KEEP. Do not invent replacements.

Schema:
{
  "decisions": [
    {"id": "<entry_id>", "action": "keep" | "drop", "reason": "short reason"}
  ]
}
"""

_SEMANTIC_GC_USER = """Semantic memory entries to review ({count} items):
{entries}

Return a decision for every supplied entry."""


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass
class MemoryGCResult:
    maintenance_ran: bool = False
    ds_reviewed: int = 0
    ds_dropped: int = 0
    living_reviewed: int = 0
    living_applied: int = 0
    living_archived: int = 0
    living_weakened: int = 0
    living_merged: int = 0
    living_history_removed: int = 0
    pruned_total: int = 0
    journal_compacted: bool = False
    duration_sec: float = 0.0
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "maintenance_ran": self.maintenance_ran,
            "ds_reviewed": self.ds_reviewed,
            "ds_dropped": self.ds_dropped,
            "living_reviewed": self.living_reviewed,
            "living_applied": self.living_applied,
            "living_archived": self.living_archived,
            "living_weakened": self.living_weakened,
            "living_merged": self.living_merged,
            "living_history_removed": self.living_history_removed,
            "pruned_total": self.pruned_total,
            "journal_compacted": self.journal_compacted,
            "duration_sec": round(self.duration_sec, 2),
            "warnings": self.warnings[:16],
            "notes": self.notes[:24],
        }


# ── Daemon ────────────────────────────────────────────────────────────────────

class MemoryGCService:
    """Thread daemon dọn memory định kỳ."""

    def __init__(
        self,
        *,
        memory_core: Any,
        llm_service: Any | None = None,
        idle_probe: Any | None = None,
        interval_seconds: float | None = None,
        ds_review_limit: int | None = None,
        anchor_journal_max_mb: float | None = None,
    ) -> None:
        self.memory_core = memory_core
        self.llm_service = llm_service
        self.idle_probe = idle_probe
        self.interval_seconds = float(
            interval_seconds
            if interval_seconds is not None
            else _env_float("ERIS_MEMORY_GC_INTERVAL_SEC", _DEFAULT_INTERVAL_SEC)
        )
        self.ds_review_limit = int(
            ds_review_limit
            if ds_review_limit is not None
            else _env_int("ERIS_MEMORY_GC_DS_LIMIT", _DEFAULT_DS_REVIEW_LIMIT)
        )
        self.anchor_journal_max_mb = float(
            anchor_journal_max_mb
            if anchor_journal_max_mb is not None
            else _env_float("ERIS_MEMORY_GC_JOURNAL_MAX_MB", _DEFAULT_ANCHOR_JOURNAL_MAX_MB)
        )
        self._enabled = _env_flag("ERIS_MEMORY_GC_ENABLED", True)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_run_at = 0.0
        self._last_living_user_review_version = -1
        self._last_living_user_review_at = 0.0
        self.last_result: dict[str, Any] = {}
        self.run_count = 0

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self._enabled:
            logger.info("[memory_gc] disabled via ERIS_MEMORY_GC_ENABLED=0")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ERIS-MemoryGC", daemon=True)
        self._thread.start()
        logger.info("[memory_gc] started; interval=%.0fs role=critic", self.interval_seconds)

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def run_once(self) -> MemoryGCResult:
        """Chạy một lượt GC đồng bộ, tiện cho test và nút trigger thủ công."""
        return self._run_gc()

    # ── Loop ───────────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        # Delay để không tranh VRAM/CPU với bootstrap model.
        startup_delay = _env_float("ERIS_MEMORY_GC_STARTUP_DELAY_SEC", 120.0)
        self._stop.wait(timeout=startup_delay)
        while not self._stop.is_set():
            try:
                now = time.time()
                if now - self._last_run_at >= self.interval_seconds and self._is_idle():
                    result = self._run_gc()
                    self._last_run_at = time.time()
                    self.last_result = result.to_dict()
                    self.run_count += 1
                    logger.info(
                        "[memory_gc] run #%d maintenance=%s semantic_drop=%d "
                        "living(applied=%d archive=%d weaken=%d merge=%d) pruned=%d (%.1fs)",
                        self.run_count,
                        result.maintenance_ran,
                        result.ds_dropped,
                        result.living_applied,
                        result.living_archived,
                        result.living_weakened,
                        result.living_merged,
                        result.pruned_total,
                        result.duration_sec,
                    )
            except Exception as exc:
                logger.warning("[memory_gc] loop error: %s", exc)
            self._stop.wait(timeout=30.0)

    def _is_idle(self) -> bool:
        probe = self.idle_probe
        if probe is None:
            return True
        try:
            return bool(probe())
        except TypeError:
            try:
                quiet_for = time.time() - self._last_run_at
                return bool(probe(quiet_for=quiet_for, now=time.time()))
            except Exception:
                return True
        except Exception:
            return True

    # ── GC logic ───────────────────────────────────────────────────────────────

    def _run_gc(self) -> MemoryGCResult:
        result = MemoryGCResult()
        t0 = time.time()

        # 1. Maintenance canonical hiện có: decay, prune, consolidate.
        try:
            from memory.memory_maintenance import MemoryMaintenanceRunner

            runner = MemoryMaintenanceRunner(
                self.memory_core,
                destructive=True,
                llm_service=self.llm_service,
            )
            report = runner.run(budget="normal", reason="memory_gc_periodic", destructive=True)
            result.maintenance_ran = True
            pruned = report.pruned if isinstance(report.pruned, dict) else {}
            result.pruned_total = int(pruned.get("dropped_total", 0))
            result.notes.extend(list(getattr(report, "notes", []) or [])[:8])
            result.warnings.extend(list(getattr(report, "warnings", []) or [])[:4])
        except Exception as exc:
            result.warnings.append(f"maintenance_failed:{type(exc).__name__}:{exc}")
            logger.warning("[memory_gc] maintenance runner failed: %s", exc)

        curator = self._get_curator_client()

        # 2. Semantic memory critic.
        try:
            self._run_semantic_review(result, curator)
        except Exception as exc:
            result.warnings.append(f"semantic_review_failed:{type(exc).__name__}:{exc}")
            logger.warning("[memory_gc] semantic review failed: %s", exc)

        # 3. Living-user curator: Qwen gom cụm, DeepSeek critic phán, rule áp dụng.
        try:
            self._run_living_user_review(result, curator)
        except Exception as exc:
            result.warnings.append(f"living_review_failed:{type(exc).__name__}:{exc}")
            logger.warning("[memory_gc] living-user review failed: %s", exc)

        # 4. Compact anchor journal nếu quá lớn.
        try:
            self._compact_anchor_journal(result)
        except Exception as exc:
            result.warnings.append(f"journal_compact_failed:{type(exc).__name__}:{exc}")

        result.duration_sec = time.time() - t0
        return result

    def _run_semantic_review(self, result: MemoryGCResult, critic: Any | None) -> None:
        if critic is None:
            result.notes.append("semantic_review_skipped:no_critic_worker")
            return

        semantic_store = getattr(self.memory_core, "semantic", None)
        if semantic_store is None or not hasattr(semantic_store, "load"):
            result.notes.append("semantic_review_skipped:no_semantic_store")
            return

        items = list(semantic_store.load())
        candidates = [item for item in items if self._is_semantic_gc_candidate(item)][: self.ds_review_limit]
        if not candidates:
            result.notes.append("semantic_review_skipped:no_candidates")
            return

        raw = self._call_model(
            critic,
            _SEMANTIC_GC_SYSTEM,
            _SEMANTIC_GC_USER.format(
                count=len(candidates),
                entries=self._format_semantic_entries(candidates),
            ),
            max_tokens=1600,
        )
        if not raw:
            result.warnings.append("semantic_review_no_response")
            return

        decisions = self._parse_decisions(raw)
        if not decisions:
            result.warnings.append("semantic_review_parse_failed")
            return

        drop_ids = {
            str(row.get("id"))
            for row in decisions
            if str(row.get("action", "")).strip().lower() == "drop"
        }
        # Chỉ drop ID trong candidate batch. Critic không được lén ghi tên hàng xóm.
        allowed_ids = {self._item_id(item) for item in candidates}
        drop_ids &= allowed_ids
        kept = [item for item in items if self._item_id(item) not in drop_ids]
        actually_dropped = len(items) - len(kept)
        if actually_dropped > 0 and hasattr(semantic_store, "save"):
            semantic_store.save(kept)
            result.ds_dropped = actually_dropped
            result.notes.append(f"semantic_dropped:{actually_dropped}")
        result.ds_reviewed = len(candidates)

    def _run_living_user_review(self, result: MemoryGCResult, critic: Any | None) -> None:
        living_user = getattr(self.memory_core, "living_user", None)
        if living_user is None:
            result.notes.append("living_review_skipped:no_living_user")
            return
        store = getattr(living_user, "profile_store", None)
        version = int(getattr(store, "version", -1))
        now = time.time()
        max_age = _env_float("ERIS_MEMORY_GC_LIVING_REVIEW_MAX_AGE_SEC", 24 * 3600.0)
        if (
            version == self._last_living_user_review_version
            and now - self._last_living_user_review_at < max_age
        ):
            result.notes.append("living_review_skipped:profile_unchanged")
            return

        from memory.living_user.curator import LivingUserMemoryCurator

        reviewer = None
        if critic is not None:
            reviewer = lambda system, user, max_tokens: self._call_model(
                critic, system, user, max_tokens=max_tokens
            )
        curator = LivingUserMemoryCurator(
            living_user,
            reviewer=reviewer,
            embedding_index=getattr(living_user, "embedding_index", None),
        )
        report = curator.run()
        result.living_reviewed = report.reviewed
        result.living_applied = report.applied
        result.living_archived = report.archived
        result.living_weakened = report.weakened
        result.living_merged = report.merged
        result.living_history_removed = report.history_removed
        result.warnings.extend(report.warnings[:6])
        result.notes.extend(report.notes[:8])
        if report.skipped_reason:
            result.notes.append(f"living_review:{report.skipped_reason}")

        # Nếu critic tạm chết thì thử lại ở chu kỳ kế tiếp, không khóa 24 giờ chỉ
        # vì một process worker vừa hắt hơi.
        if report.skipped_reason != "no_critic_reviewer":
            self._last_living_user_review_version = int(getattr(store, "version", version))
            self._last_living_user_review_at = now

    def _compact_anchor_journal(self, result: MemoryGCResult) -> None:
        core_dir = str(os.getenv("ERIS_MEMORY_CORE_DIR", "memory_core"))
        journal_path = os.path.join(core_dir, "anchor_journal.jsonl")
        if not os.path.isfile(journal_path):
            return
        size_mb = os.path.getsize(journal_path) / (1024 * 1024)
        if size_mb <= self.anchor_journal_max_mb:
            return

        with open(journal_path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
        # Giữ 60% dòng gần nhất; event ledger canonical không nằm ở file này.
        keep_from = max(0, len(lines) - int(len(lines) * 0.6))
        kept_lines = lines[keep_from:]
        tmp = journal_path + ".gc_tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.writelines(kept_lines)
        os.replace(tmp, journal_path)
        result.journal_compacted = True
        result.notes.append(f"journal_compacted:{size_mb:.1f}MB->{len(kept_lines)}_lines")

    # ── Client/model helpers ───────────────────────────────────────────────────

    def _get_critic_client(self) -> Any | None:
        try:
            pm = getattr(self.llm_service, "_process_manager", None)
            if pm is None:
                pm = getattr(self.llm_service, "process_manager", None)
            if pm is not None:
                client = pm.build_deepseek_worker_client("critic", required=False)
                if client is not None:
                    return client
        except Exception:
            pass
        return getattr(self.llm_service, "critic_client", None) or getattr(self.llm_service, "social_critic_client", None)

    def _get_curator_client(self) -> Any | None:
        """Lấy đúng DeepSeek curator worker, nếu không có thì fallback sang critic."""
        try:
            from llm.process_manager import RemoteModelProcessManager

            pm = getattr(self.llm_service, "_process_manager", None)
            if pm is None:
                pm = getattr(self.llm_service, "process_manager", None)
            if pm is None and isinstance(self.llm_service, RemoteModelProcessManager):
                pm = self.llm_service
            if pm is not None:
                client = pm.build_deepseek_worker_client("curator", required=False)
                if client is not None:
                    return client
                client = pm.build_deepseek_worker_client("critic", required=False)
                if client is not None:
                    return client
        except Exception:
            pass

        client = (
            getattr(self.llm_service, "critic_client", None)
            or getattr(self.llm_service, "social_critic_client", None)
        )
        if client is not None:
            return client

        # Fallback bị tắt mặc định để không dựng Gemma lên chỉ để làm sổ sách.
        if _env_flag("ERIS_MEMORY_GC_ALLOW_MODEL_FALLBACK", False):
            return (
                getattr(self.llm_service, "inner_client", None)
                or getattr(self.llm_service, "client", None)
            )
        return None

    def _call_model(self, client: Any, system: str, user: str, *, max_tokens: int) -> str | None:
        try:
            response = client.create_chat_completion(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                timeout=_env_float("ERIS_MEMORY_GC_CRITIC_TIMEOUT_SEC", 45.0),
            )
            extract = getattr(self.llm_service, "_extract_content", None)
            if callable(extract):
                return str(extract(response) or "")
            choices = response.get("choices") if isinstance(response, dict) else None
            if choices and isinstance(choices, list):
                message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
                return str(message.get("content", "") or "")
            return None
        except Exception as exc:
            logger.warning("[memory_gc] critic call failed: %s", exc)
            return None

    # ── Semantic helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_decisions(raw: str) -> list[dict[str, Any]]:
        text = str(raw or "").strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start < 0 or end <= start:
            return []
        try:
            data = json.loads(text[start:end])
        except Exception:
            return []
        rows = data.get("decisions", []) if isinstance(data, dict) else []
        return [dict(row) for row in rows if isinstance(row, dict) and row.get("id")]

    def _is_semantic_gc_candidate(self, item: Any) -> bool:
        metadata = self._metadata(item)
        getter = item.get if isinstance(item, dict) else lambda key, default=None: getattr(item, key, default)
        fact_key = str(
            getter("fact_key", "")
            or metadata.get("fact_key")
            or ""
        ).strip()
        claim = str(
            getter("claim", "")
            or getter("summary", "")
            or getter("semantic_value", "")
            or ""
        ).strip()
        if not claim:
            return True
        # Canonical fact_key có evidence được bảo vệ khỏi batch critic thông thường.
        evidence = tuple(getter("evidence_ids", ()) or metadata.get("evidence_ids", ()) or ())
        if fact_key and evidence:
            return False
        confidence = float(getter("confidence", metadata.get("confidence", 0.5)) or 0.5)
        source = str(getter("source", "") or metadata.get("source", "") or "")
        return confidence < 0.82 or source in {"profile_model", "dream_model", "model_inference"}

    def _format_semantic_entries(self, items: list[Any]) -> str:
        lines: list[str] = []
        for item in items:
            metadata = self._metadata(item)
            payload = {
                "id": self._item_id(item),
                "fact_key": str(getattr(item, "fact_key", "") or metadata.get("fact_key") or ""),
                "claim": str(
                    getattr(item, "claim", "")
                    or getattr(item, "summary", "")
                    or getattr(item, "semantic_value", "")
                    or ""
                )[:420],
                "confidence": float(getattr(item, "confidence", metadata.get("confidence", 0.5)) or 0.5),
                "source": str(getattr(item, "source", "") or metadata.get("source", ""))[:60],
                "evidence_ids": list(getattr(item, "evidence_ids", ()) or metadata.get("evidence_ids", ()) or ())[:12],
            }
            lines.append(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))
        return "\n".join(lines)

    @staticmethod
    def _item_id(item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("id") or item.get("claim_id") or id(item))
        return str(getattr(item, "id", "") or getattr(item, "claim_id", "") or id(item))

    @staticmethod
    def _metadata(item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            return dict(item.get("metadata") or {})
        return dict(getattr(item, "metadata", {}) or {})


# ── Builder ───────────────────────────────────────────────────────────────────

def build_memory_gc_service(
    *,
    memory_core: Any,
    llm_service: Any | None = None,
    idle_probe: Any | None = None,
) -> MemoryGCService | None:
    """Builder trả MemoryGCService đã start(), hoặc None nếu bị tắt."""
    if not _env_flag("ERIS_MEMORY_GC_ENABLED", True) or memory_core is None:
        return None
    try:
        service = MemoryGCService(
            memory_core=memory_core,
            llm_service=llm_service,
            idle_probe=idle_probe,
        )
        service.start()
        return service
    except Exception as exc:
        logger.warning("[memory_gc] build failed: %s", exc)
        return None


__all__ = ["MemoryGCResult", "MemoryGCService", "build_memory_gc_service"]
