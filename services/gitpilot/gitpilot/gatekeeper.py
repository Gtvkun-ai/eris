"""GitPilot Gatekeeper — Pre-classification before any repo I/O.

Evaluates a user message deterministically (rule-based) or via a fast
LLM call and decides which execution path to take:

    conversational  → direct_reply (0 agents, 0 repo reads, < 2s)
    info            → info_pipeline (targeted read, 1-2 LLM calls, < 8s)
    code_task       → task_pipeline (planned subagents, < 20s)
    ambiguous       → clarification question (0 agents)

The rule-based fast path covers ~80% of traffic with zero latency and
zero token cost.  For edge cases the gatekeeper fires a single cheap
LLM call (a short classification prompt) to disambiguate.

This module has NO I/O imports from gitpilot's github_api or agentic
modules — it is intentionally dependency-free so the API layer can run
it synchronously before acquiring any repo context.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal, Optional

# ---------------------------------------------------------------------------
# Route type
# ---------------------------------------------------------------------------

Route = Literal["conversational", "info", "code_task", "ambiguous"]


@dataclass
class GatekeeperDecision:
    """Result of gatekeeper classification."""

    route: Route
    confidence: float          # 0.0–1.0
    rationale: str
    needs_repo: bool
    # Optional hints for downstream pipelines (from cache keyword hinting)
    suggested_keywords: list[str] = field(default_factory=list)
    # True when the rule-based path fired (no LLM was called)
    fast_path: bool = True


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Strip accents, lowercase, collapse whitespace."""
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped.lower().strip())


# ---------------------------------------------------------------------------
# Rule-based fast path
# ---------------------------------------------------------------------------

# ── Conversational triggers ──────────────────────────────────────────────────
# Short greetings, social phrases, meta questions about the assistant.
_CONVERSATIONAL_EXACT: frozenset[str] = frozenset({
    # Vietnamese
    "xin chao", "chao", "chao ban", "chao em", "chao eris", "xin chao eris",
    "hey", "hi", "hello", "hello eris", "hi eris",
    "alo", "e oi", "em oi", "eris oi",
    "cam on", "cam on ban", "cam on em", "xin cam on",
    "ok", "okay", "duoc roi", "hieu roi", "biet roi",
    "tam biet", "bye", "goodbye",
    # Short social
    "ban co khoe khong", "em co khoe khong", "hom nay the nao",
    "ban la gi", "em la gi", "ban ten gi", "em ten gi",
    "ban lam duoc gi", "em lam duoc gi",
    "gioi thieu ve ban di", "gioi thieu ve em di",
})

# Prefix-based: if normalized message STARTS WITH these → conversational
_CONVERSATIONAL_PREFIXES: tuple[str, ...] = (
    "xin chao",
    "chao ban",
    "chao em",
    "chao eris",
    "cam on",
    "thank you",
    "thanks",
    "biet roi",
    "ok ban",
    "ok em",
    "got it",
    "understood",
    "noted",
)

# ── Info / question triggers ────────────────────────────────────────────────
_INFO_KEYWORDS: tuple[str, ...] = (
    # Vietnamese
    "tai sao", "vi sao", "lam sao", "the nao", "nhu the nao",
    "giai thich", "mo ta", "tom tat", "tong quan", "doc hieu",
    "no lam gi", "no hoat dong nhu the nao", "no dung de",
    "phan tich", "so sanh", "khac nhau", "giong nhau",
    "ban co biet", "em co biet", "co the cho toi biet",
    "cho toi biet", "cho em biet",
    # English
    "what is", "what are", "what does", "what do",
    "how does", "how do", "how is", "how are",
    "why is", "why does", "why do", "why are",
    "explain", "describe", "summarize", "overview",
    "tell me about", "show me how", "can you explain",
    "what's", "whats", "hows", "whys",
    "difference between", "compare", "similar to",
)

