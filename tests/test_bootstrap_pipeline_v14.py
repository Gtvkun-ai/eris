from __future__ import annotations

from types import SimpleNamespace

import pytest

from runtime.coordinator_bootstrap import CoordinatorBootstrapMixin
from runtime.subsystem_health import HealthStatus, SubsystemHealthRegistry


class FakeSupervisor:
    def __init__(self) -> None:
        self.shutdowns = 0

    def shutdown_all(self) -> None:
        self.shutdowns += 1


def make_owner() -> CoordinatorBootstrapMixin:
    owner = object.__new__(CoordinatorBootstrapMixin)
    owner.bootstrap_completed_phases = []
    owner.subsystem_health_registry = SubsystemHealthRegistry(clock=lambda: 10.0)
    owner.subsystem_supervisor = FakeSupervisor()
    return owner


def test_bootstrap_phase_records_success() -> None:
    owner = make_owner()
    called = []

    owner._run_bootstrap_phase("memory", lambda value: called.append(value), value=7)

    assert called == [7]
    assert owner.bootstrap_completed_phases == ["memory"]
    assert owner.subsystem_health_registry.get("runtime.bootstrap.memory").status == HealthStatus.HEALTHY
    assert owner.subsystem_supervisor.shutdowns == 0


def test_bootstrap_phase_records_fatal_failure_and_cleans_services() -> None:
    owner = make_owner()

    with pytest.raises(RuntimeError, match="broken phase"):
        owner._run_bootstrap_phase("cognition", lambda: (_ for _ in ()).throw(RuntimeError("broken phase")))

    health = owner.subsystem_health_registry.get("runtime.bootstrap.cognition")
    assert health.status == HealthStatus.FAILED
    assert health.last_error_type == "RuntimeError"
    assert owner.subsystem_supervisor.shutdowns == 1
