# -*- coding: utf-8 -*-
"""Knowledge Acquisition bridge cho ERIS Cognitive Pipeline V3.

Tầng này biến ``InquiryPlan`` thành một kết quả có nguồn, thay vì để
``search_memory`` chỉ là nhãn đẹp nằm trong debug trace.

Thiết kế cố ý hỗ trợ hai nhịp:
- planning: thu memory/pattern ngay; không tạo direct web system action;
- execution/finalize: nhận kết quả tool thật và đóng lại acquisition result.

Direct web search đã bị loại khỏi hot path. Nghiên cứu ngoài chỉ đi qua Tutor
policy riêng; V3 không được phát ``system_action`` mạng và không được thay câu chat
bằng lỗi credential. Các hàm resolve cũ bên dưới chỉ còn phục vụ đọc trace/cache cũ.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
import re
import time
from typing import Any, Iterable, Optional


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    if is_dataclass(value):
        return _plain(asdict(value))
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return _plain(to_dict())
        except Exception:
            pass
    return repr(value)


def _compact(text: Any, limit: int = 900) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def _evidence_ids(frame: Any) -> tuple[str, ...]:
    ids: list[str] = []
    workspace = _get(frame, "workspace", None)
    selected = _get(workspace, "selected_evidence", []) or []
    for item in selected:
        value = _get(item, "id", _get(item, "evidence_id", ""))
        if value:
            ids.append(str(value))
    if not ids:
        for item in (_get(frame, "evidence", []) or []):
            value = _get(item, "id", _get(item, "evidence_id", ""))
            if value:
                ids.append(str(value))
    return tuple(dict.fromkeys(ids))[:16]


@dataclass(slots=True)
class KnowledgeSource:
    source_type: str
    source_id: str
    title: str = ""
    content: str = ""
    confidence: float = 0.0
    reliability: float = 0.0
    evidence_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _plain(asdict(self))


@dataclass(slots=True)
class KnowledgeAcquisitionResult:
    action: str = "none"
    query: str = ""
    attempted: bool = False
    succeeded: bool = False
    deferred: bool = False
    system_action: str = ""
    sources: list[KnowledgeSource] = field(default_factory=list)
    distilled_facts: list[str] = field(default_factory=list)
    candidate_beliefs: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    error: str = ""
    latency_ms: float = 0.0
    execution_phase: str = "planning"

    @property
    def confidence(self) -> float:
        if not self.sources:
            return 0.35 if self.deferred else 0.0
        return max(0.0, min(1.0, sum(s.confidence * max(0.2, s.reliability) for s in self.sources) / len(self.sources)))

    def to_dict(self) -> dict[str, Any]:
        payload = _plain(asdict(self))
        payload["confidence"] = round(self.confidence, 4)
        return payload


class KnowledgeAcquisitionEngine:
    """Thực thi/hoãn inquiry bằng các adapter production hiện có."""

    def __init__(self, *, eager_external_io: Optional[bool] = None) -> None:
        # Giữ tham số để extension cũ không vỡ constructor. External I/O không còn
        # thuộc engine này; Tutor là lane nghiên cứu duy nhất.
        del eager_external_io
        self.eager_external_io = False

    def acquire(
        self,
        frame: Any,
        inquiry: Any,
        *,
        runtime_owner: Any = None,
        legacy_frame: Any = None,
        permission: Any = None,
    ) -> KnowledgeAcquisitionResult:
        started = time.perf_counter()
        action = str(_get(inquiry, "action", "infer_quietly") or "infer_quietly")
        query = self._query_from_frame(frame)
        try:
            if action == "search_memory":
                result = self._search_memory(frame, runtime_owner=runtime_owner, legacy_frame=legacy_frame, query=query)
            elif action == "compare_patterns":
                result = self._compare_patterns(frame, legacy_frame=legacy_frame, query=query)
            elif action == "search_web":
                # Tương thích với frame/cache cũ: nuốt nhãn đã nghỉ hưu, tuyệt đối
                # không tạo deferred system action rồi chen lỗi tool vào chat.
                result = KnowledgeAcquisitionResult(
                    action="infer_quietly",
                    query=query,
                    attempted=False,
                    succeeded=False,
                    deferred=False,
                    system_action="",
                    error="direct_web_search_removed",
                )
            else:
                result = KnowledgeAcquisitionResult(action=action, query=query)
        except Exception as exc:
            result = KnowledgeAcquisitionResult(action=action, query=query, attempted=True, error=repr(exc))
        result.latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
        return result

    def resolve_from_execution(
        self,
        existing: KnowledgeAcquisitionResult | dict[str, Any] | None,
        *,
        frame: Any,
        final_decision: Any = None,
        execution_result: Any = None,
    ) -> KnowledgeAcquisitionResult:
        """Giữ API finalize nhưng không hấp thụ direct web tool nữa.

        Frame/cache cũ có thể còn mang action ``search_web``. Ta scrub nó về
        ``infer_quietly`` để không tạo belief từ lỗi credential hoặc text UI.
        """
        del frame, final_decision, execution_result
        result = self._coerce(existing)
        if result.action == "search_web" or result.system_action == "search_web":
            return KnowledgeAcquisitionResult(
                action="infer_quietly",
                query=result.query,
                attempted=False,
                succeeded=False,
                deferred=False,
                system_action="",
                error="direct_web_search_removed",
                execution_phase="finalize",
            )
        return result

    def _search_memory(self, frame: Any, *, runtime_owner: Any, legacy_frame: Any, query: str) -> KnowledgeAcquisitionResult:
        sources: list[KnowledgeSource] = []
        evidence = _evidence_ids(frame)

        # 1) Memory resonance đã qua production retrieval.
        resonance = _get(legacy_frame, "memory_resonance", None)
        activations = list(_get(resonance, "activations", []) or [])
        for idx, item in enumerate(activations[:8]):
            text = _compact(_get(item, "text", _get(item, "summary", "")), 900)
            if not text:
                continue
            sid = str(_get(item, "record_id", "") or f"memory_activation:{idx}")
            sources.append(KnowledgeSource(
                source_type="memory_activation",
                source_id=sid,
                title=str(_get(item, "layer", "memory") or "memory"),
                content=text,
                confidence=float(_get(item, "relevance", _get(item, "score", 0.62)) or 0.62),
                reliability=0.68,
                evidence_ids=tuple(_get(item, "evidence_ids", ()) or evidence),
                metadata={"reason": str(_get(item, "reason", "") or "")},
            ))

        # 2) Workspace-selected memory. Đây là đường sạch nhất nếu resonance không có.
        workspace = _get(frame, "workspace", None)
        for idx, item in enumerate((_get(workspace, "selected_memory", []) or [])[:8]):
            text = _compact(item, 900)
            if not text:
                continue
            sources.append(KnowledgeSource(
                source_type="workspace_memory",
                source_id=f"workspace_memory:{idx}",
                content=text,
                confidence=0.58,
                reliability=0.58,
                evidence_ids=evidence,
            ))

        facts = list(dict.fromkeys(s.content for s in sources if s.content))[:8]
        candidates = [
            {
                "claim": fact,
                "confidence": max(0.45, min(0.72, sources[i].confidence if i < len(sources) else 0.55)),
                "source_ids": [sources[i].source_id] if i < len(sources) else list(evidence),
                "status": "tentative",
                "domain": "user",
            }
            for i, fact in enumerate(facts)
        ]
        return KnowledgeAcquisitionResult(
            action="search_memory",
            query=query,
            attempted=True,
            succeeded=bool(sources),
            sources=sources,
            distilled_facts=facts,
            candidate_beliefs=candidates,
            error="" if sources else "no_relevant_memory",
        )

    def _compare_patterns(self, frame: Any, *, legacy_frame: Any, query: str) -> KnowledgeAcquisitionResult:
        evidence = list(_get(frame, "evidence", []) or [])
        claims = [_compact(_get(ev, "claim", _get(ev, "content", "")), 500) for ev in evidence]
        claims = [x for x in claims if x]
        conflicts: list[str] = []
        lower = [x.lower() for x in claims]
        for i, left in enumerate(lower):
            for j in range(i + 1, len(lower)):
                right = lower[j]
                if left == right:
                    continue
                if ("không " in left and left.replace("không ", "") in right) or ("không " in right and right.replace("không ", "") in left):
                    conflicts.append(f"{claims[i]} <> {claims[j]}")
        sources = [KnowledgeSource(
            source_type="pattern_comparison",
            source_id=f"pattern:{idx}",
            content=claim,
            confidence=0.60,
            reliability=0.62,
            evidence_ids=_evidence_ids(frame),
        ) for idx, claim in enumerate(claims[:8])]
        return KnowledgeAcquisitionResult(
            action="compare_patterns",
            query=query,
            attempted=True,
            succeeded=bool(claims),
            sources=sources,
            distilled_facts=claims[:8],
            conflicts=conflicts[:8],
        )

    @staticmethod
    def _query_from_frame(frame: Any) -> str:
        return _compact(_get(frame, "user_text", ""), 500)

    @staticmethod
    def _coerce(value: KnowledgeAcquisitionResult | dict[str, Any] | None) -> KnowledgeAcquisitionResult:
        if isinstance(value, KnowledgeAcquisitionResult):
            return value
        if not isinstance(value, dict):
            return KnowledgeAcquisitionResult()
        sources: list[KnowledgeSource] = []
        for item in value.get("sources", []) or []:
            if isinstance(item, KnowledgeSource):
                sources.append(item)
            elif isinstance(item, dict):
                try:
                    sources.append(KnowledgeSource(**item))
                except Exception:
                    continue
        return KnowledgeAcquisitionResult(
            action=str(value.get("action", "none") or "none"),
            query=str(value.get("query", "") or ""),
            attempted=bool(value.get("attempted", False)),
            succeeded=bool(value.get("succeeded", False)),
            deferred=bool(value.get("deferred", False)),
            system_action=str(value.get("system_action", "") or ""),
            sources=sources,
            distilled_facts=[str(x) for x in (value.get("distilled_facts", []) or [])],
            candidate_beliefs=list(value.get("candidate_beliefs", []) or []),
            conflicts=[str(x) for x in (value.get("conflicts", []) or [])],
            error=str(value.get("error", "") or ""),
            latency_ms=float(value.get("latency_ms", 0.0) or 0.0),
            execution_phase=str(value.get("execution_phase", "planning") or "planning"),
        )


__all__ = ["KnowledgeSource", "KnowledgeAcquisitionResult", "KnowledgeAcquisitionEngine"]
