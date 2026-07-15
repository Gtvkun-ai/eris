# -*- coding: utf-8 -*-
"""Tests cho Nước 3 (a)+(b) — cắm ToM pipeline vào response path.

Crux: chứng minh hợp đồng đọc ĐÚNG (PHASE2_DOWNSTREAM_CONTRACT) làm các read vốn
bị từ chối nay chạy được — tức "dây không dẫn điện" giờ dẫn. Phủ thêm flag gating,
non-mutating contract override, và extract workspace.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cortex import tom_advisor as ta
from cortex.global_workspace import WorkspaceFrame, WorkspaceItem
from cortex.meaning import Phase2MeaningPipeline


# Hợp đồng SAI kiểu cũ (giống _build_downstream_contract của engine): WorldSceneBuilder
# KHÔNG được cấp broadcast_items -> read bị guard -> scene rỗng.
_WRONG_CONTRACT = {
    "WorldSceneBuilder": ["selected_evidence", "selected_body_state", "dominant_thread"],
}


def _frame(contract):
    item = WorkspaceItem(
        id="item-1",
        kind="user_request",
        content="can you help me with this?",
        summary="can you help me with this?",
        priority=0.8,
        confidence=0.8,
        evidence_ids=["ev-1"],
    )
    return WorkspaceFrame(
        frame_id="frame-1",
        timestamp=0.0,
        budget_mode="normal",
        broadcast_items=[item],
        active_threads=["thread-1"],
        dominant_thread="thread-1",
        broadcast_reason="test",
        forbidden_assumptions=[],
        downstream_contract={k: list(v) for k, v in contract.items()},
    )


def _world_scene_missing(result):
    for sd in result.debug.get("stage_debugs", []):
        if getattr(sd, "stage", "") == "WorldSceneBuilder":
            return list(getattr(sd, "missing_fields", []) or [])
    return None


# ---------------------------------------------------------------------------
# Flag gating
# ---------------------------------------------------------------------------
def test_advisor_flag_default_off(monkeypatch):
    monkeypatch.delenv("ERIS_TOM_ADVISOR", raising=False)
    assert ta.tom_advisor_enabled() is False
    # advise() phải trả "" khi tắt, kể cả có workspace hợp lệ
    assert ta.advise(_frame(_WRONG_CONTRACT)) == ""


def test_advisor_flag_on(monkeypatch):
    monkeypatch.setenv("ERIS_TOM_ADVISOR", "1")
    assert ta.tom_advisor_enabled() is True


def test_real_embeddings_off_returns_none(monkeypatch):
    monkeypatch.delenv("ERIS_MEANING_REAL_EMBEDDINGS", raising=False)
    assert ta.build_real_semantic_engine() is None


# ---------------------------------------------------------------------------
# Contract override — non-mutating + đúng field
# ---------------------------------------------------------------------------
def test_contract_override_is_correct_and_nonmutating():
    original = _frame(_WRONG_CONTRACT)
    fixed = ta._frame_with_phase2_contract(original)
    # frame gốc KHÔNG bị đổi
    assert original.downstream_contract == {k: list(v) for k, v in _WRONG_CONTRACT.items()}
    # frame mới mang hợp đồng Phase 2 đúng
    assert "broadcast_items" in fixed.downstream_contract["WorldSceneBuilder"]
    assert "active_threads" in fixed.downstream_contract["WorldSceneBuilder"]
    # dữ liệu nội dung được giữ
    assert fixed.broadcast_items == original.broadcast_items
    assert fixed.frame_id == original.frame_id


# ---------------------------------------------------------------------------
# Extract workspace
# ---------------------------------------------------------------------------
def test_extract_workspace_passthrough():
    ws = _frame(_WRONG_CONTRACT)
    assert ta._extract_workspace(ws) is ws


def test_extract_workspace_from_cognitive_frame():
    ws = _frame(_WRONG_CONTRACT)
    cog = SimpleNamespace(workspace=ws)
    assert ta._extract_workspace(cog) is ws


def test_extract_workspace_none_for_junk():
    assert ta._extract_workspace(SimpleNamespace(foo="bar")) is None
    assert ta._extract_workspace(None) is None


# ---------------------------------------------------------------------------
# CRUX — hợp đồng đúng làm read vốn bị chặn nay chạy
# ---------------------------------------------------------------------------
def test_wrong_contract_denies_world_scene_read():
    # Với hợp đồng sai, WorldSceneBuilder không đọc được broadcast_items -> missing.
    result = Phase2MeaningPipeline().run(_frame(_WRONG_CONTRACT))
    missing = _world_scene_missing(result)
    assert missing is not None
    assert "broadcast_items" in missing


def test_correct_contract_conducts():
    # Với hợp đồng Phase 2 đúng (do advisor áp), broadcast_items đọc được -> KHÔNG missing.
    fixed = ta._frame_with_phase2_contract(_frame(_WRONG_CONTRACT))
    result = Phase2MeaningPipeline().run(fixed)
    missing = _world_scene_missing(result)
    assert missing is not None
    assert "broadcast_items" not in missing


def test_advise_from_workspace_runs_without_error():
    # Không khẳng định có read cụ thể (phụ thuộc nội dung), chỉ cần không vỡ và trả str.
    out = ta.advise_from_workspace(_frame(_WRONG_CONTRACT))
    assert isinstance(out, str)
