# -*- coding: utf-8 -*-
"""Idempotency ledger nhỏ cho delivery receipt V12."""
from __future__ import annotations

import threading
from typing import Any

from .contracts import DeliveryReceipt


class DeliveryReceiptLedger:
    def __init__(self, *, logger: Any = None) -> None:
        self.logger = logger
        self._lock = threading.RLock()
        self._seen: set[str] = set()

    def commit_once(self, receipt: DeliveryReceipt) -> bool:
        key = str(receipt.delivery_id or "")
        if not key:
            return False
        with self._lock:
            if key in self._seen:
                return False
            self._seen.add(key)
            if len(self._seen) > 4096:
                self._seen = set(list(self._seen)[-2048:])
        return True


__all__ = ["DeliveryReceiptLedger"]
