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


def _git(repo: Path, *args: str) -> None:
    completed = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr or completed.stdout


def _owner(repo: Path, *, client=None):
    if client is None:
        service = SimpleNamespace(client=None, fallback_client=None, escalation_client=None)
    else:
        service = SimpleNamespace(client=client, fallback_client=None, escalation_client=None)
    return SimpleNamespace(
        project_root=str(repo),
        memory_core=SimpleNamespace(base_dir=str(repo / "memory_core")),
        llm_service=service,
        runtime_settings={
            "project_ops": {
                "enabled": True,
                "autonomy_mode": "full",
                "proceed_without_user_reply": True,
                "auto_rollback_on_failure": True,
                "auto_package_patch": True,
                "coding_max_tokens": 2200,
                "coding_timeout_seconds": 30,
            }
        },
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "eris"
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


def test_contracts_and_router_expose_autonomous_project_actions(tmp_path: Path):
    repo = _repo(tmp_path)
    runtime = ProjectOperationsRuntime(_owner(repo))
    assert PROJECT_OPERATIONS_VERSION == "project_operations.v1.0"
    assert set(PROJECT_CAPABILITY_IDS) >= {
        "project_apply_patch", "project_run_tests", "project_rollback",
        "project_package_patch", "project_execute_task",
    }
    assert len(runtime.contracts()) == len(PROJECT_CAPABILITY_IDS)
    router = ActionRouter()
    assert router.route_chat("tìm symbol ActionExecutor") == ("project_find_symbol", "ActionExecutor")
    assert router.route_chat("xem diff project") == ("project_git_diff", "current")
    assert router.route_chat("sửa file sample.py rồi chạy test") == (
        "project_execute_task", "sửa file sample.py rồi chạy test"
    )
    # Câu hỏi tư vấn không được tự tiện đụng source.
    assert router.route_chat("có nên sửa project này không") is None


def test_apply_patch_is_verified_and_can_rollback(tmp_path: Path):
    repo = _repo(tmp_path)
    runtime = ProjectOperationsRuntime(_owner(repo))
    patch = """diff --git a/sample.py b/sample.py
--- a/sample.py
+++ b/sample.py
@@ -1,2 +1,2 @@
 def value():
-    return 1
+    return 2
"""
    result = runtime.execute("project_apply_patch", json.dumps({"patch": patch}))
    assert result.success
    assert result.verified
    assert (repo / "sample.py").read_text(encoding="utf-8").endswith("return 2\n")
    assert (repo / ".eris" / "project_ops" / result.operation_id / "snapshot_manifest.json").is_file()

    rollback = runtime.execute("project_rollback", json.dumps({"operation_id": result.operation_id}))
    assert rollback.success
    assert (repo / "sample.py").read_text(encoding="utf-8").endswith("return 1\n")


def test_executor_runs_tests_and_packages_only_changed_files(tmp_path: Path):
    repo = _repo(tmp_path)
    owner = _owner(repo)
    runtime = ProjectOperationsRuntime(owner)
    executor = ActionExecutor(observer=None)
    executor.bind_project_runtime(runtime)

    patch = """diff --git a/sample.py b/sample.py
--- a/sample.py
+++ b/sample.py
@@ -1,2 +1,2 @@
 def value():
-    return 1
+    return 2
"""
    applied = executor.execute("project_apply_patch", json.dumps({"patch": patch}))
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
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
    assert "sample.py" in names
    assert "GHI_CHU_VI.txt" in names
    assert "tests/test_sample.py" not in names


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
    patch = """diff --git a/sample.py b/sample.py
--- a/sample.py
+++ b/sample.py
@@ -1,2 +1,2 @@
 def value():
-    return 1
+    return 2
"""
    runtime = ProjectOperationsRuntime(_owner(repo, client=_FakeCodingClient(patch)))
    result = runtime.execute("project_execute_task", "sửa sample.py để test đạt rồi đóng gói")
    assert result.success
    assert result.verified
    assert result.data["touched_files"] == ["sample.py"]
    assert result.data["package"]["zip_path"]
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
    bad_patch = """diff --git a/sample.py b/sample.py
--- a/sample.py
+++ b/sample.py
@@ -1,2 +1,2 @@
 def value():
-    return 1
+    return 3
"""
    good_patch = """diff --git a/sample.py b/sample.py
--- a/sample.py
+++ b/sample.py
@@ -1,2 +1,2 @@
 def value():
-    return 1
+    return 2
"""
    client = _RetryCodingClient(bad_patch, good_patch)
    runtime = ProjectOperationsRuntime(_owner(repo, client=client))
    result = runtime.execute("project_execute_task", "sửa sample.py để test đạt")
    assert result.success
    assert client.calls == 2
    assert len(result.data["attempts"]) == 2
    assert result.data["attempts"][0]["success"] is False
    assert result.data["attempts"][1]["success"] is True
    assert result.data["unanswered_question_count"] == 2
    question_files = list((repo / ".eris" / "project_ops").glob("*/questions_vi.json"))
    assert len(question_files) == 2
    assert (repo / "sample.py").read_text(encoding="utf-8").endswith("return 2\n")
