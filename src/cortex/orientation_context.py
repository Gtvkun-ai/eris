from __future__ import annotations

"""
orientation_context.py
======================

Shared semantic substrate for ERIS' Ni and GoalPersistence layers.

Why this file exists
--------------------
Ni and GoalPersistence must not each keep their own little pile of keyword
superstition. That creates two independent judges:
    - Ni decides the user is drifting.
    - GoalPersistence decides the user has a task.
Then both amplify each other and ERIS becomes a productivity supervisor with
better hair.

This module centralizes lightweight semantic interpretation:
    - activity intent: research / recovery / play / avoidance / technical focus
    - user goal intent: concrete task / debug thread / design direction / casual
    - closure detection with negation handling
    - goal relation and intervention pressure
    - token/anchor matching for safe goal merge

It is still heuristic, because no local embedding model is assumed here.
The important design choice: heuristics produce *hypotheses* and *permission*,
not moral verdicts.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping, Sequence


# ---------------------------------------------------------------------------
# Basic utilities
# ---------------------------------------------------------------------------

_REMOVABLE_URL_BITS = re.compile(r"https?://|www\.|[?&=#%]")
_WORD_RE = re.compile(r"[a-z0-9#+.]+")

STOP_WORDS: set[str] = {
    # English function words
    "and", "the", "for", "from", "this", "that", "with", "then", "than",
    "into", "onto", "about", "what", "when", "where", "which", "while",
    "because", "should", "could", "would", "there", "their", "have", "has",
    "had", "was", "were", "are", "is", "be", "been", "being",
    # Vietnamese function words normalized without accents
    "dang", "trong", "cua", "voi", "khi", "thi", "neu", "ngai", "toi",
    "mot", "nhung", "khong", "duoc", "cho", "cai", "nay", "kia", "roi",
    "nhe", "nhi", "vay", "day", "nua", "qua", "hoi", "lam", "nha", "the",
}


def clamp01(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:  # NaN
        return 0.0
    return max(0.0, min(1.0, number))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def clean_text(value: object, *, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def normalize(value: object) -> str:
    """Normalize for semantic matching, not for display.

    Vietnamese 'đ' is replaced manually because Unicode decomposition does not
    fold it into 'd'. The result is intentionally plain ASCII-ish text.
    """

    raw = str(value or "").strip().lower().replace("đ", "d")
    raw = unicodedata.normalize("NFKD", raw)
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = _REMOVABLE_URL_BITS.sub(" ", raw)
    raw = re.sub(r"[^a-z0-9#+./:\s_-]+", " ", raw)
    raw = raw.replace("_", " ").replace("-", " ")
    return " ".join(raw.split())


def tokens(value: object, *, keep_short_code_tokens: bool = True) -> set[str]:
    result: set[str] = set()
    for token in _WORD_RE.findall(normalize(value)):
        if token in STOP_WORDS:
            continue
        if len(token) < 3 and not (keep_short_code_tokens and token in {"c#", "c++", "ai", "ui"}):
            continue
        result.add(token)
    return result


def phrase_in(normalized: str, phrase: str) -> bool:
    phrase_norm = normalize(phrase)
    if not phrase_norm:
        return False
    return phrase_norm in normalized


def has_any(normalized: str, phrases: Sequence[str]) -> bool:
    return any(phrase_in(normalized, phrase) for phrase in phrases)


def count_hits(normalized: str, phrases: Sequence[str]) -> int:
    return sum(1 for phrase in phrases if phrase_in(normalized, phrase))


def unique_recent(items: Iterable[str], *, limit: int = 8) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = clean_text(item, limit=160)
        key = normalize(text)
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return tuple(out[-limit:])


# ---------------------------------------------------------------------------
# Phrase groups
# ---------------------------------------------------------------------------

TECHNICAL_TERMS: tuple[str, ...] = (
    "code", "coding", "source", "bug", "debug", "fix", "terminal", "commit",
    "review", "python", "c#", "c++", "godot", "vscode", "visual studio", "cursor",
    "api", "sdk", "stack overflow", "stackoverflow", "github", "git", "readme",
    "traceback", "exception", "error", "build", "compile", "runtime", "script",
    "class", "function", "method", "json", "xml", "udp", "http", "llm", "model",
    "coordinator", "engine", "module", "dataclass", "pipeline", "parser", "guard",
)

LEARNING_TERMS: tuple[str, ...] = (
    "tutorial", "course", "lesson", "guide", "docs", "documentation", "manual",
    "how to", "example", "explain", "giai thich", "huong dan", "hoc", "tai lieu",
    "fix loi", "sua loi", "cach fix", "learn", "reference", "research", "paper",
)

MEDIA_TERMS: tuple[str, ...] = (
    "youtube", "youtu", "video", "playlist", "podcast", "music", "lofi", "soundtrack",
    "nhac", "bai hat", "background", "stream", "watch", "xem video",
)

SHORT_FORM_TERMS: tuple[str, ...] = (
    "shorts", "tiktok", "reel", "reels", "doomscroll", "scroll vo thuc", "keo vo thuc",
)

PLAY_TERMS: tuple[str, ...] = (
    "steam", "game", "gaming", "anime", "manga", "movie", "netflix", "film", "trailer",
    "rimworld", "skyrim", "factorio", "genshin", "wuthering", "wuwa", "toram",
)

COMMUNICATION_TERMS: tuple[str, ...] = (
    "zalo", "messenger", "facebook", "discord", "slack", "teams", "telegram",
    "gmail", "mail", "meeting", "meet", "chat", "call", "zoom", "tin nhan", "nhan tin",
)

RECOVERY_TERMS: tuple[str, ...] = (
    "break", "rest", "relax", "chill", "nghi", "thu gian", "giai lao", "nghe nhac",
    "nghi mat", "hoi phuc", "met", "burnout", "tam nghi", "di ia", "an com", "ngu",
)

AVOIDANCE_TERMS: tuple[str, ...] = (
    "ne viec", "tron viec", "luoi", "procrastinate", "procrastination", "mat tap trung",
    "le viec", "lan nua", "cuon", "nghien", "sa lay", "avoid", "escape from friction",
)

SYSTEM_WAIT_TERMS: tuple[str, ...] = (
    "install", "installer", "update", "download", "loading", "build", "compile", "deploy",
    "render", "wait", "waiting", "cho build", "dang build", "dang cai", "setup", "restart",
)

TASK_VERBS_STRONG: tuple[str, ...] = (
    "fix", "sua", "debug", "implement", "add", "them", "build", "tao", "viet",
    "refactor", "review", "danh gia", "test", "wire", "connect", "noi", "rewrite",
    "nang cap", "toi uu", "patch", "replace", "split", "tach", "merge",
)

TASK_VERBS_SOFT: tuple[str, ...] = (
    "nen lam", "can lam", "phai lam", "huong fix", "cach fix", "doc benh", "xem loi",
    "giai thich", "phan tich", "kiem tra", "soi", "danh gia", "on chua",
)

DESIGN_TERMS: tuple[str, ...] = (
    "architecture", "kien truc", "design", "thiet ke", "pipeline", "cortex", "runtime",
    "semantic", "emergent", "memory", "state", "continuity", "relationship", "dynamics",
    "infj", "eris", "ni", "fe", "ti", "se", "goal", "planner", "speech", "meaning",
)

FILE_OR_MODULE_RE = re.compile(r"\b[a-zA-Z_][a-zA-Z0-9_]*(?:\.py|\.cs|\.gd|\.tscn|\.json|\.txt|\.xml)\b")

CASUAL_MARKERS: tuple[str, ...] = (
    "dang chill", "noi chuyen", "tam su", "cho vui", "ke di", "hihi", "haha", "ban gai",
    "di ia", "toi vui", "cuoc doi", "hom nay", "nghi xiu", "ke di", "thich qua",
)

NEGATION_TERMS: tuple[str, ...] = (
    "khong", "chua", "not", "no", "never", "van chua", "chua he", "chua phai", "dau co",
)

CLOSURE_TERMS: tuple[str, ...] = (
    "done", "fixed", "resolved", "solved", "complete", "completed", "close_goal",
    "xong", "da xong", "giai quyet", "dong goal", "ổn rồi", "on roi", "hết lỗi", "het loi",
)

REJECTION_AFTER_CLOSURE: tuple[str, ...] = (
    "chua xong", "khong xong", "not done", "not fixed", "not resolved", "van loi",
    "van chua", "chua fixed", "chua resolve", "con loi", "fail", "sai roi", "chua on",
)


# ---------------------------------------------------------------------------
# Shared semantic dataclasses
# ---------------------------------------------------------------------------

class ActivityIntentLabel(str, Enum):
    RESEARCH = "research"
    TECHNICAL_FOCUS = "technical_focus"
    SUPPORTIVE_BACKGROUND = "supportive_background"
    RECOVERY = "recovery"
    PLAY_OR_RECOVERY = "play_or_recovery"
    POSSIBLE_AVOIDANCE = "possible_avoidance"
    FRAGMENTED_SWITCHING = "fragmented_switching"
    SOCIAL_COORDINATION = "social_coordination"
    SYSTEM_WAITING = "system_waiting"
    UNKNOWN = "unknown"


class GoalRelationLabel(str, Enum):
    ALIGNED = "aligned"
    ADJACENT = "adjacent"
    NEUTRAL = "neutral"
    CONFLICTING = "conflicting"
    UNKNOWN = "unknown"


class GoalTextKind(str, Enum):
    CONCRETE_TASK = "concrete_task"
    DEBUG_THREAD = "debug_thread"
    DESIGN_DIRECTION = "design_direction"
    RESEARCH_THREAD = "research_thread"
    REVIEW_REQUEST = "review_request"
    CORRECTION_THREAD = "correction_thread"
    CASUAL = "casual"
    RECOVERY = "recovery"
    COMMENTARY = "commentary"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class ActivityIntent:
    label: str = ActivityIntentLabel.UNKNOWN.value
    confidence: float = 0.25
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GoalRelation:
    label: str = GoalRelationLabel.UNKNOWN.value
    confidence: float = 0.25
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OrientationSignal:
    intent: ActivityIntent
    relation: GoalRelation
    orientation_coherence: float
    goal_conflict_score: float
    intervention_pressure: float
    confidence: float
    reason_span: str
    evidence: tuple[str, ...] = ()
    channels: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GoalTextSignal:
    """Semantic signal extracted from direct user text.

    persist_permission:
        Whether the text deserves durable background tracking.

    intervention_permission:
        Whether ERIS may bring the goal up proactively later.
        A goal can be persistent but not interruptive. This single distinction
        prevents the delightful abomination called "helpful nagging".
    """

    kind: str = GoalTextKind.NONE.value
    summary: str = ""
    confidence: float = 0.0
    strength: float = 0.0
    urgency: float = 0.0
    persist_permission: float = 0.0
    intervention_permission: float = 0.0
    actionability: float = 0.0
    evidence: tuple[str, ...] = ()
    anchors: tuple[str, ...] = ()

    @property
    def should_persist(self) -> bool:
        return self.persist_permission >= 0.55 and self.confidence >= 0.42 and bool(self.summary)

    @property
    def can_intervene(self) -> bool:
        return self.intervention_permission >= 0.55 and self.actionability >= 0.45


@dataclass(frozen=True, slots=True)
class ClosureSignal:
    closed: bool
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SemanticContextProbe:
    focus_kind: str = "general"
    focus_text: str = ""
    window_text: str = ""
    browsing_text: str = ""
    memory_text: str = ""
    current_text: str = ""
    idle_seconds: float = 0.0
    open_window_count: int = 0
    active_goal_strength: float = 0.0
    active_goal_type: str = ""
    active_goal_intervention_permission: float = 0.0
    active_goal_summary: str = ""

    @property
    def combined_text(self) -> str:
        return " ".join(
            part
            for part in (
                self.focus_text,
                self.window_text,
                self.browsing_text,
                self.memory_text,
                self.current_text,
                self.active_goal_summary,
            )
            if part
        )


def extract_anchors(text: str, *, max_items: int = 10) -> tuple[str, ...]:
    norm = normalize(text)
    result: list[str] = []

    for match in FILE_OR_MODULE_RE.findall(str(text or "")):
        result.append(match)

    for phrase_group in (TECHNICAL_TERMS, DESIGN_TERMS):
        for phrase in phrase_group:
            p = normalize(phrase)
            if p and p in norm:
                result.append(phrase)

    # Include high-information tokens as fallback.
    for token in sorted(tokens(text)):
        if len(token) >= 5:
            result.append(token)

    return unique_recent(result, limit=max_items)


def goal_match_score(left: str, right: str, *, left_anchors: Sequence[str] = (), right_anchors: Sequence[str] = ()) -> float:
    """Weighted match for merging durable goals.

    The old "overlap >= 2" rule makes every ERIS technical sentence look like
    the same goal. This matcher asks for either anchor overlap or stronger token
    overlap. Shocking: two random mentions of "system" and "fix" are not destiny.
    """

    left_tokens = tokens(left)
    right_tokens = tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0

    token_overlap = len(left_tokens & right_tokens)
    token_ratio = token_overlap / max(1, min(len(left_tokens), len(right_tokens)))

    la = {normalize(a) for a in left_anchors if normalize(a)}
    ra = {normalize(a) for a in right_anchors if normalize(a)}
    anchor_overlap = len(la & ra)
    anchor_ratio = anchor_overlap / max(1, min(len(la), len(ra))) if la and ra else 0.0

    score = token_ratio * 0.55 + min(1.0, token_overlap / 5.0) * 0.15 + anchor_ratio * 0.30
    if anchor_overlap >= 1:
        score += 0.18
    if token_overlap >= 5:
        score += 0.08
    return clamp01(score)


def has_negated_closure(text: str) -> bool:
    norm = normalize(text)
    if has_any(norm, REJECTION_AFTER_CLOSURE):
        return True

    words = norm.split()
    closure_words = {normalize(term) for term in CLOSURE_TERMS}
    neg_words = {normalize(term) for term in NEGATION_TERMS}
    for i, word in enumerate(words):
        if word in closure_words:
            window = words[max(0, i - 3): i]
            if any(w in neg_words for w in window):
                return True
    return False


def infer_closure_signal(text: str, *, thought_stream_report: object = None) -> ClosureSignal:
    norm = normalize(text)
    evidence: list[str] = []
    confidence = 0.0

    if has_negated_closure(text):
        return ClosureSignal(False, 0.0, ("negated_closure",))

    if has_any(norm, CLOSURE_TERMS):
        evidence.append("closure_phrase")
        confidence = 0.74

    for disturbance in tuple(getattr(thought_stream_report, "disturbances", ()) or ()):  # compatible with existing stream
        if bool(getattr(disturbance, "closes_loop", False)):
            evidence.append("thought_stream_closes_loop")
            confidence = max(confidence, 0.64)

    return ClosureSignal(confidence >= 0.55, confidence, tuple(evidence))


def infer_goal_text_signal(text: str, *, channel: str = "chat", force_speak: bool = False) -> GoalTextSignal:
    """Classify direct user text as a durable goal candidate or not.

    This function deliberately rejects "long sentence = goal". Human speech can
    be exploratory, casual, frustrated, playful, or just noise with grammar.
    Tragic, yes, but code has to cope.
    """

    raw = clean_text(text, limit=220)
    norm = normalize(raw)
    if not raw:
        return GoalTextSignal()

    evidence: list[str] = []
    anchors = extract_anchors(raw)
    token_count = len(tokens(raw))
    is_direct_channel = channel in {"chat", "force_speak"} or bool(force_speak)

    if has_any(norm, CASUAL_MARKERS) and not (has_any(norm, TASK_VERBS_STRONG) or anchors):
        return GoalTextSignal(
            kind=GoalTextKind.CASUAL.value,
            summary=raw,
            confidence=0.58,
            evidence=("casual_marker",),
            anchors=anchors,
        )

    if has_any(norm, RECOVERY_TERMS) and not (has_any(norm, TASK_VERBS_STRONG) or anchors):
        return GoalTextSignal(
            kind=GoalTextKind.RECOVERY.value,
            summary=raw,
            confidence=0.62,
            evidence=("recovery_marker",),
            anchors=anchors,
        )

    strong_task = has_any(norm, TASK_VERBS_STRONG)
    soft_task = has_any(norm, TASK_VERBS_SOFT)
    has_design = has_any(norm, DESIGN_TERMS)
    has_tech = has_any(norm, TECHNICAL_TERMS)
    has_learning = has_any(norm, LEARNING_TERMS)
    has_question_shape = "?" in raw or any(phrase_in(norm, p) for p in ("sao", "vi sao", "tai sao", "nen", "co nen", "what", "why", "how"))
    has_file_anchor = bool(FILE_OR_MODULE_RE.search(raw))
    correction_like = has_any(norm, ("sai roi", "khong phai", "thieu", "chua dung", "nham", "fix lai", "doc lai"))

    kind = GoalTextKind.NONE.value
    confidence = 0.0
    strength = 0.0
    urgency = 0.0
    persist = 0.0
    intervene = 0.0
    actionability = 0.0

    if is_direct_channel and correction_like and (has_tech or has_design or anchors):
        kind = GoalTextKind.CORRECTION_THREAD.value
        evidence.append("technical_correction")
        confidence = 0.66
        strength = 0.54
        urgency = 0.46
        persist = 0.62
        intervene = 0.42
        actionability = 0.56

    elif is_direct_channel and (strong_task or has_file_anchor) and (has_tech or has_design or anchors):
        kind = GoalTextKind.CONCRETE_TASK.value
        evidence.append("explicit_task_with_anchor")
        confidence = 0.76
        strength = 0.72
        urgency = 0.52
        persist = 0.82
        intervene = 0.58
        actionability = 0.78

    elif is_direct_channel and (soft_task or has_question_shape) and (has_tech or has_design):
        kind = GoalTextKind.DEBUG_THREAD.value if ("loi" in norm or "error" in norm or "bug" in norm or "debug" in norm) else GoalTextKind.REVIEW_REQUEST.value
        evidence.append("technical_question_or_review")
        confidence = 0.64
        strength = 0.58
        urgency = 0.42
        persist = 0.64
        intervene = 0.38
        actionability = 0.54

    elif is_direct_channel and has_design and token_count >= 5:
        kind = GoalTextKind.DESIGN_DIRECTION.value
        evidence.append("design_direction")
        confidence = 0.58
        strength = 0.50
        urgency = 0.30
        persist = 0.58
        intervene = 0.26
        actionability = 0.38

    elif is_direct_channel and has_learning and (has_question_shape or has_tech):
        kind = GoalTextKind.RESEARCH_THREAD.value
        evidence.append("research_thread")
        confidence = 0.55
        strength = 0.42
        urgency = 0.24
        persist = 0.52
        intervene = 0.18
        actionability = 0.32

    elif token_count >= 10 and (has_tech or has_design) and (strong_task or soft_task):
        # Fallback for long technical directive-like messages. Still weaker than explicit task.
        kind = GoalTextKind.COMMENTARY.value
        evidence.append("long_technical_commentary")
        confidence = 0.44
        strength = 0.34
        urgency = 0.18
        persist = 0.42
        intervene = 0.10
        actionability = 0.22

    else:
        return GoalTextSignal(
            kind=GoalTextKind.COMMENTARY.value if token_count >= 5 else GoalTextKind.NONE.value,
            summary=raw,
            confidence=0.30,
            evidence=("insufficient_goal_commitment",),
            anchors=anchors,
        )

    return GoalTextSignal(
        kind=kind,
        summary=raw,
        confidence=clamp01(confidence),
        strength=clamp01(strength),
        urgency=clamp01(urgency),
        persist_permission=clamp01(persist),
        intervention_permission=clamp01(intervene),
        actionability=clamp01(actionability),
        evidence=tuple(evidence),
        anchors=anchors,
    )


# ---------------------------------------------------------------------------
# Activity/orientation inference used by Ni
# ---------------------------------------------------------------------------

class OrientationInterpreter:
    """Shared interpreter for Ni.

    It reads context as a field of possible meanings, not as an app-category
    morality table. Yes, that sentence sounds like a philosophy undergraduate,
    but here it merely means "do not punish YouTube when the tab says Godot".
    """

    def infer_activity_intent(self, probe: SemanticContextProbe) -> ActivityIntent:
        norm = normalize(probe.combined_text)
        evidence: list[str] = []

        has_technical = has_any(norm, TECHNICAL_TERMS)
        has_learning = has_any(norm, LEARNING_TERMS)
        has_media = has_any(norm, MEDIA_TERMS)
        has_short = has_any(norm, SHORT_FORM_TERMS)
        has_play = has_any(norm, PLAY_TERMS)
        has_comm = has_any(norm, COMMUNICATION_TERMS)
        has_recovery = has_any(norm, RECOVERY_TERMS)
        has_avoidance = has_any(norm, AVOIDANCE_TERMS)
        has_system_wait = has_any(norm, SYSTEM_WAIT_TERMS)

        if has_avoidance:
            evidence.append("explicit_avoidance_language")
            return ActivityIntent(ActivityIntentLabel.POSSIBLE_AVOIDANCE.value, 0.72, tuple(evidence))

        if has_media and (has_technical or has_learning):
            evidence.append("media_with_learning_or_technical_terms")
            return ActivityIntent(ActivityIntentLabel.RESEARCH.value, 0.76, tuple(evidence))

        if has_system_wait and probe.focus_kind in {"coding", "documentation", "system", "general"}:
            evidence.append("system_or_build_waiting")
            return ActivityIntent(ActivityIntentLabel.SYSTEM_WAITING.value, 0.64, tuple(evidence))

        if has_media and probe.focus_kind == "focus_aid_media" and not has_short:
            evidence.append("media_as_focus_aid")
            return ActivityIntent(ActivityIntentLabel.SUPPORTIVE_BACKGROUND.value, 0.62, tuple(evidence))

        if has_short:
            evidence.append("short_form_media")
            if probe.active_goal_strength >= 0.35:
                return ActivityIntent(ActivityIntentLabel.POSSIBLE_AVOIDANCE.value, 0.62, tuple(evidence))
            return ActivityIntent(ActivityIntentLabel.RECOVERY.value, 0.46, tuple(evidence))

        if probe.focus_kind in {"coding", "documentation"} or has_technical:
            evidence.append("technical_or_documentation_context")
            return ActivityIntent(ActivityIntentLabel.TECHNICAL_FOCUS.value, 0.66 if has_technical else 0.55, tuple(evidence))

        if has_learning:
            evidence.append("learning_terms_without_media")
            return ActivityIntent(ActivityIntentLabel.RESEARCH.value, 0.58, tuple(evidence))

        if has_comm or probe.focus_kind == "communication":
            evidence.append("communication_context")
            return ActivityIntent(ActivityIntentLabel.SOCIAL_COORDINATION.value, 0.56, tuple(evidence))

        if has_recovery:
            evidence.append("recovery_language")
            return ActivityIntent(ActivityIntentLabel.RECOVERY.value, 0.64, tuple(evidence))

        if has_play or probe.focus_kind == "entertainment":
            evidence.append("play_or_entertainment_context")
            confidence = 0.50 if probe.active_goal_strength < 0.50 else 0.42
            return ActivityIntent(ActivityIntentLabel.PLAY_OR_RECOVERY.value, confidence, tuple(evidence))

        if probe.idle_seconds >= 900 and probe.active_goal_strength < 0.25:
            evidence.append("long_idle_without_goal_pressure")
            return ActivityIntent(ActivityIntentLabel.RECOVERY.value, 0.40, tuple(evidence))

        evidence.append("insufficient_semantic_signal")
        return ActivityIntent(ActivityIntentLabel.UNKNOWN.value, 0.28, tuple(evidence))

    def infer_idle_posture(self, probe: SemanticContextProbe, intent_label: str) -> tuple[str, float, tuple[str, ...]]:
        idle = float(probe.idle_seconds or 0.0)
        if idle < 60:
            return "active", 0.00, ("idle=active",)
        if idle < 300:
            return "short_stillness", 0.10, ("idle=short_stillness",)
        if idle < 900:
            if probe.focus_kind in {"coding", "documentation"}:
                return "possible_reading_or_thinking", 0.22, ("idle=possible_reading_or_thinking",)
            if intent_label in {"supportive_background", "recovery", "play_or_recovery"}:
                return "passive_recovery_possible", 0.20, ("idle=passive_recovery_possible",)
            return "medium_ambiguous", 0.28, ("idle=medium_ambiguous",)

        if probe.focus_kind in {"coding", "documentation", "system"}:
            return "long_thinking_waiting_or_stall", 0.38, ("idle=long_thinking_waiting_or_stall",)
        if intent_label in {"recovery", "play_or_recovery", "supportive_background"}:
            return "extended_recovery_or_drift", 0.34, ("idle=extended_recovery_or_drift",)
        return "long_ambiguous", 0.42, ("idle=long_ambiguous",)

    def estimate_fragmentation(self, probe: SemanticContextProbe) -> float:
        count = int(probe.open_window_count or 0)
        fragmentation = 0.0
        if count >= 12:
            fragmentation += 0.18
        elif count >= 9:
            fragmentation += 0.12
        elif count >= 7:
            fragmentation += 0.07
        if probe.focus_kind == "communication":
            fragmentation *= 0.45
        if has_any(normalize(probe.combined_text), ("alt tab", "switch", "window switch", "doi cua so", "nhay tab")):
            fragmentation += 0.12
        return clamp01(fragmentation)

    def infer_goal_relation(self, *, intent: ActivityIntent, probe: SemanticContextProbe, fragmentation: float, idle_label: str) -> GoalRelation:
        evidence: list[str] = []
        active_goal_strength = clamp01(probe.active_goal_strength)
        intervention_perm = clamp01(probe.active_goal_intervention_permission)

        if intent.label in {"technical_focus", "research", "system_waiting"}:
            label = GoalRelationLabel.ALIGNED.value
            confidence = 0.64 if active_goal_strength >= 0.25 else 0.50
            evidence.append("intent_supports_work_or_learning")

        elif intent.label == "supportive_background":
            label = GoalRelationLabel.ADJACENT.value
            confidence = 0.56
            evidence.append("background_support_not_goal_conflict")

        elif intent.label == "social_coordination":
            label = GoalRelationLabel.ADJACENT.value if active_goal_strength >= 0.30 else GoalRelationLabel.NEUTRAL.value
            confidence = 0.48
            evidence.append("communication_may_be_coordination")

        elif intent.label == "recovery":
            label = GoalRelationLabel.NEUTRAL.value
            confidence = 0.56
            evidence.append("recovery_is_valid_state")

        elif intent.label == "play_or_recovery":
            if active_goal_strength >= 0.62 and intervention_perm >= 0.50 and fragmentation >= 0.12:
                label = GoalRelationLabel.CONFLICTING.value
                confidence = 0.54
                evidence.append("play_with_high_goal_pressure_and_fragmentation")
            else:
                label = GoalRelationLabel.NEUTRAL.value
                confidence = 0.45
                evidence.append("play_not_automatically_conflict")

        elif intent.label == "possible_avoidance":
            if active_goal_strength >= 0.35 and intervention_perm >= 0.35:
                label = GoalRelationLabel.CONFLICTING.value
                confidence = max(0.56, intent.confidence)
                evidence.append("avoidance_signal_over_active_goal")
            else:
                label = GoalRelationLabel.NEUTRAL.value
                confidence = 0.40
                evidence.append("avoidance_without_clear_intervention_permission")

        elif intent.label == "fragmented_switching":
            label = GoalRelationLabel.CONFLICTING.value if active_goal_strength >= 0.40 else GoalRelationLabel.UNKNOWN.value
            confidence = 0.46
            evidence.append("fragmentation_relation_uncertain")

        else:
            label = GoalRelationLabel.UNKNOWN.value
            confidence = 0.28
            evidence.append("unknown_relation")

        if idle_label in {"long_thinking_waiting_or_stall", "long_ambiguous"} and label == GoalRelationLabel.CONFLICTING.value:
            confidence -= 0.08
            evidence.append("long_idle_lowers_conflict_certainty")

        return GoalRelation(label=label, confidence=clamp01(confidence), evidence=tuple(evidence))

    def estimate_orientation(self, probe: SemanticContextProbe) -> OrientationSignal:
        evidence: list[str] = [f"focus_kind={probe.focus_kind}"]
        if probe.active_goal_strength > 0.0:
            evidence.append(f"active_goal_strength={probe.active_goal_strength:.2f}")
        if probe.active_goal_intervention_permission > 0.0:
            evidence.append(f"goal_intervention_permission={probe.active_goal_intervention_permission:.2f}")

        intent = self.infer_activity_intent(probe)
        evidence.extend(intent.evidence)

        idle_label, idle_ambiguity, idle_evidence = self.infer_idle_posture(probe, intent.label)
        evidence.extend(idle_evidence)

        fragmentation = self.estimate_fragmentation(probe)
        if fragmentation > 0.0:
            evidence.append(f"fragmentation={fragmentation:.2f}")

        relation = self.infer_goal_relation(intent=intent, probe=probe, fragmentation=fragmentation, idle_label=idle_label)
        evidence.extend(relation.evidence)

        coherence = self._estimate_coherence(
            intent=intent,
            relation=relation,
            active_goal_strength=probe.active_goal_strength,
            fragmentation=fragmentation,
            idle_ambiguity=idle_ambiguity,
            combined_text=probe.combined_text,
        )
        conflict = self._estimate_conflict(
            intent=intent,
            relation=relation,
            active_goal_strength=probe.active_goal_strength,
            active_goal_intervention_permission=probe.active_goal_intervention_permission,
            fragmentation=fragmentation,
            idle_ambiguity=idle_ambiguity,
        )
        intervention = self._estimate_intervention_pressure(
            intent=intent,
            relation=relation,
            active_goal_strength=probe.active_goal_strength,
            active_goal_intervention_permission=probe.active_goal_intervention_permission,
            conflict=conflict,
            fragmentation=fragmentation,
            idle_ambiguity=idle_ambiguity,
            idle_label=idle_label,
        )
        confidence = self._estimate_confidence(
            probe=probe,
            intent=intent,
            relation=relation,
            idle_ambiguity=idle_ambiguity,
            fragmentation=fragmentation,
        )

        reason = (
            f"{probe.focus_kind}:intent={intent.label}:relation={relation.label}:"
            f"coh={coherence:.2f}:conflict={conflict:.2f}:intervene={intervention:.2f}"
        )
        evidence.extend(
            (
                f"intent={intent.label}:{intent.confidence:.2f}",
                f"relation={relation.label}:{relation.confidence:.2f}",
                f"coherence={coherence:.2f}",
                f"goal_conflict={conflict:.2f}",
                f"intervention={intervention:.2f}",
                f"confidence={confidence:.2f}",
            )
        )

        return OrientationSignal(
            intent=intent,
            relation=relation,
            orientation_coherence=coherence,
            goal_conflict_score=conflict,
            intervention_pressure=intervention,
            confidence=confidence,
            reason_span=reason,
            evidence=tuple(evidence),
            channels={
                "intent_confidence": intent.confidence,
                "relation_confidence": relation.confidence,
                "active_goal_strength": clamp01(probe.active_goal_strength),
                "goal_intervention_permission": clamp01(probe.active_goal_intervention_permission),
                "fragmentation": fragmentation,
                "idle_ambiguity": idle_ambiguity,
            },
        )

    def _estimate_coherence(
        self,
        *,
        intent: ActivityIntent,
        relation: GoalRelation,
        active_goal_strength: float,
        fragmentation: float,
        idle_ambiguity: float,
        combined_text: str,
    ) -> float:
        base_by_intent = {
            "technical_focus": 0.72,
            "research": 0.70,
            "system_waiting": 0.62,
            "supportive_background": 0.60,
            "social_coordination": 0.58,
            "recovery": 0.58,
            "play_or_recovery": 0.52,
            "possible_avoidance": 0.40,
            "fragmented_switching": 0.34,
            "unknown": 0.48,
        }
        coherence = base_by_intent.get(intent.label, 0.48)

        if relation.label == GoalRelationLabel.ALIGNED.value:
            coherence += 0.10 * relation.confidence
        elif relation.label == GoalRelationLabel.ADJACENT.value:
            coherence += 0.04 * relation.confidence
        elif relation.label == GoalRelationLabel.CONFLICTING.value:
            coherence -= 0.18 * relation.confidence

        if active_goal_strength >= 0.45 and intent.label in {"technical_focus", "research", "system_waiting"}:
            coherence += 0.06

        coherence -= fragmentation * 0.45
        coherence -= idle_ambiguity * 0.20
        if has_any(normalize(combined_text), ("co the", "hinh nhu", "maybe", "khong chac", "chua ro", "unclear")):
            coherence -= 0.04
        return clamp01(coherence)

    def _estimate_conflict(
        self,
        *,
        intent: ActivityIntent,
        relation: GoalRelation,
        active_goal_strength: float,
        active_goal_intervention_permission: float,
        fragmentation: float,
        idle_ambiguity: float,
    ) -> float:
        conflict = 0.08
        if relation.label == GoalRelationLabel.CONFLICTING.value:
            conflict += 0.42 * relation.confidence
        elif relation.label == GoalRelationLabel.UNKNOWN.value:
            conflict += 0.08
        elif relation.label == GoalRelationLabel.NEUTRAL.value:
            conflict += 0.04
        elif relation.label in {GoalRelationLabel.ALIGNED.value, GoalRelationLabel.ADJACENT.value}:
            conflict -= 0.04

        if intent.label == ActivityIntentLabel.POSSIBLE_AVOIDANCE.value:
            conflict += 0.18 * intent.confidence
        elif intent.label == ActivityIntentLabel.FRAGMENTED_SWITCHING.value:
            conflict += 0.14
        elif intent.label in {"research", "technical_focus", "supportive_background", "system_waiting"}:
            conflict -= 0.08
        elif intent.label == ActivityIntentLabel.RECOVERY.value:
            conflict -= 0.05

        if relation.label == GoalRelationLabel.CONFLICTING.value:
            conflict += clamp01(active_goal_strength) * 0.16
            conflict += clamp01(active_goal_intervention_permission) * 0.12
        else:
            conflict += clamp01(active_goal_strength) * 0.02

        conflict += fragmentation * 0.36
        conflict += idle_ambiguity * 0.08
        if intent.label == ActivityIntentLabel.PLAY_OR_RECOVERY.value and active_goal_strength < 0.50:
            conflict -= 0.08
        return clamp01(conflict)

    def _estimate_intervention_pressure(
        self,
        *,
        intent: ActivityIntent,
        relation: GoalRelation,
        active_goal_strength: float,
        active_goal_intervention_permission: float,
        conflict: float,
        fragmentation: float,
        idle_ambiguity: float,
        idle_label: str,
    ) -> float:
        pressure = 0.04
        if relation.label == GoalRelationLabel.CONFLICTING.value:
            pressure += conflict * 0.62
            pressure += clamp01(active_goal_strength) * 0.12
            pressure += clamp01(active_goal_intervention_permission) * 0.22
        elif relation.label == GoalRelationLabel.UNKNOWN.value:
            pressure += 0.05
        elif relation.label == GoalRelationLabel.NEUTRAL.value:
            pressure += 0.02
        elif relation.label == GoalRelationLabel.ADJACENT.value:
            pressure -= 0.02
        elif relation.label == GoalRelationLabel.ALIGNED.value:
            pressure -= 0.04

        if intent.label == ActivityIntentLabel.POSSIBLE_AVOIDANCE.value:
            pressure += 0.14 * intent.confidence
        if intent.label == ActivityIntentLabel.FRAGMENTED_SWITCHING.value:
            pressure += 0.10
        pressure += fragmentation * 0.28

        if relation.label != GoalRelationLabel.CONFLICTING.value:
            pressure -= idle_ambiguity * 0.12
        elif idle_label in {"long_thinking_waiting_or_stall", "possible_reading_or_thinking"}:
            pressure -= 0.08

        if intent.label in {"research", "technical_focus", "supportive_background", "system_waiting"}:
            pressure -= 0.10
        elif intent.label in {"recovery", "play_or_recovery"} and relation.label != GoalRelationLabel.CONFLICTING.value:
            pressure -= 0.12
        return clamp01(pressure)

    def _estimate_confidence(
        self,
        *,
        probe: SemanticContextProbe,
        intent: ActivityIntent,
        relation: GoalRelation,
        idle_ambiguity: float,
        fragmentation: float,
    ) -> float:
        confidence = 0.34
        if probe.focus_text:
            confidence += 0.06
        if probe.window_text:
            confidence += 0.05
        if probe.current_text:
            confidence += 0.08
        if probe.browsing_text:
            confidence += 0.06
        if probe.memory_text:
            confidence += 0.04
        if probe.active_goal_summary:
            confidence += 0.08

        confidence += intent.confidence * 0.22
        confidence += relation.confidence * 0.14
        confidence += clamp01(probe.active_goal_strength) * 0.08
        confidence += clamp01(probe.active_goal_intervention_permission) * 0.06

        confidence -= idle_ambiguity * 0.18
        confidence -= min(0.08, fragmentation * 0.18)
        if intent.label == ActivityIntentLabel.UNKNOWN.value:
            confidence -= 0.08
        if relation.label == GoalRelationLabel.UNKNOWN.value:
            confidence -= 0.05
        return clamp(confidence, 0.12, 0.92)
