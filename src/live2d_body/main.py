# -*- coding: utf-8 -*-
"""Entry point: ``python -m live2d_body.main``."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from .config import Live2DBodyConfig
from .renderer import Live2DDependencyError, run_renderer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Eris Live2D body")
    parser.add_argument("--model", type=Path, help="Đường dẫn *.model3.json")
    parser.add_argument("--port", type=int, help="UDP stage mirror port, mặc định 4252")
    parser.add_argument("--decorated", action="store_true", help="Hiện title bar để debug")
    parser.add_argument("--not-topmost", action="store_true", help="Không ghim cửa sổ lên trên")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = Live2DBodyConfig.from_env()
    if args.model is not None:
        config = replace(config, model_path=args.model)
    if args.port is not None:
        config = replace(config, listen_port=max(1, min(65535, args.port)))
    if args.decorated:
        config = replace(config, decorated=True)
    if args.not_topmost:
        config = replace(config, topmost=False)
    try:
        run_renderer(config)
    except KeyboardInterrupt:
        return 0
    except (Live2DDependencyError, FileNotFoundError, RuntimeError, OSError) as exc:
        print(f"[Live2D][ERROR] {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
