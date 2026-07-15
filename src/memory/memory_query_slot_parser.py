from __future__ import annotations

"""
memory_query_slot_parser.py

Slot grammar tiếng Việt cho memory query.

Nó KHÔNG execute memory.
Nó KHÔNG gọi ledger.
Nó KHÔNG trả lời user.

Nó chỉ sinh QueryHypothesis / MemoryQueryIR từ slot:
- target role/act
- anchor role/act
- relation
- ordinal/quantity
- surface
- fact_key

Đây vẫn là pattern, nhưng là pattern có cấu trúc + confidence + ambiguity,
không phải keyword route kiểu "if câu hỏi thứ: nth_question()".
"""

from dataclasses import dataclass
from typing import Optional
import re
import unicodedata

from .memory_query_ir import (
    ActRef,
    MemoryQueryIR,
    MemoryRelation,
    MemorySelector,
    QueryHypothesis,
    QueryIntent,
    RelationRef,
    RoleRef,
    SurfaceMode,
    clamp01,
)


@dataclass(slots=True)
class SlotSignal:
    """Một tín hiệu slot rút từ text."""

    name: str
    value: object
    confidence: float
    evidence: str


@dataclass(slots=True)
class SlotParseResult:
    """Kết quả parse slot."""

    hypotheses: tuple[QueryHypothesis, ...]
    signals: tuple[SlotSignal, ...]
    normalized_text: str

    @property
    def has_self_disclosure(self) -> bool:
        return any(signal.name == "self_disclosure_fact" for signal in self.signals)


