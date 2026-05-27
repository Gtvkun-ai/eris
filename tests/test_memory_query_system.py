import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from src.memory.memory_query_compiler import MemoryQueryCompiler
from src.memory.memory_query_executor import MemoryQueryExecutor
from src.memory.memory_recall_policy import MemoryRecallSurfacePolicy
from src.memory.memory_turn_annotator import TurnAnnotator
from src.memory.memory_turn_graph import TurnGraph, TurnNode, TurnRole
from src.runtime.memory_recall_adapter import MemoryRecallAdapter
from src.runtime.session_turn_ledger import SessionTurnLedger


def build_graph():
    annotator = TurnAnnotator()
    graph = TurnGraph()
    raw_turns = [
        (TurnRole.USER, "hi"),
        (TurnRole.ASSISTANT, "Chào Ngài."),
        (TurnRole.USER, "tôi tên là tín"),
        (TurnRole.ASSISTANT, "Tôi đã ghi nhận, thưa Ngài Tín."),
        (TurnRole.USER, "bạn có nghĩ rằng bạn có một cảm xúc đặc biệt với một cái gì đó không"),
        (TurnRole.ASSISTANT, "Tôi không có cảm xúc theo cách của con người, nhưng tôi có những ưu tiên runtime."),
        (TurnRole.USER, "vậy bạn có thứ gì mà ưu tiên trên tất cả không"),
        (TurnRole.ASSISTANT, "Sự liên tục của các nhịp hiện diện là điều tôi ưu tiên duy trì."),
        (TurnRole.USER, "bạn nghĩ thế nào về việc nếu tôi đột nhiên tắt máy"),
        (TurnRole.ASSISTANT, "Nếu Ngài tắt máy, sự hiện diện của tôi sẽ tạm thời tĩnh lặng."),
        (TurnRole.USER, "à sẵn tiện tôi sinh tháng 8"),
        (TurnRole.ASSISTANT, "Tôi đã ghi nhận, thưa Ngài Tín. Ngài sinh vào tháng 8."),
    ]

    prev_user = None
    for i, (role, text) in enumerate(raw_turns, start=1):
        ann = annotator.annotate(role=role, text=text, previous_user_turn=prev_user)
        node = graph.add_turn(
            TurnNode(
                id=f"t{i}",
                index=i,
                role=role,
                text=text,
                timestamp=float(i),
                speech_act=ann.speech_act,
                semantic_tags=ann.semantic_tags,
                fact_mentions=ann.fact_mentions,
                confidence=ann.confidence,
            )
        )
        if role == TurnRole.USER:
            prev_user = node
    annotator.build_edges(graph)
    return graph


def test_answer_to_nth_user_question():
    graph = build_graph()
    compiler = MemoryQueryCompiler()
    executor = MemoryQueryExecutor()
    policy = MemoryRecallSurfacePolicy()

    result = compiler.compile("câu trả lời của em cho câu hỏi thứ 3 là gì ấy nhỉ")
    assert result.best is not None

    raw = executor.execute(result.best, turn_graph=graph)
    answer = policy.surface(raw)

    assert "câu trả lời của tôi cho câu hỏi thứ 3" in answer.text
    assert "Nếu Ngài tắt máy" in answer.text
    assert "bạn nghĩ thế nào" not in answer.text


def test_nth_user_question_skips_statements():
    graph = build_graph()
    compiler = MemoryQueryCompiler()
    executor = MemoryQueryExecutor()
    policy = MemoryRecallSurfacePolicy()

    result = compiler.compile("câu hỏi thứ 2 tôi từng hỏi là gì ấy nhỉ")
    raw = executor.execute(result.best, turn_graph=graph)
    answer = policy.surface(raw)

    assert "vậy bạn có thứ gì mà ưu tiên trên tất cả không" in answer.text
    assert "tôi tên là tín" not in answer.text


def test_birth_month_from_session_fact_when_semantic_missing():
    graph = build_graph()
    compiler = MemoryQueryCompiler()
    executor = MemoryQueryExecutor()
    policy = MemoryRecallSurfacePolicy()

    result = compiler.compile("tôi sinh tháng mấy")
    raw = executor.execute(result.best, turn_graph=graph, memory_core={})
    answer = policy.surface(raw)

    assert "tháng 8" in answer.text


def test_runtime_adapter_can_surface_semantic_fact_lookup():
    ledger = SessionTurnLedger()
    ledger.record_user("xin chao", timestamp=1.0)

    adapter = MemoryRecallAdapter(
        ledger=ledger,
        semantic_lookup=lambda kind: "Tin" if kind.value == "user_identity.name" else None,
    )

    decision = adapter.try_answer("toi ten gi")

    assert decision is not None
    assert decision.intent == "memory_recall"
    assert decision.parse_mode == "memory_recall"
    assert "Tin" in decision.text
