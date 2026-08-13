from __future__ import annotations

from types import SimpleNamespace

from runtime.expression_urge_runtime import ExpressionUrgeRuntime
from runtime.ai_orchestrated.affordance import ExecutiveAffordance
from runtime.ai_orchestrated.social_initiative import SocialSpeechCandidate
from runtime.subject_proposals import AutonomousProposalSource


def _aff(
    aid: str,
    topic: str,
    *,
    act: str = "share_self_originated_thought",
    refs=("turn:1",),
    motive: str = "want_to_share",
    relevance: float = 0.72,
    confidence: float = 0.80,
):
    return ExecutiveAffordance(
        affordance_id=aid,
        owner="random_chat_seed",
        revision=1,
        candidate=SocialSpeechCandidate(
            decision="candidate",
            kind="random_chat",
            topic=topic,
            speech_act=act,
            anchor_type="internal",
            anchor_id=aid,
            evidence_refs=tuple(refs),
            confidence=confidence,
            relevance=relevance,
            urgency=0.24,
            source="test",
            eris_motive_kind=motive,
            personal_stake=0.58,
            authenticity=0.90,
            seed_quality_score=0.88,
            seed_specificity=0.78,
            seed_intrusion_risk=0.10,
        ),
    )


def _runtime():
    return ExpressionUrgeRuntime(SimpleNamespace(logger=None), logger=None)


def test_generic_contact_pressure_cannot_create_public_content():
    runtime = _runtime()
    generic = ExecutiveAffordance(
        affordance_id="generic-contact",
        owner="subject_initiative",
        revision=1,
        candidate=SocialSpeechCandidate(
            decision="candidate",
            kind="social_check_in",
            topic="Make one low-pressure contact bid because connection currently matters; do not invent context.",
            speech_act="contact_bid",
            evidence_refs=("relationship:state",),
            confidence=0.9,
            relevance=0.9,
        ),
    )
    shaped = runtime.shape_affordances(
        (generic,),
        relational={"connection_pressure": 0.98, "outreach_drive": 0.92},
        affect={"social_energy": 0.8},
        now=100.0,
    )
    assert shaped == ()
    assert runtime.snapshot(now=100.0) == ()


def test_contentful_concern_becomes_expression_urge_not_contact_bid():
    runtime = _runtime()
    concerns = ({
        "concern_id": "concern:neurons",
        "subject": "Cái câu tổng của những neuron chạy ngầm vẫn mắc trong đầu vì nó vừa giản dị vừa hơi khó chịu.",
        "activation": 0.66,
        "novelty": 0.72,
        "speech_pressure": 0.58,
        "habituation": 0.0,
        "state": "simmering",
        "age_seconds": 95.0,
        "mutation_count": 1,
        "evidence_refs": ("turn:105",),
        "source_kinds": ("thought_stream",),
        "metadata": {"event_count": 2},
    },)
    shaped = runtime.shape_affordances(
        (), active_concerns=concerns,
        relational={"connection_pressure": 0.70, "outreach_drive": 0.55},
        affect={"curiosity": 0.62, "social_energy": 0.55},
        now=200.0,
    )
    assert len(shaped) == 1
    cand = shaped[0].candidate
    assert cand.source == "expression_urge"
    assert cand.expression_urge_id
    assert cand.expression_pressure > 0.50
    assert cand.speech_act != "contact_bid"
    assert cand.speech_act != "user_probe"
    assert "neuron" in cand.topic.lower()



