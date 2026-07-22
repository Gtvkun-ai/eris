# -*- coding: utf-8 -*-
"""Cấu hình nhỏ, không lôi toàn bộ settings cognition vào renderer."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"", "0", "false", "off", "no", "none"}


@dataclass(frozen=True, slots=True)
class Live2DBodyConfig:
    model_path: Path
    listen_host: str = "127.0.0.1"
    listen_port: int = 4252
    backend_host: str = "127.0.0.1"
    backend_port: int = 4243
    body_host: str = "127.0.0.1"
    body_port: int = 4242
    width: int = 520
    height: int = 900
    scale: float = 1.0
    offset_x: float = 0.0
    offset_y: float = -0.02
    transparent: bool = True
    topmost: bool = True
    decorated: bool = False
    x: int | None = None
    y: int | None = None

    @classmethod
    def from_env(cls, *, root: Path | None = None) -> "Live2DBodyConfig":
        project_root = root or Path(__file__).resolve().parents[1]
        default_model = project_root / "assets" / "live2d" / "infj" / "infj.model3.json"
        model_path = Path(os.getenv("ERIS_LIVE2D_MODEL", str(default_model))).expanduser()
        return cls(
            model_path=model_path,
            listen_host=os.getenv("ERIS_LIVE2D_HOST", "127.0.0.1").strip() or "127.0.0.1",
            listen_port=max(1, min(65535, _int_env("ERIS_LIVE2D_PORT", 4252))),
            backend_host=os.getenv("ERIS_LIVE2D_BACKEND_HOST", "127.0.0.1").strip() or "127.0.0.1",
            backend_port=max(1, min(65535, _int_env("ERIS_LIVE2D_BACKEND_PORT", 4243))),
            body_host=os.getenv("ERIS_LIVE2D_BODY_HOST", "127.0.0.1").strip() or "127.0.0.1",
            body_port=max(1, min(65535, _int_env("ERIS_LIVE2D_BODY_PORT", 4242))),
            width=max(320, _int_env("ERIS_LIVE2D_WIDTH", 520)),
            height=max(480, _int_env("ERIS_LIVE2D_HEIGHT", 900)),
            scale=max(0.2, min(3.0, _float_env("ERIS_LIVE2D_SCALE", 1.0))),
            offset_x=max(-2.0, min(2.0, _float_env("ERIS_LIVE2D_OFFSET_X", 0.0))),
            offset_y=max(-2.0, min(2.0, _float_env("ERIS_LIVE2D_OFFSET_Y", -0.02))),
            transparent=_bool_env("ERIS_LIVE2D_TRANSPARENT", True),
            topmost=_bool_env("ERIS_LIVE2D_TOPMOST", True),
            decorated=_bool_env("ERIS_LIVE2D_DECORATED", False),
            x=_int_env("ERIS_LIVE2D_X", -1) if _int_env("ERIS_LIVE2D_X", -1) >= 0 else None,
            y=_int_env("ERIS_LIVE2D_Y", -1) if _int_env("ERIS_LIVE2D_Y", -1) >= 0 else None,
        )
