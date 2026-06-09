# -*- coding: utf-8 -*-
"""meaning_hypothesis.py — ``MeaningHypothesisEngine`` (stage 4 của Phase 2).

ContextAnnotation set → MeaningHypothesis set.

**Module WRAP, không reimplement scoring (R5.7).** Engine này *bọc* hai engine đã
có sẵn và **uỷ quyền** (delegate) toàn bộ phần chấm điểm semantic cho chúng:

- ``cortex.semantic_hypothesis.SemanticHypothesisEngine.compare(...)`` — nguồn
  thật của cosine/score/confidence/ambiguity. ``MeaningHypothesisEngine`` KHÔNG
  tự tính cosine, prior, anchor-boost hay bất kỳ điểm semantic nào; nó chỉ
  **adapt** ``SemanticHypothesis`` → ``MeaningHypothesis``.
- ``cortex.meaning.meaning_layer.MeaningLayer.evaluate(...)`` — vật liệu
  meaning-slot (scene/activity meaning, public_seed, semantic_family) dùng để
  **làm giàu** summary và tinh chỉnh ánh xạ category, KHÔNG để chấm điểm.

Cả hai engine được **tiêm vào** (dependency injection) qua constructor nên test
có thể truyền spy/fake để khẳng định việc delegate thực sự xảy ra (task 11.6).

Hợp đồng hành vi (map requirement):

- **R5.1** — sinh 1..``config.max_hypotheses`` (mặc định 4) ``MeaningHypothesis``.
- **R5.2** — mỗi hypothesis có ``evidence_ids`` KHÔNG rỗng và ba chỉ số
  (``confidence``/``ambiguity``/``overread_risk``) đều ∈ [0,1] (clamp ở
  ``__post_init__``; engine đảm bảo ``evidence_ids`` non-empty).
- **R5.3** — hai+ hypothesis có ``|Δconfidence| ≤ config.ambiguity_margin``
  (mặc định 0.08) → **tăng** ``ambiguity`` của chúng, không vượt 1.0.
- **R5.4** — không hypothesis nào được evidence chống đỡ → đúng MỘT hypothesis
  "insufficient evidence" với ``confidence < config.meaning_low_conf`` (0.2) và
  ``is_insufficient_evidence=True``.
- **R5.5 / R5.6** — xếp giảm dần theo ``confidence``; bằng confidence → tie-break
  **tăng dần** theo ``ambiguity``.
- **R5.7** — WRAP, không reimplement scoring (xem trên).

### Ánh xạ semantic label → Taxonomy.MEANING category

Hàm ``_map_category`` là ánh xạ **xác định** (deterministic):

1. Nếu label đã là một id hợp lệ trong ``Taxonomy.MEANING`` → dùng trực tiếp.
2. Nếu không, dò một bảng keyword (substring, đã chuẩn hoá lowercase) trên label
   rồi tới ``semantic_family`` của meaning-slot.
3. Không khớp gì → mặc định an toàn ``"literal_statement"`` (category trung tính
   nhất, không over-read).

Mọi category đều đi qua ``Taxonomy.require("MEANING", ...)`` (R11.2).

### Công thức overread_risk ∈ [0,1]

Tổ hợp tuyến tính có trọng số (tổng trọng số = 1.0 nên kết quả luôn ∈ [0,1] trước
khi ``clamp01``)::

    overread_risk = clamp01(
        0.5 * (1.0 if is_fallback else 0.0)            # encoder fallback → rủi ro cao
      + 0.3 * (1.0 - clamp01(margin_from_next))         # biên top1-top2 nhỏ → mơ hồ → rủi ro
      + 0.2 * (1.0 if evidence_count < min_evidence else 0.0)  # thiếu evidence → rủi ro
    )

Diễn giải: suy diễn dễ "vượt bằng chứng" nhất khi (a) embedding chỉ là fallback
nên điểm không đáng tin, (b) khoảng cách tới giả thuyết kế tiếp nhỏ (mơ hồ), và
(c) ít evidence chống đỡ. ``min_evidence`` lấy từ ``config.min_evidence_count``.

### Quyết định evidence_ids cho fallback "insufficient evidence" (R5.2 vs R5.4)

R5.2 buộc mọi hypothesis sinh ra phải có ``evidence_ids`` non-empty, nhưng
hypothesis "insufficient evidence" (R5.4) theo bản chất KHÔNG có evidence. Giải
quyết: gán một **sentinel** ``evidence_ids=["insufficient_evidence"]`` để bất biến
non-empty vẫn giữ, trong khi cờ ``is_insufficient_evidence=True`` nói rõ bản chất
"không có evidence thật". Đây là lựa chọn có chủ đích, được test 11.4 kiểm.

Module thuần logic + delegate; KHÔNG import encoder thật ở thời điểm load (hai
engine được tiêm vào dạng instance đã dựng sẵn).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

from .ambiguity import AmbiguityModule
from .config import Phase2Config
from .contracts import ContextAnnotation, MeaningHypothesis, StageDebug, clamp01
from .taxonomy import Taxonomy

if TYPE_CHECKING:  # pragma: no cover - chỉ phục vụ type-checker, tránh import encoder
    from ..semantic_hypothesis import (
        SemanticHypothesis,
        SemanticHypothesisEngine,
        SemanticHypothesisReport,
    )
    from .meaning_layer import MeaningLayer


__all__ = ["MeaningHypothesisEngine"]


# Domain mặc định để hỏi SemanticHypothesisEngine. "activity_intent" là domain
# giàu prototype nhất trong bank mặc định; pipeline facade (task 18) có thể wrap
# engine với domain khác mà không đổi adapter này.
_DEFAULT_DOMAIN = "activity_intent"

# Sentinel evidence_id cho hypothesis "insufficient evidence" (R5.4) — giữ bất
# biến non-empty của R5.2 trong khi is_insufficient_evidence flag bản chất.
_INSUFFICIENT_EVIDENCE_SENTINEL = "insufficient_evidence"

# Mức tăng ambiguity tối thiểu khi phát hiện near-tie (R5.3) để đảm bảo ambiguity
# thực sự "tăng" chứ không chỉ giữ nguyên (vẫn bị clamp ≤ 1.0).
_NEAR_TIE_BUMP = 0.15

# Trọng số công thức overread_risk (tổng = 1.0 → kết quả ∈ [0,1]).
_OVERREAD_W_FALLBACK = 0.5
_OVERREAD_W_MARGIN = 0.3
_OVERREAD_W_EVIDENCE = 0.2

# Phân số của meaning_low_conf dùng cho confidence của hypothesis insufficient
# evidence (đảm bảo < meaning_low_conf một cách an toàn).
_INSUFFICIENT_CONF_FRACTION = 0.5

# Bảng keyword (substring) ánh xạ label/semantic_family → Taxonomy.MEANING.
# Thứ tự duyệt cố định (dict giữ thứ tự chèn) nên ánh xạ là xác định.
_LABEL_KEYWORD_MAP: dict[str, str] = {
    "request": "request",
    "ask": "request",
    "question": "question",
    "inquir": "question",
    "complaint": "complaint",
    "complain": "complaint",
    "joke": "joke",
    "humor": "joke",
    "probe": "probe",
    "test": "probe",
    "emotional": "emotional_disclosure",
    "emotion": "emotional_disclosure",
    "disclos": "emotional_disclosure",
    "feel": "emotional_disclosure",
    "sarcas": "sarcasm",
    "irony": "sarcasm",
    "agreement": "agreement",
    "agree": "agreement",
    "disagreement": "disagreement",
    "disagree": "disagreement",
    "small_talk": "small_talk",
    "smalltalk": "small_talk",
    "chit": "small_talk",
    "statement": "literal_statement",
    "literal": "literal_statement",
}

# Category an toàn mặc định khi không khớp ánh xạ nào (trung tính, không over-read).
_DEFAULT_CATEGORY = "literal_statement"


class MeaningHypothesisEngine:
    """Adapter bọc ``SemanticHypothesisEngine`` + ``MeaningLayer`` (stage 4).

    KHÔNG reimplement scoring — uỷ quyền cho engine được tiêm vào (R5.7).
    """

    def __init__(
        self,
        *,
        semantic_engine: "SemanticHypothesisEngine",
        meaning_layer: "MeaningLayer",
        ambiguity_module: AmbiguityModule,
        config: Phase2Config | None = None,
    ) -> None:
        self.semantic_engine = semantic_engine
        self.meaning_layer = meaning_layer
        self.ambiguity_module = ambiguity_module
        self.config = config or Phase2Config()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def generate(
        self, annotations: list[ContextAnnotation], *, frame_id: str
    ) -> tuple[list[MeaningHypothesis], StageDebug]:
        """Sinh tập ``MeaningHypothesis`` từ các ``ContextAnnotation``.

        Xem docstring module cho hợp đồng đầy đủ (R5.1–R5.7).
        """

        notes: list[str] = []

        # --- Gom vật liệu từ annotations (KHÔNG đọc Raw_World) ----------------
        items = list(annotations or [])
        text = self._build_text(items)
        evidence_ids = self._collect_evidence_ids(items)
        anchors = self._collect_anchors(items)

        # --- R5.4: không có gì để chống đỡ → fallback insufficient evidence ---
        if not items or not evidence_ids or not text:
            notes.append("no supporting evidence available; insufficient-evidence fallback")
            hypotheses = [self._insufficient_evidence_hypothesis(frame_id)]
            return hypotheses, self._build_debug(hypotheses, notes)

        # --- DELEGATE: chấm điểm semantic do SemanticHypothesisEngine lo (R5.7)
        report = self.semantic_engine.compare(_DEFAULT_DOMAIN, text, anchors=anchors)

        # --- DELEGATE: làm giàu meaning-slot (không dùng để chấm điểm) --------
        meaning_slot = self._evaluate_meaning_slot(text)

        semantic_hypotheses = list(getattr(report, "hypotheses", ()) or ())
        if not semantic_hypotheses:
            notes.append("semantic report empty; insufficient-evidence fallback")
            hypotheses = [self._insufficient_evidence_hypothesis(frame_id)]
            return hypotheses, self._build_debug(hypotheses, notes)

        report_ambiguity = clamp01(getattr(report, "ambiguity", 0.0))
        family = str(getattr(meaning_slot, "semantic_family", "") or "")
        slot_summary = self._slot_summary(meaning_slot)

        # --- ADAPT SemanticHypothesis → MeaningHypothesis (cap max_hypotheses)
        max_n = max(1, int(self.config.max_hypotheses or 4))
        produced: list[MeaningHypothesis] = []
        for index, sem in enumerate(semantic_hypotheses[:max_n]):
            produced.append(
                self._adapt(
                    sem,
                    index=index,
                    frame_id=frame_id,
                    evidence_ids=evidence_ids,
                    report_ambiguity=report_ambiguity,
                    family=family,
                    slot_summary=slot_summary,
                )
            )

        # --- R5.3: near-tie confidence → tăng ambiguity ----------------------
        produced = self._raise_near_tie_ambiguity(produced)

        # --- R5.5 / R5.6: xếp giảm dần confidence, tie-break tăng dần ambiguity
        produced.sort(key=lambda h: (-h.confidence, h.ambiguity))

        notes.append(
            f"adapted {len(produced)} hypotheses from semantic report "
            f"(domain={_DEFAULT_DOMAIN}, report_ambiguity={report_ambiguity:.3f})"
        )
        return produced, self._build_debug(produced, notes)

    # ------------------------------------------------------------------
    # Adaptation helpers
    # ------------------------------------------------------------------
    def _adapt(
        self,
        sem: "SemanticHypothesis",
        *,
        index: int,
        frame_id: str,
        evidence_ids: list[str],
        report_ambiguity: float,
        family: str,
        slot_summary: str,
    ) -> MeaningHypothesis:
        """Adapt một ``SemanticHypothesis`` thành ``MeaningHypothesis``.

        Giữ nguyên ``confidence`` của semantic hypothesis (không chấm lại điểm);
        ``ambiguity`` lấy từ report; ``overread_risk`` suy theo công thức module.
        """

        label = str(getattr(sem, "label", "") or "")
        category = self._map_category(label, family)
        overread_risk = self._overread_risk(sem, evidence_count=len(evidence_ids))

        summary_bits = [bit for bit in (label, slot_summary) if bit]
        summary = " | ".join(summary_bits) if summary_bits else label or "meaning"

        return MeaningHypothesis(
            hypothesis_id=f"{frame_id}:meaning:{index}",
            category=category,
            summary=summary,
            evidence_ids=list(evidence_ids),
            confidence=clamp01(getattr(sem, "confidence", 0.0)),
            ambiguity=report_ambiguity,
            overread_risk=overread_risk,
            is_insufficient_evidence=False,
            source_semantic_label=label or None,
        )

    def _overread_risk(self, sem: "SemanticHypothesis", *, evidence_count: int) -> float:
        """Suy ``overread_risk`` ∈ [0,1] từ fallback/biên độ/đủ evidence.

        Xem docstring module cho công thức và diễn giải.
        """

        is_fallback = bool(getattr(sem, "is_fallback", False))
        margin = clamp01(getattr(sem, "margin_from_next", 0.0))
        min_evidence = max(1, int(self.config.min_evidence_count or 2))

        risk = (
            _OVERREAD_W_FALLBACK * (1.0 if is_fallback else 0.0)
            + _OVERREAD_W_MARGIN * (1.0 - margin)
            + _OVERREAD_W_EVIDENCE * (1.0 if evidence_count < min_evidence else 0.0)
        )
        return clamp01(risk)

    def _raise_near_tie_ambiguity(
        self, hypotheses: list[MeaningHypothesis]
    ) -> list[MeaningHypothesis]:
        """R5.3 — hai+ hypothesis có ``|Δconfidence| ≤ margin`` → tăng ambiguity.

        Dùng ``AmbiguityModule.compute`` (delegate) để lấy ambiguity mức-tập làm
        sàn, rồi cộng thêm ``_NEAR_TIE_BUMP`` để đảm bảo giá trị thực sự tăng
        (vẫn clamp ≤ 1.0). Hypothesis không near-tie giữ nguyên.
        """

        if len(hypotheses) < 2:
            return hypotheses

        margin = float(self.config.ambiguity_margin)
        set_result = self.ambiguity_module.compute(hypotheses)
        set_ambiguity = clamp01(set_result.value) if set_result.valid else 0.0

        confidences = [h.confidence for h in hypotheses]
        for i, hyp in enumerate(hypotheses):
            near_tie = any(
                j != i and abs(confidences[i] - confidences[j]) <= margin
                for j in range(len(confidences))
            )
            if not near_tie:
                continue
            bumped = max(hyp.ambiguity, set_ambiguity, hyp.ambiguity + _NEAR_TIE_BUMP)
            hyp.ambiguity = clamp01(bumped)
        return hypotheses

    # ------------------------------------------------------------------
    # Category mapping (deterministic)
    # ------------------------------------------------------------------
    @staticmethod
    def _map_category(label: str, family: str) -> str:
        """Ánh xạ xác định label/semantic_family → ``Taxonomy.MEANING`` id.

        Mặc định an toàn ``literal_statement`` khi không khớp gì (R5.2/R11.2).
        """

        normalized = MeaningHypothesisEngine._normalize(label)

        # 1) label đã là một category MEANING hợp lệ.
        if normalized in Taxonomy.MEANING:
            return Taxonomy.require("MEANING", normalized)

        # 2) dò keyword trên label, rồi trên semantic_family.
        for source in (normalized, MeaningHypothesisEngine._normalize(family)):
            if not source:
                continue
            for keyword, category in _LABEL_KEYWORD_MAP.items():
                if keyword in source:
                    return Taxonomy.require("MEANING", category)

        # 3) mặc định an toàn.
        return Taxonomy.require("MEANING", _DEFAULT_CATEGORY)

    # ------------------------------------------------------------------
    # Insufficient-evidence fallback (R5.4)
    # ------------------------------------------------------------------
    def _insufficient_evidence_hypothesis(self, frame_id: str) -> MeaningHypothesis:
        """Sinh đúng MỘT hypothesis "insufficient evidence" (R5.4).

        ``confidence < config.meaning_low_conf``; sentinel evidence_id giữ bất
        biến non-empty của R5.2; cờ ``is_insufficient_evidence=True``.
        ``overread_risk`` đặt tối đa (1.0) vì không có evidence thật chống đỡ.
        """

        confidence = clamp01(self.config.meaning_low_conf * _INSUFFICIENT_CONF_FRACTION)
        return MeaningHypothesis(
            hypothesis_id=f"{frame_id}:meaning:insufficient",
            category=Taxonomy.require("MEANING", _DEFAULT_CATEGORY),
            summary="insufficient evidence to form a supported meaning hypothesis",
            evidence_ids=[_INSUFFICIENT_EVIDENCE_SENTINEL],
            confidence=confidence,
            ambiguity=0.0,
            overread_risk=1.0,
            is_insufficient_evidence=True,
            source_semantic_label=None,
        )

    # ------------------------------------------------------------------
    # Material gathering
    # ------------------------------------------------------------------
    @staticmethod
    def _build_text(items: Sequence[ContextAnnotation]) -> str:
        """Ghép các ``observation.summary`` thành text để feed semantic engine."""

        parts: list[str] = []
        for ann in items:
            summary = str(getattr(ann.observation, "summary", "") or "").strip()
            if summary:
                parts.append(summary)
        return " ".join(parts).strip()

    @staticmethod
    def _collect_evidence_ids(items: Sequence[ContextAnnotation]) -> list[str]:
        """Gom evidence_ids từ mọi annotation, dedupe, giữ thứ tự xuất hiện."""

        seen: set[str] = set()
        ordered: list[str] = []
        for ann in items:
            for eid in getattr(ann.observation, "evidence_ids", ()) or ():
                key = str(eid)
                if key and key not in seen:
                    seen.add(key)
                    ordered.append(key)
        return ordered

    @staticmethod
    def _collect_anchors(items: Sequence[ContextAnnotation]) -> tuple[str, ...]:
        """Gom anchor tag nhẹ từ register/relationship để hỗ trợ semantic match."""

        anchors: list[str] = []
        seen: set[str] = set()
        for ann in items:
            for value in (
                getattr(ann, "register", ""),
                getattr(ann, "relationship", ""),
                getattr(ann, "social_norm", ""),
            ):
                token = str(value or "").strip().lower()
                if token and token not in seen:
                    seen.add(token)
                    anchors.append(token)
        return tuple(anchors)

    def _evaluate_meaning_slot(self, text: str) -> Any:
        """DELEGATE tới ``MeaningLayer.evaluate`` để lấy vật liệu meaning-slot.

        Không dùng để chấm điểm; chỉ làm giàu summary/category. Bọc trong
        try/except để lỗi enrichment không phá pipeline (vẫn có semantic report).
        """

        try:
            return self.meaning_layer.evaluate(user_text=text)
        except Exception:  # pragma: no cover - enrichment là best-effort
            return None

    @staticmethod
    def _slot_summary(meaning_slot: Any) -> str:
        """Rút một mẩu summary người-đọc-được từ meaning-slot (nếu có)."""

        if meaning_slot is None:
            return ""
        for attr in ("scene_meaning", "user_activity_meaning", "public_seed", "meaning"):
            value = str(getattr(meaning_slot, attr, "") or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _normalize(text: str) -> str:
        """Chuẩn hoá nhẹ cho so khớp keyword: lowercase + strip."""

        return str(text or "").strip().lower()

    # ------------------------------------------------------------------
    # Debug
    # ------------------------------------------------------------------
    @staticmethod
    def _build_debug(
        hypotheses: Sequence[MeaningHypothesis], notes: list[str]
    ) -> StageDebug:
        """Gom ``StageDebug`` với chỉ số tổng hợp của tập hypothesis."""

        if hypotheses:
            top = hypotheses[0]
            confidence: float | None = top.confidence
            ambiguity: float | None = max(h.ambiguity for h in hypotheses)
            overread_risk: float | None = max(h.overread_risk for h in hypotheses)
        else:  # pragma: no cover - generate() luôn sinh ≥1 hypothesis
            confidence = ambiguity = overread_risk = None
        return StageDebug(
            stage="MeaningHypothesisEngine",
            confidence=confidence,
            ambiguity=ambiguity,
            overread_risk=overread_risk,
            notes=list(notes),
        )
