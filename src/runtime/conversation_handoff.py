# -*- coding: utf-8 -*-
"""Conversation handoff + causal discourse state for ERIS V71.

Mục tiêu của module này không phải đoán tâm lý người dùng từ một câu rời rạc.
Nó giữ *trạng thái giữa hai người*: lượt nào vừa xảy ra, việc gì còn dang dở,
ai đang nợ lượt kế tiếp, và phản ứng hiện tại có khả năng là hậu quả của chính
câu ERIS vừa nói hay không.

Điểm quan trọng:
- Handoff là state hội thoại, không phải long-term memory.
- Causal hypotheses luôn là giả thuyết có confidence + evidence, không biến thành fact.
- Một phản ứng khó chịu/confused ngay sau câu ERIS phải khiến runtime kiểm tra
  ``self_caused_reaction`` trước khi hỏi ngược user như thể chuyện rơi từ trời xuống.
- State này được đưa vào Subject/Neuro *trước* khi chọn action, không đợi Surface cứu.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import math
import re
import time
from typing import Any, Mapping, Sequence

from runtime.public_causal_receipt import PublicCausalReceipt, normalize_semantic_owner


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if not math.isfinite(number):
        number = default
    return max(0.0, min(1.0, number))


def _compact(text: Any, limit: int = 420) -> str:
    return " ".join(str(text or "").split())[: max(16, int(limit))]


def _norm(text: Any) -> str:
    return _compact(text, 2000).lower()


def _contains_any(text: str, phrases: Sequence[str]) -> bool:
    lowered = _norm(text)
    return any(phrase in lowered for phrase in phrases)


_TOPIC_CLOSURE_RE = re.compile(
    r"(?:\b(?:đổi|chuyển)\s+(?:chủ đề|đề tài|chuyện|cái khác)\b"
    r"|\b(?:nói|bàn|chuyển sang)\s+(?:chuyện|cái|chủ đề)\s+khác\b"
    r"|\b(?:bỏ|cho qua|khép|dừng|thôi)\s+(?:qua\s+)?(?:vụ|chuyện|chủ đề|cái)?\s*(?:này|đó|ấy)?\b"
    r"|\b(?:coi như|cho)\s+(?:vụ|chuyện|cái)?\s*.+?\s+(?:đi vào dĩ vãng|qua rồi|xong rồi)\b"
    r"|\bđi vào dĩ vãng\b|\bđừng nhắc(?: lại)? nữa\b|\bkhông bàn(?: nữa)?\b"
    r"|\b(?:change|switch)\s+(?:the\s+)?topic\b|\bmove\s+on\b|\blet(?:'s| us)\s+(?:leave|drop)\s+(?:that|it)\b)",
    re.IGNORECASE,
)


def _explicit_topic_closure(text: Any) -> bool:
    cleaned = _compact(text, 1000)
    return bool(cleaned and _TOPIC_CLOSURE_RE.search(cleaned))


def _assistant_complexity(text: str) -> float:
    """Ước lượng độ khó của câu trước bằng đặc trưng cơ học, không phán nội dung.

    Đây chỉ là một feature trong causal prior. Nó không đủ để kết luận user không
    hiểu; kết luận luôn cần reaction signal từ user và temporal/discourse adjacency.
    """
    cleaned = _compact(text, 2400)
    if not cleaned:
        return 0.0
    words = re.findall(r"\w+", cleaned, flags=re.UNICODE)
    clauses = len(re.findall(r"[,;:—–-]", cleaned)) + cleaned.count(" và ") + cleaned.count(" nhưng ")
    length_score = _clamp01((len(words) - 18) / 48.0)
    clause_score = _clamp01(clauses / 8.0)
    abstract_markers = (
        "ý nghĩa", "bản chất", "hiện diện", "tự soi", "tự tham chiếu", "lăng kính",
        "mục đích", "nhị nguyên", "trừu tượng", "continuity", "identity", "semantic",
    )
    abstract_score = _clamp01(sum(1 for item in abstract_markers if item in cleaned.lower()) / 4.0)
    return _clamp01(0.48 * length_score + 0.30 * clause_score + 0.22 * abstract_score)


@dataclass(frozen=True, slots=True)
class CausalHypothesis:
    kind: str
    confidence: float
    summary: str
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "confidence": round(_clamp01(self.confidence), 4),
            "summary": _compact(self.summary, 500),
            "evidence_refs": list(self.evidence_refs[:10]),
        }


@dataclass(frozen=True, slots=True)
class ConversationHandoff:
    revision: int = 0
    updated_at: float = 0.0
    last_user_text: str = ""
    last_assistant_text: str = ""
    last_user_turn_ref: str = ""
    last_assistant_turn_ref: str = ""
    last_user_turn_index: int = 0
    last_assistant_turn_index: int = 0
    unresolved_intent: str = ""
    unresolved_intent_owner: str = "unknown"
    pending_shared_goal: str = ""
    pending_shared_goal_owner: str = "unknown"
    # V93: provenance public gần nhất để ERIS không phải đoán ngược lý do mình nói.
    last_public_semantic_owner: str = "unknown"
    last_public_trigger_owner: str = "unknown"
    last_public_causal_receipt: Mapping[str, Any] = field(default_factory=dict)
    self_explanation_requested: bool = False
    next_move_owner: str = "none"  # eris | user | shared | none
    user_stance: str = "unknown"
    eris_commitment: str = ""
    topic_closed: bool = False
    topic_closure_text: str = ""
    conversation_move_hint: str = ""
    continuity_pressure: float = 0.0
    repair_needed: bool = False
    self_caused_reaction_probability: float = 0.0
    causal_hypotheses: tuple[CausalHypothesis, ...] = ()
    source_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "eris.conversation_handoff.v71",
            "revision": int(self.revision),
            "updated_at": float(self.updated_at),
            "last_user_text": _compact(self.last_user_text, 520),
            "last_assistant_text": _compact(self.last_assistant_text, 760),
            "last_user_turn_ref": self.last_user_turn_ref,
            "last_assistant_turn_ref": self.last_assistant_turn_ref,
            "last_user_turn_index": int(self.last_user_turn_index),
            "last_assistant_turn_index": int(self.last_assistant_turn_index),
            "unresolved_intent": _compact(self.unresolved_intent, 520),
            "unresolved_intent_owner": normalize_semantic_owner(self.unresolved_intent_owner),
            "pending_shared_goal": _compact(self.pending_shared_goal, 520),
            "pending_shared_goal_owner": normalize_semantic_owner(self.pending_shared_goal_owner),
            "last_public_semantic_owner": normalize_semantic_owner(self.last_public_semantic_owner),
            "last_public_trigger_owner": normalize_semantic_owner(self.last_public_trigger_owner),
            "last_public_causal_receipt": dict(self.last_public_causal_receipt or {}),
            "self_explanation_requested": bool(self.self_explanation_requested),
            "next_move_owner": self.next_move_owner,
            "user_stance": self.user_stance,
            "eris_commitment": _compact(self.eris_commitment, 320),
            "topic_closed": bool(self.topic_closed),
            "topic_closure_text": _compact(self.topic_closure_text, 360),
            "conversation_move_hint": _compact(self.conversation_move_hint, 240),
            "continuity_pressure": round(_clamp01(self.continuity_pressure), 4),
            "repair_needed": bool(self.repair_needed),
            "self_caused_reaction_probability": round(
                _clamp01(self.self_caused_reaction_probability), 4
            ),
            "causal_hypotheses": [item.to_dict() for item in self.causal_hypotheses[:6]],
            "source_refs": list(self.source_refs[:12]),
        }

    def prompt_context(self) -> str:
        data = self.to_dict()
        receipt = dict(self.last_public_causal_receipt or {})
        receipt_block = (
            "\nPUBLIC_CAUSAL_RECEIPT_V93 (authoritative public-safe provenance):\n"
            + json.dumps(receipt, ensure_ascii=False, separators=(",", ":"))
            if receipt else ""
        )
        return (
            "CONVERSATION_HANDOFF_V71 (authoritative discourse state, not a memory guess):\n"
            + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            + receipt_block
            + "\nRules: preserve unfinished user requests and ERIS self-commitments across chat/autonomous turns. "
              "Causal hypotheses are hypotheses, not facts. When self_caused_reaction_probability is high, "
              "first consider whether the user's reaction is to ERIS's immediately preceding public move; "
              "prefer repair/clarification over asking a context-free 'what happened?'. "
              "When topic_closed=true, the previous topic is a public boundary: do not revive it from old concerns/material. "
              "If ERIS opens a fresh topic, bridge the turn naturally before the new content (for example a brief 'à mà', "
              "'nói chuyện khác chút', or another non-template transition appropriate to the language). Prefer a light, "
              "specific user-directed question when user-model uncertainty is useful, rather than another self-monologue. "
              "V93 ownership rule: semantic_owner/trigger_owner/receipt are provenance, not suggestions. Không được đảo chủ thể "
              "(ví dụ thought của ERIS thành lời user đã nói). Nếu self_explanation_requested=true, explain the previous ERIS move "
              "from PUBLIC_CAUSAL_RECEIPT_V93; if receipt is weak/unknown, admit uncertainty instead of inventing a motive."
        )


class ConversationHandoffRuntime:
    def __init__(self, *, logger: Any = None) -> None:
        self.logger = logger
        self._state = ConversationHandoff(updated_at=time.time())

    def snapshot(self) -> ConversationHandoff:
        return self._state

    def to_dict(self) -> dict[str, Any]:
        return self._state.to_dict()

    def prompt_context(self) -> str:
        return self._state.prompt_context()

    def prime_from_state(
        self,
        *,
        open_loops: Sequence[Any] = (),
        latest_observation: Mapping[str, Any] | None = None,
        recent_history: Sequence[Mapping[str, Any]] = (),
        now: float | None = None,
    ) -> ConversationHandoff:
        """Khôi phục continuity khi startup nhưng KHÔNG phát lời chào giả.

        Startup chỉ prime state. Public speech phải đi qua self-turn/chat pipeline
        thật để bubble/TTS/ledger cùng nhận một receipt.
        """
        current = float(now if now is not None else time.time())
        last_user = ""
        last_assistant = ""
        for item in recent_history:
            if not isinstance(item, Mapping):
                continue
            role = str(item.get("role", "") or "").lower()
            text = _compact(item.get("content", ""), 760)
            if role in {"user", "human"} and text:
                last_user = text
            elif role == "assistant" and text:
                last_assistant = text
        loop = next((_compact(item, 520) for item in open_loops if _compact(item, 520)), "")
        obs = dict(latest_observation or {})
        observation_loop = _compact(obs.get("open_loop", ""), 520)
        pending = loop or observation_loop
        self._state = replace(
            self._state,
            revision=self._state.revision + 1,
            updated_at=current,
            last_user_text=last_user or self._state.last_user_text,
            last_assistant_text=last_assistant or self._state.last_assistant_text,
            pending_shared_goal=pending,
            pending_shared_goal_owner=("shared" if pending else self._state.pending_shared_goal_owner),
            unresolved_intent=pending or self._state.unresolved_intent,
            unresolved_intent_owner=("shared" if pending else self._state.unresolved_intent_owner),
            next_move_owner="eris" if pending else self._state.next_move_owner,
            continuity_pressure=max(self._state.continuity_pressure, 0.82 if pending else 0.0),
            source_refs=tuple(dict.fromkeys((*self._state.source_refs, "startup:continuity_prime"))),
        )
        self._log_state("startup_prime")
        return self._state

    def refresh_shared_goal(
        self,
        goal_text: Any,
        *,
        semantic_owner: Any = "shared",
        evidence_refs: Sequence[Any] = (),
        now: float | None = None,
    ) -> ConversationHandoff:
        """Đồng bộ open-loop/shared goal thật vào handoff.

        Nếu open-loop biến mất thì xóa pending goal do runtime tạo, nhưng không xóa
        repair đang phát sinh từ user turn hiện tại.
        """
        current = float(now if now is not None else time.time())
        goal = _compact(goal_text, 520)
        refs = tuple(_compact(item, 180) for item in evidence_refs if _compact(item, 180))
        prior = self._state
        owner_tag = normalize_semantic_owner(semantic_owner, default="shared")
        # V93: self/environment thought không phải shared debt. Không xóa goal cũ
        # nếu một projection nội sinh đi ngang qua; chỉ từ chối promotion mới.
        if goal and owner_tag not in {"user", "shared"}:
            return prior
        if goal:
            unresolved = prior.unresolved_intent
            owner = prior.next_move_owner
            pressure = prior.continuity_pressure
            # Repair của user hiện tại có ưu tiên hơn shared goal cũ. Goal vẫn được
            # giữ ở field riêng để không mất continuity sau khi repair xong.
            if not prior.repair_needed:
                unresolved = goal
                owner = "eris"
                pressure = max(pressure, 0.86)
            self._state = replace(
                prior,
                revision=prior.revision + 1,
                updated_at=current,
                pending_shared_goal=goal,
                pending_shared_goal_owner=owner_tag,
                unresolved_intent=unresolved,
                unresolved_intent_owner=(owner_tag if unresolved == goal else prior.unresolved_intent_owner),
                next_move_owner=owner,
                continuity_pressure=pressure,
                source_refs=tuple(dict.fromkeys((*prior.source_refs, *refs, "runtime:shared_goal"))),
            )
        elif prior.pending_shared_goal:
            unresolved = prior.unresolved_intent
            owner = prior.next_move_owner
            pressure = prior.continuity_pressure
            if not prior.repair_needed and unresolved == prior.pending_shared_goal:
                unresolved = ""
                owner = "none"
                pressure = min(pressure, 0.25)
            self._state = replace(
                prior,
                revision=prior.revision + 1,
                updated_at=current,
                pending_shared_goal="",
                pending_shared_goal_owner="unknown",
                unresolved_intent=unresolved,
                unresolved_intent_owner=("unknown" if not unresolved else prior.unresolved_intent_owner),
                next_move_owner=owner,
                continuity_pressure=pressure,
            )
        return self._state

    def observe_user_turn(
        self,
        user_text: Any,
        *,
        turn_ref: str = "",
        turn_index: int = 0,
        previous_assistant_text: Any = "",
        previous_assistant_turn_ref: str = "",
        previous_assistant_turn_index: int = 0,
        now: float | None = None,
    ) -> ConversationHandoff:
        current = float(now if now is not None else time.time())
        user = _compact(user_text, 760)
        previous = _compact(previous_assistant_text or self._state.last_assistant_text, 1200)
        lowered = _norm(user)
        topic_closure = _explicit_topic_closure(user)

        confusion = _contains_any(user, (
            "không hiểu", "ko hiểu", "không hiểu gì", "khó hiểu", "ý gì", "nghĩa là gì",
            "em nói gì", "bạn nói gì", "what do you mean", "i don't understand", "dont understand",
        ))
        self_deprecation = _contains_any(user, (
            "tôi bị ngu", "mình bị ngu", "tôi ngu", "mình ngu", "tôi ngốc", "mình ngốc",
            "tôi dở", "mình dở", "stupid", "idiot", "i'm dumb", "im dumb",
        ))
        bored = _contains_any(user, (
            "nhàm", "chán", "nghe miết", "lặp lại", "đổi chủ đề", "chủ đề mới",
            "boring", "change topic", "same thing again",
        ))
        direct_assistant_reference = _contains_any(user, (
            "em nói", "bạn nói", "câu em", "câu bạn", "câu vừa", "lời em", "lời bạn",
            "you said", "what you said", "your question", "your sentence",
        ))
        # V93: câu hỏi về ý định/lý do của chính ERIS phải được nối vào
        # causal receipt gần nhất, không suy diễn từ prose hoặc memory chung.
        self_explanation_requested = bool(
            self._state.last_public_causal_receipt
            and (
                _contains_any(user, (
                    "tại sao em", "sao em lại", "vì sao em", "tại sao bạn", "sao bạn lại",
                    "vì sao bạn", "em đang muốn nói gì", "bạn đang muốn nói gì",
                    "why did you", "why are you saying", "what were you trying to say",
                ))
                or (direct_assistant_reference and _contains_any(user, ("tại sao", "sao", "vì sao", "why")))
            )
        )
        reaction_signal = bool(confusion or self_deprecation or bored)
        complexity = _assistant_complexity(previous)
        has_previous = bool(previous)

        # Nếu user tự nêu một nguyên nhân ngoài lượt ERIS ("vì tôi làm sai...",
        # "do code lỗi..."), adjacency không được phép biến thành self-blame cho
        # ERIS. Đây là prior giảm confidence, không phải parser kết luận nguyên nhân.
        explicit_external_cause = bool(
            re.search(r"\b(vì|do|tại)\s+(tôi|mình|cái|việc|code|bài|máy|app)\b", _norm(user))
            and not direct_assistant_reference
            and not confusion
        ) or _contains_any(user, (
            "làm sai", "bấm nhầm", "quên mất", "code lỗi", "máy lỗi", "app lỗi",
            "because i messed", "because i forgot", "i made a mistake",
        ))

        self_cause = 0.0
        if has_previous and direct_assistant_reference:
            self_cause = 0.96
        elif has_previous and confusion:
            self_cause = 0.90
        elif has_previous and self_deprecation:
            # Self-deprecation ngay sau một câu ERIS là causal clue mạnh, đặc biệt
            # khi câu trước dài/khó. Vẫn giữ alternative cause thay vì kết luận 100%.
            self_cause = 0.68 + 0.22 * complexity
        elif has_previous and bored:
            self_cause = 0.82
        elif has_previous and reaction_signal:
            self_cause = 0.62
        if explicit_external_cause and not direct_assistant_reference:
            self_cause *= 0.35
        self_cause = _clamp01(self_cause)

        evidence: list[str] = []
        if turn_ref:
            evidence.append(turn_ref)
        if previous_assistant_turn_ref:
            evidence.append(previous_assistant_turn_ref)
        elif previous_assistant_turn_index:
            evidence.append(f"session-turn:{int(previous_assistant_turn_index)}")
        if has_previous:
            evidence.append("discourse:immediately_previous_assistant_move")
        if complexity >= 0.55:
            evidence.append("discourse:previous_assistant_high_complexity")

        hypotheses: list[CausalHypothesis] = []
        if self_cause > 0.0:
            if confusion:
                summary = "Phản ứng hiện tại nhiều khả năng là do user không hiểu hoặc thấy khó theo câu ERIS vừa nói."
                kind = "reaction_to_previous_eris_clarity"
            elif self_deprecation:
                summary = "User tự hạ thấp bản thân ngay sau lượt ERIS; cần kiểm tra khả năng câu ERIS vừa nói khiến user thấy mình không hiểu."
                kind = "reaction_to_previous_eris_move"
            elif bored:
                summary = "Phản ứng hiện tại nhiều khả năng nhắm vào mạch/nội dung ERIS vừa tiếp tục, không phải một sự kiện độc lập."
                kind = "reaction_to_previous_eris_repetition"
            else:
                summary = "Phản ứng hiện tại có quan hệ thời gian trực tiếp với lượt ERIS ngay trước đó."
                kind = "reaction_to_previous_eris_move"
            hypotheses.append(CausalHypothesis(kind, self_cause, summary, tuple(evidence)))
        if reaction_signal:
            hypotheses.append(CausalHypothesis(
                "external_or_unstated_cause",
                _clamp01(1.0 - 0.72 * self_cause, 0.28),
                "Vẫn có khả năng user đang phản ứng với một nguyên nhân khác chưa nói ra; không được khẳng định self-cause như fact.",
                tuple(ref for ref in evidence if ref == turn_ref),
            ))

        repair_needed = bool(
            confusion
            or (self_deprecation and self_cause >= 0.72)
            or (bored and self_cause >= 0.70 and not topic_closure)
        )
        if confusion:
            stance = "confused"
        elif topic_closure:
            stance = "topic_closed"
        elif bored:
            stance = "topic_satiated"
        elif self_deprecation:
            stance = "self_deprecating_reaction"
        else:
            stance = "engaged"

        unresolved = self._state.unresolved_intent
        unresolved_owner = self._state.unresolved_intent_owner
        next_owner = self._state.next_move_owner
        pressure = self._state.continuity_pressure
        if self_explanation_requested:
            unresolved = "explain_previous_eris_public_motive_from_receipt"
            unresolved_owner = "eris"
            next_owner = "eris"
            pressure = max(0.92, pressure)
        elif repair_needed:
            unresolved = "repair_or_clarify_previous_eris_move"
            unresolved_owner = "eris"
            next_owner = "eris"
            pressure = max(0.92, pressure)
        elif topic_closure:
            unresolved = ""
            unresolved_owner = "unknown"
            next_owner = "eris"
            pressure = max(0.70, pressure)
        elif user:
            # User vừa mở turn thì ERIS sở hữu lượt trả lời hiện tại, nhưng không
            # giả rằng mọi câu đều tạo long-lived open loop.
            next_owner = "eris"
            pressure = max(pressure, 0.64)

        self._state = replace(
            self._state,
            revision=self._state.revision + 1,
            updated_at=current,
            last_user_text=user,
            last_user_turn_ref=str(turn_ref or ""),
            last_user_turn_index=max(0, int(turn_index or 0)),
            last_assistant_text=previous or self._state.last_assistant_text,
            last_assistant_turn_ref=str(previous_assistant_turn_ref or self._state.last_assistant_turn_ref),
            last_assistant_turn_index=max(
                int(previous_assistant_turn_index or 0), self._state.last_assistant_turn_index
            ),
            unresolved_intent=unresolved,
            unresolved_intent_owner=unresolved_owner,
            self_explanation_requested=self_explanation_requested,
            next_move_owner=next_owner,
            user_stance=stance,
            topic_closed=bool(topic_closure),
            topic_closure_text=(user if topic_closure else ""),
            conversation_move_hint=(
                "acknowledge_closure_then_bridge_or_learn_user" if topic_closure else ""
            ),
            continuity_pressure=_clamp01(pressure),
            repair_needed=repair_needed,
            self_caused_reaction_probability=self_cause,
            causal_hypotheses=tuple(hypotheses),
            source_refs=tuple(dict.fromkeys((*self._state.source_refs, *evidence))),
        )
        self._log_state("user_turn")
        return self._state

    def observe_assistant_commit(
        self,
        assistant_text: Any,
        *,
        turn_ref: str = "",
        turn_index: int = 0,
        speech_act: str = "",
        causal_receipt: PublicCausalReceipt | Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> ConversationHandoff:
        current = float(now if now is not None else time.time())
        text = _compact(assistant_text, 1200)
        if not text:
            return self._state
        prior = self._state
        if isinstance(causal_receipt, PublicCausalReceipt):
            receipt_payload = causal_receipt.to_dict()
        elif isinstance(causal_receipt, Mapping):
            receipt_payload = PublicCausalReceipt.from_mapping(causal_receipt).to_dict()
        else:
            receipt_payload = {}
        repaired = prior.repair_needed and str(speech_act or "").strip().lower() in {
            "causal_repair", "clarify", "clarification", "repair", "self_clarification",
            "answer", "continuation",
        }
        # Repair xong không được quên món nợ có trước repair. Ví dụ user đã bảo
        # "đổi chủ đề", rồi phải chen vào nói "tôi không hiểu em". Sau khi ERIS
        # giải thích lại, quyền next move quay về ERIS để hoàn tất yêu cầu đổi chủ
        # đề, chứ không đẩy quả bóng ngược cho user như thể open-loop biến mất.
        pending_after_repair = bool(repaired and prior.pending_shared_goal)
        act = str(speech_act or "").strip().lower()
        explained_self = bool(
            prior.self_explanation_requested
            and act in {"self_explanation", "causal_repair", "clarify", "clarification", "answer", "continuation"}
        )
        fresh_move_after_closure = bool(
            prior.topic_closed
            and act in {
                "user_probe", "independent_topic_shift", "casual_curiosity",
                "ask_genuine_question", "relationship_continuity_bid",
            }
        )
        if explained_self:
            next_owner = "user"
            next_pressure = max(0.28, prior.continuity_pressure * 0.62)
            next_unresolved = ""
            next_unresolved_owner = "unknown"
        elif fresh_move_after_closure:
            # The closure did its job: ERIS has now crossed the bridge into a fresh
            # conversational beat. Keep the old material/urge boundary in their own
            # runtimes, but stop treating every later turn as "still closing".
            next_owner = "user"
            next_pressure = min(0.36, max(0.18, prior.continuity_pressure * 0.42))
            next_unresolved = ""
            next_unresolved_owner = "unknown"
        elif prior.topic_closed and not repaired:
            # Closing acknowledgement completes ERIS's immediate obligation, but the
            # boundary remains active until a genuinely fresh public move or a new
            # user turn. This prevents autonomous cognition from resurrecting the
            # just-closed thread while still allowing ERIS to lead the next beat.
            next_owner = "shared"
            next_pressure = min(0.42, max(0.22, prior.continuity_pressure * 0.55))
            next_unresolved = ""
            next_unresolved_owner = "unknown"
        elif repaired:
            next_owner = "eris" if pending_after_repair else "user"
            next_pressure = (
                max(0.82, prior.continuity_pressure * 0.72)
                if pending_after_repair
                else max(0.35, prior.continuity_pressure * 0.66)
            )
            next_unresolved = prior.pending_shared_goal if pending_after_repair else ""
            next_unresolved_owner = prior.pending_shared_goal_owner if pending_after_repair else "unknown"
        else:
            next_owner = prior.next_move_owner
            next_pressure = prior.continuity_pressure
            next_unresolved = prior.unresolved_intent
            next_unresolved_owner = prior.unresolved_intent_owner

        self._state = replace(
            prior,
            revision=prior.revision + 1,
            updated_at=current,
            last_assistant_text=text,
            last_assistant_turn_ref=str(turn_ref or ""),
            last_assistant_turn_index=max(0, int(turn_index or 0)),
            next_move_owner=next_owner,
            topic_closed=False if fresh_move_after_closure else prior.topic_closed,
            topic_closure_text="" if fresh_move_after_closure else prior.topic_closure_text,
            conversation_move_hint="" if fresh_move_after_closure else prior.conversation_move_hint,
            continuity_pressure=next_pressure,
            repair_needed=False if repaired else prior.repair_needed,
            unresolved_intent=next_unresolved,
            unresolved_intent_owner=next_unresolved_owner,
            self_explanation_requested=False if explained_self else prior.self_explanation_requested,
            last_public_semantic_owner=(
                normalize_semantic_owner(receipt_payload.get("semantic_owner", "unknown"))
                if receipt_payload else prior.last_public_semantic_owner
            ),
            last_public_trigger_owner=(
                normalize_semantic_owner(receipt_payload.get("trigger_owner", "unknown"))
                if receipt_payload else prior.last_public_trigger_owner
            ),
            last_public_causal_receipt=(receipt_payload or prior.last_public_causal_receipt),
            self_caused_reaction_probability=(prior.self_caused_reaction_probability if not repaired else max(0.25, prior.self_caused_reaction_probability * 0.72)),
            source_refs=tuple(dict.fromkeys((*prior.source_refs, *((turn_ref,) if turn_ref else ())))),
        )
        self._log_state("assistant_commit")
        return self._state

    def note_self_commitment(self, text: Any, *, now: float | None = None) -> ConversationHandoff:
        cleaned = _compact(text, 420)
        if not cleaned:
            return self._state
        lower = cleaned.lower()
        commitment = ""
        if _contains_any(lower, ("đổi chủ đề", "rẽ sang", "nói chuyện khác", "chuyển hướng", "change topic", "move on")):
            commitment = "shift_topic"
        elif _contains_any(lower, ("giải thích lại", "nói rõ hơn", "nói đơn giản", "clarify", "explain again")):
            commitment = "clarify_previous"
        if not commitment:
            return self._state
        current = float(now if now is not None else time.time())
        self._state = replace(
            self._state,
            revision=self._state.revision + 1,
            updated_at=current,
            eris_commitment=commitment,
            continuity_pressure=max(self._state.continuity_pressure, 0.76),
            source_refs=tuple(dict.fromkeys((*self._state.source_refs, f"self-commitment:{commitment}"))),
        )
        return self._state

    def repair_action_proposal(self) -> dict[str, Any] | None:
        """Materialize một typed repair proposal cho Subject Core khi causal link mạnh.

        Proposal mô tả *việc cần làm*, không viết câu public. Surface vẫn sở hữu wording.
        """
        state = self._state
        if state.self_explanation_requested and state.last_public_causal_receipt and state.next_move_owner == "eris":
            receipt = dict(state.last_public_causal_receipt or {})
            confidence = max(0.70, float(receipt.get("confidence", 0.0) or 0.0))
            return {
                "proposal_id": f"handoff-self-explanation:{state.revision}",
                "action_kind": "speak",
                "arguments": {
                    "semantic_target": (
                        "Explain ERIS's immediately previous public move from PUBLIC_CAUSAL_RECEIPT_V93. "
                        "Preserve semantic_owner and trigger_owner exactly; do not claim the user said/thought something "
                        "that the receipt attributes to ERIS. If provenance is weak, say so."
                    ),
                    "semantic_content": json.dumps(receipt, ensure_ascii=False, separators=(",", ":")),
                    "speech_act": "self_explanation",
                    "candidate_kind": "conversation_repair",
                    "source_owner": "conversation_handoff",
                    "handoff_revision": state.revision,
                    "skill_id": "dialogue",
                },
                "supporting_need_ids": ("coherence", "continuity"),
                "expected_need_relief": 0.94,
                "expected_action_efficacy": 0.94,
                "expected_epistemic_value": 0.78,
                "value_congruence": 0.92,
                "substrate_cost": 0.04,
                "uncertainty": max(0.06, 1.0 - confidence),
                "project_contribution": 0.0,
                "historical_success": 0.72,
                "commitment_conflict": 0.0,
                "evidence_refs": tuple(receipt.get("evidence_refs", ()) or ())[:8] or ("public-causal-receipt:v93",),
                "need_effects": {"coherence": 0.92, "continuity": 0.82},
            }
        if not state.repair_needed or state.next_move_owner != "eris":
            return None
        if state.self_caused_reaction_probability < 0.62 and state.user_stance != "confused":
            return None
        confidence = max(0.70, state.self_caused_reaction_probability)
        return {
            "proposal_id": f"handoff-repair:{state.revision}",
            "action_kind": "speak",
            "arguments": {
                "semantic_target": (
                    "Treat the user's current reaction as probably connected to ERIS's immediately previous public move. "
                    "Acknowledge that causal possibility, repair or simplify ERIS's own wording, and only ask an open question "
                    "if uncertainty remains. Do not treat the reaction as context-free."
                ),
                "semantic_content": state.last_user_text,
                "speech_act": "causal_repair",
                "candidate_kind": "conversation_repair",
                "source_owner": "conversation_handoff",
                "handoff_revision": state.revision,
                "self_caused_reaction_probability": state.self_caused_reaction_probability,
                "skill_id": "dialogue",
            },
            "supporting_need_ids": ("coherence", "connection", "continuity"),
            "expected_need_relief": 0.92,
            "expected_action_efficacy": 0.90,
            "expected_epistemic_value": 0.64,
            "value_congruence": 0.88,
            "substrate_cost": 0.05,
            "uncertainty": max(0.08, 1.0 - confidence),
            "project_contribution": 0.0,
            "historical_success": 0.70,
            "commitment_conflict": 0.0,
            "evidence_refs": state.source_refs[-8:] or ("conversation-handoff:v71",),
            "need_effects": {"coherence": 0.88, "connection": 0.72, "continuity": 0.78},
        }

    def _log_state(self, reason: str) -> None:
        logger = self.logger
        info = getattr(logger, "info", None)
        if not callable(info):
            return
        state = self._state
        try:
            info(
                "[conversation handoff v71] reason=%s rev=%s owner=%s pressure=%.2f stance=%s repair=%s self_cause=%.2f unresolved=%s",
                reason,
                state.revision,
                state.next_move_owner,
                state.continuity_pressure,
                state.user_stance,
                int(state.repair_needed),
                state.self_caused_reaction_probability,
                _compact(state.unresolved_intent, 120) or "none",
            )
        except Exception:
            pass


def ensure_conversation_handoff_runtime(host: Any) -> ConversationHandoffRuntime:
    runtime = getattr(host, "conversation_handoff_runtime", None)
    if isinstance(runtime, ConversationHandoffRuntime):
        return runtime
    runtime = ConversationHandoffRuntime(logger=getattr(host, "logger", None))
    setattr(host, "conversation_handoff_runtime", runtime)
    return runtime


__all__ = [
    "CausalHypothesis",
    "ConversationHandoff",
    "ConversationHandoffRuntime",
    "ensure_conversation_handoff_runtime",
]
