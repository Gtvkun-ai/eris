# -*- coding: utf-8 -*-
"""Xác minh báo cáo Phase 7 trước khi đóng release Phase 8."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

_REQUIRED = {
    "greeting",
    "panel_delivery",
    "normal_chat",
    "repair_after_correction",
    "action_confirmation",
    "memory_provenance",
    "tts_same_language",
    "provider_recovery",
    "surface_sanitizer",
    "personality_banter",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Báo cáo phải là JSON object")
    coverage = payload.get("scenario_coverage", {})
    missing = set(coverage.get("missing", [])) if isinstance(coverage, dict) else set(_REQUIRED)
    results = coverage.get("results", {}) if isinstance(coverage, dict) else {}
    missing |= {name for name in _REQUIRED if name not in results}
    failed_findings = [
        str(item.get("name", "unknown"))
        for item in payload.get("findings", [])
        if isinstance(item, dict) and str(item.get("status", "")) == "fail"
    ]
    warnings = [
        str(item.get("name", "unknown"))
        for item in payload.get("findings", [])
        if isinstance(item, dict) and str(item.get("status", "")) == "warn"
    ]
    hardening = payload.get("hardening_verification", {})
    hardening_status = str(hardening.get("status", "")) if isinstance(hardening, dict) else ""
    turns = int(payload.get("public_turns", 0) or 0)
    events_path = Path(str(payload.get("events_path", "") or ""))
    if events_path and not events_path.is_absolute():
        events_path = (path.parent / events_path).resolve()
    events_ok = bool(str(events_path)) and events_path.is_file()
    ready = (
        str(payload.get("status", "")) == "pass"
        and 20 <= turns <= 30
        and not missing
        and not failed_findings
        and hardening_status != "fail"
        and events_ok
    )
    return {
        "ready_for_phase8": ready,
        "report": str(path.resolve()),
        "report_sha256": _sha256(path),
        "validation_id": str(payload.get("validation_id", "")),
        "status": str(payload.get("status", "")),
        "public_turns": turns,
        "missing_scenarios": sorted(missing),
        "failed_findings": failed_findings,
        "warnings": warnings,
        "hardening_status": hardening_status,
        "events_path": str(events_path),
        "events_exists": events_ok,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Xác minh report Phase 7 của Eris")
    parser.add_argument("report")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    result = verify(Path(args.report))
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready_for_phase8"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
