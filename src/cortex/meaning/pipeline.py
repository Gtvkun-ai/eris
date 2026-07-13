# -*- coding: utf-8 -*-
"""pipeline.py — ``Phase2MeaningPipeline`` facade (task 18.1).

Dây nối (wiring) toàn bộ pipeline Phase 2 thành một facade duy nhất chạy **đúng
thứ tự bắt buộc** và cưỡng chế hai ràng buộc xương sống:

1. **WorkspaceFrame-only (R1)** — mọi stage chỉ đọc frame qua ``FrameReadView``
   (``view.for_module("<Stage>")``); không stage nào chạm ``Raw_World``.
2. **ToM-after-Meaning (R7.2)** — ``StageLedger`` ghi nhận ``MeaningHypothesisEngine``
   và ``PragmaticIntentEngine`` **trước** khi ``TheoryOfMindCore`` chạy; nhờ vậy
   guard thứ tự bên trong ToM không bao giờ trip khi đi qua facade này.

Thứ tự pipeline (mỗi mũi tên = đầu ra stage trước thành đầu vào stage sau)::

    WorkspaceFrame
      → FrameReadView
      → WorldSceneBuilder.build        → (WorldScene, sd1)
      → WorldInterpreter.interpret     → (Observation[], sd2)
      → SocioculturalContext.annotate  → (ContextAnnotation[], sd3)
      → MeaningHypothesisEngine.generate → (MeaningHypothesis[], sd4)  [ledger.record]
      → PragmaticIntentEngine.derive   → (PragmaticIntent[], sd5)      [ledger.record]
      → TheoryOfMindCore.infer         → (MentalStateInference[], sd6)
      → OverreadBrake.evaluate         → (EvaluatedConclusion[], sd7)
      → SurfaceMeaningPolicy.partition → Phase2Result (+ stage debugs / Phase2Run)

### Quyết định về ``semantic_engine`` mặc định (out-of-the-box)

``MeaningHypothesisEngine`` (stage 4) **bọc** một ``SemanticHypothesisEngine``,
mà engine đó cần một *embedding encoder*. Một encoder thật (sentence-transformer /
remote API) là **nặng** và cần model tải về — không phù hợp để facade chạy ngay
trong test hay dev mà không có hạ tầng.

Khảo sát ``cortex.semantic_encoder`` cho thấy đã có sẵn
``LexicalHashingSemanticEncoder``: một encoder **fallback xác định** (deterministic)
dựa trên hashing token/char, KHÔNG cần model tải về, luôn đánh dấu
``is_fallback=True`` để downstream tự cap confidence. Vì vậy:

- Nếu caller **tiêm** ``semantic_engine`` → dùng đúng cái đó.
- Nếu KHÔNG → facade **lười dựng** (lazy, chỉ khi ``run()`` lần đầu) một
  ``SemanticHypothesisEngine(LexicalHashingSemanticEncoder())`` thật. Đây là lựa
  chọn sạch hơn một ``_NullSemanticEngine`` giả: nó đi qua đúng đường dẫn scoring
  thật (delegate đầy đủ, R5.7) trong khi vẫn an toàn — embedding fallback có
  confidence bị cap và ``overread_risk`` cao, nên pipeline **tự nhiên** nghiêng về
  đường "insufficient evidence" / withheld thay vì phán bậy. Không tải model,
  không I/O ngoài.

Encoder/engine được import **lười** bên trong ``run()`` (không ở thời điểm load
module) để tránh kéo theo phụ thuộc encoder khi chỉ cần import facade.

``meaning_layer`` (``cortex.meaning.meaning_layer.MeaningLayer``) là nhẹ, không cần
encoder, nên mặc định dựng ngay bằng ``MeaningLayer()``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from .ambiguity import AmbiguityModule
from .config import Phase2Config, StageLedger
from .contracts import (
    Conclusion,
    Phase2Result,
    StageDebug,
)
from .debug_render import Phase2Run
from .meaning_hypothesis import MeaningHypothesisEngine
from .overread_brake import OverreadBrake
from .pragmatic_intent import PragmaticIntentEngine
from .read_contract import FrameReadView, RawWorldAccessError
from .sociocultural_context import SocioculturalContext
from .surface_meaning_policy import SurfaceMeaningPolicy
from .world_interpreter import WorldInterpreter
from .world_scene_builder import WorldSceneBuilder

if TYPE_CHECKING:  # pragma: no cover - chỉ phục vụ type-checker
    from ..global_workspace import WorkspaceFrame
    from ..semantic_hypothesis import SemanticHypothesisEngine
    from .meaning_layer import MeaningLayer


__all__ = ["Phase2MeaningPipeline"]


# Tên module dùng để đọc ``forbidden_assumptions`` cho OverreadBrake. Trong hợp
# đồng mặc định của Phase 2, "TheoryOfMindCore" được phép đọc field này (R8.6).
_FORBIDDEN_READER_MODULE = "TheoryOfMindCore"

# Lever D: độ "dám đọc" mặc định của ToM trong pipeline. Tự gate theo
# overread_risk bên trong ToM, nên đây là quyền dám đọc ở vùng rủi ro thấp,
# không phải quyền overclaim. 0.0 = thủ như cũ; ~0.5 = dám hơn một cách an toàn.
_TOM_BOLDNESS = 0.5


def _resolve_tom_boldness() -> float:
    """Boldness hiệu dụng: hằng số nền + độ-dám-đọc long-arc (nếu feature bật).

    TRƠ TUYỆT ĐỐI khi tắt: kiểm tra env TRƯỚC, không import gì từ module mới nếu
    chưa bật. Bọc try/except để không bao giờ làm crash hay đổi hành vi pipeline.
    """
    import os as _os

    if _os.getenv("ERIS_DEVELOPMENT_GROWTH_ENABLED", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return _TOM_BOLDNESS
    try:
        from ..development_system import get_default_development_system
        from ..development_bias import effective_tom_boldness

        system = get_default_development_system()
        system.profile.reload_if_changed()
        return effective_tom_boldness(_TOM_BOLDNESS, system.development_bias())
    except Exception:
        return _TOM_BOLDNESS


class Phase2MeaningPipeline:
    """Facade chạy toàn bộ pipeline Phase 2 theo đúng thứ tự bắt buộc.

    Dùng đơn giản nhất::

        from cortex.meaning import Phase2MeaningPipeline
        result = Phase2MeaningPipeline().run(frame)   # frame: WorkspaceFrame

    Cộng sự nặng (``semantic_engine``) được tiêm tùy chọn; nếu không, facade lười
    dựng một engine fallback xác định để chạy được ngay (xem docstring module).
    """

    def __init__(
        self,
        *,
        config: Optional[Phase2Config] = None,
        semantic_engine: Optional["SemanticHypothesisEngine"] = None,
        meaning_layer: Optional["MeaningLayer"] = None,
    ) -> None:
        self.config = config if config is not None else Phase2Config()

        # MeaningLayer nhẹ, không cần encoder → dựng ngay nếu không được tiêm.
        if meaning_layer is None:
            from .meaning_layer import MeaningLayer

            meaning_layer = MeaningLayer()
        self.meaning_layer = meaning_layer

        # semantic_engine có thể nặng → KHÔNG dựng vội. Giữ None và lười dựng một
        # engine fallback xác định ở lần run() đầu tiên nếu vẫn None.
        self._semantic_engine = semantic_engine

        # Cộng sự nhẹ, không phụ thuộc encoder — dựng sẵn.
        self.ambiguity_module = AmbiguityModule()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(self, frame: Optional["WorkspaceFrame"]) -> Phase2Result:
        """Chạy frame qua toàn bộ pipeline, trả ``Phase2Result``.

        ``frame is None`` → chạy với ``view=None`` (đường empty-scene của
        ``WorldSceneBuilder``), kết thúc bằng ``Phase2Result`` rỗng (không
        surfaced/withheld). ``frame_id`` luôn được gắn lên kết quả (R1.5).
        """

        ledger = StageLedger()
        stage_debugs: List[StageDebug] = []

        # --- Wrap frame trong FrameReadView (boundary đọc có kiểm soát) -------
        root_view: Optional[FrameReadView] = (
            FrameReadView(frame) if frame is not None else None
        )
        frame_id: Optional[str] = frame.frame_id if frame is not None else None

        # --- Stage 1: WorldSceneBuilder --------------------------------------
        scene, sd1 = WorldSceneBuilder().build(
            self._view_for(root_view, "WorldSceneBuilder")
        )
        stage_debugs.append(sd1)

        # --- Stage 2: WorldInterpreter ---------------------------------------
        observations, sd2 = WorldInterpreter().interpret(
            scene, low_conf_threshold=self.config.interpreter_low_conf
        )
        stage_debugs.append(sd2)

        # --- Stage 3: SocioculturalContext -----------------------------------
        annotations, sd3 = SocioculturalContext().annotate(
            observations, self._view_for(root_view, "SocioculturalContext")
        )
        stage_debugs.append(sd3)

        # --- Stage 4: MeaningHypothesisEngine (WRAP semantic + meaning) ------
        meaning_engine = MeaningHypothesisEngine(
            semantic_engine=self._get_semantic_engine(),
            meaning_layer=self.meaning_layer,
            ambiguity_module=self.ambiguity_module,
            config=self.config,
        )
        meaning_hyps, sd4 = meaning_engine.generate(annotations, frame_id=frame_id)
        stage_debugs.append(sd4)
        # ToM-after-Meaning: ghi Meaning vào ledger TRƯỚC khi ToM chạy (R7.2).
        ledger.record("MeaningHypothesisEngine", frame_id)

        # --- Stage 5: PragmaticIntentEngine ----------------------------------
        intents, sd5 = PragmaticIntentEngine().derive(meaning_hyps, frame_id=frame_id)
        stage_debugs.append(sd5)
        ledger.record("PragmaticIntentEngine", frame_id)

        # --- Stage 6: TheoryOfMindCore (chỉ chạy sau Meaning/Pragmatic) ------
        from ..tom import ToMHistoryAdapter, TheoryOfMindCore

        history = ToMHistoryAdapter().load(
            self._view_for(root_view, "TheoryOfMindCore")
        )
        mental_states, sd6 = TheoryOfMindCore().infer(
            meaning=meaning_hyps,
            intents=intents,
            ledger=ledger,
            frame_id=frame_id,
            history=history,
            # Lever D: dám đọc ở rủi ro thấp. Tự gate theo overread_risk nên cú đọc
            # rủi ro cao vẫn bị thắng; chỉ cú đọc ít rủi ro được phép sống.
            # Long-arc (eris-developmental-growth): khi bật, độ-dám-đọc tích lũy
            # cộng thêm vào boldness; mặc định tắt nên giữ nguyên hành vi cũ.
            boldness=_resolve_tom_boldness(),
        )
        stage_debugs.append(sd6)

        # --- Stage 7: OverreadBrake (gom mọi conclusion) ---------------------
        conclusions: List[Conclusion] = []
        conclusions.extend(meaning_hyps)
        conclusions.extend(intents)
        conclusions.extend(mental_states)
        forbidden = self._read_forbidden(root_view)
        evaluated, sd7 = OverreadBrake(self.config).evaluate(
            conclusions, forbidden_assumptions=forbidden
        )
        stage_debugs.append(sd7)

        # --- Stage 8: SurfaceMeaningPolicy → Phase2Result --------------------
        result = SurfaceMeaningPolicy(self.config).partition(
            evaluated, frame_id=frame_id
        )

        # Giữ nguyên artifact trung gian trên kết quả canonical. Đây không phải
        # debug decoration: CognitivePipeline dùng chính các object này để điền
        # world_scene / interpretation / sociocultural / meaning / tom mà không
        # chạy Phase 2 lần thứ hai. Một pipeline chạy hai lần cho cùng một input là
        # một cách khá sáng tạo để tự tạo ra hai sự thật.
        result.world_scene = scene
        result.observations = list(observations)
        result.sociocultural_annotations = list(annotations)
        result.meaning_hypotheses = list(meaning_hyps)
        result.pragmatic_intents = list(intents)
        result.mental_states = list(mental_states)
        result.evaluated_conclusions = list(evaluated)

        # --- Gắn stage debugs + Phase2Run vào result.debug -------------------
        self._attach_debug(result, frame_id, stage_debugs)
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _view_for(
        root_view: Optional[FrameReadView], module: str
    ) -> Optional[FrameReadView]:
        """Trả view đã scope theo ``module`` (hoặc ``None`` khi không có frame)."""

        if root_view is None:
            return None
        return root_view.for_module(module)

    def _get_semantic_engine(self) -> "SemanticHypothesisEngine":
        """Trả ``SemanticHypothesisEngine``, lười dựng fallback xác định nếu cần.

        Xem docstring module cho lý do chọn ``LexicalHashingSemanticEncoder``
        (fallback deterministic, không tải model, an toàn no-overread).
        """

        if self._semantic_engine is None:
            # Import lười để không kéo encoder vào khi chỉ import facade.
            from ..semantic_encoder import LexicalHashingSemanticEncoder
            from ..semantic_hypothesis import SemanticHypothesisEngine

            self._semantic_engine = SemanticHypothesisEngine(
                LexicalHashingSemanticEncoder()
            )
        return self._semantic_engine

    @staticmethod
    def _read_forbidden(root_view: Optional[FrameReadView]) -> List[str]:
        """Đọc ``forbidden_assumptions`` qua hợp đồng (module được phép đọc).

        Ngoài hợp đồng / không có frame → trả ``[]`` (degrade, không crash). Đây
        là đầu vào cho luật R8.6 của ``OverreadBrake``.
        """

        if root_view is None:
            return []
        try:
            raw = root_view.read(
                "forbidden_assumptions", module=_FORBIDDEN_READER_MODULE
            )
        except RawWorldAccessError:
            return []
        except Exception:  # pragma: no cover - phòng thủ, không bao giờ crash facade
            return []
        if not raw:
            return []
        return [str(item) for item in raw if item is not None]

    @staticmethod
    def _attach_debug(
        result: Phase2Result,
        frame_id: Optional[str],
        stage_debugs: List[StageDebug],
    ) -> None:
        """Gắn danh sách ``StageDebug`` + một ``Phase2Run`` vào ``result.debug``.

        ``result.debug`` đã là dict (do ``SurfaceMeaningPolicy`` dựng); ta bổ
        sung thông tin run-level để ``DebugRender`` có thể render lại đầy đủ.
        """

        debug = result.debug if isinstance(result.debug, dict) else {}
        debug["frame_id"] = frame_id
        debug["stage_debugs"] = stage_debugs
        debug["phase2_run"] = Phase2Run(
            frame_id=frame_id,
            stage_debugs=stage_debugs,
            result=result,
        )
        result.debug = debug