class MemoryQuerySlotParser:
    """
    Parser slot nhẹ.

    Dùng cho tiếng Việt thân mật kiểu:
    - "câu hỏi thứ 2 tôi từng hỏi là gì"
    - "câu trả lời của em cho câu hỏi thứ 3"
    - "3 câu hỏi trước đó của tôi"
    - "tôi sinh tháng mấy"
    """

    def parse(self, text: str) -> SlotParseResult:
        raw = text or ""
        norm = normalize_vi(raw)
        signals = self._extract_signals(raw, norm)
        hypotheses = self._build_hypotheses(raw, norm, signals)
        hypotheses = tuple(sorted(hypotheses, key=lambda h: h.score, reverse=True))
        return SlotParseResult(
            hypotheses=hypotheses,
            signals=tuple(signals),
            normalized_text=norm,
        )

    # ------------------------------------------------------------------
    # Signal extraction
    # ------------------------------------------------------------------

    def _extract_signals(self, raw: str, norm: str) -> list[SlotSignal]:
        signals: list[SlotSignal] = []

        self_disclosure = infer_self_disclosure_fact(norm)
        if self_disclosure:
            signals.append(
                SlotSignal(
                    "self_disclosure_fact",
                    self_disclosure,
                    self_disclosure[1],
                    "self_disclosure_phrase",
                )
            )

        ordinal = extract_ordinal(norm)
        if ordinal is not None:
            signals.append(SlotSignal("ordinal", ordinal, 0.94, "ordinal_phrase"))

        quantity = extract_quantity(norm)
        if quantity is not None:
            signals.append(SlotSignal("quantity", quantity, 0.90, "quantity_phrase"))

        if looks_recent(norm):
            signals.append(SlotSignal("recent", True, 0.82, "recent_phrase"))

        role_target = infer_target_role(norm)
        if role_target:
            signals.append(SlotSignal("target_role", role_target, role_target[1], "role_target_phrase"))

        act_target = infer_target_act(norm)
        if act_target:
            signals.append(SlotSignal("target_act", act_target, act_target[1], "act_target_phrase"))

        anchor = infer_anchor(norm)
        if anchor:
            signals.append(SlotSignal("anchor", anchor, anchor[2], "anchor_phrase"))

        relation = infer_relation(norm)
        if relation:
            signals.append(SlotSignal("relation", relation, relation[1], "relation_phrase"))

        fact_key = infer_fact_key(norm)
        if fact_key:
            signals.append(SlotSignal("fact_key", fact_key, fact_key[1], "fact_phrase"))

        if asks_count(norm):
            signals.append(SlotSignal("intent", QueryIntent.RECALL_COUNT, 0.86, "count_phrase"))

        if asks_summary(norm):
            signals.append(SlotSignal("intent", QueryIntent.RECALL_SUMMARY, 0.76, "summary_phrase"))

        if asks_exact(norm):
            signals.append(SlotSignal("surface", SurfaceMode.EXACT, 0.80, "exact_phrase"))

        return signals

    # ------------------------------------------------------------------
    # Hypothesis builder
    # ------------------------------------------------------------------

    def _build_hypotheses(
        self,
        raw: str,
        norm: str,
        signals: list[SlotSignal],
    ) -> list[QueryHypothesis]:
        by_name = {s.name: s for s in signals}
        hypos: list[QueryHypothesis] = []

        if by_name.get("self_disclosure_fact"):
            return hypos

        fact_signal = by_name.get("fact_key")
        if fact_signal:
            fact_key, fact_conf = fact_signal.value  # type: ignore[misc]
            conf = min(0.92, 0.72 + fact_conf * 0.22)
            ir = MemoryQueryIR(
                intent=QueryIntent.RECALL_FACT,
                target=MemorySelector(
                    role=RoleRef.USER,
                    act=ActRef.FACT_DISCLOSURE,
                    fact_key=str(fact_key),
                ),
                relation=MemoryRelation(RelationRef.SELF),
                surface=SurfaceMode.EXACT,
                confidence=conf,
                ambiguity=1.0 - conf,
                intercept_permission=True,
                evidence=("slot:fact_key", fact_signal.evidence),
                raw_text=raw,
            )
            hypos.append(QueryHypothesis(ir=ir, score=conf, source="slot_parser", reasons=("fact_key_detected",)))

        # Count query: "tôi hỏi bao nhiêu câu"
        intent_signal = by_name.get("intent")
        if intent_signal and intent_signal.value == QueryIntent.RECALL_COUNT:
            target = self._target_from_signals(signals, default_role=RoleRef.USER, default_act=ActRef.QUESTION)
            conf = self._confidence(signals, base=0.72)
            ir = MemoryQueryIR(
                intent=QueryIntent.RECALL_COUNT,
                target=target,
                surface=SurfaceMode.COUNT,
                confidence=conf,
                ambiguity=1.0 - conf,
                intercept_permission=True,
                evidence=("slot:count",),
                raw_text=raw,
            )
            hypos.append(QueryHypothesis(ir=ir, score=conf, source="slot_parser", reasons=("count_query",)))

        # Recent list query: "3 câu hỏi trước đó"
        quantity = _signal_value(signals, "quantity")
        recent = bool(_signal_value(signals, "recent"))
        if quantity is not None and ("cau hoi" in norm or "hoi" in norm):
            role = RoleRef.USER if ("toi" in norm or "cua toi" in norm or "ban" in norm) else RoleRef.ANY
            target = MemorySelector(
                role=role,
                act=ActRef.QUESTION,
                quantity=int(quantity),
                recent=recent or True,
            )
            conf = self._confidence(signals, base=0.78)
            ir = MemoryQueryIR(
                intent=QueryIntent.RECALL_TURN,
                target=target,
                surface=SurfaceMode.EXACT,
                confidence=conf,
                ambiguity=1.0 - conf,
                intercept_permission=True,
                evidence=("slot:recent_quantity_questions",),
                raw_text=raw,
            )
            hypos.append(QueryHypothesis(ir=ir, score=conf, source="slot_parser", reasons=("recent_questions",)))

        # Relation query: assistant answer to user question ordinal N.
        relation_signal = by_name.get("relation")
        anchor_signal = by_name.get("anchor")
        ordinal = _signal_value(signals, "ordinal")
        target_role_pair = _signal_value(signals, "target_role")
        target_act_pair = _signal_value(signals, "target_act")

        if relation_signal and relation_signal.value[0] == RelationRef.ANSWER_TO:
            target_role = target_role_pair[0] if target_role_pair else RoleRef.ASSISTANT
            target_act = target_act_pair[0] if target_act_pair else ActRef.ANSWER
            anchor_role, anchor_act, _anchor_conf = anchor_signal.value if anchor_signal else (RoleRef.USER, ActRef.QUESTION, 0.70)
            anchor = MemorySelector(
                role=anchor_role,
                act=anchor_act,
                ordinal=int(ordinal) if ordinal is not None else None,
                semantic_hint=extract_semantic_anchor(norm),
            )
            target = MemorySelector(role=target_role, act=target_act)
            conf = self._confidence(signals, base=0.80)
            ir = MemoryQueryIR(
                intent=QueryIntent.RECALL_TURN,
                target=target,
                relation=MemoryRelation(RelationRef.ANSWER_TO, anchor=anchor),
                surface=SurfaceMode.EXACT,
                confidence=conf,
                ambiguity=1.0 - conf,
                intercept_permission=True,
                evidence=("slot:answer_to_relation",),
                raw_text=raw,
            )
            hypos.append(QueryHypothesis(ir=ir, score=conf, source="slot_parser", reasons=("answer_to_relation",)))

        # Ordinal direct query: "câu hỏi thứ 2 tôi hỏi".
        # Nếu đã có relation ANSWER_TO, không sinh hypothesis direct này nữa.
        # Không thì câu "câu trả lời của em cho câu hỏi thứ 3" sẽ bị đọc nhầm
        # thành "câu hỏi thứ 3".
        has_answer_to_relation = bool(
            relation_signal and relation_signal.value[0] == RelationRef.ANSWER_TO
        )
        if ordinal is not None and ("cau hoi" in norm or "hoi" in norm) and not has_answer_to_relation:
            role = RoleRef.USER if ("toi" in norm or "cua toi" in norm or "ban" in norm) else RoleRef.ANY
            target = MemorySelector(role=role, act=ActRef.QUESTION, ordinal=int(ordinal))
            conf = self._confidence(signals, base=0.76)
            ir = MemoryQueryIR(
                intent=QueryIntent.RECALL_TURN,
                target=target,
                surface=SurfaceMode.EXACT,
                confidence=conf,
                ambiguity=1.0 - conf,
                intercept_permission=True,
                evidence=("slot:ordinal_question",),
                raw_text=raw,
            )
            hypos.append(QueryHypothesis(ir=ir, score=conf, source="slot_parser", reasons=("ordinal_user_question",)))

        # Assistant ordinal: "em nói câu thứ 1"
        if ordinal is not None and ("em noi" in norm or "ban noi" in norm or "eris noi" in norm):
            target = MemorySelector(role=RoleRef.ASSISTANT, act=ActRef.ANY, ordinal=int(ordinal))
            conf = self._confidence(signals, base=0.72)
            ir = MemoryQueryIR(
                intent=QueryIntent.RECALL_TURN,
                target=target,
                surface=SurfaceMode.EXACT,
                confidence=conf,
                ambiguity=1.0 - conf,
                intercept_permission=True,
                evidence=("slot:assistant_ordinal",),
                raw_text=raw,
            )
            hypos.append(QueryHypothesis(ir=ir, score=conf, source="slot_parser", reasons=("assistant_ordinal",)))

        # Generic recall turn fallback hypothesis, dùng khi có signal recall nhưng chưa đủ.
        if not hypos and looks_like_generic_recall_request(norm):
            target = self._target_from_signals(signals)
            conf = self._confidence(signals, base=0.48)
            ir = MemoryQueryIR(
                intent=QueryIntent.RECALL_TURN,
                target=target,
                surface=SurfaceMode.GIST if conf < 0.62 else SurfaceMode.EXACT,
                confidence=conf,
                ambiguity=1.0 - conf,
                intercept_permission=False,
                evidence=("slot:generic_recall",),
                warnings=("generic_slot_query",),
                raw_text=raw,
            )
            hypos.append(QueryHypothesis(ir=ir, score=conf, source="slot_parser", reasons=("generic_recall",)))

        return hypos

    def _target_from_signals(
        self,
        signals: list[SlotSignal],
        *,
        default_role: RoleRef = RoleRef.ANY,
        default_act: ActRef = ActRef.ANY,
    ) -> MemorySelector:
        role_pair = _signal_value(signals, "target_role")
        act_pair = _signal_value(signals, "target_act")
        ordinal = _signal_value(signals, "ordinal")
        quantity = _signal_value(signals, "quantity")
        recent = bool(_signal_value(signals, "recent"))
        return MemorySelector(
            role=role_pair[0] if role_pair else default_role,
            act=act_pair[0] if act_pair else default_act,
            ordinal=int(ordinal) if ordinal is not None else None,
            quantity=int(quantity) if quantity is not None else None,
            recent=recent,
        )

    def _confidence(self, signals: list[SlotSignal], *, base: float) -> float:
        if not signals:
            return base
        # Tăng confidence theo số slot độc lập, nhưng kẹp để không tự tin vô lý.
        avg = sum(s.confidence for s in signals) / len(signals)
        diversity = min(0.16, len({s.name for s in signals}) * 0.025)
        return clamp01(base * 0.62 + avg * 0.30 + diversity)


