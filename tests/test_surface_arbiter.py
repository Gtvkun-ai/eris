# -*- coding: utf-8 -*-
"""Unit tests tối thiểu cho SurfaceArbiter.

Chạy nhanh, không cần runtime đầy đủ, không gọi model thật. Đây là điểm quan trọng:
SurfaceArbiter phải test được độc lập, nếu không nó lại thành một cái thần điện
runtime chỉ hoạt động khi đủ 14 module đứng thành hàng.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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

    def test_presence_cue_forces_llm_after_silence(self) -> None:
        calls: list[SurfaceImpulse] = []

        def fake_llm(*, impulse, snapshot, force_llm=False):
            calls.append(impulse)
            self.assertTrue(force_llm)
            return "Một nhịp yên hơi dài.", "fake_llm"

        arbiter = SurfaceArbiter(policy=self._policy(), llm_micro_gen=fake_llm)
        decision = arbiter.arbitrate(presence_cue=Cue(confidence=0.34), silent_cycles=3, surface_kind="presence_maintenance")

        self.assertTrue(decision.should_speak)
        self.assertEqual(decision.parse_mode, "presence_maintenance")
        self.assertEqual(decision.generation_mode, "force_llm")
        self.assertEqual(len(calls), 1)

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

        self.assertTrue(decision.should_speak)
        self.assertEqual(decision.kind, "inner_whim")
        self.assertEqual(decision.source, "surface_arbiter_llm")
        self.assertIn("kind=inner_whim", decision.text)

    def test_llm_decline_becomes_body_only_and_tracks_streak(self) -> None:
        def blank_llm(*, impulse, snapshot, force_llm=False):
            return "", "declined"

        arbiter = SurfaceArbiter(policy=self._policy(max_body_only_streak=2), llm_micro_gen=blank_llm)
        first = arbiter.arbitrate(presence_cue=Cue(confidence=0.56), surface_kind="presence_maintenance")
        second = arbiter.arbitrate(presence_cue=Cue(confidence=0.56), surface_kind="presence_maintenance")

        self.assertTrue(first.body_only)
        self.assertTrue(second.body_only)
        self.assertEqual(arbiter._body_only_streak, 2)

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

        self.assertEqual(config.force_llm_after_silent, 3)
        self.assertEqual(config.high_conf_threshold, 0.55)
        self.assertIn("presence_maintenance", config.always_llm_kinds)


if __name__ == "__main__":
    unittest.main()
