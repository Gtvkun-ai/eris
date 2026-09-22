"""One-shot surgical edit of services/gitpilot/gitpilot/_api_app.py.

Applies the approved plan (P0-A + P0-hardening):
  * import PlanStep at top level (no inner `from .agentic import PlanResult`)
  * short-circuit returns an "answer, not a plan" step so classifyPlan()
    renders the greeting as a chat reply instead of a failure banner
  * the whole short-circuit is gated behind the `gatekeeper` feature flag
  * admission threshold raised to exact/prefix matches only (H6)
  * import/runtime failures are logged as WARNING with a traceback
"""
from __future__ import annotations

import io
import pathlib
import sys

PATH = pathlib.Path("services/gitpilot/gitpilot/_api_app.py")
src = PATH.read_text(encoding="utf-8")
lines = src.splitlines(keepends=True)

ANCHOR_START = "        # ── Gatekeeper pre-classification"
ANCHOR_END_OLD = '            logger.debug("[gatekeeper] skipped: %s", _gate_err)'
ANCHOR_TASK = '    @_track_task(kind="plan", title_fn=lambda req: req.goal)'
ANCHOR_POST = '@app.post("/api/chat/plan")'
ANCHOR_IMPORT = "    PlanResult,\n"

CONSTANT = '''# ── Gatekeeper short-circuit admission threshold ────────────────────────────
# ``gatekeeper.classify_request`` scores on a fixed, documented scale:
#   1.00 — exact conversational match ("xin chào", "cam on")
#   0.95 — conversational prefix ("xin chào, bạn khoẻ không?")
#   0.80 — weak heuristic: "very short, no repo signal"
# Only the two strong tiers may *drop* a request before the planner runs.  The
# 0.80 tier is a routing hint, not a decision: it also fires for terse-but-real
# requests ("do thing", "hello world python"), and short-circuiting those
# swallowed the planner wholesale — caught by tests/test_chat_plan_friendly_errors.py.
_GATEKEEPER_SHORT_CIRCUIT_MIN_CONFIDENCE = 0.95


'''

NEW_BLOCK = '''        # ── Gatekeeper pre-classification ────────────────────────────────
        # Evaluate the request BEFORE any repo I/O or LLM call.
        # Conversational messages (greetings, social, meta) are served
        # instantly without reading the repo tree or spawning agents.
        # Behind the `gatekeeper` flag (default on) so a hot endpoint can be
        # rolled back by config rather than by editing this file.
        # Best-effort: any failure is logged loudly and falls through to the
        # existing planner pipeline.
        try:
            from . import flags as _flags

            if _flags.is_on("gatekeeper", default=True):
                from .gatekeeper import classify_request as _gate_classify
                from .pipelines.direct_reply import direct_reply as _direct_reply

                _gate = await _gate_classify(req.goal)
                logger.info(
                    "[gatekeeper] route=%s confidence=%.2f fast=%s rationale=%r",
                    _gate.route, _gate.confidence, _gate.fast_path, _gate.rationale,
                )

                if (
                    _gate.route == "conversational"
                    and _gate.confidence >= _GATEKEEPER_SHORT_CIRCUIT_MIN_CONFIDENCE
                ):
                    # Zero repo reads, zero agents — answer directly.
                    logger.info("[gatekeeper] SHORT-CIRCUIT: conversational → direct_reply")
                    reply = await _direct_reply(
                        req.goal,
                        owner=req.repo_owner,
                        repo=req.repo_name,
                    )
                    # "Answer, not a plan" — the same convention the Lite
                    # planner uses for a Q&A fallback: one step, no files, so
                    # the frontend's classifyPlan() renders the summary as a
                    # chat reply instead of an approvable plan.
                    return PlanResult(
                        goal=req.goal,
                        summary=reply["summary"],
                        steps=[
                            PlanStep(
                                step_number=1,
                                title="Answer",
                                description=reply["summary"],
                                files=[],
                            )
                        ],
                    )

        except Exception as _gate_err:
            logger.warning("[gatekeeper] skipped: %s", _gate_err, exc_info=True)
'''


def replace_block() -> None:
    global lines
    start = next(i for i, l in enumerate(lines) if l.rstrip("\n") == ANCHOR_START)
    end = next(i for i, l in enumerate(lines) if l.rstrip("\n") == ANCHOR_END_OLD)
    assert end > start, (start, end)
    lines[start : end + 1] = NEW_BLOCK.splitlines(keepends=True)


def insert_constant() -> None:
    global lines
    task = next(i for i, l in enumerate(lines) if l.rstrip("\n") == ANCHOR_TASK)
    post = task - 1
    while lines[post].rstrip("\n") != ANCHOR_POST:
        post -= 1
        assert post > task - 10, "could not find the @app.post line"
    lines[post:post] = CONSTANT.splitlines(keepends=True)


def add_planstep_import() -> None:
    global lines
    idx = [i for i, l in enumerate(lines) if l == ANCHOR_IMPORT]
    assert len(idx) == 1, f"expected exactly one top-level PlanResult import, got {idx}"
    lines[idx[0] + 1 : idx[0] + 1] = ["    PlanStep,\n"]


replace_block()
insert_constant()
add_planstep_import()
PATH.write_text("".join(lines), encoding="utf-8")
print(f"patched {PATH}")
