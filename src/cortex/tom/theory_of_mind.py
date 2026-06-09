# -*- coding: utf-8 -*-
"""theory_of_mind.py — ``TheoryOfMindCore`` (stage 6 của Phase 2).

``MeaningHypothesis`` set + ``PragmaticIntent`` set → ``MentalStateInference`` set.

``TheoryOfMindCore`` suy luận **trạng thái tâm trí** (mental state) của đối phương
CHỈ từ đầu ra của ``MeaningHypothesisEngine`` và ``PragmaticIntentEngine`` — không
bao giờ từ ``Raw_World`` hay câu thô của người dùng. Ràng buộc "không đọc câu thô"
được cưỡng chế bằng **kiểu**: chữ ký ``infer`` chỉ nhận ``meaning`` và ``intents``
(R7.1), không có tham số nào mang văn bản thô.

Hợp đồng hành vi (map requirement):

- **R7.2 — ToM-after-Meaning GUARD**: mở đầu ``infer`` tra ``StageLedger``. Nếu
  ``MeaningHypothesisEngine`` HOẶC ``PragmaticIntentEngine`` chưa có entry cho
  ``frame_id`` hiện tại → ToM **từ chối chạy**: trả về tập rỗng và **ghi** một
  ``ToMOrderingViolation(missing_stage, frame_id)`` vào debug.

  Quyết định "raise vs return-empty": theo phần *Error Handling* của design —
  "ToM returns an empty inference set and records the violation" — module này
  **KHÔNG raise**; nó trả ``([], debug)`` với vi phạm được ghi observable trong
  ``StageDebug``: ``missing_fields`` chứa tên stage thiếu và ``notes`` chứa thông
  điệp của ``ToMOrderingViolation`` (R13.3 test có thể assert: không output +
  violation đã ghi).

- **R7.1** — chỉ suy từ ``meaning``/``intents``; không Raw_World/câu thô.
- **R7.6** — mỗi inference: ``category`` ∈ ``Taxonomy.MENTAL_STATE`` (gán qua
  ``Taxonomy.require``), ``confidence`` ∈ [0,1], có ``supporting_meaning_ids`` trỏ
  về ``MeaningHypothesis`` mà nó dẫn xuất.
- **R7.7** — nếu KHÔNG gắn được tham chiếu ``MeaningHypothesis`` hỗ trợ nào (id
  của intent không khớp meaning nào trong tập đầu vào) → vẫn sinh inference nhưng
  đánh cờ ``unsupported=True``.
- **R7.3** — dùng ``MentalStateRanker`` để xếp inference giảm dần theo plausibility.
- **R7.4** — dùng ``CounterfactualCorrector`` để hạ confidence khi có giải thích
  phản thực đủ mạnh.
- **R7.5/R7.8** — nhận ``history: ToMHistory`` do ``ToMHistoryAdapter`` cấp; nếu
  ``history.available is False`` → ghi "history unavailable" vào debug và **vẫn
  chạy tiếp**.

### Ánh xạ INTENT → MENTAL_STATE (xác định)

``_map_mental_state`` ánh xạ **xác định** một id ``Taxonomy.INTENT`` sang một id
``Taxonomy.MENTAL_STATE``:

| INTENT category        | MENTAL_STATE category |
|------------------------|-----------------------|
| ``express_frustration``| ``frustrated``        |
| ``ask_for_help``       | ``curious``           |
| ``tease``              | ``playful``           |
| ``seek_reassurance``   | ``anxious``           |
| ``share_information``  | ``content``           |
| ``request_action``     | ``content``           |
| ``test_boundary``      | ``withdrawn``         |
| ``seek_connection``    | ``affectionate``      |
| ``vent_emotion``       | ``hurt``              |
| ``deflect``            | ``withdrawn``         |

Category lạ → mặc định an toàn ``content`` (trung tính nhất, không over-read). Mọi
id đi qua ``Taxonomy.require("MENTAL_STATE", …)`` (R7.6/R11.2).

### Sinh counterfactual (phản thực) — cách tiếp cận

Một intent **đối thủ** có confidence cao là một diễn giải thay thế khả dĩ cho cùng
tín hiệu. Vì vậy với mỗi inference dẫn xuất từ intent ``Iₖ``, ta dựng các
``Counterfactual`` từ **các intent còn lại** ``Iⱼ (j ≠ k)``: mỗi counterfactual có
``confidence = Iⱼ.confidence`` và ``explanation`` mô tả trạng thái tâm trí thay
thế. ``CounterfactualCorrector`` sẽ hạ confidence của inference khi tồn tại một
counterfactual ``confidence ≥ threshold`` (mặc định của corrector). Cách này đơn
giản nhưng có thực: một alternative cạnh tranh mạnh làm giảm độ chắc chắn của
inference (R7.4), không bao giờ đẩy confidence xuống dưới 0.0.

Thứ tự xử lý: dựng inference thô → **corrector** hạ confidence theo counterfactual
→ **ranker** xếp hạng theo confidence đã hiệu chỉnh. Trả về danh sách đã xếp hạng.

Phụ thuộc một chiều: ``cortex.tom.theory_of_mind`` → ``cortex.tom.contracts`` /
``cortex.tom.mental_state_ranker`` / ``cortex.tom.counterfactual_corrector`` /
``cortex.meaning.*`` (config, taxonomy, contracts). Không import kênh Raw_World.
"""

