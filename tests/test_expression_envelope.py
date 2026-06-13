# -*- coding: utf-8 -*-
"""Tests for ExpressionEnvelope — the continuous expression controller."""

from cortex.expression_envelope import ExpressionEnvelope
from cortex.internal_state import PersistentInternalState


def _state(**kwargs) -> PersistentInternalState:
    state = PersistentInternalState()
    for key, value in kwargs.items():
        setattr(state, key, value)
    return state


def test_warmth_threat_match_legacy_formula():
    # Công thức cũ trong personality.py: warmth = attach*0.55 + tender*0.55.
    state = _state(attachment=0.6, tenderness=0.4, irritation=0.2, protectiveness=0.3)
    env = ExpressionEnvelope.from_state(state, channel="chat")
    assert abs(env.warmth - min(1.0, 0.6 * 0.55 + 0.4 * 0.55)) < 1e-6
    assert abs(env.threat - min(1.0, 0.2 * 0.42 + 0.3 * 0.30)) < 1e-6


def test_ceiling_and_floor_match_legacy_levers():
    # identity_reduction giữ trần 0.30, sàn 0.52 như Lever C cũ.
    state = _state(attachment=0.9, tenderness=0.9)
    env = ExpressionEnvelope.from_state(state, channel="chat", identity_reduction=True)
    assert env.expression_ceiling() == 0.30
    assert env.suppression_floor() == 0.52

    # Riêng tư + ấm + ít đe dọa → trần nâng > base, sàn hạ về 0.40.
    warm = ExpressionEnvelope.from_state(state, channel="chat")
    assert warm.expression_ceiling() > 0.52
    assert warm.expression_ceiling() <= 0.70
    assert warm.suppression_floor() == 0.40

    # Cold default → trần/sàn base.
    cold = ExpressionEnvelope.from_state(_state(), channel="autonomous")
    assert cold.expression_ceiling() == 0.52
    assert cold.suppression_floor() == 0.48


def test_expressiveness_rises_with_warmth_falls_with_restraint():
    warm = ExpressionEnvelope.from_state(_state(attachment=0.8, tenderness=0.7, social_energy=0.7), channel="chat")
    cold = ExpressionEnvelope.from_state(_state(restraint_pressure=0.9, fatigue=0.8), channel="chat")
    assert warm.expressiveness > cold.expressiveness


def test_length_band_widens_with_expressiveness():
    warm = ExpressionEnvelope.from_state(_state(attachment=0.9, tenderness=0.9, social_energy=0.8), channel="chat")
    cold = ExpressionEnvelope.from_state(_state(restraint_pressure=0.9, fatigue=0.9), channel="chat")
    assert warm.target_max_words > cold.target_max_words
    assert warm.target_min_words >= cold.target_min_words
    assert warm.target_max_words > warm.target_min_words


def test_directness_permission_gated_by_warmth_trust_and_threat():
    open_env = ExpressionEnvelope.from_state(
        _state(attachment=0.8, tenderness=0.7, social_energy=0.6), channel="chat", trust=0.8
    )
    guarded = ExpressionEnvelope.from_state(
        _state(irritation=0.8, protectiveness=0.7), channel="chat", trust=0.0
    )
    assert open_env.directness_permission > guarded.directness_permission
    # identity_reduction luôn khóa directness về 0.
    reduced = ExpressionEnvelope.from_state(
        _state(attachment=0.9, tenderness=0.9), channel="chat", trust=0.9, identity_reduction=True
    )
    assert reduced.directness_permission == 0.0


def test_speak_bias_positive_when_silent_and_social_negative_when_restrained():
    talky = ExpressionEnvelope.from_state(_state(silence_pressure=0.9, social_energy=0.8, boredom=0.6), channel="chat")
    quiet = ExpressionEnvelope.from_state(_state(restraint_pressure=0.9, fatigue=0.9), channel="autonomous")
    assert talky.speak_bias > 0.0
    assert quiet.speak_bias < talky.speak_bias
    # Bị kẹp trong [-0.15, 0.20].
    assert -0.15 <= talky.speak_bias <= 0.20
    assert -0.15 <= quiet.speak_bias <= 0.20


def test_private_flag_from_channel():
    assert ExpressionEnvelope.from_state(_state(), channel="chat").private is True
    assert ExpressionEnvelope.from_state(_state(), channel="force_speak").private is True
    assert ExpressionEnvelope.from_state(_state(), channel="autonomous").private is False


def test_default_suppression_falls_with_expressiveness():
    warm = ExpressionEnvelope.from_state(
        _state(attachment=0.9, tenderness=0.9, social_energy=0.8), channel="chat"
    )
    cold = ExpressionEnvelope.from_state(
        _state(restraint_pressure=0.9, fatigue=0.9), channel="autonomous"
    )
    # Mở → nền kìm thấp; khép → nền kìm cao.
    assert warm.default_suppression() < cold.default_suppression()
    # Luôn trong dải an toàn.
    for env in (warm, cold):
        assert 0.42 <= env.default_suppression() <= 0.80


def test_default_suppression_neutral_near_legacy_constant():
    # State mặc định phải cho nền ≈ 0.66 cũ (không lệch hành vi nền).
    env = ExpressionEnvelope.from_state(_state(), channel="chat")
    assert abs(env.default_suppression() - 0.66) < 0.08


def test_default_suppression_identity_reduction_is_high():
    env = ExpressionEnvelope.from_state(
        _state(attachment=0.9, tenderness=0.9), channel="chat", identity_reduction=True
    )
    assert env.default_suppression() >= 0.70


def test_handles_garbage_state_without_raising():
    class Bogus:
        attachment = "not a number"
        irritation = None

    env = ExpressionEnvelope.from_state(Bogus(), channel="chat")
    assert 0.0 <= env.expressiveness <= 1.0
    assert 0.0 <= env.warmth <= 1.0
    assert 0.42 <= env.default_suppression() <= 0.80
