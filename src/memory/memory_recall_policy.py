from __future__ import annotations

"""
memory_recall_policy.py

Surface policy cho recall answer.

Bản mới KHÔNG parse user text.
Bản mới KHÔNG execute ledger.
Bản mới chỉ quyết định:
- có đủ confidence để trả không
- exact quote hay gist
- nguồn nào được nói
- nếu thiếu thì nhận không chắc ra sao

Đây là điểm khác với policy cũ bị trộn parse + resolve + execute.
"""

from dataclasses import dataclass
import re

from .memory_query_ir import (
    MemorySourceKind,
    RawRecallResult,
    RecallAnswer,
    SurfaceMode,
)


@dataclass(slots=True)
class RecallPolicyConfig:
    exact_min_confidence: float = 0.62
    gist_min_confidence: float = 0.42
    count_min_confidence: float = 0.50
    allow_session_exact_quote: bool = True
    allow_semantic_fact_surface: bool = True
    max_exact_chars: int = 1200


class MemoryRecallSurfacePolicy:
    """Policy surface kết quả recall thành câu public."""

    def __init__(self, config: RecallPolicyConfig | None = None) -> None:
        self.config = config or RecallPolicyConfig()

    def surface(self, result: RawRecallResult) -> RecallAnswer:
        ir = result.ir

        if not result.found:
            return RecallAnswer.uncertain(
                self._missing_text(result),
                ir=ir,
                debug_trace="recall_missing:" + ",".join(result.warnings),
            )

        if result.source == MemorySourceKind.SEMANTIC_MEMORY and not self.config.allow_semantic_fact_surface:
            return RecallAnswer.uncertain(
                "Tôi có dấu hiệu ký ức semantic, nhưng không nên surface trực tiếp lúc này.",
                ir=ir,
                debug_trace="semantic_surface_not_allowed",
            )

        if ir.surface == SurfaceMode.COUNT or result.count is not None:
            if result.confidence < self.config.count_min_confidence:
                return RecallAnswer.uncertain(
                    "Tôi chưa đủ chắc để đếm phần đó.",
                    ir=ir,
                    debug_trace="count_confidence_low",
                )
            return RecallAnswer(
                text=self._count_text(result),
                confidence=result.confidence,
                source=result.source,
                surface=SurfaceMode.COUNT,
                ir=ir,
                debug_trace=self._trace(result),
            )

        if ir.surface == SurfaceMode.EXACT and result.exact_text:
            if result.confidence < self.config.exact_min_confidence:
                # Hạ xuống gist nếu có gist và đủ điều kiện.
                if result.gist and result.confidence >= self.config.gist_min_confidence:
                    gist_text = self._safe_public_text(result.gist)
                    if gist_text is None:
                        return RecallAnswer.uncertain(
                            "Tôi có dấu vết, nhưng phần lấy ra đang ở dạng nội bộ nên không nên surface thủ công.",
                            ir=ir,
                            debug_trace="raw_object_surface_blocked",
                        )
                    return RecallAnswer(
                        text=gist_text,
                        confidence=result.confidence,
                        source=result.source,
                        surface=SurfaceMode.GIST,
                        ir=ir,
                        debug_trace=self._trace(result) + "|downgraded_to_gist",
                    )
                return RecallAnswer.uncertain(
                    "Tôi có dấu vết ký ức đó, nhưng không đủ chắc để quote nguyên văn.",
                    ir=ir,
                    debug_trace="exact_confidence_low",
                )

            text = self._safe_public_text(result.exact_text)
            if text is None:
                return RecallAnswer.uncertain(
                    "Tôi có dấu vết, nhưng phần lấy ra đang ở dạng nội bộ nên không nên surface thủ công.",
                    ir=ir,
                    debug_trace="raw_object_surface_blocked",
                )
            text = text.strip()
            if len(text) > self.config.max_exact_chars:
                text = text[: self.config.max_exact_chars - 3].rstrip() + "..."

            return RecallAnswer(
                text=self._exact_text(result, text),
                confidence=result.confidence,
                source=result.source,
                surface=SurfaceMode.EXACT,
                ir=ir,
                debug_trace=self._trace(result),
                metadata={"evidence": result.evidence, "warnings": result.warnings},
            )

        if result.gist:
            if result.confidence < self.config.gist_min_confidence:
                return RecallAnswer.uncertain(
                    "Tôi chỉ có gist rất yếu, nói ra sẽ dễ lệch.",
                    ir=ir,
                    debug_trace="gist_confidence_low",
                )
            gist_text = self._safe_public_text(result.gist)
            if gist_text is None:
                return RecallAnswer.uncertain(
                    "Tôi có dấu vết, nhưng phần lấy ra đang ở dạng nội bộ nên không nên surface thủ công.",
                    ir=ir,
                    debug_trace="raw_object_surface_blocked",
                )
            return RecallAnswer(
                text=gist_text,
                confidence=result.confidence,
                source=result.source,
                surface=SurfaceMode.GIST,
                ir=ir,
                debug_trace=self._trace(result),
            )

        return RecallAnswer.uncertain(
            "Tôi tìm được dấu vết, nhưng không có nội dung đủ sạch để nói lại.",
            ir=ir,
            debug_trace="recall_result_unrenderable",
        )

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def _exact_text(self, result: RawRecallResult, text: str) -> str:
        ir = result.ir

        if result.source == MemorySourceKind.SEMANTIC_MEMORY:
            return text

        if result.source == MemorySourceKind.SESSION_TURN_GRAPH:
            if ir.target.quantity:
                return f"Nếu tính trong phiên hiện tại, {ir.target.quantity} mục gần nhất là:\n{text}"

            # Nếu là answer_to, nói rõ đây là câu trả lời, không nhầm thành câu hỏi.
            if ir.relation.relation.value == "answer_to":
                ordinal = ir.relation.anchor.ordinal if ir.relation.anchor else None
                if ordinal:
                    return f"Nếu tính trong phiên hiện tại, câu trả lời của tôi cho câu hỏi thứ {ordinal} là: “{text}”."
                return f"Nếu tính trong phiên hiện tại, câu trả lời đó là: “{text}”."

            if ir.target.act.value == "question" and ir.target.ordinal:
                return f"Nếu tính trong phiên hiện tại, câu hỏi thứ {ir.target.ordinal} bạn hỏi là: “{text}”."

            if ir.target.role.value == "assistant" and ir.target.ordinal:
                return f"Nếu tính trong phiên hiện tại, câu thứ {ir.target.ordinal} tôi nói là: “{text}”."

            return f"Nếu tính trong phiên hiện tại: “{text}”."

        return text

    def _count_text(self, result: RawRecallResult) -> str:
        count = int(result.count or 0)
        ir = result.ir
        if ir.target.act.value == "question":
            return f"Nếu tính trong phiên hiện tại, bạn đã hỏi {count} câu."
        return f"Nếu tính trong phiên hiện tại, tôi đếm được {count} mục."

    def _missing_text(self, result: RawRecallResult) -> str:
        warnings = set(result.warnings)
        if any(w.startswith("fact_not_found:user.birth_month") for w in warnings):
            return "Tôi chưa có ký ức semantic đủ chắc về tháng sinh của bạn."
        if any(w.startswith("fact_not_found:user.name") for w in warnings):
            return "Tôi chưa có ký ức semantic đủ chắc về tên của bạn."
        if "anchor_not_found" in warnings:
            return "Tôi không tìm thấy câu mốc trong phiên hiện tại."
        if "answer_node_not_found" in warnings:
            return "Tôi tìm thấy câu hỏi mốc, nhưng không tìm thấy câu trả lời tương ứng đủ sạch."
        if "target_node_not_found" in warnings:
            return "Tôi không tìm thấy lượt đó trong phiên hiện tại."
        if any(w.startswith("fact_not_found:") for w in warnings):
            return "Tôi có thể có dấu vết liên quan, nhưng chưa có ký ức đủ chắc để coi nó là fact ổn định."
        return "Tôi chưa đủ chắc để lần lại ký ức đó."

    def _trace(self, result: RawRecallResult) -> str:
        ir = result.ir
        return (
            f"memory_query|intent={ir.intent.value}|source={result.source.value}|"
            f"surface={ir.surface.value}|conf={result.confidence:.2f}|"
            f"ir={ir.signature()}"
        )

    def _safe_public_text(self, text: str | None) -> str | None:
        clean = str(text or "").strip()
        if not clean:
            return None
        if self._looks_like_raw_object_surface(clean):
            return None
        return clean

    def _looks_like_raw_object_surface(self, text: str) -> bool:
        one_line = " ".join(text.split())
        if any(
            marker in one_line
            for marker in (
                "MemoryPacket(",
                "RawRecallResult(",
                "RecallAnswer(",
                "QueryHypothesis(",
                "MemoryQueryIR(",
            )
        ):
            return True
        if re.match(r"^<[^>]+object at 0x[0-9a-f]+>$", one_line, flags=re.IGNORECASE):
            return True
        if re.match(r"^[A-Za-z_][A-Za-z0-9_.]*\(.+=.+\)$", one_line):
            return True
        if re.match(r"^(SimpleNamespace|Namespace|dataclass)\(.+\)$", one_line):
            return True
        if one_line.startswith("{") and one_line.endswith("}") and (":" in one_line or "=" in one_line):
            return True
        if one_line.startswith("[") and one_line.endswith("]") and (":" in one_line or "=" in one_line):
            return True
        return False
