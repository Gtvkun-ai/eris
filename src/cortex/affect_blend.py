# -*- coding: utf-8 -*-
"""
affect_blend.py
===============

Proof-of-concept (CHƯA nối vào pipeline) cho cách biểu diễn *stance* mềm hơn:
thay thang ngưỡng ``if threat>=0.66 ...`` trong ``appraisal._choose_stance`` bằng
một **phân bố mềm trên các điểm hút (attractor)** trong không gian affect, kèm
**quán tính cảm xúc (EMA inertia)**.

Vì sao
------
Cảm xúc người không phải một nhãn rời rạc chọn bằng first-match. Nó là một vùng
pha trộn trong không gian liên tục (core affect → emotion được kiến tạo). Một
người có thể vừa *che chở*, vừa *mệt*, vừa *hơi mềm* cùng lúc; và trạng thái đó
không nhảy giật khi một trục vượt ngưỡng, mà trôi dần (hysteresis).

Cơ chế lõi — DÙNG LẠI ĐƯỢC Ở NHIỀU TẦNG
---------------------------------------
Toàn bộ module quy về MỘT primitive duy nhất: ``soft_assign``.

    điểm quan sát  --(khoảng cách RMS tới mỗi neo)-->  similarity
    similarity     --(softmax theo temperature)----->  phân bố mềm
    phân bố mềm    --(EMA với phân bố trước)--------->  phân bố có quán tính

``blend_stance`` chỉ là một wrapper mỏng của ``soft_assign`` với bộ neo stance.
Cùng primitive này có thể tái dùng cho:
- đọc affect của sự-kiện (chiếu lên các affect-direction prototype),
- gán meaning/intent (đã có ``semantic_prototypes`` đi cùng hướng).

Tức là: ít khái niệm hơn, không thêm dependency. Chỉ ``math`` + ``dataclasses``.

Thiết kế cố ý
-------------
- KHÔNG import gì từ phần còn lại của ``cortex`` để PoC chạy/đo độc lập.
- KHÔNG quyết định hành động. Nó chỉ trả phân bố + tiện ích đọc phân bố đó.
- Giữ ``top()`` trả về một string stance để TƯƠNG THÍCH NGƯỢC với
  ``CognitiveAppraisal.stance`` (argmax của phân bố).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import exp, isfinite, sqrt
from typing import Mapping


# ---------------------------------------------------------------------------
# Không gian affect: đúng các trục mà CognitiveAppraisal đã có.
# valence là trục có dấu [-1, 1]; các trục còn lại [0, 1].
# ---------------------------------------------------------------------------
AFFECT_AXES: tuple[str, ...] = (
    "valence",
    "arousal",
    "certainty",
    "agency",
    "controllability",
    "intimacy",
    "threat",
    "protectiveness",
    "jealousy_lite",
    "amusement",
    "fatigue",
    "tenderness",
)


# Mỗi stance là MỘT HƯỚNG trong không gian affect, chỉ khai báo các trục thật sự
# định nghĩa nó. `grounded` KHÔNG nằm ở đây: nó là trạng thái nền (baseline) thắng
# khi không hướng cảm xúc nào được kích hoạt đủ mạnh (xem grounded_floor).
STANCE_ANCHORS: dict[str, dict[str, float]] = {
    "protective": {"threat": 0.80, "protectiveness": 0.82, "tenderness": 0.40},
    "watchful": {"jealousy_lite": 0.55, "threat": 0.45, "certainty": 0.50},
    "tender_under_cold": {"tenderness": 0.80, "intimacy": 0.72, "valence": 0.30},
    "tired": {"fatigue": 0.78, "arousal": 0.22},
    "dry_playful": {"amusement": 0.70, "valence": 0.40, "threat": 0.10},
    "soft_uncertain": {"certainty": 0.16, "arousal": 0.30, "valence": -0.05},
}

# Tên trạng thái nền.
GROUNDED_STANCE = "grounded"

# Điểm trung tính của không gian affect. Hệ số chiếu đo affect "đi xa neutral bao
# nhiêu theo hướng anchor": ~1 tại anchor, ~0 tại neutral, <0 khi đi ngược.
# certainty trung tính ở 0.5 (không chắc cũng không mơ hồ); các trục còn lại ở 0.
AFFECT_NEUTRAL: dict[str, float] = {"certainty": 0.5}


# Hướng dẫn bề mặt cho từng stance (port từ appraisal._stance_guidance). Ở dạng
# blend, lớp prompt có thể nối top-k hướng dẫn theo trọng số thay vì một câu.
STANCE_GUIDANCE: dict[str, str] = {
    "protective": "speak briefly, concrete first, with guarded care; avoid theatrical alarm.",
    "watchful": "let the line carry mild possessive watchfulness, kept light and non-accusatory.",
    "tender_under_cold": "make the surface restrained while letting warmth show through the wording.",
    "tired": "slow the rhythm and keep the sentence spare.",
    "dry_playful": "allow a small dry aside, but keep it grounded in the scene.",
    "soft_uncertain": "soften claims and avoid inventing motives or details.",
    "grounded": "stay grounded, reserved, and responsive to the strongest cue.",
}


@dataclass(frozen=True, slots=True)
class AffectBlendConfig:
    """Cấu hình cho đường stance dạng blend.

    Chỉ vài knob có nghĩa thay cho hàng chục magic-number ngưỡng cũ:
    - temperature: độ sắc của phân bố stance (nhỏ -> dứt khoát, lớn -> phân vân).
    - inertia: quán tính cảm xúc giữa các turn (cao -> trôi chậm, ít flip-flop).
    - dominant_k / dominant_min_weight: cách chọn top-k stance để dựng guidance.
    - enabled: tắt -> AppraisalEngine quay về _choose_stance cũ.
    """

    temperature: float = 0.18
    inertia: float = 0.6
    dominant_k: int = 2
    dominant_min_weight: float = 0.08
    # Ngưỡng nền cho `grounded`: stance cảm xúc phải kích hoạt (hệ số chiếu) vượt
    # mức này mới thắng grounded. ~0.5 = "đi nửa đường tới anchor".
    grounded_floor: float = 0.5
    enabled: bool = True


DEFAULT_BLEND_CONFIG = AffectBlendConfig()


def _finite(value: object, fallback: float = 0.0) -> float:
    """Ép một giá trị về float hữu hạn; NaN/inf/None -> fallback."""
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    if not isfinite(numeric):
        return fallback
    return numeric


def rms_distance(point: Mapping[str, float], anchor: Mapping[str, float]) -> float:
    """Khoảng cách RMS giữa ``point`` và ``anchor`` TRÊN CÁC TRỤC CỦA ANCHOR.

    Chỉ tính trên các trục mà anchor khai báo, rồi lấy trung bình bình phương.
    Dùng RMS (không phải tổng) để các neo có số trục khác nhau vẫn so được công
    bằng: một neo định nghĩa bằng 2 trục không tự nhiên "gần" hơn neo 3 trục.
    """
    keys = tuple(anchor.keys())
    if not keys:
        return float("inf")
    total = 0.0
    for axis in keys:
        diff = _finite(point.get(axis, 0.0)) - _finite(anchor[axis])
        total += diff * diff
    return sqrt(total / len(keys))


def direction_match(point: Mapping[str, float], anchor: Mapping[str, float], neutral: Mapping[str, float]) -> float:
    """Mức ``point`` kích hoạt hướng ``anchor`` tính từ ``neutral`` — trong [0,1].

    Với mỗi trục của anchor: fill = clamp(m/d, 0, 1) = đã đi bao nhiêu phần đường
    từ neutral tới target theo ĐÚNG chiều (d = target - neutral, m = point - neutral).
    - 1.0 khi point đạt hoặc vượt target (vượt KHÔNG cộng thêm: bão hòa).
    - 0.0 khi point ở neutral hoặc đi NGƯỢC chiều (không phạt âm).
    Activation = trung bình các fill, trọng số theo |d| (trục càng đặc trưng càng nặng).

    Vì sao không dùng hệ số chiếu thô: chiếu thô thưởng cho "đi xa", nên một trục
    chỉ mang sắc thái nhẹ (vd arousal=0.30 ở soft_uncertain) bị một affect arousal
    cao bơm phồng vô lý. Bão hòa khử đúng cái đó: đạt target là đủ "thuộc về" stance.
    """
    num = 0.0
    den = 0.0
    for axis, target in anchor.items():
        n = _finite(neutral.get(axis, 0.0))
        d = _finite(target) - n
        if d == 0.0:
            continue  # trục trùng neutral không phân biệt được gì.
        m = _finite(point.get(axis, n)) - n
        fill = m / d
        fill = 0.0 if fill < 0.0 else (1.0 if fill > 1.0 else fill)
        weight = abs(d)
        num += fill * weight
        den += weight
    if den <= 0.0:
        return 0.0
    return num / den


def _softmax(scores: Mapping[str, float], temperature: float) -> dict[str, float]:
    """Softmax có nhiệt độ. Temperature nhỏ -> phân bố sắc (gần one-hot)."""
    temperature = max(1e-6, float(temperature))
    # Trừ max để ổn định số học.
    top = max(scores.values())
    exps = {name: exp((score - top) / temperature) for name, score in scores.items()}
    denom = sum(exps.values()) or 1.0
    return {name: value / denom for name, value in exps.items()}


def _ema(prev: Mapping[str, float], current: Mapping[str, float], inertia: float) -> dict[str, float]:
    """Blend hai phân bố theo quán tính. inertia=1 -> giữ prev; 0 -> lấy current."""
    inertia = min(1.0, max(0.0, float(inertia)))
    names = set(prev) | set(current)
    blended = {
        name: inertia * _finite(prev.get(name, 0.0)) + (1.0 - inertia) * _finite(current.get(name, 0.0))
        for name in names
    }
    denom = sum(blended.values()) or 1.0
    return {name: value / denom for name, value in blended.items()}


def soft_assign(
    point: Mapping[str, float],
    anchors: Mapping[str, Mapping[str, float]],
    *,
    neutral: Mapping[str, float] = AFFECT_NEUTRAL,
    temperature: float = 0.18,
    prev: Mapping[str, float] | None = None,
    inertia: float = 0.6,
    baseline: tuple[str, float] | None = None,
) -> dict[str, float]:
    """Primitive lõi: gán một điểm vào phân bố mềm trên các hướng, có quán tính.

    similarity = hệ số chiếu của point lên mỗi hướng anchor (từ neutral) ->
    softmax theo temperature -> EMA với phân bố trước (nếu có).

    ``baseline`` là một pseudo-anchor có similarity cố định, đại diện trạng thái
    nền (ví dụ ``("grounded", 0.5)``): chỉ thắng khi không hướng nào kích hoạt đủ.

    Đây là cơ chế dùng chung cho stance / meaning. ``blend_stance`` là wrapper.
    """
    if not anchors and baseline is None:
        return {}
    sims = {name: direction_match(point, anchor, neutral) for name, anchor in anchors.items()}
    if baseline is not None:
        sims[baseline[0]] = float(baseline[1])
    dist = _softmax(sims, temperature)
    if prev:
        dist = _ema(prev, dist, inertia)
    return dist


@dataclass(frozen=True, slots=True)
class StanceBlend:
    """Phân bố mềm trên các stance, kèm tiện ích đọc.

    weights: tên stance -> trọng số (>=0, tổng ~1).
    """

    weights: dict[str, float] = field(default_factory=dict)

    def top(self) -> str:
        """Argmax -> string stance, để tương thích ngược với CognitiveAppraisal.stance."""
        if not self.weights:
            return "grounded"
        return max(self.weights.items(), key=lambda kv: kv[1])[0]

    def dominant(self, k: int = 2, *, min_weight: float = 0.08) -> tuple[tuple[str, float], ...]:
        """Top-k stance vượt ngưỡng tối thiểu, đã sắp giảm dần."""
        ranked = sorted(self.weights.items(), key=lambda kv: kv[1], reverse=True)
        return tuple((name, w) for name, w in ranked[: max(1, k)] if w >= min_weight)

    def entropy(self) -> float:
        """Độ phân vân của trạng thái (0 = dứt khoát, cao = mơ hồ/đa cảm)."""
        from math import log

        acc = 0.0
        for w in self.weights.values():
            if w > 0.0:
                acc -= w * log(w)
        return acc

    def to_dict(self) -> dict[str, float]:
        return {name: round(float(w), 4) for name, w in sorted(self.weights.items(), key=lambda kv: kv[1], reverse=True)}


def blend_stance(
    affect: Mapping[str, float],
    *,
    anchors: Mapping[str, Mapping[str, float]] = STANCE_ANCHORS,
    temperature: float | None = None,
    prev: "StanceBlend | Mapping[str, float] | None" = None,
    inertia: float | None = None,
    config: "AffectBlendConfig | None" = None,
) -> "StanceBlend":
    """Tính phân bố stance mềm từ vector affect, có quán tính tuỳ chọn.

    Parameters
    ----------
    affect:
        Mapping trục->giá trị (các trục của AFFECT_AXES; thiếu trục coi như 0).
    temperature:
        Nhỏ -> phân bố sắc (gần một stance). Lớn -> pha trộn nhiều. Đây là MỘT
        knob duy nhất thay cho hàng chục magic number ngưỡng cũ. None -> lấy từ config.
    prev:
        Phân bố stance của turn trước. Nếu có, áp EMA để tạo quán tính cảm xúc.
    inertia:
        Mức giữ lại trạng thái cũ [0,1]. Cao -> trôi chậm, ít flip-flop. None -> config.
    config:
        AffectBlendConfig để lấy mặc định cho temperature/inertia khi không truyền rời.
    """
    cfg = config or DEFAULT_BLEND_CONFIG
    temp = cfg.temperature if temperature is None else temperature
    iner = cfg.inertia if inertia is None else inertia
    prev_weights = prev.weights if isinstance(prev, StanceBlend) else prev
    dist = soft_assign(
        affect,
        anchors,
        neutral=AFFECT_NEUTRAL,
        temperature=temp,
        prev=prev_weights,
        inertia=iner,
        baseline=(GROUNDED_STANCE, cfg.grounded_floor),
    )
    return StanceBlend(weights=dist)


def guidance_blend(
    blend: "StanceBlend",
    *,
    guidance: Mapping[str, str] = STANCE_GUIDANCE,
    k: int | None = None,
    config: "AffectBlendConfig | None" = None,
) -> str:
    """Nối hướng dẫn bề mặt của top-k stance theo trọng số, cho lớp prompt.

    Trả về dạng: "protective(0.52): ... | tired(0.31): ...".
    Lớp prompt cũ chỉ nhận một câu; cái này cho nó thấy CẢ pha trộn.
    """
    cfg = config or DEFAULT_BLEND_CONFIG
    top_k = cfg.dominant_k if k is None else k
    parts: list[str] = []
    for name, weight in blend.dominant(k=top_k, min_weight=cfg.dominant_min_weight):
        text = guidance.get(name)
        if text:
            parts.append(f"{name}({weight:.2f}): {text}")
    if not parts:
        return guidance.get(blend.top(), guidance["grounded"])
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Event-affect bằng phép chiếu prototype — DÙNG LẠI đúng pattern soft_assign:
# similarity (cosine) -> softmax -> blend các vector affect mục tiêu.
# Thay cho đếm token lexicon trong _event_affect.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AffectDirectionPrototype:
    """Một hướng affect của sự-kiện, mô tả bằng NGHĨA chứ không phải keyword.

    name:    nhãn debug.
    phrases: các câu mô tả nghĩa-cảm-xúc (encoder sẽ biến thành centroid vector).
    affect:  vector affect mục tiêu (valence/tenderness/arousal) khi cảnh khớp.
    """

    name: str
    phrases: tuple[str, ...]
    affect: dict[str, float]


# Bộ prototype mặc định cho affect của sự-kiện. Mô tả tình huống, không liệt kê token.
EVENT_AFFECT_PROTOTYPES: tuple[AffectDirectionPrototype, ...] = (
    AffectDirectionPrototype(
        name="quiet_struggle",
        phrases=(
            "someone is quietly struggling, drained, or having a hard time",
            "the scene shows fatigue, sadness, loneliness, or being overwhelmed",
        ),
        affect={"valence": -0.6, "tenderness": 0.7, "arousal": 0.4},
    ),
    AffectDirectionPrototype(
        name="relief_warmth",
        phrases=(
            "something just went well and there is relief and warmth",
            "a worry resolved, a small win, a calm and pleasant moment",
        ),
        affect={"valence": 0.6, "tenderness": 0.3, "arousal": 0.4},
    ),
    AffectDirectionPrototype(
        name="focus_threat",
        phrases=(
            "a threat to focus or to the ongoing work or goal",
            "pressure, risk, or something that could derail the current task",
        ),
        affect={"valence": -0.4, "tenderness": 0.1, "arousal": 0.6},
    ),
    AffectDirectionPrototype(
        name="bright_excited",
        phrases=(
            "excitement, enthusiasm, a bright and energetic positive moment",
            "celebrating, looking forward to something with eager energy",
        ),
        affect={"valence": 0.7, "tenderness": 0.2, "arousal": 0.7},
    ),
)

_EVENT_AFFECT_KEYS: tuple[str, ...] = ("valence", "tenderness", "arousal")


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    """Cosine similarity; vector rỗng/khác chiều -> 0.0 (không phải -1, để softmax mượt)."""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    nl = sqrt(sum(a * a for a in left))
    nr = sqrt(sum(b * b for b in right))
    if nl <= 0.0 or nr <= 0.0:
        return 0.0
    return dot / (nl * nr)


def project_event_affect(
    event_text: str,
    prototypes: tuple[AffectDirectionPrototype, ...] = EVENT_AFFECT_PROTOTYPES,
    *,
    encode,
    temperature: float = 0.25,
) -> dict[str, float] | None:
    """Chiếu văn bản sự-kiện lên các prototype -> blend vector affect mục tiêu.

    ``encode`` là callable ``str -> vector | None``. Trả về:
    - dict {valence, tenderness, arousal} khi encode được cả event lẫn ít nhất
      một prototype.
    - ``None`` khi encoder không khả dụng / ném / trả rỗng -> caller tự fallback
      (Req 4.6). Hàm này KHÔNG bao giờ ném ra ngoài.

    Cảnh hỗn hợp (vừa pos vừa neg) cho ra vector pha trộn thay vì triệt tiêu về 0,
    vì đây là blend trong không gian affect, không phải phép trừ đếm token.
    """
    text = str(event_text or "").strip()
    if not text or not prototypes:
        return None
    try:
        event_vec = encode(text)
    except Exception:
        return None
    event_vec = _clean_vector(event_vec)
    if not event_vec:
        return None

    sims: dict[str, float] = {}
    affects: dict[str, dict[str, float]] = {}
    for proto in prototypes:
        proto_vec = _encode_prototype(proto, encode)
        if not proto_vec:
            continue
        sims[proto.name] = _cosine(event_vec, proto_vec)
        affects[proto.name] = proto.affect
    if not sims:
        return None

    weights = _softmax(sims, temperature)
    blended = {key: 0.0 for key in _EVENT_AFFECT_KEYS}
    for name, weight in weights.items():
        target = affects[name]
        for key in _EVENT_AFFECT_KEYS:
            blended[key] += weight * _finite(target.get(key, 0.0))
    return blended


def _encode_prototype(proto: AffectDirectionPrototype, encode) -> tuple[float, ...]:
    """Encode centroid của các phrase prototype. Lỗi -> vector rỗng."""
    vectors: list[tuple[float, ...]] = []
    for phrase in proto.phrases:
        try:
            vec = _clean_vector(encode(phrase))
        except Exception:
            vec = ()
        if vec:
            vectors.append(vec)
    if not vectors:
        return ()
    dim = len(vectors[0])
    if any(len(v) != dim for v in vectors):
        return vectors[0]
    return tuple(sum(col) / len(vectors) for col in zip(*vectors))


def _clean_vector(vector) -> tuple[float, ...]:
    """Ép về tuple float hữu hạn; bất kỳ giá trị xấu nào -> rỗng (an toàn)."""
    if vector is None:
        return ()
    try:
        out = tuple(float(v) for v in vector)
    except (TypeError, ValueError):
        return ()
    if not out or any(not isfinite(v) for v in out):
        return ()
    return out
