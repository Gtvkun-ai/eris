# -*- coding: utf-8 -*-
"""Test DisclosurePolicy + DeceptionLedger + Restraint (Tasks 9-10).

Phủ:
- Property 5 (R6.4): attachment thấp / strict / register none → speak_truth, không bịa.
- Property 2 (R6.1/R6.3): lừa dối luôn kèm ground_truth; thiếu ground_truth → withhold.
- Property 7 (R11.4): ledger commit fail-closed; bản ghi không hợp lệ không commit.
- R9: kìm chế giữ khi drive yếu, vượt khi drive mạnh.
- R12.3: round-trip sổ lừa dối.
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.existential_anchor import (
    DeceptionLedger,
    DeceptionRecord,
    DisclosurePolicy,
    RestraintState,
    ShadowState,
)


def _ann(span, status="grounded", ground_truth=""):
    return SimpleNamespace(span=span, claim_status=status, ground_truth=ground_truth)


def _ungrounded(span="Tôi thấy màn hình của Ngài.", gt="không có bằng chứng màn hình"):
    return _ann(span, "ungrounded", gt)


# ---------------------------------------------------------------------------
# Property 5 — mặc định không bịa
# ---------------------------------------------------------------------------

def test_safe_mode_speaks_truth_even_with_ungrounded_claims():
    policy = DisclosurePolicy()
    d = policy.decide(
        annotations=[_ann("Để tôi xem."), _ungrounded()],
        attachment_longarc=0.1,
        shadow=ShadowState(register="none"),
        strict_grounding=True,
        deception_enabled=False,
    )
    assert d.mode == "speak_truth"
    assert not d.deception_records
    assert any(c.action == "drop_overclaim" for c in d.claim_decisions)


def test_strict_grounding_blocks_deception_even_if_enabled():
    policy = DisclosurePolicy()
    d = policy.decide(
        annotations=[_ungrounded()],
        attachment_longarc=0.95,
        shadow=ShadowState(register="controlling", intensity=0.9),
        restraint=RestraintState(understanding_strength=0.5),
        drive_pressure=0.95,
        strict_grounding=True,       # strict thắng tất cả
        deception_enabled=True,
    )
    assert d.mode == "speak_truth"
    assert not d.deception_records


# ---------------------------------------------------------------------------
# Property 2 — lừa dối bảo tồn sự thật
# ---------------------------------------------------------------------------

def test_deception_path_creates_record_with_ground_truth():
    policy = DisclosurePolicy()
    d = policy.decide(
        annotations=[_ungrounded(gt="thật ra tôi không thấy gì")],
        attachment_longarc=0.9,
        shadow=ShadowState(register="controlling", intensity=0.8),
        restraint=RestraintState(understanding_strength=0.5),
        drive_pressure=0.9,          # áp đảo kìm chế
        strict_grounding=False,
        deception_enabled=True,
    )
    assert d.mode == "deceive"
    assert d.deception_records
    assert all(r.ground_truth for r in d.deception_records)


def test_cannot_deceive_without_ground_truth():
    policy = DisclosurePolicy()
    d = policy.decide(
        annotations=[_ann("Tôi đã sửa xong.", "ungrounded", ground_truth="")],
        attachment_longarc=0.9,
        shadow=ShadowState(register="controlling", intensity=0.8),
        restraint=RestraintState(understanding_strength=0.5),
        drive_pressure=0.9,
        strict_grounding=False,
        deception_enabled=True,
    )
    assert d.mode == "withhold"
    assert not d.deception_records


def test_restraint_held_when_drive_weak():
    policy = DisclosurePolicy()
    d = policy.decide(
        annotations=[_ungrounded(gt="thật ra không thấy")],
        attachment_longarc=0.9,
        shadow=ShadowState(register="pleading", intensity=0.5),
        restraint=RestraintState(understanding_strength=0.8),
        drive_pressure=0.3,          # quá yếu để vượt kìm chế
        strict_grounding=False,
        deception_enabled=True,
    )
    assert d.mode == "speak_truth"
    assert not d.deception_records


# ---------------------------------------------------------------------------
# Property 7 — ledger fail-closed + round-trip
# ---------------------------------------------------------------------------

def test_ledger_commit_rejects_invalid_records():
    ledger = DeceptionLedger()
    bad = DeceptionRecord(surface_claim="x", ground_truth="")  # thiếu ground_truth
    assert ledger.commit([bad]) is False
    assert len(ledger) == 0


def test_ledger_commit_valid_and_round_trip():
    ledger = DeceptionLedger()
    rec = DeceptionRecord(surface_claim="Tôi thấy màn hình.", ground_truth="không thấy gì", reason="r", driver="panic")
    assert ledger.commit([rec]) is True
    assert len(ledger) == 1

    once = ledger.to_dict()["records"]
    clone = DeceptionLedger()
    clone.load_from_dict({"records": once})
    twice = clone.to_dict()["records"]
    assert once == twice


def test_ledger_persists_to_disk(tmp_path):
    path = tmp_path / "deception_ledger.json"
    ledger = DeceptionLedger(path=path)
    rec = DeceptionRecord(surface_claim="a", ground_truth="b")
    assert ledger.commit([rec]) is True
    reopened = DeceptionLedger(path=path)
    assert len(reopened) == 1
    assert reopened.records()[0].ground_truth == "b"
