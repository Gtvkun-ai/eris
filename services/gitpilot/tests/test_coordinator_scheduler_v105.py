"""V105 scheduler regression tests."""
from __future__ import annotations

import asyncio
import pytest

from gitpilot.coordinator.scheduler import ActionScheduler, ResearchScheduler
from gitpilot.coordinator.state import ResearchJob, ResearchReport


@pytest.mark.anyio
async def test_action_dependency_forces_delegate_before_await_barrier():
    scheduler = ActionScheduler()
    events: list[str] = []

    async def readonly(action):
        events.append("start:" + action["type"])
        await asyncio.sleep(0)
        events.append("done:" + action["type"])

    async def barrier(action):
        events.append("barrier:" + action["type"])

    errors = []
    await scheduler.execute(
        [
            {"id":"delegate1","type":"delegate","jobs":[]},
            {"id":"await1","type":"await_subagents","depends_on":["delegate1"]},
        ],
        run_readonly=readonly,
        run_barrier=barrier,
        on_error=lambda action, exc: errors.append((action, exc)),
    )

    assert errors == []
    assert events.index("done:delegate") < events.index("barrier:await_subagents")


@pytest.mark.anyio
async def test_unbounded_logical_jobs_use_bounded_worker_tasks():
    release = asyncio.Event()
    active = 0
    peak = 0

    async def runner(job: ResearchJob, job_id: str) -> ResearchReport:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await release.wait()
        active -= 1
        return ResearchReport(job_id=job_id, label=job.label, summary="ok")

    scheduler = ResearchScheduler(parallelism=3, runner=runner)
    ids = [scheduler.submit(ResearchJob(goal=f"job {i}", label=str(i))) for i in range(50)]
    await asyncio.sleep(0.01)

    assert len(ids) == 50
    assert len(scheduler._workers) == 3, "logical jobs must not become one asyncio.Task each"
    assert peak == 3

    release.set()
    results = await scheduler.collect(wait=True)
    assert len(results) == 50
    await scheduler.close()
