"""
Permission Gate module.
Enforces ALLOW/ASK/DENY rules for agent actions.
"""
from enum import Enum
from typing import Dict

class Permission(Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"

class PermissionGate:
    def __init__(self):
        self.tool_policies: Dict[str, Permission] = {
            "search_capabilities": Permission.ALLOW,
            "activate_skill": Permission.ALLOW,
            "project_read_file": Permission.ALLOW,
            "project_search_text": Permission.ALLOW,
            "list_dir": Permission.ALLOW,
            "project_apply_patch": Permission.ALLOW,
            "project_write_file": Permission.ALLOW,
            "pytest": Permission.ALLOW,
            "git commit": Permission.ASK,
            "git push": Permission.DENY,
            "rm -rf": Permission.DENY,
        }
        
    def check_permission(self, action_name: str) -> Permission:
        if action_name in self.tool_policies:
            return self.tool_policies[action_name]
        for key, policy in self.tool_policies.items():
            if action_name.startswith(key):
                return policy
        return Permission.ASK

    def set_policy(self, action_name: str, permission: Permission):
        self.tool_policies[action_name] = permission
