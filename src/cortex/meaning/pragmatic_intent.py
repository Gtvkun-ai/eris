# -*- coding: utf-8 -*-
"""pragmatic_intent.py — ``PragmaticIntentEngine`` (stage 5 của Phase 2).

MeaningHypothesis set → PragmaticIntent set.

Engine này suy ý định giao tiếp (pragmatic intent: yêu cầu, than phiền, đùa,
thăm dò…) **chỉ từ** tập ``MeaningHypothesis`` do ``MeaningHypothesisEngine``
sinh ra. Nó KHÔNG đọc/không tham chiếu Raw_World — chữ ký ``derive`` chỉ nhận
``list[MeaningHypothesis]`` nên ràng buộc "không đọc câu thô / raw world" được
cưỡng chế bằng kiểu (R6.2).

Hợp đồng hành vi (map requirement):

- **R6.1** — tập ranked KHÔNG rỗng → sinh 1..8 ``PragmaticIntent``, mỗi cái thuộc
  ĐÚNG MỘT category trong ``Taxonomy.INTENT`` (gán qua ``Taxonomy.require``).
- **R6.2** — chỉ suy từ ``MeaningHypothesis``; không đọc Raw_World.
- **R6.3** — mỗi intent có ``confidence ∈ [0,1]`` và ≥1
  ``supporting_meaning_ids``; danh sách hỗ trợ được GIỮ kể cả khi
  ``confidence == 0.0``.
- **R6.4** — nếu BẤT KỲ supporter nào có ``ambiguity > 0.7`` → intent dẫn xuất
  nhận ``confidence`` **nghiêm ngặt thấp hơn** so với khi cùng tập supporter
  nhưng mọi ``ambiguity ≤ 0.7`` (xem "Công thức confidence" bên dưới).
- **R6.5** — tập rỗng → 0 intent + ghi chú "no pragmatic intent could be
  derived" trong ``StageDebug.notes``.

### Ánh xạ Taxonomy.MEANING → Taxonomy.INTENT (xác định)

``_map_intent`` là ánh xạ **xác định** (deterministic) từ
``MeaningHypothesis.category`` (một id ``Taxonomy.MEANING``) sang một id
``Taxonomy.INTENT``, có tinh chỉnh nhẹ theo ``summary``:

| MEANING category        | INTENT category      |
|-------------------------|----------------------|
| ``request``             | ``request_action``   |
| ``question``            | ``ask_for_help``     |
| ``complaint``           | ``express_frustration`` |
| ``joke``                | ``tease``            |
| ``probe``               | ``test_boundary``    |
| ``emotional_disclosure``| ``vent_emotion`` (→ ``seek_reassurance`` nếu summary gợi ý trấn an) |
| ``small_talk``          | ``seek_connection``  |
| ``agreement``           | ``seek_connection``  |
| ``disagreement``        | ``express_frustration`` |
| ``sarcasm``             | ``deflect``          |
| ``literal_statement``   | ``share_information``|

Không khớp gì (category lạ) → dò keyword trên ``summary``; vẫn không khớp →
mặc định an toàn ``share_information`` (intent trung tính nhất, không over-read).
Mọi category đi qua ``Taxonomy.require("INTENT", …)`` (R6.1/R11.2).

### Khử trùng theo intent category

Nhiều ``MeaningHypothesis`` có thể ánh xạ về cùng một intent. Engine gom chúng
thành MỘT ``PragmaticIntent`` cho mỗi category: hợp nhất (union, giữ thứ tự)
``supporting_meaning_ids`` và tổng hợp confidence/ambiguity/overread_risk từ toàn
bộ supporter của nhóm. Sau đó xếp giảm dần theo ``confidence`` (tie-break theo id
category để xác định) và GIỮ tối đa 8 (R6.1).

### Công thức confidence ∈ [0,1] (R6.3, R6.4)

Confidence của một intent là **hàm thuần** của tập supporter::

    base   = max(supporter.confidence for supporter in group)   # đơn điệu tăng
    factor = 1.0                          nếu max_ambiguity ≤ HIGH_AMBIGUITY_THRESHOLD
           = 1.0 - HIGH_AMBIGUITY_PENALTY nếu max_ambiguity  > HIGH_AMBIGUITY_THRESHOLD
    confidence = clamp01(base * factor)

trong đó ``max_ambiguity = max(supporter.ambiguity for supporter in group)``,
``HIGH_AMBIGUITY_THRESHOLD = 0.7`` và ``HIGH_AMBIGUITY_PENALTY = 0.5`` (>0).

Vì ``factor`` cho nhánh ambiguity-cao = ``0.5`` **nhỏ hơn nghiêm ngặt** ``1.0`` của
nhánh ambiguity-thấp, với CÙNG tập supporter và ``base > 0`` ta có
``base*0.5 < base*1.0`` — tức confidence khi có supporter ``ambiguity > 0.7``
luôn **thấp hơn nghiêm ngặt** so với khi mọi ``ambiguity ≤ 0.7`` (R6.4). Quan hệ
này có thể kiểm chứng vì confidence là hàm thuần của supporter: chỉ thay đổi
ambiguity của supporter (vượt/không vượt 0.7) là yếu tố duy nhất đổi ``factor``.
Trường hợp suy biến ``base == 0`` cho cùng giá trị 0 ở cả hai nhánh; danh sách
``supporting_meaning_ids`` vẫn được giữ nguyên (R6.3).

``overread_risk`` của intent lấy ``max`` overread_risk của supporter (mang rủi ro
mạnh nhất xuôi dòng để OverreadBrake xử ở stage sau).
"""

