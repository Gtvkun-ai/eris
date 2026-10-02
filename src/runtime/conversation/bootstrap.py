# -*- coding: utf-8 -*-
"""Production wiring for the single V12 conversation authority."""
from __future__ import annotations

from typing import Any

from .agent import DeterministicRootAgent, RuntimeModelRootAgent
from .delivery_adapter import RuntimeConversationDeliveryAdapter
from .kernel import ConversationKernel
from .runtime_writer import RuntimeConversationWriter
from .session_store import ConversationSessionStore


def ensure_conversation_kernel(host: Any) -> ConversationKernel:
    current = getattr(host, "conversation_kernel", None)
    if isinstance(current, ConversationKernel):
        return current

    logger = getattr(host, "logger", None)
    router = getattr(host, "ai_model_router", None)
    root = RuntimeModelRootAgent(router, logger=logger) if router is not None else DeterministicRootAgent()
    kernel = ConversationKernel(
        root,
        store=ConversationSessionStore(logger=logger),
        writer=RuntimeConversationWriter(host),
        delivery=RuntimeConversationDeliveryAdapter(host),
        logger=logger,
    )
    host.conversation_kernel = kernel
    return kernel


__all__ = ["ensure_conversation_kernel"]
