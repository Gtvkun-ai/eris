# -*- coding: utf-8 -*-
"""Đọc, giải thích, sửa và xóa living user memory từ dòng lệnh.

Ví dụ::

    python tools/inspect_living_user_memory.py --memory-dir memory_core summary
    python tools/inspect_living_user_memory.py --memory-dir memory_core explain user.name
    python tools/inspect_living_user_memory.py --memory-dir memory_core correct user.name Khang
    python tools/inspect_living_user_memory.py --memory-dir memory_core forget user.name

Tool chỉ thao tác trên profile projection. ``forget --hard`` xóa record khỏi profile,
version history và audit của living-user store; nó không giả vờ xóa raw chat/event
ledger ở các store khác. Xóa thật trên toàn hệ thống cần retention workflow riêng.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory.living_user import LivingUserMemoryService  # noqa: E402


def _json_value(raw: str) -> Any:
    """Cho phép truyền số/list/object; chuỗi thường vẫn giữ nguyên."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Quản lý living user memory của ERIS")
    parser.add_argument(
        "--memory-dir",
        default="memory_core",
        help="Thư mục memory core, mặc định: memory_core",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    summary = sub.add_parser("summary", help="In bản tổng hợp dễ đọc")
    summary.add_argument("--include-inferred", action="store_true", help="Hiện cả suy luận thận trọng")
    summary.add_argument("--include-sensitive", action="store_true", help="Hiện mục private/sensitive")
    summary.add_argument("--limit", type=int, default=36)

    export = sub.add_parser("json", help="In snapshot JSON để audit")
    export.add_argument("--include-sensitive", action="store_true")
    export.add_argument("--limit", type=int, default=120)

    explain = sub.add_parser("explain", help="Giải thích một profile path và evidence")
    explain.add_argument("path")
    explain.add_argument("--project-id", default="")

    correct = sub.add_parser("correct", help="Sửa một giá trị bằng lời xác nhận explicit")
    correct.add_argument("path")
    correct.add_argument("value", help="Chuỗi hoặc JSON value")
    correct.add_argument("--project-id", default="")
    correct.add_argument("--evidence-id", default="", help="ID evidence; để trống sẽ tạo manual timestamp")

    forget = sub.add_parser("forget", help="Quên một path hoặc cả prefix")
    forget.add_argument("path_or_prefix")
    forget.add_argument("--project-id", default="")
    forget.add_argument(
        "--hard",
        action="store_true",
        help="Xóa khỏi profile + history/audit/trace của living-user store",
    )

    work = sub.add_parser("work", help="In goals, commitments và workflow đang hoạt động")
    work.add_argument("--query", default="")
    work.add_argument("--project-id", default="")
    work.add_argument("--session-id", default="")

    add_goal = sub.add_parser("add-goal", help="Thêm mục tiêu explicit")
    add_goal.add_argument("title")
    add_goal.add_argument("--description", default="")
    add_goal.add_argument("--next-action", action="append", default=[])
    add_goal.add_argument("--project-id", default="")
    add_goal.add_argument("--evidence-id", default="")

    add_workflow = sub.add_parser("add-workflow", help="Thêm procedural workflow explicit")
    add_workflow.add_argument("trigger")
    add_workflow.add_argument("steps", nargs="+")
    add_workflow.add_argument("--project-id", default="")
    add_workflow.add_argument("--evidence-id", default="")

    replay = sub.add_parser("replay", help="Tổng hợp trace pipeline gần đây")
    replay.add_argument("--limit", type=int, default=500)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    service = LivingUserMemoryService(Path(args.memory_dir))

    if args.command == "summary":
        print(service.render_summary(
            include_inferred=bool(args.include_inferred),
            include_sensitive=bool(args.include_sensitive),
            limit=max(0, int(args.limit)),
        ))
        return 0

    if args.command == "json":
        payload = service.summary(
            include_sensitive=bool(args.include_sensitive),
            limit=max(0, int(args.limit)),
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "explain":
        explanations = service.explain(args.path, project_id=args.project_id)
        if not explanations:
            print("Không tìm thấy memory đang hoạt động cho path này.")
            return 2
        print(json.dumps([item.to_dict() for item in explanations], ensure_ascii=False, indent=2))
        return 0

    if args.command == "correct":
        evidence_id = args.evidence_id or f"manual_correction_{int(time.time())}"
        result = service.correct(
            args.path,
            _json_value(args.value),
            evidence_ids=(evidence_id,),
            project_id=args.project_id,
        )
        print(json.dumps({
            "changed": result.changed,
            "record_ids": list(result.record_ids),
            "rejected": list(result.rejected),
            "version": result.version,
        }, ensure_ascii=False, indent=2))
        return 0 if result.changed else 2

    if args.command == "forget":
        count = service.forget(
            args.path_or_prefix,
            project_id=args.project_id,
            hard=bool(args.hard),
        )
        print(f"Đã {'xóa cứng' if args.hard else 'đánh dấu quên'} {count} record.")
        return 0 if count else 2

    if args.command == "work":
        context = service.active_work(
            args.query, project_id=args.project_id, session_id=args.session_id,
        )
        print(json.dumps({
            "goals": [x.to_dict() for x in context.goals],
            "commitments": [x.to_dict() for x in context.commitments],
            "workflows": [x.to_dict() for x in context.workflows],
        }, ensure_ascii=False, indent=2))
        return 0

    if args.command == "add-goal":
        evidence_id = args.evidence_id or f"manual_goal_{int(time.time())}"
        goal = service.add_goal(
            args.title, description=args.description, next_actions=args.next_action,
            evidence_ids=(evidence_id,), project_id=args.project_id,
        )
        print(json.dumps(goal.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "add-workflow":
        evidence_id = args.evidence_id or f"manual_workflow_{int(time.time())}"
        workflow = service.add_workflow(
            args.trigger, args.steps, evidence_ids=(evidence_id,), project_id=args.project_id,
        )
        print(json.dumps(workflow.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "replay":
        print(json.dumps(service.replay_report(limit=max(1, args.limit)).to_dict(), ensure_ascii=False, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
