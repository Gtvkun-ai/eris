"""Trace the orchestrator's agentic loop step by step (no LLM, no network)."""
import asyncio, sys, io, logging
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "services/gitpilot")

logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s %(message)s")

from gitpilot.pipelines.task_pipeline import TaskOrchestrator, _load_cache_files

async def main():
    cache = _load_cache_files("eris")
    print(f"Cache loaded: {len(cache)} files\n")

    orch = TaskOrchestrator(
        "fix the timeout bug in inference_broker.py where requests hang indefinitely",
        owner="gtvkun",
        repo="eris",
        branch="main",
        llm_call=None,     # no LLM — uses heuristic path
        fetch_file_fn=None, # no network
        cache_data=cache,
    )

    result = await orch.run()
    print("\n--- RESULT ---")
    print(f"Pipeline : {result['metadata']['pipeline']}")
    print(f"Turns    : {result['metadata']['turns']}")
    print(f"Files read: {result['metadata']['files_read']}")
    print(f"AST read : {result['metadata']['ast_read']}")
    print(f"Tokens   : {result['metadata']['tokens_used']}")
    print(f"Latency  : {result['metadata']['latency_ms']}ms")
    print(f"\nSummary:\n{result['summary']}")

    print("\n--- CONTEXT NOTES ---")
    for note in orch.ctx.notes:
        print(f"  {note}")

asyncio.run(main())
