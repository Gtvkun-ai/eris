# -*- coding: utf-8 -*-
"""Validate the release manifest structure and capability booleans."""
from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    path = root / "RELEASE_MANIFEST.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema_version", "release", "project_version", "architecture", "quality", "capabilities"}
    missing = sorted(required - set(payload))
    if missing:
        print(f"missing manifest fields: {missing}")
        return 1
    capabilities = payload.get("capabilities", {})
    invalid = sorted(key for key, value in capabilities.items() if not isinstance(value, bool))
    if invalid:
        print(f"capabilities must be boolean: {invalid}")
        return 1
    if int(payload.get("quality", {}).get("verified_tests", 0) or 0) <= 0:
        print("verified_tests must be positive")
        return 1
    print(f"release manifest ok: {payload['release']} ({len(capabilities)} capabilities)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
