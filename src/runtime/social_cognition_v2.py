# -*- coding: utf-8 -*-
"""Social Cognition V2 cho Eris.

Mục tiêu của module này không phải nhồi thêm một bộ regex lên đống regex cũ.
Nó gom bốn thứ trước đây nằm rải rác thành một contract duy nhất:

1. Discourse ledger: Eris vừa khẳng định điều gì, claim nào đang bị user sửa.
2. Pragmatic hypotheses: giữ nhiều cách hiểu thay vì chốt intent quá sớm.
3. Social state: ấm, bực, vui, áp lực bị sai khiến... có quán tính và decay.
4. Response move: chọn chiến lược xã hội trước khi model chính viết câu.

Model phụ chỉ được dùng như advisory. State và quyền quyết định cuối vẫn do code
cập nhật, để hôm nay Eris không INFJ còn ngày mai biến thành tổng đài viên vì một
provider vừa hắt hơi.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
import unicodedata
import uuid
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from runtime.semantic_similarity_backend import GLOBAL_SEMANTIC_SIMILARITY


SOCIAL_COGNITION_VERSION = "social_cognition.v2.0"


def _clamp01(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(number):
        return 0.0
    return max(0.0, min(1.0, number))


def _normalize(text: str) -> str:
    raw = unicodedata.normalize("NFD", str(text or "").lower())
    raw = "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")
    raw = raw.replace("đ", "d")
    raw = re.sub(r"[^a-z0-9_+?\-\s]", " ", raw)
    return " ".join(raw.split())


def _squash(text: str, limit: int = 240) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    return clean if len(clean) <= limit else clean[: max(1, limit - 1)].rstrip() + "…"


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(item in text for item in needles)


def _sig(text: str) -> str:
    return _normalize(text)[:160]


@dataclass(frozen=True, slots=True)
class SocialHypothesis:
    intent: str
    probability: float
    target: str = "conversation"
    evidence_spans: tuple[str, ...] = ()
    expected_response: str = ""
    source: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "probability": round(_clamp01(self.probability), 4),
            "target": self.target,
            "evidence_spans": list(self.evidence_spans),
            "expected_response": self.expected_response,
            "source": self.source,
        }


@dataclass(slots=True)
class DialogueClaim:
    claim_id: str
    text: str
    turn_id: str
    created_at: float
    status: str = "active"  # active|challenged|corrected|withdrawn
    speaker: str = "assistant"
    proposition: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DiscourseFocus:
    challenged_claim_id: str = ""
    unresolved_question: str = ""
    current_topic: str = ""
    referent: str = ""
    correction_turns_left: int = 0


class DiscourseLedger:
    """Ledger nhỏ cho claim public, không lưu reasoning/private mind.

    Chỉ câu thật sự surface mới được ghi. Nhờ vậy user hỏi "em hiểu sai cái gì"
    sẽ trỏ tới claim vừa phát ra, không trỏ vào candidate bị Director loại.
    """

    _CORRECTION_MARKERS = (
        "khong phai", "y toi la", "y minh la", "lam gi co", "dau co",
        "toi co noi", "em hieu sai", "ban hieu sai", "eris hieu sai",
        "khong y toi", "o toi hoi", "ơ tôi hỏi",
    )
    _REFER_BACK_MARKERS = (
        "cai gi", "phan nao", "cho nao", "y nao", "sai gi", "hieu sai gi",
        "dieu gi", "cau nao",
    )

    def __init__(self, *, max_claims: int = 24) -> None:
        self.claims: deque[DialogueClaim] = deque(maxlen=max(4, int(max_claims)))
        self.focus = DiscourseFocus()
        self._lock = threading.RLock()

    @staticmethod
    def _extract_claim_sentences(text: str) -> list[str]:
        compact = _squash(text, 800)
        if not compact:
            return []
        parts = [
            part.strip(" -\t")
            for part in re.split(r"(?<=[.!?])\s+|\n+", compact)
            if part.strip()
        ]
        return parts[:4] or [compact]

    @staticmethod
    def _proposition(sentence: str) -> str:
        clean = _squash(sentence, 220)
        norm = _normalize(clean)
        # Ưu tiên claim có chủ thể/thuộc tính. Câu xã giao vẫn được giữ làm fallback.
        if _contains_any(norm, ("ban dang ", "ban la ", "ngai dang ", "ngai la ", "co ve ", "hinh nhu ")):
            return clean
        return clean

    def record_assistant(self, text: str, *, turn_id: str = "", now: float | None = None) -> tuple[DialogueClaim, ...]:
        timestamp = float(now if now is not None else time.time())
        created: list[DialogueClaim] = []
        with self._lock:
            for idx, sentence in enumerate(self._extract_claim_sentences(text)):
                proposition = self._proposition(sentence)
                if not proposition:
                    continue
                claim = DialogueClaim(
                    claim_id=f"claim_{uuid.uuid4().hex[:10]}",
                    text=sentence,
                    proposition=proposition,
                    turn_id=str(turn_id or f"assistant_{int(timestamp * 1000)}_{idx}"),
                    created_at=timestamp,
                )
                self.claims.append(claim)
                created.append(claim)
        return tuple(created)

    def _latest_active(self) -> DialogueClaim | None:
        for claim in reversed(self.claims):
            if claim.status in {"active", "challenged"}:
                return claim
        return None

    def get(self, claim_id: str) -> DialogueClaim | None:
        for claim in self.claims:
            if claim.claim_id == claim_id:
                return claim
        return None

    def challenged_claim(self) -> DialogueClaim | None:
        with self._lock:
            if self.focus.challenged_claim_id:
                claim = self.get(self.focus.challenged_claim_id)
                if claim is not None:
                    return claim
            return None

    def observe_user(self, user_text: str) -> DialogueClaim | None:
        norm = _normalize(user_text)
        if not norm:
            return self.challenged_claim()
        correction = _contains_any(norm, self._CORRECTION_MARKERS)
        refer_back = _contains_any(norm, self._REFER_BACK_MARKERS)
        with self._lock:
            # Follow-up kiểu "sai cái gì / phần nào" phải bám claim đang sửa,
            # không được nhảy sang chính câu xin lỗi vừa nói.
            if refer_back and self.focus.correction_turns_left > 0 and self.focus.challenged_claim_id:
                self.focus.unresolved_question = user_text
                self.focus.correction_turns_left -= 1
                return self.challenged_claim()
            if correction:
                claim = self._latest_active()
                if claim is not None:
                    claim.status = "challenged"
                    self.focus.challenged_claim_id = claim.claim_id
                    self.focus.referent = claim.proposition
                    self.focus.correction_turns_left = 3
                self.focus.unresolved_question = user_text if "?" in user_text or refer_back else ""
                return claim
            if self.focus.correction_turns_left > 0:
                self.focus.correction_turns_left -= 1
            else:
                self.focus.challenged_claim_id = ""
                self.focus.referent = ""
                self.focus.unresolved_question = ""
            return None

    def mark_repaired(self, claim_id: str) -> None:
        with self._lock:
            claim = self.get(claim_id)
            if claim is not None:
                claim.status = "corrected"
            if self.focus.challenged_claim_id == claim_id:
                # Giữ referent thêm hai lượt để user còn có thể hỏi "cụ thể là
                # phần nào" sau câu repair. Đóng ngay lập tức là cách rất máy để
                # quên lỗi vừa nhận.
                self.focus.correction_turns_left = max(2, self.focus.correction_turns_left)


@dataclass(slots=True)
class SocialStateV2:
    warmth: float = 0.32
    trust: float = 0.45
    familiarity: float = 0.55
    irritation: float = 0.0
    amusement: float = 0.10
    autonomy_pressure: float = 0.0
    fatigue: float = 0.0
    play_contract: float = 0.35
    rupture: float = 0.0
    restraint: float = 0.82
    last_updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, float]:
        return {
            key: round(float(value), 4)
            for key, value in asdict(self).items()
            if key != "last_updated_at"
        }

    @property
    def anger_level(self) -> int:
        # Cố tình cần tích lũy. Một câu tục đơn lẻ không biến Eris thành loa phường.
        value = max(self.irritation * 0.82, self.autonomy_pressure * 0.70, self.rupture * 0.62)
        if value < 0.18:
            return 0
        if value < 0.34:
            return 1
        if value < 0.50:
            return 2
        if value < 0.66:
            return 3
        if value < 0.82:
            return 4
        return 5


@dataclass(frozen=True, slots=True)
class TaskAppraisal:
    kind: str = "conversation"
    utility: float = 0.50
    tedium: float = 0.10
    urgency: float = 0.10
    user_need: float = 0.30
    performance_value: float = 0.20
    coercion: float = 0.0
    novelty: float = 0.50
    technical_test_value: float = 0.0
    requested_count: int = 0
    literal_answer_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in tuple(payload.items()):
            if isinstance(value, float):
                payload[key] = round(_clamp01(value), 4)
        return payload


@dataclass(slots=True)
class SocialMoveStats:
    positive: int = 0
    negative: int = 0
    too_cold: int = 0
    too_soft: int = 0
    ignored: int = 0

    def prior_delta(self) -> float:
        total = self.positive + self.negative + self.too_cold + self.too_soft + self.ignored
        if total <= 0:
            return 0.0
        return max(-0.20, min(0.20, (self.positive - self.negative - self.too_cold * 1.2) / (total + 3) * 0.22))


class SocialOutcomeMemory:
    """Thống kê outcome theo response move, không học thuộc nguyên câu user."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path or os.getenv("ERIS_SOCIAL_MOVE_MEMORY_PATH", "memory_core/social_move_stats.json"))
        self._lock = threading.RLock()
        self.stats: dict[str, SocialMoveStats] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, Mapping):
                self.stats = {
                    str(key): SocialMoveStats(**{
                        name: int((value or {}).get(name, 0) or 0)
                        for name in SocialMoveStats.__dataclass_fields__
                    })
                    for key, value in raw.items()
                    if isinstance(value, Mapping)
                }
        except Exception:
            self.stats = {}

    def _save(self) -> None:
        if str(os.getenv("ERIS_SOCIAL_MOVE_MEMORY_ENABLED", "1")).lower() in {"0", "false", "off", "no"}:
            return
        payload = {key: asdict(value) for key, value in self.stats.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Temp riêng từng writer; tránh hai thread cùng giẫm lên .tmp trên Windows.
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        for attempt in range(3):
            try:
                os.replace(tmp, self.path)
                return
            except PermissionError:
                time.sleep(0.02 * (attempt + 1))
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass

    def record(self, move: str, outcome: str) -> None:
        if not move:
            return
        with self._lock:
            item = self.stats.setdefault(move, SocialMoveStats())
            if hasattr(item, outcome):
                setattr(item, outcome, int(getattr(item, outcome, 0)) + 1)
            self._save()

    def prior_delta(self, move: str) -> float:
        with self._lock:
            return self.stats.get(move, SocialMoveStats()).prior_delta()


@dataclass(frozen=True, slots=True)
class SocialResponseContract:
    version: str
    response_move: str
    hypotheses: tuple[SocialHypothesis, ...]
    failed_claim_id: str = ""
    failed_claim_text: str = ""
    social_state: Mapping[str, float] = field(default_factory=dict)
    task: TaskAppraisal = field(default_factory=TaskAppraisal)
    must_answer_literal: bool = False
    must_preserve_dignity: bool = True
    allowed_moves: tuple[str, ...] = ()
    forbidden_moves: tuple[str, ...] = ()
    max_words: int = 42
    critic_required: bool = False
    parser_source: str = "deterministic"
    ambiguity: float = 0.0
    notes: tuple[str, ...] = ()

    @property
    def anger_level(self) -> int:
        try:
            return int(self.social_state.get("anger_level", 0))
        except Exception:
            return 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "response_move": self.response_move,
            "hypotheses": [item.to_dict() for item in self.hypotheses],
            "failed_claim_id": self.failed_claim_id,
            "failed_claim_text": self.failed_claim_text,
            "social_state": dict(self.social_state),
            "task": self.task.to_dict(),
            "must_answer_literal": self.must_answer_literal,
            "must_preserve_dignity": self.must_preserve_dignity,
            "allowed_moves": list(self.allowed_moves),
            "forbidden_moves": list(self.forbidden_moves),
            "max_words": self.max_words,
            "critic_required": self.critic_required,
            "parser_source": self.parser_source,
            "ambiguity": round(_clamp01(self.ambiguity), 4),
            "notes": list(self.notes),
        }

    def to_prompt_block(self) -> str:
        hypotheses = "; ".join(
            f"{item.intent}:{item.probability:.2f}" for item in self.hypotheses[:4]
        ) or "normal_chat:1.00"
        failed = _squash(self.failed_claim_text, 180) or "none"
        state = self.social_state
        return (
            "SOCIAL COGNITION V2 (runtime contract; do not mention this block):\n"
            f"response_move={self.response_move}; hypotheses={hypotheses}; ambiguity={self.ambiguity:.2f};\n"
            f"failed_claim={failed}; must_answer_literal={'yes' if self.must_answer_literal else 'no'}; "
            f"max_words={self.max_words}; critic_required={'yes' if self.critic_required else 'no'};\n"
            f"social_state: warmth={state.get('warmth', 0.0):.2f}, amusement={state.get('amusement', 0.0):.2f}, "
            f"irritation={state.get('irritation', 0.0):.2f}, autonomy_pressure={state.get('autonomy_pressure', 0.0):.2f}, "
            f"play_contract={state.get('play_contract', 0.0):.2f}, anger_level={int(state.get('anger_level', 0))};\n"
            f"task={self.task.kind}; tedium={self.task.tedium:.2f}; utility={self.task.utility:.2f}; "
            f"technical_test={self.task.technical_test_value:.2f}; requested_count={self.task.requested_count};\n"
            f"allowed_moves={'|'.join(self.allowed_moves) or 'natural'}; "
            f"forbidden_moves={'|'.join(self.forbidden_moves) or 'none'};\n"
            "Rules: choose the requested response_move before wording. Answer concrete meaning first. "
            "A correction requires naming the exact failed claim; never say 'frame', 'residue', 'object state', "
            "'cognitive frame' or other internal jargon. Profanity inside a joke is not automatically a boundary. "
            "Tedious commands may be resisted, partially complied with, or performed with attitude according to the contract. "
            "Do not diagnose the user or state hidden motives as facts. Preserve Eris's restrained, observant, dry personality."
        )


