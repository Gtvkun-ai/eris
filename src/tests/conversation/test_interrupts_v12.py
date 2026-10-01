# -*- coding: utf-8 -*-
from runtime.conversation import InterruptKind, classify_interrupt


def test_backchannel_does_not_cancel_audio_or_continuation():
    result = classify_interrupt("ừm")
    assert result.kind == InterruptKind.BACKCHANNEL
    assert result.cancel_audio is False
    assert result.cancel_generation is False
    assert result.preserve_continuation is True


def test_stop_and_steering_preempt():
    stop = classify_interrupt("khoan, dừng lại")
    assert stop.kind == InterruptKind.STOP
    assert stop.cancel_audio and stop.cancel_generation

    steer = classify_interrupt("không, chuyển qua phần khác")
    assert steer.kind == InterruptKind.STEERING
    assert steer.cancel_audio and steer.cancel_generation
