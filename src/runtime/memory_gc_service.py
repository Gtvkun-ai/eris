# -*- coding: utf-8 -*-
"""
runtime.memory_gc_service
=========================

Daemon dọn dẹp memory định kỳ mỗi 20 phút khi runtime rảnh tay.

Làm 3 việc mỗi lượt:
1. MemoryMaintenanceRunner.run(budget="normal", destructive=True)
   - Prune thật các item hết hạn / rác (session/transient/noise)
   - Access decay (half-life 7 ngày)
   - Consolidate memory candidate
   - AI curator: distill episodic cluster → semantic fact,
     bridge concern chín → long-term memory
2. Gọi DeepSeek (worker "inner") để AI đánh giá thêm:
   - Quét semantic_memory.json và epistemic_v2.json
   - Chấm điểm từng entry, trả về danh sách ID nên xóa/giữ
   - Drop các entry confidence thấp không có fact_key
3. Compact anchor_journal.jsonl nếu quá lớn (> 50MB)

Không chạy nếu:
- Đang có chat đang xử lý (idle_probe trả False)
- Interval chưa đủ 20 phút kể từ lần chạy trước
- LLM service hoặc memory_core chưa sẵn sàng
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

_DEFAULT_INTERVAL_SEC = 20 * 60  # 20 phút
_DEFAULT_ANCHOR_JOURNAL_MAX_MB = 50
_DEFAULT_DS_REVIEW_LIMIT = 80  # số entry tối đa gửi DeepSeek đánh giá mỗi lượt


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except Exception:
        return default


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


# ── Prompt ────────────────────────────────────────────────────────────────────

_GC_SYSTEM = """You are a memory garbage collector for ERIS, an AI companion.
You receive a batch of memory entries and must classify each one.

Rules:
- Output ONLY a JSON object, no prose.
- For each entry, decide: "keep" or "drop".
- DROP if: confidence < 0.40, OR the claim is a transient social phrase
  (greetings, slang observations, questions about ERIS's name, one-time events
  with no lasting significance).
- KEEP if: the entry has a fact_key, OR confidence >= 0.65, OR the claim
  describes a stable user trait / preference / relationship pattern.
- When uncertain, KEEP.

Output schema:
{
  "decisions": [
    {"id": "<entry_id>", "action": "keep"|"drop", "reason": "<short reason>"}
  ]
}"""

_GC_USER = """Memory entries to review ({count} items):
{entries}

