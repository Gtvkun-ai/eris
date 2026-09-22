"""Durable workspace-scoped memory for the Main Coordinator.

Session memory answers "what happened in this chat?".  This module answers a
separate question: "what has Main already learned about this workspace across
sessions and process restarts?"

The store is deliberately local and boring: one compact JSON document per
workspace identity under ``~/.gitpilot/workspace-memory`` (configurable via
``GITPILOT_WORKSPACE_MEMORY_ROOT``).  It never stores provider secrets and it
never treats old source evidence as fresh: revision compatibility is still
checked by ``CoordinatorState`` on the next turn.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .state import CoordinatorMemory

_DEFAULT_ROOT = Path.home() / ".gitpilot" / "workspace-memory"
_SCHEMA_VERSION = 1
_PROCESS_LOCK = threading.RLock()


@contextmanager
def _cross_process_lock(path: Path, *, timeout: float = 5.0):
    """Tiny portable lock-file for merge-on-save critical sections.

    Atomic replace protects readers from partial JSON; this lock additionally
    prevents two backend processes from both reading the same old file and then
    overwriting each other's merged knowledge. Stale lock files are reclaimed.
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + timeout
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, f"{os.getpid()} {time.time()}".encode("ascii", errors="ignore"))
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > 30.0:
                    lock_path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError(f"workspace memory lock timeout: {lock_path}")
            time.sleep(0.02)
    try:
        yield
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass


@dataclass(frozen=True)
class WorkspaceIdentity:
    """Stable identity for one local workspace checkout/folder.

    Local/folder sessions currently expose no trustworthy remote URL, so the
    canonical resolved path is the authority.  That is intentionally stricter
    than repo-name matching: two separate working trees must not silently share
    dirty-tree knowledge merely because their directory names match.
    """

    key: str
    canonical_path: str
    repo_name: str

    @classmethod
    def from_workspace(cls, workspace) -> "WorkspaceIdentity":
        canonical = str(Path(workspace.path).expanduser().resolve())
        # normcase matters on Windows where the same path may be reopened with
        # different casing.  Resolve first so symlink aliases converge too.
        material = os.path.normcase(canonical)
        key = hashlib.sha256(("local-workspace\0" + material).encode("utf-8")).hexdigest()[:32]
        return cls(
            key=key,
            canonical_path=canonical,
            repo_name=str(getattr(workspace, "repo", "") or Path(canonical).name),
        )


@dataclass
class WorkspaceMemoryRecord:
    identity: WorkspaceIdentity
    memory: CoordinatorMemory
    first_seen: float
    last_seen: float
    write_count: int = 0


class WorkspaceMemoryStore:
    """Atomic, compact, workspace-scoped persistence for CoordinatorMemory."""

    def __init__(self, root: Optional[Path] = None) -> None:
        configured = os.getenv("GITPILOT_WORKSPACE_MEMORY_ROOT", "").strip()
        self.root = Path(root or configured or _DEFAULT_ROOT).expanduser()

    def identity_for(self, workspace) -> WorkspaceIdentity:
        return WorkspaceIdentity.from_workspace(workspace)

    def _path(self, identity: WorkspaceIdentity) -> Path:
        return self.root / f"{identity.key}.json"

    def load(self, workspace) -> WorkspaceMemoryRecord:
        identity = self.identity_for(workspace)
        path = self._path(identity)
        now = time.time()
        with _PROCESS_LOCK:
            if not path.exists():
                return WorkspaceMemoryRecord(identity, CoordinatorMemory(), now, now, 0)
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                # Corrupt memory must never prevent opening a workspace. Keep the
                # bad file for diagnosis; start from clean cognitive state.
                return WorkspaceMemoryRecord(identity, CoordinatorMemory(), now, now, 0)

        memory = CoordinatorMemory.from_dict(raw.get("memory"))
        return WorkspaceMemoryRecord(
            identity=identity,
            memory=memory,
            first_seen=float(raw.get("first_seen") or now),
            last_seen=float(raw.get("last_seen") or now),
            write_count=int(raw.get("write_count") or 0),
        )

    def save(self, workspace, memory: CoordinatorMemory) -> WorkspaceMemoryRecord:
        """Merge with latest disk state, compact, then atomically replace JSON.

        Merge-on-save plus a small cross-process lock prevents independent chat
        sessions/backends from casually erasing each other's supported knowledge. Atomic
        ``replace`` means a crash cannot leave a half-written JSON document.
        """
        identity = self.identity_for(workspace)
        path = self._path(identity)
        now = time.time()
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass

        with _PROCESS_LOCK, _cross_process_lock(path):
            first_seen = now
            write_count = 0
            disk_memory: CoordinatorMemory | None = None
            if path.exists():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    first_seen = float(raw.get("first_seen") or now)
                    write_count = int(raw.get("write_count") or 0)
                    disk_memory = CoordinatorMemory.from_dict(raw.get("memory"))
                except Exception:
                    disk_memory = None

            # Disk may contain findings produced by another session after this
            # runtime was created. Merge when it exists; on first save preserve
            # the runtime memory verbatim instead of comparing it with a freshly
            # constructed (and therefore artificially "newer") empty memory.
            if disk_memory is None:
                merged = memory.copy()
            else:
                merged = disk_memory.copy()
                merged.merge_from(memory)
            merged.compact()
            merged.touch()

            payload: dict[str, Any] = {
                "schema_version": _SCHEMA_VERSION,
                "workspace": {
                    "key": identity.key,
                    "canonical_path": identity.canonical_path,
                    "repo_name": identity.repo_name,
                },
                "first_seen": first_seen,
                "last_seen": now,
                "write_count": write_count + 1,
                "memory": merged.to_dict(),
            }

            tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, path)

        return WorkspaceMemoryRecord(identity, merged, first_seen, now, write_count + 1)

    def delete(self, workspace) -> bool:
        """Explicit maintenance hook; never called automatically by cognition."""
        identity = self.identity_for(workspace)
        path = self._path(identity)
        with _PROCESS_LOCK:
            if not path.exists():
                return False
            path.unlink()
            return True


__all__ = ["WorkspaceIdentity", "WorkspaceMemoryRecord", "WorkspaceMemoryStore"]
