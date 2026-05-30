from __future__ import annotations

"""
memory_kernel.py
================

MemoryKernel là cổng thần kinh duy nhất cho memory runtime.

Mục tiêu của file này:
- Runtime không gọi trực tiếp MemoryCommitPolicy, MemoryQueryExecutor, PacketBuilder,
  CandidateStore, Pruner lung tung nữa.
- Runtime chỉ biết 4 động từ:
    ingest()       : đưa text/evidence vào memory lifecycle.
    answer()       : trả lời deterministic câu hỏi trí nhớ.
    build_packet() : dựng resonance/context packet cho prompt/cognition.
    maintain()     : chạy chưng cất/prune/repair nền.

Lưu ý quan trọng:
- MemoryKernel KHÔNG thay model thành quan tòa trí nhớ.
- Parser/model chỉ được đọc nghĩa ban đầu trong semantic_digest.
- Ontology, entailment, worthiness, retention và commit vẫn do code quyết.

Đây là facade thật, không phải thêm một lớp trang trí chỉ để repo trông có vẻ
kiến trúc hơn. Thế giới đã có đủ facade vô dụng rồi.
"""

import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .memory_cognition import CommitPolicy, MemoryCognitionCore, MemoryQuery
from .memory_commit_policy import MemoryCommitPolicy
from .memory_kernel_contracts import (
    MaintenanceBudget,
    MemoryAnswerResult,
    MemoryIngestMode,
    MemoryIngestResult,
    MemoryKernelConfig,
    MemoryMaintenanceReport,
)
from .memory_maintenance import MemoryMaintenanceRunner
from .memory_packet_builder import MemoryPacket
from .memory_query_compiler import MemoryQueryCompiler
from .memory_query_executor import MemoryQueryExecutor
from .memory_recall_policy import MemoryRecallSurfacePolicy
from .memory_turn_annotator import TurnAnnotator
from .memory_turn_graph import TurnGraph


@dataclass(slots=True)
class MemoryKernelDebugSnapshot:
    """Snapshot nhỏ cho dev mode.

    Không đưa thẳng ra public chat. Đây là để log/debug UI.
    """

    base_dir: str
    has_semantic_parser: bool
    fast_policy_has_parser: bool
    digest_policy_has_parser: bool
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_dir": self.base_dir,
            "has_semantic_parser": self.has_semantic_parser,
            "fast_policy_has_parser": self.fast_policy_has_parser,
            "digest_policy_has_parser": self.digest_policy_has_parser,
            "timestamp": self.timestamp,
        }


