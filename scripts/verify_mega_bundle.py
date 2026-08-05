#!/usr/bin/env python3
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
manifest_path = root / "release" / "MANIFEST_SHA256.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
errors = []
for entry in manifest["files"]:
    rel = entry["path"]
    path = root / rel
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
    except Exception:
        errors.append(f"unsafe path: {rel}")
        continue
    if not path.is_file():
        errors.append(f"missing: {rel}")
        continue
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    if h.hexdigest() != entry["sha256"]:
        errors.append(f"checksum mismatch: {rel}")
    if path.stat().st_size != entry["bytes"]:
        errors.append(f"size mismatch: {rel}")

if errors:
    print("VERIFY FAILED")
    for error in errors:
        print("-", error)
    sys.exit(1)
print(f"VERIFY OK: {len(manifest['files'])} files, {manifest['total_bytes']} bytes")
