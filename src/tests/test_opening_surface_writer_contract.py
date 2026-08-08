# -*- coding: utf-8 -*-
from runtime.ai_orchestrated.opening_director import OpeningDirector

from tests.opening_test_helpers import make_opening_input


def test_invalid_surface_writer_forced_use() -> None:
    opening_input = make_opening_input()
    director = OpeningDirector(mode="hybrid")
    plan = director.plan(opening_input)

    def bad_writer(_plan, _evidence):
        return {
            "display": {
                "language": "vi",
                "beats": [{"beat_id": "b1", "text": "[cười] Anh đang buồn à?"}],
                "full_text": "[cười] Anh đang buồn à? Trả lời em đi?",
            },
            "speech": {"language": "ja", "beats": [{"beat_id": "b1", "text": "x"}], "full_text": "x"},
            "self_check": {"all_beats_realized": False, "unsupported_claims": ["user emotion"], "question_count": 2},
        }

    surface = director.realize(opening_input, plan, surface_writer=bad_writer)
    assert "[cười]" in surface.display_text
    assert surface.question_count == 2
