#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V103 FINAL2 - deterministic end-to-end nervous replay.

Replay này cố ý dùng đúng runtime production: SharedActivationBus ->
ContinuousDynamicsRuntime -> NervousAutonomousAuthorityV103 -> candidate bypass ->
public commit receipt. Không gọi LLM/TTS/network; Surface local chỉ được biểu diễn
bằng lexeme deterministic của motor.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.activation_nervous_system_v98 import ContinuousDynamicsRuntime, ModulationEvent, SharedActivationBus
from runtime.nervous_system_v103_final import NervousAutonomousAuthorityV103, NervousSystemConfigV103


def _candidate(source_id: str):
    content = f"Replay semantic target {source_id}."
    return SimpleNamespace(
        kind="random_chat", topic=content, speech_act="share_self_originated_thought",
        evidence_refs=("replay:evidence",), uncertainty=0.02,
        expression_commitment={
            "origin": "expression_urge", "source_id": source_id,
            "semantic_target": content, "motive": "share", "pressure": 0.98,
            "freshness": 0.99, "persistence": 0.96,
        },
        expression_urge_id=source_id, expression_motive="share",
        expression_pressure=0.98, expression_freshness=0.99,
        expression_satisfaction=0.0, relevance=0.9, urgency=0.5,
    )


def _affordance(source_id: str):
    return SimpleNamespace(affordance_id=f"replay:{source_id}", owner="expression_urge", candidate=_candidate(source_id))


def _coalition(action: str, source_id: str = ""):
    args = {}
    if source_id:
        args["expression_commitment"] = {
            "origin": "expression_urge", "source_id": source_id,
            "semantic_target": f"Replay semantic target {source_id}.",
        }
    return SimpleNamespace(action_kind=action, arguments=args, score=-99.0 if source_id else 99.0, uncertainty=0.1)


def _frame(source_id: str):
    return SimpleNamespace(
        frame_id="replay:frame",
        coalitions=(_coalition("speak", "other"), _coalition("speak", source_id), _coalition("silence")),
        appraisals=(), activations=(), proposals=(),
        substrate=SimpleNamespace(processing_capacity=1.0),
    )


def _run_segment(*, initial_values: dict, event: ModulationEvent, affordance=None, label: str) -> dict:
    now = 0.0
    bus = SharedActivationBus(clock=lambda: now, initial_values=initial_values)
    authority = NervousAutonomousAuthorityV103(
        bus, config=NervousSystemConfigV103(mode="active"), clock=lambda: now,
    )
    dynamics = ContinuousDynamicsRuntime(bus, tick_interval_sec=0.1, clock=lambda: now, health_observer=authority.health)
    bus.submit(event)
    rows = []
    selection_reason = ""
    surface = ""
    source_id = "replay:urge"
    for tick in range(16):
        now = (tick + 1) * 0.1
        snapshot = dynamics.tick_once(now=now, dt=0.1)
        inputs = (affordance,) if affordance is not None else ()
        _, decision = authority.preprocess_affordances(inputs, now=now)
        row = {
            "at": round(now, 3), "revision": snapshot.revision,
            "fields": {k: round(float(v), 6) for k, v in snapshot.values.items()},
            "channel": decision.channel, "committed": decision.committed,
            "activation": round(decision.activation, 6),
            "semantic_source_id": decision.semantic_source_id,
        }
        if decision.committed and decision.channel != "silence":
            if decision.channel == "proposition":
                selection = authority.selection_for_frame(_frame(source_id))
                selection_reason = str(getattr(selection, "reason", "") or "")
                row["candidate_bypass"] = selection_reason
                surface = "realized_by_surface_contract"
                authority.note_public_commit(source_id, now=now)
            else:
                surface = decision.local_text or decision.channel
                authority.note_public_commit(decision.semantic_source_id, now=now)
            row["surface"] = surface
            row["receipt"] = "public_commit"
            rows.append(row)
            break
        rows.append(row)
    health = authority.health.snapshot()
    # Wall-clock profiling không deterministic; replay contract chỉ so trajectory,
    # motor commits và causal outcome. Latency được benchmark ở soak/health riêng.
    health.pop("tick_ms", None)
    return {
        "label": label,
        "rows": rows,
        "surface": surface,
        "candidate_bypass": selection_reason,
        "final_state": bus.snapshot().to_dict(),
        "health": health,
    }


def run_replay() -> dict:
    vocal_initial = {
        "curiosity": 0.05, "boredom": 0.90, "social_need": 0.90, "task_focus": 0.0,
        "concern_salience": 0.05, "uncertainty": 0.0, "expressive_pressure": 1.0,
        "inhibition": 0.0, "fatigue": 0.0,
    }
    vocal_event = ModulationEvent(
        source="replay_social_idle", targets=vocal_initial, strength=1.0,
        half_life_seconds=5.0, ttl_seconds=6.0, created_at=0.0,
        event_id="replay:vocal", tags=("replay", "vocal"),
    )
    vocal = _run_segment(initial_values=vocal_initial, event=vocal_event, label="local_vocalization")

    proposition_initial = {
        "curiosity": 0.90, "boredom": 0.15, "social_need": 0.75, "task_focus": 0.30,
        "concern_salience": 0.95, "uncertainty": 0.03, "expressive_pressure": 0.98,
        "inhibition": 0.02, "fatigue": 0.02,
    }
    proposition_event = ModulationEvent(
        source="replay_semantic_wave", targets=proposition_initial, strength=1.0,
        half_life_seconds=5.0, ttl_seconds=6.0, created_at=0.0,
        event_id="replay:proposition", tags=("replay", "semantic", "fresh_evidence"),
    )
    proposition = _run_segment(
        initial_values=proposition_initial, event=proposition_event,
        affordance=_affordance("replay:urge"), label="proposition_candidate_bypass",
    )

    payload = {
        "schema": "eris.v103_final2.nervous_replay.v1",
        "segments": [vocal, proposition],
        "pass": bool(
            vocal.get("surface")
            and proposition.get("candidate_bypass", "").startswith("candidate_bypass:nervous_motor:proposition")
        ),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report = run_replay()
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
