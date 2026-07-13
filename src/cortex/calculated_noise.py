# -*- coding: utf-8 -*-
"""Bounded deterministic noise for timing/wording variation.

Noise is seeded per frame, capped, and never touches truth/permission. Randomness
without fences is merely a bug wearing a little hat.
"""
from __future__ import annotations

import hashlib
from typing import Any

from runtime.canonical_cognition import NoiseFrame


class CalculatedNoiseEngine:
    module_name = "calculated_noise"

    def generate(self, frame: Any) -> NoiseFrame:
        seed = hashlib.sha256(str(getattr(frame, "frame_id", "") or "").encode("utf-8")).digest()
        values = [(byte / 255.0) * 0.12 for byte in seed[:7]]
        return NoiseFrame(*values)


__all__ = ["CalculatedNoiseEngine"]
