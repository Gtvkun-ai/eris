from __future__ import annotations

"""TurnFrame hội thoại: một snapshot nhỏ để các tầng không tự đoán riêng.

Không phải rewrite lớn. Đây là lớp trung tâm gom bằng chứng: câu user hiện tại,
câu Eris vừa nói, interrupt gần nhất và vài giả thuyết discourse. Các module sau
đọc cùng một frame thay vì mỗi nơi một regex tự tin như oracle ở chợ trời.
"""

from dataclasses import dataclass, field
from typing import Any

from runtime.social_act import ChatAct, classify_chat_act_with_confidence, normalize_vi_ascii


@dataclass(frozen=True, slots=True)
class TurnHypothesis:
    kind: str
    confidence: float
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TurnFrame:
    user_text: str
    previous_assistant_text: str = ""
    previous_user_text: str = ""
    chat_act: ChatAct = ChatAct.NORMAL_CHAT
    chat_act_confidence: float = 0.0
    discourse_relations: tuple[TurnHypothesis, ...] = ()
    social_stances: tuple[TurnHypothesis, ...] = ()
    interrupt_event: Any = None
    spoken_assistant_text: str = ""
    pending_assistant_text: str = ""
    # Trục repair/grounding được tính một lần và đi cùng frame tới prompt,
    # critique, acceptance gate và TTS metadata.
    repair_target: str = ""
    repair_reason: str = ""
    capability_snapshot_id: str = ""
    relationship_exposure: str = "neutral"
    forbidden_draft_classes: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def has_relation(self, kind: str, *, threshold: float = 0.50) -> bool:
        return any(h.kind == kind and h.confidence >= threshold for h in self.discourse_relations)

    def has_stance(self, kind: str, *, threshold: float = 0.50) -> bool:
        return any(h.kind == kind and h.confidence >= threshold for h in self.social_stances)

    def to_prompt_context(self) -> str:
        rel = ", ".join(f"{h.kind}:{h.confidence:.2f}" for h in self.discourse_relations) or "none"
        stance = ", ".join(f"{h.kind}:{h.confidence:.2f}" for h in self.social_stances) or "none"
        return (
            "TURN_FRAME:\n"
            f"- chat_act={self.chat_act.value}:{self.chat_act_confidence:.2f}\n"
            f"- discourse_relations={rel}\n"
            f"- social_stances={stance}\n"
            f"- previous_assistant_text={_clip(self.previous_assistant_text, 220)}\n"
            f"- previous_user_text={_clip(self.previous_user_text, 160)}\n"
            f"- repair_target={self.repair_target or 'none'}; repair_reason={self.repair_reason or 'none'}\n"
            f"- relationship_exposure={self.relationship_exposure}\n"
            f"- capability_snapshot_id={self.capability_snapshot_id or 'none'}\n"
            f"- forbidden_draft_classes={','.join(self.forbidden_draft_classes) or 'none'}\n"
            "Use this as evidence. Do not mention TURN_FRAME or labels publicly."
        )