# ── Code task triggers ──────────────────────────────────────────────────────
_CODE_TASK_KEYWORDS: tuple[str, ...] = (
    # Modification
    "fix", "sua", "sua loi", "sua bug", "repair",
    "add", "them", "tao", "create", "generate", "build",
    "delete", "xoa", "remove", "bor", "clean up",
    "change", "thay doi", "update", "cap nhat", "modify", "edit",
    "refactor", "toi uu", "optimize", "rewrite", "viet lai",
    "rename", "move", "migrate",
    # Execution
    "run", "chay", "execute", "launch", "test",
    # Debug
    "debug", "tim loi", "trace", "breakpoint", "reproduce",
    # Implementation
    "implement", "code", "viet code", "make it", "lam cho",
    "integrate", "tich hop", "connect",
)

# Code task strong indicators: file extensions, path separators, code symbols
_CODE_ARTIFACT_RE = re.compile(
    r"(?:"
    r"[\w/\\]+\.(?:py|ts|tsx|js|jsx|go|rs|java|kt|cs|gd|cpp|c|h|md|json|yaml|toml)"
    r"|def\s+\w+|class\s+\w+|function\s+\w+"
    r"|import\s+\w+|from\s+\w+"
    r"|#\w+|@\w+"  # hashtag or decorator
    r")",
    re.IGNORECASE,
)


def _word_count(text: str) -> int:
    return len(text.split())


def _rule_based_classify(goal: str) -> Optional[GatekeeperDecision]:
    """Try to classify *goal* with zero LLM calls.

    Returns a :class:`GatekeeperDecision` when confident, ``None`` when
    the message is ambiguous and an LLM call would add value.
    """
    norm = _normalize(goal)
    wc = _word_count(norm)

    # ── Empty / trivial ────────────────────────────────────────────────────
    if not norm or wc == 0:
        return GatekeeperDecision(
            route="conversational",
            confidence=1.0,
            rationale="empty message",
            needs_repo=False,
            fast_path=True,
        )

    # ── Exact conversational match ─────────────────────────────────────────
    clean = norm.strip("?!., ")
    if clean in _CONVERSATIONAL_EXACT:
        return GatekeeperDecision(
            route="conversational",
            confidence=1.0,
            rationale=f"exact conversational match: '{clean}'",
            needs_repo=False,
            fast_path=True,
        )

    # ── Prefix conversational match (short messages only) ─────────────────
    if wc <= 8:
        for prefix in _CONVERSATIONAL_PREFIXES:
            if norm.startswith(prefix):
                return GatekeeperDecision(
                    route="conversational",
                    confidence=0.95,
                    rationale=f"conversational prefix: '{prefix}'",
                    needs_repo=False,
                    fast_path=True,
                )

    # ── Very short with no code artifact → likely conversational ──────────
    if wc <= 4 and not _CODE_ARTIFACT_RE.search(goal):
        has_info = any(kw in norm for kw in _INFO_KEYWORDS)
        has_code = any(kw in norm for kw in _CODE_TASK_KEYWORDS)
        if not has_info and not has_code:
            return GatekeeperDecision(
                route="conversational",
                confidence=0.80,
                rationale=f"very short ({wc} words), no repo signal",
                needs_repo=False,
                fast_path=True,
            )

    # ── Strong code-task signal ────────────────────────────────────────────
    has_artifact = bool(_CODE_ARTIFACT_RE.search(goal))
    code_kw_count = sum(1 for kw in _CODE_TASK_KEYWORDS if kw in norm)
    info_kw_count = sum(1 for kw in _INFO_KEYWORDS if kw in norm)

    if has_artifact and code_kw_count >= 1:
        keywords = [w for w in re.split(r"\s+", norm) if len(w) > 3][:8]
        return GatekeeperDecision(
            route="code_task",
            confidence=0.95,
            rationale=f"code artifact + {code_kw_count} action keyword(s)",
            needs_repo=True,
            suggested_keywords=keywords,
            fast_path=True,
        )

    if code_kw_count >= 2 and info_kw_count == 0:
        keywords = [w for w in re.split(r"\s+", norm) if len(w) > 3][:8]
        return GatekeeperDecision(
            route="code_task",
            confidence=0.85,
            rationale=f"{code_kw_count} action keywords, no info markers",
            needs_repo=True,
            suggested_keywords=keywords,
            fast_path=True,
        )

    # ── Info/question signal ───────────────────────────────────────────────
    if info_kw_count >= 1 and code_kw_count == 0:
        keywords = [w for w in re.split(r"\s+", norm) if len(w) > 3][:8]
        return GatekeeperDecision(
            route="info",
            confidence=0.85,
            rationale=f"{info_kw_count} info keyword(s)",
            needs_repo=True,
            suggested_keywords=keywords,
            fast_path=True,
        )

    if info_kw_count >= 1 and code_kw_count >= 1:
        # Both info and code signals → likely info-first ("explain then fix")
        keywords = [w for w in re.split(r"\s+", norm) if len(w) > 3][:8]
        return GatekeeperDecision(
            route="info",
            confidence=0.70,
            rationale="mixed info+code signals — routing as info",
            needs_repo=True,
            suggested_keywords=keywords,
            fast_path=True,
        )

    # ── Long message with code keyword → code task ─────────────────────────
    if wc > 10 and code_kw_count >= 1:
        keywords = [w for w in re.split(r"\s+", norm) if len(w) > 3][:8]
        return GatekeeperDecision(
            route="code_task",
            confidence=0.75,
            rationale=f"long message ({wc}w) with action keyword",
            needs_repo=True,
            suggested_keywords=keywords,
            fast_path=True,
        )

    # ── Cannot classify deterministically ─────────────────────────────────
    return None


