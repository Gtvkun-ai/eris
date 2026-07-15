# -*- coding: utf-8 -*-
"""Smoke-test end-to-end cho Nước 3(a) — advisory chảy từ CognitiveFrame tới prompt.

Không cần mạng/model. Chứng minh:
  1. `_render_advisory` rút đúng dòng `tom_read` từ một MentalStateInference surfaced.
  2. Method THẬT `_build_appraisal_context` (FrameBuilderMixin) chèn dòng tom_read
     vào context prompt khi advise trả non-empty.
  3. Tắt cờ → context y hệt render gốc (không advisory) — đường mặc định bất biến.
  4. `advise()` chạy pipeline THẬT trên một CognitiveFrame có workspace slot mà
     không vỡ, và bị gate đúng theo cờ.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cortex import tom_advisor as ta
from cortex.appraisal import AppraisalEngine
from cortex.contracts import CognitiveAppraisal
from cortex.global_workspace import WorkspaceFrame, WorkspaceItem
from runtime.frame_builder import FrameBuilderMixin


# ---------------------------------------------------------------------------
# Harness dùng METHOD THẬT trên FrameBuilderMixin
# ---------------------------------------------------------------------------
class _Harness(FrameBuilderMixin):
    pass


def _harness():
    h = _Harness()
    h.appraisal_engine = AppraisalEngine()
    return h


def _appraisal():
    return CognitiveAppraisal(stance="tender_under_cold", valence=-0.2, tenderness=0.4)


def _workspace_frame():
    item = WorkspaceItem(
        id="item-1",
        kind="user_request",
        content="sao bạn im lặng vậy",
        summary="sao bạn im lặng vậy",
        priority=0.8,
        confidence=0.8,
        evidence_ids=["ev-1"],
    )
    return WorkspaceFrame(
        frame_id="frame-e2e",
        timestamp=0.0,
        budget_mode="normal",
        broadcast_items=[item],
        active_threads=["t1"],
        dominant_thread="t1",
        broadcast_reason="e2e",
        forbidden_assumptions=[],
        downstream_contract={},  # cố ý rỗng: advisor tự áp hợp đồng Phase 2 đúng
    )


def _cog_frame_with_workspace():
    """CognitiveFrame giả: chỉ cần slot ``workspace`` để advisor rút ra."""
    return SimpleNamespace(workspace=_workspace_frame())


# ---------------------------------------------------------------------------
# 1. Extraction
# ---------------------------------------------------------------------------
def test_render_advisory_from_surfaced_mental_state():
    result = SimpleNamespace(
        surfaced=[
            SimpleNamespace(kind="meaning", confidence=0.9, conclusion=SimpleNamespace(category="joke")),
            SimpleNamespace(kind="mental_state", confidence=0.72, conclusion=SimpleNamespace(category="frustrated")),
        ]
    )
    line = ta._render_advisory(result)
    assert line.startswith("tom_read:")
    assert "bực" in line  # frustrated -> "đang bực/khó chịu"
    assert "0.72" in line


def test_render_advisory_empty_when_no_mental_state():
    result = SimpleNamespace(
        surfaced=[SimpleNamespace(kind="meaning", confidence=0.9, conclusion=SimpleNamespace(category="joke"))]
    )
    assert ta._render_advisory(result) == ""


# ---------------------------------------------------------------------------
# 2+3. Method THẬT _build_appraisal_context chèn advisory vào prompt context
# ---------------------------------------------------------------------------
def test_appraisal_context_appends_tom_read(monkeypatch):
    # Cô lập bước chèn: ép advise trả một dòng cố định (extraction đã test riêng).
    monkeypatch.setattr(ta, "advise", lambda frame: "tom_read: bạn có thể đang bực (độ tin ~0.70).")
    h = _harness()
    ctx = h._build_appraisal_context(_appraisal(), frame=object())
    assert "appraisal_stance:" in ctx           # context gốc còn nguyên
    assert "tom_read: bạn có thể đang bực" in ctx  # advisory đã chảy vào prompt


def test_appraisal_context_unchanged_without_frame(monkeypatch):
    # Không có frame -> không advisory, dù advise có trả gì.
    monkeypatch.setattr(ta, "advise", lambda frame: "tom_read: KHÔNG NÊN XUẤT HIỆN")
    h = _harness()
    ctx = h._build_appraisal_context(_appraisal(), frame=None)
    base = AppraisalEngine().render_prompt_context(_appraisal())
    assert ctx == base
    assert "tom_read" not in ctx


# ---------------------------------------------------------------------------
# 4. advise() chạy pipeline THẬT trên CognitiveFrame, gate theo cờ
# ---------------------------------------------------------------------------
def test_advise_off_by_default(monkeypatch):
    monkeypatch.delenv("ERIS_TOM_ADVISOR", raising=False)
    assert ta.advise(_cog_frame_with_workspace()) == ""


def test_advise_runs_real_pipeline_when_on(monkeypatch):
    monkeypatch.setenv("ERIS_TOM_ADVISOR", "1")
    # Pipeline Phase 2 chạy thật trên workspace (hợp đồng đúng do advisor áp);
    # không khẳng định có read cụ thể (phụ thuộc encoder fallback), chỉ cần KHÔNG vỡ
    # và trả str. Đây là bằng chứng đường dẫn end-to-end không ném.
    out = ta.advise(_cog_frame_with_workspace())
    assert isinstance(out, str)


def test_full_chain_appraisal_to_prompt_with_real_advise(monkeypatch):
    """Chuỗi đầy đủ: cog_frame -> _build_appraisal_context THẬT -> advise THẬT.

    Khẳng định không vỡ và context gốc luôn có mặt; nếu pipeline có surface một
    mental_state thì dòng tom_read xuất hiện (không bắt buộc, tránh phụ thuộc model).
    """
    monkeypatch.setenv("ERIS_TOM_ADVISOR", "1")
    h = _harness()
    cog = _cog_frame_with_workspace()
    ctx = h._build_appraisal_context(_appraisal(), frame=cog)
    assert "appraisal_axes:" in ctx
    if "tom_read:" in ctx:
        assert "độ tin ~" in ctx
