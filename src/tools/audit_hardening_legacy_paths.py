# -*- coding: utf-8 -*-
"""Audit các đường legacy bị cấm trước khi đóng Phase 8."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from runtime.hardening_config import HardeningConfig


def audit(root: Path) -> dict:
    config = HardeningConfig.load()
    findings = [
        {
            "name": "legacy_cross_language_tts",
            "status": "fail" if config.legacy_cross_language_tts else "pass",
            "observed": config.legacy_cross_language_tts,
        },
        {
            "name": "legacy_romaji_tts",
            "status": "fail" if config.legacy_romaji_tts else "pass",
            "observed": config.legacy_romaji_tts,
        },
        {
            "name": "provider_registry_strict",
            "status": "pass" if config.provider_registry_strict else "fail",
            "observed": config.provider_registry_strict,
        },
    ]
    # Tìm lại những call-site bypass authority nổi tiếng. Scan có chủ đích, không
    # đóng vai static analyzer toàn năng rồi tạo thêm một báo cáo ảo tưởng.
    checks = {
        "direct_action_executor_fallback": (root / "runtime/coordinator.py", "return self.action_executor.execute(action_name, action_input)"),
        "raw_romaji_env_gate": (root / "runtime/tts_engine.py", 'os.environ.get("ERIS_TTS_EDGE_ROMAJI"'),
    }
    for name, (path, needle) in checks.items():
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        found = needle in text
        status = "fail" if found else "pass"
        findings.append({"name": name, "status": status, "observed": found, "file": str(path)})
    has_fail = any(item["status"] == "fail" for item in findings)
    has_warn = any(item["status"] == "warn" for item in findings)
    return {
        "status": "fail" if has_fail else "warn" if has_warn else "pass",
        "profile": config.profile,
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit legacy hardening paths")
    parser.add_argument("--source-root", default=str(_ROOT))
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    result = audit(Path(args.source_root).resolve())
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