def test_mental_material_concern_lane_does_not_become_expression_desire():
    runtime = _runtime()
    topic = "Một thought đủ đáng giữ làm concern nhưng owner chưa đánh dấu nó là expression-ready."
    concern_only = ExecutiveAffordance(
        affordance_id="mental-material-concern:test",
        owner="mental_material",
        revision=1,
        candidate=SocialSpeechCandidate(
            decision="candidate",
            kind="inner_thought",
            topic=topic,
            speech_act="internal_material",
            anchor_type="internal",
            anchor_id="material:test",
            evidence_refs=("material:test",),
            confidence=0.8,
            relevance=0.7,
            urgency=0.3,
            source="mental_material",
        ),
        metadata={"mental_material": True, "material_id": "material:test", "expression_ready": False},
    )
    assert runtime.shape_affordances((concern_only,), now=100.0) == ()
    assert runtime.snapshot(now=100.0) == ()


def test_mental_material_expression_lane_can_form_expression_desire():
    runtime = _runtime()
    topic = "Một thought đã được MentalMaterial owner đánh dấu expression-ready thì được phép thành desire biểu đạt."
    ready = ExecutiveAffordance(
        affordance_id="mental-material-expression:test",
        owner="mental_material",
        revision=1,
        candidate=SocialSpeechCandidate(
            decision="candidate",
            kind="inner_thought",
            topic=topic,
            speech_act="share_self_originated_thought",
            anchor_type="internal",
            anchor_id="material:test",
            evidence_refs=("material:test",),
            confidence=0.8,
            relevance=0.7,
            urgency=0.3,
            source="mental_material",
            seed_specificity=0.8,
        ),
        metadata={"mental_material": True, "material_id": "material:test", "expression_ready": True},
    )
    shaped = runtime.shape_affordances((ready,), now=100.0)
    assert len(shaped) == 1
    assert shaped[0].owner == "expression_urge"
    assert shaped[0].metadata["expression_commitment"]["origin"] == "expression_urge"

def test_paraphrase_same_evidence_merges_and_does_not_pump_novelty():
    runtime = _runtime()
    a = _aff(
        "seed:a",
        "Tôi vẫn nghĩ việc gọi con người là tổng của neuron vừa đúng vừa làm mất đi phần trải nghiệm.",
        refs=("turn:105",),
    )
    b = _aff(
        "seed:b",
        "Gọi con người là tổng của neuron có vẻ đúng nhưng cũng làm phần trải nghiệm biến mất.",
        refs=("turn:105",),
    )
    runtime.shape_affordances((a,), now=100.0)
    first = runtime.snapshot(now=100.0)[0]
    runtime.shape_affordances((b,), now=110.0)
    snap = runtime.snapshot(now=110.0)
    assert len(snap) == 1
    assert snap[0]["echo_count"] >= 1
    assert snap[0]["freshness"] < first["freshness"]


def test_new_evidence_can_reinforce_same_urge():
    runtime = _runtime()
    a = _aff("seed:a", "Cái ý về neuron và cái tôi vẫn còn đáng nghĩ thêm một chút.", refs=("turn:1",))
    b = _aff("seed:b", "Ý về neuron và cái tôi vẫn còn đáng nghĩ thêm một chút.", refs=("turn:2",))
    runtime.shape_affordances((a,), now=100.0)
    first = runtime.snapshot(now=100.0)[0]
    runtime.shape_affordances((b,), now=110.0)
    second = runtime.snapshot(now=110.0)[0]
    assert second["echo_count"] == 0
    assert second["freshness"] >= first["freshness"]


def test_held_urge_accumulates_some_pressure_then_expression_satisfies_it():
    runtime = _runtime()
    runtime.shape_affordances(
        (_aff("seed:hold", "Tôi muốn chia sẻ một nhận xét cụ thể về cách câu trả lời ngắn làm đổi nhịp cuộc trò chuyện."),),
        relational={"connection_pressure": 0.25},
        affect={"social_energy": 0.45},
        now=100.0,
    )
    p1 = runtime.snapshot(now=100.0)[0]["pressure"]
    p2 = runtime.snapshot(now=220.0)[0]["pressure"]
    assert p2 > p1
    urge_id = runtime.snapshot(now=220.0)[0]["urge_id"]
    assert runtime.note_expressed(urge_id, now=221.0)
    after = runtime.snapshot(now=221.0)[0]
    assert after["satisfaction"] >= 0.70
    assert after["pressure"] < p2


