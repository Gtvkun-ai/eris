from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from runtime.ai_orchestrated.cognitive_blackboard import TypedCognitiveBlackboard
from runtime.ai_orchestrated.grounding_validator import AutonomousGroundingValidator
from runtime.ai_orchestrated.contracts import IntentionPlan
from runtime.ai_orchestrated.initiative import InitiativeAction, InitiativeController, SpeechIntent
from runtime.ai_orchestrated.social_candidate import SocialSpeechCandidate
from runtime.ai_orchestrated.surface_intent import SurfaceIntentEngine


def _snapshot(**overrides):
    data = {
        "time": 1000.0,
        "telemetry": {},
        "screen_context": {
            "fresh": False,
            "privacy_blocked": False,
            "meaningful_delta": False,
            "window_changed": False,
            "window_title": "",
            "evidence_refs": [],
        },
        "conversation_baton": {
            "reply_expected": False,
            "assistant_may_continue": False,
            "thread_fresh": False,
            "thread_key": "none",
        },
        "activity_session": {"new_event_keys": []},
        "self_context": {
            "has_public_seed": False,
            "strongest_seed_score": 0.0,
            "attention": {},
            "agenda": [],
            "private_mind_surface": [],
            "private_life_surface": [],
        },
        "discovery": {},
        "commentary_expectation": {
            "due": False,
            "required": False,
            "reason": "cadence_not_due",
            "anchor_kind": "persona_presence",
        },
        "engagement_context": {"active": False},
        "engagement_interaction": {},
        "seconds_since_user": 120.0,
        "seconds_since_assistant": 120.0,
        "memory_context": "",
        "open_loops": [],
        "recent_public_history": [],
    }
    data.update(overrides)
    return data



def _social_agenda_candidate() -> SocialSpeechCandidate:
    return SocialSpeechCandidate(
        decision="candidate",
        kind="social_agenda",
        topic="Advance one grounded shared bit without opening a new topic.",
        speech_act="advance_social_goal",
        anchor_type="conversation",
        anchor_id="goal:test",
        confidence=0.9,
        relevance=0.85,
        urgency=0.2,
        tone="soft_warm",
        reason="test_claimed_goal",
        source="social_agenda_store",
        continuation_lane="social_agenda",
        claim_token="goal:test:v2:worker",
        idempotency_key="goal:test:move:1",
    )

def test_blackboard_only_surfaces_public_safe_inner_seed():
    snapshot = _snapshot(
        self_context={
            "has_public_seed": True,
            "strongest_seed_score": 0.81,
            "attention": {"internal_drive": 0.7},
            "agenda": [],
            "private_mind_surface": [
                {
                    "id": "pm:1",
                    "topic_seed": "Một ý đã qua public surface valve",
                    "confidence": 0.82,
                    "score": 0.77,
                    "raw_chain_of_thought": "không được lọt qua",
                }
            ],
            "private_life_surface": [],
        }
    )
    board = TypedCognitiveBlackboard.from_snapshot(snapshot, now=1000.0)

    assert board.public_seed_ready is True
    assert board.anchors[0].kind == "self"
    payload = str(board.public_view())
    assert "Một ý đã qua public surface valve" in payload
    assert "raw_chain_of_thought" not in payload
    assert "không được lọt qua" not in payload


def test_controller_returns_no_op_without_anchor(tmp_path: Path):
    controller = InitiativeController(state_path=tmp_path / "initiative.json")
    board = TypedCognitiveBlackboard.from_snapshot(_snapshot(), now=1000.0)

    decision = controller.decide(board)

    assert decision.action is InitiativeAction.NO_OP
    assert decision.reason == "no_speech_candidate"


def test_controller_uses_body_only_when_user_busy_and_screen_changes(tmp_path: Path):
    controller = InitiativeController(state_path=tmp_path / "initiative.json")
    board = TypedCognitiveBlackboard.from_snapshot(
        _snapshot(
            telemetry={"user_busy": True},
            screen_context={
                "fresh": True,
                "privacy_blocked": False,
                "meaningful_delta": True,
                "window_changed": False,
                "window_title": "RimWorld",
                "evidence_refs": ["screen:1"],
            },
        ),
        now=1000.0,
    )

    decision = controller.decide(board)

    assert decision.action is InitiativeAction.BODY_ONLY
    assert decision.reason == "user_busy"
    assert decision.speech_intent is None


