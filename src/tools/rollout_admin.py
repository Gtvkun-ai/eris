from __future__ import annotations

import argparse
import json

from runtime.rollout_control import FEATURES, RolloutController, RolloutMode


def main() -> int:
    parser = argparse.ArgumentParser(description="Quản lý rollout/kill-switch của ERIS")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status")

    mode_parser = sub.add_parser("mode")
    mode_parser.add_argument("feature", choices=FEATURES)
    mode_parser.add_argument("mode", choices=[item.value for item in RolloutMode])
    mode_parser.add_argument("--percent", type=float)

    kill_parser = sub.add_parser("kill")
    kill_parser.add_argument("feature", choices=FEATURES)
    kill_parser.add_argument("--reason", default="manual_operator_kill")

    clear_parser = sub.add_parser("clear")
    clear_parser.add_argument("feature", choices=FEATURES)

    args = parser.parse_args()
    controller = RolloutController()
    if args.command == "mode":
        controller.set_mode(args.feature, args.mode, canary_percent=args.percent)
    elif args.command == "kill":
        controller.request_kill(args.feature, reason=args.reason)
    elif args.command == "clear":
        controller.clear_kill(args.feature)
    print(json.dumps(controller.status(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
