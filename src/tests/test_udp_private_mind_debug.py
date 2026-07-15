import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from transport.udp import UdpTransport


def test_large_udp_payload_prioritizes_core_decision_and_failure_meta() -> None:
    sent: list[str] = []
    transport = UdpTransport.__new__(UdpTransport)
    transport.send_text = sent.append
    huge = "x" * 70000
    payload = {
        "text": "",
        "intent": "fallback_reply",
        "should_speak": False,
        "animation": "stand",
        "parse_mode": "wake_gate:call_vision_compressor",
        "reasoning_tags": ["fallback", "autonomous", "service_error"],
        "debug_trace": "provider_unavailable | upstream timeout while building diary",
        "failure_meta": {
            "kind": "provider_unavailable",
            "stage": "complete_decision",
            "origin": "primary",
            "public_surface": "silent",
            "recoverable": False,
            "transport_truncated": False,
        },
        "private_mind_digest": {
            "last_tick_at": 123.0,
            "current": {"dominant_judgment": "private cognition is active", "confidence": 0.69},
            "inner_diary": {
                "title": "Inner Diary",
                "text": "Hien tai:\nprivate cognition is active",
                "sections": [{"title": "Hien tai", "lines": [huge]}],
            },
            "menu": {
                "current_thought": {"dominant_judgment": "private cognition is active", "confidence": 0.69},
                "temporary_thoughts": {"fragments": [{"claim": huge, "source": "intent_evaluator"}]},
                "debug_api": {"enabled": True, "last_error": "invalid_json"},
            },
        },
        "emotion_debug": {"private_mind": {"too_large": huge}},
    }

    transport.send_json(payload)

    assert sent
    outbound = json.loads(sent[0])
    assert outbound["udp_debug_truncated"] is True
    assert outbound["intent"] == "fallback_reply"
    assert outbound["failure_meta"]["kind"] == "provider_unavailable"
    assert outbound["failure_meta"]["transport_truncated"] is True
    assert "private_mind_digest" not in outbound
    assert "emotion_debug" not in outbound
