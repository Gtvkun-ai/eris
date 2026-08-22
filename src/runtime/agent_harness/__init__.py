"""Unified Agent Harness public surface."""

from .task_store import AgentTaskStore
from .event_bus import AgentEventBus
from .supervisor_bridge import AgentSupervisorBridge
from .gemini_cli_executor import GeminiCliDecisionExecutor, GeminiCliError
from .native_tool_adapter import NativeCapabilityToolAdapter
from .capability_self_model import CapabilityProfile, CapabilitySelfAssessment, CapabilitySelfModel
from .workspace_checkpoint_store import WorkspaceCheckpoint, WorkspaceCheckpointStore
from .cline_bridge_client import ClineBridgeClient
from .steering_loader import load_steering, write_steering_file, ensure_steering_dir
from .spec_manager import detect_spec_intent, create_spec, execute_spec, list_specs

__all__ = [
    "AgentTaskStore",
    "AgentEventBus",
    "AgentSupervisorBridge",
    "GeminiCliDecisionExecutor",
    "GeminiCliError",
    "NativeCapabilityToolAdapter",
    "CapabilityProfile",
    "CapabilitySelfAssessment",
    "CapabilitySelfModel",
    "WorkspaceCheckpoint",
    "WorkspaceCheckpointStore",
    # Cline integration
    "ClineBridgeClient",
    # Steering files
    "load_steering",
    "write_steering_file",
    "ensure_steering_dir",
    # Spec system
    "detect_spec_intent",
    "create_spec",
    "execute_spec",
    "list_specs",
]
