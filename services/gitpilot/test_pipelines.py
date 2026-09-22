"""Smoke test for the new hierarchical pipeline (no LLM, no network)."""
import asyncio, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "services/gitpilot")

from gitpilot.gatekeeper import classify_request
from gitpilot.pipelines.direct_reply import direct_reply
from gitpilot.pipelines.info_pipeline import info_pipeline
from gitpilot.pipelines.task_pipeline import task_pipeline

REPO = "eris"
OWNER = "gtvkun"

async def run_test(label, coro):
    t0 = time.perf_counter()
    result = await coro
    ms = int((time.perf_counter() - t0) * 1000)
    pipeline = result.get("metadata", {}).get("pipeline", "?") if isinstance(result, dict) else "PlanResult"
    summary = result.get("summary", "")[:120] if isinstance(result, dict) else str(result)[:120]
    print(f"\n{'='*60}")
    print(f"[{label}] {ms}ms  pipeline={pipeline}")
    print(f"Summary: {summary}...")
    return ms

async def main():
    print("=== PIPELINE SMOKE TEST (no LLM, no network) ===\n")

    # Test 1: Gatekeeper classification
    cases = [
        ("xin chao", "conversational"),
        ("fix the timeout in inference_broker.py", "code_task"),
        ("explain how dialog system works", "info"),
        ("sua loi trong file agentic.py", "code_task"),
        ("tai sao orchestrator bi loi", "info"),
    ]
    print("--- Gatekeeper ---")
    for msg, expected in cases:
        d = await classify_request(msg)
        status = "OK" if d.route == expected else f"MISS (got {d.route})"
        print(f"  {status:<10} conf={d.confidence:.2f}  {msg!r}")

    # Test 2: Direct reply (instant)
    print("\n--- Direct Reply ---")
    ms = await run_test("xin chao", direct_reply("xin chao", owner=OWNER, repo=REPO))
    print(f"  Target: < 100ms  ->  {'OK' if ms < 100 else 'SLOW'}")

    # Test 3: Info pipeline with cache (no LLM, no network)
    print("\n--- Info Pipeline (cache only, no LLM) ---")
    ms = await run_test(
        "explain orchestrator",
        info_pipeline(
            "explain how orchestrator handles inference timeout",
            owner=OWNER, repo=REPO,
            keywords=["orchestrator", "inference", "timeout"],
            fetch_file_fn=None,   # no network
            llm_call=None,        # no LLM
        )
    )
    print(f"  Target: < 500ms  ->  {'OK' if ms < 500 else 'SLOW'}")

    # Test 4: Task pipeline Phase 1+2 (no LLM, no network)
    print("\n--- Task Pipeline (cache scope + parallel subagents, no LLM) ---")
    ms = await run_test(
        "fix timeout",
        task_pipeline(
            "fix the timeout bug in inference_broker.py",
            owner=OWNER, repo=REPO,
            keywords=["inference", "broker", "timeout"],
            fetch_file_fn=None,   # no network
            llm_call=None,        # no LLM
            fallback_fn=None,
        )
    )
    print(f"  Target: < 1000ms  ->  {'OK' if ms < 1000 else 'SLOW'}")

    print("\n=== DONE ===")

asyncio.run(main())
