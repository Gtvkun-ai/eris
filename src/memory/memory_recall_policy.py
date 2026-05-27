from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol

from .memory_models import MemoryKind, RecallAnswer, RecallRequest, SurfaceMode
from .text_normalize_vi import compact_spaces, normalize_vi
try:
    from ..runtime.session_turn_ledger import SessionTurnLedger
except ImportError:
    from runtime.session_turn_ledger import SessionTurnLedger


class SemanticLookup(Protocol):
    def __call__(self, kind: MemoryKind) -> Optional[Any]:
        ...


class EpisodicLookup(Protocol):
    def __call__(self, query: str) -> Optional[Any]:
        ...


class RecallTargetRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    UNKNOWN = "unknown"


class RecallResolutionKind(str, Enum):
    NONE = "none"
    SEMANTIC_FACT = "semantic_fact"
    EXACT_ORDINAL = "exact_ordinal"
    COUNT = "count"
    LONGEST = "longest"
    GIST = "gist"


@dataclass(frozen=True)
class RecallCue:
    """Một tín hiệu nhỏ cho thấy user đang hỏi loại recall nào."""

    label: str
    weight: float
    evidence: str


@dataclass
class RecallCueFrame:
    """
    Khung cue trung gian.

    Đây là phần thay cho if-else fallback. Ta không hỏi "có keyword X không",
    mà gom tín hiệu, chấm áp lực, rồi arbitration chọn dạng recall hợp lý.
    """

    raw_text: str
    normalized_text: str
    cues: list[RecallCue] = field(default_factory=list)

    memory_pressure: float = 0.0
    semantic_pressure: float = 0.0
    exact_pressure: float = 0.0
    gist_pressure: float = 0.0
    count_pressure: float = 0.0
    longest_pressure: float = 0.0

    target_role: RecallTargetRole = RecallTargetRole.UNKNOWN
    target_role_confidence: float = 0.0

    ordinal: Optional[int] = None
    asks_question_only: bool = False
    semantic_kind: MemoryKind = MemoryKind.UNKNOWN

    ambiguity: float = 0.0

    def add(self, label: str, weight: float, evidence: str) -> None:
        self.cues.append(RecallCue(label=label, weight=weight, evidence=evidence))

    def debug_labels(self) -> list[str]:
        return [f"{cue.label}:{cue.weight:.2f}" for cue in self.cues]


