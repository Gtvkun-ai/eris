# -*- coding: utf-8 -*-
"""V6: runtime không được biên tập public wording vì pacing/TTS."""
from runtime.agent_loop.contracts import TurnSpeechBudget
from runtime.agent_loop.speech import enforce_public_speech_budget


def test_legacy_speech_guard_is_observer_only_even_far_over_old_cap() -> None:
    original = ("Hen hen. Rõ ràng là tôi đang hiểu ý anh rồi, nhưng cách gọi này "
                "nghe buồn cười thật đấy — để tôi theo nhịp này một chút.")
    budget = TurnSpeechBudget(
        target_words=5, hard_max_words=8, max_beats=1,
        target_seconds=2.0, hard_max_seconds=3.0,
    )
    result = enforce_public_speech_budget(original, budget, speed=1.0)
    assert result.text == original
    assert result.clipped is False


def test_runtime_source_has_no_post_writer_hard_clip_call() -> None:
    from pathlib import Path
    source = (Path(__file__).parents[1] / "runtime" / "ai_orchestrated" / "orchestrator.py").read_text(encoding="utf-8")
    assert "hard-clipped writer output before TTS" not in source
    assert "payload[\"text\"] = _display_guard.text" not in source
    assert "payload[\"speech_text\"] = _speech_guard.text" not in source
