from __future__ import annotations

"""
semantic_hypothesis.py
======================

Sinh hypothesis ngữ nghĩa từ embedding + prototype bank.

Vai trò
-------
File này là tầng giữa:
    text hiện tại -> encode -> so với prototype -> top-k hypothesis

Nó không biết Ni, GoalPersistence hay SpeechCore. Nó chỉ nói:
    "context này gần nhãn nào, gần bao nhiêu, có mơ hồ không?"

Quy tắc sống còn
----------------
- top1 cao nhưng top2 cũng cao => vẫn mơ hồ.
- fallback hashing => confidence phải bị cap.
- prototype ít câu mẫu => confidence thấp hơn.
- semantic hypothesis không được veto lexical negation/hard anchor.

Không tuân thủ mấy điều trên thì chỉ là keyword heuristic cosplay vector.
Một truyền thống công nghệ đáng buồn nhưng phổ biến.
"""

from dataclasses import dataclass, field
from typing import Mapping, Sequence

try:  # Cho phép chạy trong package thật.
    from .semantic_encoder import BaseSemanticEncoder, SemanticVector, cosine_similarity, mean_vectors, clamp01
    from .semantic_prototypes import PrototypeBank, PrototypeSet, DEFAULT_PROTOTYPE_BANK
except ImportError:  # Cho phép copy file ra chạy lẻ khi test nhanh.
    from semantic_encoder import BaseSemanticEncoder, SemanticVector, cosine_similarity, mean_vectors, clamp01  # type: ignore
    from semantic_prototypes import PrototypeBank, PrototypeSet, DEFAULT_PROTOTYPE_BANK  # type: ignore


@dataclass(frozen=True, slots=True)
class PrototypeCentroid:
    """Vector centroid đã encode của một PrototypeSet."""

    domain: str
    label: str
    vector: tuple[float, ...]
    model_id: str
    phrase_count: int
    prototype_prior: float
    tags: tuple[str, ...] = ()
    is_fallback: bool = False

    @property
    def usable(self) -> bool:
        return bool(self.vector) and self.phrase_count > 0


@dataclass(frozen=True, slots=True)
class SemanticHypothesis:
    """Một giả thuyết semantic.

    score:
        Điểm cuối sau khi tính cosine, prior, anchor boost và cap fallback.
    raw_similarity:
        Cosine gốc giữa text vector và centroid.
    confidence:
        Độ tin cho riêng hypothesis này.
    evidence:
        Debug evidence để hiểu vì sao score lên/xuống.
    """

    domain: str
    label: str
    score: float
    confidence: float
    raw_similarity: float
    margin_from_next: float = 0.0
    prototype_prior: float = 0.5
    anchor_boost: float = 0.0
    is_fallback: bool = False
    evidence: tuple[str, ...] = ()
    debug: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SemanticHypothesisReport:
    """Kết quả semantic top-k cho một domain."""

    domain: str
    text: str
    hypotheses: tuple[SemanticHypothesis, ...]
    dominant: SemanticHypothesis | None
    ambiguity: float
    confidence: float
    semantic_available: bool
    encoder_model_id: str = ""
    fallback_used: bool = False
    evidence: tuple[str, ...] = ()

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(h.label for h in self.hypotheses)

    @property
    def uncertain(self) -> bool:
        return self.ambiguity >= 0.45 or self.confidence < 0.45 or self.dominant is None


@dataclass(frozen=True, slots=True)
class HypothesisConfig:
    """Tham số scoring semantic.

    min_signal:
        Điểm tối thiểu để một hypothesis được xem là có tín hiệu.
    min_margin:
        Khoảng cách top1-top2 cần có để giảm ambiguity.
    fallback_confidence_cap:
        Cap confidence khi encoder là hashing/null fallback.
    semantic_confidence_cap:
        Cap confidence khi có embedding thật. Vẫn cap, vì vector không phải
        quyền phán xét vũ trụ.
    prior_weight:
        Mức ảnh hưởng của prior label.
    anchor_boost_weight:
        Mức ảnh hưởng của tag/anchor trùng nhẹ.
    """

    top_k: int = 4
    min_signal: float = 0.48
    min_margin: float = 0.08
    fallback_confidence_cap: float = 0.58
    semantic_confidence_cap: float = 0.86
    prior_weight: float = 0.08
    anchor_boost_weight: float = 0.06
    weak_prototype_penalty: float = 0.05


