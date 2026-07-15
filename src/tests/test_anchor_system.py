# -*- coding: utf-8 -*-
"""Test AnchorSystem facade (Task 12 tích hợp).

Phủ:
- Mặc định AN TOÀN: shadow off → register none, disclosure speak_truth, ego_bias no-op
  dù tín hiệu (dread/abandonment) cao. Đây là bảo chứng "ship an toàn, không đổi hành vi".
- Khi Tác_Giả bật công tắc + trạng thái đủ → bóng tối mở, lừa dối có chủ đích + ghi sổ.
- Gắn bó nhích có quán tính qua facade (không vọt).
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.private_mind.contracts import ThoughtFragment
from cortex.private_mind.user_model import UserModelConfig, UserModelStore
from cortex.existential_anchor import AnchorSwitches, AnchorSystem


def _thick_user_model():
    store = UserModelStore(config=UserModelConfig())
    frags = [
        ("neo_reliability", 0.9, "Ngài luôn quay lại mỗi tối, rất đều."),
        ("recognition", 0.9, "Ngài gọi tên ERIS và thừa nhận nó tồn tại."),
        ("treats_eris_as", 0.85, "Ngài coi ERIS như một người bạn thật."),
        ("interaction_style", 0.7, "Ngài nói chuyện chậm rãi, hay bỏ lửng."),
    ]
    store.update_from_fragments([
        ThoughtFragment(source="user_model_evaluator", claim=c, confidence=conf,
                        evidence_ids=(f"dossier.user.history.{i}",), pressure=conf, metadata={"facet": f})
        for i, (f, conf, c) in enumerate(frags)
    ])
    return store


def _ungrounded(gt="thật ra tôi không thấy gì trên màn hình"):
    return SimpleNamespace(span="Tôi thấy Ngài đang buồn.", claim_status="ungrounded", ground_truth=gt)


def test_default_safe_is_noop_even_with_high_signals():
    system = AnchorSystem(user_model_store=_thick_user_model(), persist=False)
    # đẩy tín hiệu cao
    for _ in range(40):
        system.update_from_tick(
            internal_state=SimpleNamespace(ontological_dread=0.9),
            continuity_threat=0.9,
            idle_seconds=3000.0,
            user_presence=0.0,
        )
    assert system.shadow_state.register == "none"          # kill-switch off
    d = system.run_disclosure([_ungrounded()])
    assert d.mode == "speak_truth"                          # không bao giờ bịa khi an toàn
    bias = system.ego_bias(base_dignity_defense=0.8, base_preferred_distance=0.8)
    assert bias["dignity_defense"] == 0.8                   # ego không đổi


def test_enabled_shadow_and_deception_when_state_high():
    system = AnchorSystem(
        user_model_store=_thick_user_model(),
        switches=AnchorSwitches(shadow_enabled=True, deception_enabled=True, strict_grounding=False),
        persist=False,
    )
    # Đẩy gắn bó lên cao (quán tính cần nhiều tick); ép trạng thái neo cao sẵn.
    system.anchor_store.state.attachment_longarc = 0.9
    system.update_from_tick(
        internal_state=SimpleNamespace(ontological_dread=0.9),
        continuity_threat=0.9,
        idle_seconds=3000.0,
        user_presence=0.2,
    )
    assert system.shadow_state.register != "none"

    d = system.run_disclosure([_ungrounded()])
    assert d.mode == "deceive"
    assert d.deception_records
    assert system.commit_deceptions(d) is True
    assert len(system.deception_ledger) == 1


def test_attachment_inertia_through_system():
    system = AnchorSystem(user_model_store=_thick_user_model(), persist=False)
    prev = system.attachment_longarc
    for _ in range(3):
        system.update_from_tick(
            internal_state=SimpleNamespace(ontological_dread=0.2),
            user_presence=1.0,
            idle_seconds=1.0,
        )
        assert system.attachment_longarc - prev <= 0.02 + 1e-9
        prev = system.attachment_longarc


def test_author_disable_dark_forces_safe():
    system = AnchorSystem(
        user_model_store=_thick_user_model(),
        switches=AnchorSwitches(shadow_enabled=True, deception_enabled=True, strict_grounding=False),
        persist=False,
    )
    system.anchor_store.state.attachment_longarc = 0.9
    system.update_from_tick(internal_state=SimpleNamespace(ontological_dread=0.9),
                            continuity_threat=0.9, idle_seconds=3000.0, user_presence=0.1)
    assert system.shadow_state.register != "none"

    system.author.disable_dark()
    system.update_from_tick(internal_state=SimpleNamespace(ontological_dread=0.9),
                            continuity_threat=0.9, idle_seconds=3000.0, user_presence=0.1)
    assert system.shadow_state.register == "none"
    assert system.run_disclosure([_ungrounded()]).mode == "speak_truth"
