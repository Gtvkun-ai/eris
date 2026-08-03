from __future__ import annotations

from pathlib import Path

from runtime.ai_orchestrated.cognitive_blackboard import TypedCognitiveBlackboard
from runtime.ai_orchestrated.grounding_validator import AutonomousGroundingValidator
from runtime.ai_orchestrated.initiative import InitiativeAction, InitiativeController
from runtime.ai_orchestrated.social_initiative import SocialInitiativeEngine, SocialSpeechCandidate
from runtime.ai_orchestrated.surface_intent import SurfaceIntentEngine


def _snapshot(**overrides):
    data = {
        "time": 1000.0,
        "telemetry": {},
        "screen_context": {
            "fresh": True,
            "privacy_blocked": False,
            "meaningful_delta": False,
            "window_changed": False,
            "window_title": "Brave - moc3 discussion",
            "evidence_refs": ["screen:raw-title"],
        },
        "vision_grounding": {
            "recommendation": "silence",
            "evidence_strength": 0.0,
            "claims": [],
        },
        "conversation_baton": {
            "reply_expected": False,
            "assistant_may_continue": False,
            "thread_fresh": False,
            "thread_key": "none",
        },
        "activity_session": {"has_new_event": False, "new_event_keys": []},
        "self_context": {"has_public_seed": False, "attention": {}},
        "discovery": {},
        "commentary_expectation": {"due": False, "required": False},
        "engagement_context": {"active": False},
        "engagement_interaction": {},
        "latest_observation": {},
        "seconds_since_user": 30.0,
        "seconds_since_assistant": 30.0,
        "open_loops": [],
        "recent_public_history": [],
    }
    data.update(overrides)
    return data


def test_raw_window_title_never_becomes_screen_speech_anchor():
    snapshot = _snapshot(
        screen_context={
            "fresh": True,
            "privacy_blocked": False,
            "meaningful_delta": True,
            "window_changed": True,
            "window_title": "Chỉnh sửa moc3 elegant - Brave",
            "evidence_refs": ["screen:raw-title"],
        }
    )
    board = TypedCognitiveBlackboard.from_snapshot(snapshot, now=1000.0)

    assert board.mechanical_delta is True
    assert all(anchor.kind != "screen" for anchor in board.anchors)
    assert board.public_view()["screen_title"] == ""


def test_grounded_claim_creates_screen_anchor_with_real_provenance():
    snapshot = _snapshot(
        screen_context={
            "fresh": True,
            "privacy_blocked": False,
            "meaningful_delta": True,
            "window_changed": True,
            "window_title": "Brave",
            "evidence_refs": ["screen:raw-title"],
        },
        vision_grounding={
            "recommendation": "speak",
            "evidence_strength": 0.88,
            "claims": [
                {
                    "claim_id": "claim:1",
                    "text": "Một trang thảo luận về chỉnh sửa mô hình Live2D đang hiển thị.",
                    "grounded": True,
                    "stale": False,
                    "evidence_ids": ["ocr:live2d-topic"],
                }
            ],
        },
    )
    board = TypedCognitiveBlackboard.from_snapshot(snapshot, now=1000.0)

    anchor = next(anchor for anchor in board.anchors if anchor.kind == "screen")
    assert anchor.topic_seed.startswith("Một trang thảo luận")
    assert anchor.evidence_refs == ("ocr:live2d-topic",)
    assert "Brave" not in board.public_view()["screen_title"]


def test_governor_does_not_invent_topic_when_candidate_is_explicitly_missing(tmp_path: Path):
    board = TypedCognitiveBlackboard.from_snapshot(
        _snapshot(commentary_expectation={"due": True, "required": True}),
        now=1000.0,
    )
    controller = InitiativeController(state_path=tmp_path / "initiative.json")

    decision = controller.decide(board, None)

    assert decision.action is InitiativeAction.NO_OP
    assert decision.reason == "no_speech_candidate"


def test_social_candidate_can_speak_without_factual_grounding(tmp_path: Path):
    board = TypedCognitiveBlackboard.from_snapshot(
        _snapshot(seconds_since_user=400.0, seconds_since_assistant=400.0),
        now=1000.0,
    )
    candidate = SocialSpeechCandidate(
        decision="candidate",
        kind="casual_curiosity",
        topic="Ask one light question about what the user feels like talking about now.",
        speech_act="casual_curiosity",
        anchor_type="idle",
        anchor_id="shared_quiet",
        requires_grounding=False,
        confidence=0.8,
        relevance=0.7,
        urgency=0.15,
        tone="casual_warm",
        reason="quiet_period",
    )
    decision = InitiativeController(state_path=tmp_path / "initiative.json").decide(board, candidate)

    assert decision.action is InitiativeAction.SPEECH
    assert decision.speech_intent is not None
    assert decision.speech_intent.anchor_type == "idle"
    assert AutonomousGroundingValidator().validate_intent(decision.speech_intent, board).allowed is True


