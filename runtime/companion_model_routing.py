# -*- coding: utf-8 -*-
"""Companion-aware DeepSeek model routing for public chat turns.

The router is deliberately deterministic and cheap.  Flash remains the default,
while Pro is selected when understanding the user's intended meaning or producing
an expressive companion response is materially harder than answering a clear
instruction.  Missing facts are not treated as "deep": the model should ask one
focused question instead of inventing them.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


def _plain(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    ascii_text = ascii_text.lower().replace("đ", "d")
    return re.sub(r"\s+", " ", ascii_text).strip()


def _contains_any(text: str, phrases: Sequence[str]) -> int:
    return sum(1 for phrase in phrases if phrase in text)


_STYLE_REQUESTS = (
    "viet hay hon", "noi hay hon", "dien dat hay hon", "tra loi hay hon",
    "co van", "van ve", "van chuong", "tinh te", "sau sac", "co hon",
    "giau cam xuc", "an du", "lang man", "tho hon", "muot hon", "dep hon",
    "bot kho", "do may moc", "tu nhien hon", "viet nhu", "giong van",
    "caption", "loi nhan", "buc thu", "doan van", "viet truyen", "sang tac",
)
_ABSTRACT_MARKERS = (
    "y nghia", "ban chat", "ton tai", "hien huu", "y thuc", "tu do",
    "con nguoi", "dinh menh", "thuc tai", "dung sai", "that su la gi",
    "minh la ai", "toi la ai", "em la ai", "song de lam gi", "tri ky",
    "tinh yeu", "co don", "trong rong", "vo nghia", "ham y", "an y",
    "ngu y", "tuong lai cua chung ta", "moi quan he", "giua toi va em",
)
_RELATIONAL_MARKERS = (
    "hieu toi", "hieu minh", "quan tam toi", "co nho toi", "co thuong toi",
    "tai sao em", "tai sao ban", "em nghi gi ve toi", "ban nghi gi ve toi",
    "chung ta", "giua toi va em", "moi quan he", "gan gui", "xa cach",
    "that long", "noi that", "cam thay ve toi", "toi co y nghia gi",
)
_EMOTION_MARKERS = (
    "toi thay", "toi cam thay", "minh thay", "minh cam thay", "buon",
    "co don", "trong rong", "met moi", "bat an", "so hai", "that vong",
    "ton thuong", "lac long", "khong on", "khong biet phai", "nho ai",
    "day dut", "xau ho", "ghen", "tuc", "yeu", "thuong", "ghet ban than",
)
_CONTEXT_REFERENCES = (
    "cai do", "cai nay", "y do", "y nay", "chuyen do", "chuyen nay",
    "nhu vay", "the con", "vay a", "sao lai the", "sao em noi vay",
    "noi tiep di", "do thi sao", "con cai kia", "luc nay", "hoi nay",
)
_TECHNICAL_DEPTH = (
    "kien truc", "architecture", "refactor", "race condition", "deadlock",
    "debug", "root cause", "nhieu module", "toan repo", "migration",
    "distributed", "concurrency", "bao mat", "security review", "benchmark",
    "toi uu", "optimize", "thiet ke he thong", "system design",
)
_EXPLICIT_DEEP = (
    "phan tich sau", "dao sau", "suy nghi ky", "can nhac ky", "nghiem tuc",
    "nhieu goc nhin", "giai thich tan goc", "dung tra loi hong hot",
)
_SIMPLE_COMMANDS = (
    "mo ", "dong ", "copy ", "dan ", "phat ", "dung nhac", "tang am luong",
    "giam am luong", "gui file", "tai file", "chay test", "chay lenh",
    "xoa file", "doi ten", "luu file", "tim file", "may gio", "hom nay ngay",
)
_SIMPLE_CHAT = (
    "xin chao", "chao", "hello", "hi", "cam on", "ok", "oke", "uh",
    "u", "duoc", "xong chua", "co khong", "dung khong",
)
_MISSING_FACT_PATTERNS = (
    r"^(lam|sua|viet|gui|doi|xoa|them|bo) (di|no|cai do|cai nay)$",
    r"^(lam|sua|viet|gui|doi|xoa|them|bo) (no|cai do|cai nay) di$",
    r"^(lam|sua|viet|gui|doi|xoa|them|bo)$",
    r"^(tiep tuc|lam tiep|sua tiep)$",
)


@dataclass(frozen=True, slots=True)
class CompanionRoutingPolicy:
    enabled: bool = True
    pro_threshold: float = 0.58
    max_reasoning_threshold: float = 0.86
    route_style_to_pro: bool = True
    route_abstract_to_pro: bool = True
    route_relational_to_pro: bool = True
    route_contextual_ambiguity_to_pro: bool = True
    simple_turns_stay_flash: bool = True

    @classmethod
    def from_runtime(cls) -> "CompanionRoutingPolicy":
        try:
            from runtime.runtime_settings_store import get_runtime_settings_store

            chat = get_runtime_settings_store().get("chat", default={}) or {}
            return cls(
                enabled=bool(chat.get("companion_routing_enabled", True)),
                pro_threshold=max(0.2, min(0.95, float(chat.get("companion_pro_threshold", 0.58) or 0.58))),
                max_reasoning_threshold=max(
                    0.5,
                    min(1.0, float(chat.get("companion_max_reasoning_threshold", 0.86) or 0.86)),
                ),
                route_style_to_pro=bool(chat.get("companion_style_uses_pro", True)),
                route_abstract_to_pro=bool(chat.get("companion_abstract_uses_pro", True)),
                route_relational_to_pro=bool(chat.get("companion_relational_uses_pro", True)),
                route_contextual_ambiguity_to_pro=bool(
                    chat.get("companion_contextual_ambiguity_uses_pro", True)
                ),
                simple_turns_stay_flash=bool(chat.get("companion_simple_turns_stay_flash", True)),
            )
        except (ImportError, AttributeError, TypeError, ValueError, OSError):
            return cls()


@dataclass(frozen=True, slots=True)
class CompanionRouteDecision:
    tier: str
    score: float
    reasoning_effort: str | None
    thinking_mode: str
    reasons: tuple[str, ...]
    clarification_preferred: bool = False
    style_sensitive: bool = False

    @property
    def use_pro(self) -> bool:
        return self.tier == "pro"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["use_pro"] = self.use_pro
        return payload

    def prompt_context(self) -> str:
        reason_text = ", ".join(self.reasons) if self.reasons else "clear_simple_turn"
        clarification = (
            " Essential facts appear missing: ask exactly one focused question and do not invent details."
            if self.clarification_preferred
            else ""
        )
        return (
            f"Companion routing selected {self.tier.upper()} for reasons [{reason_text}]. "
            "Do not mention model routing to the user. Preserve ERIS continuity and answer the whole intended meaning."
            f"{clarification}"
        )


def _history_text(history: Sequence[Mapping[str, Any]] | None, *, limit: int = 4) -> str:
    parts: list[str] = []
    for item in list(history or ())[-limit:]:
        if not isinstance(item, Mapping):
            continue
        content = item.get("content", "")
        if isinstance(content, str):
            parts.append(content)
    return _plain(" ".join(parts))


def route_companion_turn(
    user_text: str,
    *,
    recent_history: Sequence[Mapping[str, Any]] | None = None,
    policy: CompanionRoutingPolicy | None = None,
) -> CompanionRouteDecision:
    """Select Flash or Pro for one public companion turn.

    The score is not a truth classifier.  It is a routing pressure estimate used
    to reserve Pro for turns where nuance, interpretation or expressive quality
    materially affects the result.
    """

    policy = policy or CompanionRoutingPolicy.from_runtime()
    text = _plain(user_text)
    history = _history_text(recent_history)
    tokens = re.findall(r"[a-z0-9]+", text)

    if not policy.enabled:
        return CompanionRouteDecision(
            tier="flash",
            score=0.0,
            reasoning_effort=None,
            thinking_mode="disabled",
            reasons=("routing_disabled",),
        )

    style_hits = _contains_any(text, _STYLE_REQUESTS)
    abstract_hits = _contains_any(text, _ABSTRACT_MARKERS)
    relational_hits = _contains_any(text, _RELATIONAL_MARKERS)
    emotion_hits = _contains_any(text, _EMOTION_MARKERS)
    context_hits = _contains_any(text, _CONTEXT_REFERENCES)
    technical_hits = _contains_any(text, _TECHNICAL_DEPTH)
    explicit_deep_hits = _contains_any(text, _EXPLICIT_DEEP)
    simple_command_hits = _contains_any(text, _SIMPLE_COMMANDS)
    simple_chat = text in _SIMPLE_CHAT or (len(tokens) <= 3 and any(text.startswith(x) for x in _SIMPLE_CHAT))

    missing_facts = any(re.fullmatch(pattern, text) for pattern in _MISSING_FACT_PATTERNS)
    if missing_facts and not history:
        return CompanionRouteDecision(
            tier="flash",
            score=0.12,
            reasoning_effort=None,
            thinking_mode="disabled",
            reasons=("missing_required_facts",),
            clarification_preferred=True,
        )

    score = 0.0
    reasons: list[str] = []
    style_sensitive = False

    if style_hits and policy.route_style_to_pro:
        score = max(score, 0.90)
        reasons.append("expressive_style_request")
        style_sensitive = True
    if abstract_hits and policy.route_abstract_to_pro:
        score += min(0.78, 0.48 + 0.13 * abstract_hits)
        reasons.append("abstract_meaning")
    if relational_hits and policy.route_relational_to_pro:
        score += min(0.72, 0.42 + 0.11 * relational_hits)
        reasons.append("relational_subtext")
        style_sensitive = True
    if emotion_hits:
        score += min(0.48, 0.22 + 0.08 * emotion_hits)
        reasons.append("emotional_nuance")
        style_sensitive = True
    if context_hits and history and policy.route_contextual_ambiguity_to_pro:
        score += 0.58 if len(tokens) <= 12 else 0.38
        reasons.append("contextual_ambiguity")
    if technical_hits:
        score += min(0.72, 0.38 + 0.12 * technical_hits)
        reasons.append("technical_depth")
    if explicit_deep_hits:
        score += 0.46
        reasons.append("explicit_deep_request")

    # Long reflective questions are often semantically dense even without a
    # convenient keyword.  Length alone never selects Pro; it only nudges a turn
    # that already contains reflection or emotion.
    if len(tokens) >= 34 and (abstract_hits or relational_hits or emotion_hits):
        score += 0.12
        reasons.append("dense_reflective_turn")

    if policy.simple_turns_stay_flash and not style_hits:
        if simple_chat:
            score -= 0.55
            reasons.append("simple_social_turn")
        elif simple_command_hits and not technical_hits:
            score -= 0.42
            reasons.append("clear_simple_command")

    score = max(0.0, min(1.0, score))
    use_pro = score >= policy.pro_threshold

    if not use_pro:
        return CompanionRouteDecision(
            tier="flash",
            score=round(score, 3),
            reasoning_effort=None,
            thinking_mode="disabled",
            reasons=tuple(dict.fromkeys(reasons)) or ("clear_simple_turn",),
            clarification_preferred=missing_facts,
            style_sensitive=style_sensitive,
        )

    # Literary and relational turns benefit from the stronger model but not
    # necessarily visible chain-of-thought latency.  Abstract/technical turns use
    # thinking mode; very dense ones receive max effort.
    thinking = bool(abstract_hits or technical_hits or explicit_deep_hits)
    effort = "max" if thinking and score >= policy.max_reasoning_threshold else ("high" if thinking else None)
    return CompanionRouteDecision(
        tier="pro",
        score=round(score, 3),
        reasoning_effort=effort,
        thinking_mode="enabled" if thinking else "disabled",
        reasons=tuple(dict.fromkeys(reasons)) or ("companion_depth",),
        clarification_preferred=missing_facts,
        style_sensitive=style_sensitive,
    )


__all__ = [
    "CompanionModelRouter",
    "CompanionRouteDecision",
    "CompanionRoutingPolicy",
    "route_companion_turn",
]


class CompanionModelRouter:
    """Small injectable facade used by runtime/tests."""

    def __init__(self, policy: CompanionRoutingPolicy | None = None) -> None:
        self.policy = policy

    def route(
        self,
        user_text: str,
        *,
        recent_history: Sequence[Mapping[str, Any]] | None = None,
    ) -> CompanionRouteDecision:
        return route_companion_turn(
            user_text,
            recent_history=recent_history,
            policy=self.policy,
        )
