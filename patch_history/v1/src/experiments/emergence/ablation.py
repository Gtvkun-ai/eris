# -*- coding: utf-8 -*-
"""Clone-only causal ablation helpers."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


def tombstone_events(database_path: str | Path, event_ids: Iterable[str]) -> int:
    """Record experiment tombstones without mutating canonical events."""
    connection = sqlite3.connect(str(database_path))
    try:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS experiment_tombstones(
                event_id TEXT PRIMARY KEY, reason TEXT NOT NULL DEFAULT 'causal_ablation'
            )"""
        )
        count = 0
        for event_id in event_ids:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO experiment_tombstones(event_id) VALUES (?)", (str(event_id),)
            )
            count += cursor.rowcount
        connection.commit()
        return count
    finally:
        connection.close()
