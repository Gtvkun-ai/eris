# -*- coding: utf-8 -*-
"""Runner soak test mô phỏng lịch sử dài, restart và isolation.

Runner không ngủ 7 ngày ngoài đời. Nó nén thời gian bằng clock giả nhưng vẫn tạo
nhiều lượt, đóng/mở repository, replay hash và kiểm tra subject không rò state.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class SoakSpec:
    simulated_days: int = 7
    turns_per_day: int = 20
    restart_every_turns: int = 25
    subject_ids: tuple[str, ...] = ("eris-a", "eris-b")
    seed: int = 0

    def __post_init__(self) -> None:
        if self.simulated_days < 1 or self.turns_per_day < 1:
            raise ValueError("soak duration must be positive")
        if self.restart_every_turns < 1:
            raise ValueError("restart cadence must be positive")
        if len(set(self.subject_ids)) != len(self.subject_ids):
            raise ValueError("subject ids must be unique")


@dataclass(frozen=True, slots=True)
class SoakReport:
    simulated_days: int
    total_turns: int
    restart_count: int
    event_chain_ok: bool
    replay_stable: bool
    cross_instance_leakage: int
    projection_hashes: Mapping[str, str]
    passed: bool
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write_json(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )


class SoakInstancePort:
    """Tài liệu interface dùng bởi run_simulated_soak.

    Factory phải trả object có apply_turn(payload), snapshot(), close() và
    restart(). Dùng duck typing để runner không kéo runtime production vào test.
    """


def _hash_snapshot(snapshot: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


async def run_simulated_soak(
    spec: SoakSpec,
    *,
    instance_factory: Callable[[str, int], Any],
    turn_factory: Callable[[str, int, int], Mapping[str, Any]],
) -> SoakReport:
    instances = {
        subject_id: instance_factory(subject_id, spec.seed + index)
        for index, subject_id in enumerate(spec.subject_ids)
    }
    restart_count = 0
    total_turns = 0
    notes: list[str] = []

    for day in range(spec.simulated_days):
        for turn in range(spec.turns_per_day):
            for subject_id, instance in tuple(instances.items()):
                payload = dict(turn_factory(subject_id, day, turn))
                payload.setdefault("subject_id", subject_id)
                await _maybe_await(instance.apply_turn(payload))
                total_turns += 1
                if total_turns % spec.restart_every_turns == 0:
                    before = _hash_snapshot(dict(instance.snapshot()))
                    replacement = await _maybe_await(instance.restart())
                    if replacement is not None:
                        instances[subject_id] = replacement
                        instance = replacement
                    after = _hash_snapshot(dict(instance.snapshot()))
                    restart_count += 1
                    if before != after:
                        notes.append(f"projection changed across restart: {subject_id}")

    projection_hashes = {
        subject_id: _hash_snapshot(dict(instance.snapshot()))
        for subject_id, instance in instances.items()
    }
    event_chain_ok = all(bool(instance.verify_event_chain()) for instance in instances.values())
    replay_stable = all(bool(instance.verify_replay()) for instance in instances.values())

    leakage = 0
    snapshots = {subject_id: dict(instance.snapshot()) for subject_id, instance in instances.items()}
    for subject_id, snapshot in snapshots.items():
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        leakage += sum(
            other_id in encoded
            for other_id in spec.subject_ids
            if other_id != subject_id
        )
    if not event_chain_ok:
        notes.append("event chain verification failed")
    if not replay_stable:
        notes.append("deterministic replay verification failed")
    if leakage:
        notes.append(f"cross-instance leakage={leakage}")

    for instance in instances.values():
        close = getattr(instance, "close", None)
        if callable(close):
            await _maybe_await(close())

    return SoakReport(
        simulated_days=spec.simulated_days,
        total_turns=total_turns,
        restart_count=restart_count,
        event_chain_ok=event_chain_ok,
        replay_stable=replay_stable,
        cross_instance_leakage=leakage,
        projection_hashes=projection_hashes,
        passed=not notes,
        notes=tuple(notes),
    )


__all__ = ["SoakReport", "SoakSpec", "run_simulated_soak"]
