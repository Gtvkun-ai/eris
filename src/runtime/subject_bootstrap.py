# -*- coding: utf-8 -*-
"""Feature-flagged composition for Subject Core rollout."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cortex.subject import SubjectService, SubjectServiceConfig
from memory.subject import SubjectRepository
from runtime.audit import ForensicStore
from runtime.world import CapabilityPolicy, CapabilityToken, CommandPolicy, SandboxWorld


FALSE_VALUES = {"0", "false", "no", "off", "disabled"}


def subject_core_enabled() -> bool:
    return str(os.getenv("ERIS_SUBJECT_CORE_ENABLED", "0") or "0").strip().lower() not in FALSE_VALUES


@dataclass(slots=True)
class SubjectCoreComponents:
    repository: SubjectRepository
    forensic_store: ForensicStore
    subject_service: SubjectService
    sandbox_world: SandboxWorld
    capability_token: CapabilityToken

    def close(self) -> None:
        self.forensic_store.close()
        self.repository.close()


def build_subject_core_components(
    *,
    data_root: str | os.PathLike[str] | None = None,
    workspace_root: str | os.PathLike[str] | None = None,
    action_executor: Any = None,
) -> SubjectCoreComponents:
    root = Path(data_root or os.getenv("ERIS_SUBJECT_CORE_DATA_DIR") or "data/subject_core").resolve()
    root.mkdir(parents=True, exist_ok=True)
    workspace = Path(workspace_root or os.getenv("ERIS_SUBJECT_WORKSPACE") or os.getcwd()).resolve()
    repository = SubjectRepository(root / "subject.db")
    forensic = ForensicStore(root / "audit.db")
    service = SubjectService(
        config=SubjectServiceConfig(
            subject_id=str(os.getenv("ERIS_SUBJECT_ID", "eris") or "eris"),
            deterministic=str(os.getenv("ERIS_SUBJECT_DETERMINISTIC", "0") or "0").lower() not in FALSE_VALUES,
            random_seed=int(os.getenv("ERIS_SUBJECT_RANDOM_SEED", "0") or 0),
        ),
        repository=repository,
        audit=forensic,
    )
    executable_allowlist = frozenset(
        item.strip() for item in str(os.getenv("ERIS_SANDBOX_EXECUTABLES", "python,python3,git") or "").split(",") if item.strip()
    )
    policy = CapabilityPolicy(CommandPolicy(
        executable_allowlist=executable_allowlist,
        workspace_root=str(workspace),
        network_enabled=False,
        environment_allowlist=frozenset(),
        policy_version="sandbox-policy-v2",
    ))
    sandbox = SandboxWorld(policy=policy, repository=repository, audit=forensic)
    capabilities = frozenset(
        item.strip() for item in str(os.getenv("ERIS_SANDBOX_CAPABILITIES", "observe,investigate,practice,preserve_commitment,request_capability,speak,simulate,read_file,write_file,run") or "").split(",") if item.strip()
    )
    now = time.time()
    token = CapabilityToken(
        token_id=f"bootstrap-{int(now)}",
        subject_id=service.config.subject_id,
        capabilities=capabilities,
        issued_at=now,
        expires_at=now + 86400.0,
        policy_version=policy.command_policy.policy_version,
        scope={"workspace_root": str(workspace)},
    )
    if action_executor is not None and callable(getattr(action_executor, "bind_sandbox_world", None)):
        action_executor.bind_sandbox_world(sandbox, token)
    return SubjectCoreComponents(repository, forensic, service, sandbox, token)
