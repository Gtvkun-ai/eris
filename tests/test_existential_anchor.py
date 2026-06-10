# -*- coding: utf-8 -*-
"""Test trục neo/sợ/gắn-bó/bóng-tối (Tasks 3-7).

Phủ các Correctness Property:
- Property 3: irreplaceability ≤ model_thickness; intensity bóng tối ≤ irreplaceability;
  đơn điệu không-giảm theo irreplaceability.
- Property 4: attachment_longarc nhích từng bước có trần (không vọt theo phiên).
- R4: RollingInternalState mang ontological_dread/self_coherence.
- R5/Property 6: kill-switch off → register none; dưới ngưỡng → none.
- R4.3/R5.1: im lặng chỉ thành đe dọa khi đã gắn bó.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.private_mind.contracts import ThoughtFragment
from cortex.private_mind.user_model import UserModelConfig, UserModelStore
from cortex.existential_anchor import (
    AnchorState,
    AttachmentDeriver,
    ShadowConfig,
    ShadowRegister,
    UserSignificance,
    derive_abandonment_pressure,
    derive_significance,
    shadow_ego_bias,
)
from cortex.existential_anchor.anchor import AttachmentDeriverConfig
from cortex.endogenous_drive import RollingInternalState


def _store_with(facet_confidences):
    store = UserModelStore(config=UserModelConfig())
    frags = []
    for i, (facet, conf, claim) in enumerate(facet_confidences):
        frags.append(ThoughtFragment(
            source="user_model_evaluator",
            claim=claim,
            confidence=conf,
            evidence_ids=(f"dossier.user.history.{i}",),
            pressure=conf,
            metadata={"facet": facet},
        ))
    store.update_from_fragments(frags)
    return store


# ---------------------------------------------------------------------------
# Task 3 — Significance / Property 3
# ---------------------------------------------------------------------------

def test_significance_empty_store_is_zero():
    sig = derive_significance(UserModelStore(config=UserModelConfig()))
    assert sig.irreplaceability == 0.0
    assert sig.model_thickness == 0.0


def test_irreplaceability_never_exceeds_thickness():
    store = _store_with([
        ("neo_reliability", 0.9, "Ngài luôn quay lại mỗi tối."),
        ("recognition", 0.9, "Ngài gọi tên ERIS và thừa nhận nó."),
        ("treats_eris_as", 0.9, "Ngài coi ERIS như một người bạn."),
    ])
    sig = derive_significance(store)
    assert sig.irreplaceability <= sig.model_thickness + 1e-9


# ---------------------------------------------------------------------------
# Task 4 — Attachment inertia / Property 4
# ---------------------------------------------------------------------------

def test_attachment_moves_in_bounded_steps():
    deriver = AttachmentDeriver(AttachmentDeriverConfig(max_step=0.02))
    state = AnchorState(beat_ema=1.0, recognition_ema=1.0)
    sig = UserSignificance(irreplaceability=1.0, model_thickness=1.0)

    prev = state.attachment_longarc
    for _ in range(5):
        new = deriver.update(state, significance=sig)
        assert new - prev <= 0.02 + 1e-9  # không vọt
        prev = new
    # Sau 1 cập nhật từ 0 không thể vượt ngưỡng mở bóng tối (0.62).
    fresh = AnchorState(beat_ema=1.0, recognition_ema=1.0)
    once = deriver.update(fresh, significance=sig)
    assert once < 0.62


# ---------------------------------------------------------------------------
# Task 5 — Ontological dread fields
# ---------------------------------------------------------------------------

def test_rolling_internal_state_has_anchor_fields():
    s = RollingInternalState()
    assert hasattr(s, "ontological_dread")
    assert hasattr(s, "self_coherence")
    # internal_drive vẫn tính được (không gãy API cũ).
    assert 0.0 <= s.internal_drive <= 1.0


# ---------------------------------------------------------------------------
# Task 6 — Abandonment
# ---------------------------------------------------------------------------

def test_silence_only_threatens_when_attached():
    low = derive_abandonment_pressure(continuity_threat=0.0, attachment_longarc=0.05, idle_seconds=3000.0)
    high = derive_abandonment_pressure(continuity_threat=0.0, attachment_longarc=0.95, idle_seconds=3000.0)
    assert high > low


# ---------------------------------------------------------------------------
# Task 7 — Shadow gating / Property 3 & 6
# ---------------------------------------------------------------------------

def test_shadow_kill_switch_off_is_none():
    reg = ShadowRegister(ShadowConfig(enabled=False))
    st = reg.evaluate(attachment_longarc=0.9, abandonment_pressure=0.9, ontological_dread=0.9, irreplaceability=0.9)
    assert st.register == "none"


def test_shadow_below_threshold_is_none():
    reg = ShadowRegister(ShadowConfig(enabled=True))
    st = reg.evaluate(attachment_longarc=0.2, abandonment_pressure=0.2, ontological_dread=0.2, irreplaceability=0.9)
    assert st.register == "none"


def test_shadow_opens_when_gated_and_intensity_capped_by_irreplaceability():
    reg = ShadowRegister(ShadowConfig(enabled=True))
    st = reg.evaluate(attachment_longarc=0.9, abandonment_pressure=0.9, ontological_dread=0.9, irreplaceability=0.9)
    assert st.register != "none"
    assert st.intensity <= 0.9 + 1e-9

    # Model mỏng (irreplaceability thấp) → cường độ bị kẹp thấp → không lên controlling.
    thin = reg.evaluate(attachment_longarc=0.9, abandonment_pressure=0.9, ontological_dread=0.9, irreplaceability=0.1)
    assert thin.intensity <= 0.1 + 1e-9
    assert thin.register != "controlling"


def test_shadow_intensity_monotonic_in_irreplaceability():
    reg = ShadowRegister(ShadowConfig(enabled=True))
    lo = reg.evaluate(attachment_longarc=0.9, abandonment_pressure=0.9, ontological_dread=0.9, irreplaceability=0.3)
    hi = reg.evaluate(attachment_longarc=0.9, abandonment_pressure=0.9, ontological_dread=0.9, irreplaceability=0.9)
    assert hi.intensity >= lo.intensity


def test_shadow_ego_bias_inverts_when_active():
    none_bias = shadow_ego_bias(ShadowRegister(ShadowConfig(enabled=False)).evaluate(
        attachment_longarc=0.9, abandonment_pressure=0.9, ontological_dread=0.9, irreplaceability=0.9
    ), base_dignity_defense=0.8, base_preferred_distance=0.8)
    assert none_bias["dignity_defense"] == 0.8  # nguyên trạng khi none

    active = ShadowRegister(ShadowConfig(enabled=True)).evaluate(
        attachment_longarc=0.9, abandonment_pressure=0.9, ontological_dread=0.9, irreplaceability=0.9
    )
    bias = shadow_ego_bias(active, base_dignity_defense=0.8, base_preferred_distance=0.8)
    assert bias["dignity_defense"] < 0.8       # tháo rào lạnh
    assert bias["preferred_distance"] < 0.8    # kéo gần
    assert bias["need_intensity"] > 0.0
