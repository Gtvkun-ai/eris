from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "vscode-extension"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_v91_extension_activation_has_no_desktop_bridge_dependency() -> None:
    source = _read(EXT / "src" / "extension.ts")
    assert "ErisObserverBridge" not in source
    assert "CompanionWorkspaceObserver" not in source
    assert "registerExternalAgentObservationBridge" not in source
    assert "erisLink" not in source


def test_v91_gitpilot_client_does_not_read_or_publish_eris_desktop_context() -> None:
    source = _read(EXT / "src" / "gitPilotClient.ts")
    forbidden = (
        "ErisObserverBridge",
        "publishCodingObservation",
        "readProjectContext",
        "userIntentObservation",
        "taskLifecycleObservation",
        "fromGitPilotEvent",
    )
    for marker in forbidden:
        assert marker not in source


def test_v91_extension_manifest_has_no_eris_link_settings() -> None:
    package = _read(EXT / "package.json")
    assert '"version": "0.22.0"' in package
    assert "erisCode.erisLink" not in package
    assert "Companion Observation Bridge" not in package


def test_v91_desktop_coordinator_does_not_start_eris_code_observer_listener() -> None:
    source = _read(ROOT / "runtime" / "coordinator.py")
    assert "observer_link_enabled()" not in source
    assert "ErisCodeObserverLink(" not in source
    assert "self.eris_code_observer_link = None" in source
    assert "self.coding_observation_service = None" in source
