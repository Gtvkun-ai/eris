from __future__ import annotations

from pathlib import Path

from memory.memory_query_compiler import MemoryQueryCompiler
from runtime.conversation_continuity import ConversationContinuityAdapter
from runtime.session_turn_ledger import SessionTurnLedger


def test_recent_turn_recall_uses_previous_user_turn_not_profile_memory() -> None:
    ledger = SessionTurnLedger()
    ledger.record_user("nghe rõ cái chi")
    ledger.record_assistant("Thì câu em vừa nói ấy.")
    # Orchestrator ghi current user turn trước khi gọi continuity adapter.
    ledger.record_user("tôi nói cái gì ta")

    decision = ConversationContinuityAdapter(ledger).try_answer("tôi nói cái gì ta")

    assert decision is not None
    assert decision.parse_mode == "conversation_continuity"
    assert decision.intent == "recent_turn_recall"
    assert "nghe rõ cái chi" in decision.text
    assert "tên" not in decision.text.lower()


def test_short_repair_corrects_previous_recent_turn_recall() -> None:
    ledger = SessionTurnLedger()
    ledger.record_user("nghe rõ cái chi")
    ledger.record_assistant("Thì câu em vừa nói ấy.")
    ledger.record_user("tôi nói cái gì ta")
    ledger.record_assistant("Tôi chưa nhớ bạn từng nói tên mình.")
    ledger.record_user("hả")

    decision = ConversationContinuityAdapter(ledger).try_answer("hả")

    assert decision is not None
    assert decision.intent == "conversation_repair"
    assert "trả lời lệch ý" in decision.text
    assert "nghe rõ cái chi" in decision.text


def test_memory_compiler_does_not_route_recent_turn_recall_to_user_name() -> None:
    for query in ("tôi nói cái gì ta", "tôi vừa nói gì", "nãy tôi nói gì"):
        result = MemoryQueryCompiler().compile(query)
        assert result.best is None or result.best.target.fact_key != "user.name"

    name_result = MemoryQueryCompiler().compile("tôi tên gì")
    assert name_result.best is not None
    assert name_result.best.target.fact_key == "user.name"


def test_settings_cooldown_uses_int64_instead_of_int32() -> None:
    source = (Path(__file__).resolve().parents[1] / "body" / "UdpListener.SettingsPanel.cs").read_text(encoding="utf-8")

    assert "public long CooldownMs" in source
    assert 'ReadJsonInt64(pool, "global_cooldown_ms", 0L)' in source
    assert 'ReadJsonInt64(key, "cooldown_ms", 0L)' in source
    assert 'cooldownEl.GetInt32()' not in source
    assert 'keyCooldownEl.GetInt32()' not in source