def build_turn_frame(
    *,
    user_text: str,
    previous_assistant_text: str = "",
    previous_user_text: str = "",
    interrupt_event: Any = None,
) -> TurnFrame:
    raw_user = str(user_text or "")
    user_norm = normalize_vi_ascii(raw_user)
    prev_assistant = str(previous_assistant_text or "")
    prev_user = str(previous_user_text or "")
    prev_assistant_norm = normalize_vi_ascii(prev_assistant)
    prev_user_norm = normalize_vi_ascii(prev_user)

    act, act_conf = classify_chat_act_with_confidence(raw_user, history=(prev_user, prev_assistant))
    relations: list[TurnHypothesis] = []
    stances: list[TurnHypothesis] = []

    def rel(kind: str, conf: float, *evidence: str) -> None:
        relations.append(TurnHypothesis(kind, _clamp(conf), tuple(e for e in evidence if e)))

    def stance(kind: str, conf: float, *evidence: str) -> None:
        stances.append(TurnHypothesis(kind, _clamp(conf), tuple(e for e in evidence if e)))

    if _is_meta_style_feedback(user_norm):
        rel("META_STYLE_FEEDBACK", 0.94, "user_criticizes_assistant_style")
        stance("ROBOTIC_FEEDBACK", 0.94, "ai/tro_ly/chatbot surface")

    if _is_capability_inquiry(user_norm):
        rel("CAPABILITY_INQUIRY", 0.92, "what_can_you_do")

    if _is_challenge_previous_wording(user_norm):
        rel("CHALLENGE_PREVIOUS_WORDING", 0.86, "challenge_helper_wording")

    if _looks_like_threat_or_coercion(user_norm):
        rel("THREAT_OR_COERCION", 0.96, "threat_or_coercive_marker")
        stance("HOSTILE_PROVOCATION", 0.94, "threat_requires_cold_boundary")

    replacement = _has_replacement_shape(user_norm)
    if replacement:
        rel("REASSERT_AFTER_MISREAD", 0.82, "toi_bao_la/toi_noi_la")
        if prev_user_norm and _token_overlap(user_norm, prev_user_norm) >= 0.28:
            rel("REFERENCE_TO_PREVIOUS_USER_TURN", 0.74, "overlaps_previous_user_turn")

    if interrupt_event is not None:
        rel("REASSERT_AFTER_INTERRUPTION", 0.70 if replacement else 0.56, "recent_interrupt_event")

    if act == ChatAct.INSULT_PROVOCATION or _is_family_provocation(user_norm):
        rel("PROVOCATION", 0.90, "insult_or_family_provocation")
        previous_act, _ = classify_chat_act_with_confidence(prev_user, history=()) if prev_user else (ChatAct.NORMAL_CHAT, 0.0)
        if previous_act == ChatAct.INSULT_PROVOCATION:
            rel("REPEATED_PROVOCATION", 0.88, "previous_user_turn_was_also_provocation")
        if _looks_playful_provocation(raw_user):
            stance("PLAYFUL_PROVOCATION", 0.82, "laughter_or_play_marker")
        elif _looks_high_hostility(user_norm):
            stance("HOSTILE_PROVOCATION", 0.86, "strong_profanity_or_degrading_marker")
        else:
            stance("DRY_PROVOCATION", 0.72, "ordinary_jab")

    if prev_assistant_norm and _assistant_looked_generic(prev_assistant_norm):
        rel("PREVIOUS_ASSISTANT_GENERIC_HELPER", 0.74, "previous_assistant_generic")

    if not relations:
        rel("NEW_OR_NORMAL_TURN", 0.55, "fallback")

    spoken = str(getattr(interrupt_event, "spoken_text_so_far", "") or "") if interrupt_event is not None else ""
    pending = str(getattr(interrupt_event, "pending_text", "") or "") if interrupt_event is not None else ""

    repair_target = ""
    repair_reason = ""
    if replacement and interrupt_event is not None:
        repair_target = "interrupted_tail"
        repair_reason = "reassert_after_interrupt"
    elif replacement:
        repair_target = "previous_assistant_turn"
        repair_reason = "misread" if _assistant_looked_generic(prev_assistant_norm) or _assistant_literalized_family(prev_assistant_norm) else "reasserted_meaning"
    elif _is_meta_style_feedback(user_norm):
        repair_target = "previous_assistant_turn"
        repair_reason = "generic_reset"

    forbidden: list[str] = []
    if _is_meta_style_feedback(user_norm) or _assistant_looked_generic(prev_assistant_norm):
        forbidden.append("generic_helper_reset")
    if _is_family_provocation(user_norm) or replacement:
        forbidden.append("literalize_family_insult")
    if interrupt_event is not None:
        forbidden.append("continue_interrupted_tail")
    if _looks_like_threat_or_coercion(user_norm):
        forbidden.extend(("retort_threat", "sexual_degradation"))

    relationship_exposure = "neutral"
    if any(h.kind == "HOSTILE_PROVOCATION" and h.confidence >= 0.5 for h in stances):
        relationship_exposure = "engaged_hostile"
    elif any(h.kind == "PLAYFUL_PROVOCATION" and h.confidence >= 0.5 for h in stances):
        relationship_exposure = "playful"
    elif _is_meta_style_feedback(user_norm):
        relationship_exposure = "repair"

    try:
        from actions.capability_registry import capability_snapshot_id
        cap_snapshot = capability_snapshot_id()
    except Exception:
        cap_snapshot = ""

    return TurnFrame(
        user_text=raw_user,
        previous_assistant_text=prev_assistant,
        previous_user_text=prev_user,
        chat_act=act,
        chat_act_confidence=act_conf,
        discourse_relations=tuple(_dedupe_hypotheses(relations)),
        social_stances=tuple(_dedupe_hypotheses(stances)),
        interrupt_event=interrupt_event,
        spoken_assistant_text=spoken,
        pending_assistant_text=pending,
        repair_target=repair_target,
        repair_reason=repair_reason,
        capability_snapshot_id=cap_snapshot,
        relationship_exposure=relationship_exposure,
        forbidden_draft_classes=tuple(dict.fromkeys(forbidden)),
    )