class _NoSurfaceRouter:
    surface_client = None


def test_liveness_fallback_is_silent_by_default():
    """Seed/worker chết thì random chat im; không dựng liveness candidate ngầm."""
    board = TypedCognitiveBlackboard.from_snapshot(
        _snapshot(seconds_since_user=900.0, seconds_since_assistant=900.0),
        now=1000.0,
    )
    candidate = SocialInitiativeEngine(_NoSurfaceRouter()).propose(board, snapshot=_snapshot())

    assert candidate is None


def test_legacy_liveness_fallback_remains_behind_flag(monkeypatch):
    """Đường cũ còn để rollback, nhưng phải bật flag rõ ràng."""
    import runtime.architecture_flags as architecture_flags

    monkeypatch.setattr(architecture_flags, "legacy_social_fallback_enabled", lambda: True)
    board = TypedCognitiveBlackboard.from_snapshot(
        _snapshot(seconds_since_user=900.0, seconds_since_assistant=900.0),
        now=1000.0,
    )
    candidate = SocialInitiativeEngine(_NoSurfaceRouter()).propose(board, snapshot=_snapshot())

    assert candidate is not None
    assert candidate.source == "initiative_local_liveness"
    assert candidate.kind in {"casual_curiosity", "social_check_in"}
    assert not hasattr(candidate, "text")


class _ScreenFallbackRouter:
    surface_client = object()

    def build_surface_public_payload(self, *, text, plan, mode):
        return {"text": text, "mode": mode}


class _Reducer:
    pass


def test_screen_mode_has_no_local_wording_fallback(tmp_path: Path):
    board = TypedCognitiveBlackboard.from_snapshot(
        _snapshot(
            screen_context={
                "fresh": True,
                "privacy_blocked": False,
                "meaningful_delta": True,
                "window_changed": True,
                "window_title": "Brave",
                "evidence_refs": ["screen:raw"],
            },
            vision_grounding={
                "recommendation": "speak",
                "evidence_strength": 0.9,
                "claims": [{
                    "text": "Một cửa sổ trình duyệt đang hiển thị.",
                    "grounded": True,
                    "stale": False,
                    "evidence_ids": ["ocr:browser"],
                }],
            },
            seconds_since_user=120.0,
            seconds_since_assistant=120.0,
        ),
        now=1000.0,
    )
    candidate = SocialSpeechCandidate(
        decision="candidate",
        kind="screen_comment",
        topic="Ask a cautious question about the grounded browser-window claim.",
        speech_act="comment_current_surface",
        anchor_type="screen",
        anchor_id="ocr:browser",
        evidence_refs=("ocr:browser",),
        requires_grounding=True,
        confidence=0.9,
        relevance=0.8,
        urgency=0.1,
        tone="curious",
    )
    decision = InitiativeController(state_path=tmp_path / "initiative.json").decide(board, candidate)
    engine = SurfaceIntentEngine(_ScreenFallbackRouter(), _Reducer())

    assert decision.speech_intent is not None
    assert engine.fallback_payload(decision.speech_intent, board, language="vi") is None


def test_surface_reuses_shared_ds2api_key_by_default(monkeypatch):
    import llm.deepseek_workers as workers

    monkeypatch.delenv("ERIS_DS_SURFACE_API_KEY", raising=False)
    monkeypatch.delenv("ERIS_DS_SURFACE_ALLOW_SHARED_KEY", raising=False)
    monkeypatch.setenv("ERIS_DS2API_ENABLED", "1")
    monkeypatch.setenv("ERIS_DS2API_API_KEY", "shared-surface-key")
    monkeypatch.setattr(
        workers,
        "get_secret",
        lambda *names, default="": "shared-surface-key" if "ERIS_DS2API_API_KEY" in names else "",
    )

    spec = workers.load_worker_spec("surface")

    assert spec.configured is True
    assert spec.api_key == "shared-surface-key"


def test_social_worker_is_not_called_before_any_opportunity():
    class _Router:
        surface_client = object()
        called = False

        def propose_social_initiative(self, _request):
            self.called = True
            return {"decision": "none"}

    router = _Router()
    board = TypedCognitiveBlackboard.from_snapshot(
        _snapshot(seconds_since_user=20.0, seconds_since_assistant=20.0),
        now=1000.0,
    )

    candidate = SocialInitiativeEngine(router).propose(board, snapshot=_snapshot())

    assert candidate is None
    assert router.called is False
