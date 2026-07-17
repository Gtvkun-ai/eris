# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from actions.capability_registry import capability_definition
from actions.confirmation import public_action_text
from actions.executor import ActionExecutor
from actions.router import ActionRouter
from memory.unresolved_memory import UnresolvedMemoryCandidate
from runtime.internal_cognitive_capabilities import (
    COGNITIVE_CAPABILITY_IDS,
    INTERNAL_COGNITIVE_VERSION,
    InternalCognitiveCapabilityRuntime,
)
from runtime.public_turn_ledger import PublicTurnLedger
from runtime.social_cognition_v2 import SocialCognitionEngine, SocialOutcomeMemory


class _MemoryNoDisk(SocialOutcomeMemory):
    def __init__(self):
        self.stats = {}
        import threading
        self._lock = threading.RLock()

    def _save(self):
        return None


class _CandidateStore:
    def __init__(self, items=()):
        self.items = list(items)

    def load(self):
        return list(self.items)


def _owner(candidates=()):
    engine = SocialCognitionEngine(outcome_memory=_MemoryNoDisk())
    public = PublicTurnLedger()
    store = _CandidateStore(candidates)
    core = SimpleNamespace(memory_candidate=store)
    return SimpleNamespace(
        social_cognition_v2=engine,
        public_turn_ledger=public,
        memory_kernel=SimpleNamespace(core=core),
        memory_core=core,
    )


def test_contract_catalog_has_read_only_cognitive_capabilities():
    assert INTERNAL_COGNITIVE_VERSION == "internal_cognitive.v1.0"
    assert len(COGNITIVE_CAPABILITY_IDS) == 8
    for capability_id in COGNITIVE_CAPABILITY_IDS:
        definition = capability_definition(capability_id)
        assert definition is not None
        assert definition.visible_in_ui_group == "cognition"


def test_review_challenged_claim_executes_and_is_verified():
    owner = _owner()
    engine = owner.social_cognition_v2
    engine.record_public_response("Tôi nghĩ bạn đang gây chuyện rồi.")
    engine.analyze("không phải em gây chuyện hả")

    result = InternalCognitiveCapabilityRuntime(owner).execute("review_discourse_claim", "latest_challenged")
    assert result.success is True
    assert result.executed is True
    assert result.verified is True
    assert "gây chuyện" in result.public_text
    assert result.evidence[0].evidence_id.startswith("claim_id:")


def test_memory_candidate_inspection_does_not_promote_candidate_to_fact():
    candidate = UnresolvedMemoryCandidate(
        id="cand_1",
        raw_text="User có thể thích một thứ gì đó",
        extraction_status="unresolved",
    )
    owner = _owner([candidate])
    result = InternalCognitiveCapabilityRuntime(owner).execute("inspect_memory_candidates")
    assert result.success is True
    assert result.data["active_count"] == 1
    # Public surface không đọc nguyên thuật ngữ debug như candidate/fact.
    assert "chưa sắp xếp xong" in result.public_text
    assert "chắc chắn" in result.public_text
    assert "candidate" not in result.public_text.lower()
    assert "fact" not in result.public_text.lower()
    assert "User có thể thích" not in result.public_text


def test_compare_recent_public_turns_has_real_turn_evidence():
    owner = _owner()
    owner.public_turn_ledger.append(channel="chat", text="Tôi chưa có dữ kiện để kết luận.", parse_mode="chat")
    owner.public_turn_ledger.append(channel="chat", text="Tôi chưa đủ dữ kiện để kết luận.", parse_mode="chat")
    result = InternalCognitiveCapabilityRuntime(owner).execute("compare_recent_turns")
    assert result.success is True
    assert len(result.evidence) == 2
    assert result.data["similarity"] > 0.4


def test_contradiction_detector_finds_positive_negative_pair():
    owner = _owner()
    engine = owner.social_cognition_v2
    engine.record_public_response("Tôi có thể đọc telemetry runtime.")
    engine.record_public_response("Tôi không thể đọc telemetry runtime.")
    result = InternalCognitiveCapabilityRuntime(owner).execute("detect_internal_contradictions")
    assert result.success is True
    assert result.data["contradiction_count"] >= 1
    assert "mâu thuẫn" in result.public_text


def test_open_loop_summary_combines_discourse_and_memory_without_guessing():
    candidate = UnresolvedMemoryCandidate(id="cand_2", raw_text="mảnh chưa rõ", extraction_status="partial")
    owner = _owner([candidate])
    engine = owner.social_cognition_v2
    engine.record_public_response("Bạn đang né câu hỏi.")
    engine.analyze("không phải, ý tôi là chuyện khác")
    result = InternalCognitiveCapabilityRuntime(owner).execute("summarize_open_loops")
    assert result.success is True
    assert result.data["open_loop_count"] >= 2
    assert result.data["memory_candidate_count"] == 1


def test_action_executor_and_public_formatter_use_verified_cognitive_result():
    owner = _owner()
    owner.social_cognition_v2.record_public_response("Bạn đang gây chuyện.")
    owner.social_cognition_v2.analyze("không phải em gây chuyện")
    runtime = InternalCognitiveCapabilityRuntime(owner)
    executor = ActionExecutor(observer=None)
    executor.bind_cognitive_runtime(runtime)
    result = executor.execute("review_discourse_claim", "latest_challenged")
    assert result.success is True
    assert result.observed is True
    assert "gây chuyện" in public_action_text(result)


def test_router_only_routes_explicit_cognitive_commands():
    router = ActionRouter()
    assert router.route_chat("kiểm lại claim vừa hiểu sai đi") == ("review_discourse_claim", "latest_challenged")
    assert router.route_chat("kiểm tra em có tự mâu thuẫn không") == ("detect_internal_contradictions", "recent")
    # Câu hỏi repair tự nhiên phải để social cognition xử lý, không route action.
    assert router.route_chat("em hiểu sai cái gì nè") is None


def test_autonomous_intention_is_executed_instead_of_promised():
    candidate = UnresolvedMemoryCandidate(id="cand_3", raw_text="mảnh chưa rõ", extraction_status="failed")
    owner = _owner([candidate])
    runtime = InternalCognitiveCapabilityRuntime(owner)
    action = runtime.execute_intention("Mình muốn kiểm lại vài mảnh ký ức còn sót, rồi mới yên tâm.")
    assert action is not None
    assert action.success is True
    assert action.observed is True
    assert "Tôi đã kiểm tra" in action.message
    assert "Mình muốn" not in action.message
