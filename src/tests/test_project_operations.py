# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

from actions.executor import ActionExecutor
from actions.router import ActionRouter
from runtime.project_operations import (
    PROJECT_CAPABILITY_IDS,
    PROJECT_OPERATIONS_VERSION,
    ProjectOperationsRuntime,
)
from runtime.workspace_manager import WorkspaceManager


def _git(repo: Path, *args: str) -> None:
    completed = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr or completed.stdout


def _base_owner(home: Path, *, client=None, source_hint: Path | None = None):
    if client is None:
        service = SimpleNamespace(client=None, fallback_client=None, escalation_client=None)
    else:
        service = SimpleNamespace(client=client, fallback_client=None, escalation_client=None)
    # project_root/repo_root cố tình có thể tồn tại để kiểm tra runtime không tự
    # coi source hint là active workspace.
    return SimpleNamespace(
        project_root=str(source_hint or ""),
        repo_root=str(source_hint or ""),
        memory_core=SimpleNamespace(base_dir=str((source_hint or home) / "memory_core")),
        llm_service=service,
        runtime_settings={
            "project_ops": {
                "enabled": True,
                "eris_home": str(home),
                "workspace_root": "",
                "allow_implicit_source_repo": False,
                "fallback_to_runtime_source": False,
                "autonomy_mode": "full",
                "proceed_without_user_reply": True,
                "auto_rollback_on_failure": True,
                "auto_package_patch": True,
                "coding_max_tokens": 2200,
                "coding_timeout_seconds": 30,
                "git_clone_timeout_seconds": 60,
                "max_repair_attempts": 2,
            }
        },
    )


def _owner(repo: Path, *, client=None):
    home = repo.parent / "ErisLive"
    owner = _base_owner(home, client=client, source_hint=repo)
    manager = WorkspaceManager(owner)
    manager.register_local(repo, activate=True)
    owner.workspace_manager = manager
    return owner