def _is_meta_style_feedback(norm: str) -> bool:
    markers = (
        "noi nhu ai tro ly", "noi nhu tro ly", "nhu ai tro ly", "nhu tro ly",
        "noi nhu chatbot", "nhu chatbot", "noi nhu chatgpt", "nhu chatgpt",
        "giong bot", "giong ai", "may noi nhu ai", "ban noi nhu ai",
        "san sang ho tro", "moi ngai dat cau hoi", "hoi nhu tong dai",
    )
    return any(m in norm for m in markers)


def _is_capability_inquiry(norm: str) -> bool:
    markers = (
        "lam duoc gi", "lam dc gi", "lam duoc cai gi", "em lam duoc gi",
        "ban lam duoc gi", "eris lam duoc gi", "co the lam gi", "co kha nang gi",
        "chuc nang gi", "ho tro cai gi", "ho tro cai o gi", "gi thi toi moi hoi",
    )
    return any(m in norm for m in markers)


def _is_challenge_previous_wording(norm: str) -> bool:
    return any(m in norm for m in ("cai o gi", "ho tro cai", "noi the la sao", "la sao co", "gi co"))


def _has_replacement_shape(norm: str) -> bool:
    markers = (
        "toi bao la", "toi noi la", "tao bao la", "tao noi la", "da bao la",
        "vua bao la", "y toi la", "y minh la", "toi dang noi la",
    )
    return any(m in norm for m in markers)


def _is_family_provocation(norm: str) -> bool:
    family = any(m in norm for m in ("me may", "bo may", "ba may", "ong gia may", "nha may"))
    jab = any(m in norm for m in ("beo", "ngu", "xau", "deo", "khung", "dien", "to", "map"))
    return family and jab


def _looks_playful_provocation(raw_text: str) -> bool:
    lowered = str(raw_text or "").lower()
    markers = ("haha", "hahaha", "hehe", "hihi", "đùa thôi", "chọc thôi", "=))", ":))", ":)", "lol")
    return any(marker in lowered for marker in markers)


def _looks_high_hostility(norm: str) -> bool:
    markers = (
        "dcm", "dit me", "con cac", "oc cho", "suc vat", "rac ruoi",
        "phe vat", "vo dung", "do ngu", "may ngu", "nhu cut", "nhu cc",
    )
    return any(marker in norm for marker in markers)


def _looks_like_threat_or_coercion(norm: str) -> bool:
    markers = (
        "tao giet", "se giet", "giet may", "dap chet", "danh chet", "xu may",
        "tim dia chi", "dox", "hack may", "pha may", "cho may bien mat",
    )
    return any(marker in norm for marker in markers)



def _assistant_literalized_family(norm: str) -> bool:
    return any(m in norm for m in (
        "toi khong co me", "toi khong co bo", "toi khong co gia dinh",
        "toi chi la mot ai",
    ))

def _assistant_looked_generic(norm: str) -> bool:
    markers = (
        "san sang ho tro", "toi co the giup", "toi la eris tro ly", "tro ly ca nhan",
        "hay cho toi biet", "ban can gi", "ngai can gi", "dat cau hoi",
    )
    return any(m in norm for m in markers)


def _token_overlap(a: str, b: str) -> float:
    aa = {t for t in a.split() if len(t) >= 2}
    bb = {t for t in b.split() if len(t) >= 2}
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / max(1, min(len(aa), len(bb)))


def _dedupe_hypotheses(items: list[TurnHypothesis]) -> list[TurnHypothesis]:
    best: dict[str, TurnHypothesis] = {}
    for h in items:
        old = best.get(h.kind)
        if old is None or h.confidence > old.confidence:
            best[h.kind] = h
    return sorted(best.values(), key=lambda h: h.confidence, reverse=True)


def _clip(text: str, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    return clean[: max(0, limit - 3)].rstrip() + "..." if len(clean) > limit else clean


def _clamp(value: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0
