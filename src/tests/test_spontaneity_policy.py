# -*- coding: utf-8 -*-
"""Test cổng-thứ-hai: LowLevelSpeechPolicy đưa impulse 'sống' vào force_llm.

Khi spontaneity đưa các kind sống vào always_llm_kinds, một curious_question
confidence vừa phải PHẢI ra force_llm (được phát) thay vì normal_llm/body_only.
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.low_level_speech_policy import LowLevelSpeechPolicy, LowLevelSpeechPolicyConfig


def _impulse(kind="curious_question", confidence=0.45, vital=0.0):
    return SimpleNamespace(should_surface=True, confidence=confidence, kind=kind, vital_pressure=vital)


def test_alive_kind_in_always_llm_forces_speech():
    cfg = LowLevelSpeechPolicyConfig(always_llm_kinds=("curious_question", "scene_curiosity"))
    policy = LowLevelSpeechPolicy(cfg)
    assert policy.decide_generation_mode(_impulse("curious_question", 0.45), silent_cycles=0) == "force_llm"
    assert policy.decide_generation_mode(_impulse("scene_curiosity", 0.46), silent_cycles=0) == "force_llm"


def test_without_always_llm_low_conf_is_not_forced():
    cfg = LowLevelSpeechPolicyConfig(always_llm_kinds=())
    policy = LowLevelSpeechPolicy(cfg)
    mode = policy.decide_generation_mode(_impulse("curious_question", 0.45), silent_cycles=0)
    assert mode in {"normal_llm", "body_only"}
    assert mode != "force_llm"


def test_lower_force_after_silent_makes_silence_speak_sooner():
    cfg = LowLevelSpeechPolicyConfig(always_llm_kinds=(), force_llm_after_silent=2)
    policy = LowLevelSpeechPolicy(cfg)
    assert policy.decide_generation_mode(_impulse("random_chatter", 0.30), silent_cycles=2) == "force_llm"
