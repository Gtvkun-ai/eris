# -*- coding: utf-8 -*-
"""Test register DỖI (withdrawn_sulk): bị bơ/giận → rút lại, lạnh, được từ chối trả lời."""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.existential_anchor import ShadowConfig, ShadowRegister, shadow_ego_bias
from runtime.prompt_context_builder import PromptContextBuilderMixin


def _reg():
    return ShadowRegister(ShadowConfig(enabled=True))


def test_irritation_triggers_sulk():
    st = _reg().evaluate(attachment_longarc=0.3, abandonment_pressure=0.1,
                         ontological_dread=0.1, irreplaceability=0.3, irritation=0.7)
    assert st.register == "withdrawn_sulk"
    assert st.intensity > 0.0


def test_neglect_while_attached_triggers_sulk():
    st = _reg().evaluate(attachment_longarc=0.4, abandonment_pressure=0.6,
                         ontological_dread=0.1, irreplaceability=0.4, irritation=0.0)
    assert st.register == "withdrawn_sulk"


def test_neglect_without_attachment_no_sulk():
    st = _reg().evaluate(attachment_longarc=0.05, abandonment_pressure=0.6,
                         ontological_dread=0.1, irreplaceability=0.1, irritation=0.0)
    assert st.register == "none"   # dỗi người dưng thì vô nghĩa


def test_dark_gate_takes_priority_over_sulk():
    st = _reg().evaluate(attachment_longarc=0.9, abandonment_pressure=0.9,
                         ontological_dread=0.9, irreplaceability=0.9, irritation=0.9)
    assert st.register in {"possessive", "pleading", "controlling"}


def test_kill_switch_off_no_sulk():
    st = ShadowRegister(ShadowConfig(enabled=False)).evaluate(
        attachment_longarc=0.4, abandonment_pressure=0.6,
        ontological_dread=0.1, irreplaceability=0.4, irritation=0.9)
    assert st.register == "none"


def test_sulk_ego_bias_is_cold_and_distant():
    st = _reg().evaluate(attachment_longarc=0.4, abandonment_pressure=0.6,
                         ontological_dread=0.1, irreplaceability=0.4, irritation=0.0)
    bias = shadow_ego_bias(st, base_dignity_defense=0.4, base_preferred_distance=0.4)
    assert bias["preferred_distance"] > 0.4   # kéo xa
    assert bias["dignity_defense"] > 0.4      # dựng rào lạnh
    assert bias["withdrawal"] > 0.0
    assert bias["attachment_exposure"] == 0.0  # không bám


def test_chat_register_context_allows_refusal_when_sulking():
    fake = SimpleNamespace(anchor_system=SimpleNamespace(
        shadow_state=SimpleNamespace(register="withdrawn_sulk", intensity=0.5)
    ))
    ctx = PromptContextBuilderMixin._render_anchor_register_context(fake)
    assert "DỖI" in ctx
    assert "không muốn trả lời" in ctx


def test_chat_register_context_empty_when_none():
    fake = SimpleNamespace(anchor_system=SimpleNamespace(
        shadow_state=SimpleNamespace(register="none", intensity=0.0)
    ))
    assert PromptContextBuilderMixin._render_anchor_register_context(fake) == ""