# ---------------------------------------------------------------------------
# Signal helpers
# ---------------------------------------------------------------------------


def infer_target_role(norm: str) -> Optional[tuple[RoleRef, float]]:
    assistant_markers = ("em tra loi", "em dap", "em noi", "ban tra loi", "ban dap", "ban noi", "eris noi")
    user_markers = ("toi hoi", "cua toi", "toi tung hoi", "ban hoi")
    if any(m in norm for m in assistant_markers):
        return (RoleRef.ASSISTANT, 0.86)
    if any(m in norm for m in user_markers):
        return (RoleRef.USER, 0.82)
    return None


def infer_target_act(norm: str) -> Optional[tuple[ActRef, float]]:
    if any(m in norm for m in ("tra loi", "dap", "phan hoi", "reply")):
        return (ActRef.ANSWER, 0.84)
    if any(m in norm for m in ("cau hoi", "toi hoi", "hoi gi", "hoi la gi")):
        return (ActRef.QUESTION, 0.82)
    if any(m in norm for m in ("toi noi", "toi bao", "toi ke")):
        return (ActRef.STATEMENT, 0.60)
    return None


def infer_anchor(norm: str) -> Optional[tuple[RoleRef, ActRef, float]]:
    if "cau hoi" in norm or "toi hoi" in norm or "ban hoi" in norm:
        return (RoleRef.USER, ActRef.QUESTION, 0.84)
    if "cau em noi" in norm or "em noi" in norm:
        return (RoleRef.ASSISTANT, ActRef.ANY, 0.72)
    return None