def test_controller_approves_speech_before_surface_worker(tmp_path: Path):
    controller = InitiativeController(state_path=tmp_path / "initiative.json")
    board = TypedCognitiveBlackboard.from_snapshot(
        _snapshot(
            commentary_expectation={
                "due": True,
                "required": True,
                "reason": "maximum_quiet_reached",
                "anchor_kind": "persona_presence",
            },
            seconds_since_user=180.0,
        ),
        now=1000.0,
    )

    decision = controller.decide(board, _social_agenda_candidate())

    assert decision.action is InitiativeAction.SPEECH
    assert decision.speech_intent is not None
    assert decision.speech_intent.mode == "random_chat"
    assert decision.plan.semantics.turn_kind == "social_agenda"


@dataclass
class _ReducerState:
    version: int = 0


class _Reducer:
    def snapshot(self):
        return _ReducerState()

    def submit(self, _event):
        return None


class _SurfaceRouter:
    def __init__(self):
        self.surface_client = object()
        self.requests = []

    def realize_surface_speech(self, request):
        self.requests.append(request)
        return {
            "text": "Im lâu vậy, tôi sắp tính phí làm vật trang trí rồi đó.",
            "confidence": 0.88,
            "performance_hint": "dry",
            "evidence_refs": [],
            "claim_manifest": [],
            "reason": "wording_complete",
        }

    def build_surface_public_payload(self, *, text, plan, mode):
        return {"text": text, "should_speak": True, "performance_hint": plan.performance_hint, "mode": mode}


class _EmptySurfaceRouter(_SurfaceRouter):
    def realize_surface_speech(self, request):
        self.requests.append(request)
        return {}


class _SentinelSurfaceRouter(_SurfaceRouter):
    def realize_surface_speech(self, request):
        self.requests.append(request)
        return {"_surface_unavailable_reason": "surface_primary_empty_or_invalid"}


class _ThrowingSurfaceRouter(_SurfaceRouter):
    def realize_surface_speech(self, request):
        self.requests.append(request)
        raise RuntimeError("surface transport broke")


class _ThinPresenceSurfaceRouter(_SurfaceRouter):
    def realize_surface_speech(self, request):
        self.requests.append(request)
        return {
            "text": "Toi day.",
            "confidence": 0.88,
            "performance_hint": "soft",
            "evidence_refs": [],
            "claim_manifest": [],
            "reason": "wording_complete",
        }


def test_surface_worker_only_realizes_approved_speech(tmp_path: Path):
    controller = InitiativeController(state_path=tmp_path / "initiative.json")
    board = TypedCognitiveBlackboard.from_snapshot(
        _snapshot(commentary_expectation={"due": True, "required": True, "reason": "maximum_quiet_reached", "anchor_kind": "persona_presence"}),
        now=1000.0,
    )
    decision = controller.decide(board, _social_agenda_candidate())
    router = _SurfaceRouter()
    engine = SurfaceIntentEngine(router, _Reducer())

    turn = engine.realize(decision.speech_intent, board, snapshot=_snapshot())

    assert turn is not None
    assert turn.public_payload["text"].startswith("Im lâu")
    request = router.requests[0]
    assert request["surface_contract"]["authority"] == "wording_only"
    assert request["surface_contract"]["fixed_mode"] == "random_chat"
    assert "decision" not in request["surface_contract"]


def test_surface_worker_records_empty_payload_reason(tmp_path: Path):
    controller = InitiativeController(state_path=tmp_path / "initiative.json")
    board = TypedCognitiveBlackboard.from_snapshot(
        _snapshot(commentary_expectation={"due": True, "required": True, "reason": "maximum_quiet_reached", "anchor_kind": "persona_presence"}),
        now=1000.0,
    )
    decision = controller.decide(board, _social_agenda_candidate())
    router = _EmptySurfaceRouter()
    engine = SurfaceIntentEngine(router, _Reducer())

    turn = engine.realize(decision.speech_intent, board, snapshot=_snapshot())

    assert turn is None
    assert engine.last_failure_reason == "surface_worker_empty_payload"


def test_surface_worker_preserves_router_unavailable_reason(tmp_path: Path):
    controller = InitiativeController(state_path=tmp_path / "initiative.json")
    board = TypedCognitiveBlackboard.from_snapshot(
        _snapshot(commentary_expectation={"due": True, "required": True, "reason": "maximum_quiet_reached", "anchor_kind": "persona_presence"}),
        now=1000.0,
    )
    decision = controller.decide(board, _social_agenda_candidate())
    router = _SentinelSurfaceRouter()
    engine = SurfaceIntentEngine(router, _Reducer())

    turn = engine.realize(decision.speech_intent, board, snapshot=_snapshot())

    assert turn is None
    assert engine.last_failure_reason == "surface_primary_empty_or_invalid"


