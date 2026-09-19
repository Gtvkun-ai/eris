#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Accelerated deterministic soak cho Eris V103 FINAL nervous system.

Không sleep theo wall-clock. Ta chạy fake clock đủ 24h để bắt các lỗi state drift,
NaN/out-of-range, event leak và latency distribution. Đây là test engineering cho
continuous dynamics, không phải giả vờ đã để app desktop chạy thật 24 giờ.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.activation_nervous_system_v98 import ContinuousDynamicsRuntime, ModulationEvent, SharedActivationBus
from runtime.nervous_system_v103_final import MotorSemanticTarget, NervousAutonomousAuthorityV103, NervousSystemConfigV103


def _candidate(source_id: str):
    content = f"Soak semantic target {source_id}."
    return SimpleNamespace(
        kind="random_chat", topic=content, speech_act="share_self_originated_thought",
        evidence_refs=("soak:fixture",), uncertainty=0.03,
        expression_commitment={
            "origin": "expression_urge", "source_id": source_id,
            "semantic_target": content, "motive": "inspect", "pressure": 0.97,
            "freshness": 0.98, "persistence": 0.96,
        },
        expression_urge_id=source_id, expression_motive="inspect",
        expression_pressure=0.97, expression_freshness=0.98,
        expression_satisfaction=0.0, relevance=0.9, urgency=0.5,
    )


def _affordance(source_id: str):
    return SimpleNamespace(affordance_id=f"soak:{source_id}", owner="expression_urge", candidate=_candidate(source_id))


def _coalition(action: str, source_id: str = ""):
    args = {}
    if source_id:
        args["expression_commitment"] = {
            "origin": "expression_urge", "source_id": source_id,
            "semantic_target": f"Soak semantic target {source_id}.",
        }
    return SimpleNamespace(action_kind=action, arguments=args, score=-99.0 if source_id else 99.0, uncertainty=0.1)


def _frame(source_id: str):
    return SimpleNamespace(
        frame_id="soak:frame",
        coalitions=(_coalition("speak", "soak:other"), _coalition("speak", source_id), _coalition("silence")),
        appraisals=(), activations=(), proposals=(), substrate=SimpleNamespace(processing_capacity=1.0),
    )


