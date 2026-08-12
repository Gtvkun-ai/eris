# -*- coding: utf-8 -*-
"""Small evidence-linked concept graph for consolidated beliefs/worldview."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Mapping

from .json_store_io import atomic_write_json


_STOP = {
    "the", "a", "an", "is", "are", "and", "or", "to", "of", "in", "on", "for", "with",
    "là", "và", "của", "cho", "trong", "một", "những", "các", "được", "có", "không", "với",
}


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    return obj.get(name, default) if isinstance(obj, Mapping) else getattr(obj, name, default)


def _claim(content: Any) -> str:
    if isinstance(content, Mapping):
        for key in ("claim", "text", "description", "summary", "content"):
            value = str(content.get(key, "") or "").strip()
            if value:
                return " ".join(value.split())
        return json.dumps(content, ensure_ascii=False, sort_keys=True)
    return " ".join(str(content or "").split())


def _concepts(text: str) -> list[str]:
    tokens = [x.lower() for x in re.findall(r"[\wÀ-ỹ]+", text, flags=re.UNICODE)]
    tokens = [x for x in tokens if len(x) >= 3 and x not in _STOP and not x.isdigit()]
    # Preserve first occurrence and cap, because a concept graph is not a word landfill.
    return list(dict.fromkeys(tokens))[:14]


class ConceptGraphStore:
    def __init__(self, path: str, *, max_nodes: int = 1600, max_edges: int = 5000) -> None:
        self.path = path
        self.max_nodes = max_nodes
        self.max_edges = max_edges
        self._lock = threading.RLock()

    def load(self) -> dict[str, Any]:
        with self._lock:
            if not os.path.isfile(self.path) or os.path.getsize(self.path) <= 0:
                return {"version": 1, "nodes": {}, "edges": {}}
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if not isinstance(data, dict):
                    raise ValueError("bad graph")
                data.setdefault("version", 1)
                data.setdefault("nodes", {})
                data.setdefault("edges", {})
                return data
            except Exception:
                return {"version": 1, "nodes": {}, "edges": {}}

    def ingest_commit(self, request: Any, *, record_id: str = "") -> dict[str, Any]:
        metadata = dict(_get(request, "metadata", {}) or {})
        content = metadata.get("raw_content", _get(request, "content", ""))
        claim = _claim(content)
        concepts = _concepts(claim)
        if not claim or not concepts:
            return {"nodes": 0, "edges": 0}
        confidence = max(0.0, min(1.0, float(_get(request, "confidence", 0.5) or 0.5)))
        evidence = [str(x) for x in (_get(request, "evidence_ids", []) or []) if str(x).strip()]
        now = time.time()
        with self._lock:
            graph = self.load()
            nodes = graph["nodes"]
            edges = graph["edges"]
            for concept in concepts:
                node = nodes.setdefault(concept, {
                    "label": concept,
                    "weight": 0.0,
                    "occurrences": 0,
                    "evidence_ids": [],
                    "record_ids": [],
                    "updated_at": now,
                })
                node["weight"] = min(1.0, max(float(node.get("weight", 0.0)), confidence) + 0.01)
                node["occurrences"] = int(node.get("occurrences", 0)) + 1
                node["evidence_ids"] = list(dict.fromkeys([*node.get("evidence_ids", []), *evidence]))[-24:]
                if record_id:
                    node["record_ids"] = list(dict.fromkeys([*node.get("record_ids", []), record_id]))[-24:]
                node["updated_at"] = now
            for i, left in enumerate(concepts):
                for right in concepts[i + 1:]:
                    a, b = sorted((left, right))
                    key = f"{a}::{b}"
                    edge = edges.setdefault(key, {
                        "source": a,
                        "target": b,
                        "weight": 0.0,
                        "occurrences": 0,
                        "evidence_ids": [],
                        "updated_at": now,
                    })
                    edge["weight"] = min(1.0, float(edge.get("weight", 0.0)) + confidence * 0.08)
                    edge["occurrences"] = int(edge.get("occurrences", 0)) + 1
                    edge["evidence_ids"] = list(dict.fromkeys([*edge.get("evidence_ids", []), *evidence]))[-24:]
                    edge["updated_at"] = now
            if len(nodes) > self.max_nodes:
                keep = sorted(nodes, key=lambda k: (nodes[k].get("weight", 0.0), nodes[k].get("updated_at", 0.0)), reverse=True)[: self.max_nodes]
                graph["nodes"] = {k: nodes[k] for k in keep}
                allowed = set(keep)
                graph["edges"] = {k: v for k, v in edges.items() if v.get("source") in allowed and v.get("target") in allowed}
            if len(graph["edges"]) > self.max_edges:
                keep_edges = sorted(graph["edges"], key=lambda k: (graph["edges"][k].get("weight", 0.0), graph["edges"][k].get("updated_at", 0.0)), reverse=True)[: self.max_edges]
                graph["edges"] = {k: graph["edges"][k] for k in keep_edges}
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            atomic_write_json(self.path, graph)
            return {"nodes": len(concepts), "edges": max(0, len(concepts) * (len(concepts) - 1) // 2)}

    def neighbors(self, concept: str, *, limit: int = 10) -> list[dict[str, Any]]:
        key = str(concept or "").strip().lower()
        graph = self.load()
        results = []
        for edge in graph.get("edges", {}).values():
            if edge.get("source") == key:
                results.append({"concept": edge.get("target"), **edge})
            elif edge.get("target") == key:
                results.append({"concept": edge.get("source"), **edge})
        results.sort(key=lambda x: (x.get("weight", 0.0), x.get("occurrences", 0)), reverse=True)
        return results[: max(1, int(limit))]


__all__ = ["ConceptGraphStore"]