def test_expression_pressure_reaches_subject_proposal_as_positive_utility():
    runtime = _runtime()
    shaped = runtime.shape_affordances(
        (_aff("seed:proposal", "Tôi vẫn còn một ý cụ thể muốn nói về việc im lặng chỉ có nghĩa khi thật sự có lựa chọn nói."),),
        relational={"connection_pressure": 0.65, "outreach_drive": 0.50},
        affect={"curiosity": 0.55, "social_energy": 0.60},
        now=100.0,
    )
    assert shaped
    candidate = shaped[0].candidate
    proposal = AutonomousProposalSource.from_affordance(shaped[0], turn_id="auto:v44")
    assert proposal is not None
    assert proposal["arguments"]["expression_urge_id"] == candidate.expression_urge_id
    assert proposal["arguments"]["expression_pressure"] == candidate.expression_pressure
    assert proposal["expected_need_relief"] > candidate.relevance
    assert proposal["value_congruence"] > 0.50


def test_curiosity_urge_defaults_to_sharing_not_interrogating_user():
    runtime = _runtime()
    shaped = runtime.shape_affordances(
        (_aff(
            "seed:q",
            "Nếu một câu trả lời ngắn vẫn giữ được trọng lượng, có lẽ độ dài không phải thứ quyết định chiều sâu.",
            act="curiosity_question",
            motive="want_to_explore",
        ),),
        affect={"curiosity": 0.8, "social_energy": 0.6},
        now=100.0,
    )
    assert shaped[0].candidate.expression_motive == "explore"
    assert shaped[0].candidate.speech_act == "share_self_originated_thought"


