import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from transport.udp import UdpTransport


def test_large_udp_payload_preserves_compact_private_mind_digest() -> None:
    sent: list[str] = []
    transport = UdpTransport.__new__(UdpTransport)
    transport.send_text = sent.append
    huge = "x" * 70000
    payload = {
        "text": "",
        "should_speak": False,
        "animation": "stand",
        "parse_mode": "wake_gate:call_vision_compressor",
        "private_mind_digest": {
            "last_tick_at": 123.0,
            "current": {"dominant_judgment": "private cognition is active", "confidence": 0.69},
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
    assert outbound["private_mind_digest"]["current"]["dominant_judgment"] == "private cognition is active"
    assert outbound["private_mind_digest"]["menu"]["debug_api"]["last_error"] == "invalid_json"
    assert outbound["emotion_debug"]["private_mind"]["udp_debug_truncated"] is True