from __future__ import annotations

from typing import Sequence

from .contracts import MeaningHypothesis, PragmaticIntent, StageDebug, clamp01
from .taxonomy import Taxonomy


__all__ = ["PragmaticIntentEngine"]


# Số intent tối đa được sinh (R6.1: "between 1 and 8").
_MAX_INTENTS = 8

# Ngưỡng ambiguity "cao" và mức phạt confidence khi vượt ngưỡng (R6.4). Penalty
# > 0 nên nhánh ambiguity-cao luôn cho confidence thấp hơn nghiêm ngặt khi base>0.
_HIGH_AMBIGUITY_THRESHOLD = 0.7
_HIGH_AMBIGUITY_PENALTY = 0.5

# Intent an toàn mặc định khi không ánh xạ được (trung tính, không over-read).
_DEFAULT_INTENT = "share_information"

# Ánh xạ xác định MEANING category → INTENT category. Thứ tự chèn cố định.
_MEANING_INTENT_MAP: dict[str, str] = {
    "request": "request_action",
    "question": "ask_for_help",
    "complaint": "express_frustration",
    "joke": "tease",
    "probe": "test_boundary",
    "emotional_disclosure": "vent_emotion",
    "small_talk": "seek_connection",
    "agreement": "seek_connection",
    "disagreement": "express_frustration",
    "sarcasm": "deflect",
    "literal_statement": "share_information",
}

# Keyword (substring) trên summary gợi ý ý định "tìm trấn an" cho
# emotional_disclosure (tinh chỉnh "and/or summary" của R6.1).
_REASSURANCE_KEYWORDS: tuple[str, ...] = (
    "reassur",
    "worry",
    "worried",
    "afraid",
    "scared",
    "anxious",
    "nervous",
)

# Keyword (substring) trên summary để dò intent khi category không ánh xạ được.
_SUMMARY_KEYWORD_MAP: dict[str, str] = {
    "help": "ask_for_help",
    "please": "request_action",
    "frustrat": "express_frustration",
    "annoy": "express_frustration",
    "joke": "tease",
    "tease": "tease",
    "test": "test_boundary",
    "probe": "test_boundary",
    "connect": "seek_connection",
    "reassur": "seek_reassurance",
}


