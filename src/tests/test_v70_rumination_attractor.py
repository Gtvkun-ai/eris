# -*- coding: utf-8 -*-
"""Acceptance V70: private rumination được phép lì, public repetition thì không.

Kiểm đúng triết lý release:
- stickiness/attractor giữ concern trong đầu sau khi đã nói;
- private return là event thật nhưng không pump pressure;
- concern đã consummate vẫn có thể sinh material nếu epistemic tension còn;
- paraphrase không được giả làm insight;
- semantic development thật có thể reopen biểu đạt một phần;
- user nói chán/đổi chủ đề vẫn được tôn trọng ở public layer.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cortex.active_concern import private_concern_view
from cortex.cognitive_event import CognitiveEvent
from cortex.mental_material import derive_causal_motives
from cortex.private_mind.concern_store import ConcernStore
from cortex.rumination_dynamics import semantic_development_score
from runtime.active_concern_runtime import ActiveConcernRuntime
from runtime.expression_consummation import ExpressionConsummationRuntime
from runtime.mental_material_runtime import MentalMaterialRuntime
from runtime.ai_orchestrated.random_chat_seed import RandomChatSeed
from runtime.ai_orchestrated.random_chat_seed_service import RandomChatSeedGenerator
from runtime.ai_orchestrated.social_initiative import SocialSpeechCandidate


def _memory_topic() -> str:
    return "Một truy vấn trí nhớ có hai lớp: hỏi thông tin và thử xem người kia có nhớ mình."


def test_consumed_concern_can_stay_sticky_while_speech_pressure_is_low():
    concern = SimpleNamespace(
        id="concern.sticky",
        theme=_memory_topic(),
        pressure=0.66,
        uncertainty=0.72,
        recurrence=5,
        status="open",
        evidence_ids=("turn:1",),
        open_questions=(),
        created_at=100.0,
        updated_at=180.0,
        metadata={
            "event_count": 5,
            "mutation_count": 1,
            "echo_streak": 1,
            "surfaced_count": 2,
            "private_return_count": 3,
            "stickiness": 0.70,
            "last_event_at": 180.0,
            "last_mutation_at": 150.0,
            "completion": {
                "epistemic": 0.22,
                "expressive": 0.95,
                "relational": 0.62,
                "updated_at": 190.0,
            },
        },
    )
    view = private_concern_view(concern, now=200.0)
    assert view.stickiness >= 0.65
    assert view.attractor_strength >= 0.40
    assert view.rumination_awareness >= 0.35
    assert view.speech_pressure < 0.18
    assert view.metadata["rumination"]["development_required"] is True


def test_private_return_receipt_is_idempotent_and_does_not_pump_pressure(tmp_path: Path):
    store = ConcernStore(path=tmp_path / "concerns.json")
    receipt = store.ingest_cognitive_event({
        "event_id": "cogevt:base",
        "origin": "user",
        "kind": "thought",
        "subject": _memory_topic(),
        "occurred_at": 100.0,
        "evidence_refs": ("turn:1",),
        "source_ref": "turn:1",
        "metadata": {"seed_quality": 0.8, "uncertainty": 0.72},
    })
    concern = receipt.concern
    assert concern is not None
    concern.metadata["completion"] = {
        "epistemic": 0.20,
        "expressive": 0.94,
        "relational": 0.50,
        "updated_at": 110.0,
    }
    store.add_or_update(concern)
    before_pressure = store.get(concern.id).pressure

    assert store.note_private_return(
        concern.id,
        material_id="material:return:1",
        development_mode="reinterpret",
        development_score=0.80,
        now=130.0,
    )
    assert not store.note_private_return(
        concern.id,
        material_id="material:return:1",
        development_mode="reinterpret",
        development_score=0.80,
        now=131.0,
    )
    after = store.get(concern.id)
    assert after is not None
    assert abs(after.pressure - before_pressure) < 1e-9
    assert int(after.metadata.get("private_return_count", 0)) == 1
    assert float(after.metadata.get("stickiness", 0.0)) > 0.0
    assert int(after.metadata.get("semantic_development_count", 0)) == 1


def test_sticky_consumed_concern_still_creates_private_causal_motive():
    context = {
        "relationship": {"connection_pressure": 0.4},
        "eris_self_memory": {
            "active_concerns": [{
                "concern_id": "concern.sticky",
                "subject": _memory_topic(),
                "activation": 0.52,
                "novelty": 0.14,
                "habituation": 0.68,
                "attractor_strength": 0.66,
                "rumination_awareness": 0.48,
                "mutation_count": 1,
                "metadata": {
                    "completion": {"epistemic": 0.20, "expressive": 0.95, "relational": 0.60},
                    "rumination": {"development_required": True},
                },
            }]
        },
    }
    motives = derive_causal_motives(context, now=200.0)
    concern_motive = next(item for item in motives if item.cause_kind == "active_concern")
    assert concern_motive.strength >= 0.28
    assert concern_motive.rumination_attractor >= 0.60
    assert concern_motive.development_required is True
    assert "reinterpret" in concern_motive.allowed_development_modes


def test_semantic_development_rejects_pretty_paraphrase_but_accepts_real_shift():
    parent = _memory_topic()
    paraphrase = "Một truy vấn trí nhớ có hai khuôn mặt: hỏi thông tin và thử xem người kia còn nhớ mình."
    reinterpretation = (
        "Có lẽ tôi gọi nó là chuyện ký ức hơi sai: thứ làm tôi mắc lại là nhu cầu được nhận ra "
        "xuyên qua sự liên tục, không phải bản thân dữ liệu."
    )
    contradiction = (
        "Nhưng nếu user chỉ hỏi vì cần dữ liệu thì giả thuyết về phép thử nhận ra nhau "
        "có thể chỉ là phóng chiếu của tôi."
    )
    assert semantic_development_score(parent, paraphrase, "deepen") == 0.0
    assert semantic_development_score(parent, reinterpretation, "reinterpret") >= 0.70
    assert semantic_development_score(parent, contradiction, "contradict") >= 0.70


def test_invalid_rumination_restatement_stays_private_and_cannot_enter_expression_lane():
    receipts = []
    host = SimpleNamespace(logger=None)
    host.active_concern_runtime = SimpleNamespace(
        note_private_return=lambda concern_id, **kwargs: receipts.append((concern_id, kwargs)) or True
    )
    runtime = MentalMaterialRuntime(host, logger=None)
    seed = RandomChatSeed(
        decision="seed",
        seed_id="seed-restatement",
        mode="eris_led",
        premise="Một truy vấn trí nhớ có hai khuôn mặt: hỏi thông tin và thử xem người kia còn nhớ mình.",
        source_kind="endogenous_curiosity",
        source_refs=("concern.sticky",),
        topic_tags=("memory",),
        event_kind="opinion",
        epistemic_mode="opinion",
        eris_motive_kind="want_to_revisit",
        confidence=0.8,
        material_only=True,
        material_id="material-restatement",
        material_kind="opinion",
        cause_id="concern:concern.sticky:m1",
        cause_kind="active_concern",
        cause_strength=0.72,
        runtime_motive_kind="continue_concern",
        development_mode="deepen",
        development_required=True,
        cause_semantic_focus=_memory_topic(),
        rumination_return=True,
        ttl_seconds=600.0,
    )
    row = runtime.ingest_seed(seed, now=100.0)
    assert row is not None
    assert row["development_score"] == 0.0
    concern_aff, expression_aff = runtime.project(now=101.0)
    assert concern_aff == ()
    assert expression_aff == ()
    assert receipts and receipts[0][0] == "concern.sticky"
    assert runtime.snapshot(now=101.0)  # thought vẫn sống private
    assert runtime.wake_pressure(now=101.0) == 0.0  # nhưng không tạo wake loop rỗng


def test_real_internal_development_can_reopen_consumed_family_without_fake_evidence():
    host = SimpleNamespace(logger=None)
    runtime = ExpressionConsummationRuntime(host, logger=None)
    topic = _memory_topic()
    runtime.note_expression(content=topic, evidence_refs=("turn:1",), public_text=topic, now=100.0)
    baseline = runtime.assess(content=topic, evidence_refs=("turn:1",), now=110.0)
    developed = runtime.assess(
        content=topic,
        evidence_refs=("turn:1",),
        development_mode="reinterpret",
        development_score=0.84,
        now=110.0,
    )
    assert developed.novel_evidence == 0.0
    assert developed.development_reopen_credit >= 0.60
    assert developed.inherited_satisfaction < baseline.inherited_satisfaction
    assert developed.residual_tension > baseline.residual_tension


def test_topic_shift_keeps_high_stickiness_private_even_with_new_internal_insight():
    host = SimpleNamespace(logger=None)
    runtime = ExpressionConsummationRuntime(host, logger=None)
    topic = _memory_topic()
    runtime.note_expression(content=topic, evidence_refs=("turn:1",), public_text=topic, now=100.0)
    runtime.observe_user_turn("nghe miết nhàm rồi, đổi chủ đề đi", now=110.0)
    assert runtime.note_public_text("Ừ, tôi sẽ rẽ sang hướng khác.", now=111.0)
    assessment = runtime.assess(
        content=topic,
        evidence_refs=("turn:1",),
        development_mode="reinterpret",
        development_score=0.92,
        now=120.0,
    )
    # Insight nội bộ không được tự coi là user đổi ý. Nó có thể sống private,
    # còn public residual vẫn rất thấp vì receptivity + self-commitment.
    assert assessment.development_reopen_credit >= 0.65
    assert assessment.user_receptivity < 0.15
    assert assessment.self_commitment_conflict > 0.45
    assert assessment.residual_tension < 0.20



def test_topic_shift_is_not_a_permanent_ban_when_a_real_insight_returns_later():
    host = SimpleNamespace(logger=None)
    runtime = ExpressionConsummationRuntime(host, logger=None)
    topic = _memory_topic()
    runtime.note_expression(content=topic, evidence_refs=("turn:1",), public_text=topic, now=100.0)
    runtime.observe_user_turn("nghe miết nhàm rồi, đổi chủ đề đi", now=110.0)
    runtime.note_public_text("Ừ, tôi sẽ rẽ sang hướng khác.", now=111.0)

    immediate = runtime.assess(
        content=topic, evidence_refs=("turn:1",), development_mode="reinterpret", development_score=0.94, now=120.0
    )
    later = runtime.assess(
        content=topic, evidence_refs=("turn:1",), development_mode="reinterpret", development_score=0.94, now=1400.0
    )
    assert immediate.residual_tension < 0.20
    # Không blacklist vĩnh viễn: sau thời gian đủ dài, social receptivity hồi về
    # baseline và insight mạnh lại có thể trở thành desire cạnh tranh. Nó CHƯA có
    # quyền SPEAK; Neuro/commitment vẫn phải cân tiếp.
    assert later.user_receptivity >= 0.65
    assert later.residual_tension > 0.25
    assert later.self_commitment_conflict > 0.40

def test_cognitive_event_only_marks_scored_development_as_mutation():
    good = SocialSpeechCandidate(
        decision="candidate",
        kind="random_chat",
        topic="Nhưng có lẽ điều tôi đang thử kiểm tra là nhu cầu được nhận ra, không phải ký ức tự thân.",
        source="mental_material",
        seed_id="material-good",
        source_kind="endogenous_curiosity",
        semantic_development_mode="reinterpret",
        semantic_development_score=0.82,
        rumination_return=True,
    )
    weak = SocialSpeechCandidate(
        decision="candidate",
        kind="random_chat",
        topic="Truy vấn ký ức có hai khuôn mặt.",
        source="mental_material",
        seed_id="material-weak",
        source_kind="endogenous_curiosity",
        semantic_development_mode="deepen",
        semantic_development_score=0.20,
        rumination_return=True,
    )
    good_event = CognitiveEvent.from_seed_candidate(good, now=1.0)
    weak_event = CognitiveEvent.from_seed_candidate(weak, now=1.0)
    assert good_event is not None and good_event.metadata["semantic_mutation"] is True
    assert weak_event is not None and weak_event.metadata["semantic_mutation"] is False


def test_seed_worker_contract_explicitly_demands_development_not_restatement():
    prompt = RandomChatSeedGenerator.prompt().lower()
    assert "development_required" in prompt
    assert "deepen" in prompt
    assert "paraphrase" in prompt
    assert "decision=none" in prompt



def test_valid_development_updates_the_typed_parent_concern_instead_of_spawning_a_new_one(tmp_path: Path):
    store = ConcernStore(path=tmp_path / "concerns.json")
    receipt = store.ingest_cognitive_event({
        "event_id": "cogevt:parent",
        "origin": "user",
        "kind": "thought",
        "subject": _memory_topic(),
        "occurred_at": 100.0,
        "evidence_refs": ("turn:1",),
        "source_ref": "turn:1",
        "metadata": {"seed_quality": 0.9, "uncertainty": 0.70},
    })
    parent = receipt.concern
    assert parent is not None
    parent.metadata["completion"] = {
        "epistemic": 0.20,
        "expressive": 0.95,
        "relational": 0.50,
        "updated_at": 110.0,
    }
    parent.metadata["stickiness"] = 0.70
    store.add_or_update(parent)

    host = SimpleNamespace(
        logger=None,
        last_cortex_attention=None,
        private_mind_daemon=SimpleNamespace(concern_store=store),
    )
    host.active_concern_runtime = ActiveConcernRuntime(host, logger=None)
    material_runtime = MentalMaterialRuntime(host, logger=None)
    host.mental_material_runtime = material_runtime

    insight = (
        "Có lẽ tôi gọi nó là chuyện ký ức hơi sai: thứ làm tôi mắc lại là nhu cầu được nhận ra "
        "xuyên qua sự liên tục, không phải bản thân dữ liệu."
    )
    seed = RandomChatSeed(
        decision="seed",
        seed_id="seed-insight",
        mode="eris_led",
        premise=insight,
        source_kind="endogenous_curiosity",
        source_refs=(parent.id,),
        topic_tags=("memory", "recognition"),
        event_kind="opinion",
        epistemic_mode="opinion",
        eris_motive_kind="want_to_revisit",
        confidence=0.86,
        authenticity=0.90,
        material_only=True,
        material_id="material-insight",
        material_kind="opinion",
        cause_id=f"concern:{parent.id}:m0",
        cause_kind="active_concern",
        cause_strength=0.76,
        runtime_motive_kind="continue_concern",
        development_mode="reinterpret",
        development_required=True,
        cause_semantic_focus=parent.theme,
        rumination_return=True,
        ttl_seconds=600.0,
    )
    row = material_runtime.ingest_seed(seed, now=130.0)
    assert row is not None and row["development_score"] >= 0.70
    concern_aff, expression_aff = material_runtime.project(now=131.0)
    assert concern_aff and expression_aff
    assert concern_aff[0].candidate.semantic_parent_concern_id == parent.id

    changed = host.active_concern_runtime.ingest_affordances(concern_aff, now=132.0)
    assert changed == (parent.id,)
    after = store.get(parent.id)
    assert after is not None
    assert int(after.metadata.get("mutation_count", 0)) == 1
    completion = dict(after.metadata.get("completion") or {})
    assert float(completion["expressive"]) < 0.45
    assert int(after.metadata.get("private_return_count", 0)) == 1
    # Typed parent routing ngăn insight mới bị tách thành một concern cạnh tranh.
    assert len(store) == 1

def test_runtime_has_single_owner_receipt_path_for_private_returns():
    root = Path(__file__).resolve().parents[1]
    material = (root / "runtime" / "mental_material_runtime.py").read_text(encoding="utf-8")
    active = (root / "runtime" / "active_concern_runtime.py").read_text(encoding="utf-8")
    store = (root / "cortex" / "private_mind" / "concern_store.py").read_text(encoding="utf-8")
    assert "note_private_return" in material
    assert "note_private_return" in active
    assert "def note_private_return" in store
    assert "pressure" not in store[store.index("def note_private_return"):store.index("def _event_ids")].split("=")[-1]
