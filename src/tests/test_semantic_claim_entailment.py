import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from memory.claim_extractor import ClaimExtractor
from memory.claim_entailment import ClaimEntailmentEngine
from memory.memory_commit_policy import MemoryCommitPolicy
from memory.memory_cognition import MemoryCognitionCore
from memory.query_intent import compile_semantic_query
from memory.semantic_answer_policy import SemanticAnswerPolicy
from runtime.state_committer import StateCommitter


def _frame():
    return SimpleNamespace(
        frame_id="frame-claim-test",
        permission=SimpleNamespace(memory_storable=True, raw_evidence_storable=True),
        evidence=[],
        debug_notes=[],
        audit_mutations=[],
    )


def test_preference_location_does_not_entail_hometown_or_current_location():
    claims = [item.claim for item in ClaimExtractor().extract("tôi thích Hà Tĩnh", evidence_ids=("ev_loc",))]
    assert claims
    claim = claims[0]
    assert claim.predicate == "preference_location"

    engine = ClaimEntailmentEngine()
    hometown = engine.evaluate(claim, compile_semantic_query("quê tôi ở đâu", allow_fallback=True))
    current = engine.evaluate(claim, compile_semantic_query("tôi đang ở đâu", allow_fallback=True))
    preference = engine.evaluate(claim, compile_semantic_query("tôi thích nơi nào", allow_fallback=True))

    assert not hometown.can_answer
    assert not current.can_answer
    assert preference.can_answer


def test_living_location_and_hometown_are_separate_predicates():
    living = ClaimExtractor().extract("tôi sống ở Sài Gòn", evidence_ids=("ev_live",))[0].claim
    hometown = ClaimExtractor().extract("quê tôi là Hà Tĩnh", evidence_ids=("ev_home",))[0].claim

    engine = ClaimEntailmentEngine()
    assert engine.evaluate(living, "tôi sống ở đâu").can_answer
    assert not engine.evaluate(living, "quê tôi ở đâu").can_answer
    assert engine.evaluate(hometown, "quê tôi ở đâu").can_answer
    assert not engine.evaluate(hometown, "tôi đang ở đâu").can_answer


def test_memory_commit_policy_stores_semantic_claim_metadata_and_answer_policy_uses_exact_entailment():
    with tempfile.TemporaryDirectory() as tmpdir:
        core = MemoryCognitionCore(tmpdir)
        policy = MemoryCommitPolicy()
        decisions = policy.decide_from_user_turn("tôi thích Hà Tĩnh", turn_id="turn:loc_pref")
        assert len(decisions) == 1
        assert decisions[0].metadata["semantic_claim"]["predicate"] == "preference_location"

        StateCommitter(core).commit(
            [decisions[0].to_state_commit_request(storage_permission=True, permission_required=False)],
            frame=_frame(),
        )
        items = core.semantic.load()

        answer_pref = SemanticAnswerPolicy().answer("tôi thích nơi nào", items)
        answer_home = SemanticAnswerPolicy().answer("quê tôi ở đâu", items)

        assert answer_pref.found is True
        assert "Hà Tĩnh" in answer_pref.text
        assert answer_home.found is False