class PragmaticIntentEngine:
    """Suy ``PragmaticIntent`` từ tập ``MeaningHypothesis`` (stage 5).

    Chỉ nhận ``MeaningHypothesis`` qua chữ ký ``derive`` — không có kênh nào tới
    Raw_World (R6.2).
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def derive(
        self, hypotheses: list[MeaningHypothesis], *, frame_id: str
    ) -> tuple[list[PragmaticIntent], StageDebug]:
        """Suy tập ``PragmaticIntent`` từ ``hypotheses``.

        Xem docstring module cho hợp đồng đầy đủ (R6.1–R6.5).
        """

        notes: list[str] = []
        supporters = [h for h in (hypotheses or []) if h is not None]

        # --- R6.5: tập rỗng → 0 intent + chỉ báo ----------------------------
        if not supporters:
            notes.append("no pragmatic intent could be derived")
            return [], self._build_debug([], notes)

        # --- Gom supporter theo intent category (giữ thứ tự xuất hiện) ------
        # grouped[intent] = list các MeaningHypothesis ánh xạ về intent đó.
        grouped: dict[str, list[MeaningHypothesis]] = {}
        for hyp in supporters:
            intent_category = self._map_intent(hyp.category, hyp.summary)
            grouped.setdefault(intent_category, []).append(hyp)

        # --- Dựng một PragmaticIntent cho mỗi nhóm --------------------------
        intents: list[PragmaticIntent] = []
        for intent_category, group in grouped.items():
            intents.append(self._build_intent(frame_id, intent_category, group))

        # --- Xếp giảm dần confidence; tie-break theo category (xác định) ----
        intents.sort(key=lambda it: (-it.confidence, it.category))

        # --- R6.1: giữ tối đa 8 --------------------------------------------
        if len(intents) > _MAX_INTENTS:
            notes.append(
                f"capped intents from {len(intents)} to {_MAX_INTENTS} (top by confidence)"
            )
            intents = intents[:_MAX_INTENTS]

        notes.append(
            f"derived {len(intents)} pragmatic intent(s) from {len(supporters)} hypothesis(es)"
        )
        return intents, self._build_debug(intents, notes)

    # ------------------------------------------------------------------
    # Intent construction
    # ------------------------------------------------------------------
    def _build_intent(
        self, frame_id: str, intent_category: str, group: Sequence[MeaningHypothesis]
    ) -> PragmaticIntent:
        """Dựng một ``PragmaticIntent`` từ nhóm supporter cùng intent category.

        Hợp nhất ``supporting_meaning_ids`` (giữ luôn kể cả khi confidence==0,
        R6.3) và tổng hợp confidence theo công thức R6.4.
        """

        supporting_ids = self._collect_support_ids(group)
        confidence = self._aggregate_confidence(group)
        overread_risk = max((clamp01(h.overread_risk) for h in group), default=0.0)

        return PragmaticIntent(
            intent_id=f"{frame_id}:intent:{intent_category}",
            category=Taxonomy.require("INTENT", intent_category),
            confidence=confidence,
            supporting_meaning_ids=supporting_ids,
            overread_risk=overread_risk,
        )

    @staticmethod
    def _aggregate_confidence(group: Sequence[MeaningHypothesis]) -> float:
        """Confidence ∈ [0,1] của intent — hàm thuần của supporter (R6.3, R6.4).

        ``base = max(supporter.confidence)`` (đơn điệu tăng theo độ tin của
        supporter); nếu ``max(supporter.ambiguity) > 0.7`` thì nhân ``factor``
        nhỏ hơn 1.0 một cách nghiêm ngặt → confidence thấp hơn hẳn (R6.4).
        """

        base = max((clamp01(h.confidence) for h in group), default=0.0)
        max_ambiguity = max((clamp01(h.ambiguity) for h in group), default=0.0)
        factor = (
            1.0 - _HIGH_AMBIGUITY_PENALTY
            if max_ambiguity > _HIGH_AMBIGUITY_THRESHOLD
            else 1.0
        )
        return clamp01(base * factor)

    @staticmethod
    def _collect_support_ids(group: Sequence[MeaningHypothesis]) -> list[str]:
        """Hợp nhất ``hypothesis_id`` của nhóm, dedupe, giữ thứ tự xuất hiện.

        Luôn trả ≥1 id (nhóm theo định nghĩa có ≥1 supporter) — giữ cả khi
        confidence của intent bằng 0.0 (R6.3).
        """

        seen: set[str] = set()
        ordered: list[str] = []
        for hyp in group:
            hid = str(getattr(hyp, "hypothesis_id", "") or "")
            if hid and hid not in seen:
                seen.add(hid)
                ordered.append(hid)
        return ordered

    # ------------------------------------------------------------------
    # Intent mapping (deterministic)
    # ------------------------------------------------------------------
    @classmethod
    def _map_intent(cls, meaning_category: str, summary: str) -> str:
        """Ánh xạ xác định MEANING category (+summary) → ``Taxonomy.INTENT`` id.

        Mặc định an toàn ``share_information`` khi không khớp gì (R6.1/R11.2).
        """

        category = str(meaning_category or "").strip().lower()
        normalized_summary = str(summary or "").strip().lower()

        # 1) Tinh chỉnh emotional_disclosure theo summary: gợi ý trấn an?
        if category == "emotional_disclosure":
            if any(kw in normalized_summary for kw in _REASSURANCE_KEYWORDS):
                return Taxonomy.require("INTENT", "seek_reassurance")
            return Taxonomy.require("INTENT", "vent_emotion")

        # 2) Ánh xạ trực tiếp theo MEANING category.
        mapped = _MEANING_INTENT_MAP.get(category)
        if mapped is not None:
            return Taxonomy.require("INTENT", mapped)

        # 3) Category lạ → dò keyword trên summary.
        for keyword, intent in _SUMMARY_KEYWORD_MAP.items():
            if keyword in normalized_summary:
                return Taxonomy.require("INTENT", intent)

        # 4) Mặc định an toàn.
        return Taxonomy.require("INTENT", _DEFAULT_INTENT)

    # ------------------------------------------------------------------
    # Debug
    # ------------------------------------------------------------------
    @staticmethod
    def _build_debug(
        intents: Sequence[PragmaticIntent], notes: list[str]
    ) -> StageDebug:
        """Gom ``StageDebug`` với chỉ số tổng hợp của tập intent."""

        if intents:
            confidence: float | None = intents[0].confidence
            overread_risk: float | None = max(it.overread_risk for it in intents)
        else:
            confidence = None
            overread_risk = None
        return StageDebug(
            stage="PragmaticIntentEngine",
            confidence=confidence,
            ambiguity=None,
            overread_risk=overread_risk,
            notes=list(notes),
        )