def infer_relation(norm: str) -> Optional[tuple[RelationRef, float]]:
    answer_to_markers = (
        "cho cau hoi",
        "luc toi hoi",
        "khi toi hoi",
        "sau cau hoi",
        "em dap sao luc",
        "em tra loi sao luc",
    )
    if any(m in norm for m in answer_to_markers):
        return (RelationRef.ANSWER_TO, 0.88)
    if "truoc do" in norm or "truoc day" in norm:
        return (RelationRef.RECENT_PREVIOUS, 0.62)
    if "sau do" in norm:
        return (RelationRef.AFTER, 0.62)
    return None


def _looks_like_interpretive_fact_question(norm: str) -> bool:
    """True khi user hỏi ý nghĩa/liên tưởng, không hỏi giá trị fact đã lưu."""

    interpretive_markers = (
        "lien tuong", "y nghia", "goi nho", "goi len", "goi gi", "nghe giong",
        "tuong trung", "cam giac", "an tuong", "nghi den", "gan voi", "vi sao ten",
        "ten co nghia", "ten nay co nghia", "ten toi nghe", "ten toi co hay", "danh gia ten",
        "associate", "remind you of", "meaning of",
    )
    return any(marker in norm for marker in interpretive_markers)


def infer_fact_key(norm: str) -> Optional[tuple[str, float]]:
    # Gợi ý fact_key, không đọc memory tại đây. Câu hỏi diễn giải phải đi qua LLM,
    # không được memory adapter cướp lượt chỉ vì có cụm "tên tôi".
    if _looks_like_interpretive_fact_question(norm):
        return None
    if any(m in norm for m in ("toi ten gi", "ten toi", "toi ten la gi", "nho ten toi")):
        return ("user.name", 0.88)
    if any(m in norm for m in ("toi sinh thang may", "thang sinh", "sinh thang may", "birthday month")):
        return ("user.birth_month", 0.90)
    if any(m in norm for m in ("que toi o dau", "que cua toi", "toi que o dau", "hometown")):
        return ("user.hometown", 0.88)
    if any(m in norm for m in ("toi dang o dau", "toi hien o dau", "hien tai toi o dau")):
        return ("user.current_location", 0.82)
    if any(m in norm for m in ("toi song o dau", "noi o cua toi", "living location", "current residence")):
        return ("user.living_location", 0.82)
    if any(m in norm for m in ("toi thich noi nao", "toi thich o dau", "dia diem toi thich", "location preference")):
        return ("user.preference.location", 0.78)
    if any(m in norm for m in ("truoc day toi o dau", "qua khu toi o dau", "toi tung o dau")):
        return ("user.past_location", 0.78)
    return None


