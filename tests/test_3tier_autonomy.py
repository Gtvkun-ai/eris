# -*- coding: utf-8 -*-
from types import SimpleNamespace

from cortex.daydream_consolidation import DaydreamConsolidator, DaydreamPacket
from cortex.observer_contracts import ObserverFrame, SignalDiff, SignalSnapshot
from runtime.autonomous_wake_governor import AutonomousWakeGovernor
from runtime.model_budget_policy import ModelBudgetPolicy, ModelBudgetPolicyConfig, ResourceSnapshot
from runtime.contextual_autonomy_loop import ContextualAutonomyLoop


class FakeDaydreamClient:
    def chat_json(self, model, messages, keep_alive=None, temperature=0.0):
        class Result:
            ok = True
            parsed = {
                "insights": [
                    {
                        "kind": "memory_pattern",
                        "summary": "Co mot unresolved loop can giu lai de xu ly sau.",
                        "evidence_ids": ["ev1"],
                        "confidence": 0.72,
                        "pressure": 0.68,
                        "speech_value": 0.10,
                        "proposed_agenda_kind": "memory_consolidation",
                    },
                    {
                        "kind": "open_question",
                        "summary": "Insight nay bi reject vi evidence la.",
                        "evidence_ids": ["ev_fake"],
                        "confidence": 0.90,
                        "pressure": 0.80,
                        "speech_value": 0.20,
                        "proposed_agenda_kind": "open_question",
                    },
                ]
            }

        return Result()


def test_daydream_rejects_unknown_evidence_ids():
    packet = DaydreamPacket(id="p1", kind="semantic", text="memory text", evidence_ids=("ev1",))
    daydream = DaydreamConsolidator(llm_client=FakeDaydreamClient())
    result = daydream.consolidate([packet])
    assert result.ok is True
    assert len(result.insights) == 1
    assert result.insights[0].evidence_ids == ("ev1",)
    assert len(result.rejected) == 1
    assert result.rejected[0].reject_reason == "unknown_evidence_id"


def test_contextual_loop_returns_wake_decision_without_model():
    snap = SignalSnapshot(
        active_app="Code",
        active_window_title="main.py - Visual Studio Code",
        focus_kind_hint="code",
        idle_seconds=360,
        cpu_percent=5,
        ram_percent=35,
        recent_events=["key_press"],
    )
    diff = SignalDiff(diff_score=0.8, novelty=0.8, repetition=0.0, reason=["smoke"])
    obs = ObserverFrame(
        focus_kind="code",
        activity_intent="debugging",
        salience=0.90,
        novelty=0.85,
        possible_error=0.75,
        recommended_action="call_vision_compressor",
        evidence=["observer_ev"],
    )
    loop = ContextualAutonomyLoop(daydream=DaydreamConsolidator(llm_client=None))
    result = loop.tick(signal_snapshot=snap, signal_diff=diff, observer_frame=obs)
    assert result.user_context.focus_kind == "code"
    assert result.wake_decision.level in {
        "observe_only",
        "think_only",
        "micro_presence",
        "call_vision_compressor",
        "wake_main_cognition",
        "sleep",
    }
    assert result.next_heartbeat_seconds >= 2.0


def test_wake_governor_ignores_budget_busy_signal_and_keeps_main_wake():
    governor = AutonomousWakeGovernor()
    policy = ModelBudgetPolicy(
        ModelBudgetPolicyConfig(
            enabled=True,
            queue_enabled=True,
            remote_api_enabled=False,
            cpu_block_percent=999.0,
            ram_block_percent=999.0,
            gpu_block_percent=999.0,
            vram_block_percent=999.0,
            gpu_temp_block_c=999.0,
            main_cooldown_seconds=0.0,
            four_b_cooldown_seconds=0.0,
            default_queue_timeout_seconds=1.0,
            queue_poll_seconds=0.01,
            max_queue_size=4,
            assume_gtx_1650ti_4gb=False,
        )
    )
    policy._active_leases["vision_lock"] = SimpleNamespace(tier="vision_compressor")

    decision = governor.decide(
        user_context=SimpleNamespace(
            external_pressure=0.92,
            interrupt_cost=0.18,
            possible_error=0.25,
            user_presence=0.90,
            recommended_action="wake_main_cognition",
        ),
        internal_state=SimpleNamespace(
            internal_drive=0.72,
            consolidation_pressure=0.10,
            insight_pressure=0.10,
        ),
        agenda_stack=None,
        budget_policy=policy,
        resource_snapshot=ResourceSnapshot(cpu_percent=35.0, ram_percent=48.0),
    )

    assert decision.level == "wake_main_cognition"
    assert decision.should_speak is True
    assert decision.should_wake_main is True
    assert decision.reason == "main_wake_allowed"


def test_wake_governor_keeps_main_wake_under_extreme_pressure():
    governor = AutonomousWakeGovernor()
    policy = ModelBudgetPolicy(
        ModelBudgetPolicyConfig(
            enabled=True,
            queue_enabled=True,
            remote_api_enabled=True,
            cpu_block_percent=80.0,
            ram_block_percent=80.0,
            gpu_block_percent=70.0,
            vram_block_percent=72.0,
            gpu_temp_block_c=999.0,
            main_cooldown_seconds=0.0,
            four_b_cooldown_seconds=0.0,
            default_queue_timeout_seconds=1.0,
            queue_poll_seconds=0.01,
            max_queue_size=4,
            assume_gtx_1650ti_4gb=True,
        )
    )

    decision = governor.decide(
        user_context=SimpleNamespace(
            external_pressure=0.95,
            interrupt_cost=0.12,
            possible_error=0.30,
            user_presence=0.92,
            recommended_action="wake_main_cognition",
        ),
        internal_state=SimpleNamespace(
            internal_drive=0.78,
            consolidation_pressure=0.10,
            insight_pressure=0.10,
        ),
        agenda_stack=None,
        budget_policy=policy,
        resource_snapshot=ResourceSnapshot(
            cpu_percent=98.0,
            ram_percent=97.0,
            gpu_util_percent=94.0,
            vram_used_mb=3600.0,
            vram_total_mb=4096.0,
        ),
    )

    assert decision.level == "wake_main_cognition"
    assert decision.should_speak is True
    assert decision.should_wake_main is True
    assert decision.budget_reason == "queue_only_policy"


def test_wake_governor_silence_debt_adds_speech_pressure():
    governor = AutonomousWakeGovernor()

    decision = governor.decide(
        user_context=SimpleNamespace(
            external_pressure=0.30,
            interrupt_cost=0.18,
            possible_error=0.0,
            user_presence=0.18,
            recommended_action="observe_only",
            idle_seconds=30.0,
        ),
        internal_state=SimpleNamespace(
            internal_drive=0.18,
            consolidation_pressure=0.10,
            insight_pressure=0.10,
        ),
        agenda_stack=None,
        budget_policy=None,
        resource_snapshot=ResourceSnapshot(cpu_percent=18.0, ram_percent=28.0),
        autonomous_silent_cycles=12,
    )

    assert decision.debug["silence_debt"] == 1.0
    assert decision.debug["silence_debt_weight"] == 0.25
    assert decision.speech_value >= 0.40
