# -*- coding: utf-8 -*-
"""Tests cho Nước 3(c) — đường surface không-anchor có-cổng.

Cho phép một bận tâm nội tâm áp lực CAO nổi lên public dù thiếu anchor ngoài, khi
cờ ERIS_INTERIOR_SURFACE_NONANCHORED bật. Mặc định TẮT → hành vi cũ (body_only).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cortex.private_mind.surface_valve import SurfaceValve
from cortex.private_mind.contracts import SurfaceCandidate


def _valve():
    return SurfaceValve()


def _judgment(pressure=0.9, source="gemini"):
    return SimpleNamespace(pressure=pressure, source=source)


def _candidate(**meta):
    base = {
        "novelty": 0.6,
        "repetition": 0.1,
        "evidence_strength": 0.1,  # thấp -> path anchor thường KHÔNG mở
        "semantic_family": "self_reflection",
    }
    base.update(meta)
    return SurfaceCandidate(
        kind="private_mind_surface",
        topic_seed="một bận tâm nội tâm tôi đã giữ lâu",
        usefulness=0.7,
        confidence=0.7,
        interrupt_cost=0.2,
        metadata=base,
    )


# ---------------------------------------------------------------------------
# Helper trực tiếp
# ---------------------------------------------------------------------------
def test_helper_off_by_default(monkeypatch):
    monkeypatch.delenv("ERIS_INTERIOR_SURFACE_NONANCHORED", raising=False)
    v = _valve()
    assert v._interior_nonanchored_allowed(
        judgment=_judgment(0.95), novelty=0.6, repetition=0.1,
        semantic_family="self_reflection", api_degraded=False,
        semantic_family_recently_used=False,
    ) is False


def test_helper_on_high_pressure(monkeypatch):
    monkeypatch.setenv("ERIS_INTERIOR_SURFACE_NONANCHORED", "1")
    v = _valve()
    assert v._interior_nonanchored_allowed(
        judgment=_judgment(0.95), novelty=0.6, repetition=0.1,
        semantic_family="self_reflection", api_degraded=False,
        semantic_family_recently_used=False,
    ) is True


def test_helper_rejects_low_pressure(monkeypatch):
    monkeypatch.setenv("ERIS_INTERIOR_SURFACE_NONANCHORED", "1")
    v = _valve()
    assert v._interior_nonanchored_allowed(
        judgment=_judgment(0.5), novelty=0.6, repetition=0.1,
        semantic_family="self_reflection", api_degraded=False,
        semantic_family_recently_used=False,
    ) is False


def test_helper_rejects_filler_and_degraded(monkeypatch):
    monkeypatch.setenv("ERIS_INTERIOR_SURFACE_NONANCHORED", "1")
    v = _valve()
    assert v._interior_nonanchored_allowed(
        judgment=_judgment(0.95), novelty=0.6, repetition=0.1,
        semantic_family="private_mind_continuity_filler", api_degraded=False,
        semantic_family_recently_used=False,
    ) is False
    assert v._interior_nonanchored_allowed(
        judgment=_judgment(0.95), novelty=0.6, repetition=0.1,
        semantic_family="self_reflection", api_degraded=True,
        semantic_family_recently_used=False,
    ) is False


# ---------------------------------------------------------------------------
# Integration qua _apply_public_surface_gate
# ---------------------------------------------------------------------------
def test_gate_body_only_when_off(monkeypatch):
    monkeypatch.delenv("ERIS_INTERIOR_SURFACE_NONANCHORED", raising=False)
    v = _valve()
    out = v._apply_public_surface_gate(_candidate(), judgment=_judgment(0.95))
    # không anchor + tắt cờ -> không public, rớt body_only
    assert out is not None
    assert out.channel == "body_only"
    assert not out.metadata.get("interior_nonanchored_surface")


def test_gate_public_nonanchored_when_on(monkeypatch):
    monkeypatch.setenv("ERIS_INTERIOR_SURFACE_NONANCHORED", "1")
    v = _valve()
    out = v._apply_public_surface_gate(_candidate(), judgment=_judgment(0.95))
    assert out is not None
    assert out.channel != "body_only"
    assert out.metadata.get("interior_nonanchored_surface") is True
    assert out.metadata.get("public_surface_allowed") is True