def run(hours: float, step: float, seed: int) -> dict:
    rng = random.Random(seed)
    fake_now = 0.0
    bus = SharedActivationBus(clock=lambda: fake_now)
    authority = NervousAutonomousAuthorityV103(
        bus,
        config=NervousSystemConfigV103(mode="active"),
        clock=lambda: fake_now,
    )
    dynamics = ContinuousDynamicsRuntime(
        bus,
        tick_interval_sec=min(0.25, step),
        clock=lambda: fake_now,
        health_observer=authority.health,
    )
    target = MotorSemanticTarget(
        source_id="soak:concern",
        semantic_target="Kiểm tra continuous nervous system có giữ state ổn định lâu dài hay không.",
        motive="inspect",
        pressure=0.96,
        freshness=0.98,
        persistence=0.95,
        uncertainty=0.04,
        evidence_refs=("soak:fixture",),
    )

    ticks = max(1, int(hours * 3600.0 / step))
    commits = 0
    commits_by_channel = {name: 0 for name in ("body", "vocalization", "micro_expression", "proposition")}
    hard_boundary_ticks = 0
    started = time.perf_counter()
    phase_ticks = max(1, int(600.0 / step))
    phase_names = ("body", "vocalization", "micro_expression", "proposition")
    source_id = "soak:concern"
    affordance = _affordance(source_id)
    candidate_bypass_events = 0

    for index in range(ticks):
        fake_now = (index + 1) * step
        phase = phase_names[(index // phase_ticks) % len(phase_names)]

        # FINAL2 coverage phase: mỗi 10 phút kéo field vào một regime khác nhau.
        # Đây vẫn là ModulationEvent -> dynamics; không set field trực tiếp.
        if index % phase_ticks == 0:
            phase_targets = {
                "body": {
                    "curiosity": 0.92, "boredom": 0.42, "social_need": 0.46, "task_focus": 0.05,
                    "concern_salience": 0.08, "uncertainty": 0.04, "expressive_pressure": 0.26,
                    "inhibition": 0.03, "fatigue": 0.02,
                },
                "vocalization": {
                    "curiosity": 0.05, "boredom": 0.94, "social_need": 0.92, "task_focus": 0.0,
                    "concern_salience": 0.05, "uncertainty": 0.02, "expressive_pressure": 1.0,
                    "inhibition": 0.01, "fatigue": 0.0,
                },
                "micro_expression": {
                    "curiosity": 1.0, "boredom": 0.05, "social_need": 0.82, "task_focus": 0.0,
                    "concern_salience": 1.0, "uncertainty": 0.02, "expressive_pressure": 0.25,
                    "inhibition": 0.01, "fatigue": 0.0,
                },
                "proposition": {
                    "curiosity": 0.92, "boredom": 0.10, "social_need": 0.78, "task_focus": 0.28,
                    "concern_salience": 0.98, "uncertainty": 0.02, "expressive_pressure": 1.0,
                    "inhibition": 0.01, "fatigue": 0.01,
                },
            }[phase]
            bus.submit(ModulationEvent(
                source=f"soak_phase_{phase}", targets=phase_targets, strength=1.0,
                half_life_seconds=18.0, ttl_seconds=90.0, created_at=fake_now,
                event_id=f"soak-phase:{phase}:{index}", tags=("soak", "coverage", phase),
            ))

        # Stimulus deterministic nhưng đa dạng: novelty, social idle, task focus,
        # uncertainty và concern. Random ở đây chỉ tạo fixture event; RNG seed cố định.
        if index % max(1, int(47.0 / step)) == 0:
            bus.submit(ModulationEvent(
                source="soak_fixture",
                impulses={
                    "curiosity": rng.uniform(-0.04, 0.18),
                    "boredom": rng.uniform(-0.16, 0.12),
                    "social_need": rng.uniform(-0.03, 0.08),
                    "expressive_pressure": rng.uniform(-0.05, 0.12),
                    "uncertainty": rng.uniform(-0.05, 0.09),
                },
                strength=0.55,
                half_life_seconds=1.2,
                ttl_seconds=4.0,
                created_at=fake_now,
                event_id=f"soak:{index}",
            ))
        # Mỗi vài phút có một "semantic wave" có evidence thật để motor được
        # exercise cả proposition + refractory/STP, thay vì soak chỉ đo silence.
        if index % max(1, int(300.0 / step)) == 0:
            bus.submit(ModulationEvent(
                source="soak_semantic_wave",
                targets={
                    "curiosity": 0.86,
                    "social_need": 0.72,
                    "concern_salience": 0.90,
                    "expressive_pressure": 0.96,
                    "inhibition": 0.05,
                    "uncertainty": 0.06,
                },
                strength=0.92,
                half_life_seconds=2.5,
                ttl_seconds=8.0,
                created_at=fake_now,
                event_id=f"soak-semantic:{index}",
            ))

        if index % max(1, int(180.0 / step)) == 0:
            bus.submit(ModulationEvent(
                source="soak_task",
                targets={"task_focus": 0.82 if (index // max(1, int(180.0 / step))) % 2 else 0.12},
                strength=0.70,
                half_life_seconds=3.0,
                ttl_seconds=12.0,
                created_at=fake_now,
                event_id=f"soak-task:{index}",
            ))

        snapshot = dynamics.tick_once(now=fake_now, dt=step)
        hard_boundary = (index % max(1, int(600.0 / step))) < max(1, int(3.0 / step))
        if hard_boundary:
            hard_boundary_ticks += 1
        inputs = (affordance,) if phase == "proposition" else ()
        _, decision = authority.preprocess_affordances(
            inputs, runtime_context={"user_holds_turn": hard_boundary}, now=fake_now
        )
        if decision.committed and decision.channel != "silence":
            commits += 1
            commits_by_channel[decision.channel] = commits_by_channel.get(decision.channel, 0) + 1
            if decision.channel == "proposition":
                selection = authority.selection_for_frame(_frame(source_id))
                if selection is not None and str(selection.reason).startswith("candidate_bypass:nervous_motor:proposition"):
                    candidate_bypass_events += 1
            # Body-only không phải speech discharge. Chỉ channel phát âm/lời mới
            # tăng speech homeostasis + STP public-expression depression.
            if decision.channel in {"vocalization", "micro_expression", "proposition"}:
                authority.note_public_commit(decision.semantic_source_id, now=fake_now)

        # Property bắt buộc: field/motor phải finite + normalized suốt soak.
        for value in snapshot.values.values():
            if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
                raise AssertionError(f"activation out of range at tick {index}: {snapshot.values}")
        if not 0.0 <= decision.activation <= 1.0:
            raise AssertionError(f"motor activation out of range at tick {index}: {decision}")
        if hard_boundary and decision.channel != "silence":
            raise AssertionError(f"hard boundary violated at tick {index}: {decision}")

    elapsed = time.perf_counter() - started
    health = authority.health.snapshot()
    return {
        "schema": "eris.v103_final2.soak_report.v1",
        "virtual_hours": hours,
        "step_seconds": step,
        "ticks": ticks,
        "rng_seed": seed,
        "wall_elapsed_seconds": round(elapsed, 4),
        "ticks_per_wall_second": round(ticks / max(1e-9, elapsed), 2),
        "non_silence_commits": commits,
        "commits_by_channel": commits_by_channel,
        "candidate_bypass_events": candidate_bypass_events,
        "coverage": {
            "all_motor_channels_seen": all(commits_by_channel.get(name, 0) > 0 for name in ("body", "vocalization", "micro_expression", "proposition")),
            "candidate_bypass_seen": candidate_bypass_events > 0,
        },
        "hard_boundary_ticks": hard_boundary_ticks,
        "final_state": bus.snapshot().to_dict(),
        "nervous_health": health,
        "stp": list(authority.stp.snapshot(now=fake_now, limit=8)),
        "pass": bool(
            all(commits_by_channel.get(name, 0) > 0 for name in ("body", "vocalization", "micro_expression", "proposition"))
            and candidate_bypass_events > 0
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--step", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=103)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report = run(max(0.01, args.hours), max(0.05, min(1.0, args.step)), args.seed)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
