from __future__ import annotations

from types import SimpleNamespace

from cortex.low_level_speech_policy import LowLevelSpeechPolicy, LowLevelSpeechPolicyConfig
from cortex.surface_arbiter import SurfaceArbiter, SurfaceImpulse
from runtime.presence_controller import PresenceControllerMixin
from runtime.sensor_visibility import derive_sensor_visibility_state


class _DummyPresence(PresenceControllerMixin):
    def __init__(self, returned_text: str):
        self.returned_text = returned_text
        self.last_text = ""
        self.presence_maintenance_silent_cycles = 0
        self.micro_presence_llm_enabled = True
        self.micro_presence_llm_probability = 1.0
        self.captured_context = None
        self.logger = SimpleNamespace(warning=lambda *args, **kwargs: None, info=lambda *args, **kwargs: None)

    def _current_ego_surface_state(self):
        return {}

    def _normalize_user_message(self, text: str) -> str:
        table = str.maketrans(
            "àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ",
            "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyyd",
        )
        return str(text or "").lower().translate(table)

    def _is_near_duplicate_text(self, a, b):
        return False

    def _is_placeholder_micro_text(self, text):
        return False

    def _hybrid_micro_presence_text(self, **kwargs):
        self.captured_context = kwargs.get("micro_context") or {}
        return self.returned_text, "llm_signal"


def _policy() -> LowLevelSpeechPolicy:
    return LowLevelSpeechPolicy(
        LowLevelSpeechPolicyConfig(
            min_surface_interval_seconds=0.0,
            family_cooldown_seconds=0.0,
            high_conf_threshold=0.55,
            min_surface_confidence=0.38,
            body_only_min_confidence=0.32,
            always_llm_kinds=("blind_frustration",),
        )
    )


def test_permission_blocked_and_plain_missing_evidence_do_not_allow_public_grumble():
    permission = derive_sensor_visibility_state(
        snapshot=SimpleNamespace(
            vision_permission_blocked=True,
            vision_facts=(),
            recent_events=(),
            metadata={},
        )
    )
    assert permission.vision_permission_blocked is True
    assert permission.public_frustration_allowed is False
    assert permission.should_stay_quiet is True

    plain_missing = derive_sensor_visibility_state(
        snapshot=SimpleNamespace(vision_facts=(), recent_events=(), metadata={})
    )
    assert plain_missing.no_current_screen_evidence is True
    assert plain_missing.public_frustration_allowed is False


def test_timeout_budget_and_context_shift_allow_tiny_public_grumble():
    timeout = derive_sensor_visibility_state(
        snapshot=SimpleNamespace(vision_facts=(), recent_events=("vision_timeout",), metadata={})
    )
    assert timeout.vision_timeout is True
    assert timeout.public_frustration_allowed is True

    budget = derive_sensor_visibility_state(
        snapshot=SimpleNamespace(vision_facts=(), recent_events=("resource_guard:vram_busy",), metadata={})
    )
    assert budget.budget_blocked is True
    assert budget.public_frustration_allowed is True

    shifted = derive_sensor_visibility_state(
        snapshot=SimpleNamespace(vision_facts=(), recent_events=("window_changed",), metadata={})
    )
    assert shifted.context_shift_without_refresh is True
    assert shifted.public_frustration_allowed is True


def test_surface_arbiter_treats_blind_frustration_as_speakable_sensor_impulse():
    calls = []

    def generator(*, impulse, snapshot, force_llm=False):
        calls.append((impulse, force_llm))
        return "Tam nhin bi nghen nhe roi.", "ok"

    arbiter = SurfaceArbiter(policy=_policy(), llm_micro_gen=generator)
    impulse = SurfaceImpulse(
        kind="blind_frustration",
        source="sensor_visibility",
        confidence=0.62,
        pressure=0.62,
        score=0.62,
        topic_seed="vision_timeout",
        speech_act="blind_frustration",
        family="sensor_visibility:vision_timeout",
        evidence=(
            "event_id=sensor_visibility:vision_timeout",
            "sensor_visibility=limited",
            "no_current_screen_evidence=true",
            "vision_timeout=true",
            "recent_context_shift=false",
        ),
        reason="vision_timeout",
        missing_evidence_ids=True,
        should_surface=True,
        needs_external_evidence=False,
    )

    decision = arbiter.arbitrate(extra_impulses=(impulse,), silent_cycles=0)

    assert decision.should_speak is True
    assert decision.body_only is False
    assert decision.kind == "blind_frustration"
    assert calls and calls[0][0].needs_external_evidence is False
    assert calls[0][1] is True


def test_blind_frustration_context_is_passed_and_blame_is_blocked_without_context_shift():
    state = derive_sensor_visibility_state(
        snapshot=SimpleNamespace(vision_facts=(), recent_events=("vision_timeout",), metadata={})
    )
    impulse = SurfaceImpulse(
        kind="blind_frustration",
        source="sensor_visibility",
        confidence=0.66,
        score=0.66,
        evidence=("sensor_visibility=limited", *state.evidence),
        reason=state.reason,
        missing_evidence_ids=True,
        should_surface=True,
        needs_external_evidence=False,
        raw=state,
    )
    dummy = _DummyPresence("Ngai lai doi cua so nen toi mu roi.")

    text, source = dummy._surface_arbiter_llm_generate(
        impulse=impulse,
        snapshot=SimpleNamespace(),
        force_llm=True,
    )

    assert text == ""
    assert source == "blind_frustration_blame_blocked"
    assert "sensor_visibility_contract" in dummy.captured_context
    assert "recent_context_shift=false" in " ".join(impulse.evidence)


def test_blind_frustration_blame_allowed_when_recent_context_shift_is_evidenced():
    state = derive_sensor_visibility_state(
        snapshot=SimpleNamespace(vision_facts=(), recent_events=("window_changed",), metadata={})
    )
    impulse = SurfaceImpulse(
        kind="blind_frustration",
        source="sensor_visibility",
        confidence=0.60,
        score=0.61,
        evidence=("sensor_visibility=limited", *state.evidence),
        reason=state.reason,
        missing_evidence_ids=True,
        should_surface=True,
        needs_external_evidence=False,
        raw=state,
    )
    dummy = _DummyPresence("Ngai doi ngu canh nhanh qua, tam nhin hut mat.")

    text, source = dummy._surface_arbiter_llm_generate(
        impulse=impulse,
        snapshot=SimpleNamespace(),
        force_llm=True,
    )

    assert text
    assert source == "llm_signal"
