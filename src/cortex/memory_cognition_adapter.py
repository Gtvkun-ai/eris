# -*- coding: utf-8 -*-
"""Canonical memory-cognition adapter for V3.

The adapter asks the production MemoryCognitionCore for a budgeted packet when
one is available. It only falls back to already-selected workspace/legacy
memory, never to a blind dump of every store. Memory is context, not a subpoena.
"""
from __future__ import annotations

from typing import Any

from runtime.canonical_cognition import CanonicalMemoryPacket


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _values(obj: Any, name: str) -> list[str]:
    value = _get(obj, name, []) or []
    if isinstance(value, str):
        value = [value]
    return [str(item) for item in value if str(item).strip()]


class MemoryCognitionAdapterEngine:
    module_name = "memory_cognition"

    @staticmethod
    def _find_core(runtime_owner: Any = None, legacy_frame: Any = None) -> Any:
        candidates = [runtime_owner, legacy_frame]
        for owner in candidates:
            if owner is None:
                continue
            for name in ("memory_cognition", "memory_cognition_core", "memory_core"):
                core = _get(owner, name, None)
                if core is not None and (callable(getattr(core, "recall", None)) or callable(getattr(core, "retrieve", None))):
                    return core
            kernel = _get(owner, "memory_kernel", None)
            for name in ("core", "cognition", "memory_cognition"):
                core = _get(kernel, name, None)
                if core is not None and (callable(getattr(core, "recall", None)) or callable(getattr(core, "retrieve", None))):
                    return core
        return None

    def build(self, frame: Any, *, legacy_frame: Any = None, runtime_owner: Any = None, knowledge: Any = None) -> CanonicalMemoryPacket:
        budget = {"fast": 180, "normal": 420, "deep": 760, "reflection": 620}.get(str(_get(frame, "budget_mode", "normal")), 420)
        notes: list[str] = []
        packet = None
        core = self._find_core(runtime_owner, legacy_frame)
        if core is not None:
            try:
                query = str(_get(frame, "user_text", "") or "")
                recall = getattr(core, "recall", None) or getattr(core, "retrieve", None)
                try:
                    packet = recall(query, frame=frame, budget_mode=str(_get(frame, "budget_mode", "normal")))
                except TypeError:
                    try:
                        packet = recall(query, frame=frame)
                    except TypeError:
                        packet = recall(query)
                notes.append("Memory packet được lấy từ MemoryCognitionCore qua budgeted retrieval.")
            except Exception as exc:
                notes.append(f"MemoryCognitionCore retrieval failed; fallback selected context: {type(exc).__name__}.")

        workspace = _get(frame, "workspace", None)
        selected = [str(x) for x in (_get(workspace, "selected_memory", []) or []) if str(x).strip()]
        resonance = _get(legacy_frame, "memory_resonance", None)

        episodic = _values(packet, "episodic") or list(selected)
        semantic = _values(packet, "semantic")
        relational = _values(packet, "relational")
        affective = _values(packet, "affective_residue")
        procedural = _values(packet, "procedural")
        temporal = _values(packet, "temporal")
        spatial = _values(packet, "spatial")
        worldview = _values(packet, "worldview")

        if packet is None:
            episodic.extend(_values(resonance, "episodic"))
            semantic.extend(_values(resonance, "semantic"))
            relational.extend(_values(resonance, "relational"))
            notes.append("Fallback chỉ dùng memory đã qua workspace/legacy resonance, không dump store.")

        knowledge_facts = _values(knowledge, "distilled_facts")
        semantic.extend(knowledge_facts)
        if knowledge_facts:
            notes.append("Knowledge facts có source/evidence từ KnowledgeAcquisitionResult.")

        source_notes = _values(packet, "confidence_notes")
        notes.extend(source_notes[:4])
        return CanonicalMemoryPacket(
            episodic=list(dict.fromkeys(episodic))[:8],
            semantic=list(dict.fromkeys(semantic))[:10],
            relational=list(dict.fromkeys(relational))[:6],
            affective_residue=list(dict.fromkeys(affective))[:5],
            procedural=list(dict.fromkeys(procedural))[:5],
            temporal=list(dict.fromkeys(temporal))[:4],
            spatial=list(dict.fromkeys(spatial))[:4],
            worldview=list(dict.fromkeys(worldview))[:5],
            confidence_notes=list(dict.fromkeys(notes))[:8],
            token_budget=budget,
        )


__all__ = ["MemoryCognitionAdapterEngine"]