def _repo(tmp_path: Path, name: str = "sample-repo") -> Path:
    repo = tmp_path / name
    (repo / "memory_core").mkdir(parents=True)
    (repo / "sample.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_sample.py").write_text(
        "from sample import value\n\ndef test_value():\n    assert value() == 2\n", encoding="utf-8"
    )
    _git(repo, "init")
    _git(repo, "config", "user.email", "eris@example.invalid")
    _git(repo, "config", "user.name", "Eris Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    return repo


def _patch(return_value: int) -> str:
    return f"""diff --git a/sample.py b/sample.py
--- a/sample.py
+++ b/sample.py
@@ -1,2 +1,2 @@
 def value():
-    return 1
+    return {return_value}
"""


def test_contracts_and_router_expose_workspace_and_project_actions(tmp_path: Path):
    repo = _repo(tmp_path)
    runtime = ProjectOperationsRuntime(_owner(repo))
    assert PROJECT_OPERATIONS_VERSION == "project_operations.v1.1"
    assert set(PROJECT_CAPABILITY_IDS) >= {
        "project_apply_patch", "project_run_tests", "project_rollback",
        "project_package_patch", "project_execute_task", "workspace_join",
        "workspace_switch", "workspace_list", "workspace_leave",
    }
    assert len(runtime.contracts()) == len(PROJECT_CAPABILITY_IDS)
    router = ActionRouter()
    assert router.route_chat("tìm symbol ActionExecutor") == ("project_find_symbol", "ActionExecutor")
    assert router.route_chat("xem diff project") == ("project_git_diff", "current")
    assert router.route_chat("sửa file sample.py rồi chạy test") == (
        "project_execute_task", "sửa file sample.py rồi chạy test"
    )
    assert router.route_chat("vào repo https://github.com/example/demo.git") == (
        "workspace_join", "https://github.com/example/demo.git"
    )
    assert router.route_chat("vào https://github.com/example/demo.git sửa lỗi test") == (
        "project_execute_task", "vào https://github.com/example/demo.git sửa lỗi test"
    )
    assert router.route_chat("liệt kê workspace") == ("workspace_list", "")
    assert router.route_chat("chuyển sang workspace game") == ("workspace_switch", "game")
    # Câu hỏi tư vấn không được tự tiện đụng source.
    assert router.route_chat("có nên sửa project này không") is None


def test_eris_home_is_not_source_repo_and_no_implicit_workspace(tmp_path: Path):
    source_hint = _repo(tmp_path, "eris-source-hint")
    home = tmp_path / "ErisLive"
    owner = _base_owner(home, source_hint=source_hint)
    runtime = ProjectOperationsRuntime(owner)

    assert runtime.workspace_manager.home.root == home.resolve()
    assert runtime.workspace_manager.active_path() is None
    assert not runtime.availability("project_list_files")[0]
    failed = runtime.execute("project_list_files", "")
    assert not failed.success
    assert failed.data["availability_reason"] == "active_workspace_required"
    assert not (source_hint / ".eris").exists()

    expected_dirs = {
        "config", "memory", "logs", "cache", "patches", "workspaces",
        "downloads", "state", "runtime_data",
    }
    assert expected_dirs <= {item.name for item in home.iterdir() if item.is_dir()}


def test_workspace_join_local_registers_and_activates(tmp_path: Path):
    repo = _repo(tmp_path)
    home = tmp_path / "ErisLive"
    runtime = ProjectOperationsRuntime(_base_owner(home, source_hint=repo))

    joined = runtime.execute("workspace_join", json.dumps({"source": str(repo)}))
    assert joined.success
    assert joined.data["active"] is True
    assert runtime.workspace_manager.active_path() == repo.resolve()

    listed = runtime.execute("workspace_list", "")
    assert listed.success
    assert listed.data["active_workspace_id"] == joined.data["workspace_id"]
    registry = home / "state" / "workspace_registry.json"
    assert registry.is_file()
    assert str(repo.resolve()) in registry.read_text(encoding="utf-8")


def test_workspace_join_git_url_clones_under_erislive(tmp_path: Path):
    source = _repo(tmp_path, "remote-source")
    home = tmp_path / "ErisLive"
    runtime = ProjectOperationsRuntime(_base_owner(home))

    joined = runtime.execute("workspace_join", json.dumps({
        "source": source.as_uri(),
        "workspace_id": "cloned-repo",
    }))
    assert joined.success
    cloned = home / "workspaces" / "cloned-repo"
    assert runtime.workspace_manager.active_path() == cloned.resolve()
    assert (cloned / ".git").is_dir()
    assert (cloned / "sample.py").is_file()


def test_apply_patch_is_verified_and_state_lives_in_erislive(tmp_path: Path):
    repo = _repo(tmp_path)
    owner = _owner(repo)
    runtime = ProjectOperationsRuntime(owner)
    result = runtime.execute("project_apply_patch", json.dumps({"patch": _patch(2)}))
    assert result.success
    assert result.verified
    assert (repo / "sample.py").read_text(encoding="utf-8").endswith("return 2\n")

    op_dir = owner.workspace_manager.operation_dir(result.operation_id, create=False)
    assert (op_dir / "snapshot_manifest.json").is_file()
    assert not (repo / ".eris").exists()
    assert owner.workspace_manager.ledger_path().is_file()

    rollback = runtime.execute("project_rollback", json.dumps({"operation_id": result.operation_id}))
    assert rollback.success
    assert (repo / "sample.py").read_text(encoding="utf-8").endswith("return 1\n")


def test_executor_runs_tests_and_packages_only_changed_files(tmp_path: Path):
    repo = _repo(tmp_path)
    owner = _owner(repo)
    runtime = ProjectOperationsRuntime(owner)
    executor = ActionExecutor(observer=None)
    executor.bind_project_runtime(runtime)

    applied = executor.execute("project_apply_patch", json.dumps({"patch": _patch(2)}))
    assert applied.confirmed
    operation_id = applied.data["project_operation_id"]

    tests = executor.execute("project_run_tests", json.dumps({
        "command": [sys.executable, "-m", "pytest", "-q", "tests/test_sample.py"],
        "timeout": 60,
    }))
    assert tests.confirmed
    assert tests.data["exit_code"] == "0"

    package = executor.execute("project_package_patch", json.dumps({"operation_id": operation_id}))
    assert package.confirmed
    zip_path = Path(package.data["zip_path"])
    assert zip_path.is_file()
    assert owner.workspace_manager.home.root in zip_path.parents
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        notes = archive.read("GHI_CHU_VI.txt").decode("utf-8")
    assert "sample.py" in names
    assert "GHI_CHU_VI.txt" in names
    assert "tests/test_sample.py" not in names
    assert "GÓI PATCH WORKSPACE" in notes


class _FakeCodingClient:
    def __init__(self, patch: str):
        self.patch = patch

    def create_chat_completion(self, **kwargs):
        del kwargs
        content = json.dumps({
            "summary_vi": "Đổi giá trị trả về và chạy test mục tiêu.",
            "patch": self.patch,
            "tests": [[sys.executable, "-m", "pytest", "-q", "tests/test_sample.py"]],
            "notes_vi": "Đã cập nhật sample.py; test mục tiêu đạt.",
        }, ensure_ascii=False)
        return {"choices": [{"message": {"content": content}}]}


def test_execute_task_continues_without_approval_and_finishes_pipeline(tmp_path: Path):
    repo = _repo(tmp_path)
    runtime = ProjectOperationsRuntime(_owner(repo, client=_FakeCodingClient(_patch(2))))
    result = runtime.execute("project_execute_task", "sửa sample.py để test đạt rồi đóng gói")
    assert result.success
    assert result.verified
    assert result.data["touched_files"] == ["sample.py"]
    assert result.data["package"]["zip_path"]
    assert result.data["workspace"]["path"] == str(repo.resolve())
    assert (repo / "sample.py").read_text(encoding="utf-8").endswith("return 2\n")


class _RetryCodingClient:
    def __init__(self, first_patch: str, second_patch: str):
        self.patches = [first_patch, second_patch]
        self.calls = 0

    def create_chat_completion(self, **kwargs):
        del kwargs
        patch = self.patches[min(self.calls, len(self.patches) - 1)]
        self.calls += 1
        content = json.dumps({
            "summary_vi": f"Lần sửa {self.calls}",
            "assumptions_vi": ["Ưu tiên thay đổi nhỏ nhất."],
            "questions_vi": ["Có cần mở rộng sang file khác không?"],
            "patch": patch,
            "tests": [[sys.executable, "-m", "pytest", "-q", "tests/test_sample.py"]],
            "notes_vi": "Tự đọc failure rồi sửa lại.",
        }, ensure_ascii=False)
        return {"choices": [{"message": {"content": content}}]}


def test_execute_task_reads_failure_rolls_back_and_repairs(tmp_path: Path):
    repo = _repo(tmp_path)
    client = _RetryCodingClient(_patch(3), _patch(2))
    owner = _owner(repo, client=client)
    runtime = ProjectOperationsRuntime(owner)
    result = runtime.execute("project_execute_task", "sửa sample.py để test đạt")
    assert result.success
    assert client.calls == 2
    assert len(result.data["attempts"]) == 2
    assert result.data["attempts"][0]["success"] is False
    assert result.data["attempts"][1]["success"] is True
    assert result.data["unanswered_question_count"] == 2
    ops_root = owner.workspace_manager.operation_dir("_probe", create=False).parent
    question_files = list(ops_root.glob("*/questions_vi.json"))
    assert len(question_files) == 2
    assert (repo / "sample.py").read_text(encoding="utf-8").endswith("return 2\n")
