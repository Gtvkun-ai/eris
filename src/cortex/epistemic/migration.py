from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any


LEGACY_FILES = ("user_model.json", "private_concerns.json", "inner_diary.json")


def archive_v1_cognition(base_dir: str | os.PathLike[str] = "memory_core") -> dict[str, Any]:
    """Copy V1 cognition state once, without importing it into V2.

    The live V1 files are left untouched because older runtime paths may still
    need to read them during shadow rollout.  The archive is marked read-only
    and a manifest records that V2 started from an empty epistemic state.
    """

    root = Path(base_dir)
    archive = root / "legacy_v1_archive"
    manifest_path = archive / "manifest.json"
    if manifest_path.exists():
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return {"status": "existing_archive_unreadable", "archive": str(archive)}

    archive.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in LEGACY_FILES:
        source = root / name
        if not source.exists():
            continue
        target = archive / name
        shutil.copy2(source, target)
        try:
            target.chmod(0o444)
        except OSError:
            pass
        copied.append(name)

    manifest = {
        "schema_version": 1,
        "archived_at": time.time(),
        "source": str(root.resolve()),
        "files": copied,
        "read_only": True,
        "imported_into_v2": False,
        "v2_initial_state": "empty",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        manifest_path.chmod(0o444)
    except OSError:
        pass
    return manifest