# ---------------------------------------------------------------------------
# LLM fallback for ambiguous cases
# ---------------------------------------------------------------------------

async def _llm_classify(goal: str, llm_call) -> GatekeeperDecision:
    """Call a lightweight LLM to classify ambiguous messages.

    ``llm_call`` is an async callable ``(system, user) -> str`` provided by
    the caller so this module stays dependency-free.

    The prompt is deliberately tiny (< 100 tokens) and expects a one-word
    response to minimise latency and cost.
    """
    system = (
        "You are a request classifier. Classify the user message into exactly "
        "one of: conversational, info, code_task.\n"
        "- conversational: greeting, social, meta question about you\n"
        "- info: question about code, architecture, how something works\n"
        "- code_task: request to write, fix, modify, add, delete, run code\n"
        "Reply with ONLY the category word, nothing else."
    )
    try:
        raw = await llm_call(system, goal)
        category = raw.strip().lower().split()[0]
        if category not in ("conversational", "info", "code_task"):
            category = "code_task"  # safest fallback
        needs_repo = category != "conversational"
        norm = _normalize(goal)
        keywords = [w for w in re.split(r"\s+", norm) if len(w) > 3][:8]
        return GatekeeperDecision(
            route=category,  # type: ignore[arg-type]
            confidence=0.80,
            rationale=f"LLM classified as '{category}'",
            needs_repo=needs_repo,
            suggested_keywords=keywords if needs_repo else [],
            fast_path=False,
        )
    except Exception as exc:
        # LLM failed → safe fallback to code_task (never drop a real request)
        norm = _normalize(goal)
        keywords = [w for w in re.split(r"\s+", norm) if len(w) > 3][:8]
        return GatekeeperDecision(
            route="code_task",
            confidence=0.50,
            rationale=f"LLM fallback failed ({exc}), defaulting to code_task",
            needs_repo=True,
            suggested_keywords=keywords,
            fast_path=False,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def classify_request(
    goal: str,
    *,
    llm_call=None,
) -> GatekeeperDecision:
    """Classify *goal* and return a routing decision.

    Args:
        goal:     The raw user message from the chat input.
        llm_call: Optional async callable ``(system_prompt, user_msg) -> str``
                  used as fallback when rule-based classification is uncertain.
                  When ``None``, ambiguous messages fall back to ``code_task``
                  (safe: never drops a real coding request).

    Returns:
        A :class:`GatekeeperDecision` — callers should branch on ``.route``.
    """
    decision = _rule_based_classify(goal)
    if decision is not None:
        return decision

    # Ambiguous: try LLM if available, else default to code_task
    if llm_call is not None:
        return await _llm_classify(goal, llm_call)

    # No LLM → safe default
    norm = _normalize(goal)
    keywords = [w for w in re.split(r"\s+", norm) if len(w) > 3][:8]
    return GatekeeperDecision(
        route="code_task",
        confidence=0.50,
        rationale="ambiguous, no LLM available — defaulting to code_task",
        needs_repo=True,
        suggested_keywords=keywords,
        fast_path=True,
    )


__all__ = [
    "Route",
    "GatekeeperDecision",
    "classify_request",
]
