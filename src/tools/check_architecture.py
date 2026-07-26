# -*- coding: utf-8 -*-
"""Fast architectural regression checks for the stabilized ERIS runtime.

The checks intentionally protect structural boundaries rather than aesthetics.
They keep the coordinator thin, bootstrap phased, transport mediated, and
engagement domains declarative. A budget is cheaper than rediscovering a god
object after six rushed pull requests.
"""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COORDINATOR = ROOT / "runtime" / "coordinator.py"
BOOTSTRAP = ROOT / "runtime" / "coordinator_bootstrap.py"
MAX_COORDINATOR_LINES = 180
MAX_COORDINATOR_INIT_LINES = 35
MAX_BOOTSTRAP_PHASE_LINES = 175
MAX_BOOTSTRAP_INIT_LINES = 70

REQUIRED_MODULES = {
    # V5-V9 boundaries.
    "runtime/observer_private_runtime.py",
    "runtime/cognitive_event_runtime.py",
    "runtime/mental_process_runtime.py",
    "runtime/incoming_protocol_runtime.py",
    "runtime/settings_control_runtime.py",
    "runtime/tutor_research_runtime.py",
    "runtime/screen_vision_runtime.py",
    "runtime/provider_action_runtime.py",
    "runtime/incoming_dispatcher.py",
    "runtime/transport_boundary.py",
    "runtime/loop_guard.py",
    # V10-V14 boundaries.
    "runtime/coordinator_bootstrap.py",
    "runtime/model_memory_runtime.py",
    "runtime/public_output_runtime.py",
    "runtime/user_control_runtime.py",
    "runtime/coordinator_shutdown.py",
    "runtime/autonomous_loop_runtime.py",
    "runtime/runtime_diagnostics.py",
    "runtime/engagements/profiles.py",
    # V15-V18 durability and observability boundaries.
    "runtime/readiness.py",
    "runtime/diagnostic_logging.py",
    # V19-V22 reliable event delivery and SLO boundaries.
    "runtime/engagements/consumer.py",
    "runtime/engagements/recovery.py",
    "runtime/engagements/supervisor.py",
    "runtime/runtime_slo.py",
    # V31-V34 snapshot durability and release-supply-chain boundaries.
    "runtime/engagements/snapshot_journal.py",
    # V36 companion-aware DeepSeek routing boundary.
    "runtime/companion_model_routing.py",
}

REQUIRED_COORDINATOR_BASES = {
    "CoordinatorBootstrapMixin",
    "ModelMemoryRuntimeMixin",
    "PublicOutputRuntimeMixin",
    "UserControlRuntimeMixin",
    "CoordinatorShutdownMixin",
    "AutonomousLoopRuntimeMixin",
    "ObserverPrivateRuntimeMixin",
    "CognitiveEventRuntimeMixin",
    "MentalProcessRuntimeMixin",
    "IncomingProtocolRuntimeMixin",
    "SettingsControlRuntimeMixin",
    "TutorResearchRuntimeMixin",
    "ScreenVisionRuntimeMixin",
    "ProviderActionRuntimeMixin",
}

