# -*- coding: utf-8 -*-
"""Validate the machine-readable release manifest against the source tree."""
from __future__ import annotations

import ast
import json
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "RELEASE_MANIFEST.json"
EXPECTED_RELEASE = "V35"
MIN_TESTS = 352
MIN_COVERAGE_FLOOR = 36.0
EXPECTED_SETTINGS_SCHEMA = 12
EXPECTED_ENGAGEMENT_SCHEMA = 7
EXPECTED_JOURNAL_SCHEMA = 1
EXPECTED_DIAGNOSTICS_SCHEMA = 6
EXPECTED_BOUNDARIES = 26

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.audit_exception_boundaries import scan, summarize  # noqa: E402


def _method_size(path: Path, class_name: str, method_name: str) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(
        node for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name
    )
    return int(method.end_lineno or method.lineno) - int(method.lineno) + 1


def main() -> int:
    errors: list[str] = []
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if manifest.get("release") != EXPECTED_RELEASE:
        errors.append(f"unexpected release label: {manifest.get('release')}")
    if manifest.get("project_version") != project.get("version"):
        errors.append(
            f"manifest version {manifest.get('project_version')} != pyproject {project.get('version')}"
        )

    architecture = dict(manifest.get("architecture") or {})
    coordinator = ROOT / "runtime/coordinator.py"
    coordinator_lines = len(coordinator.read_text(encoding="utf-8").splitlines())
    coordinator_init_lines = _method_size(coordinator, "RuntimeCoordinator", "__init__")
    if coordinator_lines != int(architecture.get("coordinator_verified_lines", -1)):
        errors.append(
            f"manifest coordinator lines stale: {architecture.get('coordinator_verified_lines')} != {coordinator_lines}"
        )
    if coordinator_init_lines != int(architecture.get("coordinator_verified_init_lines", -1)):
        errors.append(
            "manifest coordinator init lines stale: "
            f"{architecture.get('coordinator_verified_init_lines')} != {coordinator_init_lines}"
        )
    if coordinator_lines > int(architecture.get("coordinator_max_lines", 0)):
        errors.append("manifest coordinator budget exceeded")
    if coordinator_init_lines > int(architecture.get("coordinator_init_max_lines", 0)):
        errors.append("manifest coordinator init budget exceeded")

    quality = dict(manifest.get("quality") or {})
    exception_totals = dict(summarize(scan()).get("totals") or {})
    for manifest_key, audit_key in (
        ("broad_exception_handlers", "broad"),
        ("silent_exception_handlers", "silent"),
    ):
        expected = int(quality.get(manifest_key, -1))
        actual = int(exception_totals.get(audit_key, -1))
        if expected != actual:
            errors.append(f"manifest {manifest_key} stale: {expected} != {actual}")

    coverage_floor = float(quality.get("runtime_coverage_floor_percent", 0.0))
    coverage_verified = float(quality.get("runtime_coverage_verified_percent", 0.0))
    if coverage_floor < MIN_COVERAGE_FLOOR:
        errors.append(f"runtime coverage floor must remain at least {MIN_COVERAGE_FLOOR}%")
    if coverage_verified < coverage_floor:
        errors.append("verified runtime coverage is below the declared floor")
    if int(quality.get("verified_tests", 0)) < MIN_TESTS:
        errors.append(f"verified test count must remain at least {MIN_TESTS}")

    settings_text = (ROOT / "runtime/runtime_settings_store.py").read_text(encoding="utf-8")
    registry_text = (ROOT / "runtime/engagements/registry.py").read_text(encoding="utf-8")
    journal_text = (ROOT / "runtime/engagements/snapshot_journal.py").read_text(encoding="utf-8")
    diagnostics_text = (ROOT / "runtime/runtime_diagnostics.py").read_text(encoding="utf-8")
    if int(architecture.get("settings_schema", -1)) != EXPECTED_SETTINGS_SCHEMA or '"version": 12' not in settings_text:
        errors.append("settings schema manifest/source mismatch")
    if int(architecture.get("engagement_snapshot_schema", -1)) != EXPECTED_ENGAGEMENT_SCHEMA or '"schema_version": 7' not in registry_text:
        errors.append("engagement snapshot schema manifest/source mismatch")
    if int(architecture.get("engagement_snapshot_journal_schema", -1)) != EXPECTED_JOURNAL_SCHEMA or "SCHEMA_VERSION = 1" not in journal_text:
        errors.append("engagement snapshot journal schema manifest/source mismatch")
    if int(architecture.get("diagnostics_schema", -1)) != EXPECTED_DIAGNOSTICS_SCHEMA or '"schema_version": 6' not in diagnostics_text:
        errors.append("runtime diagnostics schema manifest/source mismatch")
    if int(architecture.get("runtime_boundary_count", -1)) != EXPECTED_BOUNDARIES:
        errors.append("runtime boundary count manifest mismatch")

    capabilities = dict(manifest.get("capabilities") or {})
    required_capabilities = (
        "durable_engagement_event_consumers",
        "automatic_engagement_lifecycle",
        "runtime_readiness_verdict",
        "daemon_failure_diagnostics",
        "tamper_evident_engagement_event_chain",
        "engagement_projection_replay_and_repair",
        "leased_event_delivery_with_dead_letters",
        "runtime_readiness_slo_and_incidents",
        "snapshot_integrity_digest",
        "dead_letter_payload_replay",
        "consumer_gap_fail_closed",
        "delivery_pressure_readiness",
        "engagement_recovery_service",
        "atomic_delivery_receipts",
        "poison_batch_bisection",
        "managed_consumer_supervisor",
        "receipt_cursor_recovery",
        "two_generation_snapshot_journal",
        "snapshot_rollback_detection",
        "automatic_snapshot_fallback",
        "reproducible_source_archives",
        "safe_bounded_archive_extraction",
        "official_deepseek_provider",
        "legacy_aggregator_removed",
        "deepseek_thinking_mode_control",
        "deepseek_text_only_vision_guard",
    )
    for capability in required_capabilities:
        if capabilities.get(capability) is not True:
            errors.append(f"release capability missing: {capability}")

    deepseek_text = (ROOT / "llm/deepseek.py").read_text(encoding="utf-8")
    process_text = (ROOT / "llm/process_manager.py").read_text(encoding="utf-8")
    client_text = (ROOT / "llm/client.py").read_text(encoding="utf-8")
    vision_text = (ROOT / "runtime/screen_vision_runtime.py").read_text(encoding="utf-8")
    for token in (
        'DEEPSEEK_BASE_URL = "https://api.deepseek.com"',
        'DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"',
        'DEEPSEEK_STRONG_MODEL = "deepseek-v4-pro"',
    ):
        if token not in deepseek_text:
            errors.append(f"DeepSeek provider contract missing: {token}")
    if 'ERIS_REMOTE_PROVIDER", "deepseek"' not in process_text:
        errors.append("DeepSeek is no longer the default remote provider")
    if 'DEEPSEEK_API_KEY' not in process_text:
        errors.append("DeepSeek credential lookup missing")
    if 'reasoning_content' not in (ROOT / "llm/service.py").read_text(encoding="utf-8"):
        errors.append("DeepSeek reasoning_content isolation missing")
    if 'supports_image_input' not in vision_text:
        errors.append("DeepSeek text-only vision guard missing")
    forbidden_parts = (
        "shop" + "aikey",
        "eris_" + "aggregator_api_key",
        "eris_" + "aggregator_base_url",
    )
    for relative in (
        "llm/process_manager.py",
        "llm/key_pool.py",
        "runtime/private_mind_model_adapter.py",
        "runtime/screen_vision_runtime.py",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8").lower()
        if any(token in text for token in forbidden_parts):
            errors.append(f"legacy aggregator dependency remains in {relative}")
    if 'payload["thinking"]' not in client_text:
        errors.append("DeepSeek thinking payload control missing")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(
        "release_manifest_ok "
        f"release={manifest.get('release')} version={project.get('version')} "
        f"coordinator_lines={coordinator_lines} broad={exception_totals.get('broad')} "
        f"silent={exception_totals.get('silent')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
