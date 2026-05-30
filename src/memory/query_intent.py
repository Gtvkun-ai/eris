from __future__ import annotations

"""
query_intent.py
===============

Compatibility layer cho semantic query intent.

Hướng mới:
    query text/model JSON -> QueryMeaning -> SemanticQueryIntent -> entailment

Nếu Ngài nối model.gguf, cho model trả `answer_target` hoặc `target_predicates`.
Fallback ở đây chỉ dùng khi chưa có structured parse, và nó cố tình dè dặt:
không chắc thì trả unknown, không lôi memory overlap ra bói toán. Một phép màu nhỏ
mang tên "đừng bịa".
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

try:
    from .understanding.entity_linker import normalize
except Exception:  # pragma: no cover
    from understanding.entity_linker import normalize  # type: ignore


@dataclass(frozen=True, slots=True)
class SemanticQueryIntent:
    raw_text: str
    subject: str = "user"
    answer_target: str = "unknown"
    target_predicates: tuple[str, ...] = ()
    expected_object_type: str = "unknown"
    modality: str = "fact"
    temporal: str = "unknown"
    strict_entailment: bool = True
    requires_freshness: bool = False
    confidence: float = 0.0
    evidence: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_known(self) -> bool:
        return bool(self.answer_target and self.answer_target != "unknown" and self.target_predicates)


@dataclass(frozen=True, slots=True)
class QueryTargetFrame:
    """Một target câu hỏi ở mức ontology.

    `fallback_cues` chỉ dùng khi không có model parse. Chúng không phải luật answer.
    ClaimEntailmentEngine mới quyết định claim nào được trả lời query nào.
    """

    answer_target: str
    target_predicates: tuple[str, ...]
    expected_object_type: str
    modality: str = "fact"
    temporal: str = "unknown"
    requires_freshness: bool = False
    strict_entailment: bool = True
    fallback_cues: tuple[str, ...] = ()
    fallback_anti_cues: tuple[str, ...] = ()
    base_confidence: float = 0.70


QUERY_TARGETS: dict[str, QueryTargetFrame] = {
    "user_name": QueryTargetFrame("user_name", ("name_is",), "person_name", temporal="stable", fallback_cues=("ten", "name", "goi toi"), base_confidence=0.82),
    "user_birth_month": QueryTargetFrame("user_birth_month", ("birth_month_is",), "month", temporal="stable", fallback_cues=("sinh thang", "thang sinh", "birthday month"), base_confidence=0.82),
    "user_birth_year": QueryTargetFrame("user_birth_year", ("birth_year_is",), "year", temporal="stable", fallback_cues=("sinh nam", "nam sinh", "birth year"), base_confidence=0.80),
    "user_hometown": QueryTargetFrame("user_hometown", ("hometown_is",), "location", temporal="stable", fallback_cues=("que", "hometown"), fallback_anti_cues=("dang", "hien tai", "song", "thich"), base_confidence=0.84),
    "user_current_location": QueryTargetFrame("user_current_location", ("current_location_is",), "location", temporal="current", requires_freshness=True, fallback_cues=("dang o dau", "hien tai", "bay gio", "current location"), fallback_anti_cues=("que", "thich"), base_confidence=0.82),
    "user_living_location": QueryTargetFrame("user_living_location", ("living_location_is",), "location", temporal="current", fallback_cues=("song o dau", "noi o", "living location", "residence"), fallback_anti_cues=("que", "thich"), base_confidence=0.80),
    "user_location_preference": QueryTargetFrame("user_location_preference", ("preference_location",), "location", modality="preference", temporal="stable", fallback_cues=("thich noi", "thich o dau", "dia diem", "location preference"), fallback_anti_cues=("que", "dang", "song"), base_confidence=0.78),
    "mentioned_location": QueryTargetFrame("mentioned_location", ("mentioned_location",), "location", modality="observation", temporal="session", strict_entailment=False, fallback_cues=("nhac dia diem", "mentioned location"), base_confidence=0.68),
    "user_response_style": QueryTargetFrame("user_response_style", ("response_style_prefers",), "style_rule", modality="preference", temporal="stable", fallback_cues=("cach tra loi", "kieu tra loi", "response style", "tone"), base_confidence=0.78),
    "user_general_preference": QueryTargetFrame("user_general_preference", ("general_preference",), "unknown", modality="preference", temporal="stable", fallback_cues=("thich gi", "so thich", "preference"), fallback_anti_cues=("dia diem", "o dau", "que"), base_confidence=0.66),
}


class QueryIntentParserProtocol:
    def parse(self, text: str) -> Mapping[str, Any] | None:  # pragma: no cover - protocol mềm
        raise NotImplementedError


@dataclass(slots=True)
class SemanticQueryIntentCompiler:
    """Compiler query có hook cho model parser.

    `structured_parser` có thể là adapter model.gguf của Ngài. Nó nên trả:
      {"answer_target":"user_hometown", "confidence":0.9}
    hoặc:
      {"target_predicates":["hometown_is"], "expected_object_type":"location"}
    """

    structured_parser: Callable[[str], Mapping[str, Any] | None] | None = None
    threshold: float = 0.64

    def compile(self, text: str, *, structured: Mapping[str, Any] | None = None) -> SemanticQueryIntent:
        raw = str(text or "").strip()
        if not raw:
            return SemanticQueryIntent(raw_text=raw, confidence=0.0, evidence=("empty_query",))

        payload = structured
        if payload is None and self.structured_parser is not None:
            try:
                payload = self.structured_parser(raw)
            except Exception:
                payload = None
        if payload:
            intent = self._from_structured(raw, payload)
            if intent.is_known and intent.confidence >= self.threshold:
                return intent

        return self._fallback_compile(raw)

    def _from_structured(self, raw: str, data: Mapping[str, Any]) -> SemanticQueryIntent:
        target_name = str(data.get("answer_target") or data.get("target") or "").strip()
        frame = QUERY_TARGETS.get(target_name)
        predicates_raw = data.get("target_predicates") or data.get("predicates")
        predicates = tuple(str(x) for x in predicates_raw if str(x).strip()) if isinstance(predicates_raw, (list, tuple)) else ()
        if frame is None and predicates:
            # Tìm frame đầu tiên có predicate tương ứng.
            frame = next((f for f in QUERY_TARGETS.values() if any(p in f.target_predicates for p in predicates)), None)
        if frame is None:
            return SemanticQueryIntent(raw_text=raw, confidence=0.0, evidence=("structured_query_unknown_target",))
        confidence = _clamp01(data.get("confidence", data.get("certainty", frame.base_confidence)))
        return SemanticQueryIntent(
            raw_text=raw,
            subject=str(data.get("subject") or "user"),
            answer_target=frame.answer_target,
            target_predicates=predicates or frame.target_predicates,
            expected_object_type=str(data.get("expected_object_type") or frame.expected_object_type),
            modality=str(data.get("modality") or frame.modality),
            temporal=str(data.get("temporal") or frame.temporal),
            strict_entailment=bool(data.get("strict_entailment", frame.strict_entailment)),
            requires_freshness=bool(data.get("requires_freshness", frame.requires_freshness)),
            confidence=confidence,
            evidence=("structured_query_parser",),
        )

    def _fallback_compile(self, raw: str) -> SemanticQueryIntent:
        norm = normalize(raw)
        best: tuple[float, QueryTargetFrame, tuple[str, ...]] | None = None
        for frame in QUERY_TARGETS.values():
            score, evidence = self._score(norm, frame)
            if best is None or score > best[0]:
                best = (score, frame, evidence)
        if best is None or best[0] < self.threshold:
            return SemanticQueryIntent(raw_text=raw, confidence=0.0, evidence=("query:unknown",))
        score, frame, evidence = best
        return SemanticQueryIntent(
            raw_text=raw,
            answer_target=frame.answer_target,
            target_predicates=frame.target_predicates,
            expected_object_type=frame.expected_object_type,
            modality=frame.modality,
            temporal=frame.temporal,
            strict_entailment=frame.strict_entailment,
            requires_freshness=frame.requires_freshness,
            confidence=min(0.94, score),
            evidence=evidence,
        )

    def _score(self, norm: str, frame: QueryTargetFrame) -> tuple[float, tuple[str, ...]]:
        evidence: list[str] = []
        score = 0.0
        hay = f" {norm} "
        for cue in frame.fallback_cues:
            c = normalize(cue)
            if not c:
                continue
            if f" {c} " in hay or c in norm:
                score = max(score, frame.base_confidence)
                evidence.append(f"fallback_query:{frame.answer_target}:{c}")
        for anti in frame.fallback_anti_cues:
            a = normalize(anti)
            if a and (f" {a} " in hay or a in norm):
                score -= 0.30
                evidence.append(f"fallback_query:{frame.answer_target}:anti:{a}")
        return max(0.0, score), tuple(evidence)


def compile_semantic_query(text: str) -> SemanticQueryIntent:
    return SemanticQueryIntentCompiler().compile(text)


def normalize_vi(text: str) -> str:
    """Alias cũ cho code đang import normalize_vi từ query_intent."""

    return normalize(text)


def _clamp01(value: Any) -> float:
    try:
        number = float(value)
    except Exception:
        number = 0.0
    if number != number or number in (float("inf"), float("-inf")):
        number = 0.0
    return max(0.0, min(1.0, number))


__all__ = ["SemanticQueryIntent", "SemanticQueryIntentCompiler", "QueryTargetFrame", "compile_semantic_query", "normalize_vi"]
