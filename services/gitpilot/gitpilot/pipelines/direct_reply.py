"""Direct Reply pipeline — conversational fast path.

Handles conversational requests (greetings, social, meta-questions)
without touching the repo at all.  A single LLM call with a short
system prompt generates a natural, in-context response.

Target latency: < 2 seconds (limited by LLM TTFT only).
Repo reads:     0
Agents spawned: 0
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Deterministic replies for the most common conversational inputs.
# Avoids an LLM call entirely for pure greetings.
_INSTANT_REPLIES: dict[str, str] = {
    # Vietnamese greetings
    "xin chao": "Chào bạn! Tôi sẵn sàng giúp bạn với code, debugging, hoặc bất kỳ câu hỏi nào về repo. Bạn cần gì?",
    "chao": "Chào! Bạn cần gì?",
    "chao ban": "Chào bạn! Bạn cần gì?",
    "chao em": "Chào! Tôi có thể giúp gì cho bạn?",
    "chao eris": "Chào! Bạn cần gì?",
    "xin chao eris": "Chào bạn! Tôi sẵn sàng. Bạn cần gì?",
    "hey": "Hey! Cần gì không?",
    "hi": "Hi! Cần gì không?",
    "hello": "Hello! How can I help?",
    # Thanks
    "cam on": "Không có gì! Còn gì cần giúp không?",
    "cam on ban": "Không có gì! Còn gì cần giúp không?",
    "thank you": "You're welcome! Anything else?",
    "thanks": "You're welcome!",
    # Farewell
    "tam biet": "Hẹn gặp lại!",
    "bye": "Bye!",
    "goodbye": "Goodbye!",
}


import unicodedata, re

def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped.lower().strip("?!., "))


async def direct_reply(
    goal: str,
    *,
    owner: str = "",
    repo: str = "",
    session_messages: list | None = None,
    llm_call=None,
) -> dict:
    """Generate a direct conversational reply without any repo access.

    Returns a dict compatible with the existing PlanResult JSON schema
    (``summary`` text, empty ``steps``), so the API layer and frontend
    need no changes.

    Args:
        goal:             The user's message.
        owner/repo:       Repo context for personalisation (no API calls).
        session_messages: Last N chat messages for context (no repo reads).
        llm_call:         Async ``(system, user, messages) -> str`` callable.
                          When ``None``, falls back to _INSTANT_REPLIES.
    """
    norm = _normalize(goal)

    # ── Instant (no LLM) ──────────────────────────────────────────────────
    instant = _INSTANT_REPLIES.get(norm)
    if instant:
        logger.info("[direct_reply] instant reply for '%s'", norm)
        return _wrap_reply(instant, goal, latency_ms=0, llm_used=False)

    # ── LLM conversational reply ──────────────────────────────────────────
    if llm_call is None:
        # No LLM available — generic fallback
        text = f"Tôi hiểu. Bạn có thể nói thêm hoặc mô tả task cụ thể hơn không?"
        return _wrap_reply(text, goal, latency_ms=0, llm_used=False)

    repo_ctx = f" Repo: `{owner}/{repo}`." if owner and repo else ""
    system = (
        "You are GitPilot, an AI coding assistant.{repo_ctx} "
        "The user sent a conversational message (not a code task). "
        "Reply naturally and concisely in the SAME language as the user. "
        "If Vietnamese, reply in Vietnamese. Keep reply under 3 sentences. "
        "Do NOT read any files. Do NOT make plans. Just chat."
    ).format(repo_ctx=repo_ctx)

    import time
    t0 = time.perf_counter()
    try:
        text = await llm_call(system, goal, session_messages or [])
    except Exception as exc:
        logger.warning("[direct_reply] LLM call failed: %s", exc)
        text = "Tôi hiểu rồi. Bạn cần gì tiếp theo?"
    latency_ms = int((time.perf_counter() - t0) * 1000)

    logger.info("[direct_reply] LLM reply in %dms", latency_ms)
    return _wrap_reply(text, goal, latency_ms=latency_ms, llm_used=True)


def _wrap_reply(text: str, goal: str, *, latency_ms: int, llm_used: bool) -> dict:
    """Wrap reply text in a PlanResult-compatible dict."""
    return {
        "goal": goal,
        "summary": text,
        "steps": [],
        "metadata": {
            "pipeline": "direct_reply",
            "latency_ms": latency_ms,
            "llm_used": llm_used,
            "repo_reads": 0,
            "agents": 0,
        },
    }


__all__ = ["direct_reply"]
