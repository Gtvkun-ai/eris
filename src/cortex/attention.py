import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from .contracts import AttentionCandidate, CognitiveBroadcast, PerceptEvent

'''File attention.py là “bộ chọn chú ý” (attention selector): nó nhận một danh sách PerceptEvent 
(các tín hiệu như user_message, active_window, recent_event, vision_fact…), chấm điểm từng cái, 
lấy top-N, rồi tạo ra một CognitiveBroadcast (tóm tắt tín hiệu nổi bật nhất để downstream dùng)'''

'''
novelty             độ mới
specificity         độ cụ thể
user_relevance      liên quan tới user
risk                rủi ro/lỗi/tài nguyên
social_charge       tín hiệu xã hội/chat
recency             độ gần đây
memory_resonance    cộng hưởng memory
personality_bias    tín hiệu tính cách/tâm trạng/continuity
'''
def _bounded(value: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def _normalize_tokens(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", (text or "").lower())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.replace("\u0111", "d")
    normalized = re.sub(r"[^a-z0-9_\s]+", " ", normalized)
    stop_words = {
        "a",
        "an",
        "and",
        "at",
        "cua",
        "dang",
        "for",
        "in",
        "is",
        "la",
        "of",
        "on",
        "the",
        "to",
        "toi",
        "trong",
        "va",
    }
    return {token for token in normalized.split() if len(token) >= 3 and token not in stop_words}


def _normalize_token_sequence(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKD", (text or "").lower())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.replace("\u0111", "d")
    normalized = re.sub(r"[^a-z0-9_\s]+", " ", normalized)
    stop_words = {
        "a",
        "an",
        "and",
        "at",
        "cua",
        "dang",
        "for",
        "in",
        "is",
        "la",
        "of",
        "on",
        "the",
        "to",
        "toi",
        "trong",
        "va",
    }
    return tuple(token for token in normalized.split() if len(token) >= 3 and token not in stop_words)


def _token_bigrams(tokens: Sequence[str]) -> set[tuple[str, str]]:
    return set(zip(tokens, tokens[1:])) if len(tokens) >= 2 else set()


def _character_trigrams(text: str) -> Counter[str]:
    normalized = _normalize_for_bias(text).replace(" ", "_")
    if len(normalized) < 3:
        return Counter()
    return Counter(normalized[index : index + 3] for index in range(len(normalized) - 2))


def _cosine_counter(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    shared = set(left) & set(right)
    numerator = sum(left[key] * right[key] for key in shared)
    left_norm = sum(value * value for value in left.values()) ** 0.5
    right_norm = sum(value * value for value in right.values()) ** 0.5
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return _bounded(numerator / (left_norm * right_norm))


def _cosine_dense(left: Sequence[float], right: Sequence[float]) -> float:
    size = min(len(left), len(right))
    if size <= 0:
        return 0.0
    numerator = sum(float(left[index]) * float(right[index]) for index in range(size))
    left_norm = sum(float(value) * float(value) for value in left[:size]) ** 0.5
    right_norm = sum(float(value) * float(value) for value in right[:size]) ** 0.5
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return _bounded(numerator / (left_norm * right_norm))


def _normalize_for_bias(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", (text or "").lower())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.replace("\u0111", "d")
    normalized = re.sub(r"[^a-z0-9_#\s]+", " ", normalized)
    return " ".join(normalized.split())


def _contains_normalized_phrase(text: str, phrase: str) -> bool:
    """Match a normalized token or phrase with real token boundaries.

    This avoids substring false positives such as matching ``sad`` inside another
    word, while still supporting multi-token Vietnamese phrases after
    normalization, e.g. ``tin nhan`` or ``chua xong``.
    """
    normalized_text = _normalize_for_bias(text)
    normalized_phrase = _normalize_for_bias(phrase)
    if not normalized_text or not normalized_phrase:
        return False
    return re.search(rf"(?<!\w){re.escape(normalized_phrase)}(?!\w)", normalized_text) is not None


def _contains_any_normalized_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    #Đây là kỹ thuật giúp hàm tránh được lỗi substring false positive (lỗi nhận diện sai chuỗi con).
    '''
    re.escape(normalized_phrase): Hàm này vô hiệu hóa mọi ký tự đặc biệt có trong cụm từ (như dấu . hay *). Đảm bảo Regex coi cụm từ đó như một chuỗi văn bản thuần túy.
    (?<!\\w) (Negative Lookbehind): Đảm bảo ngay trước cụm từ cần tìm KHÔNG CÓ một ký tự chữ cái, số, hoặc dấu gạch dưới (\\w).
    (?!\\w) (Negative Lookahead): Đảm bảo ngay sau cụm từ cần tìm KHÔNG CÓ một ký tự chữ cái, số, hoặc dấu gạch dưới.
    '''
    return any(_contains_normalized_phrase(text, phrase) for phrase in phrases)


NEGATION_CUES = {
    "aint",
    "arent",
    "cannot",
    "cant",
    "chang",
    "chua",
    "didnt",
    "doesnt",
    "dont",
    "isnt",
    "ko",
    "khong",
    "never",
    "no",
    "not",
    "nothing",
    "without",
}
NEGATION_HELPERS = {"anymore", "co", "con", "he", "phai", "really", "that", "the", "very"}
NEGATION_BREAKERS = {"but", "however", "ma", "nhung", "song", "though", "yet"}


def _phrase_token_spans(tokens: Sequence[str], phrase: str) -> tuple[tuple[int, int], ...]:
    phrase_tokens = tuple(_normalize_for_bias(phrase).split())
    if not phrase_tokens or len(phrase_tokens) > len(tokens):
        return ()
    width = len(phrase_tokens)
    return tuple(
        (index, index + width)
        for index in range(len(tokens) - width + 1)
        if tuple(tokens[index : index + width]) == phrase_tokens
    )


def _is_negated_span(tokens: Sequence[str], start: int) -> bool:
    window = tokens[max(0, start - 4) : start]
    if not window:
        return False
    if any(token in NEGATION_BREAKERS for token in window):
        last_breaker = max(index for index, token in enumerate(window) if token in NEGATION_BREAKERS)
        window = window[last_breaker + 1 :]
    if not window:
        return False
    for index, token in enumerate(window):
        if token not in NEGATION_CUES:
            continue
        tail = window[index + 1 :]
        return len(tail) <= 2 or all(item in NEGATION_HELPERS for item in tail)
    return False


def _contains_affirmed_normalized_phrase(text: str, phrase: str) -> bool:
    tokens = tuple(_normalize_for_bias(text).split())
    for start, _end in _phrase_token_spans(tokens, phrase):
        if not _is_negated_span(tokens, start):
            return True
    return False


def _contains_any_affirmed_normalized_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    return any(_contains_affirmed_normalized_phrase(text, phrase) for phrase in phrases)


def _normalized_text_with_evidence(percept: PerceptEvent) -> str:
    return _normalize_for_bias(
        " ".join(
            (
                str(getattr(percept, "content", "") or ""),
                " ".join(str(item) for item in (getattr(percept, "evidence", ()) or ())),
                str(getattr(percept, "source", "") or ""),
                str(getattr(percept, "novelty_hint", "") or ""),
            )
        )
    )

# AttentionScoringProfile là một cấu trúc dữ liệu lưu trữ các “soft data priors” 
# (các giả định mềm dựa trên dữ liệu) cho bộ chấm điểm chú ý. Nó có hai bảng:
#  kind_priors và hint_priors, lưu trữ các điểm số trung bình cho từng loại tín hiệu
#  (kind) và từng gợi ý độ mới (novelty_hint).
@dataclass(slots=True)
class AttentionScoringProfile:
    """Soft data priors for the attention scorer."""

    kind_priors: dict[str, dict[str, float]] = field(default_factory=dict)
    hint_priors: dict[str, dict[str, float]] = field(default_factory=dict)

    @classmethod
    def from_observations(
        cls,
        observations: Iterable[Mapping[str, object]],
    ) -> "AttentionScoringProfile":
        kind_totals: dict[str, Counter[str]] = {}
        hint_totals: dict[str, Counter[str]] = {}
        kind_counts: Counter[str] = Counter()
        hint_counts: Counter[str] = Counter()

        for observation in observations:
            kind = str(observation.get("kind") or observation.get("label") or "")
            hint = str(observation.get("novelty_hint") or "")
            raw_parts = observation.get("score_parts") or {}
            if not isinstance(raw_parts, Mapping):
                continue
            parts = {
                str(key): _bounded(float(value))
                for key, value in raw_parts.items()
                if isinstance(value, int | float)
            }
            if not parts:
                continue
            if kind:
                kind_totals.setdefault(kind, Counter()).update(parts)
                kind_counts[kind] += 1
            if hint:
                hint_totals.setdefault(hint, Counter()).update(parts)
                hint_counts[hint] += 1

        return cls(
            kind_priors={
                kind: {key: total / max(1, kind_counts[kind]) for key, total in totals.items()}
                for kind, totals in kind_totals.items()
            },
            hint_priors={
                hint: {key: total / max(1, hint_counts[hint]) for key, total in totals.items()}
                for hint, totals in hint_totals.items()
            },
        )

    def blended_parts(
        self,
        parts: Mapping[str, float],
        *,
        kind: str,
        novelty_hint: str,
        strength: float,
    ) -> dict[str, float]:
        strength = _bounded(strength, maximum=0.65)
        if strength <= 0.0:
            return dict(parts)

        priors: dict[str, float] = {}
        for source, source_weight in (
            (self.hint_priors.get(novelty_hint, {}), 0.45),
            (self.kind_priors.get(kind, {}), 0.55),
        ):
            for key, value in source.items():
                priors[key] = priors.get(key, 0.0) + (_bounded(value) * source_weight)

        if not priors:
            return dict(parts)
        return {
            key: _bounded((float(value) * (1.0 - strength)) + (priors.get(key, value) * strength))
            for key, value in parts.items()
        }


class AttentionWorkspace:
    SCORE_KEYS = (
        "novelty",
        "specificity",
        "user_relevance",
        "risk",
        "social_charge",
        "recency",
        "memory_resonance",
        "personality_bias",
    )
    WEIGHTS = {
        "novelty": 0.16,
        "specificity": 0.14,
        "user_relevance": 0.18,
        "risk": 0.14,
        "social_charge": 0.10,
        "recency": 0.08,
        "memory_resonance": 0.08,
        "personality_bias": 0.12,
    }
    HARD_RISK_TERMS = (
        "traceback",
        "exception",
        "crash",
        "fatal",
        "segmentation fault",
        "out of memory",
        "oom",
        "failed to start",
        "process died",
        "unhandled",
    )
    SOFT_RISK_TERMS = (
        "error",
        "failed",
        "failure",
        "warning",
        "loi",
        "lỗi",
        "bug",
    )
    RESOURCE_RISK_TERMS = (
        "cpu",
        "gpu",
        "ram",
        "memory",
        "disk",
        "temperature",
        "overheat",
        "lag",
        "freeze",
        "stutter",
    )
    USER_DISCUSSION_HINTS = (
        "la gi",
        "là gì",
        "sao",
        "tai sao",
        "tại sao",
        "nghia la",
        "nghĩa là",
        "fix",
        "sua",
        "sửa",
        "debug",
        "giai thich",
        "giải thích",
        "hoi",
        "hỏi",
        "noi ve",
        "nói về",
    )
    SOCIAL_TERMS = (
        "chat",
        "discord",
        "dm",
        "mail",
        "message",
        "messenger",
        "slack",
        "zalo",
        "tin nhan",
        "tin nhắn",
    )
    PERSONALITY_BIAS_TERMS = {
        "hesitation": (
            "hesitation",
            "hesitant",
            "hover",
            "hovering",
            "pause",
            "paused",
            "pausing",
            "stalled",
            "stuck",
            "khung lai",
            "luong lu",
            "ngap ngung",
        ),
        "mood_shift": (
            "angry",
            "rage",
            "resigned",
            "sigh",
            "heavy_sigh",
            "tired",
            "sad",
            "stress",
            "buc",
            "buon",
            "cam chiu",
            "met",
        ),
        "avoidance": (
            "avoid",
            "avoidance",
            "hiding",
            "minimize",
            "minimizing",
            "panic",
            "fragmented",
            "absent",
            "switching",
            "tranh",
        ),
        "continuity": (
            "again",
            "repeat",
            "repeated",
            "resume",
            "continuity",
            "memory",
            "unresolved",
            "loop",
            "momentum",
            "lap lai",
        ),
        "emotional_undertone": (
            "attachment",
            "lonely",
            "connection",
            "voice_call",
            "message",
            "social",
            "fear",
            "quiet",
            "co don",
            "tam trang",
        ),
        "unfinished_intention": (
            "unfinished",
            "intention",
            "draft",
            "deleting",
            "half",
            "blank",
            "no_edits",
            "no_typing",
            "typing_and_deleting",
            "hovering_voice_call",
            "dang do",
            "chua xong",
        ),
    }

    CURRENT_SIGNAL_LABELS = {
        "user_message",
        "user_force_speak",
        "vision_fact",
        "resource_pressure",
        "norm_deviation",
        "cognitive_attractor",
        "substrate_disturbance",
        "persistent_goal",
        "recent_event",
        "evidence",
    }

    def __init__(
        self,
        *,
        broadcast_threshold: float = 0.50,
        secondary_margin: float = 0.14,
        max_candidates: int = 6,
        max_winners: int = 3,
        scoring_profile: AttentionScoringProfile | Mapping[str, object] | None = None,
        learned_profile_strength: float = 0.22,
        memory_embedding_fn: Callable[[str], Sequence[float]] | None = None,
    ):
        self.broadcast_threshold = broadcast_threshold
        self.secondary_margin = secondary_margin
        self.max_candidates = max_candidates
        self.max_winners = max_winners
        self.scoring_profile = self._coerce_scoring_profile(scoring_profile)
        self.learned_profile_strength = _bounded(learned_profile_strength, maximum=0.65)
        self.memory_embedding_fn = memory_embedding_fn

    def _coerce_scoring_profile(
        self,
        scoring_profile: AttentionScoringProfile | Mapping[str, object] | None,
    ) -> AttentionScoringProfile | None:
        if scoring_profile is None:
            return None
        if isinstance(scoring_profile, AttentionScoringProfile):
            return scoring_profile
        raw_kind_priors = scoring_profile.get("kind_priors", {})
        raw_hint_priors = scoring_profile.get("hint_priors", {})
        return AttentionScoringProfile(
            kind_priors=self._coerce_prior_table(raw_kind_priors),
            hint_priors=self._coerce_prior_table(raw_hint_priors),
        )

    # Hàm _coerce_prior_table nhận một đối tượng raw_table và chuyển đổi nó thành một bảng priors có cấu trúc đúng. Nó kiểm tra xem raw_table có phải là một Mapping hay không, sau đó duyệt qua các mục của raw_table để xây dựng một bảng mới chỉ chứa các giá trị số hợp lệ (int hoặc float) được giới hạn trong khoảng từ 0.0 đến 1.0 bằng cách sử dụng hàm _bounded.
    def _coerce_prior_table(self, raw_table: object) -> dict[str, dict[str, float]]:
        if not isinstance(raw_table, Mapping):
            return {}
        table: dict[str, dict[str, float]] = {}
        for raw_key, raw_parts in raw_table.items():
            if not isinstance(raw_parts, Mapping):
                continue
            parts: dict[str, float] = {}
            for raw_part_key, raw_value in raw_parts.items():
                if isinstance(raw_value, int | float):
                    parts[str(raw_part_key)] = _bounded(float(raw_value))
            if parts:
                table[str(raw_key)] = parts
        return table

    # Hàm learn_from_observations nhận một iterable các quan sát (observations), mỗi quan sát là một mapping chứa thông tin về kind, novelty_hint, và score_parts. Nó tạo ra một AttentionScoringProfile mới từ các quan sát này, sau đó kết hợp nó với scoring_profile hiện tại của AttentionWorkspace bằng cách sử dụng một tỷ lệ học tập (learning_rate) để điều chỉnh mức độ ảnh hưởng của các quan sát mới so với kiến thức hiện có.
    def learn_from_observations(
        self,
        observations: Iterable[Mapping[str, object]],
        *,
        learning_rate: float = 0.18,
    ) -> AttentionScoringProfile:
        learned = AttentionScoringProfile.from_observations(observations) #Tạo một AttentionScoringProfile mới từ các quan sát đầu vào.
        learning_rate = _bounded(learning_rate, maximum=0.65) #Đảm bảo learning_rate nằm trong khoảng từ 0.0 đến 0.65 để tránh ảnh hưởng quá mức của các quan sát mới.
        if self.scoring_profile is None:
            self.scoring_profile = learned
            return learned

        # Kết hợp kind_priors và hint_priors của scoring_profile hiện tại với learned bằng cách sử dụng hàm _merge_prior_tables, điều chỉnh theo learning_rate để tạo ra một bảng priors mới phản ánh cả kiến thức hiện có và thông tin mới học được.
        self.scoring_profile.kind_priors = self._merge_prior_tables(
            self.scoring_profile.kind_priors,
            learned.kind_priors,
            learning_rate=learning_rate,
        )
        self.scoring_profile.hint_priors = self._merge_prior_tables(
            self.scoring_profile.hint_priors,
            learned.hint_priors,
            learning_rate=learning_rate,
        )
        return self.scoring_profile

    # Hàm _merge_prior_tables nhận hai bảng priors (old_table và new_table) và một tỷ lệ học tập (learning_rate), sau đó kết hợp chúng để tạo ra một bảng mới phản ánh cả kiến thức hiện có và thông tin mới học được.
    def _merge_prior_tables(
        self,
        old_table: Mapping[str, Mapping[str, float]],
        new_table: Mapping[str, Mapping[str, float]],
        *,
        learning_rate: float,
    ) -> dict[str, dict[str, float]]:
        merged = {key: dict(parts) for key, parts in old_table.items()}
        for key, new_parts in new_table.items():
            old_parts = merged.get(key, {})
            combined = dict(old_parts)
            for part_key, new_value in new_parts.items():
                old_value = old_parts.get(part_key, new_value)
                combined[part_key] = _bounded(
                    (float(old_value) * (1.0 - learning_rate)) + (float(new_value) * learning_rate)
                )
            merged[key] = combined
        return merged

    def select(
        self,
        percepts: tuple[PerceptEvent, ...],
        *,
        channel: str = "",
        snapshot=None,
        user_text: str = "",
        long_term_memory: tuple[str, ...] | list[str] = (),
    ) -> tuple[tuple[AttentionCandidate, ...], CognitiveBroadcast]:
        candidates = self.rank(
            percepts,
            channel=channel,
            snapshot=snapshot,
            user_text=user_text,
            long_term_memory=long_term_memory,
        )
        return candidates, self.build_broadcast(candidates)

    def rank(
        self,
        percepts: tuple[PerceptEvent, ...],
        *,
        channel: str = "",
        snapshot=None,
        user_text: str = "",
        long_term_memory: tuple[str, ...] | list[str] = (),
    ) -> tuple[AttentionCandidate, ...]:
        candidates = [
            self.score_event(
                percept,
                channel=channel,
                snapshot=snapshot,
                user_text=user_text,
                long_term_memory=long_term_memory,
            )
            for percept in percepts
        ]
        candidates.sort(key=lambda item: item.score, reverse=True)
        return tuple(candidates[: self.max_candidates])

    def build_broadcast(self, candidates: tuple[AttentionCandidate, ...]) -> CognitiveBroadcast:
        if not candidates:
            return CognitiveBroadcast(reason="attention_workspace:no_percepts")

        current_winners = tuple(
            candidate
            for candidate in candidates
            if candidate.label in self.CURRENT_SIGNAL_LABELS and candidate.score >= self.broadcast_threshold
        )
        pool = current_winners if current_winners else candidates
        top = pool[0]
        winners: list[AttentionCandidate] = []
        for candidate in pool:
            if candidate.label == "cycle_channel":
                continue
            if candidate.score < self.broadcast_threshold:
                continue
            if top.score - candidate.score > self.secondary_margin:
                continue
            winners.append(candidate)
            if len(winners) >= self.max_winners:
                break

        if not winners:
            return CognitiveBroadcast(
                label="low_salience",
                content="",
                score=top.score,
                source=top.source,
                reason=(
                    "attention_workspace:top_below_threshold; "
                    f"top={top.label}:{top.score:.2f}"
                ),
            )

        primary = winners[0]
        return CognitiveBroadcast(
            label=primary.label,
            content=" | ".join(item.content for item in winners),
            score=primary.score,
            source=primary.source,
            reason=(
                "attention_workspace:winners="
                + ",".join(f"{item.label}:{item.score:.2f}" for item in winners)
            ),
            evidence=tuple(dict.fromkeys(item for winner in winners for item in winner.evidence))[:6],
            items=tuple(winners),
        )

    def score_event(
        self,
        percept: PerceptEvent,
        *,
        channel: str = "",
        snapshot=None,
        user_text: str = "",
        long_term_memory: tuple[str, ...] | list[str] = (),
    ) -> AttentionCandidate:
        parts = {
            "novelty": self._score_novelty(percept), #Đánh giá độ mới của tín hiệu.
            "specificity": self._score_specificity(percept), #Đánh giá độ cụ thể.
            "user_relevance": self._score_user_relevance(
                percept,
                channel=channel,
                snapshot=snapshot,
                user_text=user_text,
            ),
            "risk": self._score_risk(percept),
            "social_charge": self._score_social_charge(percept, snapshot=snapshot),
            "recency": self._score_recency(percept),
            "memory_resonance": self._score_memory_resonance(percept, long_term_memory),
            "personality_bias": self._score_personality_bias(percept, snapshot=snapshot),
        }
        if self.scoring_profile is not None:
            parts = self.scoring_profile.blended_parts(
                parts,
                kind=percept.kind,
                novelty_hint=percept.novelty_hint,
                strength=self.learned_profile_strength,
            )
        raw_score = sum(parts[key] * self.WEIGHTS[key] for key in self.SCORE_KEYS)
        confidence_scale = 0.75 + 0.25 * _bounded(percept.confidence, minimum=0.05, maximum=1.0)
        score = _bounded(raw_score * confidence_scale)
        reason = "; ".join(f"{key}={parts[key]:.2f}" for key in self.SCORE_KEYS)
        return AttentionCandidate(
            label=percept.kind,
            content=percept.content,
            score=score,
            source=percept.source,
            reason=reason,
            evidence=percept.evidence,
            privacy_level=percept.privacy_level,
            novelty_hint=percept.novelty_hint,
            score_parts={key: round(parts[key], 3) for key in self.SCORE_KEYS},
        )

    def _score_novelty(self, percept: PerceptEvent) -> float:
        hint = (percept.novelty_hint or "").lower()
        if hint in {"direct_user_input", "explicit_request"}:
            return 1.0
        if hint in {"input_disturbance"} or percept.kind == "substrate_disturbance":
            return 0.74
        if hint in {"new_screen_fact", "threshold_crossed"}:
            return 0.92
        if hint in {"baseline_deviation"}:
            return 0.84
        if hint in {"cognitive_attractor"} or percept.kind == "cognitive_attractor":
            return 0.92
        if hint in {"cognitive_momentum"} or percept.kind == "cognitive_momentum":
            return 0.86
        if hint in {"persistent_goal"} or percept.kind == "persistent_goal":
            return 0.80
        if hint in {"presence_background"} or percept.kind == "social_presence_event":
            return 0.18
        if hint in {"session_resume"} or percept.kind == "session_ritual":
            return 0.38
        if hint in {"concrete_telemetry", "duration_threshold"}:
            return 0.72
        if hint in {"screen_fact"}:
            return 0.66
        if hint in {"cached_screen_fact", "repeated_screen_fact"}:
            return 0.34
        if hint in {"routine_telemetry", "ambient_context", "cycle_marker", "none"}:
            return 0.16
        return 0.30

    #Event có evidence, có số, có dạng vision_fact, resource_pressure, norm_deviation sẽ được tăng điểm.
    def _score_specificity(self, percept: PerceptEvent) -> float:
        if percept.kind == "cycle_channel":
            return 0.05
        if percept.kind == "social_presence_event":
            return 0.18
        if percept.kind == "session_ritual":
            return 0.32
        if percept.kind == "cognitive_attractor":
            score = 0.74
            if percept.evidence:
                score += 0.12
            if "topic=" in percept.content or "loop=" in percept.content:
                score += 0.08
            return _bounded(score)
        if percept.kind == "cognitive_momentum":
            score = 0.62
            if percept.evidence:
                score += 0.12
            if "topic=" in percept.content or "thought=" in percept.content:
                score += 0.08
            return _bounded(score)
        if percept.kind == "persistent_goal":
            score = 0.66
            if percept.evidence:
                score += 0.12
            if "goal=" in percept.content:
                score += 0.08
            return _bounded(score)
        if percept.kind == "substrate_disturbance":
            return 0.50 + (0.12 if percept.evidence else 0.0)
        if percept.kind in {"active_window", "focus_context"}:
            return 0.18
        tokens = _normalize_tokens(percept.content)
        score = 0.25 + min(0.45, len(tokens) * 0.045)
        if percept.evidence:
            score += 0.12
        if any(char.isdigit() for char in percept.content):
            score += 0.08
        if percept.kind == "vision_fact":
            score += 0.18
        elif percept.kind == "resource_pressure":
            score += 0.10
        elif percept.kind == "norm_deviation":
            score += 0.10
        return _bounded(score)

    #Đánh giá liên quan tới người dùng.
    def _score_user_relevance(self, percept: PerceptEvent, *, channel: str, snapshot=None, user_text: str = "") -> float:
        if percept.kind in {"user_message", "user_force_speak"}:
            return 1.0
        if percept.kind == "substrate_disturbance":
            return 0.72
        if percept.kind == "cognitive_attractor":
            return 0.90
        if percept.kind == "cognitive_momentum":
            return 0.82
        if percept.kind == "persistent_goal":
            return 0.86
        if percept.kind == "social_presence_event":
            return 0.20
        if percept.kind == "session_ritual":
            return 0.38
        if channel in {"chat", "force_speak"} and percept.kind in {"vision_fact", "recent_event", "evidence"}:
            return 0.68
        if percept.kind == "resource_pressure":
            return 0.70
        if percept.kind == "vision_fact":
            return 0.70
        if percept.kind == "norm_deviation":
            return 0.45
        if percept.kind in {"recent_event", "evidence"}:
            return 0.50
        if percept.kind in {"active_window", "focus_context"}:
            return 0.18

        content_tokens = _normalize_tokens(percept.content)
        user_tokens = _normalize_tokens(user_text)
        if content_tokens and user_tokens:
            overlap = len(content_tokens & user_tokens) / max(1, len(user_tokens))
            return _bounded(0.30 + overlap * 0.55)
        return 0.25

    def _score_risk(self, percept: PerceptEvent) -> float:
        text = _normalized_text_with_evidence(percept)
        content_only = _normalize_for_bias(percept.content)

        if percept.kind == "resource_pressure":
            return 0.95
        if percept.kind == "cognitive_attractor":
            return 0.10
        if percept.kind == "cognitive_momentum":
            return 0.08
        if percept.kind == "persistent_goal":
            return 0.06
        if percept.kind == "social_presence_event":
            return 0.02
        if percept.kind == "session_ritual":
            return 0.02

        has_hard_risk = _contains_any_normalized_phrase(text, self.HARD_RISK_TERMS)
        has_soft_risk = _contains_any_normalized_phrase(text, self.SOFT_RISK_TERMS)
        has_resource_risk = _contains_any_normalized_phrase(text, self.RESOURCE_RISK_TERMS)
        user_is_discussing_risk = (
            percept.kind in {"user_message", "user_force_speak"}
            and (has_hard_risk or has_soft_risk or has_resource_risk)
            and _contains_any_normalized_phrase(content_only, self.USER_DISCUSSION_HINTS)
        )

        # User hỏi hoặc nói về lỗi thì là chủ đề cần chú ý, không phải emergency.
        if user_is_discussing_risk:
            if has_hard_risk:
                return 0.48
            if has_soft_risk or has_resource_risk:
                return 0.34

        # Substrate disturbance đã là nhiễu runtime, nên hard evidence mới nâng mạnh.
        if percept.kind == "substrate_disturbance":
            if has_hard_risk:
                return 0.70
            if has_soft_risk or has_resource_risk:
                return 0.34
            return 0.12

        # Vision/recent/evidence là nơi dễ phản ánh lỗi thật trên màn hình/log.
        if percept.kind in {"vision_fact", "recent_event", "evidence", "norm_deviation"}:
            if has_hard_risk:
                return 0.76
            if has_resource_risk:
                return 0.58
            if has_soft_risk:
                return 0.46

        if has_hard_risk:
            return 0.64
        if has_resource_risk:
            return 0.42
        if has_soft_risk:
            return 0.32
        if percept.kind == "idle_state" and _contains_normalized_phrase(text, "600"):
            return 0.42
        return 0.05

    #Đánh giá tín hiệu xã hội: chat, message, Discord, Zalo, mail...
    #Nếu active window là communication hoặc content có từ liên quan nhắn tin thì tăng điểm.
    def _score_social_charge(self, percept: PerceptEvent, *, snapshot=None) -> float:
        normalized = _normalize_for_bias(percept.content)
        kind = str(getattr(snapshot, "active_window_kind", "") or "")
        if percept.kind == "user_message":
            return 0.70
        if percept.kind == "substrate_disturbance":
            return 0.42
        if percept.kind == "cognitive_attractor":
            return 0.34
        if percept.kind == "cognitive_momentum":
            return 0.30
        if percept.kind == "persistent_goal":
            return 0.32
        if percept.kind == "social_presence_event":
            return 0.16
        if percept.kind == "session_ritual":
            return 0.20
        if kind == "communication":
            return 0.42
        if _contains_any_normalized_phrase(normalized, self.SOCIAL_TERMS):
            return 0.54
        return 0.05

    #Đánh giá độ gần đây. Tín hiệu mới, user input, threshold crossed sẽ cao. Tín hiệu ambient/routine sẽ thấp.
    def _score_recency(self, percept: PerceptEvent) -> float:
        hint = (percept.novelty_hint or "").lower()
        if hint in {"direct_user_input", "explicit_request", "new_screen_fact", "threshold_crossed"}:
            return 0.90
        if hint in {"input_disturbance"} or percept.kind == "substrate_disturbance":
            return 0.78
        if hint in {"baseline_deviation"}:
            return 0.82
        if hint in {"cognitive_attractor"} or percept.kind == "cognitive_attractor":
            return 0.88
        if hint in {"cognitive_momentum"} or percept.kind == "cognitive_momentum":
            return 0.84
        if hint in {"persistent_goal"} or percept.kind == "persistent_goal":
            return 0.78
        if hint in {"presence_background"} or percept.kind == "social_presence_event":
            return 0.22
        if hint in {"session_resume"} or percept.kind == "session_ritual":
            return 0.42
        if hint in {"concrete_telemetry", "duration_threshold", "screen_fact"}:
            return 0.72
        if hint in {"cached_screen_fact", "repeated_screen_fact"}:
            return 0.34
        if hint in {"ambient_context", "routine_telemetry", "cycle_marker"}:
            return 0.18
        return 0.35

    #Nó normalize token rồi tính overlap với tối đa 12 memory gần nhất. Một số memory layer có trọng số khác nhau:
    def _score_memory_resonance(
        self,
        percept: PerceptEvent,
        long_term_memory: tuple[str, ...] | list[str],
    ) -> float:
        content_text = " ".join((percept.content, *percept.evidence))
        content_tokens = set(_normalize_tokens(content_text))
        content_sequence = _normalize_token_sequence(content_text)
        if not content_tokens and not _normalize_for_bias(content_text):
            return 0.0
        content_bigrams = _token_bigrams(content_sequence)
        content_trigrams = _character_trigrams(content_text)
        content_embedding = self._memory_embedding(content_text)

        best = 0.0
        recent_memories = tuple(long_term_memory or ())[-32:]
        for reverse_index, raw_memory in enumerate(reversed(recent_memories)):
            memory = str(raw_memory or "")
            memory_tokens = set(_normalize_tokens(memory))
            memory_sequence = _normalize_token_sequence(memory)
            if not memory_tokens and not _normalize_for_bias(memory):
                continue

            overlap = len(content_tokens & memory_tokens)
            containment = overlap / max(3, min(len(content_tokens), len(memory_tokens), 18))
            jaccard = overlap / max(1, len(content_tokens | memory_tokens))
            bigram_overlap = content_bigrams & _token_bigrams(memory_sequence)
            bigram_score = len(bigram_overlap) / max(1, min(len(content_bigrams), len(memory_sequence), 10))
            char_score = _cosine_counter(content_trigrams, _character_trigrams(memory))
            embedding_score = self._embedding_similarity(content_embedding, self._memory_embedding(memory))

            lexical_score = (
                containment * 0.42
                + jaccard * 0.22
                + bigram_score * 0.20
                + char_score * 0.16
            )
            layer_weight = self._memory_layer_weight(memory)
            recency_decay = max(0.70, 1.0 - (reverse_index * 0.012))
            score = max(lexical_score, embedding_score * 0.90) * layer_weight * recency_decay
            if "active_memory_resonance/" in memory:
                score += self._extract_resonance_score(memory) * 0.24
            best = max(best, score)
        return _bounded(best)

    # Hàm _memory_embedding nhận một chuỗi văn bản và trả về một embedding vector dưới dạng một sequence các float. Nếu memory_embedding_fn
    #  không được cung cấp hoặc nếu có lỗi trong quá trình tạo embedding, nó sẽ trả về một tuple rỗng.
    def _memory_embedding(self, text: str) -> Sequence[float]:
        if self.memory_embedding_fn is None:
            return ()
        try:
            return tuple(float(value) for value in self.memory_embedding_fn(text))
        except (TypeError, ValueError):
            return ()

    def _embedding_similarity(self, left: Sequence[float], right: Sequence[float]) -> float:
        if not left or not right:
            return 0.0
        return _cosine_dense(left, right)

    #Nếu event dính các từ như “stuck”, “stress”, “unfinished”, “lonely”, “repeat”... thì tăng bias.
    #Đây là phần làm hệ thống chú ý tới các pattern hành vi/tâm trạng, không chỉ dữ liệu khô.
    def _score_personality_bias(self, percept: PerceptEvent, *, snapshot=None) -> float:
        text_parts = [
            str(percept.content or ""),
            " ".join(str(item) for item in (percept.evidence or ())),
            str(percept.kind or ""),
            str(percept.novelty_hint or ""),
        ]
        if snapshot is not None:
            user_signals = getattr(snapshot, "user_signals", None)
            text_parts.extend(
                (
                    str(getattr(snapshot, "focus_summary", "") or ""),
                    str(getattr(snapshot, "ambient_tone", "") or ""),
                    str(getattr(snapshot, "tease_bias", "") or ""),
                    " ".join(str(item) for item in (getattr(snapshot, "recent_events", ()) or ())),
                    str(getattr(user_signals, "typing_speed", "") if user_signals is not None else ""),
                    str(getattr(user_signals, "window_switching", "") if user_signals is not None else ""),
                    str(getattr(user_signals, "focus_pattern", "") if user_signals is not None else ""),
                )
            )
        normalized = _normalize_for_bias(" ".join(part for part in text_parts if part))
        if not normalized:
            return 0.0

        hits: list[str] = []
        if percept.kind == "persistent_goal":
            hits.append("continuity")
        for category, terms in self.PERSONALITY_BIAS_TERMS.items():
            #Personality bias cũng bỏ substring
            #Nên các bias kiểu sad, met, buc, loop, message không còn dễ dính nhầm trong chuỗi dài.
            if _contains_any_affirmed_normalized_phrase(normalized, terms):
                hits.append(category)
        if not hits:
            return 0.0

        score = 0.38 + min(0.42, len(hits) * 0.12)
        if percept.kind in {"cognitive_momentum", "cognitive_attractor"} and "continuity" in hits:
            score += 0.18
        if percept.kind in {"user_message", "user_force_speak"}:
            score += 0.10
        if percept.kind in {"recent_event", "vision_fact", "substrate_disturbance"}:
            score += 0.08
        return _bounded(score)

    def _memory_layer_weight(self, memory: str) -> float:
        lowered = (memory or "").lower()
        if "active_memory_resonance/working" in lowered or lowered.startswith("working:"):
            return 1.10
        if "active_memory_resonance/procedural" in lowered or lowered.startswith("procedural"):
            return 1.06
        if "active_memory_resonance/relationship" in lowered or lowered.startswith("relationship/"):
            return 1.00
        if "active_memory_resonance/episodic" in lowered or lowered.startswith("episodic:"):
            return 0.96
        if "active_memory_resonance/semantic" in lowered or lowered.startswith("semantic/"):
            return 0.90
        return 0.82

    def _extract_resonance_score(self, memory: str) -> float:
        match = re.search(r"\bscore=([0-9.]+)", memory or "")
        if not match:
            return 0.0
        try:
            return _bounded(float(match.group(1)))
        except ValueError:
            return 0.0
