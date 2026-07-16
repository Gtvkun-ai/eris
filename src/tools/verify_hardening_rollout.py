# -*- coding: utf-8 -*-
"""Replay observability và xác minh canary hardening.

Ví dụ:
  python tools/verify_hardening_rollout.py \
      --input logs/eris_observability.jsonl \
      --output logs/hardening_verification.json

Exit code:
- 0: pass hoặc warn;
- 2: có finding fail.
"""
from __future__ import annotations

import sys
import argparse
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from runtime.hardening_baseline import HardeningBaseline
from runtime.hardening_verifier import HardeningVerifier
from runtime.observability import ErisObservability
from runtime.rollout_control import RolloutController


def _load_provider_health(path: str) -> dict:
    if not path:
        return {}
    source = Path(path)
    if not source.exists():
        return {}
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(payload, dict) and isinstance(payload.get("provider_health"), dict):
        return dict(payload["provider_health"])
    return dict(payload) if isinstance(payload, dict) else {}




def _provider_health_from_store(store: ErisObservability) -> dict:
    fields = store.latest_fields("provider_health_snapshot")
    providers = fields.get("providers") if isinstance(fields, dict) else None
    return dict(providers) if isinstance(providers, dict) else {}

def main() -> int:
    parser = argparse.ArgumentParser(description="Xác minh rollout hardening Eris từ observability JSONL")
    parser.add_argument("--input", default="logs/eris_observability.jsonl")
    parser.add_argument("--output", default="logs/hardening_verification.json")
    parser.add_argument("--provider-health", default="", help="JSON provider health tùy chọn")
    parser.add_argument("--baseline", default="", help="Baseline JSON đã chụp từ stable")
    parser.add_argument("--apply-rollback", action="store_true", help="Áp kill-switch khi health gate phát hiện fail")
    args = parser.parse_args()

    store = ErisObservability.replay_jsonl(args.input)
    controller = RolloutController(observability=store)
    provider_health = _load_provider_health(args.provider_health) or _provider_health_from_store(store)
    baseline = HardeningBaseline.load(args.baseline) if args.baseline else None
    report = HardeningVerifier(baseline=baseline).verify(
        store.metric_snapshot(),
        provider_health=provider_health,
        rollout_status=controller.status(),
    )

    if args.apply_rollback:
        from runtime.hardening_rollout import HardeningHealthGate
        HardeningHealthGate(controller, baseline=baseline).evaluate_observability(store, auto_kill=True)

    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": report.status,
        "public_turns": report.public_turns,
        "output": str(target),
        "failed": [item.name for item in report.findings if item.status == "fail"],
        "warnings": [item.name for item in report.findings if item.status == "warn"],
    }, ensure_ascii=False, indent=2))
    return 2 if report.status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