from __future__ import annotations

from typing import Optional, Sequence

from ..meaning.config import Phase2Config, StageLedger
from ..meaning.contracts import MeaningHypothesis, PragmaticIntent, StageDebug
from ..meaning.taxonomy import Taxonomy
from .contracts import MentalStateInference, ToMHistory, ToMOrderingViolation
from .counterfactual_corrector import Counterfactual, CounterfactualCorrector
from .mental_state_ranker import MentalStateRanker


__all__ = ["TheoryOfMindCore"]


# Tên stage tiền đề bắt buộc cho ToM-after-Meaning guard (R7.2).
_REQUIRED_STAGES: tuple[str, ...] = (
    "MeaningHypothesisEngine",
    "PragmaticIntentEngine",
)

# Mental-state mặc định an toàn khi intent category không ánh xạ được (trung
# tính nhất, không over-read).
_DEFAULT_MENTAL_STATE = "content"

# Ánh xạ xác định INTENT category → MENTAL_STATE category. Thứ tự chèn cố định.
_INTENT_MENTAL_STATE_MAP: dict[str, str] = {
    "express_frustration": "frustrated",
    "ask_for_help": "curious",
    "tease": "playful",
    "seek_reassurance": "anxious",
    "share_information": "content",
    "request_action": "content",
    "test_boundary": "withdrawn",
    "seek_connection": "affectionate",
    "vent_emotion": "hurt",
    "deflect": "withdrawn",
}