class RecallCueExtractor:
    """
    Rút cue từ câu user bằng nhiều tín hiệu nhỏ.

    Vẫn có pattern vì ngôn ngữ phải bám chữ, không thể thiền ra ordinal từ hư vô.
    Nhưng pattern chỉ tạo cue; quyết định cuối nằm ở resolver.
    """

    _ORDINAL_WORDS = {
        "1": 1,
        "mot": 1,
        "nhat": 1,
        "dau": 1,
        "2": 2,
        "hai": 2,
        "nhi": 2,
        "3": 3,
        "ba": 3,
        "4": 4,
        "bon": 4,
        "tu": 4,
        "5": 5,
        "nam": 5,
        "6": 6,
        "sau": 6,
        "7": 7,
        "bay": 7,
        "8": 8,
        "tam": 8,
        "9": 9,
        "chin": 9,
        "10": 10,
        "muoi": 10,
        "11": 11,
        "muoi mot": 11,
        "12": 12,
        "muoi hai": 12,
    }

    _ORDINAL_RE = re.compile(
        r"(?:cau(?:\s+hoi)?\s+thu|luot\s+thu|turn\s+thu|thu)\s+"
        r"([0-9]+|mot|nhat|dau|hai|nhi|ba|bon|tu|nam|sau|bay|tam|chin|muoi(?:\s+mot|\s+hai)?)\b"
    )

    _MEMORY_WORDS = ("nho", "tung", "vua", "da noi", "luc nay", "ban nay", "hoi nay", "truoc do", "gan day")
    _EXACT_WORDS = ("nguyen van", "chinh xac", "cau thu", "cau hoi thu", "noi gi", "la cau nao", "la gi")
    _GIST_WORDS = ("lien quan", "dai y", "noi ve", "quanh", "chu de", "ve cai gi")
    _COUNT_WORDS = ("bao nhieu", "may cau", "dem", "so cau")
    _LONGEST_WORDS = ("dai nhat", "nhieu ky tu", "nhieu ki tu", "longest")
    _USER_ROLE_WORDS = ("toi noi", "toi tung noi", "toi da noi", "toi vua noi", "toi hoi", "ngai noi", "ngai hoi")
    _ASSISTANT_ROLE_WORDS = ("em noi", "em tung noi", "em da noi", "em vua noi", "eris noi", "ban noi")
    _NAME_WORDS = ("toi ten la gi", "ten toi", "ten cua toi", "em nho ten toi", "toi la ai")
    _BIRTH_MONTH_WORDS = ("thang sinh", "toi sinh thang", "sinh thang may", "sinh thang nao")

    def extract(self, user_text: str) -> RecallCueFrame:
        raw = compact_spaces(user_text)
        n = normalize_vi(raw)

        frame = RecallCueFrame(raw_text=raw, normalized_text=n)
        tokens = self._tokenize(n)

        self._score_memory_pressure(frame, tokens)
        self._score_semantic_fact(frame, n)
        self._score_exactness(frame, n)
        self._score_gist(frame, n)
        self._score_count_and_longest(frame, n)
        self._score_target_role(frame, n)
        self._score_question_only(frame, n)
        self._extract_ordinal(frame, n)
        self._compute_ambiguity(frame)

        return frame

    def _score_memory_pressure(self, frame: RecallCueFrame, tokens: set[str]) -> None:
        score = 0.0
        for word in self._MEMORY_WORDS:
            if self._contains(frame.normalized_text, word):
                score += 0.22
                frame.add("memory_word", 0.22, word)

        if {"cau", "hoi"} <= tokens or "cau hoi" in frame.normalized_text:
            score += 0.18
            frame.add("question_sequence_hint", 0.18, "cau/hoi")

        if "ten" in tokens or "thang" in tokens:
            score += 0.12
            frame.add("personal_fact_hint", 0.12, "ten/thang")

        frame.memory_pressure = min(score, 1.0)

    def _score_semantic_fact(self, frame: RecallCueFrame, n: str) -> None:
        name_score = self._phrase_score(n, self._NAME_WORDS, weight=0.35)
        birth_score = self._phrase_score(n, self._BIRTH_MONTH_WORDS, weight=0.32)

        if name_score > 0:
            frame.semantic_pressure += name_score
            frame.semantic_kind = MemoryKind.USER_NAME
            frame.add("semantic_name", name_score, "name_query")

        if birth_score > 0 and name_score <= 0:
            frame.semantic_pressure += birth_score
            frame.semantic_kind = MemoryKind.USER_BIRTH_MONTH
            frame.add("semantic_birth_month", birth_score, "birth_month_query")

        frame.semantic_pressure = min(frame.semantic_pressure, 1.0)

    def _score_exactness(self, frame: RecallCueFrame, n: str) -> None:
        score = self._phrase_score(n, self._EXACT_WORDS, weight=0.17)
        if score:
            frame.add("exact_surface_hint", score, "exact_words")

        if self._ORDINAL_RE.search(n):
            score += 0.55
            frame.add("ordinal_hint", 0.55, "ordinal")

        frame.exact_pressure = min(score, 1.0)

    def _score_gist(self, frame: RecallCueFrame, n: str) -> None:
        score = self._phrase_score(n, self._GIST_WORDS, weight=0.20)

        if "nho" in n and frame.exact_pressure < 0.45:
            score += 0.18
            frame.add("soft_memory_request", 0.18, "nho_without_exact")

        if score:
            frame.add("gist_hint", min(score, 1.0), "gist_words")

        frame.gist_pressure = min(score, 1.0)

    def _score_count_and_longest(self, frame: RecallCueFrame, n: str) -> None:
        count_score = self._phrase_score(n, self._COUNT_WORDS, weight=0.27)
        longest_score = self._phrase_score(n, self._LONGEST_WORDS, weight=0.40)

        if "cau hoi" in n or ("cau" in n and "hoi" in n):
            if count_score:
                count_score += 0.25
                frame.add("count_question_scope", 0.25, "cau_hoi")
            if longest_score:
                longest_score += 0.20
                frame.add("longest_question_scope", 0.20, "cau_hoi")

        frame.count_pressure = min(count_score, 1.0)
        frame.longest_pressure = min(longest_score, 1.0)

        if frame.count_pressure:
            frame.add("count_hint", frame.count_pressure, "count_words")
        if frame.longest_pressure:
            frame.add("longest_hint", frame.longest_pressure, "longest_words")

    def _score_target_role(self, frame: RecallCueFrame, n: str) -> None:
        user_score = self._phrase_score(n, self._USER_ROLE_WORDS, weight=0.26)
        assistant_score = self._phrase_score(n, self._ASSISTANT_ROLE_WORDS, weight=0.30)

        # "em nhớ câu tôi nói" có cả em + tôi, nhưng target là user.
        if "toi" in n and ("em nho" in n or "ban nho" in n):
            user_score += 0.18
            frame.add("remember_my_line", 0.18, "toi+em_nho")

        if assistant_score > user_score and assistant_score >= 0.25:
            frame.target_role = RecallTargetRole.ASSISTANT
            frame.target_role_confidence = min(assistant_score, 1.0)
            frame.add("target_assistant", frame.target_role_confidence, "assistant_role_words")
        elif user_score >= 0.18:
            frame.target_role = RecallTargetRole.USER
            frame.target_role_confidence = min(user_score, 1.0)
            frame.add("target_user", frame.target_role_confidence, "user_role_words")
        else:
            frame.target_role = RecallTargetRole.USER
            frame.target_role_confidence = 0.45
            frame.add("target_default_user", 0.45, "default_memory_owner")

    def _score_question_only(self, frame: RecallCueFrame, n: str) -> None:
        if "cau hoi" in n or "hoi" in n:
            frame.asks_question_only = True
            frame.add("question_only", 0.34, "hoi/cau_hoi")

    def _extract_ordinal(self, frame: RecallCueFrame, n: str) -> None:
        match = self._ORDINAL_RE.search(n)
        if not match:
            return
        token = match.group(1)
        frame.ordinal = self._ORDINAL_WORDS.get(token)
        if frame.ordinal is None and token.isdigit():
            frame.ordinal = int(token)

    def _compute_ambiguity(self, frame: RecallCueFrame) -> None:
        active = [
            frame.semantic_pressure,
            frame.exact_pressure,
            frame.gist_pressure,
            frame.count_pressure,
            frame.longest_pressure,
        ]
        strong = [score for score in active if score >= 0.35]
        if len(strong) <= 1:
            frame.ambiguity = 0.10 if frame.memory_pressure > 0 else 0.40
            return

        sorted_scores = sorted(strong, reverse=True)
        gap = sorted_scores[0] - sorted_scores[1]
        frame.ambiguity = max(0.10, min(0.85, 0.65 - gap))

    @staticmethod
    def _tokenize(n: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", n))

    @staticmethod
    def _contains(text: str, phrase: str) -> bool:
        return phrase in text

    @classmethod
    def _phrase_score(cls, text: str, phrases: tuple[str, ...], *, weight: float) -> float:
        hits = sum(1 for phrase in phrases if cls._contains(text, phrase))
        if hits <= 0:
            return 0.0
        return min(1.0, hits * weight)


class RecallIntentResolver:
    """
    Arbitration cho recall intent.

    Resolver nhận cue frame và chọn action theo pressure. Đây là chỗ thay thế
    nhánh fallback. Có thể debug vì mọi quyết định đều có cue + pressure.
    """

    def resolve(self, frame: RecallCueFrame) -> Optional[RecallRequest]:
        if self._not_memory_query(frame):
            return None

        kind = self._choose_kind(frame)
        if kind == RecallResolutionKind.NONE:
            return None

        if kind == RecallResolutionKind.SEMANTIC_FACT:
            return RecallRequest(
                mode=SurfaceMode.SEMANTIC,
                kind=frame.semantic_kind,
                raw_text=frame.raw_text,
                confidence=self._confidence(frame, frame.semantic_pressure),
            )

        if kind == RecallResolutionKind.COUNT:
            return RecallRequest(
                mode=SurfaceMode.EXACT,
                asks_count=True,
                asks_question_only=True,
                raw_text=frame.raw_text,
                confidence=self._confidence(frame, frame.count_pressure),
            )

        if kind == RecallResolutionKind.LONGEST:
            return RecallRequest(
                mode=SurfaceMode.EXACT,
                asks_longest=True,
                asks_question_only=True,
                raw_text=frame.raw_text,
                confidence=self._confidence(frame, frame.longest_pressure),
            )

        if kind == RecallResolutionKind.EXACT_ORDINAL:
            return RecallRequest(
                mode=SurfaceMode.EXACT,
                ordinal=frame.ordinal,
                target_role=frame.target_role.value,
                asks_question_only=frame.asks_question_only,
                raw_text=frame.raw_text,
                confidence=self._confidence(frame, frame.exact_pressure),
            )

        if kind == RecallResolutionKind.GIST:
            return RecallRequest(
                mode=SurfaceMode.GIST,
                kind=MemoryKind.USER_GENERAL_TOPIC,
                raw_text=frame.raw_text,
                confidence=self._confidence(frame, frame.gist_pressure or frame.memory_pressure),
            )

        return None

    def _not_memory_query(self, frame: RecallCueFrame) -> bool:
        return max(
            frame.memory_pressure,
            frame.semantic_pressure,
            frame.exact_pressure,
            frame.count_pressure,
            frame.longest_pressure,
            frame.gist_pressure,
        ) < 0.30

    def _choose_kind(self, frame: RecallCueFrame) -> RecallResolutionKind:
        # Semantic fact thắng khi user hỏi định danh rõ. Tên/tháng sinh không nên rơi xuống gist.
        if frame.semantic_pressure >= 0.35:
            return RecallResolutionKind.SEMANTIC_FACT

        # Count/longest là thao tác ledger deterministic, không cho LLM tự diễn xiếc.
        if frame.count_pressure >= 0.48:
            return RecallResolutionKind.COUNT

        if frame.longest_pressure >= 0.48:
            return RecallResolutionKind.LONGEST

        # Exact ordinal chỉ mở khi có ordinal thật và áp lực exact đủ cao.
        if frame.ordinal is not None and frame.exact_pressure >= 0.48:
            return RecallResolutionKind.EXACT_ORDINAL

        # Mặc định của recall tự nhiên là gist, không phải transcript.
        if frame.memory_pressure >= 0.35 or frame.gist_pressure >= 0.25:
            return RecallResolutionKind.GIST

        return RecallResolutionKind.NONE

    @staticmethod
    def _confidence(frame: RecallCueFrame, winning_pressure: float) -> float:
        confidence = 0.45 + min(winning_pressure, 1.0) * 0.45
        confidence -= frame.ambiguity * 0.18
        if frame.target_role_confidence < 0.40:
            confidence -= 0.05
        return max(0.25, min(confidence, 0.96))


class RecallIntentClassifier:
    """
    Public classifier giữ API cũ, nhưng bên trong là cue extraction + resolver.

    Các code cũ đang gọi `RecallIntentClassifier().classify(text)` vẫn chạy.
    """

    def __init__(
        self,
        extractor: RecallCueExtractor | None = None,
        resolver: RecallIntentResolver | None = None,
    ) -> None:
        self.extractor = extractor or RecallCueExtractor()
        self.resolver = resolver or RecallIntentResolver()
        self.last_frame: RecallCueFrame | None = None

    def classify(self, user_text: str) -> Optional[RecallRequest]:
        frame = self.extractor.extract(user_text)
        self.last_frame = frame
        return self.resolver.resolve(frame)


class MemoryRecallPolicy:
    """
    Thực thi recall đã phân loại.

    Policy này chỉ chọn nguồn và surface. Nó không tự thành memory store.
    """

    def __init__(self, classifier: RecallIntentClassifier | None = None) -> None:
        self.classifier = classifier or RecallIntentClassifier()

    def answer(
        self,
        user_text: str,
        *,
        ledger: SessionTurnLedger,
        semantic_lookup: SemanticLookup | None = None,
        episodic_lookup: EpisodicLookup | None = None,
    ) -> Optional[RecallAnswer]:
        request = self.classifier.classify(user_text)
        if request is None:
            return None

        frame = getattr(self.classifier, "last_frame", None)

        handlers = (
            self._try_semantic,
            self._try_count,
            self._try_longest,
            self._try_ordinal,
            self._try_gist,
        )

        for handler in handlers:
            answer = handler(
                request,
                ledger=ledger,
                semantic_lookup=semantic_lookup,
                episodic_lookup=episodic_lookup,
                frame=frame,
            )
            if answer is not None:
                return answer

        return None

    def _try_semantic(
        self,
        request: RecallRequest,
        *,
        ledger: SessionTurnLedger,
        semantic_lookup: SemanticLookup | None,
        episodic_lookup: EpisodicLookup | None,
        frame: RecallCueFrame | None,
    ) -> Optional[RecallAnswer]:
        if request.mode != SurfaceMode.SEMANTIC:
            return None
        if request.kind not in (MemoryKind.USER_NAME, MemoryKind.USER_BIRTH_MONTH):
            return None

        record = semantic_lookup(request.kind) if semantic_lookup else None
        value = self._extract_value(record)

        if request.kind == MemoryKind.USER_NAME:
            if value:
                return RecallAnswer(
                    text=f"Ngài từng nói tên mình là {value}.",
                    confidence=min(request.confidence, 0.94),
                    source="semantic_memory",
                    surface_mode=SurfaceMode.SEMANTIC,
                    debug_trace=self._trace("semantic_recall:user_name", frame),
                    metadata={"kind": request.kind.value, "value": value},
                )
            return RecallAnswer(
                text="Tôi chưa có ký ức semantic đủ chắc về tên của Ngài.",
                confidence=0.35,
                source="semantic_memory",
                surface_mode=SurfaceMode.UNCERTAIN,
                debug_trace=self._trace("semantic_recall:user_name_missing", frame),
                metadata={"kind": request.kind.value},
            )

        if request.kind == MemoryKind.USER_BIRTH_MONTH:
            if value:
                return RecallAnswer(
                    text=f"Ngài từng nói tháng sinh của mình là tháng {value}.",
                    confidence=min(request.confidence, 0.90),
                    source="semantic_memory",
                    surface_mode=SurfaceMode.SEMANTIC,
                    debug_trace=self._trace("semantic_recall:user_birth_month", frame),
                    metadata={"kind": request.kind.value, "value": value},
                )
            return RecallAnswer(
                text="Tôi chưa có ký ức semantic đủ chắc về tháng sinh của Ngài.",
                confidence=0.35,
                source="semantic_memory",
                surface_mode=SurfaceMode.UNCERTAIN,
                debug_trace=self._trace("semantic_recall:user_birth_month_missing", frame),
                metadata={"kind": request.kind.value},
            )

        return None

    def _try_count(
        self,
        request: RecallRequest,
        *,
        ledger: SessionTurnLedger,
        semantic_lookup: SemanticLookup | None,
        episodic_lookup: EpisodicLookup | None,
        frame: RecallCueFrame | None,
    ) -> Optional[RecallAnswer]:
        if not request.asks_count:
            return None

        count = ledger.count_user_questions()
        return RecallAnswer(
            text=f"Nếu tính các câu hỏi public trong phiên hiện tại, Ngài đã hỏi {count} câu.",
            confidence=0.95,
            source="session_turn_ledger",
            surface_mode=SurfaceMode.EXACT,
            debug_trace=self._trace("ledger_count:user_questions", frame),
            metadata={"count": count},
        )

    def _try_longest(
        self,
        request: RecallRequest,
        *,
        ledger: SessionTurnLedger,
        semantic_lookup: SemanticLookup | None,
        episodic_lookup: EpisodicLookup | None,
        frame: RecallCueFrame | None,
    ) -> Optional[RecallAnswer]:
        if not request.asks_longest:
            return None

        turn = ledger.longest_user_question()
        if turn is None:
            return RecallAnswer(
                text="Tôi chưa thấy câu hỏi nào đủ rõ trong ledger phiên này.",
                confidence=0.40,
                source="session_turn_ledger",
                surface_mode=SurfaceMode.UNCERTAIN,
                debug_trace=self._trace("ledger_longest:no_question", frame),
            )

        return RecallAnswer(
            text=f"Câu hỏi dài nhất trong phiên hiện tại là: “{turn.text}”.",
            confidence=0.94,
            source="session_turn_ledger",
            surface_mode=SurfaceMode.EXACT,
            debug_trace=self._trace("ledger_longest:user_question", frame),
            metadata={"turn_index": turn.index, "text": turn.text},
        )

    def _try_ordinal(
        self,
        request: RecallRequest,
        *,
        ledger: SessionTurnLedger,
        semantic_lookup: SemanticLookup | None,
        episodic_lookup: EpisodicLookup | None,
        frame: RecallCueFrame | None,
    ) -> Optional[RecallAnswer]:
        if request.ordinal is None:
            return None

        if request.target_role == RecallTargetRole.ASSISTANT.value:
            turn = ledger.nth_assistant_turn(request.ordinal)
            role_text = "câu thứ"
            owner = "tôi từng nói"
        elif request.asks_question_only:
            turn = ledger.nth_user_question(request.ordinal)
            role_text = "câu hỏi thứ"
            owner = "Ngài hỏi"
        else:
            turn = ledger.nth_user_turn(request.ordinal)
            role_text = "câu thứ"
            owner = "Ngài nói"

        if turn is None:
            return RecallAnswer(
                text=f"Tôi không có đủ dữ liệu trong ledger phiên này để xác nhận {role_text} {request.ordinal}.",
                confidence=0.42,
                source="session_turn_ledger",
                surface_mode=SurfaceMode.UNCERTAIN,
                debug_trace=self._trace(f"ledger_ordinal:missing:{request.target_role}:{request.ordinal}", frame),
                metadata={"ordinal": request.ordinal, "target_role": request.target_role},
            )

        return RecallAnswer(
            text=f"Nếu tính trong phiên hiện tại, {role_text} {request.ordinal} {owner} là: “{turn.text}”.",
            confidence=0.94,
            source="session_turn_ledger",
            surface_mode=SurfaceMode.EXACT,
            debug_trace=self._trace(f"ledger_ordinal:hit:{request.target_role}:{request.ordinal}", frame),
            metadata={"ordinal": request.ordinal, "turn_index": turn.index, "text": turn.text},
        )

    def _try_gist(
        self,
        request: RecallRequest,
        *,
        ledger: SessionTurnLedger,
        semantic_lookup: SemanticLookup | None,
        episodic_lookup: EpisodicLookup | None,
        frame: RecallCueFrame | None,
    ) -> Optional[RecallAnswer]:
        if request.mode != SurfaceMode.GIST:
            return None

        episodic = episodic_lookup(request.raw_text) if episodic_lookup else None
        episodic_value = self._extract_surface(episodic)
        if episodic_value:
            return RecallAnswer(
                text=episodic_value,
                confidence=min(request.confidence, 0.74),
                source="episodic_memory",
                surface_mode=SurfaceMode.GIST,
                debug_trace=self._trace("episodic_gist:lookup_hit", frame),
            )

        topics = ledger.gist_recent_user_topics()
        if topics:
            joined = ", ".join(topics)
            return RecallAnswer(
                text=f"Tôi nhớ đại ý gần đây Ngài đang nói quanh: {joined}. Tôi sẽ không quote nguyên văn nếu Ngài chưa hỏi rõ.",
                confidence=min(request.confidence, 0.72),
                source="session_turn_ledger",
                surface_mode=SurfaceMode.GIST,
                debug_trace=self._trace("ledger_gist:recent_topics", frame),
                metadata={"topics": topics},
            )

        return RecallAnswer(
            text="Tôi chỉ có cảm giác rất mờ về đoạn trước, chưa đủ chắc để nhắc lại như một ký ức rõ.",
            confidence=0.32,
            source="session_turn_ledger",
            surface_mode=SurfaceMode.UNCERTAIN,
            debug_trace=self._trace("gist:no_recent_topics", frame),
        )

    @staticmethod
    def _extract_value(record: Any) -> Optional[str]:
        if record is None:
            return None
        if isinstance(record, str):
            return record
        if isinstance(record, dict):
            meta = record.get("metadata") or {}
            return (
                meta.get("value")
                or record.get("value")
                or record.get("surface")
                or record.get("claim")
            )
        return getattr(record, "value", None) or getattr(record, "surface", None) or getattr(record, "claim", None)

    @staticmethod
    def _extract_surface(record: Any) -> Optional[str]:
        if record is None:
            return None
        if isinstance(record, str):
            return record
        if isinstance(record, dict):
            return record.get("surface") or record.get("gist") or record.get("claim")
        return getattr(record, "surface", None) or getattr(record, "gist", None) or getattr(record, "claim", None)

    @staticmethod
    def _trace(prefix: str, frame: RecallCueFrame | None) -> str:
        if frame is None:
            return prefix
        return (
            f"{prefix} | cues={frame.debug_labels()} | "
            f"pressure(memory={frame.memory_pressure:.2f}, semantic={frame.semantic_pressure:.2f}, "
            f"exact={frame.exact_pressure:.2f}, gist={frame.gist_pressure:.2f}, "
            f"count={frame.count_pressure:.2f}, longest={frame.longest_pressure:.2f}, "
            f"ambiguity={frame.ambiguity:.2f})"
        )
