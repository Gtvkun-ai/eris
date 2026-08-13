# -*- coding: utf-8 -*-
"""Acceptance cho V69 Consummation / Residual Tension.

Mục tiêu không phải cấm lặp câu ở Surface, mà chứng minh state đổi sớm hơn:
- nói xong => semantic family kế thừa expressive completion;
- concern vẫn sống nhưng speech pressure giảm;
- evidence/user mở lại => residual tension quay lại;
- user chán/đổi chủ đề => receptivity + habituation đổi state;
- lời "tôi sẽ đổi chủ đề" của Eris trở thành self-commitment thật.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cortex.active_concern import private_concern_view
from cortex.private_mind.concern_store import ConcernStore
from runtime.expression_consummation import ExpressionConsummationRuntime
from runtime.expression_urge_runtime import ExpressionUrgeRuntime
from runtime.ai_orchestrated.affordance import ExecutiveAffordance
from runtime.ai_orchestrated.social_initiative import SocialSpeechCandidate


def _host():
    host = SimpleNamespace(logger=None)
    host.expression_consummation_runtime = ExpressionConsummationRuntime(host, logger=None)
    host.expression_urge_runtime = ExpressionUrgeRuntime(host, logger=None)
    return host


def _aff(aid: str, topic: str, *, refs=("turn:1",)) -> ExecutiveAffordance:
    return ExecutiveAffordance(
        affordance_id=aid,
        owner="random_chat_seed",
        revision=1,
        candidate=SocialSpeechCandidate(
            decision="candidate",
            kind="random_chat",
            topic=topic,
            speech_act="share_self_originated_thought",
            anchor_type="internal",
            anchor_id=aid,
            evidence_refs=tuple(refs),
            confidence=0.82,
            relevance=0.82,
            urgency=0.30,
            source="test",
            eris_motive_kind="want_to_share",
            personal_stake=0.62,
            authenticity=0.95,
            seed_quality_score=0.90,
            seed_specificity=0.84,
            seed_intrusion_risk=0.08,
        ),
    )


def _topics(rows):
    return [str(item.candidate.topic) for item in rows if getattr(item, "candidate", None) is not None]


def test_expression_consumes_semantic_family_before_new_commitment_is_built():
    host = _host()
    runtime = host.expression_urge_runtime
    topic = "Một truy vấn trí nhớ đôi khi vừa hỏi thông tin vừa thử xem người kia có thực sự nhớ mình không."
    shaped = runtime.shape_affordances((_aff("a", topic),), now=100.0)
    assert len(shaped) == 1
    urge_id = shaped[0].candidate.expression_urge_id
    assert runtime.note_expressed(urge_id, public_text=topic, now=110.0)

    paraphrase = "Truy vấn trí nhớ có thể có hai lớp: lấy thông tin và kiểm tra liệu người nghe còn nhớ mình."
    shaped2 = runtime.shape_affordances((_aff("b", paraphrase),), now=120.0)
    # Ý đã consummate không còn là desire-to-speak mới. V67 vẫn đúng: cái gì đã
    # thành commitment thì SPEAK; V69 chỉ không materialize desire đã hoàn tất.
    assert not [row for row in shaped2 if getattr(row, "owner", "") == "expression_urge"]
    snap = runtime.snapshot(now=120.0)
    assert snap and snap[0]["satisfaction"] >= 0.88
    assert snap[0]["consummation"]["semantic_satiation"] >= 0.55


def test_new_substantive_evidence_reopens_same_semantic_family():
    host = _host()
    runtime = host.expression_urge_runtime
    topic = "Một truy vấn trí nhớ có thể là phép thử nhận ra nhau chứ không chỉ lấy dữ liệu."
    shaped = runtime.shape_affordances((_aff("a", topic, refs=("turn:1",)),), now=100.0)
    runtime.note_expressed(shaped[0].candidate.expression_urge_id, public_text=topic, now=110.0)

    changed = "Truy vấn trí nhớ lại trở nên đáng nói khi một lượt mới cho thấy user đang kiểm tra việc được nhớ."
    reopened = runtime.shape_affordances((_aff("b", changed, refs=("turn:2",)),), now=130.0)
    assert [row for row in reopened if getattr(row, "owner", "") == "expression_urge"]
    snap = runtime.snapshot(now=130.0)[0]
    assert snap["consummation"]["novel_evidence"] > 0.0 or snap["consummation"]["reopen_credit"] > 0.0


def test_user_topic_satiation_suppresses_old_family_without_blocking_new_topic():
    host = _host()
    runtime = host.expression_urge_runtime
    old = "Một câu hỏi về ký ức có hai lớp: thông tin và phép thử xem người kia có nhớ mình."
    shaped = runtime.shape_affordances((_aff("old", old),), now=100.0)
    runtime.note_expressed(shaped[0].candidate.expression_urge_id, public_text=old, now=110.0)

    outcome = host.expression_consummation_runtime.observe_user_turn(
        "mấy cái này nghe miết nhàm, đổi chủ đề mới mẻ hơn đi", now=120.0
    )
    assert outcome["outcome"] == "topic_satiated"
    assert host.expression_consummation_runtime.note_public_text(
        "Ừ, tôi sẽ rẽ sang hướng khác.", now=121.0
    )

    old_again = _aff(
        "old2",
        "Truy vấn ký ức có hai khuôn mặt: hỏi dữ liệu và thử xem người đối diện còn nhớ mình.",
    )
    fresh = _aff(
        "fresh",
        "Tôi tò mò vì sao anh hay yêu cầu tự chấm điểm sau mỗi bài test; con số hay cách giải thích quan trọng hơn?",
        refs=("turn:3",),
    )
    rows = runtime.shape_affordances((old_again, fresh), now=130.0, limit=4)
    topics = "\n".join(_topics(rows)).lower()
    assert "tự chấm điểm" in topics
    assert "hai khuôn mặt" not in topics

    assessment = host.expression_consummation_runtime.assess(content=old, evidence_refs=("turn:1",), now=130.0)
    assert assessment.user_receptivity < 0.20
    assert assessment.self_commitment_conflict > 0.70


def test_user_can_explicitly_reopen_topic_after_shift():
    host = _host()
    cons = host.expression_consummation_runtime
    topic = "Một truy vấn trí nhớ có hai lớp: hỏi thông tin và thử xem người kia có nhớ mình."
    cons.note_expression(content=topic, evidence_refs=("turn:1",), public_text=topic, now=100.0)
    cons.observe_user_turn("đổi chủ đề đi, nghe hơi nhàm rồi", now=110.0)
    cons.note_public_text("Tôi sẽ đổi sang chuyện khác.", now=111.0)

    outcome = cons.observe_user_turn("nhưng tại sao truy vấn trí nhớ lại có hai lớp?", now=130.0)
    assert outcome["outcome"] == "user_reopens"
    assessment = cons.assess(content=topic, evidence_refs=("turn:1",), now=131.0)
    assert assessment.reopen_credit >= 0.70
    assert assessment.inherited_satisfaction < 0.40
    assert assessment.self_commitment_conflict < 0.10


def test_private_concern_remains_active_while_expression_completion_reduces_speech_pressure():
    base = SimpleNamespace(
        id="concern:test",
        theme="Một câu hỏi về ký ức vẫn khiến tôi suy nghĩ về việc được nhận ra.",
        pressure=0.72,
        uncertainty=0.58,
        recurrence=3,
        status="open",
        evidence_ids=("turn:1",),
        open_questions=(),
        created_at=100.0,
        updated_at=180.0,
        metadata={"event_count": 3, "mutation_count": 1, "last_event_at": 180.0, "last_mutation_at": 180.0},
    )
    before = private_concern_view(base, now=200.0)
    base.metadata["completion"] = {"epistemic": 0.15, "expressive": 0.92, "relational": 0.35, "updated_at": 195.0}
    after = private_concern_view(base, now=200.0)
    # Nội tâm không bị xóa chỉ vì đã nói.
    assert abs(after.activation - before.activation) < 1e-9
    assert abs(after.persistence - before.persistence) < 1e-9
    assert after.speech_pressure < before.speech_pressure * 0.40
    assert after.metadata["completion"]["residual_expression"] <= 0.10


def test_real_semantic_mutation_reopens_concern_completion(tmp_path: Path):
    store = ConcernStore(path=tmp_path / "concerns.json")
    first = store.ingest_cognitive_event({
        "event_id": "cogevt:1",
        "origin": "user",
        "kind": "thought",
        "subject": "Truy vấn trí nhớ có thể vừa hỏi thông tin vừa kiểm tra việc được nhớ.",
        "occurred_at": 100.0,
        "evidence_refs": ("turn:1",),
        "source_ref": "turn:1",
        "metadata": {"seed_quality": 0.8},
    })
    concern = first.concern
    assert concern is not None
    concern.metadata["completion"] = {"epistemic": 0.4, "expressive": 0.9, "relational": 0.6, "updated_at": 110.0}
    store.add_or_update(concern)

    second = store.ingest_cognitive_event({
        "event_id": "cogevt:2",
        "origin": "user",
        "kind": "thought",
        "subject": "Truy vấn trí nhớ có thể vừa hỏi thông tin vừa kiểm tra việc được nhớ.",
        "occurred_at": 130.0,
        "evidence_refs": ("turn:2",),
        "source_ref": "turn:2",
        "metadata": {"seed_quality": 0.8, "semantic_mutation": True},
    })
    assert second.concern is not None
    assert second.mutation is True
    completion = dict(second.concern.metadata.get("completion") or {})
    assert 0.30 <= float(completion["expressive"]) <= 0.45
    assert float(completion["epistemic"]) < 0.30


def test_runtime_hooks_are_before_commitment_and_after_public_receipt():
    root = Path(__file__).resolve().parents[1]
    urge = (root / "runtime" / "expression_urge_runtime.py").read_text(encoding="utf-8")
    pipeline = (root / "runtime" / "ai_orchestrated" / "self_turn_pipeline.py").read_text(encoding="utf-8")
    orchestrator = (root / "runtime" / "ai_orchestrated" / "orchestrator.py").read_text(encoding="utf-8")
    assert "_inherit_consummation" in urge
    assert "commitment_payload(" in urge
    assert urge.index("_inherit_consummation") < urge.index("commitment_payload(", urge.index("def shape_affordances"))
    assert "public_text=text" in pipeline
    assert "observe_consumption(user_text" in orchestrator
    assert "note_public_text(public_text" in orchestrator
