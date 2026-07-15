# -*- coding: utf-8 -*-
"""Unit tests tối thiểu cho SurfaceArbiter.

Chạy nhanh, không cần runtime đầy đủ, không gọi model thật. Đây là điểm quan trọng:
SurfaceArbiter phải test được độc lập, nếu không nó lại thành một cái thần điện
runtime chỉ hoạt động khi đủ 14 module đứng thành hàng.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cortex.contracts import SpeechImpulse
from cortex.low_level_speech_policy import LowLevelSpeechPolicy, LowLevelSpeechPolicyConfig
from cortex.surface_arbiter import SurfaceArbiter, SurfaceImpulse


@dataclass
class Cue:
    needs_micro_presence: bool = True
    focus_family: str = "general_idle"
    confidence: float = 0.40
    curiosity: float = 0.0
    missing_evidence_ids: bool = True
    body_action: str = "idle_shift"
    reason: str = "presence_maintenance"
    evidence: tuple[str, ...] = ("idle_seconds=180",)
    should_call_llm: bool = True
    allow_body_only: bool = True


@dataclass
class Frame:
    speech_core: object | None = None


@dataclass
class SpeechCore:
    speech_impulse: SpeechImpulse


class SurfaceArbiterTests(unittest.TestCase):
    def _policy(self, **overrides) -> LowLevelSpeechPolicy:
        data = {
            "force_llm_after_silent": 3,
            "high_conf_threshold": 0.55,
            "min_surface_confidence": 0.38,
            "body_only_min_confidence": 0.32,
            "min_surface_interval_seconds": 0,
            "family_cooldown_seconds": 0,
            "max_body_only_streak": 3,
            "always_llm_kinds": (
                "presence_maintenance",
                "re_engagement",
                "micro_observation",
                "inner_whim",
                "idle_curiosity",
                "thought_stream_surface",
            ),
        }
        data.update(overrides)
        return LowLevelSpeechPolicy(LowLevelSpeechPolicyConfig.from_mapping(data, use_env=False))

    def test_presence_cue_forces_llm_after_silence_when_anchored(self) -> None:
        calls: list[SurfaceImpulse] = []

        def fake_llm(*, impulse, snapshot, force_llm=False):
            calls.append(impulse)
            self.assertTrue(force_llm)
            return "Một nhịp yên hơi dài.", "fake_llm"

        arbiter = SurfaceArbiter(policy=self._policy(), llm_micro_gen=fake_llm)
        cue = Cue(confidence=0.34, missing_evidence_ids=False, evidence=("ev.active_window=VSCode",))
        decision = arbiter.arbitrate(presence_cue=cue, silent_cycles=4, surface_kind="presence_maintenance")

        self.assertTrue(decision.should_speak)
        self.assertEqual(decision.parse_mode, "presence_maintenance")
        self.assertEqual(decision.generation_mode, "force_llm")
        self.assertEqual(len(calls), 1)

    def test_unanchored_presence_after_silence_is_body_only(self) -> None:
        calls: list[SurfaceImpulse] = []

        def fake_llm(*, impulse, snapshot, force_llm=False):
            calls.append(impulse)
            return "Má»™t nhá»‹p yÃªn hÆ¡i dÃ i.", "fake_llm"

        arbiter = SurfaceArbiter(policy=self._policy(), llm_micro_gen=fake_llm)
        decision = arbiter.arbitrate(presence_cue=Cue(confidence=0.34), silent_cycles=4, surface_kind="presence_maintenance")

        self.assertFalse(decision.should_speak)
        self.assertTrue(decision.body_only)
        self.assertEqual(decision.generation_mode, "forced_body_only")
        self.assertEqual(len(calls), 0)

    def test_spontaneous_impulse_can_win_over_weak_presence(self) -> None:
        def fake_llm(*, impulse, snapshot, force_llm=False):
            return f"kind={impulse.kind}", "fake_llm"

        spontaneous = SpeechImpulse(
            source="endogenous",
            source_layer="spontaneous_life",
            impulse_type="inner_whim",
            suggested_speech_act="inner_whim",
            topic_seed="quiet runtime thought",
            family="inner_whim:test",
            surface_pressure=0.72,
            evidence=("agent_state_stack/internal_state",),
            reason="test spontaneous impulse",
        )
        arbiter = SurfaceArbiter(policy=self._policy(), llm_micro_gen=fake_llm)
        decision = arbiter.arbitrate(
            cognitive_frame=Frame(speech_core=SpeechCore(spontaneous)),
            presence_cue=Cue(confidence=0.40),
            surface_kind="surface",
        )

        # The spontaneous inner_whim (pressure 0.72) wins selection over the weak
        # presence cue (confidence 0.40): the decision carries the spontaneous
        # impulse, not the presence one. Under the persona-anchor contract it then
        # settles to body-only because it has no concrete anchor token
        # (memory_id/event_id/vision_fact_id), but winning the slot is the point.
        self.assertEqual(decision.kind, "inner_whim")
        self.assertEqual(decision.confidence, 0.72)
        self.assertTrue(decision.body_only)
        self.assertEqual(decision.reason, "forced_body_only:persona_anchor_missing")

    def test_llm_decline_becomes_body_only_and_tracks_streak(self) -> None:
        def blank_llm(*, impulse, snapshot, force_llm=False):
            return "", "declined"

        arbiter = SurfaceArbiter(policy=self._policy(max_body_only_streak=2), llm_micro_gen=blank_llm)
        first = arbiter.arbitrate(presence_cue=Cue(confidence=0.56), surface_kind="presence_maintenance")
        second = arbiter.arbitrate(presence_cue=Cue(confidence=0.56), surface_kind="presence_maintenance")

        self.assertTrue(first.body_only)
        self.assertTrue(second.body_only)
        self.assertEqual(arbiter._body_only_streak, 2)

    def test_thought_stream_surface_without_anchor_is_body_only(self) -> None:
        arbiter = SurfaceArbiter(policy=self._policy(), llm_micro_gen=lambda **kwargs: ("kind=thought", "fake"))
        report = SimpleNamespace(
            topic_seed="small stray thought",
            pressure=0.82,
            momentum_score=0.82,
        )
        snapshot = SimpleNamespace(idle_seconds=0.0)
        frame = SimpleNamespace(
            thought_stream_report=report,
            internal_state_before=SimpleNamespace(vital_pressure=0.0),
            internal_state_after=SimpleNamespace(vital_pressure=0.0),
        )

        decision = arbiter.arbitrate(
            cognitive_frame=frame,
            snapshot=snapshot,
            surface_kind="presence_maintenance",
            silent_cycles=0,
        )

        self.assertTrue(decision.body_only)
        # Plain thought-stream residue is now classified as inner_whim (not a
        # generic "thought_stream_surface" kind), and without a concrete anchor
        # token it is held to body-only by the persona-anchor contract.
        self.assertEqual(decision.kind, "inner_whim")
        self.assertEqual(decision.reason, "forced_body_only:persona_anchor_missing")

    def test_thought_stream_surface_caps_confidence_when_vital_is_low(self) -> None:
        arbiter = SurfaceArbiter(policy=self._policy(), llm_micro_gen=lambda **kwargs: ("kind=thought", "fake"))
        report = SimpleNamespace(
            topic_seed="associative_drift:cognition_layer",
            pressure=0.95,
            momentum_score=0.95,
        )
        state = SimpleNamespace(
            vital_pressure=0.0,
            recursive_reactivation_pressure=0.28,
            memory_replay_pressure=0.0,
            mental_processes=SimpleNamespace(continuity=SimpleNamespace(level=0.22)),
        )
        frame = SimpleNamespace(
            thought_stream_report=report,
            internal_state_before=state,
            internal_state_after=state,
        )
        snapshot = SimpleNamespace(idle_seconds=0.0)

        decision = arbiter.arbitrate(
            cognitive_frame=frame,
            snapshot=snapshot,
            surface_kind="surface",
            silent_cycles=0,
        )

        # Low vital pressure caps the surfaced confidence at 0.68 even though the
        # raw thought pressure is 0.95. The thought is classified as inner_whim
        # and (lacking a concrete anchor token) settles to body-only, but the
        # capped confidence is still recorded on the decision.
        self.assertEqual(decision.kind, "inner_whim")
        self.assertTrue(decision.body_only)
        self.assertLessEqual(decision.confidence, 0.68)

    def test_yaml_policy_loader(self) -> None:
        config = LowLevelSpeechPolicyConfig.from_mapping(
            {
                "force_llm_after_silent": 5,
                "always_llm_kinds": ["re_engagement"],
                "min_surface_interval_seconds": 0,
            },
            use_env=False,
        )
        self.assertEqual(config.force_llm_after_silent, 5)
        self.assertEqual(config.always_llm_kinds, ("re_engagement",))

    def test_default_repo_yaml_is_loaded_when_env_is_missing(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch("cortex.low_level_speech_policy._default_policy_config_path", return_value=Path("config/low_level_speech_policy.yaml")):
                config = LowLevelSpeechPolicyConfig.from_env()

        self.assertEqual(config.force_llm_after_silent, 6)
        self.assertEqual(config.presence_force_llm_after_silent, 4)
        self.assertEqual(config.high_conf_threshold, 0.58)
        self.assertNotIn("presence_maintenance", config.always_llm_kinds)
        self.assertIn("presence_maintenance", config.presence_always_llm_kinds)


if __name__ == "__main__":
    unittest.main()