class MemoryKernel:
    """Facade chính cho toàn bộ memory runtime.

    Cách dùng khuyến nghị:

        kernel = MemoryKernel(base_dir="memory_core", semantic_parser=parser)
        kernel.ingest(user_text, mode="fast")
        kernel.ingest(user_text, mode="semantic_digest")  # worker nền gọi
        answer = kernel.answer("tôi tên gì", session_ledger=ledger)
        packet = kernel.build_packet("current task", budget_mode="normal")
        kernel.maintain(reason="idle", budget="small")

    Nếu runtime cũ vẫn đang truyền MemoryCognitionCore vào, dùng from_existing_core().
    """

    def __init__(
        self,
        base_dir: str | None = None,
        *,
        core: MemoryCognitionCore | None = None,
        semantic_parser: Any | None = None,
        config: MemoryKernelConfig | None = None,
        commit_policy: CommitPolicy | None = None,
        query_compiler: MemoryQueryCompiler | None = None,
        query_executor: MemoryQueryExecutor | None = None,
        surface_policy: MemoryRecallSurfacePolicy | None = None,
        turn_annotator: TurnAnnotator | None = None,
    ) -> None:
        if core is None and not base_dir:
            raise ValueError("MemoryKernel cần base_dir hoặc core hiện có")

        self.core = core or MemoryCognitionCore(str(base_dir), policy=commit_policy)
        self.config = config or MemoryKernelConfig()
        self.semantic_parser = semantic_parser

        # fast_policy cố tình KHÔNG nhận semantic_parser.
        # Đây là policy cho hot path, không được gọi model local/remote.
        self.fast_policy = MemoryCommitPolicy(semantic_parser=None)

        # digest_policy được quyền dùng parser đã nối, thường chạy ở worker nền.
        self.digest_policy = MemoryCommitPolicy(semantic_parser=semantic_parser)

        self.query_compiler = query_compiler or MemoryQueryCompiler()
        self.query_executor = query_executor or MemoryQueryExecutor()
        self.surface_policy = surface_policy or MemoryRecallSurfacePolicy()
        self.turn_annotator = turn_annotator or TurnAnnotator()

    @classmethod
    def from_existing_core(
        cls,
        core: MemoryCognitionCore,
        *,
        semantic_parser: Any | None = None,
        config: MemoryKernelConfig | None = None,
    ) -> "MemoryKernel":
        """Bọc MemoryCognitionCore hiện có mà không migrate store ngay.

        Dùng trong runtime chuyển tiếp: coordinator vẫn build memory_core cũ,
        nhưng các path mới gọi qua MemoryKernel.
        """

        return cls(core=core, semantic_parser=semantic_parser, config=config)

    # ------------------------------------------------------------------
    # Ingest path
    # ------------------------------------------------------------------

    def ingest(
        self,
        text: str,
        *,
        evidence_ids: list[str] | None = None,
        turn_id: str | None = None,
        source: str = "chat_turn",
        mode: MemoryIngestMode = "fast",
        allow_candidate: bool | None = None,
        storage_permission: bool = True,
        permission_required: bool = False,
        context: Mapping[str, Any] | None = None,
    ) -> MemoryIngestResult:
        """Đưa một mảnh text/evidence vào memory lifecycle.

        Đây là cổng ingest duy nhất mà runtime nên gọi.

        mode="fast":
            Không gọi parser/model. Dùng rule rẻ để commit fact rõ.

        mode="semantic_digest":
            Dùng digest_policy, có thể gọi parser model local đã inject.
            Thích hợp cho background worker khi remote API đang pending.

        mode="reflection":
            Giống semantic_digest nhưng source/debug thể hiện là reflection.
        """

        raw = str(text or "").strip()
        if not raw:
            return MemoryIngestResult(
                accepted=False,
                mode=mode,
                source=source,
                input_text="",
                warnings=["empty_ingest_text"],
            )

        allow_candidate = self.config.allow_candidate_by_default if allow_candidate is None else bool(allow_candidate)
        policy = self.fast_policy if mode == "fast" else self.digest_policy

        # turn_id là evidence mặc định nếu caller chưa đưa evidence_ids.
        # Không có evidence thì commit layer hiện tại sẽ reject nhiều target, đúng thôi.
        effective_evidence = list(evidence_ids or [])
        if not effective_evidence and turn_id:
            effective_evidence = [str(turn_id)]

        # MemoryCommitPolicy hiện nhận turn_id, evidence nằm trong decision.
        # Nếu cần evidence_ids trực tiếp hơn, sửa policy sau, không nhét hack vào store.
        decisions = policy.decide_from_user_turn(
            raw,
            turn_id=turn_id or (effective_evidence[0] if effective_evidence else None),
            allow_candidate=allow_candidate,
        )

        commit_results: list[Any] = []
        warnings: list[str] = []
        for decision in decisions:
            try:
                # Semantic digest không được commit claim quá yếu.
                confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
                if mode != "fast" and confidence < self.config.digest_commit_min_confidence:
                    warnings.append(f"digest_decision_confidence_low:{confidence:.2f}")
                    continue

                request = decision.to_state_commit_request(
                    storage_permission=storage_permission,
                    permission_required=permission_required,
                )
                request = self._annotate_request(
                    request,
                    mode=mode,
                    source=source,
                    context=context,
                    evidence_ids=effective_evidence,
                )
                commit_results.append(self.core.commit(request))
            except Exception as exc:  # pragma: no cover - ingest không được giết chat cycle
                warnings.append(f"commit_failed:{type(exc).__name__}:{exc}")

        return MemoryIngestResult(
            accepted=bool(commit_results),
            mode=mode,
            source=source,
            input_text=raw,
            decisions=list(decisions),
            commit_results=commit_results,
            warnings=warnings,
            debug={
                "decision_count": len(decisions),
                "evidence_ids": effective_evidence,
                "has_semantic_parser": self.semantic_parser is not None,
                "policy": "fast_policy" if policy is self.fast_policy else "digest_policy",
            },
        )

    # ------------------------------------------------------------------
    # Answer path
    # ------------------------------------------------------------------

    def answer(
        self,
        query: str,
        *,
        session_ledger: Any | None = None,
        context: Mapping[str, Any] | None = None,
        min_confidence: float | None = None,
        max_ambiguity: float | None = None,
    ) -> MemoryAnswerResult:
        """Trả lời deterministic cho câu hỏi memory nếu đủ chắc.

        Hàm này không gọi LLM để trả lời. Nếu compiler cần LLM structured parser thì
        nó chỉ được trả IR, không được trả text public bịa từ trí nhớ.
        """

        raw = str(query or "").strip()
        if not raw:
            return MemoryAnswerResult(intercepted=False, reason="empty_query")

        min_confidence = self.config.answer_min_confidence if min_confidence is None else float(min_confidence)
        max_ambiguity = self.config.answer_max_ambiguity if max_ambiguity is None else float(max_ambiguity)

        compile_result = self.query_compiler.compile(raw)
        if not compile_result.has_query or compile_result.best is None:
            return MemoryAnswerResult(
                intercepted=False,
                compile_result=compile_result,
                reason="not_memory_query",
                debug=self._compile_debug(compile_result),
            )

        best = compile_result.best
        confidence = float(getattr(best, "confidence", 0.0) or 0.0)
        ambiguity = float(getattr(best, "ambiguity", 1.0) or 1.0)
        if confidence < min_confidence:
            return MemoryAnswerResult(
                intercepted=False,
                compile_result=compile_result,
                reason=f"query_confidence_low:{confidence:.2f}",
                debug=self._compile_debug(compile_result),
            )
        if ambiguity > max_ambiguity:
            return MemoryAnswerResult(
                intercepted=False,
                compile_result=compile_result,
                reason=f"query_ambiguity_high:{ambiguity:.2f}",
                debug=self._compile_debug(compile_result),
            )

        turn_graph = None
        if session_ledger is not None:
            turn_graph = TurnGraph.from_session_ledger(session_ledger, annotator=self.turn_annotator)

        raw_result = self.query_executor.execute(
            best,
            turn_graph=turn_graph,
            memory_core=self.core,
        )
        answer = self.surface_policy.surface(raw_result)
        answer_text = str(getattr(answer, "text", "") or "").strip()
        intercepted = bool(answer_text) and float(getattr(answer, "confidence", 0.0) or 0.0) >= min_confidence

        return MemoryAnswerResult(
            intercepted=intercepted,
            answer=answer,
            compile_result=compile_result,
            raw_result=raw_result,
            reason="answered" if intercepted else "answer_not_confident_enough",
            debug={
                **self._compile_debug(compile_result),
                "raw_found": bool(getattr(raw_result, "found", False)),
                "answer_confidence": float(getattr(answer, "confidence", 0.0) or 0.0),
                "context_keys": sorted((context or {}).keys()),
            },
        )

    # ------------------------------------------------------------------
    # Packet/resonance path
    # ------------------------------------------------------------------

    def build_packet(
        self,
        query: str = "",
        *,
        budget_mode: str = "normal",
        max_items: int = 18,
        token_budget: int = 900,
        frame: Any | None = None,
    ) -> MemoryPacket:
        """Dựng MemoryPacket/resonance context cho cognition.

        Packet không phải exact answer. Packet là áp lực nội bộ được quota theo layer.
        Runtime/prompt builder dùng nó như context có kiểm soát.
        """

        q = MemoryQuery(
            query=str(query or ""),
            budget_mode=budget_mode if budget_mode in {"fast", "normal", "deep", "reflection"} else "normal",
            max_items=max_items,
            token_budget=token_budget,
        )
        return self.core.recall(q, frame=frame)

    # Alias cho code đọc thuận miệng hơn.
    recall_packet = build_packet

    # ------------------------------------------------------------------
    # Maintain path
    # ------------------------------------------------------------------

    def maintain(
        self,
        *,
        budget: MaintenanceBudget = "small",
        reason: str = "idle",
        destructive: bool | None = None,
    ) -> MemoryMaintenanceReport:
        """Chạy maintenance nền.

        Không gọi trong hot path chat. Gọi từ idle/reflection/session end.
        """

        runner = MemoryMaintenanceRunner(
            self.core,
            ingest_policy=self.digest_policy,
            destructive=self.config.destructive_maintenance,
        )
        return runner.run(budget=budget, reason=reason, destructive=destructive)

    # ------------------------------------------------------------------
    # Compatibility helpers: để migration không phải sửa cả repo trong một nhát.
    # ------------------------------------------------------------------

    def commit(self, request: Any, *, frame: Any = None) -> Any:
        """Compat: route commit cũ xuống core.

        Runtime mới nên gọi ingest(), nhưng StateCommitter cũ vẫn có thể gọi commit().
        """

        return self.core.commit(request, frame=frame)

    def commit_many(self, requests: list[Any], *, frame: Any = None) -> list[Any]:
        return self.core.commit_many(requests, frame=frame)

    def recall(self, query: Any = "", *, frame: Any = None) -> MemoryPacket:
        """Compat với MemoryCognitionCore.recall()."""

        return self.core.recall(query, frame=frame)

    def retrieve(self, query: Any = "", *, frame: Any = None) -> MemoryPacket:
        return self.core.retrieve(query, frame=frame)

    def load(self) -> dict[str, Any]:
        return self.core.load()

    def save(self, snapshot: Mapping[str, Any] | None = None) -> None:
        self.core.save(snapshot)

    def render_context(self, *args: Any, **kwargs: Any) -> str:
        return self.core.render_context(*args, **kwargs)

    def lookup_fact(self, fact_key: str) -> Any:
        return self.core.lookup_fact(fact_key)

    def debug_snapshot(self) -> MemoryKernelDebugSnapshot:
        return MemoryKernelDebugSnapshot(
            base_dir=str(getattr(self.core, "base_dir", "")),
            has_semantic_parser=self.semantic_parser is not None,
            fast_policy_has_parser=getattr(self.fast_policy, "semantic_parser", None) is not None,
            digest_policy_has_parser=getattr(self.digest_policy, "semantic_parser", None) is not None,
            timestamp=time.time(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _annotate_request(
        self,
        request: Any,
        *,
        mode: MemoryIngestMode,
        source: str,
        context: Mapping[str, Any] | None,
        evidence_ids: list[str],
    ) -> Any:
        """Gắn metadata kernel vào StateCommitRequest/dict.

        request hiện có thể là dict từ memory_models.to_state_commit_request().
        Dùng dict để tránh phụ thuộc StateCommitRequest cụ thể.
        """

        if isinstance(request, dict):
            metadata = dict(request.get("metadata") or {})
            metadata.setdefault("memory_kernel_mode", mode)
            metadata.setdefault("memory_kernel_source", source)
            metadata.setdefault("memory_kernel_context", dict(context or {}))
            metadata.setdefault("source", metadata.get("source") or "MemoryKernel")
            request["metadata"] = metadata
            if evidence_ids and not request.get("evidence_ids"):
                request["evidence_ids"] = list(evidence_ids)
            return request

        metadata = dict(getattr(request, "metadata", {}) or {})
        metadata.setdefault("memory_kernel_mode", mode)
        metadata.setdefault("memory_kernel_source", source)
        metadata.setdefault("memory_kernel_context", dict(context or {}))
        try:
            setattr(request, "metadata", metadata)
        except Exception:
            pass
        try:
            current_evidence = list(getattr(request, "evidence_ids", []) or [])
            if evidence_ids and not current_evidence:
                setattr(request, "evidence_ids", list(evidence_ids))
        except Exception:
            pass
        return request

    def _compile_debug(self, compile_result: Any) -> dict[str, Any]:
        debug = getattr(compile_result, "debug", None)
        best = getattr(compile_result, "best", None)
        return {
            "has_query": bool(getattr(compile_result, "has_query", False)),
            "best_intent": str(getattr(best, "intent", "") or ""),
            "best_confidence": float(getattr(best, "confidence", 0.0) or 0.0) if best is not None else 0.0,
            "best_ambiguity": float(getattr(best, "ambiguity", 1.0) or 1.0) if best is not None else 1.0,
            "slot_hypotheses": int(getattr(debug, "slot_hypotheses", 0) or 0) if debug is not None else 0,
            "semantic_confidence": float(getattr(debug, "semantic_confidence", 0.0) or 0.0) if debug is not None else 0.0,
            "semantic_ambiguity": float(getattr(debug, "semantic_ambiguity", 1.0) or 1.0) if debug is not None else 1.0,
            "llm_called": bool(getattr(debug, "llm_called", False)) if debug is not None else False,
            "notes": list(getattr(debug, "notes", ()) or ()) if debug is not None else [],
        }


# Tên alias để migrate từ MemoryCognitionCore không bị gãy import ngay.
MemoryCoreKernel = MemoryKernel


__all__ = ["MemoryKernel", "MemoryCoreKernel", "MemoryKernelDebugSnapshot"]
