"""Schedulers for coordinator actions and background research.

V104 used one ``asyncio.Task`` per logical subagent and batched all read-only
operations together. V105 separates *logical work* from *physical workers* and
adds explicit action dependencies/barriers.
"""
from __future__ import annotations

import asyncio
import itertools
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from .state import ResearchJob, ResearchReport


@dataclass
class _QueuedResearch:
    priority: float
    order: int
    job_id: str
    job: ResearchJob
    future: asyncio.Future[ResearchReport]


class ResearchScheduler:
    """Unbounded logical queue backed by a bounded worker pool.

    There is one Future per logical job, but only ``parallelism`` worker Tasks.
    This prevents thousands of delegated branches from materialising as thousands
    of sleeping asyncio Tasks while keeping the cognitive job count unrestricted.
    """

    def __init__(
        self,
        *,
        parallelism: int,
        runner: Callable[[ResearchJob, str], Awaitable[ResearchReport]],
    ) -> None:
        self.parallelism = max(1, int(parallelism))
        self.runner = runner
        self._queue: asyncio.PriorityQueue[tuple[float, int, _QueuedResearch]] = asyncio.PriorityQueue()
        self._counter = itertools.count()
        self._workers: list[asyncio.Task[None]] = []
        self._futures: dict[str, asyncio.Future[ResearchReport]] = {}
        self._labels: dict[str, str] = {}
        self._closed = False

    def _ensure_workers(self) -> None:
        if self._workers or self._closed:
            return
        for index in range(self.parallelism):
            self._workers.append(asyncio.create_task(self._worker(index)))

    def submit(self, job: ResearchJob) -> str:
        if self._closed:
            raise RuntimeError("research scheduler is closed")
        self._ensure_workers()
        job_id = uuid.uuid4().hex[:8]
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ResearchReport] = loop.create_future()
        self._futures[job_id] = future
        self._labels[job_id] = job.label
        order = next(self._counter)
        item = _QueuedResearch(job.priority, order, job_id, job, future)
        # PriorityQueue lấy số nhỏ trước; priority cao phải chạy trước.
        self._queue.put_nowait((-float(job.priority), order, item))
        return job_id

    async def _worker(self, _index: int) -> None:
        while True:
            try:
                _prio, _order, item = await self._queue.get()
            except asyncio.CancelledError:
                return
            try:
                if item.future.cancelled():
                    continue
                report = await self.runner(item.job, item.job_id)
                if not item.future.done():
                    item.future.set_result(report)
            except asyncio.CancelledError:
                if not item.future.done():
                    item.future.cancel()
                raise
            except Exception as exc:
                if not item.future.done():
                    item.future.set_exception(exc)
            finally:
                self._queue.task_done()

    def ids(self) -> list[str]:
        return list(self._futures)

    def label(self, job_id: str) -> str:
        return self._labels.get(job_id, "research")

    def pending_ids(self) -> list[str]:
        return [job_id for job_id, future in self._futures.items() if not future.done()]

    async def collect(
        self,
        *,
        wait: bool,
        job_ids: Optional[list[str]] = None,
    ) -> list[tuple[str, ResearchReport | BaseException]]:
        selected = [
            job_id for job_id in (job_ids or list(self._futures))
            if job_id in self._futures
        ]
        if wait and selected:
            await asyncio.gather(
                *[self._futures[job_id] for job_id in selected],
                return_exceptions=True,
            )

        out: list[tuple[str, ResearchReport | BaseException]] = []
        for job_id in list(selected):
            future = self._futures.get(job_id)
            if future is None or not future.done():
                continue
            self._futures.pop(job_id, None)
            self._labels.pop(job_id, None)
            if future.cancelled():
                out.append((job_id, asyncio.CancelledError()))
                continue
            try:
                out.append((job_id, future.result()))
            except BaseException as exc:  # result may preserve provider exception
                out.append((job_id, exc))
        return out

    async def close(self, *, cancel_pending: bool = True) -> None:
        self._closed = True
        if cancel_pending:
            for future in self._futures.values():
                if not future.done():
                    future.cancel()
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._futures.clear()
        self._labels.clear()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break


class ActionScheduler:
    """Dependency-aware scheduler for Main actions.

    Independent read/search/status/diff/delegate actions may run in parallel.
    Mutations and ``await_subagents`` are barriers. Explicit ``depends_on`` ids
    form a DAG; invalid/cyclic dependencies are surfaced as action errors by the
    caller instead of being guessed around.
    """

    PARALLEL_SAFE = {"search", "read", "git_status", "git_diff", "delegate"}
    BARRIERS = {"await_subagents", "write", "delete", "run"}

    async def execute(
        self,
        actions: list[dict[str, Any]],
        *,
        run_readonly: Callable[[dict[str, Any]], Awaitable[None]],
        run_barrier: Callable[[dict[str, Any]], Awaitable[None]],
        on_error: Callable[[dict[str, Any], BaseException], None],
    ) -> None:
        nodes: list[tuple[str, dict[str, Any]]] = []
        used_ids: set[str] = set()
        for index, action in enumerate(actions):
            if not isinstance(action, dict):
                continue
            action_id = str(action.get("id") or f"auto_{index}")
            if action_id in used_ids:
                action_id = f"{action_id}_{index}"
            used_ids.add(action_id)
            copied = dict(action)
            copied["_action_id"] = action_id
            nodes.append((action_id, copied))

        completed: set[str] = set()
        remaining = dict(nodes)
        order = [node_id for node_id, _ in nodes]

        while remaining:
            ready: list[tuple[str, dict[str, Any]]] = []
            for node_id in order:
                action = remaining.get(node_id)
                if action is None:
                    continue
                deps = [str(x) for x in (action.get("depends_on") or [])]
                if all(dep in completed for dep in deps):
                    ready.append((node_id, action))

            if not ready:
                # Cycle hoặc dependency trỏ id không tồn tại.
                unresolved = RuntimeError(
                    "action dependency graph cannot progress: "
                    + ", ".join(remaining)
                )
                for _node_id, action in list(remaining.items()):
                    on_error(action, unresolved)
                return

            # Nếu action sớm nhất là barrier, chạy đúng một barrier để giữ semantics.
            first_id, first = ready[0]
            first_type = str(first.get("type") or "").lower()
            if first_type in self.BARRIERS or first_type not in self.PARALLEL_SAFE:
                try:
                    await run_barrier(first)
                except BaseException as exc:
                    on_error(first, exc)
                completed.add(first_id)
                remaining.pop(first_id, None)
                continue

            # Batch các parallel-safe ready nodes đứng trước barrier đầu tiên theo order.
            batch: list[tuple[str, dict[str, Any]]] = []
            ready_ids = {node_id for node_id, _ in ready}
            for node_id in order:
                if node_id not in ready_ids:
                    continue
                action = remaining[node_id]
                typ = str(action.get("type") or "").lower()
                if typ not in self.PARALLEL_SAFE:
                    if batch:
                        break
                    continue
                batch.append((node_id, action))

            results = await asyncio.gather(
                *[run_readonly(action) for _node_id, action in batch],
                return_exceptions=True,
            )
            for (node_id, action), result in zip(batch, results):
                if isinstance(result, BaseException):
                    on_error(action, result)
                completed.add(node_id)
                remaining.pop(node_id, None)
