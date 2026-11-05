"""P3: bản đồ khám phá kiến thức mở rộng, tách khỏi điểm mastery/bài chấm.

- Không lấy nhánh do AI đề xuất làm bằng chứng người học đã nắm kiến thức.
- Dữ liệu có revision CAS để hai cửa sổ không âm thầm ghi đè lẫn nhau.
- Node được nối bằng parent_id: thêm nhánh mới không thay đổi ID của node cũ.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import unicodedata
import uuid
from typing import Any

META_KEY = "learning_canvas_graphs_p3_v1"
MAX_GROUPS = 24
MAX_NODES = 64  # Giới hạn kích thước snapshot UDP, không giới hạn môn học ở cấp thiết kế.
MAX_GRAPH_BYTES = 35000  # Tránh commit đồ thị không thể trả về trong gói UDP.


def _title(value: Any, max_length: int = 120) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= max_length:
        raise ValueError("invalid_graph_title")
    value = value.strip()
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("invalid_graph_title")
    return value


def _summary(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 240 or any(ord(ch) < 32 and ch != "\n" for ch in value):
        raise ValueError("invalid_graph_summary")
    return value.strip()


def _id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9:_-]{1,120}", value):
        raise ValueError("invalid_graph_id")
    return value


def _new_group_id(title: str) -> str:
    # Hash ngắn làm phần tên gợi nhớ; nonce chống va chạm khi mở nhiều bản đồ cùng tên.
    normalized = unicodedata.normalize("NFKC", title).casefold()
    return "topic-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8] + "-" + uuid.uuid4().hex[:8]


class GraphWorkspace:
    """CRUD cho nhánh kiến thức khám phá (draft), không chạm learning evidence."""

    def __init__(self, store, *, legacy_group_id="java-di"):
        self.store = store
        self.legacy_group_id = legacy_group_id
        self._lock = threading.RLock()

    def _load(self) -> dict:
        raw = self.store.get_meta(META_KEY, None)
        if raw is None:
            return {"schema": "eris.learning.graph.p3", "revision": 0,
                    "selected_group_id": self.legacy_group_id, "groups": []}
        if (not isinstance(raw, dict) or raw.get("schema") != "eris.learning.graph.p3"
                or type(raw.get("revision")) is not int or raw["revision"] < 0
                or not isinstance(raw.get("groups"), list) or len(raw["groups"]) > MAX_GROUPS):
            raise ValueError("invalid_saved_graph_workspace")
        return raw

    def snapshot(self) -> dict:
        with self._lock:
            state = self._load()
            selected = state["selected_group_id"]
            graph = next((group for group in state["groups"] if group["group_id"] == selected), None)
            return {"schema": "eris.learning.graph.p3", "revision": state["revision"],
                    "selected_group_id": selected,
                    "groups": [{"group_id": self.legacy_group_id, "title": "Java · Dependency Injection", "kind": "lesson"}]
                    + [{"group_id": item["group_id"], "title": item["title"],
                        "kind": "exploration", "node_count": len(item["nodes"])} for item in state["groups"]],
                    "graph": copy.deepcopy(graph)}

    def _write(self, state: dict, base_revision: int) -> None:
        if type(base_revision) is not int or base_revision < 0:
            raise ValueError("invalid_graph_revision")
        if base_revision != state["revision"]:
            raise ValueError("stale_graph_revision")
        for graph in state["groups"]:
            if len(json.dumps(graph, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_GRAPH_BYTES:
                raise ValueError("graph_payload_limit")
        state["revision"] += 1
        if not self.store.compare_and_set_meta_revision(META_KEY, base_revision, state):
            raise ValueError("stale_graph_revision")

    def create(self, title: str, *, base_revision: int, origin="user", follow=True) -> dict:
        title = _title(title)
        if origin not in {"user", "eris_proposed"}:
            raise ValueError("invalid_graph_origin")
        with self._lock:
            state = self._load()
            if len(state["groups"]) >= MAX_GROUPS:
                raise ValueError("graph_group_limit")
            group_id = _new_group_id(title)
            root_id = group_id + ":root"
            group = {"group_id": group_id, "title": title, "selected_node_id": root_id,
                     "nodes": [{"id": root_id, "parent_id": "", "title": title, "summary": "",
                                "origin": origin}]}
            state["groups"].append(group)
            if follow:
                state["selected_group_id"] = group_id
            self._write(state, base_revision)
            return copy.deepcopy(group)

    def select(self, group_id: str, *, base_revision: int, node_id: str = "") -> None:
        group_id = _id(group_id)
        with self._lock:
            state = self._load()
            if group_id != self.legacy_group_id:
                group = next((item for item in state["groups"] if item["group_id"] == group_id), None)
                if group is None:
                    raise ValueError("unknown_graph_group")
                if node_id:
                    if node_id not in {node["id"] for node in group["nodes"]}:
                        raise ValueError("unknown_graph_node")
                    group["selected_node_id"] = node_id
            elif node_id:
                raise ValueError("unknown_graph_node")
            state["selected_group_id"] = group_id
            self._write(state, base_revision)

    def expand(self, group_id: str, parent_id: str, nodes: list[dict], *, base_revision: int,
               origin: str = "user", follow=True) -> list[dict]:
        group_id, parent_id = _id(group_id), _id(parent_id)
        if origin not in {"user", "eris_proposed"}:
            raise ValueError("invalid_graph_origin")
        if not isinstance(nodes, list) or not 1 <= len(nodes) <= 8:
            raise ValueError("invalid_graph_nodes")
        # Validate everything before modifying persisted state.
        clean = []
        seen: set[str] = set()
        for node in nodes:
            if not isinstance(node, dict):
                raise ValueError("invalid_graph_node")
            title = _title(node.get("title"))
            summary = _summary(node.get("summary", ""))
            normalized = unicodedata.normalize("NFKC", title).casefold()
            if normalized in seen:
                raise ValueError("duplicate_graph_child")
            seen.add(normalized)
            clean.append((title, summary, normalized))
        with self._lock:
            state = self._load()
            group = next((item for item in state["groups"] if item["group_id"] == group_id), None)
            if group is None:
                raise ValueError("unknown_graph_group")
            if parent_id not in {node["id"] for node in group["nodes"]}:
                raise ValueError("unknown_graph_parent")
            if len(group["nodes"]) + len(clean) > MAX_NODES:
                raise ValueError("graph_node_limit")
            siblings = {unicodedata.normalize("NFKC", node["title"]).casefold()
                        for node in group["nodes"] if node["parent_id"] == parent_id}
            if seen & siblings:
                raise ValueError("duplicate_graph_child")
            additions = [{"id": group_id + ":" + uuid.uuid4().hex[:12],
                          "parent_id": parent_id, "title": title, "summary": summary, "origin": origin}
                         for title, summary, _ in clean]
            group["nodes"].extend(additions)
            if follow:
                group["selected_node_id"] = additions[0]["id"]
                state["selected_group_id"] = group_id
            self._write(state, base_revision)
            return copy.deepcopy(additions)
