# -*- coding: utf-8 -*-
"""
cortex/situation_model.py
=========================

Situation Model — mô hình tình huống bền vững với vòng dự đoán → quan sát → sai số.

Đây là câu trả lời cho "TẦNG 2 — không có mô hình, chỉ có máy đếm lặp": novelty của
ERIS trước đây chỉ là bảng tra theo `repeat_count`. Module này mang một trạng thái
tình huống sống qua các chu kỳ (Cognitive_Cycle), tạo một dự đoán ngắn về cái sắp
tới, rồi mỗi chu kỳ đo "sai số dự đoán" = khoảng cách ngữ nghĩa giữa điều đã kỳ vọng
và thực tế quan sát được. Sai số đó (chứ không phải số lần lặp) mới là "mới".

Nguyên tắc:
- Mặc định bật (config.enabled=true). Khi tắt, không ai bị ảnh hưởng.
- Tái dùng hạ tầng sẵn có: cosine/normalize/embedding-cache trong event_semantics,
  và tokenize/clamp01 trong attention_salience. Không phát minh lại bánh xe.
- Tất định: lõi cập nhật nhận `now` từ ngoài, không gọi time.time() ngầm.
- Commit-or-rollback: lỗi giữa chừng không để lại trạng thái nửa vời.

Module này KHÔNG ghi long-term memory, KHÔNG gọi LLM, KHÔNG kết luận tâm lý người
dùng. Nó chỉ duy trì "tôi đang nghĩ chuyện gì sắp xảy ra, và thực tế lệch bao nhiêu".
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Optional, Sequence


# =============================================================================
# 0. Import mềm — tái dùng hạ tầng sẵn có
# =============================================================================

try:  # cùng package cortex
    from .event_semantics import (  # type: ignore
        EventEmbeddingCache,
        _cosine_similarity,
        _normalize_vector,
    )
except Exception:  # pragma: no cover
    from cortex.event_semantics import (  # type: ignore
        EventEmbeddingCache,
        _cosine_similarity,
        _normalize_vector,
    )

try:  # cùng package cortex
    from .attention_salience import clamp01, safe_float, tokenize  # type: ignore
except Exception:  # pragma: no cover
    from cortex.attention_salience import clamp01, safe_float, tokenize  # type: ignore


# =============================================================================
# 1. Literal contracts
# =============================================================================

EngagementTrend = Literal["tang", "giam", "on_dinh"]   # tăng / giảm / ổn định

# Lý do prediction_error không xác định / degraded — tập phân loại quan sát được.
ErrorReason = Literal[
    "ok",
    "cold_start",
    "no_percept",
    "missing_prediction_embedding",
    "missing_percept_embedding",
    "no_prev_prediction",
]

_MAX_PREDICTION_LEN = 280


# =============================================================================
# 2. Data models
# =============================================================================

@dataclass(slots=True)
class Prediction:
    """Dự đoán ngắn về percept mong đợi ở chu kỳ kế tiếp."""

    description: str = ""                 # 1..280 ký tự khi không rỗng
    confidence: float = 0.0               # [0,1]; Cold_Start -> 0.0
    embedding: tuple[float, ...] = ()     # tùy chọn
    embedding_available: bool = False
    created_cycle: int = 0

    def __post_init__(self) -> None:
        text = str(self.description or "").strip()
        if len(text) > _MAX_PREDICTION_LEN:
            text = text[:_MAX_PREDICTION_LEN]
        self.description = text
        self.confidence = clamp01(self.confidence)
        self.embedding = tuple(self.embedding or ())
        self.embedding_available = bool(self.embedding_available and self.embedding)

    @property
    def is_empty(self) -> bool:
        return not self.description.strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "confidence": self.confidence,
            "embedding_available": self.embedding_available,
            "created_cycle": self.created_cycle,
        }


@dataclass(slots=True)
class OpenLoop:
    """Một mạch chưa khép trong tình huống (câu hỏi chưa trả lời, việc dở dang...)."""

    loop_id: str
    description: str = ""
    is_open: bool = True
    expectation_violated: bool = False
    updated_ts: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "loop_id": self.loop_id,
            "description": self.description,
            "is_open": self.is_open,
            "expectation_violated": self.expectation_violated,
            "updated_ts": self.updated_ts,
        }


@dataclass(slots=True)
class PredictionErrorResult:
    """Kết quả đo sai số dự đoán cho một chu kỳ / một candidate."""

    value: float = 0.0          # [0,1]; 0 = khớp, 1 = trái hoàn toàn
    defined: bool = False       # False khi Cold_Start / không percept / chưa có prediction
    degraded: bool = False      # True khi dùng fallback token-overlap
    reason: ErrorReason = "cold_start"

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "defined": self.defined,
            "degraded": self.degraded,
            "reason": self.reason,
        }


@dataclass(slots=True)
class ExpectationViolation:
    """Bản ghi vi phạm kỳ vọng — động cơ của tò mò."""

    expected: str
    observed: str
    prediction_error: float
    cycle: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected": self.expected,
            "observed": self.observed,
            "prediction_error": self.prediction_error,
            "cycle": self.cycle,
        }


@dataclass(slots=True)
class PerceptView:
    """Quan sát tổng hợp của một chu kỳ, rút từ frame.evidence."""

    text: str = ""
    tokens: tuple[str, ...] = ()
    embedding: tuple[float, ...] = ()
    user_activity_score: float = 0.0

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


@dataclass(slots=True)
class SituationModelState:
    """Trạng thái tình huống bền vững, mang qua các chu kỳ."""

    content_thread: str = ""
    current_activity: str = ""
    engagement_trend: EngagementTrend = "on_dinh"
    open_loops: list[OpenLoop] = field(default_factory=list)
    last_prediction: Prediction = field(default_factory=Prediction)
    last_error: PredictionErrorResult = field(default_factory=PredictionErrorResult)
    observed_percept_count: int = 0
    cycle_count: int = 0
    recent_engagement: list[float] = field(default_factory=list)
    last_violation: Optional[ExpectationViolation] = None


@dataclass(slots=True)
class SituationUpdate:
    """Kết quả một lần observe_and_update."""

    error: PredictionErrorResult
    violation: Optional[ExpectationViolation] = None
    state_snapshot: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# 3. Cấu hình
# =============================================================================

@dataclass(slots=True)
class SituationModelConfig:
    """Cấu hình Situation Model.

    Mặc định BẬT: novelty được dẫn dắt bởi prediction error. Khi chưa có embedding
    provider, model chạy ở chế độ fallback token-overlap (degraded) cho tới khi được
    cấp provider. `prediction_error_weight` phải lớn hơn nghiêm ngặt
    `habituation_weight`: vi phạm kỳ vọng là tín hiệu chính, habituation chỉ là số
    hạng phụ.
    """

    enabled: bool = True
    expectation_violation_threshold: float = 0.5
    cold_start_min_percepts: int = 5
    engagement_window: int = 3
    high_prediction_error_threshold: float = 0.65
    salience_floor: float = 0.30
    max_open_loops: int = 100
    prediction_error_weight: float = 1.00
    habituation_weight: float = 0.35

    def normalized(self) -> "SituationModelConfig":
        """Trả bản config đã clamp + ép bất biến trọng số."""

        pe_weight = max(0.0, safe_float(self.prediction_error_weight, 1.0))
        hab_weight = max(0.0, safe_float(self.habituation_weight, 0.35))
        # Bất biến: habituation < prediction_error (nhỏ hơn nghiêm ngặt).
        if hab_weight >= pe_weight:
            hab_weight = pe_weight * 0.5
        return SituationModelConfig(
            enabled=bool(self.enabled),
            expectation_violation_threshold=clamp01(self.expectation_violation_threshold),
            cold_start_min_percepts=max(0, int(self.cold_start_min_percepts)),
            engagement_window=max(1, int(self.engagement_window)),
            high_prediction_error_threshold=clamp01(self.high_prediction_error_threshold),
            salience_floor=clamp01(self.salience_floor),
            max_open_loops=max(1, int(self.max_open_loops)),
            prediction_error_weight=pe_weight,
            habituation_weight=hab_weight,
        )


# =============================================================================
# 4. Observability — SituationLogger
# =============================================================================

class SituationLogger:
    """Ghi prediction vs reality vs error mỗi chu kỳ.

    Thay cho dòng `repetition=1.00` phẳng lì. Mọi thao tác đều được bọc để lỗi log
    không bao giờ làm gián đoạn Cognitive_Cycle.
    """

    def __init__(self, sink: Optional[Any] = None) -> None:
        # sink: object có .info()/.warning(), hoặc None -> giữ trong bộ đệm.
        self._sink = sink
        self.records: list[dict[str, Any]] = []

    def _emit(self, payload: dict[str, Any]) -> None:
        try:
            self.records.append(payload)
            if len(self.records) > 256:
                self.records = self.records[-256:]
            sink = self._sink
            if sink is not None:
                fn = getattr(sink, "info", None)
                if callable(fn):
                    fn("situation_model %r", payload)
        except Exception:
            # Observability không được phép giết chu kỳ.
            pass

    def log_cycle(
        self,
        *,
        prev_prediction: Prediction,
        percept: PerceptView,
        error: PredictionErrorResult,
        cycle: int,
    ) -> None:
        try:
            if prev_prediction.is_empty or error.reason in ("cold_start", "no_prev_prediction"):
                self._emit({
                    "kind": "cycle",
                    "cycle": cycle,
                    "state": "cold_start",
                    "percept": percept.text[:160],
                })
                return
            payload: dict[str, Any] = {
                "kind": "cycle",
                "cycle": cycle,
                "expected": prev_prediction.description[:160],
                "observed": percept.text[:160],
            }
            if error.defined:
                payload["prediction_error"] = round(error.value, 4)
            else:
                payload["prediction_error"] = None
                payload["reason"] = error.reason
            if error.degraded:
                payload["degraded"] = True
                payload["reason"] = error.reason
            self._emit(payload)
        except Exception:
            pass

    def log_violation(self, violation: ExpectationViolation) -> None:
        try:
            self._emit({
                "kind": "expectation_violation",
                "cycle": violation.cycle,
                "expected": violation.expected[:160],
                "observed": violation.observed[:160],
                "prediction_error": round(violation.prediction_error, 4),
            })
        except Exception:
            pass


# =============================================================================
# 5. SituationModel — vòng đời dự đoán → quan sát → sai số
# =============================================================================

class SituationModel:
    """Mô hình tình huống bền vững.

    Vòng đời mỗi chu kỳ (observe_and_update):
        1. quan sát Percept từ frame
        2. đo Prediction_Error so với Prediction của chu kỳ trước
        3. cập nhật trạng thái (open loops, engagement trend)
        4. tạo Prediction mới cho chu kỳ kế

    Attention gọi `prediction_error_for(candidate)` trong cùng chu kỳ; nó so candidate
    với Prediction ĐANG HOẠT ĐỘNG của chu kỳ này (tức prediction của chu kỳ trước),
    không phải prediction mới vừa sinh.
    """

    def __init__(
        self,
        config: Optional[SituationModelConfig] = None,
        *,
        embedding_cache: Optional[EventEmbeddingCache] = None,
        embedding_provider: Optional[Any] = None,
        logger: Optional[SituationLogger] = None,
        knowledge_provider: Optional[Any] = None,
    ) -> None:
        self.config = (config or SituationModelConfig()).normalized()
        self.state = SituationModelState()
        self.embedding_cache = embedding_cache or EventEmbeddingCache()
        self.embedding_provider = embedding_provider
        self.logger = logger or SituationLogger()
        # Hook tùy chọn (Curiosity Tutor): làm giàu mô tả Prediction bằng tri thức đã học.
        # CHỈ đọc claim đã commit; không gọi LLM/backend trong lõi (giữ tất định). None ⇒
        # hành vi SituationModel không đổi.
        self._knowledge_provider = knowledge_provider
        # Prediction đang hoạt động cho chu kỳ hiện tại (carry-over từ chu kỳ trước).
        self._active_prediction: Prediction = Prediction()
        # Cache prediction_error theo candidate trong một chu kỳ (tất định).
        self._pe_cache: dict[str, PredictionErrorResult] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Đưa toàn bộ trạng thái về mặc định trung tính."""

        self.state = SituationModelState()
        self._active_prediction = Prediction()
        self._pe_cache.clear()

    def set_knowledge_provider(self, provider: Any) -> None:
        """Gắn hook làm giàu dự đoán bằng tri thức đã học (Curiosity Tutor). None ⇒ tắt."""

        self._knowledge_provider = provider

    def observe_and_update(self, frame: Any, *, now: Optional[float] = None) -> SituationUpdate:
        """Chạy vòng đời 1 chu kỳ. Tất định, commit-or-rollback."""

        now_ts = safe_float(now, safe_float(getattr(frame, "timestamp", 0.0), 0.0))
        # Prediction đang hoạt động = prediction sinh ở cuối chu kỳ trước.
        active_prediction = self.state.last_prediction
        self._active_prediction = active_prediction
        self._pe_cache.clear()

        percept = self._percept_from_frame(frame)

        # --- Percept rỗng: giữ nguyên state, chỉ tăng cycle_count (Req 8.4) ---
        if percept.is_empty:
            draft = replace(
                self.state,
                cycle_count=self.state.cycle_count + 1,
                last_error=PredictionErrorResult(defined=False, reason="no_percept"),
            )
            self.state = draft
            error = self.state.last_error
            self.logger.log_cycle(
                prev_prediction=active_prediction, percept=percept,
                error=error, cycle=self.state.cycle_count,
            )
            return SituationUpdate(error=error, violation=None, state_snapshot=self.serialize())

        # --- Tính toàn bộ trên bản nháp; chỉ commit ở cuối (Req 8.5) ---
        try:
            error = self._compute_cycle_error(active_prediction, percept)
            new_open_loops = self._update_open_loops(percept, error, now_ts)
            new_trend, new_recent = self._update_engagement(percept, error)
            violation = self._maybe_violation(active_prediction, percept, error)
            new_count = self.state.observed_percept_count + 1
            new_cycle = self.state.cycle_count + 1
            new_prediction = self._make_prediction(percept, new_count, new_cycle)

            draft = replace(
                self.state,
                content_thread=self._derive_content_thread(percept),
                current_activity=percept.text[:_MAX_PREDICTION_LEN],
                engagement_trend=new_trend,
                open_loops=new_open_loops,
                last_prediction=new_prediction,
                last_error=error,
                observed_percept_count=new_count,
                cycle_count=new_cycle,
                recent_engagement=new_recent,
                last_violation=violation or self.state.last_violation,
            )
        except Exception:
            # Lỗi giữa chừng: không cập nhật một phần, giữ nguyên state cũ (Req 8.5).
            raise

        # Commit
        self.state = draft

        self.logger.log_cycle(
            prev_prediction=active_prediction, percept=percept,
            error=error, cycle=self.state.cycle_count,
        )
        if violation is not None:
            self.logger.log_violation(violation)

        return SituationUpdate(
            error=error, violation=violation, state_snapshot=self.serialize(),
        )

    def prediction_error_for(self, candidate: Any) -> PredictionErrorResult:
        """Sai số dự đoán cho một AttentionCandidate, so với prediction đang hoạt động."""

        if not self.config.enabled:
            return PredictionErrorResult(defined=False, reason="cold_start")
        # Cold_Start: chưa đủ percept để tin vào prediction error.
        if self.state.observed_percept_count < self.config.cold_start_min_percepts:
            return PredictionErrorResult(defined=False, reason="cold_start")
        pred = self._active_prediction
        if pred is None or pred.is_empty:
            return PredictionErrorResult(defined=False, reason="no_prev_prediction")

        key = str(getattr(candidate, "fingerprint", "") or getattr(candidate, "evidence_id", "") or id(candidate))
        cached = self._pe_cache.get(key)
        if cached is not None:
            return cached

        text = str(getattr(candidate, "claim", "") or "")
        tokens = tuple(getattr(candidate, "text_tokens", ()) or ())
        if not tokens:
            tokens = tuple(tokenize(text))
        percept = PerceptView(text=text, tokens=tokens, embedding=self._embed(text))
        result = self._compute_error(pred, percept)
        self._pe_cache[key] = result
        return result

    def expose_violation(self) -> Optional[ExpectationViolation]:
        """Vi phạm kỳ vọng gần nhất, cho các tầng downstream đọc."""

        return self.state.last_violation

    def serialize(self) -> dict[str, Any]:
        """Serialize trạng thái sang dict cho debug (Req 7.4)."""

        try:
            return {
                "content_thread": self.state.content_thread,
                "current_activity": self.state.current_activity,
                "engagement_trend": self.state.engagement_trend,
                "open_loops": [loop.to_dict() for loop in self.state.open_loops],
                "last_prediction": self.state.last_prediction.to_dict(),
                "last_error": self.state.last_error.to_dict(),
                "observed_percept_count": self.state.observed_percept_count,
                "cycle_count": self.state.cycle_count,
            }
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Percept extraction
    # ------------------------------------------------------------------

    def _percept_from_frame(self, frame: Any) -> PerceptView:
        """Rút percept tổng hợp từ frame.evidence (dominant + salient claims)."""

        evidence = list(getattr(frame, "evidence", None) or [])
        if not evidence:
            return PerceptView()

        # Lấy evidence mạnh nhất nếu frame hỗ trợ; nếu không, dùng theo thứ tự.
        strongest = getattr(frame, "strongest_evidence", None)
        if callable(strongest):
            try:
                items = strongest(limit=6, min_confidence=0.0)
            except Exception:
                items = evidence[:6]
        else:
            items = evidence[:6]

        claims: list[str] = []
        user_hits = 0
        for item in items:
            claim = str(getattr(item, "claim", "") or "").strip()
            if claim:
                claims.append(claim)
            if str(getattr(item, "source", "") or "") == "user_chat":
                user_hits += 1

        text = " | ".join(claims).strip()
        if not text:
            return PerceptView()
        tokens = tuple(tokenize(text))
        user_activity = clamp01(user_hits / max(1, len(items)))
        return PerceptView(
            text=text[: _MAX_PREDICTION_LEN * 2],
            tokens=tokens,
            embedding=self._embed(text),
            user_activity_score=user_activity,
        )

    # ------------------------------------------------------------------
    # Prediction error
    # ------------------------------------------------------------------

    def _compute_cycle_error(self, prediction: Prediction, percept: PerceptView) -> PredictionErrorResult:
        """Sai số tổng hợp của chu kỳ; bỏ qua nếu chưa có prediction trước."""

        if prediction is None or prediction.is_empty:
            return PredictionErrorResult(defined=False, reason="no_prev_prediction")
        return self._compute_error(prediction, percept)

    def _compute_error(self, prediction: Prediction, percept: PerceptView) -> PredictionErrorResult:
        """Đo sai số: embedding/cosine; fallback token-overlap khi thiếu embedding."""

        pred_vec = _normalize_vector(tuple(prediction.embedding or ()))
        perc_vec = _normalize_vector(tuple(percept.embedding or ()))

        if pred_vec and perc_vec and len(pred_vec) == len(perc_vec):
            sim = _cosine_similarity(pred_vec, perc_vec)
            # pred_vec/perc_vec đã non-empty và cùng chiều, nên sim là cosine thật
            # trong [-1,1] (không còn là sentinel -1.0 do rỗng/lệch chiều).
            if math.isfinite(sim):
                value = clamp01((1.0 - sim) / 2.0)
                return PredictionErrorResult(value=value, defined=True, degraded=False, reason="ok")

        # Fallback token-overlap (degraded).
        reason: ErrorReason = "missing_percept_embedding" if not perc_vec else "missing_prediction_embedding"
        value = self._token_overlap_error(prediction.description, percept)
        return PredictionErrorResult(value=value, defined=True, degraded=True, reason=reason)

    @staticmethod
    def _token_overlap_error(prediction_text: str, percept: PerceptView) -> float:
        a = set(tokenize(prediction_text))
        b = set(percept.tokens) or set(tokenize(percept.text))
        if not a or not b:
            return 1.0
        overlap = len(a & b) / max(1, min(len(a), len(b)))
        return clamp01(1.0 - overlap)

    def _embed(self, text: str) -> tuple[float, ...]:
        """Lấy embedding từ cache/provider; trả () nếu không có."""

        text = str(text or "").strip()
        if not text:
            return ()
        cached = self.embedding_cache.get(text)
        if cached:
            return tuple(cached)
        provider = self.embedding_provider
        if provider is None:
            return ()
        try:
            embed = getattr(provider, "embed", None)
            vector = embed(text) if callable(embed) else provider(text)
        except Exception:
            return ()
        try:
            self.embedding_cache.put(text, vector)
        except Exception:
            pass
        got = self.embedding_cache.get(text)
        return tuple(got) if got else ()

    # ------------------------------------------------------------------
    # State updates
    # ------------------------------------------------------------------

    def _update_open_loops(
        self, percept: PerceptView, error: PredictionErrorResult, now_ts: float,
    ) -> list[OpenLoop]:
        """Cập nhật open loops theo khớp/trái với prediction."""

        loops = [replace(loop) for loop in self.state.open_loops]
        if not error.defined:
            return loops[: self.config.max_open_loops]

        violated = error.value >= self.config.expectation_violation_threshold
        for loop in loops:
            if not loop.is_open:
                continue
            # Loop kỳ vọng khép nhưng percept cho thấy vẫn mở -> giữ mở + đánh dấu.
            if violated:
                loop.expectation_violated = True
                loop.updated_ts = now_ts
            else:
                loop.expectation_violated = False
                loop.updated_ts = now_ts
        return loops[: self.config.max_open_loops]

    def _update_engagement(
        self, percept: PerceptView, error: PredictionErrorResult,
    ) -> tuple[EngagementTrend, list[float]]:
        """Cập nhật Engagement_Trend theo cửa sổ N chu kỳ gần nhất."""

        if not error.defined:
            # Cold_Start / chưa xác định -> giữ ổn định cho tới khi đủ dữ liệu.
            return "on_dinh", list(self.state.recent_engagement)

        recent = list(self.state.recent_engagement)
        recent.append(percept.user_activity_score)
        window = self.config.engagement_window
        if len(recent) > window:
            recent = recent[-window:]

        if len(recent) < 2:
            return "on_dinh", recent

        mid = len(recent) // 2
        first_half = recent[:mid] or recent[:1]
        second_half = recent[mid:]
        avg_first = sum(first_half) / len(first_half)
        avg_second = sum(second_half) / len(second_half)
        delta = avg_second - avg_first
        if delta > 0.05:
            return "tang", recent
        if delta < -0.05:
            return "giam", recent
        return "on_dinh", recent

    def _maybe_violation(
        self, prediction: Prediction, percept: PerceptView, error: PredictionErrorResult,
    ) -> Optional[ExpectationViolation]:
        if not error.defined:
            return None
        if error.value < self.config.expectation_violation_threshold:
            return None
        return ExpectationViolation(
            expected=prediction.description,
            observed=percept.text[:_MAX_PREDICTION_LEN],
            prediction_error=error.value,
            cycle=self.state.cycle_count + 1,
        )

    # ------------------------------------------------------------------
    # Prediction generation
    # ------------------------------------------------------------------

    def _derive_content_thread(self, percept: PerceptView) -> str:
        """Mạch nội dung: giữ thread cũ nếu percept trùng nhiều, ngược lại cập nhật."""

        prev = self.state.content_thread
        if not prev:
            return percept.text[:_MAX_PREDICTION_LEN]
        prev_tokens = set(tokenize(prev))
        overlap = len(prev_tokens & set(percept.tokens))
        if overlap >= 2:
            return prev
        return percept.text[:_MAX_PREDICTION_LEN]

    def _make_prediction(self, percept: PerceptView, observed_count: int, cycle: int) -> Prediction:
        """Sinh Prediction thuần heuristic (tất định) cho chu kỳ kế."""

        activity = percept.text.strip() or self.state.content_thread.strip()
        if activity:
            description = f"Ngài tiếp tục: {activity}"
        else:
            description = "Tiếp tục như hiện tại"

        # Hook tri thức (Curiosity Tutor) — làm giàu dự đoán nếu có claim liên quan.
        # Chỉ đọc state đã commit; provider None hoặc không có claim ⇒ giữ heuristic.
        kp = self._knowledge_provider
        if kp is not None:
            try:
                enriched = kp.enrich(
                    content_thread=self.state.content_thread,
                    percept_text=percept.text,
                )
            except Exception:
                enriched = ""
            if enriched:
                description = str(enriched).strip()

        if len(description) > _MAX_PREDICTION_LEN:
            description = description[:_MAX_PREDICTION_LEN]

        cold_start = observed_count < self.config.cold_start_min_percepts
        confidence = 0.0 if cold_start else clamp01(0.4 + 0.1 * min(5, observed_count))

        embedding = self._embed(description)
        return Prediction(
            description=description,
            confidence=confidence,
            embedding=embedding,
            embedding_available=bool(embedding),
            created_cycle=cycle,
        )


__all__ = [
    "EngagementTrend",
    "ErrorReason",
    "Prediction",
    "OpenLoop",
    "PredictionErrorResult",
    "ExpectationViolation",
    "PerceptView",
    "SituationModelState",
    "SituationUpdate",
    "SituationModelConfig",
    "SituationLogger",
    "SituationModel",
]
