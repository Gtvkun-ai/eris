# -*- coding: utf-8 -*-
"""Permission Gate cho tool calls của agent.

Quyền xét cả tool ID lẫn arguments. Chỉ nhìn mỗi tên `project_run_command` rồi
cho qua `git push` là một lỗ hổng có tính hài hước hơi quá tay.
"""
from __future__ import annotations

from enum import Enum
import shlex
from typing import Any


class Permission(Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionGate:
    def __init__(self):
        self.tool_policies: dict[str, Permission] = {
            "search_capabilities": Permission.ALLOW,
            "activate_skill": Permission.ALLOW,
            "get_local_time": Permission.ALLOW,
            "get_now_playing": Permission.ALLOW,
            "get_active_application": Permission.ALLOW,
            "read_visible_ui_text": Permission.ALLOW,
            "inspect_runtime_log": Permission.ALLOW,
            "read_current_error": Permission.ALLOW,
            "inspect_selected_file": Permission.ALLOW,
            "get_project_status": Permission.ALLOW,
            "project_list_files": Permission.ALLOW,
            "project_read_file": Permission.ALLOW,
            "project_search_text": Permission.ALLOW,
            "project_find_symbol": Permission.ALLOW,
            "project_git_diff": Permission.ALLOW,
            "project_apply_patch": Permission.ALLOW,
            "project_run_tests": Permission.ALLOW,
            "project_run_command": Permission.ALLOW,
            "project_rollback": Permission.ALLOW,
            "project_package_patch": Permission.ALLOW,
            "workspace_list": Permission.ALLOW,
            "set_volume": Permission.ALLOW,
            "play_pause_media": Permission.ALLOW,
            "copy_text": Permission.ALLOW,
            "focus_window": Permission.ALLOW,
            "launch_app": Permission.ASK,
            "open_url": Permission.ASK,
            "workspace_join": Permission.ASK,
            "workspace_switch": Permission.ASK,
            "workspace_leave": Permission.ASK,
            # Legacy one-shot executor không còn là đường agent ưu tiên.
            "project_execute_task": Permission.DENY,
        }

    def check_permission(self, action_name: str, arguments: dict[str, Any] | None = None) -> Permission:
        name = str(action_name or "").strip()
        args = dict(arguments or {})
        if name == "project_run_command":
            command_policy = self._command_policy(str(args.get("command", "") or ""))
            if command_policy is not None:
                return command_policy
        if name in self.tool_policies:
            return self.tool_policies[name]
        for key, policy in self.tool_policies.items():
            if name.startswith(key):
                return policy
        return Permission.ASK

    @staticmethod
    def _command_policy(command: str) -> Permission | None:
        text = str(command or "").strip()
        if not text:
            return Permission.DENY
        try:
            parts = shlex.split(text, posix=False)
        except ValueError:
            return Permission.DENY
        lowered = [part.strip('"\'').lower() for part in parts]
        if not lowered:
            return Permission.DENY
        dangerous = {"rm", "rmdir", "del", "erase", "format", "shutdown", "reboot"}
        if lowered[0] in dangerous:
            return Permission.DENY
        if lowered[0] == "git" and len(lowered) > 1:
            if lowered[1] in {"push", "reset", "clean", "rebase"}:
                return Permission.DENY
            if lowered[1] in {"commit", "merge", "checkout", "switch"}:
                return Permission.ASK
        return None

    def set_policy(self, action_name: str, permission: Permission):
        self.tool_policies[action_name] = permission


__all__ = ["PermissionGate", "Permission"]