def infer_self_disclosure_fact(norm: str) -> Optional[tuple[str, float]]:
    if _looks_like_fact_update_disclosure(norm):
        return ("user.name", 0.96)
    if _looks_like_name_disclosure(norm):
        return ("user.name", 0.96)
    if _looks_like_birth_month_disclosure(norm):
        return ("user.birth_month", 0.94)
    if _looks_like_hometown_disclosure(norm):
        return ("user.hometown", 0.86)
    if _looks_like_living_location_disclosure(norm):
        return ("user.living_location", 0.84)
    if _looks_like_current_location_disclosure(norm):
        return ("user.current_location", 0.82)
    if _looks_like_location_preference_disclosure(norm):
        return ("user.preference.location", 0.76)
    if _looks_like_past_location_disclosure(norm):
        return ("user.past_location", 0.80)
    return None


def asks_count(norm: str) -> bool:
    return any(m in norm for m in ("bao nhieu cau hoi", "hoi bao nhieu", "may cau hoi", "dem cau hoi"))


def asks_summary(norm: str) -> bool:
    return any(m in norm for m in ("tom tat", "noi chung", "gist", "chu de gan day", "gan day toi noi gi"))


def asks_exact(norm: str) -> bool:
    return any(m in norm for m in ("chinh xac", "nguyen van", "cau nao", "la gi", "gi ay nhi", "gi nhi"))


def looks_recent(norm: str) -> bool:
    return any(m in norm for m in ("truoc do", "hoi nay", "luc nay", "gan day", "vua roi", "truoc"))


def looks_like_generic_recall_request(norm: str) -> bool:
    recall_markers = (
        "nho",
        "nho lai",
        "cau hoi",
        "cau tra loi",
        "tra loi",
        "em dap",
        "em noi",
        "toi hoi",
        "toi da noi",
        "toi noi gi",
        "gan day",
        "truoc do",
        "luc do",
        "luc nay",
    )
    question_markers = (
        "gi",
        "nao",
        "bao nhieu",
        "thu ",
        "tom tat",
        "noi chung",
        "gan day",
        "truoc do",
        "luc do",
    )
    return any(marker in norm for marker in recall_markers) and any(marker in norm for marker in question_markers)


def extract_quantity(norm: str) -> Optional[int]:
    # "3 câu hỏi trước", "ba câu hỏi trước"
    m = re.search(r"\b(\d+|mot|hai|ba|bon|tu|nam|sau|bay|tam|chin|muoi)\s+cau", norm)
    if not m:
        return None
    return parse_vi_number(m.group(1))