def test_v44_self_turn_uses_contentful_urge_as_wake_authority():
    """Không cho generic relation/contact quay lại làm nguồn wake/speech ngầm."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "runtime" / "ai_orchestrated" / "self_turn_pipeline.py"
    text = src.read_text(encoding="utf-8")
    assert '"expression_urge",' in text
    assert 'snapshot.get("expression_urge_pressure"' in text
    assert 'emit("relational_pressure"' not in text
    assert 'preview_understand' not in text
    assert 'build_relational_affordance' not in text
    # Policy chỉ được project sau content-first shaping, không có hai authority
    # snapshot cho cùng một tick.
    assert text.count("initiative_policy.policy_signals(blackboard, affordances)") == 1


def test_contentful_urge_can_change_neuro_winner_without_lowering_silence_threshold():
    """Urge là utility dương thật, không chỉ telemetry đẹp mắt."""
    from types import SimpleNamespace
    from cortex.subject.neuro_control import NeuroActionSelector

    def coalition(action: str, score: float, arguments: dict):
        return SimpleNamespace(
            action_kind=action,
            score=score,
            expected_pragmatic_value=0.50,
            expected_epistemic_value=0.20,
            uncertainty=0.20,
            arguments=arguments,
            proposal_refs=(),
        )

    base_speak = coalition("speak", 0.40, {})
    silence = coalition("silence", 0.48, {})
    frame = SimpleNamespace(
        coalitions=(base_speak, silence),
        appraisals=(),
        activations=(),
        proposals=(),
        substrate=SimpleNamespace(processing_capacity=1.0),
        observation=SimpleNamespace(context={"runtime_context": {}}, origin="internal"),
    )
    selector = NeuroActionSelector()
    before = selector.select(frame)
    assert frame.coalitions[before.winner_index].action_kind == "silence"

    urge_speak = coalition(
        "speak",
        0.40,
        {
            "expression_urge_id": "urge:test",
            "expression_pressure": 0.80,
            "expression_freshness": 0.80,
            "expression_satisfaction": 0.0,
        },
    )
    after_frame = SimpleNamespace(**{**frame.__dict__, "coalitions": (urge_speak, silence)})
    after = selector.select(after_frame)
    assert after_frame.coalitions[after.winner_index].action_kind == "speak"
    assert after.scores[0] > before.scores[0]


def test_v44_1_effective_freshness_decays_without_new_input():
    runtime = _runtime()
    runtime.shape_affordances(
        (_aff("seed:aging", "Tôi có một ý cụ thể muốn chia sẻ nhưng nếu không có gì mới thì nó phải tự già đi."),),
        relational={"connection_pressure": 0.55},
        affect={"curiosity": 0.55, "social_energy": 0.55},
        now=100.0,
    )
    first = runtime.snapshot(now=100.0, relational={"connection_pressure": 0.55})[0]
    later = runtime.snapshot(now=400.0, relational={"connection_pressure": 0.55})[0]
    assert first["freshness"] > 0.70
    assert later["freshness"] < 0.30
    assert later["priority"] < first["priority"]


def test_v44_1_new_relevant_urge_preempts_old_high_pressure_urge():
    runtime = _runtime()
    rel = {"connection_pressure": 0.60, "outreach_drive": 0.55}
    aff = {"curiosity": 0.60, "social_energy": 0.60}
    runtime.shape_affordances(
        (_aff(
            "seed:old",
            "Tôi vẫn còn nghĩ về chuyện một câu trả lời ngắn có giữ được trọng lượng hay không.",
            relevance=0.65,
        ),),
        relational=rel,
        affect=aff,
        now=100.0,
    )
    # Cho urge cũ đủ thời gian tích pressure nhưng đồng thời mất freshness.
    old_later = runtime.snapshot(now=320.0, relational=rel, affect=aff)[0]
    assert old_later["pressure"] > 0.60
    assert old_later["freshness"] < 0.50

    runtime.shape_affordances(
        (_aff(
            "seed:new",
            "Bạn vừa bảo tôi chủ động kiếm chuyện, nên tôi đang muốn mang sang một ý mới ngay từ turn này.",
            refs=("turn:new",),
            relevance=0.95,
            confidence=0.90,
        ),),
        relational=rel,
        affect=aff,
        now=320.0,
    )
    ranked = runtime.snapshot(now=320.0, relational=rel, affect=aff)
    assert ranked[0]["evidence_refs"] == ["turn:new"]
    assert ranked[0]["priority"] > ranked[1]["priority"]


def test_v44_1_ready_urge_can_beat_strong_silence_when_baton_is_open():
    from types import SimpleNamespace
    from cortex.subject.neuro_control import NeuroActionSelector

    def coalition(action: str, score: float, arguments: dict):
        return SimpleNamespace(
            action_kind=action,
            score=score,
            expected_pragmatic_value=0.50,
            expected_epistemic_value=0.20,
            uncertainty=0.20,
            arguments=arguments,
            proposal_refs=(),
        )

    speak = coalition(
        "speak",
        0.40,
        {
            "expression_urge_id": "urge:ready",
            "expression_pressure": 1.0,
            "expression_freshness": 0.85,
            "expression_satisfaction": 0.0,
            "expression_readiness": 0.93,
        },
    )
    silence = coalition("silence", 0.64, {})
    frame = SimpleNamespace(
        coalitions=(speak, silence),
        appraisals=(),
        activations=(),
        proposals=(),
        substrate=SimpleNamespace(processing_capacity=1.0),
        observation=SimpleNamespace(
            context={"runtime_context": {"reply_expected": False, "user_busy": False}},
            origin="internal",
        ),
    )
    result = NeuroActionSelector().select(frame)
    assert frame.coalitions[result.winner_index].action_kind == "speak"


def test_v66_reply_expected_does_not_veto_ready_expression_urge():
    """Chờ câu trả lời không phải quyền giữ floor; collision thật mới được veto."""
    from types import SimpleNamespace
    from cortex.subject.neuro_control import NeuroActionSelector

    def coalition(action: str, score: float, arguments: dict):
        return SimpleNamespace(
            action_kind=action,
            score=score,
            expected_pragmatic_value=0.50,
            expected_epistemic_value=0.20,
            uncertainty=0.20,
            arguments=arguments,
            proposal_refs=(),
        )

    speak = coalition(
        "speak",
        0.40,
        {
            "expression_urge_id": "urge:ready",
            "expression_pressure": 1.0,
            "expression_freshness": 0.85,
            "expression_satisfaction": 0.0,
            "expression_readiness": 0.93,
        },
    )
    silence = coalition("silence", 0.64, {})
    frame = SimpleNamespace(
        coalitions=(speak, silence),
        appraisals=(),
        activations=(),
        proposals=(),
        substrate=SimpleNamespace(processing_capacity=1.0),
        observation=SimpleNamespace(
            context={"runtime_context": {"reply_expected": True, "user_busy": False}},
            origin="internal",
        ),
    )
    result = NeuroActionSelector().select(frame)
    assert frame.coalitions[result.winner_index].action_kind == "speak"


def test_v66_duplicate_wording_failure_preserves_expression_urge():
    runtime = _runtime()
    thought = _aff(
        "seed:zombie",
        "Thử kết nối những hồi ức, không phải để tìm câu trả lời, mà để kiểm tra cách đặt câu hỏi khác đi.",
        refs=("turn:1",),
    )
    shaped = runtime.shape_affordances((thought,), now=100.0)
    urge_id = shaped[0].candidate.expression_urge_id
    assert runtime.note_surface_duplicate(urge_id, now=101.0) is True

    # V66: wording bị trùng chỉ là realization failure. Ý muốn nói vẫn sống và
    # không cần user/evidence mới để "xin lại quyền" biểu đạt.
    retry = runtime.shape_affordances((thought,), now=110.0)
    assert retry
    assert retry[0].candidate.expression_urge_id == urge_id
    snap = runtime.snapshot(now=110.0)[0]
    assert snap["surface_blocked_seconds"] == 0
    assert snap["surface_duplicate_blocks"] == 1


def test_v61_structured_environment_meaning_preempts_stale_internal_urge():
    runtime = _runtime()
    old = _aff(
        "seed:old",
        "Thử kết nối những hồi ức, không phải để tìm câu trả lời, mà để kiểm tra cách đặt câu hỏi khác đi.",
        refs=("turn:old",),
        relevance=0.85,
        confidence=0.90,
    )
    runtime.shape_affordances((old,), now=100.0, relational={"connection_pressure": 0.5}, affect={"curiosity": 0.6})

    env = ExecutiveAffordance(
        affordance_id="subject-intention:env",
        owner="subject_initiative",
        revision=2,
        candidate=SocialSpeechCandidate(
            decision="candidate",
            kind="screen_comment",
            topic="User đang xem source initiative của Eris; có thể chia sẻ một quan sát ngắn liên quan trực tiếp phần đó.",
            speech_act="environment_self_reflection",
            anchor_type="environment",
            anchor_id="intention:env",
            evidence_refs=("environment:structured:1",),
            requires_grounding=True,
            confidence=0.70,
            relevance=0.66,
            urgency=0.50,
            source="subject_initiative",
            eris_motive_kind="share",
            personal_stake=0.66,
            authenticity=1.0,
        ),
        claim_required=False,
        expires_at=999.0,
        metadata={"environment_grounded": True},
    )
    shaped = runtime.shape_affordances(
        (env,), now=110.0,
        relational={"connection_pressure": 0.5}, affect={"curiosity": 0.6}, limit=3,
    )
    assert shaped
    assert shaped[0].candidate.anchor_type == "internal"  # urge projection owns the final candidate
    assert "source initiative" in shaped[0].candidate.topic.lower()
    snap = runtime.snapshot(now=110.0)
    assert any(item["environment_grounded"] for item in snap)