class TheoryOfMindCore:
    """Suy ``MentalStateInference`` từ meaning + intents, có guard thứ tự (R7).

    Cộng sự được tiêm (injected) với mặc định an toàn:

    - ``ranker``: ``MentalStateRanker`` — xếp hạng inference (R7.3).
    - ``corrector``: ``CounterfactualCorrector`` — hạ confidence theo phản thực (R7.4).
    - ``config``: ``Phase2Config`` — nguồn ngưỡng dùng chung (giữ để mở rộng).
    """

    def __init__(
        self,
        *,
        ranker: Optional[MentalStateRanker] = None,
        corrector: Optional[CounterfactualCorrector] = None,
        config: Optional[Phase2Config] = None,
    ) -> None:
        self._ranker = ranker if ranker is not None else MentalStateRanker()
        self._corrector = (
            corrector if corrector is not None else CounterfactualCorrector()
        )
        self._config = config if config is not None else Phase2Config()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def infer(
        self,
        *,
        meaning: list[MeaningHypothesis],
        intents: list[PragmaticIntent],
        ledger: StageLedger,
        frame_id: str,
        history: ToMHistory,
    ) -> tuple[list[MentalStateInference], StageDebug]:
        """Suy tập ``MentalStateInference`` từ ``meaning``/``intents``.

        Xem docstring module cho hợp đồng đầy đủ (R7.1–R7.8). Trả
        ``(inferences, StageDebug)``; ``StageDebug`` là kênh debug tạm cho tới
        khi ``ToMDebug`` (task 17.1) thay thế.
        """

        notes: list[str] = []

        # --- R7.2: ToM-after-Meaning GUARD ---------------------------------
        missing_stage = self._first_missing_stage(ledger, frame_id)
        if missing_stage is not None:
            violation = ToMOrderingViolation(missing_stage, frame_id)
            notes.append(str(violation))
            # Không raise (design Error Handling): trả tập rỗng + ghi vi phạm
            # observable trong StageDebug (missing_fields + notes) cho R13.3.
            return [], StageDebug(
                stage="TheoryOfMindCore",
                confidence=None,
                ambiguity=None,
                overread_risk=None,
                missing_fields=[missing_stage],
                notes=notes,
            )

        # --- R7.8: history vắng → ghi chú, vẫn chạy tiếp -------------------
        if history is None or not history.available:
            notes.append("history unavailable")

        intent_list = [it for it in (intents or []) if it is not None]
        meaning_ids = {
            str(h.hypothesis_id)
            for h in (meaning or [])
            if h is not None
        }

        # --- Tập rỗng intent → không inference -----------------------------
        if not intent_list:
            notes.append("no mental-state inference could be derived")
            return [], self._build_debug([], notes)

        # --- Dựng inference thô (một inference cho mỗi intent) -------------
        raw_inferences = [
            self._build_inference(frame_id, intent, meaning_ids)
            for intent in intent_list
        ]

        # --- R7.4: hạ confidence theo counterfactual từ intent đối thủ -----
        corrected = self._apply_counterfactuals(raw_inferences, intent_list)

        # --- R7.3: xếp hạng theo confidence đã hiệu chỉnh ------------------
        ranked = self._ranker.rank(corrected)

        notes.append(
            f"derived {len(ranked)} mental-state inference(s) from "
            f"{len(intent_list)} intent(s)"
        )
        return ranked, self._build_debug(ranked, notes)

    # ------------------------------------------------------------------
    # Guard
    # ------------------------------------------------------------------
    @staticmethod
    def _first_missing_stage(
        ledger: StageLedger, frame_id: str
    ) -> Optional[str]:
        """Trả tên stage tiền đề ĐẦU TIÊN còn thiếu cho ``frame_id`` (hoặc None).

        Thứ tự kiểm theo ``_REQUIRED_STAGES`` để thông điệp vi phạm xác định.
        ``ledger is None`` → coi như Meaning thiếu (không thể xác nhận thứ tự).
        """

        if ledger is None:
            return _REQUIRED_STAGES[0]
        for stage in _REQUIRED_STAGES:
            if not ledger.has(stage, frame_id):
                return stage
        return None

    # ------------------------------------------------------------------
    # Inference construction
    # ------------------------------------------------------------------
    def _build_inference(
        self,
        frame_id: str,
        intent: PragmaticIntent,
        meaning_ids: set[str],
    ) -> MentalStateInference:
        """Dựng một ``MentalStateInference`` từ một ``PragmaticIntent``.

        - ``category`` ánh xạ xác định từ ``intent.category`` (R7.6).
        - ``supporting_meaning_ids`` = các id của intent gắn được vào một
          ``MeaningHypothesis`` trong tập đầu vào; không gắn được id nào →
          ``unsupported=True`` (R7.7).
        - ``confidence``/``overread_risk`` kế thừa từ intent (đã clamp [0,1] tại
          ``__post_init__`` của ``MentalStateInference``).
        """

        mental_state = self._map_mental_state(intent.category)

        attachable = [
            mid
            for mid in (intent.supporting_meaning_ids or [])
            if str(mid) in meaning_ids
        ]
        unsupported = len(attachable) == 0

        return MentalStateInference(
            inference_id=f"{frame_id}:tom:{intent.category}",
            category=Taxonomy.require("MENTAL_STATE", mental_state),
            summary=f"infers '{mental_state}' from intent '{intent.category}'",
            confidence=intent.confidence,
            overread_risk=intent.overread_risk,
            supporting_meaning_ids=attachable,
            unsupported=unsupported,
        )

    @staticmethod
    def _map_mental_state(intent_category: str) -> str:
        """Ánh xạ xác định ``Taxonomy.INTENT`` id → ``Taxonomy.MENTAL_STATE`` id.

        Mặc định an toàn ``content`` khi không khớp (R7.6/R11.2).
        """

        category = str(intent_category or "").strip().lower()
        return _INTENT_MENTAL_STATE_MAP.get(category, _DEFAULT_MENTAL_STATE)

    # ------------------------------------------------------------------
    # Counterfactual correction (R7.4)
    # ------------------------------------------------------------------
    def _apply_counterfactuals(
        self,
        inferences: Sequence[MentalStateInference],
        intents: Sequence[PragmaticIntent],
    ) -> list[MentalStateInference]:
        """Hạ confidence từng inference theo counterfactual từ intent đối thủ.

        Với inference thứ ``k`` (dẫn xuất từ intent ``k``), counterfactual là MỌI
        intent ``j ≠ k``: một diễn giải cạnh tranh khả dĩ. ``CounterfactualCorrector``
        hạ confidence khi tồn tại counterfactual ``confidence ≥ threshold`` của nó.
        """

        result: list[MentalStateInference] = []
        for k, inference in enumerate(inferences):
            counterfactuals = [
                Counterfactual(
                    explanation=(
                        f"alternative reading: intent '{other.category}' "
                        f"(maps to '{self._map_mental_state(other.category)}')"
                    ),
                    confidence=other.confidence,
                )
                for j, other in enumerate(intents)
                if j != k
            ]
            result.append(self._corrector.correct(inference, counterfactuals))
        return result

    # ------------------------------------------------------------------
    # Debug
    # ------------------------------------------------------------------
    @staticmethod
    def _build_debug(
        inferences: Sequence[MentalStateInference], notes: list[str]
    ) -> StageDebug:
        """Gom ``StageDebug`` với chỉ số tổng hợp của tập inference.

        Kênh debug tạm: ``ToMDebug`` (task 17.1) sẽ render người-đọc-được sau.
        """

        if inferences:
            confidence: float | None = inferences[0].confidence
            overread_risk: float | None = max(
                inf.overread_risk for inf in inferences
            )
        else:
            confidence = None
            overread_risk = None
        return StageDebug(
            stage="TheoryOfMindCore",
            confidence=confidence,
            ambiguity=None,
            overread_risk=overread_risk,
            notes=list(notes),
        )
