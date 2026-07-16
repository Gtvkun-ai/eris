# -*- coding: utf-8 -*-
"""Đóng Phase 8: stable profile, rollout enabled và release manifest có hash."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from runtime.hardening_release import HardeningReleaseBuilder, HardeningReleaseGuard, REQUIRED_STABLE_FEATURES
from runtime.rollout_control import RolloutController
from runtime.runtime_settings_store import RuntimeSettingsStore


def _apply_stable_settings(root: Path, *, fail_closed: bool) -> dict:
    settings_path = root / "settings/runtime_settings.json"
    store = RuntimeSettingsStore(settings_path)
    result = store.apply_patch({
        "hardening": {
            "profile": "stable",
            "production_validation_enabled": False,
            "provider_registry_strict": True,
            "release_guard_enabled": True,
            "release_guard_fail_closed": bool(fail_closed),
            "legacy_cross_language_tts": False,
            "legacy_romaji_tts": False,
        }
    })
    if result.rejected:
        raise RuntimeError("Settings bị reject: " + ", ".join(result.rejected))
    return result.settings


def _consolidate_rollout(root: Path) -> dict:
    state_path = root / "logs/rollout_state.json"
    controller = RolloutController(state_path=state_path)
    for feature in REQUIRED_STABLE_FEATURES:
        controller.clear_kill(feature)
        controller.set_mode(feature, "enabled", canary_percent=100.0)
    # Singing không nằm trong required stable và vẫn mặc định off. Eris không
    # cần giả hát chỉ để manifest trông nhiều tính năng hơn.
    return controller.status()


def main() -> int:
    parser = argparse.ArgumentParser(description="Đóng release hardening stable Phase 8")
    parser.add_argument("--source-root", default=str(_ROOT))
    parser.add_argument("--validation-report", required=True)
    parser.add_argument("--release-id", default="")
    parser.add_argument("--output", default="config/hardening_release.json")
    parser.add_argument("--notes", default="")
    parser.add_argument("--fail-closed", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.source_root).resolve()
    os.environ["ERIS_PROJECT_ROOT"] = str(root)
    os.environ["ERIS_RUNTIME_SETTINGS_PATH"] = str(root / "settings/runtime_settings.json")
    release_id = args.release_id.strip() or f"eris-hardening-stable-{time.strftime('%Y%m%d-%H%M%S')}"
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output

    # Builder tự từ chối report fail, thiếu 20 turn hoặc coverage chưa đủ.
    if args.dry_run:
        builder = HardeningReleaseBuilder(root)
        manifest = builder.build(
            release_id=release_id,
            validation_report=args.validation_report,
            notes=args.notes,
        )
        print(json.dumps({"dry_run": True, "manifest": manifest.to_dict()}, ensure_ascii=False, indent=2))
        return 0

    settings = _apply_stable_settings(root, fail_closed=args.fail_closed)
    from runtime.runtime_settings_store import reset_runtime_settings_store_for_tests
    reset_runtime_settings_store_for_tests()
    rollout = _consolidate_rollout(root)
    manifest = HardeningReleaseBuilder(root).build(
        release_id=release_id,
        validation_report=args.validation_report,
        notes=args.notes,
    )
    manifest.save(output)

    # Guard đọc settings vừa chốt, không dựa vào cache process cũ.
    from runtime.hardening_config import HardeningConfig
    guard = HardeningReleaseGuard(
        source_root=root,
        manifest_path=output,
        config=HardeningConfig.load(),
    ).verify()
    payload = {
        "release_id": manifest.release_id,
        "manifest": str(output),
        "guard": guard.to_dict(),
        "settings_profile": settings.get("hardening", {}).get("profile", ""),
        "rollout_features": list(rollout.get("features", {}).keys()),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if guard.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