def test_surface_worker_records_writer_exception_reason(tmp_path: Path):
    controller = InitiativeController(state_path=tmp_path / "initiative.json")
    board = TypedCognitiveBlackboard.from_snapshot(
        _snapshot(commentary_expectation={"due": True, "required": True, "reason": "maximum_quiet_reached", "anchor_kind": "persona_presence"}),
        now=1000.0,
    )
    decision = controller.decide(board, _social_agenda_candidate())
    router = _ThrowingSurfaceRouter()
    engine = SurfaceIntentEngine(router, _Reducer())

    turn = engine.realize(decision.speech_intent, board, snapshot=_snapshot())

    assert turn is None
    assert engine.last_failure_reason == "surface_writer_exception:RuntimeError"


def test_surface_worker_rejects_thin_presence_filler(tmp_path: Path):
    controller = InitiativeController(state_path=tmp_path / "initiative.json")
    board = TypedCognitiveBlackboard.from_snapshot(
        _snapshot(commentary_expectation={"due": True, "required": True, "reason": "maximum_quiet_reached", "anchor_kind": "persona_presence"}),
        now=1000.0,
    )
    decision = controller.decide(board, _social_agenda_candidate())
    router = _ThinPresenceSurfaceRouter()
    engine = SurfaceIntentEngine(router, _Reducer())

    turn = engine.realize(decision.speech_intent, board, snapshot=_snapshot())

    assert turn is None
    assert engine.last_failure_reason.startswith("surface_bad_utterance:")


def test_grounding_preflight_blocks_private_or_unready_anchor(tmp_path: Path):
    forged_board = TypedCognitiveBlackboard.from_snapshot(_snapshot(), now=1000.0)
    plan = IntentionPlan.from_mapping(
        {
            "plan_id": "forged:self",
            "speak": True,
            "motive": "inner_thought",
            "strategy": "share_public_safe_thought",
            "value_focus": "continuity",
            "topic": "private seed",
            "importance": 0.7,
            "intrusion_risk": 0.1,
            "confidence": 0.8,
            "performance_hint": "soft",
            "evidence_refs": [],
            "semantics": {
                "turn_kind": "internal",
                "speech_act": "share_public_safe_thought",
                "subject_key": "self:test",
                "evidence_scope": "self_context",
                "continuation_key": "none",
            },
        },
        channel="autonomous",
    )
    intent = SpeechIntent(
        plan=plan,
        mode="inner_thought",
        anchor_type="self",
        anchor_id="self:test",
        evidence_refs=(),
        max_sentences=1,
    )

    verdict = AutonomousGroundingValidator().validate_intent(intent, forged_board)

    assert verdict.allowed is False
    assert verdict.violation_code == "private_cognition_boundary"

def test_blackboard_reads_real_discovery_ready_to_share_contract():
    board = TypedCognitiveBlackboard.from_snapshot(
        _snapshot(
            discovery={
                "schema": "eris.discovery.v1",
                "ready_to_share": [
                    {
                        "discovery_id": "disc-123",
                        "lane": "fresh_curiosity",
                        "topic": "Một phát hiện đã được kiểm chứng",
                        "verified_summary": "Tóm tắt có nguồn",
                        "source": "tutor_gemini",
                        "source_confidence": 0.91,
                        "evidence": ["https://example.invalid/source"],
                    }
                ],
                "current_activity": {},
            }
        ),
        now=1000.0,
    )

    anchor = board.strongest_anchor()
    assert board.discovery_ready is True
    assert anchor is not None
    assert anchor.kind == "discovery"
    assert anchor.anchor_id == "disc-123"
    assert anchor.topic_seed == "Một phát hiện đã được kiểm chứng"
    assert anchor.confidence == 0.91
    assert anchor.metadata["lane"] == "fresh_curiosity"


def test_memory_worker_signal_becomes_grounded_memory_anchor(tmp_path: Path):
    snapshot = _snapshot(
        self_context={
            "has_public_seed": True,
            "strongest_seed_score": 0.79,
            "attention": {"internal_drive": 0.58},
            "agenda": [
                {
                    "id": "memory-seed-1",
                    "kind": "memory_resonance",
                    "summary": "Một kỷ niệm đã qua surface valve",
                    "confidence": 0.82,
                    "speech_value": 0.78,
                    "score": 0.76,
                    "evidence_refs": ["memory:episode-42"],
                }
            ],
            "private_mind_surface": [],
            "private_life_surface": [],
        },
        memory_context="episode-42: grounded recall",
    )
    board = TypedCognitiveBlackboard.from_snapshot(snapshot, now=1000.0)
    anchor = board.strongest_anchor()

    assert anchor is not None
    assert anchor.kind == "memory"
    assert anchor.evidence_refs == ("memory:episode-42",)

    decision = InitiativeController(state_path=tmp_path / "initiative.json").decide(board, None)
    assert decision.action is InitiativeAction.NO_OP
    assert decision.speech_intent is None
    assert decision.reason == "no_speech_candidate"


