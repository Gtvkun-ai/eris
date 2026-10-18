"""Writer-compatible execution receipt store; NOT a capability dispatcher.

Root V13 keeps the audited event/run/generation evidence contract while
removing all V12 registry-mediated execution from the live Root path.
"""
from runtime.conversation.context import RootCapabilityRegistry


class ToolReceiptLedger(RootCapabilityRegistry):
    """Append-only run receipts; legacy registry contains zero executable tools."""

    def __init__(self) -> None:
        super().__init__({})


__all__ = ["ToolReceiptLedger"]
