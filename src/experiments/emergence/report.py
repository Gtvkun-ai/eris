# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ExperimentReport:
    scenario_id: str
    code_revision: str
    algorithm_version: str
    metrics: Mapping[str, float]
    thresholds: Mapping[str, float]
    passed: bool
    run_count: int
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
