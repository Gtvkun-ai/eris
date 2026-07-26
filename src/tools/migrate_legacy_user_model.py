# -*- coding: utf-8 -*-
"""Migrate ``cortex.private_mind`` user_model cũ sang living user profile.

Migration không xóa file cũ và đưa belief legacy vào scope ``private`` dưới nhánh
``relationship.private_mind.*``. Chúng vẫn được đánh dấu ``inferred`` để không thể
ghi đè dữ kiện user đã nói rõ. Lịch sử loài người đã đủ rắc rối vì suy đoán được
nâng cấp thành sự thật, phần mềm không cần góp thêm.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cortex.private_mind.user_model import UserModelStore  # noqa: E402
from memory.living_user import LivingUserMemoryService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate UserModelStore legacy")
    parser.add_argument("--legacy", default="memory_core/user_model.json", help="File user_model.json cũ")
    parser.add_argument("--memory-dir", default="memory_core", help="Thư mục memory core đích")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ in số belief, không ghi")
    args = parser.parse_args()

    legacy_path = Path(args.legacy)
    if not legacy_path.exists():
        print(f"Không tìm thấy file legacy: {legacy_path}")
        return 2

    old_store = UserModelStore(path=legacy_path)
    beliefs = old_store.all()
    if args.dry_run:
        print(json.dumps({
            "legacy_path": str(legacy_path),
            "belief_count": len(beliefs),
            "facets": sorted({str(getattr(item, 'facet', 'general')) for item in beliefs}),
        }, ensure_ascii=False, indent=2))
        return 0

    service = LivingUserMemoryService(Path(args.memory_dir))
    result = service.import_legacy_beliefs(beliefs)
    print(json.dumps({
        "changed": result.changed,
        "migrated_records": len(result.record_ids),
        "rejected": list(result.rejected),
        "profile_version": result.version,
        "legacy_file_preserved": str(legacy_path),
    }, ensure_ascii=False, indent=2))
    return 0 if result.changed or not beliefs else 2


if __name__ == "__main__":
    raise SystemExit(main())
