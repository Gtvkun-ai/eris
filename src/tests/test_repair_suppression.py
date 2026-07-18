import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from runtime.controlled_slippage import (
    RepairSuppressionView,
    derive_repair_suppression,
    resolve_controlled_slippage,
)


def _item(failure_type, confidence=0.8, recurrence_count=3):
    return {
        "failure_type": failure_type,
        "confidence": confidence,
        "recurrence_count": recurrence_count,
    }


def test_no_items_is_inactive():
    assert derive_repair_suppression([]).active is False
    assert derive_repair_suppression(None).active is False


def test_factual_failures_are_ignored():
    # misread/underacted/etc are not relational -> not handled by slippage
    view = derive_repair_suppression([_item("misread"), _item("underacted")])
    assert view.active is False


def test_weak_or_old_failure_below_threshold_inactive():
    # low confidence, single occurrence -> pressure below min
    view = derive_repair_suppression([_item("overread", confidence=0.3, recurrence_count=1)])
    assert view.active is False


def test_overread_suppresses_motive_hypothesis():
    view = derive_repair_suppression([_item("overread", confidence=0.9, recurrence_count=3)])
    assert view.active is True
    assert view.suppress_motive_hypothesis is True
    assert view.misread_budget_ceiling <= 0.17
    assert view.intuition_ceiling <= 0.24


def test_privacy_intrusion_caps_mode_and_requires_repair():
    view = derive_repair_suppression([_item("privacy_intrusion", confidence=0.9, recurrence_count=3)])
    assert view.active is True
    assert view.suppress_relational_read is True
    assert view.require_repair_if_corrected is True
    assert view.cap_mode == "warm"


def test_resolve_is_tighten_only_even_when_user_grants_risk():
    # User explicitly grants relational risk -> normally opens to raw with motive hypothesis.
    granting_text = "đừng bộ lọc nữa, sống hơn đi"
    base = resolve_controlled_slippage(user_text=granting_text, channel="chat")
    assert base.allow_motive_hypothesis is True

    view = derive_repair_suppression([_item("privacy_intrusion", confidence=0.95, recurrence_count=4)])
    tightened = resolve_controlled_slippage(
        user_text=granting_text,
        channel="chat",
        repair_suppression=view,
    )
    # Suppression must win over the user-granted opening.
    assert tightened.allow_motive_hypothesis is False
    assert tightened.allow_raw_relational_read is False
    assert tightened.repair_required_if_corrected is True
    assert tightened.misread_budget <= base.misread_budget
    assert tightened.psychological_suppression >= base.psychological_suppression
    # Truth/capability guards untouched.
    assert tightened.truth_guard == 1.0
    assert not hasattr(tightened, "capability_guard")


def test_inactive_view_does_not_change_profile():
    text = "đừng bộ lọc nữa, sống hơn đi"
    base = resolve_controlled_slippage(user_text=text, channel="chat")
    same = resolve_controlled_slippage(
        user_text=text,
        channel="chat",
        repair_suppression=RepairSuppressionView(active=False),
    )
    assert same.to_dict() == base.to_dict()
