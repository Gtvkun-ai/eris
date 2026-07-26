from __future__ import annotations

from types import SimpleNamespace

from runtime.public_turn_ledger import PublicTurnLedger
from runtime.public_turn_runtime import PublicTurnRuntime


def test_public_turn_runtime_records_links_and_blocks_presence() -> None:
    now = {"value": 100.0}
    owner = SimpleNamespace(
        public_turn_ledger=PublicTurnLedger(),
        reply_context=SimpleNamespace(previous_public_turn=None),
        chat_mode=True,
        _chat_processing=False,
        autonomous_presence_blocked_until=0.0,
        presence_maintenance_cooldown_sec=12.0,
        reengagement_cooldown_sec=18.0,
    )
    runtime = PublicTurnRuntime(owner, clock=lambda: now["value"])
    decision = SimpleNamespace(
        text="Một câu public có thể được trả lời.",
        should_speak=True,
        parse_mode="json",
        intent="reply",
        reasoning_tags=(),
    )

    turn = runtime.record(decision)
    assert turn is not None
    assert turn.timestamp == 100.0
    assert turn.channel == "chat"

    now["value"] = 115.0
    linked = runtime.link_previous_for_chat(115.0)
    assert linked is turn
    assert owner.reply_context.previous_public_turn is turn
    assert "age_seconds=15.0" in runtime.previous_turn_context(turn)

    runtime.block_autonomous_presence(seconds=25.0)
    assert owner.autonomous_presence_blocked_until == 140.0