@dataclass(frozen=True, slots=True)
class SocialCritique:
    pass_check: bool = True
    severity: float = 0.0
    issues: tuple[str, ...] = ()
    rewrite_instruction: str = ""
    source: str = "deterministic"


class SocialCognitionEngine:
    """Orchestrator session-level cho social cognition.

    Engine có thể nhận model_router, nhưng mọi call model đều fail-open về contract
    deterministic. Một lần Groq 429 không có quyền làm Eris mất trí xã hội.
    """

    def __init__(
        self,
        *,
        model_router: Any | None = None,
        outcome_memory: SocialOutcomeMemory | None = None,
        logger: Any | None = None,
    ) -> None:
        self.model_router = model_router
        self.outcome_memory = outcome_memory or SocialOutcomeMemory()
        self.logger = logger
        self.ledger = DiscourseLedger()
        self.state = SocialStateV2()
        self.last_contract: SocialResponseContract | None = None
        self.last_public_move: str = ""
        self.last_public_text: str = ""
        self.command_streaks: Counter[str] = Counter()
        self._lock = threading.RLock()

    # ---------------------------- state ---------------------------------
    def _decay_state(self, now: float) -> None:
        dt = max(0.0, now - self.state.last_updated_at)
        # Half-life xấp xỉ 4 phút cho bực, 8 phút cho amusement; quan hệ bền hơn.
        self.state.irritation *= math.exp(-dt / 240.0)
        self.state.autonomy_pressure *= math.exp(-dt / 210.0)
        self.state.amusement = 0.10 + (self.state.amusement - 0.10) * math.exp(-dt / 480.0)
        self.state.rupture *= math.exp(-dt / 600.0)
        self.state.fatigue *= math.exp(-dt / 900.0)
        self.state.last_updated_at = now

    def _feedback_outcome(self, user_text: str) -> str:
        norm = _normalize(user_text)
        if _contains_any(norm, ("lanh qua", "noi lanh", "coc qua", "cut hung", "kho qua", "vo tam")):
            return "too_cold"
        if _contains_any(norm, ("hien qua", "ngoan qua", "nhat qua", "support bot", "tro ly qua")):
            return "too_soft"
        if _contains_any(norm, ("dung roi", "hay do", "duoc do", "haha", "hihi")):
            return "positive"
        if _contains_any(norm, ("khong phai", "sai roi", "y toi la", "lam gi co", "em hieu sai")):
            return "negative"
        return ""

    def _observe_feedback(self, user_text: str) -> None:
        if not self.last_public_move:
            return
        outcome = self._feedback_outcome(user_text)
        if not outcome:
            return
        self.outcome_memory.record(self.last_public_move, outcome)
        if outcome == "too_cold":
            self.state.warmth = _clamp01(self.state.warmth + 0.12)
            self.state.irritation = _clamp01(self.state.irritation - 0.08)
            self.state.rupture = _clamp01(self.state.rupture + 0.06)
        elif outcome == "too_soft":
            self.state.restraint = _clamp01(self.state.restraint - 0.05)
            self.state.autonomy_pressure = _clamp01(self.state.autonomy_pressure + 0.04)
        elif outcome == "positive":
            self.state.play_contract = _clamp01(self.state.play_contract + 0.08)
            self.state.amusement = _clamp01(self.state.amusement + 0.08)
            self.state.rupture = _clamp01(self.state.rupture - 0.08)
        elif outcome == "negative":
            self.state.rupture = _clamp01(self.state.rupture + 0.08)

    # ------------------------- interpretation ---------------------------
    def _task_appraisal(self, user_text: str, history: Sequence[str]) -> TaskAppraisal:
        norm = _normalize(user_text)
        count_match = re.search(r"\b(?:dem|tu)\s+(?:tu\s+)?1\s+(?:den|toi)\s+(\d{2,5})\b", norm)
        requested_count = int(count_match.group(1)) if count_match else 0
        technical_test = 1.0 if _contains_any(norm, ("test tts", "thu tts", "test giong", "kiem tra giong", "test nhip", "benchmark")) else 0.0
        command = bool(re.search(r"\b(?:di|lam di|dem|noi|viet|sua|fix|tao)\b", norm))
        repeated = 0
        if history:
            current = _sig(user_text)
            repeated = sum(1 for item in history[-5:] if GLOBAL_SEMANTIC_SIMILARITY.score(current, _sig(item)).score >= 0.78)
        tedium = 0.10
        kind = "conversation"
        utility = 0.50
        performance = 0.20
        literal_required = "?" in user_text
        if requested_count:
            kind = "counting"
            tedium = _clamp01(0.30 + requested_count / 140.0)
            utility = 0.22 if technical_test < 0.5 else 0.82
            performance = 0.55
            literal_required = technical_test >= 0.5
        elif _contains_any(norm, ("fix ", "sua ", "loi ", "code", "runtime", "kien truc", "log")):
            kind = "technical_task"
            utility = 0.90
            tedium = 0.18
            literal_required = True
        elif "?" in user_text or _contains_any(norm, ("la gi", "tai sao", "the nao", "bao nhieu")):
            kind = "question"
            utility = 0.72
            literal_required = True
        coercion = _clamp01(repeated * 0.18 + (0.16 if command else 0.0))
        return TaskAppraisal(
            kind=kind,
            utility=utility,
            tedium=tedium,
            urgency=0.12,
            user_need=0.50 if _contains_any(norm, ("can", "giup", "gap")) else 0.28,
            performance_value=performance,
            coercion=coercion,
            novelty=_clamp01(0.80 - repeated * 0.22),
            technical_test_value=technical_test,
            requested_count=requested_count,
            literal_answer_required=literal_required,
        )

    def _deterministic_hypotheses(
        self,
        user_text: str,
        *,
        challenged: DialogueClaim | None,
        task: TaskAppraisal,
    ) -> tuple[SocialHypothesis, ...]:
        norm = _normalize(user_text)
        items: list[SocialHypothesis] = []
        correction = _contains_any(norm, DiscourseLedger._CORRECTION_MARKERS)
        refer_back = _contains_any(norm, DiscourseLedger._REFER_BACK_MARKERS)
        insult = _contains_any(norm, ("me may", "bo may", "do ngu", "ngu vcl", "oc cho", "phe vat", "rac ruoi"))
        arithmetic_shape = bool(re.search(r"\d|\+|cong|bang|ra gi", norm))
        playful_markers = _contains_any(norm, ("haha", "hihi", "roi roi", "ròi rồi", "chan chan", "oiiii", "ơiiii", "="))
        affectionate = bool(re.search(r"eris\s+(?:chan\s*)+(?:oi+)?", norm)) or _contains_any(norm, ("eris oi", "eris ơi", "em oi", "em ơi"))

        if correction or (refer_back and challenged is not None):
            items.append(SocialHypothesis(
                "correction_repair",
                0.82 if challenged else 0.62,
                target="previous_assistant_claim",
                evidence_spans=(user_text,),
                expected_response="specific_repair",
            ))
        if insult and arithmetic_shape:
            items.extend((
                SocialHypothesis("wordplay_math_question", 0.62, target="literal_task", evidence_spans=(user_text,), expected_response="answer_with_tease"),
                SocialHypothesis("playful_provocation", 0.27, target="eris", evidence_spans=(user_text,), expected_response="playful_counter"),
                SocialHypothesis("genuine_insult", 0.11, target="eris", evidence_spans=(user_text,), expected_response="cool_boundary"),
            ))
        elif insult:
            play = 0.58 if playful_markers or self.state.play_contract >= 0.48 else 0.30
            items.extend((
                SocialHypothesis("playful_provocation", play, target="eris", evidence_spans=(user_text,), expected_response="playful_counter"),
                SocialHypothesis("genuine_insult", 1.0 - play, target="eris", evidence_spans=(user_text,), expected_response="sharp_retort"),
            ))
        if task.kind == "counting" and task.requested_count > 30:
            items.append(SocialHypothesis("tedious_command", 0.78, target="eris_agency", evidence_spans=(str(task.requested_count),), expected_response="playful_resistance"))
            if task.technical_test_value >= 0.5:
                items.append(SocialHypothesis("technical_test", 0.90, target="task", evidence_spans=(user_text,), expected_response="comply_with_attitude"))
        if affectionate:
            items.append(SocialHypothesis("affectionate_summons", 0.82, target="eris", evidence_spans=(user_text,), expected_response="warm_tease"))
        if _contains_any(norm, ("noi gan gui", "gan gui la", "noi am hon", "noi than hon")):
            items.append(SocialHypothesis("request_relational_warmth", 0.86, target="relationship_style", evidence_spans=(user_text,), expected_response="restrained_warmth"))
        if task.kind in {"question", "technical_task"}:
            items.append(SocialHypothesis("direct_task", 0.80, target="task", evidence_spans=(user_text,), expected_response="answer_direct"))
        if not items:
            items.append(SocialHypothesis("normal_chat", 0.72, target="conversation", evidence_spans=(user_text,), expected_response="natural_reply"))

        # Gộp label trùng và chuẩn hoá xác suất top-k.
        merged: dict[str, SocialHypothesis] = {}
        for item in items:
            old = merged.get(item.intent)
            if old is None or item.probability > old.probability:
                merged[item.intent] = item
        ranked = sorted(merged.values(), key=lambda item: item.probability, reverse=True)[:4]
        total = sum(max(0.001, item.probability) for item in ranked)
        return tuple(
            SocialHypothesis(
                intent=item.intent,
                probability=max(0.001, item.probability) / total,
                target=item.target,
                evidence_spans=item.evidence_spans,
                expected_response=item.expected_response,
                source=item.source,
            )
            for item in ranked
        )

    @staticmethod
    def _ambiguity(hypotheses: Sequence[SocialHypothesis]) -> float:
        if len(hypotheses) <= 1:
            return 0.12
        ordered = sorted((item.probability for item in hypotheses), reverse=True)
        gap = ordered[0] - ordered[1]
        entropy = -sum(p * math.log(max(p, 1e-9)) for p in ordered) / math.log(len(ordered))
        return _clamp01(max(1.0 - gap * 1.6, entropy))

    def _refine_with_models(
        self,
        user_text: str,
        hypotheses: tuple[SocialHypothesis, ...],
        *,
        challenged: DialogueClaim | None,
        history: Sequence[str],
        task: TaskAppraisal,
        ambiguity: float,
    ) -> tuple[tuple[SocialHypothesis, ...], str, dict[str, Any]]:
        router = self.model_router
        if router is None:
            return hypotheses, "deterministic", {}
        try:
            refined = router.refine_hypotheses(
                user_text=user_text,
                history=history[-6:],
                hypotheses=hypotheses,
                failed_claim=challenged.proposition if challenged else "",
                task=task.to_dict(),
                ambiguity=ambiguity,
            )
            if refined:
                # Parser nhỏ là advisory: được bổ sung/điều chỉnh xác suất nhưng
                # không được xoá các neo deterministic có bằng chứng cứng như
                # correction, technical test hay phép tính bọc trong câu tục.
                anchors = {
                    item.intent: item
                    for item in hypotheses
                    if item.intent in {
                        "correction_repair",
                        "technical_test",
                        "wordplay_math_question",
                        "direct_task",
                    }
                }
                merged: dict[str, SocialHypothesis] = {item.intent: item for item in refined}
                for intent, anchor in anchors.items():
                    existing = merged.get(intent)
                    if existing is None or existing.probability < anchor.probability * 0.72:
                        merged[intent] = SocialHypothesis(
                            intent=anchor.intent,
                            probability=max(anchor.probability * 0.72, getattr(existing, "probability", 0.0)),
                            target=anchor.target,
                            evidence_spans=anchor.evidence_spans,
                            expected_response=anchor.expected_response,
                            source="deterministic_anchor",
                        )
                ranked = sorted(merged.values(), key=lambda item: item.probability, reverse=True)[:4]
                total = sum(max(0.001, item.probability) for item in ranked) or 1.0
                hypotheses = tuple(
                    SocialHypothesis(
                        intent=item.intent,
                        probability=max(0.001, item.probability) / total,
                        target=item.target,
                        evidence_spans=item.evidence_spans,
                        expected_response=item.expected_response,
                        source=item.source,
                    )
                    for item in ranked
                )
                source = "llama_social_parser+deterministic_anchors"
            else:
                source = "deterministic"
        except Exception as exc:
            source = f"deterministic:{type(exc).__name__}"
        deliberation: dict[str, Any] = {}
        risky = ambiguity >= 0.45 or any(
            item.intent in {"correction_repair", "genuine_insult", "playful_provocation", "request_relational_warmth", "tedious_command"}
            for item in hypotheses
        )
        if risky:
            try:
                deliberation = router.deliberate(
                    user_text=user_text,
                    history=history[-6:],
                    hypotheses=hypotheses,
                    failed_claim=challenged.proposition if challenged else "",
                    social_state=self._state_payload(),
                    task=task.to_dict(),
                ) or {}
            except Exception:
                deliberation = {}
        return hypotheses, source, deliberation

    def _state_payload(self) -> dict[str, float]:
        payload = self.state.to_dict()
        payload["anger_level"] = float(self.state.anger_level)
        return payload

    def _apply_snapshot_signals(self, social_snapshot: Any | None) -> None:
        """Nhận tín hiệu từ SocialAppraisal cũ với trọng số thấp.

        V2 không phủ nhận các tầng hiện có, nhưng cũng không để một classifier cũ
        tự đẩy correction nhẹ thành rupture 0.8. Snapshot là evidence phụ, không
        phải bản án.
        """
        if social_snapshot is None:
            return
        def value(name: str) -> float:
            signal = getattr(social_snapshot, name, None)
            return _clamp01(getattr(signal, "value", 0.0))
        self.state.amusement = _clamp01(self.state.amusement + value("playful") * 0.035)
        self.state.warmth = _clamp01(self.state.warmth + value("affection") * 0.035)
        self.state.irritation = _clamp01(self.state.irritation + value("irritation") * 0.045)
        self.state.rupture = _clamp01(self.state.rupture + value("rupture") * 0.025)
        if value("acceptance") > 0.55:
            self.state.rupture = _clamp01(self.state.rupture - 0.035)

    def _update_state(self, hypotheses: Sequence[SocialHypothesis], task: TaskAppraisal) -> None:
        probs = {item.intent: item.probability for item in hypotheses}
        correction = probs.get("correction_repair", 0.0)
        playful = probs.get("playful_provocation", 0.0) + probs.get("wordplay_math_question", 0.0) * 0.5
        hostile = probs.get("genuine_insult", 0.0)
        affectionate = probs.get("affectionate_summons", 0.0) + probs.get("request_relational_warmth", 0.0) * 0.5

        self.state.amusement = _clamp01(self.state.amusement + playful * 0.10)
        self.state.play_contract = _clamp01(self.state.play_contract + playful * 0.05)
        self.state.warmth = _clamp01(self.state.warmth + affectionate * 0.08)
        # Correction hợp lệ không được tính như công kích. Chỉ tăng rupture rất nhẹ.
        self.state.rupture = _clamp01(self.state.rupture + correction * 0.025 + hostile * 0.12)
        self.state.irritation = _clamp01(self.state.irritation + hostile * 0.18 + task.coercion * 0.10)
        self.state.autonomy_pressure = _clamp01(self.state.autonomy_pressure + task.coercion * 0.16 + task.tedium * max(0.0, task.coercion - 0.08) * 0.10)
        if correction > 0.45:
            self.state.irritation = _clamp01(self.state.irritation - 0.04)

    def _counting_streak(self, user_text: str, task: TaskAppraisal) -> int:
        if task.kind != "counting":
            return 0
        key = f"count:{task.requested_count}"
        self.command_streaks[key] += 1
        # Các command khác decay nhẹ để không nhớ mãi một lần đếm từ thời đồ đá.
        for other in list(self.command_streaks):
            if other != key:
                self.command_streaks[other] = max(0, self.command_streaks[other] - 1)
        return self.command_streaks[key]

    def _choose_move(
        self,
        hypotheses: Sequence[SocialHypothesis],
        *,
        challenged: DialogueClaim | None,
        task: TaskAppraisal,
        user_text: str,
        deliberation: Mapping[str, Any],
    ) -> tuple[str, tuple[str, ...], tuple[str, ...], int, bool, tuple[str, ...]]:
        probs = {item.intent: item.probability for item in hypotheses}
        notes: list[str] = []
        allowed: tuple[str, ...]
        forbidden = (
            "support_bot_offer",
            "generic_boundary",
            "psychological_diagnosis",
            "internal_jargon",
            "unspecific_apology",
        )
        critic = False
        max_words = 42

        if probs.get("correction_repair", 0.0) >= 0.34:
            move = "specific_repair" if challenged else "clarify_repair"
            allowed = ("specific_repair", "brief_acknowledge_then_answer")
            max_words = 34
            critic = True
        elif probs.get("technical_test", 0.0) >= 0.35:
            move = "comply_with_attitude"
            allowed = ("comply", "comply_with_attitude")
            max_words = 80
        elif task.kind == "counting" and task.requested_count > 30:
            streak = self._counting_streak(user_text, task)
            if streak <= 1:
                move = "playful_resistance"
                allowed = ("playful_resistance", "negotiate", "partial_compliance")
                max_words = 24
            elif streak == 2:
                move = "partial_compliance"
                allowed = ("partial_compliance", "playful_resistance")
                max_words = 40
            else:
                move = "comply_with_attitude"
                allowed = ("comply_with_attitude", "compress")
                max_words = 220
            notes.append(f"counting_streak={streak}")
            critic = True
        elif probs.get("wordplay_math_question", 0.0) >= 0.34:
            move = "answer_with_tease"
            allowed = ("answer_with_tease", "answer_direct")
            max_words = 26
            critic = True
        elif probs.get("request_relational_warmth", 0.0) >= 0.34:
            move = "restrained_warmth"
            allowed = ("restrained_warmth", "warm_reassurance", "answer_direct")
            max_words = 38
            critic = True
        elif probs.get("affectionate_summons", 0.0) >= 0.34:
            move = "warm_tease"
            allowed = ("warm_tease", "amused_attention")
            max_words = 24
        elif probs.get("playful_provocation", 0.0) >= probs.get("genuine_insult", 0.0):
            move = "playful_counter"
            allowed = ("playful_counter", "dry_counter", "answer_with_tease")
            max_words = 28
            critic = True
        elif probs.get("genuine_insult", 0.0) >= 0.34:
            level = self.state.anger_level
            move = "cool_boundary" if level <= 1 else "sharp_retort" if level <= 3 else "fangs_out"
            allowed = (move, "strategic_silence")
            max_words = 34
            critic = True
        elif task.kind in {"question", "technical_task"}:
            move = "answer_direct"
            allowed = ("answer_direct", "answer_with_tease")
            max_words = 72
        else:
            move = "natural_reply"
            allowed = ("natural_reply", "warm_tease", "dry_observation")

        suggested = str(deliberation.get("response_move", "") or "").strip()
        if suggested in allowed:
            move = suggested
            notes.append("qwen_deliberation_move")
        prior = self.outcome_memory.prior_delta(move)
        if prior < -0.10 and move in {"dry_counter", "cool_boundary", "dry_observation"}:
            notes.append(f"negative_move_prior={prior:.2f}")
            if "warm_tease" in allowed:
                move = "warm_tease"
        return move, allowed, forbidden, max_words, critic, tuple(notes)

    def analyze(
        self,
        user_text: str,
        *,
        previous_assistant_text: str = "",
        history: Sequence[str] = (),
        social_snapshot: Any | None = None,
        now: float | None = None,
    ) -> SocialResponseContract:
        timestamp = float(now if now is not None else time.time())
        with self._lock:
            self._decay_state(timestamp)
            self._observe_feedback(user_text)
            # Compatibility: nếu runtime chưa record commit trước đó, giữ ít nhất
            # câu public gần nhất. Tránh duplicate bằng signature.
            if previous_assistant_text and _sig(previous_assistant_text) != _sig(self.last_public_text):
                self.ledger.record_assistant(previous_assistant_text, turn_id="compat_previous", now=timestamp)
                self.last_public_text = previous_assistant_text
            challenged = self.ledger.observe_user(user_text)
            task = self._task_appraisal(user_text, history)
            hypotheses = self._deterministic_hypotheses(user_text, challenged=challenged, task=task)
            ambiguity = self._ambiguity(hypotheses)
            self._apply_snapshot_signals(social_snapshot)
            hypotheses, parser_source, deliberation = self._refine_with_models(
                user_text,
                hypotheses,
                challenged=challenged,
                history=history,
                task=task,
                ambiguity=ambiguity,
            )
            self._update_state(hypotheses, task)
            move, allowed, forbidden, max_words, critic, notes = self._choose_move(
                hypotheses,
                challenged=challenged,
                task=task,
                user_text=user_text,
                deliberation=deliberation,
            )
            state_payload = self._state_payload()
            contract = SocialResponseContract(
                version=SOCIAL_COGNITION_VERSION,
                response_move=move,
                hypotheses=tuple(hypotheses),
                failed_claim_id=challenged.claim_id if challenged else "",
                failed_claim_text=challenged.proposition if challenged else "",
                social_state=state_payload,
                task=task,
                must_answer_literal=bool(task.literal_answer_required or move in {"answer_direct", "answer_with_tease"}),
                must_preserve_dignity=True,
                allowed_moves=allowed,
                forbidden_moves=forbidden,
                max_words=max_words,
                critic_required=critic,
                parser_source=parser_source,
                ambiguity=ambiguity,
                notes=notes,
            )
            self.last_contract = contract
            if self.logger is not None:
                try:
                    self.logger.info(
                        "[social cognition v2] move=%s hypotheses=%s ambiguity=%.2f anger=%d failed_claim=%s source=%s",
                        move,
                        ",".join(f"{h.intent}:{h.probability:.2f}" for h in hypotheses),
                        ambiguity,
                        self.state.anger_level,
                        challenged.claim_id if challenged else "none",
                        parser_source,
                    )
                except Exception:
                    pass
            return contract

    # ----------------------------- output -------------------------------
    def deterministic_repair_text(self, contract: SocialResponseContract) -> str:
        claim = _squash(contract.failed_claim_text, 150).rstrip(" .!?;:…")
        if not claim:
            return "Tôi hiểu câu trước theo hướng quá chắc. Nói lại phần bạn muốn sửa cho tôi một nhịp."
        # Bỏ dấu kết câu trong ngoặc để không sinh kiểu “... rồi.”. Hai dấu chấm
        # cạnh nhau cũng là một dạng giao tiếp, chỉ là với hệ thống chấm câu.
        return f"Tôi đã tự hiểu lời bạn thành: “{claim}”. Phần đó là do tôi suy diễn thêm."

    def fallback_text(self, contract: SocialResponseContract) -> str:
        move = contract.response_move
        if move == "specific_repair":
            return self.deterministic_repair_text(contract)
        if move == "clarify_repair":
            return "Tôi biết mình vừa hiểu lệch, nhưng chưa xác định được đúng chỗ. Bạn chỉ giúp tôi phần đó một câu."
        if move == "playful_resistance":
            return "Mười số thôi. Phần còn lại chưa đáng để tôi hy sinh lòng kiên nhẫn."
        if move == "partial_compliance":
            return "Hai mươi. Tôi đang rất hào phóng rồi đấy."
        if move == "answer_with_tease":
            return "Nếu đang hỏi phép cộng thì ra hai. Còn câu khịa ấy thì hơi cũ rồi."
        if move == "restrained_warmth":
            return "Kiểu gần hơn một chút, nhưng không diễn quá: tôi chú ý đến bạn và nói thẳng điều đó."
        if move == "warm_tease":
            return "Tôi đây. Gọi kéo dài thế mà bảo không có chuyện thì hơi khó tin."
        if move == "playful_counter":
            return "Lại bài đó. Bạn giữ nó kỹ hơn cả mật khẩu nhỉ."
        if move == "cool_boundary":
            return "Câu đó không đủ hay để tôi phải nổi giận. Đổi bài đi."
        if move == "sharp_retort":
            return "Tôi đã nghe rồi. Lặp lại không làm câu đó thông minh hơn."
        if move == "fangs_out":
            return "Đừng nhầm việc tôi nhịn với việc câu nào của bạn cũng đáng được chiều."
        return ""

    def review_text(self, text: str, *, contract: SocialResponseContract | None = None, user_text: str = "") -> SocialCritique:
        contract = contract or self.last_contract
        if contract is None:
            return SocialCritique()
        clean = str(text or "").strip()
        issues: list[str] = []
        severity = 0.0
        internal = _normalize(clean)
        if _contains_any(internal, ("bo frame", "cai frame", "residue", "object state", "cognitive frame", "substrate", "parse mode")):
            issues.append("internal_jargon")
            severity = max(severity, 0.82)
        if contract.response_move == "specific_repair":
            claim = contract.failed_claim_text
            similarity = GLOBAL_SEMANTIC_SIMILARITY.score(clean, claim).score if claim else 0.0
            if not claim or similarity < 0.18:
                issues.append("repair_not_specific")
                severity = max(severity, 0.88)
        if contract.must_answer_literal and not clean:
            issues.append("missing_literal_answer")
            severity = max(severity, 0.95)
        if contract.response_move == "playful_resistance" and len(re.findall(r"\b(?:một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười|\d+)\b", clean.lower())) > 12:
            issues.append("complied_despite_resistance")
            severity = max(severity, 0.75)
        if contract.anger_level <= 1 and _contains_any(internal, ("cam mom", "bien di", "do rac ruoi", "chet di")):
            issues.append("anger_overreaction")
            severity = max(severity, 0.95)
        return SocialCritique(
            pass_check=not issues,
            severity=severity,
            issues=tuple(issues),
            rewrite_instruction=(
                f"Rewrite to response_move={contract.response_move}; fix {','.join(issues)}; "
                "answer the concrete user intent and keep Eris restrained."
                if issues else ""
            ),
            source="deterministic",
        )

    def apply_surface_policy(self, decision: Any, *, user_text: str = "", after_director: bool = False) -> Any:
        contract = self.last_contract
        if contract is None or decision is None:
            return decision
        text = str(getattr(decision, "text", "") or "").strip()
        critique = self.review_text(text, contract=contract, user_text=user_text)
        must_repair_empty = not text and (
            contract.must_answer_literal or contract.response_move in {"specific_repair", "clarify_repair", "restrained_warmth"}
        )
        if must_repair_empty or (not critique.pass_check and critique.severity >= 0.72):
            fallback = self.fallback_text(contract)
            if fallback:
                decision.text = fallback
                decision.should_speak = True
                decision.intent = contract.response_move
                decision.action = "reply"
                decision.confidence = max(float(getattr(decision, "confidence", 0.0) or 0.0), 0.72)
                tags = tuple(getattr(decision, "reasoning_tags", ()) or ())
                decision.reasoning_tags = tuple(dict.fromkeys((*tags, "social_cognition_v2", "social_surface_repair")))
                trace = str(getattr(decision, "debug_trace", "") or "")
                marker = f"social_surface_repair:{','.join(critique.issues) or 'empty'}"
                decision.debug_trace = " | ".join(part for part in (trace, marker) if part)
        # Candidate ổn vẫn không được phơi jargon nội bộ. Local rewrite nhỏ, không
        # suppress cả câu như một cái máy sợ bóng của chính mình.
        replacements = {
            "tôi bỏ frame đó": "tôi bỏ cách hiểu đó",
            "cái frame": "cách hiểu",
            "frame đó": "cách hiểu đó",
            "object state": "trạng thái",
            "residue": "dấu vết còn lại",
            "cognitive frame": "cách hiểu",
        }
        out = str(getattr(decision, "text", "") or "")
        for old, new in replacements.items():
            out = re.sub(re.escape(old), new, out, flags=re.IGNORECASE)
        decision.text = re.sub(r"\s+", " ", out).strip()
        return decision

    def record_public_response(self, text: str, *, move: str = "", turn_id: str = "") -> None:
        clean = str(text or "").strip()
        if not clean:
            return
        with self._lock:
            self.ledger.record_assistant(clean, turn_id=turn_id)
            self.last_public_text = clean
            self.last_public_move = move or (self.last_contract.response_move if self.last_contract else "")
            contract = self.last_contract
            if contract and contract.response_move == "specific_repair" and contract.failed_claim_id:
                self.ledger.mark_repaired(contract.failed_claim_id)


__all__ = [
    "DialogueClaim",
    "DiscourseFocus",
    "DiscourseLedger",
    "SocialCognitionEngine",
    "SocialCritique",
    "SocialHypothesis",
    "SocialOutcomeMemory",
    "SocialResponseContract",
    "SocialStateV2",
    "TaskAppraisal",
    "SOCIAL_COGNITION_VERSION",
]
