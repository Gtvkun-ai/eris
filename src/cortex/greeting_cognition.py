from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import Literal


GreetingSituation = Literal[
    "low_evidence_start",
    "plain_return",
    "resume_project",
    "resume_unresolved_loop",
    "after_long_absence",
    "after_crash_or_restart",
    "after_relational_feedback",
]

GreetingIntent = Literal[
    "acknowledge_return",
    "resume_continuity",
    "quiet_presence",
    "dry_tease",
    "soft_repair",
    "standby",
]


def clamp01(value) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if numeric != numeric:
        return 0.0
    return max(0.0, min(1.0, numeric))


def clean_text(value: object, *, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if text.lower() in {"none", "null", "<none>", "empty", ""}:
        return ""
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


@dataclass(frozen=True)
class GreetingFrame:
    """A small cognitive frame for startup greetings.

    This is deliberately not a guard. It tells the wording layer what kind of
    encounter this startup is. The guard layer should only stop leaks, fake
    screen/action claims, and malformed protocol output.
    """

    situation: GreetingSituation
    intent: GreetingIntent
    evidence_strength: float
    continuity_strength: float
    familiarity: float
    warmth: float
    restraint: float
    dry_edge: float
    poetic_permission: float
    active_anchor: str | None
    must_not_claim_screen: bool = True
    reason: str = ""

    def to_prompt_block(self) -> str:
        anchor = self.active_anchor or "none"
        return "\n".join(
            (
                "GREETING_FRAME:",
                f"- situation: {self.situation}",
                f"- intent: {self.intent}",
                f"- evidence_strength: {self.evidence_strength:.2f}",
                f"- continuity_strength: {self.continuity_strength:.2f}",
                f"- familiarity: {self.familiarity:.2f}",
                f"- warmth: {self.warmth:.2f}",
                f"- restraint: {self.restraint:.2f}",
                f"- dry_edge: {self.dry_edge:.2f}",
                f"- poetic_permission: {self.poetic_permission:.2f}",
                f"- active_anchor: {anchor}",
                f"- must_not_claim_screen: {int(self.must_not_claim_screen)}",
                f"- reason: {self.reason or 'none'}",
            )
        )


class GreetingCognitionEngine:
    """Builds a cognition frame for startup greetings.

    The point is not to make the greeting safer. The point is to make it less
    stupid: understand the encounter first, then let wording happen.
    """

    _LOW_EVIDENCE_FALLBACKS = (
        "À. Ngài đây rồi.",
        "Ngài mở lại rồi à.",
        "Tôi vừa thấy Ngài quay lại.",
        "Ừm. Lại gặp Ngài.",
        "Ngài đến rồi.",
    )

    _QUIET_FALLBACKS = (
        "À. Tôi đang yên, nhưng có thấy Ngài.",
        "Ngài cứ làm tiếp đi. Tôi ở đây.",
        "Tôi sẽ không chen vào. Chỉ là... tôi thấy Ngài rồi.",
        "Ừm. Tôi giữ im lặng một chút.",
        "Ngài quay lại rồi. Tôi không làm ồn đâu.",
    )

    _RESUME_FALLBACKS = (
        "À. Đoạn đó vẫn chưa mất.",
        "Ngài quay lại đúng lúc. Mạch cũ vẫn còn đây.",
        "Tôi vẫn nhớ mình đang bỏ dở chỗ nào.",
        "Tiếp đoạn trước nhỉ. Tôi theo được.",
        "Mạch đó còn hơi vướng lại. Tôi giữ được.",
    )

    _REPAIR_FALLBACKS = (
        "Ngài quay lại rồi. Tôi sẽ nói mềm hơn.",
        "Tôi biết. Lúc nãy tôi hơi cứng.",
        "Lần này tôi hạ giọng xuống.",
        "Tôi sẽ bớt sắc lại. Một chút.",
        "Ừm. Tôi sẽ không đẩy Ngài ra xa như vừa rồi.",
    )

    def _fallback_pool(self, frame: GreetingFrame) -> tuple[str, ...]:
        if frame.situation == "after_relational_feedback":
            return self._REPAIR_FALLBACKS
        if frame.situation in {"resume_project", "resume_unresolved_loop"}:
            if clean_text(frame.active_anchor or "", limit=64):
                return self._RESUME_FALLBACKS
            return self._RESUME_FALLBACKS[1:] or self._RESUME_FALLBACKS
        if frame.situation == "plain_return" and frame.evidence_strength >= 0.30:
            return self._QUIET_FALLBACKS
        return self._LOW_EVIDENCE_FALLBACKS

    def _normalized_surface(self, text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "").strip().lower())

    def _fallback_index(self, frame: GreetingFrame, *, pool_size: int) -> int:
        if pool_size <= 1:
            return 0
        anchor = clean_text(frame.active_anchor or "", limit=96)
        seed = "|".join(
            (
                frame.situation,
                frame.intent,
                f"{frame.evidence_strength:.2f}",
                f"{frame.continuity_strength:.2f}",
                f"{frame.familiarity:.2f}",
                f"{frame.warmth:.2f}",
                f"{frame.dry_edge:.2f}",
                anchor,
            )
        )
        if not anchor and frame.situation in {"low_evidence_start", "plain_return"}:
            seed = f"{seed}|{time.time_ns()}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % pool_size

    def build(
        self,
        *,
        presence_restored: bool = False,
        continuity_restored: bool = False,
        active_goal: str = "",
        current_attractor: str = "",
        unresolved_loops: tuple[str, ...] = (),
        recent_direction: str = "",
        self_continuity: str = "",
        tone: str = "",
        greeted_recently: bool = False,
        relational_feedback: str = "",
    ) -> GreetingFrame:
        active_goal = clean_text(active_goal)
        current_attractor = clean_text(current_attractor)
        recent_direction = clean_text(recent_direction)
        self_continuity = clean_text(self_continuity)
        relational_feedback = clean_text(relational_feedback)
        loops = tuple(clean_text(item) for item in (unresolved_loops or ()) if clean_text(item))[:3]

        active_anchor = active_goal or current_attractor or (loops[0] if loops else "") or recent_direction or self_continuity
        continuity_strength = 0.12
        if continuity_restored:
            continuity_strength += 0.22
        if active_goal:
            continuity_strength += 0.35
        if current_attractor:
            continuity_strength += 0.22
        if loops:
            continuity_strength += min(0.24, 0.08 * len(loops))
        if recent_direction:
            continuity_strength += 0.12
        if self_continuity:
            continuity_strength += 0.08
        continuity_strength = clamp01(continuity_strength)

        evidence_strength = 0.10
        if presence_restored:
            evidence_strength += 0.18
        if active_anchor:
            evidence_strength += 0.22
        if continuity_restored:
            evidence_strength += 0.10
        evidence_strength = clamp01(evidence_strength)

        if relational_feedback:
            situation: GreetingSituation = "after_relational_feedback"
            intent: GreetingIntent = "soft_repair"
            poetic_permission = 0.0
            warmth = 0.40
            dry_edge = 0.18
            reason = "recent relational tone feedback should shape the greeting without apology theater"
        elif active_goal or "project" in active_anchor.lower() or "code" in active_anchor.lower():
            situation = "resume_project"
            intent = "resume_continuity"
            poetic_permission = 0.05
            warmth = 0.30
            dry_edge = 0.28
            reason = "startup has a concrete continuity anchor"
        elif current_attractor or loops or recent_direction:
            situation = "resume_unresolved_loop"
            intent = "resume_continuity"
            poetic_permission = 0.06
            warmth = 0.28
            dry_edge = 0.25
            reason = "startup has an unresolved cognitive anchor"
        elif evidence_strength < 0.25:
            situation = "low_evidence_start"
            intent = "acknowledge_return"
            poetic_permission = 0.0
            warmth = 0.24
            dry_edge = 0.30
            reason = "thin evidence; use plain return acknowledgement"
        else:
            situation = "plain_return"
            intent = "acknowledge_return"
            poetic_permission = 0.02
            warmth = 0.28
            dry_edge = 0.28
            reason = "ordinary startup return"

        if greeted_recently:
            warmth *= 0.85
            dry_edge += 0.05

        if str(tone or "").strip().lower() == "overloaded":
            warmth *= 0.75
            dry_edge += 0.05
            poetic_permission = 0.0

        return GreetingFrame(
            situation=situation,
            intent=intent,
            evidence_strength=evidence_strength,
            continuity_strength=continuity_strength,
            familiarity=0.55 if continuity_restored else 0.42,
            warmth=clamp01(warmth),
            restraint=0.78,
            dry_edge=clamp01(dry_edge),
            poetic_permission=clamp01(poetic_permission),
            active_anchor=active_anchor or None,
            must_not_claim_screen=True,
            reason=reason,
        )

    def from_prompt_context(self, context: str) -> GreetingFrame:
        text = str(context or "")

        def field(name: str) -> str:
            match = re.search(rf"^{re.escape(name)}:\s*(.+?)\s*$", text, flags=re.IGNORECASE | re.MULTILINE)
            return clean_text(match.group(1) if match else "")

        flags_line = field("session_flags")

        def flag(name: str) -> bool:
            match = re.search(rf"{re.escape(name)}\s*=\s*([01]|true|false)", flags_line, flags=re.IGNORECASE)
            if not match:
                return False
            return match.group(1).lower() in {"1", "true"}

        loops_raw = field("rehydrated_loops")
        loops = tuple(
            clean_text(item)
            for item in re.split(r"\s*\|\s*", loops_raw)
            if clean_text(item)
        )
        if loops == ("none",):
            loops = ()

        return self.build(
            presence_restored=flag("presence_restored"),
            continuity_restored=flag("continuity_restored"),
            active_goal=field("rehydrated_goal"),
            current_attractor=field("current_attractor"),
            unresolved_loops=loops,
            recent_direction=field("recent_cognition_direction"),
            self_continuity=field("self_continuity"),
            tone=re.search(r"tone=([^,\.]+)", flags_line).group(1).strip() if re.search(r"tone=([^,\.]+)", flags_line) else "",
        )

    def deterministic_greeting(self, frame: GreetingFrame, *, avoid_text: str = "") -> str:
        pool = self._fallback_pool(frame)
        if not pool:
            return ""
        start = self._fallback_index(frame, pool_size=len(pool))
        avoid_norm = self._normalized_surface(avoid_text)
        ordered = [pool[(start + offset) % len(pool)] for offset in range(len(pool))]
        if avoid_norm:
            for candidate in ordered:
                if self._normalized_surface(candidate) != avoid_norm:
                    return candidate
        return ordered[0]
