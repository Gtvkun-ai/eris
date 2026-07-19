# -*- coding: utf-8 -*-
"""Cài kiến trúc C vào RuntimeCoordinator mà không để module con ghi state trực tiếp."""

from __future__ import annotations

import os
import threading
from typing import Any, Mapping

from .contracts import RuntimeMindState
from .discovery import DiscoveryRuntime
from .expression import IdentityExpressionBridge
from .identity_consolidator import IdentityConsolidator
from .initiative import InitiativeController
from .model_router import AIRuntimeModelRouter
from .observer import PostTurnObserver
from .orchestrator import AIChatOrchestrator, AIAutonomousOrchestrator, architecture_c_enabled
from .planner import IntentionPlanner
from .stage_planner import StagePlanner
from .state_reducer import StateReducer


def install_ai_orchestrated_runtime(host: Any, llm_service: Any) -> bool:
    if not architecture_c_enabled():
        host.ai_runtime_enabled = False
        return False

    def load_state() -> RuntimeMindState:
        memory_state = getattr(host, "memory_state", None)
        if isinstance(memory_state, dict):
            return RuntimeMindState.from_mapping(memory_state.get("ai_orchestrated_state", {}))
        metadata = getattr(memory_state, "metadata", None)
        if isinstance(metadata, Mapping):
            return RuntimeMindState.from_mapping(metadata.get("ai_orchestrated_state", {}))
        return RuntimeMindState()

    persist_lock = getattr(host, "_state_lock", None) or threading.RLock()

    def persist(payload: Mapping[str, Any]) -> None:
        memory_state = getattr(host, "memory_state", None)
        with persist_lock:
            if isinstance(memory_state, dict):
                memory_state["ai_orchestrated_state"] = dict(payload)
            elif memory_state is not None:
                metadata = getattr(memory_state, "metadata", None)
                if not isinstance(metadata, dict):
                    try:
                        memory_state.metadata = {}
                        metadata = memory_state.metadata
                    except Exception:
                        metadata = None
                if isinstance(metadata, dict):
                    metadata["ai_orchestrated_state"] = dict(payload)
            saver = getattr(host, "_save_memory_state", None)
            if callable(saver):
                saver()

    reducer = StateReducer(initial_state=load_state(), persist=persist, logger=getattr(host, "logger", None))
    router = AIRuntimeModelRouter(
        llm_service,
        logger=getattr(host, "logger", None),
        budget_policy=getattr(host, "model_budget_policy", None),
    )
    observer = PostTurnObserver(
        router,
        reducer,
        logger=getattr(host, "logger", None),
        workers=int(os.getenv("ERIS_AI_OBSERVER_WORKERS", "2") or 2),
    )
    planner = IntentionPlanner(router, reducer, logger=getattr(host, "logger", None))
    discovery = DiscoveryRuntime(host, router, logger=getattr(host, "logger", None))
    initiative = InitiativeController(logger=getattr(host, "logger", None))
    consolidator = IdentityConsolidator(logger=getattr(host, "logger", None))
    expression_bridge = IdentityExpressionBridge()

    host.ai_runtime_enabled = True
    host._ai_turn_seq_lock = threading.RLock()
    host._ai_turn_seq = reducer.snapshot().last_applied_turn_seq
    host.ai_state_reducer = reducer
    host.ai_model_router = router
    host.ai_post_turn_observer = observer
    host.ai_intention_planner = planner
    host.ai_discovery_runtime = discovery
    host.ai_initiative_controller = initiative
    host.ai_identity_consolidator = consolidator
    host.ai_stage_planner = StagePlanner(expression_bridge=expression_bridge)
    host.ai_chat_orchestrator = AIChatOrchestrator(host)
    host.ai_autonomous_orchestrator = AIAutonomousOrchestrator(host)

    # Legacy social paths are kept importable but removed from production authority.
    old_observer = getattr(host, "social_observer", None)
    if old_observer is not None:
        try:
            old_observer.shutdown()
        except Exception:
            pass
    host.social_observer = None
    host.social_cognition_v2 = None

    processed_memory_turns: set[str] = set()

    def on_state(state: RuntimeMindState, event: Any, accepted: bool) -> None:
        if not accepted:
            return
        payload = dict(getattr(event, "payload", {}) or {})
        host.latest_cognitive_observation = dict(state.latest_observation)
        host.latest_personality_profile = state.personality.to_dict()
        host.latest_identity_profile = state.identity.to_dict()
        host.latest_discovery_state = discovery.panel_view()
        host.pending_social_repair = bool(state.latest_observation.get("repair_needed", False))
        # Panel đọc một state duy nhất, không ráp trust từ ba engine khác nhau.
        try:
            from runtime.ai_orchestrated.views import build_cognitive_views
            from runtime.panel_snapshot import write_social_observation
            write_social_observation(
                dict(state.latest_observation),
                relationship_state=state.relationship.to_dict(),
                cognitive_views=build_cognitive_views(state),
            )
        except Exception:
            pass
        if str(getattr(event, "kind", "")) == "cognitive_observation":
            turn_id = str(getattr(event, "turn_id", "") or "")
            memory_candidate = str(payload.get("memory_candidate", "") or "").strip()
            if (
                turn_id
                and turn_id not in processed_memory_turns
                and bool(payload.get("memory_worthy", False))
                and float(payload.get("confidence", 0.0) or 0.0) >= 0.68
                and memory_candidate
            ):
                processed_memory_turns.add(turn_id)
                enqueue = getattr(host, "_enqueue_background_memory_digest", None)
                if callable(enqueue):
                    try:
                        enqueue(
                            memory_candidate,
                            turn_id=turn_id,
                            source="ai_post_turn_observer",
                            priority="normal",
                            context={
                                "channel": "post_turn_observer",
                                "observer_confidence": float(payload.get("confidence", 0.0) or 0.0),
                                "evidence": list(payload.get("evidence", ()) or ()),
                            },
                        )
                    except Exception:
                        pass

    reducer.subscribe(on_state)
    reducer.subscribe(consolidator.observe)
    try:
        host.logger.info(
            "[architecture C] enabled version=ai_orchestrated.v5.identity_expression_panel_sync state_version=%s personality_version=%s identity_version=%s observer=post_turn planner=ai single_writer=1",
            reducer.snapshot().version,
            reducer.snapshot().personality.version,
            reducer.snapshot().identity.version,
        )
    except Exception:
        pass
    return True


def shutdown_ai_orchestrated_runtime(host: Any) -> None:
    for name in ("ai_post_turn_observer", "ai_discovery_runtime", "ai_state_reducer"):
        obj = getattr(host, name, None)
        method_name = "shutdown" if name in {"ai_post_turn_observer", "ai_discovery_runtime"} else "close"
        method = getattr(obj, method_name, None)
        if callable(method):
            try:
                method()
            except Exception:
                pass


__all__ = ["install_ai_orchestrated_runtime", "shutdown_ai_orchestrated_runtime"]
