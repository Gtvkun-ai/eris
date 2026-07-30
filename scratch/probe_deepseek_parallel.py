from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.environ["ERIS_PROJECT_ROOT"] = REPO_ROOT

from eris_secrets import apply_secrets_to_environ, load_env_file
from llm.process_manager import RemoteModelProcessManager


ROLES = ("companion", "observer", "critic", "inner", "style", "surface")


def _content_size(payload: Any) -> int:
    try:
        return len(str(payload["choices"][0]["message"].get("content", "") or ""))
    except (KeyError, IndexError, TypeError):
        return 0


def main() -> None:
    load_env_file(force=True)
    apply_secrets_to_environ()
    logger = logging.getLogger("deepseek-parallel-probe")
    logger.addHandler(logging.NullHandler())
    logger.setLevel(logging.CRITICAL)
    manager = RemoteModelProcessManager(logger=logger, project_root=REPO_ROOT)
    workers = {role: manager.build_deepseek_worker_client(role, required=True) for role in ROLES}
    start_gate = threading.Barrier(len(ROLES) + 1)
    launched_at = time.perf_counter()

    def call(role: str) -> dict[str, Any]:
        start_gate.wait(timeout=15.0)
        started = time.perf_counter()
        try:
            payload = workers[role].create_chat_completion(
                messages=[
                    {"role": "system", "content": "Return one compact JSON object only."},
                    {"role": "user", "content": f'{{"probe":"parallel","role":"{role}","ok":true}}'},
                ],
                temperature=0.0,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                max_tokens=80,
                response_format={"type": "json_object"},
                timeout=60.0,
            )
            return {
                "role": role,
                "started_ms": round((started - launched_at) * 1000.0, 1),
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
                "content_chars": _content_size(payload),
                "ok": True,
            }
        except Exception as exc:
            return {
                "role": role,
                "started_ms": round((started - launched_at) * 1000.0, 1),
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
                "error": f"{type(exc).__name__}:{exc}",
                "ok": False,
            }

    with ThreadPoolExecutor(max_workers=len(ROLES), thread_name_prefix="ds-parallel") as pool:
        futures = [pool.submit(call, role) for role in ROLES]
        start_gate.wait(timeout=15.0)
        results = [future.result() for future in as_completed(futures)]

    wall_ms = round((time.perf_counter() - launched_at) * 1000.0, 1)
    print(json.dumps({"roles": sorted(results, key=lambda item: item["role"]), "wall_ms": wall_ms}, ensure_ascii=True))


if __name__ == "__main__":
    main()