Return decisions for all {count} entries."""


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass
class MemoryGCResult:
    maintenance_ran: bool = False
    ds_reviewed: int = 0
    ds_dropped: int = 0
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
            "pruned_total": self.pruned_total,
            "journal_compacted": self.journal_compacted,
            "duration_sec": round(self.duration_sec, 2),
            "warnings": self.warnings[:12],
            "notes": self.notes[:16],
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
        self._thread = threading.Thread(
            target=self._loop,
            name="ERIS-MemoryGC",
            daemon=True,
        )
        self._thread.start()
        logger.info("[memory_gc] started; interval=%.0fs", self.interval_seconds)

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def run_once(self) -> MemoryGCResult:
        """Chạy một lượt GC đồng bộ (dùng để test hoặc trigger thủ công)."""
        return self._run_gc()

    # ── Loop ───────────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        # Delay khởi động để không tranh tài nguyên với bootstrap
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
                        "[memory_gc] run #%d done: maintenance=%s ds_dropped=%d pruned=%d journal_compact=%s (%.1fs)",
                        self.run_count,
                        result.maintenance_ran,
                        result.ds_dropped,
                        result.pruned_total,
                        result.journal_compacted,
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

        # 1. MemoryMaintenanceRunner (prune thật, AI curator)
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
            notes = getattr(report, "notes", [])
            warnings = getattr(report, "warnings", [])
            result.notes.extend(notes[:8])
            result.warnings.extend(warnings[:4])
        except Exception as exc:
            result.warnings.append(f"maintenance_failed:{type(exc).__name__}:{exc}")
            logger.warning("[memory_gc] maintenance runner failed: %s", exc)

        # 2. DeepSeek AI review — quét semantic_memory entries
        try:
            self._run_deepseek_review(result)
        except Exception as exc:
            result.warnings.append(f"ds_review_failed:{type(exc).__name__}:{exc}")
            logger.warning("[memory_gc] DeepSeek review failed: %s", exc)

        # 3. Compact anchor_journal.jsonl nếu quá lớn
        try:
            self._compact_anchor_journal(result)
        except Exception as exc:
            result.warnings.append(f"journal_compact_failed:{type(exc).__name__}:{exc}")

        result.duration_sec = time.time() - t0
        return result

    def _run_deepseek_review(self, result: MemoryGCResult) -> None:
        """Gọi DeepSeek worker 'inner' để đánh giá và xóa semantic memory rác."""
        client = self._get_ds_client()
        if client is None:
            result.notes.append("ds_review_skipped:no_inner_worker")
            return

        semantic_store = getattr(self.memory_core, "semantic", None)
        if semantic_store is None or not hasattr(semantic_store, "load"):
            result.notes.append("ds_review_skipped:no_semantic_store")
            return

        items = list(semantic_store.load())
        if not items:
            result.notes.append("ds_review_skipped:empty_store")
            return

        # Chỉ xem xét entry không có fact_key hoặc confidence thấp
        candidates = [
            item for item in items
            if self._is_gc_candidate(item)
        ][:self.ds_review_limit]

        if not candidates:
            result.notes.append("ds_review_skipped:no_candidates")
            return

        entries_text = self._format_entries_for_review(candidates)
        user_prompt = _GC_USER.format(
            count=len(candidates),
            entries=entries_text,
        )

        raw = self._call_ds(client, _GC_SYSTEM, user_prompt)
        if not raw:
            result.warnings.append("ds_review_no_response")
            return

        decisions = self._parse_decisions(raw)
        if not decisions:
            result.warnings.append("ds_review_parse_failed")
            return

        # Áp dụng quyết định drop
        drop_ids = {
            d["id"] for d in decisions
            if str(d.get("action", "")).strip().lower() == "drop"
        }
        if not drop_ids:
            result.ds_reviewed = len(candidates)
            result.notes.append("ds_review_no_drops")
            return

        # Lọc ra items cần giữ
        kept = [item for item in items if self._item_id(item) not in drop_ids]
        actually_dropped = len(items) - len(kept)

        if actually_dropped > 0 and hasattr(semantic_store, "save"):
            semantic_store.save(kept)
            result.ds_dropped = actually_dropped
            result.notes.append(
                f"ds_dropped:{actually_dropped}_items_from_semantic_store"
            )

        result.ds_reviewed = len(candidates)

    def _compact_anchor_journal(self, result: MemoryGCResult) -> None:
        """Cắt bỏ phần đầu anchor_journal.jsonl nếu quá lớn."""
        core_dir = str(os.getenv("ERIS_MEMORY_CORE_DIR", "memory_core"))
        journal_path = os.path.join(core_dir, "anchor_journal.jsonl")
        if not os.path.isfile(journal_path):
            return
        size_mb = os.path.getsize(journal_path) / (1024 * 1024)
        if size_mb <= self.anchor_journal_max_mb:
            return

        try:
            with open(journal_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            # Giữ 60% dòng gần nhất
            keep_from = max(0, len(lines) - int(len(lines) * 0.6))
            kept_lines = lines[keep_from:]
            tmp = journal_path + ".gc_tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(kept_lines)
            os.replace(tmp, journal_path)
            result.journal_compacted = True
            result.notes.append(
                f"journal_compacted:{size_mb:.1f}MB→{len(kept_lines)}_lines_kept"
            )
        except Exception as exc:
            result.warnings.append(f"journal_compact_io_error:{exc}")

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _get_ds_client(self) -> Any | None:
        """Lấy DeepSeek inner worker client nếu có."""
        try:
            from llm.process_manager import RemoteModelProcessManager
            pm = getattr(self.llm_service, "_process_manager", None)
            if pm is None:
                pm = getattr(self.llm_service, "process_manager", None)
            if pm is None and isinstance(self.llm_service, RemoteModelProcessManager):
                pm = self.llm_service
            if pm is not None:
                client = pm.build_deepseek_worker_client("inner", required=False)
                return client
        except Exception:
            pass
        # Fallback: dùng main inner_client nếu không có DS worker
        client = getattr(self.llm_service, "inner_client", None) or getattr(self.llm_service, "client", None)
        return client

    def _call_ds(self, client: Any, system: str, user: str, *, max_tokens: int = 1024) -> str | None:
        try:
            response = client.create_chat_completion(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                timeout=30.0,
            )
            # Extract content
            extract = getattr(self.llm_service, "_extract_content", None)
            if callable(extract):
                return str(extract(response) or "")
            choices = response.get("choices") if isinstance(response, dict) else None
            if choices and isinstance(choices, list):
                msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
                return str(msg.get("content", "") or "")
            return None
        except Exception as exc:
            logger.warning("[memory_gc] DS call failed: %s", exc)
            return None

    def _parse_decisions(self, raw: str) -> list[dict[str, Any]]:
        text = str(raw or "").strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start < 0 or end <= start:
            return []
        try:
            data = json.loads(text[start:end])
            decisions = data.get("decisions", [])
            if not isinstance(decisions, list):
                return []
            return [d for d in decisions if isinstance(d, dict) and d.get("id")]
        except Exception:
            return []

    def _is_gc_candidate(self, item: Any) -> bool:
        """True nếu entry đáng để AI review (không có fact_key hoặc confidence thấp)."""
        metadata = self._metadata(item)
        fact_key = str(metadata.get("fact_key") or "").strip()
        if fact_key:
            return False  # Đã có fact_key quan trọng, không cần AI review
        confidence = float(getattr(item, "confidence", metadata.get("confidence", 0.5)) or 0.5)
        return confidence < 0.80  # Chỉ review entry chưa đủ chắc

    def _format_entries_for_review(self, items: list[Any]) -> str:
        lines = []
        for item in items:
            item_id = self._item_id(item)
            claim = str(getattr(item, "claim", "") or getattr(item, "summary", "") or "")[:200]
            confidence = float(getattr(item, "confidence", 0.5) or 0.5)
            source = str(getattr(item, "source", "") or "")[:40]
            lines.append(f'- id={item_id} conf={confidence:.2f} src={source}: "{claim}"')
        return "\n".join(lines)

    def _item_id(self, item: Any) -> str:
        return str(getattr(item, "id", "") or getattr(item, "claim_id", "") or id(item))

    def _metadata(self, item: Any) -> dict[str, Any]:
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
    if not _env_flag("ERIS_MEMORY_GC_ENABLED", True):
        return None
    if memory_core is None:
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


__all__ = [
    "MemoryGCResult",
    "MemoryGCService",
    "build_memory_gc_service",
]