def extract_ordinal(norm: str) -> Optional[int]:
    patterns = (
        r"\bthu\s+(\d+|nhat|mot|hai|ba|bon|tu|nam|sau|bay|tam|chin|muoi)\b",
        r"\blan\s+thu\s+(\d+|nhat|mot|hai|ba|bon|tu|nam|sau|bay|tam|chin|muoi)\b",
        r"\bcau\s+(?:hoi\s+)?thu\s+(\d+|nhat|mot|hai|ba|bon|tu|nam|sau|bay|tam|chin|muoi)\b",
    )
    for pat in patterns:
        m = re.search(pat, norm)
        if m:
            return parse_vi_number(m.group(1))
    return None


def extract_semantic_anchor(norm: str) -> Optional[str]:
    # "về ưu tiên", "về cảm xúc", "về tắt máy"
    m = re.search(r"\bve\s+(.{2,80})", norm)
    if m:
        value = m.group(1).strip()
        # Cắt vài đuôi query nhiễu.
        value = re.sub(r"\s+(la gi|gi nhi|ay nhi|do|day)$", "", value).strip()
        return value or None
    return None


def _signal_value(signals: list[SlotSignal], name: str) -> object:
    for s in signals:
        if s.name == name:
            return s.value
    return None


def normalize_vi(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9\s_.-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_VI_NUMBERS = {
    "nhat": 1,
    "mot": 1,
    "hai": 2,
    "ba": 3,
    "bon": 4,
    "tu": 4,
    "nam": 5,
    "sau": 6,
    "bay": 7,
    "tam": 8,
    "chin": 9,
    "muoi": 10,
}


def parse_vi_number(value: str) -> Optional[int]:
    value = normalize_vi(value)
    if value.isdigit():
        return int(value)
    return _VI_NUMBERS.get(value)


def _looks_like_name_disclosure(norm: str) -> bool:
    if any(marker in norm for marker in ("toi ten gi", "ten toi", "toi ten la gi", "nho ten toi")):
        return False
    if re.search(r"\btoi\s+ten\s+(?:day\s+du\s+)?la\s+[a-z0-9_ -]{2,60}\b", norm):
        return True
    if re.search(r"\bten\s+day\s+du\s+(?:cua\s+)?toi\s+la\s+[a-z0-9_ -]{2,60}\b", norm):
        return True
    # P0: tiếng Việt chat hay rút gọn "tôi tên Tín" thay vì "tôi tên là Tín".
    # Nếu không nhận dạng dạng này là fact disclosure, compiler sẽ cho semantic
    # recall xử lý và có thể biến lượt cập nhật tên thành câu hỏi memory.
    if re.search(r"\b(?:toi|minh|tui|tao|to|em|ban)\s+ten\s+(?!gi\b|la\s+gi\b|la\b)[a-z0-9_ -]{2,40}\b", norm):
        return True
    if re.search(r"\bten\s+(?:cua\s+)?toi\s+la\s+[a-z0-9_ -]{2,40}\b", norm):
        return True
    if re.search(r"\bgoi\s+toi\s+la\s+[a-z0-9_ -]{2,40}\b", norm):
        return True
    return False


UPDATE_FACT_PATTERNS = (
    "toi ten la",
    "toi la",
    "toi moi doi ten",
    "doi ten sang",
    "tu gio goi toi la",
    "nho la toi",
    "nho rang toi",
    "hay nho la toi",
    "hay nho rang toi",
    "ten toi la",
    "ten cua toi la",
    "toi ten day du la",
    "ten day du toi la",
    "ten day du cua toi la",
)


def user_is_declaring_or_updating_fact(text: str) -> bool:
    norm = normalize_vi(text)
    if not norm:
        return False
    if _looks_like_fact_update_question(norm, raw=text):
        return False
    if infer_self_disclosure_fact(norm):
        return True
    return any(pattern in norm for pattern in UPDATE_FACT_PATTERNS)


def _looks_like_fact_update_disclosure(norm: str) -> bool:
    if _looks_like_fact_update_question(norm, raw=norm):
        return False
    return any(
        re.search(pattern, norm)
        for pattern in (
            r"\btoi\s+moi\s+doi\s+ten\s+(?:sang|thanh)\s+[a-z0-9_ -]{2,60}\b",
            r"\bdoi\s+ten\s+(?:sang|thanh)\s+[a-z0-9_ -]{2,60}\b",
            r"\btu\s+gio\s+(?:cu\s+)?goi\s+toi\s+la\s+[a-z0-9_ -]{2,60}\b",
            r"\bnho\s+(?:la|rang)\s+toi\s+(?:ten\s+la|la)\s+[a-z0-9_ -]{2,60}\b",
            r"\bhay\s+nho\s+(?:la|rang)\s+toi\s+(?:ten\s+la|la)\s+[a-z0-9_ -]{2,60}\b",
        )
    )


def _looks_like_fact_update_question(norm: str, *, raw: str) -> bool:
    remember_disclosure = ("nho la toi", "nho rang toi", "hay nho la toi", "hay nho rang toi")
    if any(marker in norm for marker in remember_disclosure):
        return False
    if "?" in str(raw or ""):
        return True
    question_markers = (
        "toi ten gi",
        "ten toi la gi",
        "toi la ai",
        "toi la gi",
        "toi thich gi",
        "toi thich gi nhi",
        "toi sinh thang may",
        "toi dang o dau",
        "toi hien o dau",
    )
    return any(re.search(r"(?:^|\s)" + re.escape(marker) + r"(?:\s|$)", norm) for marker in question_markers)


def _looks_like_birth_month_disclosure(norm: str) -> bool:
    if any(marker in norm for marker in ("toi sinh thang may", "thang sinh", "sinh thang may", "birthday month")):
        return False
    return bool(
        re.search(
            r"\b(?:toi\s+)?sinh\s+(?:vao\s+)?thang\s+([0-9]{1,2}|mot|hai|ba|bon|tu|nam|sau|bay|tam|chin|muoi|muoi mot|muoi hai)\b",
            norm,
        )
    )


def _looks_like_hometown_disclosure(norm: str) -> bool:
    if any(marker in norm for marker in ("que toi o dau", "que cua toi", "hometown")):
        return False
    return bool(re.search(r"\b(?:toi\s+)?que\s+(?:o|tai|la)?\s+.{2,60}", norm))


def _looks_like_living_location_disclosure(norm: str) -> bool:
    if any(marker in norm for marker in ("toi song o dau", "noi o cua toi", "living location")):
        return False
    return bool(re.search(r"\btoi\s+(?:hien\s+)?(?:dang\s+)?(?:song|cu\s+tru)\s+(?:o|tai)?\s+.{2,60}", norm))


def _looks_like_location_preference_disclosure(norm: str) -> bool:
    if any(marker in norm for marker in ("toi thich noi nao", "toi thich o dau", "dia diem toi thich")):
        return False
    return bool(re.search(r"\btoi\s+(?:khong\s+)?thich\s+(?:o|toi|den|di\s+den)?\s+.{2,60}", norm))


def _looks_like_current_location_disclosure(norm: str) -> bool:
    if any(marker in norm for marker in ("toi dang o dau", "toi hien o dau", "toi o dau")):
        return False
    return bool(re.search(r"\btoi\s+(?:hien\s+)?(?:dang\s+)?o\s+.{2,60}", norm))


def _looks_like_past_location_disclosure(norm: str) -> bool:
    if any(marker in norm for marker in ("truoc day toi o dau", "qua khu toi o dau", "toi tung o dau")):
        return False
    if "o dau" in norm:
        return False
    return bool(re.search(r"\b(?:qua\s+khu\s+)?toi\s+(?:tung\s+)?(?:da\s+)?o\s+.{2,60}", norm))
