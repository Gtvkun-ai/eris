# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from actions.capability_runtime import bind_runtime_owner, runtime_capability_snapshot
from actions.executor import ActionExecutor
from actions.router import ActionRouter
from runtime.environment_capabilities import (
    ENVIRONMENT_CAPABILITY_IDS,
    ENVIRONMENT_CAPABILITY_VERSION,
    EnvironmentCapabilityRuntime,
)
from screen.evidence_models import ActiveWindowInfo, ScreenTextBlock, ScreenTextSnapshot
from screen.screen_evidence_store import ScreenEvidenceStore


def _owner(tmp_path: Path):
    project = tmp_path / "eris"
    (project / "memory_core").mkdir(parents=True)
    store = ScreenEvidenceStore()
    now = time.time()
    store.publish(ScreenTextSnapshot(
        window=ActiveWindowInfo(
            title="tts_engine.py - eris - Visual Studio Code",
            process_name="Code.exe",
        ),
        blocks=(
            ScreenTextBlock(
                "block:error", "NameError: public_text is not defined", "uia", 0.91,
                "tts_engine.py - eris - Visual Studio Code", now,
            ),
            ScreenTextBlock(
                "block:code", "def synthesize(text):", "uia", 0.88,
                "tts_engine.py - eris - Visual Studio Code", now,
            ),
        ),
        captured_at=now,
        revision=7,
        backend="uia_only",
    ))
    telemetry_snapshot = SimpleNamespace(
        active_app="Visual Studio Code",
        active_window="tts_engine.py - eris - Visual Studio Code",
        active_window_title="tts_engine.py - eris - Visual Studio Code",
        content_metadata={},
        idle_seconds=2.0,
    )
    return SimpleNamespace(
        memory_core=SimpleNamespace(base_dir=str(project / "memory_core")),
        telemetry_service=SimpleNamespace(capture_snapshot=lambda **_: telemetry_snapshot),
        last_signal_snapshot=telemetry_snapshot,
        screen_evidence_store=store,
        screen_text_worker=SimpleNamespace(enabled=True),
        mood_score=50,
        inferred_pos_x=0.5,
        action_router=ActionRouter(),
        action_executor=ActionExecutor(),
        runtime_settings={"capabilities": {"respect_runtime_availability": True}},
    ), project


def test_version_and_contracts_are_complete(tmp_path: Path):
    owner, _ = _owner(tmp_path)
    runtime = EnvironmentCapabilityRuntime(owner)
    assert ENVIRONMENT_CAPABILITY_VERSION == "environment_capability.v1.0"
    assert set(ENVIRONMENT_CAPABILITY_IDS) == {
        "get_active_application", "read_visible_ui_text", "inspect_runtime_log",
        "read_current_error", "inspect_selected_file", "get_project_status",
    }
    assert len(runtime.contracts()) == 6


def test_active_application_only_claims_observed_window(tmp_path: Path):
    owner, _ = _owner(tmp_path)
    result = EnvironmentCapabilityRuntime(owner).execute("get_active_application")
    assert result.success
    assert result.data["application"] == "VS Code"
    assert "VS Code" in result.public_text
    assert "lỗi TTS" not in result.public_text


def test_visible_ui_text_returns_uia_blocks_with_evidence(tmp_path: Path):
    owner, _ = _owner(tmp_path)
    result = EnvironmentCapabilityRuntime(owner).execute("read_visible_ui_text", "current")
    assert result.success
    assert result.data["block_count"] == 2
    assert "NameError" in result.data["visible_text"]
    assert {item.evidence_id for item in result.evidence} >= {"block:error", "block:code"}


def test_visible_ui_text_respects_privacy_guard(tmp_path: Path):
    owner, _ = _owner(tmp_path)
    owner.screen_evidence_store.publish(ScreenTextSnapshot(
        window=ActiveWindowInfo(title="Gmail"),
        captured_at=time.time(), revision=8, backend="uia_only", privacy_blocked=True,
    ))
    result = EnvironmentCapabilityRuntime(owner).execute("read_visible_ui_text")
    assert result.success
    assert result.data["privacy_blocked"] is True
    assert "privacy guard" in result.public_text