class SemanticHypothesisEngine:
    """So text hiện tại với prototype bank để sinh hypothesis."""

    def __init__(
        self,
        encoder: BaseSemanticEncoder,
        *,
        prototype_bank: PrototypeBank | None = None,
        config: HypothesisConfig | None = None,
    ) -> None:
        self.encoder = encoder
        self.prototype_bank = prototype_bank or DEFAULT_PROTOTYPE_BANK
        self.config = config or HypothesisConfig()
        self._centroid_cache: dict[tuple[str, str, str], PrototypeCentroid] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def clear_cache(self) -> None:
        self._centroid_cache.clear()

    def compare(
        self,
        domain: str,
        text: str,
        *,
        anchors: Sequence[str] = (),
        labels: Sequence[str] | None = None,
    ) -> SemanticHypothesisReport:
        """Sinh hypothesis top-k cho một domain.

        labels:
            Nếu truyền vào, chỉ xét các label đó. Hữu ích khi caller muốn giới
            hạn action space theo permission.
        """

        raw_text = str(text or "").strip()
        health = self.encoder.health()
        evidence: list[str] = [f"encoder={health.model_id}"]

        if not raw_text:
            return self._empty_report(domain, raw_text, "empty_text", health)

        prototypes = self.prototype_bank.by_domain(domain)
        if labels is not None:
            allowed = {str(label) for label in labels}
            prototypes = tuple(item for item in prototypes if item.label in allowed)
        if not prototypes:
            return self._empty_report(domain, raw_text, "no_prototypes_for_domain", health)

        text_vector = self.encoder.encode(raw_text)
        if not text_vector.usable:
            return self._empty_report(domain, raw_text, "text_vector_unusable", health)

        hypotheses: list[SemanticHypothesis] = []
        for prototype in prototypes:
            centroid = self._centroid_for(prototype)
            if not centroid.usable:
                continue
            hypothesis = self._score_prototype(
                domain=domain,
                prototype=prototype,
                centroid=centroid,
                text_vector=text_vector,
                anchors=anchors,
            )
            hypotheses.append(hypothesis)

        if not hypotheses:
            return self._empty_report(domain, raw_text, "no_usable_centroids", health)

        hypotheses.sort(key=lambda item: item.score, reverse=True)
        top = hypotheses[: max(1, int(self.config.top_k or 4))]

        # Gán margin top1-top2 vào từng hypothesis để downstream đọc dễ hơn.
        if len(top) >= 2:
            margin = max(0.0, top[0].score - top[1].score)
        else:
            margin = top[0].score
        top = [
            SemanticHypothesis(
                domain=h.domain,
                label=h.label,
                score=h.score,
                confidence=h.confidence,
                raw_similarity=h.raw_similarity,
                margin_from_next=margin if i == 0 else max(0.0, h.score - (top[i + 1].score if i + 1 < len(top) else 0.0)),
                prototype_prior=h.prototype_prior,
                anchor_boost=h.anchor_boost,
                is_fallback=h.is_fallback,
                evidence=h.evidence,
                debug=h.debug,
            )
            for i, h in enumerate(top)
        ]

        dominant = top[0]
        ambiguity = self._estimate_ambiguity(dominant, top[1] if len(top) > 1 else None, health_is_fallback=health.is_fallback)
        confidence = self._report_confidence(dominant, ambiguity, health_is_fallback=health.is_fallback)
        evidence.extend(
            (
                f"top={dominant.label}:{dominant.score:.2f}",
                f"ambiguity={ambiguity:.2f}",
                f"confidence={confidence:.2f}",
            )
        )
        if health.is_fallback:
            evidence.append("fallback_embedding_confidence_capped")
        if dominant.score < self.config.min_signal:
            evidence.append("dominant_below_min_signal")

        return SemanticHypothesisReport(
            domain=domain,
            text=raw_text,
            hypotheses=tuple(top),
            dominant=dominant,
            ambiguity=ambiguity,
            confidence=confidence,
            semantic_available=health.available and not health.is_fallback,
            encoder_model_id=health.model_id,
            fallback_used=bool(health.is_fallback),
            evidence=tuple(evidence),
        )

    def compare_many(
        self,
        domains: Sequence[str],
        text: str,
        *,
        anchors: Sequence[str] = (),
    ) -> dict[str, SemanticHypothesisReport]:
        """So cùng một text với nhiều domain."""

        return {domain: self.compare(domain, text, anchors=anchors) for domain in domains}

    # ------------------------------------------------------------------
    # Centroid / scoring nội bộ
    # ------------------------------------------------------------------

    def _centroid_for(self, prototype: PrototypeSet) -> PrototypeCentroid:
        health = self.encoder.health()
        key = (health.model_id, prototype.domain, prototype.label)
        cached = self._centroid_cache.get(key)
        if cached is not None:
            return cached

        phrase_texts = [phrase.text for phrase in prototype.phrases]
        phrase_vectors = self.encoder.encode_many(phrase_texts)

        # Nhân trọng số bằng cách lặp vector theo weight tương đối nhỏ. Tránh
        # dùng numpy để file này sạch dependency.
        weighted_vectors: list[Sequence[float]] = []
        for phrase, vector in zip(prototype.phrases, phrase_vectors):
            if not vector.usable:
                continue
            repeat = max(1, min(5, int(round(float(phrase.weight or 1.0) * 2))))
            weighted_vectors.extend([vector.vector] * repeat)

        centroid_vector = mean_vectors(weighted_vectors)
        centroid = PrototypeCentroid(
            domain=prototype.domain,
            label=prototype.label,
            vector=centroid_vector,
            model_id=health.model_id,
            phrase_count=len(weighted_vectors),
            prototype_prior=prototype.prior,
            tags=prototype.all_tags,
            is_fallback=health.is_fallback,
        )
        self._centroid_cache[key] = centroid
        return centroid

    def _score_prototype(
        self,
        *,
        domain: str,
        prototype: PrototypeSet,
        centroid: PrototypeCentroid,
        text_vector: SemanticVector,
        anchors: Sequence[str],
    ) -> SemanticHypothesis:
        raw = cosine_similarity(text_vector.vector, centroid.vector)

        # Với nhiều embedding hiện đại, cosine thường nằm vùng dương. Dùng raw
        # nếu dương; nếu âm thì nén về 0. Không map (-1..1)->(0..1), vì như vậy
        # unrelated 0.0 thành 0.5, một trò ảo thuật rất có hại.
        semantic_score = clamp01(max(0.0, raw))

        prior = clamp01(prototype.prior)
        prior_component = (prior - 0.5) * self.config.prior_weight

        anchor_boost = self._anchor_boost(anchors, centroid.tags)
        weak_penalty = self.config.weak_prototype_penalty if centroid.phrase_count < 2 else 0.0

        score = semantic_score + prior_component + anchor_boost - weak_penalty
        score = clamp01(score)

        cap = self.config.fallback_confidence_cap if text_vector.is_fallback or centroid.is_fallback else self.config.semantic_confidence_cap
        confidence = min(cap, score * 0.86 + text_vector.confidence * 0.14)
        evidence = [
            f"cos={raw:.3f}",
            f"semantic={semantic_score:.2f}",
            f"prior={prior:.2f}",
        ]
        if anchor_boost > 0.0:
            evidence.append(f"anchor_boost={anchor_boost:.2f}")
        if weak_penalty > 0.0:
            evidence.append("weak_prototype_penalty")
        if text_vector.is_fallback or centroid.is_fallback:
            evidence.append("fallback_vector")

        return SemanticHypothesis(
            domain=domain,
            label=prototype.label,
            score=score,
            confidence=clamp01(confidence),
            raw_similarity=raw,
            prototype_prior=prior,
            anchor_boost=anchor_boost,
            is_fallback=text_vector.is_fallback or centroid.is_fallback,
            evidence=tuple(evidence),
            debug={
                "phrase_count": centroid.phrase_count,
                "prototype_description": prototype.description,
                "negative_labels": prototype.negative_labels,
            },
        )

    def _anchor_boost(self, anchors: Sequence[str], tags: Sequence[str]) -> float:
        if not anchors or not tags:
            return 0.0
        anchor_set = {str(anchor).strip().lower() for anchor in anchors if str(anchor).strip()}
        tag_set = {str(tag).strip().lower() for tag in tags if str(tag).strip()}
        if not anchor_set or not tag_set:
            return 0.0
        overlap = len(anchor_set & tag_set)
        if overlap <= 0:
            return 0.0
        ratio = overlap / max(1, min(len(anchor_set), len(tag_set)))
        return clamp01(min(0.14, self.config.anchor_boost_weight * ratio + 0.025 * overlap))

    def _estimate_ambiguity(self, top: SemanticHypothesis, second: SemanticHypothesis | None, *, health_is_fallback: bool) -> float:
        if top.score < self.config.min_signal:
            base = 0.72
        else:
            base = 0.28

        if second is not None:
            gap = max(0.0, top.score - second.score)
            if gap < self.config.min_margin:
                base += 0.28 * (1.0 - gap / max(0.001, self.config.min_margin))
            if second.score >= self.config.min_signal:
                base += 0.10
        else:
            gap = top.score

        if top.is_fallback or health_is_fallback:
            base += 0.16
        if top.confidence < 0.45:
            base += 0.10
        return clamp01(base)

    def _report_confidence(self, top: SemanticHypothesis, ambiguity: float, *, health_is_fallback: bool) -> float:
        confidence = top.confidence * (1.0 - 0.55 * ambiguity)
        if top.score < self.config.min_signal:
            confidence *= 0.72
        cap = self.config.fallback_confidence_cap if health_is_fallback or top.is_fallback else self.config.semantic_confidence_cap
        return clamp01(min(cap, confidence))

    def _empty_report(self, domain: str, text: str, reason: str, health: object) -> SemanticHypothesisReport:
        model_id = getattr(health, "model_id", "unknown")
        is_fallback = bool(getattr(health, "is_fallback", False))
        available = bool(getattr(health, "available", False)) and not is_fallback
        return SemanticHypothesisReport(
            domain=domain,
            text=str(text or ""),
            hypotheses=(),
            dominant=None,
            ambiguity=1.0,
            confidence=0.0,
            semantic_available=available,
            encoder_model_id=model_id,
            fallback_used=is_fallback,
            evidence=(reason, f"encoder={model_id}"),
        )
