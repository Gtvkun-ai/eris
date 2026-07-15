import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from src.memory.memory_query_compiler import MemoryQueryCompiler
from src.memory.memory_query_executor import MemoryQueryExecutor
from src.memory.memory_query_ir import MemoryQueryIR, MemorySelector, MemorySourceKind, QueryIntent, RawRecallResult
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
        (TurnRole.ASSISTANT, "Chào bạn."),
        (TurnRole.USER, "tôi tên là tín"),
        (TurnRole.ASSISTANT, "Tôi đã ghi nhận, thưa bạn Tín."),
        (TurnRole.USER, "bạn có nghĩ rằng bạn có một cảm xúc đặc biệt với một cái gì đó không"),
        (TurnRole.ASSISTANT, "Tôi không có cảm xúc theo cách của con người, nhưng tôi có những ưu tiên runtime."),
        (TurnRole.USER, "vậy bạn có thứ gì mà ưu tiên trên tất cả không"),
        (TurnRole.ASSISTANT, "Sự liên tục của các nhịp hiện diện là điều tôi ưu tiên duy trì."),
        (TurnRole.USER, "bạn nghĩ thế nào về việc nếu tôi đột nhiên tắt máy"),
        (TurnRole.ASSISTANT, "Nếu bạn tắt máy, sự hiện diện của tôi sẽ tạm thời tĩnh lặng."),
        (TurnRole.USER, "à sẵn tiện tôi sinh tháng 8"),
        (TurnRole.ASSISTANT, "Tôi đã ghi nhận, thưa bạn Tín. bạn sinh vào tháng 8."),
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
    assert "Nếu bạn tắt máy" in answer.text
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


def test_fact_disclosure_statement_is_not_compiled_as_recall_query():
    compiler = MemoryQueryCompiler()

    name_result = compiler.compile("toi ten la Tin")
    birth_result = compiler.compile("toi sinh thang 8")
    rename_result = compiler.compile("toi moi doi ten sang Ho Trung Tin sang nay")

    assert name_result.best is None
    assert "fact_disclosure_not_recall" in name_result.debug.notes
    assert birth_result.best is None
    assert "fact_disclosure_not_recall" in birth_result.debug.notes
    assert rename_result.best is None
    assert "fact_disclosure_not_recall" in rename_result.debug.notes


def test_compiler_suppresses_high_ambiguity_semantic_recall():
    compiler = MemoryQueryCompiler()

    result = compiler.compile("ten")

    assert result.best is None
    assert "semantic_recall_ambiguity_too_high" in result.debug.notes


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


def test_runtime_adapter_does_not_surface_memory_packet_repr_from_base_core():
    ledger = SessionTurnLedger()
    ledger.record_user("xin chao", timestamp=1.0)
    packet_like = SimpleNamespace(
        episodic=(),
        semantic=(),
        relational=(),
        affective_residue=(),
        procedural=(),
        repair=(),
        token_budget=900,
        source_counts={"semantic": 0},
    )
    memory_core = SimpleNamespace(lookup_fact=lambda fact_key: packet_like)

    adapter = MemoryRecallAdapter(
        ledger=ledger,
        memory_core=memory_core,
        semantic_lookup=lambda kind: None,
    )

    decision = adapter.try_answer("toi ten gi")

    assert decision is not None
    assert "MemoryPacket(" not in decision.text
    assert "namespace(" not in decision.text.lower()
    assert "chưa có" in decision.text or "chua co" in decision.text


def test_runtime_adapter_ignores_user_fact_disclosure_and_ambiguous_semantic_probe():
    ledger = SessionTurnLedger()
    ledger.record_user("xin chao", timestamp=1.0)

    adapter = MemoryRecallAdapter(
        ledger=ledger,
        semantic_lookup=lambda kind: "Tin" if kind.value == "user_identity.name" else None,
    )

    assert adapter.try_answer("toi ten la Tin") is None
    assert adapter.try_answer("toi moi doi ten sang Ho Trung Tin sang nay") is None
    assert adapter.try_answer("ten") is None


def test_runtime_adapter_fact_update_guard_runs_before_memory_kernel_answer():
    ledger = SessionTurnLedger()
    ledger.record_user("xin chao", timestamp=1.0)
    kernel = SimpleNamespace(answer=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("kernel recall should not run")))
    adapter = MemoryRecallAdapter(ledger=ledger, memory_kernel=kernel)

    assert adapter.try_answer("doi ten sang Ho Trung Tin") is None


def test_surface_policy_blocks_raw_object_repr():
    ir = MemoryQueryIR(
        intent=QueryIntent.RECALL_FACT,
        target=MemorySelector(fact_key="user.name"),
    )
    policy = MemoryRecallSurfacePolicy()
    raw = RawRecallResult(
        found=True,
        source=MemorySourceKind.SEMANTIC_MEMORY,
        ir=ir,
        exact_text="UserProfile(name='Tin')",
        confidence=0.92,
    )

    answer = policy.surface(raw)

    assert answer.surface.value == "admit_uncertain"
    assert answer.debug_trace == "raw_object_surface_blocked"


def test_surface_policy_blocks_embedded_memory_packet_repr():
    ir = MemoryQueryIR(
        intent=QueryIntent.RECALL_FACT,
        target=MemorySelector(fact_key="user.name"),
    )
    policy = MemoryRecallSurfacePolicy()
    raw = RawRecallResult(
        found=True,
        source=MemorySourceKind.SEMANTIC_MEMORY,
        ir=ir,
        exact_text="Tên bạn là MemoryPacket(episodic=[], semantic=[], token_budget=900).",
        confidence=0.92,
    )

    answer = policy.surface(raw)

    assert answer.surface.value == "admit_uncertain"
    assert answer.debug_trace == "raw_object_surface_blocked"
