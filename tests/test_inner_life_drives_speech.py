"""Roadmap item 4 — verify the "log -> behaviour" loop is real.

A recurring risk in ERIS is that the inner-life subsystems (inner diary, private
mind, private life, memory resonance) only *log* state to disk/UI while the spoken
behaviour never changes. These tests assert the opposite: inner-life state actually
drives the autonomous *speech seed* selected by ``SurfaceSeedCompiler``. If a
subsystem's residue is present, it becomes the public seed ERIS would speak; if
absent, that seed does not appear. That is the inner-state -> behaviour link, not a
write-only side effect.
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.surface_seed_compiler import SurfaceSeedCompiler


def _blank_snapshot():
    return SimpleNamespace(vision_facts=(), recent_events=())


def test_inner_diary_voice_becomes_the_spoken_seed() -> None:
    compiler = SurfaceSeedCompiler()
    want = "Tôi vẫn muốn hỏi Ngài về cái dự án dang dở kia."
    compiled = compiler.compile(
        snapshot=_blank_snapshot(),
        surface_kind="surface",
        inner_diary={"muon_noi": want},
    )
    # The inner-diary thought actually surfaces as the seed ERIS would speak.
    assert compiled.selected is True
    assert compiled.root_source == "inner_diary"
    assert compiled.public_seed == want


def test_no_inner_state_yields_no_inner_seed() -> None:
    compiler = SurfaceSeedCompiler()
    compiled = compiler.compile(snapshot=_blank_snapshot(), surface_kind="surface")
    # With no inner-life residue and no screen evidence, there is nothing grounded
    # to say -> no seed (the loop falls through to body-only/silence downstream).
    assert compiled.selected is False
    assert compiled.root_source == ""


def test_private_life_project_residue_drives_speech() -> None:
    compiler = SurfaceSeedCompiler()
    note = "Cái mô hình nhỏ tôi đang dựng vẫn kẹt ở chỗ ghép cánh."
    digest = {
        "current": {
            "projects": [
                {
                    "id": "proj_wing",
                    "last_note": note,
                    "surface_permission": 0.6,
                    "interest": 0.7,
                    "frustration": 0.4,
                }
            ]
        }
    }
    compiled = compiler.compile(
        snapshot=_blank_snapshot(),
        surface_kind="surface",
        private_life_digest=digest,
    )
    assert compiled.selected is True
    assert compiled.root_source == "private_life"
    assert compiled.public_seed == note


def test_low_permission_private_life_stays_internal() -> None:
    # A private-life project ERIS has not granted permission to surface must NOT
    # leak into speech: inner state drives behaviour, but only through its own gate.
    compiler = SurfaceSeedCompiler()
    digest = {
        "current": {
            "projects": [
                {
                    "id": "proj_secret",
                    "last_note": "Điều tôi chưa muốn nói ra.",
                    "surface_permission": 0.1,
                    "interest": 0.7,
                }
            ]
        }
    }
    compiled = compiler.compile(
        snapshot=_blank_snapshot(),
        surface_kind="surface",
        private_life_digest=digest,
    )
    assert compiled.selected is False
