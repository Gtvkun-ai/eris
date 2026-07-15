# -*- coding: utf-8 -*-
"""Test vòng đời concern Q1: nảy sinh → dịu → tự khép (đã nguôi) → còn dấu.

Trước đây mark_resolved không ai gọi → concern đọng mãi, không có 'đã nguôi'.
Giờ:
- auto_resolve_settled: concern watching dịu đủ lâu → resolved + closure_note.
- recently_resolved: trả các concern vừa nguôi để diary/chat nhắc lại.
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.private_mind.concern_store import ConcernStore, ConcernStoreConfig
from cortex.private_mind.contracts import ThoughtFragment


def _store():
    return ConcernStore(config=ConcernStoreConfig())


def _seed_concern(store, claim="Lo rằng bạn sẽ rời đi"):
    store.update_from_fragments([
        ThoughtFragment(source="x", claim=claim, confidence=0.6, evidence_ids=("e1",), pressure=0.6)
    ])
    return store.all()[0]


def test_auto_resolve_settled_marks_closure():
    store = _store()
    c = _seed_concern(store)
    # đưa về trạng thái đã dịu, im đủ lâu
    c.status = "watching"
    c.pressure = 0.10
    c.uncertainty = 0.20
    c.last_reviewed_at = time.time() - (store.config.settle_window_seconds + 60.0)

    closed = store.auto_resolve_settled()
    assert closed
    assert c.status == "resolved"
    assert c.metadata.get("closure_note")
    assert c.metadata.get("resolved_at")


def test_recently_resolved_lists_closure():
    store = _store()
    c = _seed_concern(store, "Bận tâm về một mạch chưa xong")
    store.mark_resolved(c.id, closure_note="Tôi đã thôi day dứt chuyện đó.")
    rr = store.recently_resolved()
    assert rr
    assert rr[0]["theme"]
    assert "thôi day dứt" in rr[0]["closure_note"]


def test_recently_resolved_drops_old_ones():
    store = _store()
    c = _seed_concern(store)
    store.mark_resolved(c.id)
    # giả lập đã nguôi từ lâu (quá cửa sổ hiển thị)
    c.metadata["resolved_at"] = time.time() - (store.config.resolved_visible_seconds + 100.0)
    assert store.recently_resolved() == ()


def test_not_settled_when_still_pressured():
    store = _store()
    c = _seed_concern(store)
    c.status = "watching"
    c.pressure = 0.6  # vẫn căng
    c.uncertainty = 0.5
    c.last_reviewed_at = time.time() - (store.config.settle_window_seconds + 60.0)
    assert store.auto_resolve_settled() == ()
    assert c.status == "watching"