def test_memory_named_seed_without_provenance_stays_generic_self_anchor():
    board = TypedCognitiveBlackboard.from_snapshot(
        _snapshot(
            self_context={
                "has_public_seed": True,
                "strongest_seed_score": 0.8,
                "attention": {},
                "agenda": [],
                "private_mind_surface": [
                    {
                        "id": "vague-memory",
                        "source": "memory_resonance",
                        "topic_seed": "Hình như có chuyện cũ",
                        "confidence": 0.8,
                        "score": 0.8,
                        "evidence_refs": [],
                    }
                ],
                "private_life_surface": [],
            },
            memory_context="",
        ),
        now=1000.0,
    )

    anchor = board.strongest_anchor()
    assert anchor is not None
    assert anchor.kind == "self"


def test_blackboard_reports_observer_and_critic_without_raw_reasoning():
    board = TypedCognitiveBlackboard.from_snapshot(
        _snapshot(
            latest_observation={
                "source": "groq_observer_deep",
                "confidence": 0.83,
                "repair_needed": True,
                "notes": "public-safe observation",
                "reasoning_content": "raw reasoning must not pass",
            }
        ),
        now=1000.0,
    )

    view = board.public_view()
    background = view["background_cognition"]
    assert background["observer_ready"] is True
    assert background["critic_reviewed"] is True
    assert background["repair_pending"] is True
    assert "reasoning_content" not in str(view)
    assert "raw reasoning must not pass" not in str(view)


class _DuplicateThenFreshSurfaceRouter(_SurfaceRouter):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def realize_surface_speech(self, request):
        self.requests.append(request)
        self.calls += 1
        if self.calls == 1:
            return {
                "text": "Câu cũ đã nói rồi.",
                "confidence": 0.88,
                "performance_hint": "soft",
                "evidence_refs": [],
                "claim_manifest": [],
                "reason": "stale_surface_cache",
            }
        return {
            "text": "Ý mới này mới là điều tôi muốn nói lúc này.",
            "confidence": 0.90,
            "performance_hint": "soft",
            "evidence_refs": [],
            "claim_manifest": [],
            "reason": "rewrite_current_intent",
        }


def test_v62_surface_duplicate_gets_one_same_worker_rewrite_retry(tmp_path: Path):
    """Câu cũ của Surface không được biến một desire mới thành im lặng giả chết."""

    controller = InitiativeController(state_path=tmp_path / "initiative.json")
    board = TypedCognitiveBlackboard.from_snapshot(
        _snapshot(commentary_expectation={"due": True, "required": True, "reason": "maximum_quiet_reached", "anchor_kind": "persona_presence"}),
        now=1000.0,
    )
    decision = controller.decide(board, _social_agenda_candidate())
    router = _DuplicateThenFreshSurfaceRouter()
    engine = SurfaceIntentEngine(router, _Reducer())

    turn = engine.realize(
        decision.speech_intent,
        board,
        snapshot=_snapshot(),
        avoid_text="Câu cũ đã nói rồi.",
    )

    assert turn is not None
    assert router.calls == 2
    assert turn.public_payload["text"].startswith("Ý mới này")
    assert router.requests[1]["surface_contract"]["rewrite_required"] is True
    assert router.requests[1]["surface_retry"]["attempt"] == 2
    assert engine.last_failure_reason == ""


class _DuplicateTwiceSurfaceRouter(_DuplicateThenFreshSurfaceRouter):
    def realize_surface_speech(self, request):
        self.requests.append(request)
        self.calls += 1
        return {
            "text": "Câu cũ đã nói rồi.",
            "confidence": 0.88,
            "performance_hint": "soft",
            "evidence_refs": [],
            "claim_manifest": [],
            "reason": "still_stale",
        }


def test_v62_surface_duplicate_retry_is_bounded_to_two_calls(tmp_path: Path):
    controller = InitiativeController(state_path=tmp_path / "initiative.json")
    board = TypedCognitiveBlackboard.from_snapshot(
        _snapshot(commentary_expectation={"due": True, "required": True, "reason": "maximum_quiet_reached", "anchor_kind": "persona_presence"}),
        now=1000.0,
    )
    decision = controller.decide(board, _social_agenda_candidate())
    router = _DuplicateTwiceSurfaceRouter()
    engine = SurfaceIntentEngine(router, _Reducer())

    turn = engine.realize(
        decision.speech_intent,
        board,
        snapshot=_snapshot(),
        avoid_text="Câu cũ đã nói rồi.",
    )

    assert turn is None
    assert router.calls == 2
    assert engine.last_failure_reason == "surface_duplicate_recent_utterance"
