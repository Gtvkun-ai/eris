from __future__ import annotations

"""
memory_maintenance.py
=====================

Runner maintain cho MemoryKernel.

File này gom các việc nền vốn đang nằm rải rác:
- consolidate unresolved memory candidates;
- prune/đánh dấu memory hết hạn theo retention metadata;
- kiểm tra contradiction ở mức nhẹ;
- chuẩn bị chỗ cho decay access stats sau này.

Điểm quan trọng:
- Mặc định KHÔNG xóa dữ liệu thật. Nó chỉ audit/prune plan.
- Muốn drop item thật phải bật destructive=True rõ ràng.
- Maintain không được gọi trong hot path chat. Gọi nó trong idle/reflection/session_end.

Nói cách khác: đây là chổi và thùng rác có khóa trẻ em. Vì memory mà lỡ tay xóa
thì debug sẽ rất thi vị, theo nghĩa tệ nhất.
"""

from dataclasses import asdict
from typing import Any, Iterable

from .memory_consolidator import MemoryConsolidator
from .memory_pruner import MemoryPruner
from .memory_kernel_contracts import MaintenanceBudget, MemoryMaintenanceReport


class MemoryMaintenanceRunner:
    """Orchestrator maintain nhẹ cho memory stores.

    Runner nhận `memory_core`/`MemoryKernel.core` hiện có. Nó không tự mở file JSON.
    Điều này giữ một nguồn truth duy nhất: store vẫn thuộc MemoryCognitionCore.
    """

    def __init__(self, memory_core: Any, *, ingest_policy: Any = None, destructive: bool = False) -> None:
        self.memory_core = memory_core
        self.ingest_policy = ingest_policy
        self.destructive = bool(destructive)
        self.pruner = MemoryPruner()

    def run(
        self,
        *,
        budget: MaintenanceBudget = "small",
        reason: str = "idle",
        destructive: bool | None = None,
    ) -> MemoryMaintenanceReport:
        """Chạy một lượt maintain.

        destructive=None nghĩa là dùng default từ runner.
        destructive=False nghĩa là chỉ audit, không drop item.
        destructive=True nghĩa là được save lại store sau khi bỏ item action=drop.
        """

        allow_destructive = self.destructive if destructive is None else bool(destructive)
        report = MemoryMaintenanceReport(reason=reason, budget=budget)

        # 1. Chưng cất candidate trước. Candidate là vùng đệm của câu user muốn nhớ
        # nhưng parser chưa đủ chắc. Nếu không consolidate, candidate thành nghĩa địa.
        try:
            limit = self._candidate_limit(budget)
            consolidator = MemoryConsolidator(self.memory_core, intake_policy=self.ingest_policy)
            result = consolidator.run_once(limit=limit)
            report.consolidated = result.to_dict() if hasattr(result, "to_dict") else asdict(result)
        except Exception as exc:  # pragma: no cover - maintain không được làm chết runtime
            report.warnings.append(f"consolidation_failed:{type(exc).__name__}:{exc}")

        # 2. Prune audit. Mặc định chỉ thống kê. Drop thật chỉ khi explicit bật.
        try:
            report.pruned = self._run_prune_audit(destructive=allow_destructive)
        except Exception as exc:  # pragma: no cover
            report.warnings.append(f"prune_failed:{type(exc).__name__}:{exc}")

        # 3. Contradiction repair tạm thời chỉ là placeholder có kiểm soát.
        # ClaimConsolidator hiện xử lý merge claim ở tầng claim, còn store-level repair
        # cần thêm index theo fact_key/predicate trước khi làm destructive.
        report.contradictions = {
            "checked": False,
            "reason": "store_level_contradiction_repair_not_enabled_yet",
        }

        # 4. Access decay chưa có schema chuẩn trong stores. Để note thay vì giả vờ đã làm.
        report.access_decay = {
            "applied": False,
            "reason": "access_stats_schema_not_standardized_yet",
        }

        if not allow_destructive:
            report.notes.append("maintenance_ran_in_audit_mode_no_items_deleted")
        return report

    def _candidate_limit(self, budget: MaintenanceBudget) -> int:
        if budget == "deep":
            return 48
        if budget == "normal":
            return 20
        return 6

    def _run_prune_audit(self, *, destructive: bool) -> dict[str, Any]:
        """Chạy prune trên các store có load/save.

        Các action:
        - keep: giữ nguyên.
        - archive: hiện chỉ thống kê vì chưa có archive store chuẩn.
        - drop: chỉ drop thật nếu destructive=True.
        """

        store_names = (
            "semantic",
            "relational",
            "episodic",
            "procedural",
            "affective_residue",
            "repair",
        )
        summary: dict[str, Any] = {
            "destructive": destructive,
            "stores": {},
            "dropped_total": 0,
            "archive_candidates_total": 0,
        }

        for name in store_names:
            store = getattr(self.memory_core, name, None)
            if store is None or not hasattr(store, "load"):
                continue
            items = list(store.load())
            kept: list[Any] = []
            dropped = 0
            archive_candidates = 0
            decisions: list[str] = []

            for item in items:
                decision = self.pruner.decide(item)
                decisions.append(f"{decision.action}:{decision.reason}")
                if decision.action == "drop" and destructive:
                    dropped += 1
                    continue
                if decision.action == "archive":
                    archive_candidates += 1
                kept.append(item)

            if destructive and dropped and hasattr(store, "save"):
                store.save(kept)

            summary["stores"][name] = {
                "items": len(items),
                "kept": len(kept),
                "dropped": dropped,
                "archive_candidates": archive_candidates,
                "sample_decisions": decisions[:8],
            }
            summary["dropped_total"] += dropped
            summary["archive_candidates_total"] += archive_candidates

        return summary


__all__ = ["MemoryMaintenanceRunner"]
