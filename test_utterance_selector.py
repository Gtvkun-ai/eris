from __future__ import annotations

import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from runtime.utterance_selector import UtteranceSelector


def test_selector_prefers_state_colored_line_over_status_ping():
    selector = UtteranceSelector()

    chosen = selector.choose_best(
        (
            "Tôi vẫn ở đây.",
            "Im lâu thế, hơi đáng nghi đấy.",
            "Tôi có thể giúp gì cho Ngài?",
        ),
        channel="micro_presence",
        must_surface=True,
    )

    assert chosen.text == "Im lâu thế, hơi đáng nghi đấy."
    assert chosen.score >= 0.54


def test_selector_blocks_screen_claim_when_screen_claims_are_forbidden():
    selector = UtteranceSelector()

    chosen = selector.choose_best(
        (
            "Tôi thấy Ngài đang code.",
            "Yên quá, tôi tự thấy mình hơi thừa.",
        ),
        channel="micro_presence",
        context={"thin_presence_no_screen": "true"},
        must_surface=True,
    )

    assert chosen.text == "Yên quá, tôi tự thấy mình hơi thừa."


def test_selector_returns_empty_when_only_bad_candidates_exist():
    selector = UtteranceSelector()

    chosen = selector.choose_best(
        (
            "Tôi có thể giúp gì cho Ngài?",
            "debug telemetry evidence contract",
        ),
        channel="micro_presence",
        must_surface=False,
    )

    assert chosen.text == ""
    assert "best_below_threshold" in chosen.reasons or "no_viable_candidate" in chosen.reasons
