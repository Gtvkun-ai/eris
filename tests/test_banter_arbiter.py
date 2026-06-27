import os
import sys


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from domain import Decision
from runtime.banter_arbiter import BanterArbiter


def test_hard_json_repair_with_clean_public_text_is_kept():
    arbiter = BanterArbiter()
    decision = Decision(
        text="Toi hieu, doi khi cung can nghi ngoi mot chut.",
        animation="stand",
        intent="acknowledgment",
        parse_mode="hard_json_repair",
        debug_trace="LlmService sanitized decision-like JSON before parser.",
    )

    result = arbiter.arbitrate(decision, channel="chat", user_text="xem toi bam ik. tui luoi nhan a")

    assert result.mode == "none"
    assert result.reason == "kept"
    assert result.text == ""


def test_protocol_markers_in_public_text_still_trigger_protocol_repair():
    arbiter = BanterArbiter()
    decision = Decision(
        text='json debug: {"text":"xin chao"}',
        animation="stand",
        intent="acknowledgment",
        parse_mode="hard_json_repair",
    )

    result = arbiter.arbitrate(decision, channel="chat", user_text="xin chao")

    assert result.mode == "protocol_repair"
    assert result.reason == "blocked_protocol_surface"
    assert result.text.startswith("Câu đó lệch.")
