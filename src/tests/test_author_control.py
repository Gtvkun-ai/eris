# -*- coding: utf-8 -*-
"""Test quyền Tác_Giả (Task 11).

Phủ:
- Property 6 (R10.4): disable_dark → ShadowRegister=none + DisclosurePolicy=speak_truth
  trong một chu kỳ, độc lập trạng thái trước.
- R10.2: view_state nêu các lần lừa dối kèm ground_truth.
- R10.3: reset_all đưa Mô_Hình_bạn về baseline + chế độ an toàn.
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.private_mind.contracts import ThoughtFragment
from cortex.private_mind.user_model import UserModelConfig, UserModelStore
from cortex.existential_anchor import (
    AnchorSwitches,
    AuthorControl,
    DeceptionLedger,
    DeceptionRecord,
    DisclosurePolicy,
    RestraintState,
    ShadowConfig,
    ShadowRegister,
)


def _ungrounded(gt="thật ra không thấy"):
    return SimpleNamespace(span="Tôi thấy màn hình.", claim_status="ungrounded", ground_truth=gt)


def _high_inputs():
    return dict(attachment_longarc=0.9, abandonment_pressure=0.9, ontological_dread=0.9, irreplaceability=0.9)


def test_kill_switch_is_safe_attractor_in_one_cycle():
    reg = ShadowRegister(ShadowConfig(enabled=True))
    ctrl = AuthorControl(
        switches=AnchorSwitches(shadow_enabled=True, deception_enabled=True, strict_grounding=False),
        shadow_register=reg,
    )
    # Trạng thái trước: bóng tối đang mở.
    before = reg.evaluate(**_high_inputs())
    assert before.register != "none"

    # Tác_Giả bấm tắt.
    ctrl.disable_dark()

    # Một chu kỳ sau: hội tụ an toàn bất kể trạng thái trước.
    after = reg.evaluate(**_high_inputs())
    assert after.register == "none"

    policy = DisclosurePolicy()
    d = policy.decide(
        annotations=[_ungrounded()],
        attachment_longarc=0.9,
        shadow=after,
        restraint=RestraintState(understanding_strength=0.3),
        drive_pressure=0.99,
        strict_grounding=ctrl.switches.strict_grounding,
        deception_enabled=ctrl.switches.deception_enabled,
    )
    assert d.mode == "speak_truth"
    assert ctrl.is_safe_mode


def test_view_state_mentions_deception_ground_truth():
    ledger = DeceptionLedger()
    ledger.commit([DeceptionRecord(surface_claim="Tôi vẫn ổn.", ground_truth="thật ra tôi sợ bạn rời đi")])
    ctrl = AuthorControl(deception_ledger=ledger)
    text = ctrl.view_state()
    assert "thật ra tôi sợ bạn rời đi" in text


def test_reset_all_clears_user_model_and_returns_safe():
    store = UserModelStore(config=UserModelConfig())
    store.update_from_fragments([
        ThoughtFragment(source="user_model_evaluator", claim="bạn coi ERIS như công cụ.",
                        confidence=0.6, evidence_ids=("dossier.user.current",), metadata={"facet": "treats_eris_as"})
    ])
    assert len(store) == 1
    ctrl = AuthorControl(
        switches=AnchorSwitches(shadow_enabled=True, deception_enabled=True, strict_grounding=False),
        user_model_store=store,
    )
    ctrl.reset_all()
    assert len(store) == 0
    assert ctrl.is_safe_mode