BOOTSTRAP_PHASES = {
    "_bootstrap_foundation",
    "_bootstrap_memory_and_capabilities",
    "_bootstrap_hardening_and_state",
    "_bootstrap_cognition_services",
    "_bootstrap_session_and_perception",
    "_bootstrap_thought_and_ai",
}


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def _methods(node: ast.ClassDef) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        child.name: child
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _line_count(node: ast.AST) -> int:
    start = int(getattr(node, "lineno", 0) or 0)
    end = int(getattr(node, "end_lineno", start) or start)
    return end - start + 1


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def main() -> int:
    errors: list[str] = []

    source = COORDINATOR.read_text(encoding="utf-8")
    line_count = len(source.splitlines())
    if line_count > MAX_COORDINATOR_LINES:
        errors.append(f"coordinator line budget exceeded: {line_count} > {MAX_COORDINATOR_LINES}")

    tree = ast.parse(source)
    coordinator = _class(tree, "RuntimeCoordinator")
    local_methods = _methods(coordinator)
    if set(local_methods) != {"__init__"}:
        extras = sorted(set(local_methods) - {"__init__"})
        missing = sorted({"__init__"} - set(local_methods))
        errors.append(f"coordinator must remain a facade; extras={extras} missing={missing}")

    init = local_methods.get("__init__")
    init_lines = _line_count(init) if init is not None else 0
    if init_lines > MAX_COORDINATOR_INIT_LINES:
        errors.append(f"coordinator __init__ budget exceeded: {init_lines} > {MAX_COORDINATOR_INIT_LINES}")

    bases = {_base_name(base) for base in coordinator.bases}
    missing_bases = sorted(REQUIRED_COORDINATOR_BASES - bases)
    if missing_bases:
        errors.append(f"coordinator lost runtime boundaries: {', '.join(missing_bases)}")

    bootstrap_source = BOOTSTRAP.read_text(encoding="utf-8")
    bootstrap_tree = ast.parse(bootstrap_source)
    bootstrap = _class(bootstrap_tree, "CoordinatorBootstrapMixin")
    bootstrap_methods = _methods(bootstrap)
    bootstrap_init = bootstrap_methods.get("__init__")
    bootstrap_init_lines = _line_count(bootstrap_init) if bootstrap_init is not None else 0
    if bootstrap_init_lines > MAX_BOOTSTRAP_INIT_LINES:
        errors.append(
            f"bootstrap __init__ budget exceeded: {bootstrap_init_lines} > {MAX_BOOTSTRAP_INIT_LINES}"
        )
    missing_phases = sorted(BOOTSTRAP_PHASES - set(bootstrap_methods))
    if missing_phases:
        errors.append(f"bootstrap phases missing: {', '.join(missing_phases)}")
    for phase in sorted(BOOTSTRAP_PHASES & set(bootstrap_methods)):
        size = _line_count(bootstrap_methods[phase])
        if size > MAX_BOOTSTRAP_PHASE_LINES:
            errors.append(f"bootstrap phase too large: {phase}={size} > {MAX_BOOTSTRAP_PHASE_LINES}")

    for relative in sorted(REQUIRED_MODULES):
        if not (ROOT / relative).is_file():
            errors.append(f"missing runtime boundary: {relative}")

    for relative in ("runtime/incoming_protocol_runtime.py", "runtime/settings_control_runtime.py"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        if "self.transport.send_json(" in text:
            errors.append(f"raw transport send reintroduced in {relative}")

    detector = (ROOT / "runtime/engagements/detector.py").read_text(encoding="utf-8")
    if "EngagementProfileRegistry" not in detector or "self.profiles" not in detector:
        errors.append("engagement detector no longer delegates domain matching to the profile registry")
    if "def _domain(" in detector or "def _configuration(" in detector:
        errors.append("hard-coded engagement domain/configuration chain reintroduced")

    diagnostics = (ROOT / "runtime/runtime_diagnostics.py").read_text(encoding="utf-8")
    if "class RuntimeDiagnostics" not in diagnostics:
        errors.append("unified runtime diagnostics boundary missing")

    registry = (ROOT / "runtime/engagements/registry.py").read_text(encoding="utf-8")
    contracts = (ROOT / "runtime/engagements/contracts.py").read_text(encoding="utf-8")
    for token in (
        "EngagementEventBatch",
        "EngagementConsumerState",
        "EngagementDeadLetter",
        "prev_hash",
        "event_hash",
        "_consumers",
        "def lease_events(",
        "def fail_delivery(",
        "def replay_engagement(",
        "def repair_engagement_projection(",
        "def audit_event_stream(",
        "def compact(",
        "def validate_invariants(",
        "def dead_letter_batch(",
        "def resolve_dead_letter(",
        "def reset_consumer_to_earliest(",
        "def block_consumer(",
        "blocked_reason",
        "snapshot_digest",
        "EngagementDeliveryReceipt",
        "def commit_delivery(",
        "def split_delivery_lease(",
        "def audit_delivery_receipts(",
        "def repair_receipt_cursors(",
        '"schema_version": 7',
        "def validate_snapshot_payload(",
        "def snapshot_digest(",
    ):
        if token not in registry and token not in contracts:
            errors.append(f"engagement durability contract missing: {token}")

    consumer = (ROOT / "runtime/engagements/consumer.py").read_text(encoding="utf-8")
    for token in (
        "class EngagementEventConsumer", "def poll_once(", "def replay_dead_letter(",
        "delivery_stop_on_gap", "dead_lettered",
    ):
        if token not in consumer:
            errors.append(f"reliable engagement consumer contract missing: {token}")

    consumer_supervisor = (ROOT / "runtime/engagements/supervisor.py").read_text(encoding="utf-8")
    for token in ("class EngagementConsumerSupervisor", "def tick(", "def register("):
        if token not in consumer_supervisor:
            errors.append(f"managed engagement consumer contract missing: {token}")

    readiness = (ROOT / "runtime/readiness.py").read_text(encoding="utf-8")
    if "class RuntimeReadinessEvaluator" not in readiness:
        errors.append("runtime readiness evaluator boundary missing")
    diagnostics = (ROOT / "runtime/runtime_diagnostics.py").read_text(encoding="utf-8")
    if '"schema_version": 6' not in diagnostics or '"readiness"' not in diagnostics or '"slo"' not in diagnostics:
        errors.append("runtime diagnostics readiness/SLO projection missing")
    slo = (ROOT / "runtime/runtime_slo.py").read_text(encoding="utf-8")
    for token in ("class RuntimeSLOTracker", "class RuntimeIncident", "ready_ratio"):
        if token not in slo:
            errors.append(f"runtime SLO contract missing: {token}")

    companion_router = (ROOT / "runtime/companion_model_routing.py").read_text(encoding="utf-8")
    orchestrator_text = (ROOT / "runtime/ai_orchestrated/orchestrator.py").read_text(encoding="utf-8")
    for token in ("class CompanionModelRouter", "def route_companion_turn(", "clarification_preferred"):
        if token not in companion_router:
            errors.append(f"companion model routing contract missing: {token}")
    if "route_companion_turn(user_text" not in orchestrator_text:
        errors.append("public chat no longer uses companion-aware model routing")

    journal = (ROOT / "runtime/engagements/snapshot_journal.py").read_text(encoding="utf-8")
    for token in ("class EngagementSnapshotJournal", "def load(", "def stage(", "PRIMARY_KEY", "BACKUP_KEY"):
        if token not in journal:
            errors.append(f"engagement snapshot journal contract missing: {token}")

    verifier = (ROOT / "tools/verify_release.py").read_text(encoding="utf-8")
    for token in ("def inspect_archive(", "def safe_extract_archive(", "max_compression_ratio", "duplicate archive entry"):
        if token not in verifier:
            errors.append(f"release archive hardening contract missing: {token}")

    recovery = (ROOT / "runtime/engagements/recovery.py").read_text(encoding="utf-8")
    for token in ("class EngagementRecoveryService", "def audit(", "def recover("):
        if token not in recovery:
            errors.append(f"engagement recovery contract missing: {token}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    phase_sizes = {
        phase: _line_count(bootstrap_methods[phase])
        for phase in sorted(BOOTSTRAP_PHASES)
    }
    print(
        "architecture_ok "
        f"coordinator_lines={line_count} coordinator_init_lines={init_lines} "
        f"bootstrap_init_lines={bootstrap_init_lines} bootstrap_phases={phase_sizes} "
        f"boundaries={len(REQUIRED_MODULES)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
