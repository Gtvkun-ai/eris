# -*- coding: utf-8 -*-
from cortex.daydream_consolidation import DaydreamConsolidator, DaydreamPacket
from cortex.observer_contracts import ObserverFrame, SignalDiff, SignalSnapshot
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