def test_runtime_log_tail_redacts_secrets(tmp_path: Path, monkeypatch):
    owner, project = _owner(tmp_path)
    logs = project / "logs"
    logs.mkdir()
    log_path = logs / "eris_run_20260716_220000.txt"
    log_path.write_text(
        "[INFO] start\nAuthorization: Bearer super_secret_token_123456789\n"
        "[ERROR] TTS failed with NameError\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ERIS_RUNTIME_LOG_PATH", str(log_path))
    result = EnvironmentCapabilityRuntime(owner).execute("inspect_runtime_log", "latest")
    assert result.success
    assert "super_secret" not in result.data["tail"]
    assert "[đã ẩn]" in result.data["tail"] or "khóa bí mật" in result.data["tail"]
    assert result.data["matched_line_count"] == 3


def test_current_error_uses_concrete_error_not_generic_warning(tmp_path: Path, monkeypatch):
    owner, project = _owner(tmp_path)
    logs = project / "logs"
    logs.mkdir()
    log_path = logs / "eris_run_20260716_220100.txt"
    log_path.write_text(
        "[WARNING] provider slow\nTraceback (most recent call last):\n"
        "  File 'x.py', line 2\nNameError: public_text is not defined\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ERIS_RUNTIME_LOG_PATH", str(log_path))
    result = EnvironmentCapabilityRuntime(owner).execute("read_current_error")
    assert result.success
    assert result.data["found"] is True
    assert "NameError" in result.data["error_text"]


def test_selected_file_from_title_does_not_invent_content(tmp_path: Path):
    owner, _ = _owner(tmp_path)
    result = EnvironmentCapabilityRuntime(owner).execute("inspect_selected_file", "metadata")
    assert result.success
    assert result.data["file_name"] == "tts_engine.py"
    assert result.data["content_read"] is False
    assert "chưa có path thật" in result.public_text


def test_selected_file_bridge_reads_only_inside_project(tmp_path: Path, monkeypatch):
    owner, project = _owner(tmp_path)
    target = project / "src" / "runtime" / "sample.py"
    target.parent.mkdir(parents=True)
    target.write_text("API_KEY='secret_value_should_be_hidden'\nprint('ok')\n", encoding="utf-8")
    monkeypatch.setenv("ERIS_SELECTED_FILE_PATH", str(target))
    result = EnvironmentCapabilityRuntime(owner).execute("inspect_selected_file", "content")
    assert result.success
    assert result.data["content_read"] is True
    assert "secret_value_should_be_hidden" not in result.data["preview"]
    assert "[đã ẩn]" in result.data["preview"]


def test_project_status_parses_porcelain(tmp_path: Path):
    owner, _ = _owner(tmp_path)
    runtime = EnvironmentCapabilityRuntime(owner)
    completed = subprocess.CompletedProcess(
        args=["git"], returncode=0,
        stdout="## main...origin/main [ahead 2, behind 1]\nM  staged.py\n M changed.py\n?? new.py\nUU conflict.py\n",
        stderr="",
    )
    with patch.object(runtime, "_run_git", return_value=completed):
        result = runtime.execute("get_project_status")
    assert result.success
    assert result.data["branch"] == "main"
    assert result.data["ahead"] == 2
    assert result.data["behind"] == 1
    assert result.data["dirty_count"] == 4
    assert result.data["untracked_count"] == 1
    assert result.data["conflict_count"] == 1


def test_executor_router_and_runtime_snapshot_are_wired(tmp_path: Path, monkeypatch):
    owner, project = _owner(tmp_path)
    logs = project / "logs"
    logs.mkdir()
    log_path = logs / "eris_run_20260716_220200.txt"
    log_path.write_text("[INFO] ready\n", encoding="utf-8")
    monkeypatch.setenv("ERIS_RUNTIME_LOG_PATH", str(log_path))

    runtime = EnvironmentCapabilityRuntime(owner)
    owner.environment_capabilities = runtime
    owner.action_executor.bind_environment_runtime(runtime)
    bind_runtime_owner(owner)

    assert owner.action_router.route_chat("app nào đang active") == ("get_active_application", "current")
    assert owner.action_router.route_chat("đọc lỗi hiện tại") == ("read_current_error", "current")
    assert owner.action_router.route_chat("git status") == ("get_project_status", "current")

    executed = owner.action_executor.execute("get_active_application")
    assert executed.confirmed
    snapshot = runtime_capability_snapshot()
    assert snapshot["statuses"]["get_active_application"]["available"] is True
    assert snapshot["statuses"]["read_visible_ui_text"]["available"] is True
