# -*- coding: utf-8 -*-
"""Static code-level compliance check for the ERIS architecture PDF.

This check proves source integration and tests.  It intentionally does not
claim production P50/P95 or 429 reduction without real canary logs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.audit_remote_inference_paths import audit
from tools.audit_semantic_authority_paths import audit as audit_semantic_authority


REQUIRED_FILES = {
    "runtime/inference_broker.py": "central broker",
    "runtime/broker_state_store.py": "durable cooldown/header/idempotency state",
    "runtime/work_keys.py": "stable cross-process work identity",
    "runtime/pdf_rollout.py": "shadow/canary/kill-switch rollout",
    "runtime/semantic_frame.py": "typed semantic authority invariants",
    "runtime/cognition/turn_anchor.py": "typed semantic-frame observer projection",
    "runtime/degraded_chat_fastpath.py": "degraded-only fast path",
    "runtime/topic_budget.py": "per-topic tutor budget",
    "tools/report_pdf_acceptance.py": "full acceptance report",
    "tools/evaluate_semantic_paraphrases.py": "95% discourse evaluation",
    "tools/audit_remote_inference_paths.py": "broker bypass audit",
    "tools/audit_semantic_authority_paths.py": "semantic authority cutover audit",
    "tests/fixtures/semantic_paraphrases_vi.json": "Vietnamese paraphrase suite",
    "tests/test_pdf_refactor_v6.py": "adaptive degradation and targeted preemption regression suite",
}


def check(root: Path) -> dict[str, Any]:
    files = {
        path: {"purpose": purpose, "exists": (root / path).exists()}
        for path, purpose in REQUIRED_FILES.items()
    }
    remote_audit = audit(root)
    semantic_audit = audit_semantic_authority(root)
    annotations = 0
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        annotations += path.read_text(encoding="utf-8", errors="ignore").count("PDF annotation")
    broker_source = (root / "runtime/inference_broker.py").read_text(
        encoding="utf-8", errors="replace"
    ) if (root / "runtime/inference_broker.py").exists() else ""
    transport_source = (root / "llm/client.py").read_text(
        encoding="utf-8", errors="replace"
    ) if (root / "llm/client.py").exists() else ""
    v6_invariants = {
        "required_lane_adaptive_degradation": "_required_degrade_plan_locked" in broker_source,
        "targeted_inflight_optional_preemption": "_preempt_optional_inflight_locked" in broker_source,
        "model_family_concurrency_domain": "def _model_family" in broker_source,
        "transport_payload_budget_rewrite": "input_degrade_supported" in transport_source
        and "maxOutputTokens" in transport_source,
    }
    removed_paths = (
        "runtime/semantic_shadow.py",
        "runtime/social_act.py",
        "runtime/social_intent_head.py",
        "runtime/cognition/engine.py",
        "runtime/cognition/specialists/discourse.py",
        "runtime/cognition/specialists/semantic.py",
    )
    cleanup_invariants = {
        "legacy_semantic_modules_removed": all(not (root / path).exists() for path in removed_paths),
        "removed_model_compatibility_absent": not any(
            token in path.read_text(encoding="utf-8", errors="ignore").lower()
            for path in root.rglob("*.py") if "__pycache__" not in path.parts
            for token in ("gpt" + "-oss", "gpt" + "_oss")
        ),
    }
    passed = (
        all(item["exists"] for item in files.values())
        and all(v6_invariants.values())
        and all(cleanup_invariants.values())
        and remote_audit["passed"]
        and semantic_audit["passed"]
        and annotations > 0
    )
    return {
        "schema": "eris.pdf_refactor_compliance.v4",
        "root": str(root),
        "passed": passed,
        "required_files": files,
        "pdf_annotation_count": annotations,
        "v6_admission_invariants": v6_invariants,
        "v7_cleanup_invariants": cleanup_invariants,
        "remote_inference_audit": remote_audit,
        "semantic_authority_audit": semantic_audit,
        "production_metrics_verified": False,
        "production_metrics_note": "P50/P95, TTFT và mức giảm 429 cần log baseline/canary thật.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Kiểm tra tích hợp code-level theo PDF")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    report = check(Path(args.root).resolve())
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n", encoding="utf-8")
        print(target)
    else:
        print(rendered)
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
