"""Canvas protocol and assessment data; conversation work is queued for Root."""
from __future__ import annotations

from collections import OrderedDict
import copy
from contextlib import nullcontext
import json
import threading
import time
from runtime.learning_core.records import digest

from .graph import GraphWorkspace
from .prefetch import ProgressiveGraphPrefetch
from .focus import CanvasFocusStore
from .pack import load_pack, register_pack
from .snapshot import build_snapshot
from .exercises import CanvasExercises
from .narration import CanvasPlayback


class LearningCanvasService:
    def __init__(self, learning, *, store, pack=None, java_workspace=None):
        self.learning = learning
        self.pack = pack or load_pack()
        register_pack(learning, self.pack)
        self.focus = CanvasFocusStore(store, self.pack)
        # P3 là đồ thị khám phá độc lập; không gán mastery cho nút do người/AI thêm.
        self.graphs = GraphWorkspace(store, legacy_group_id=self.pack.group_id)
        self.prefetch = ProgressiveGraphPrefetch(self.graphs, on_change=self._prefetch_changed)
        self._lock = threading.RLock()
        self._requests: OrderedDict[str, tuple[str, dict]] = OrderedDict()
        self.on_event = None
        self.on_state = None
        self.navigation_guard = None
        self._closed = False
        self.playback = CanvasPlayback(self.pack)
        self.exercises = CanvasExercises(learning, store, self.pack, workspace=java_workspace,
                                        on_completed=self._exercise_completed)

    def close(self):
        self._closed = True
        self.prefetch.close()
        self.exercises.close()

    def _prefetch_changed(self):
        # Worker chỉ phát trạng thái; Root vẫn giữ toàn bộ quyền hội thoại.
        if not self._closed and callable(self.on_state):
            self.on_state(self.state_packet(include_detail=False))

    def _schedule_prefetch(self, group_id: str, node_id: str):
        if group_id != self.pack.group_id and node_id and not self._closed:
            self.prefetch.request(group_id, node_id)

    def _snapshot(self, *, detail_node_id="", include_activity=True):
        focus = self.focus.snapshot()
        result = build_snapshot(self.learning, self.pack, focus, detail_node_id=detail_node_id)
        result["playback_stream_id"] = self.playback.stream_id
        result["graph_workspace"] = self.graphs.snapshot()
        visible = result["graph_workspace"].get("graph")
        if visible:
            result["graph_prefetch"] = {"status": self.prefetch.state(visible["group_id"],
                                                                         visible["selected_node_id"]),
                                        "node_id": visible["selected_node_id"]}
        playback = self.playback.snapshot()
        if playback:
            result["playback"] = playback
        late = self.focus.store.get_meta("learning_canvas_results_v1", {})
        for node in result["nodes"]:
            node["result_count"] = len(late.get(node["id"], []))
        if detail_node_id:
            result["late_results"] = [{k: v for k, v in row.items() if k != "data"} for row in late.get(detail_node_id, [])]
        activity = self.exercises.latest(detail_node_id or focus["node_id"]) if include_activity else None
        if activity:
            result["activity"] = activity
        return result

    def defer_result(self, kind, metadata, scope, *, event_id=""):
        node_id = scope.get("node_id")
        self.pack.node(node_id)
        with self._lock:
            late = self.focus.store.get_meta("learning_canvas_results_v1", {})
            key = event_id or digest([kind, metadata])
            rows = late.get(node_id, [])
            if any(row["id"] == key for row in rows):
                return
            data = metadata.get("research_capability", metadata.get("work_capability", metadata.get("canvas_capability", {})))
            rows.append({"id": key, "kind": kind, "summary": str(data.get("summary") or data.get("result") or "Đã có kết quả")[:2000],
                         "data": dict(data) if len(json.dumps(data, ensure_ascii=False).encode("utf-8")) <= 32000
                             else {"summary": str(data.get("summary", ""))[:12000], "data_truncated": True},
                         "focus_revision": scope.get("focus_revision"), "received_at": time.time()})
            late[node_id] = rows[-4:]
            self.focus.store.set_meta("learning_canvas_results_v1", late)
            if callable(self.on_state):
                self.on_state(self.state_packet(include_detail=False))

    def _assessment_event(self, activity_id):
        payload = self.exercises.take_event(activity_id)
        if payload:
            focus = self.focus.snapshot()
            scope = {"node_id": payload["node_id"], "focus_revision": payload.get("focus_revision", focus["focus_revision"])}
            if focus["node_id"] != scope["node_id"] or focus["focus_revision"] != scope["focus_revision"]:
                self.defer_result("tutor_result", {"canvas_capability": payload}, scope, event_id=payload["event_id"])
            elif callable(self.on_event):
                self.on_event(payload)

    def _exercise_completed(self, activity):
        if self._closed:
            return
        activity = self.exercises.fallback(activity)
        self._assessment_event(activity["activity_id"])
        if callable(self.on_state):
            packet = self.state_packet(include_detail=False)
            current = packet["learning_canvas"].get("activity", {})
            if current.get("activity_id") != activity["activity_id"]:
                packet["exercise_update"] = activity
            self.on_state(packet)

    def state_packet(self, *, include_detail=True) -> dict:
        """Server-originated state projection, applied by the UI without navigate."""
        with self._lock:
            focus = self.focus.snapshot()
            return {"type": "learning_canvas_state", "parse_mode": "learning_canvas_state",
                    "should_speak": False, "status": "ok",
                    "learning_canvas": self._snapshot(detail_node_id=focus["node_id"] if include_detail else "")}

    def handle(self, request: dict) -> dict:
        request_id = request.get("request_id", "")
        action = request.get("action", "open")
        envelope = {"type": "learning_canvas_ack", "parse_mode": "learning_canvas_ack",
                    "should_speak": False, "request_id": request_id if isinstance(request_id, str) else "",
                    "action": action if isinstance(action, str) else "", "status": "ok", "message": "Đã cập nhật."}
        with self._lock:
            try:
                if not isinstance(request_id, str) or not 1 <= len(request_id) <= 120:
                    raise ValueError("invalid_canvas_request_id")
                fingerprint = json.dumps(request, sort_keys=True, ensure_ascii=False, allow_nan=False)
                if len(fingerprint.encode("utf-8")) > 20000:
                    raise ValueError("canvas_request_too_large")
                if request_id in self._requests:
                    previous, response = self._requests[request_id]
                    if previous != fingerprint:
                        raise ValueError("canvas_request_id_reused")
                    return copy.deepcopy(response)
                # P3: graph actions có revision riêng để không đụng focus/điểm học Java.
                graph_actions = {"graph_create", "graph_select", "graph_expand"}
                if action not in graph_actions and request.get("group_id", self.pack.group_id) != self.pack.group_id:
                    raise ValueError("unknown_canvas_group")
                prefetch_target = None
                if action == "graph_create":
                    graph = self.graphs.create(request.get("title"),
                        base_revision=request.get("base_graph_revision"))
                    envelope["graph_update"] = {"group_id": graph["group_id"],
                        "node_id": graph["selected_node_id"]}
                    prefetch_target = (graph["group_id"], graph["selected_node_id"])
                elif action == "graph_select":
                    self.graphs.select(request.get("group_id"), node_id=request.get("node_id", ""),
                        base_revision=request.get("base_graph_revision"))
                    viewed = self.graphs.snapshot().get("graph")
                    if viewed:
                        prefetch_target = (viewed["group_id"], viewed["selected_node_id"])
                elif action == "graph_expand":
                    children = self.graphs.expand(request.get("group_id"), request.get("parent_id"),
                        [{"title": request.get("title"), "summary": request.get("summary", "")}],
                        base_revision=request.get("base_graph_revision"))
                    envelope["graph_update"] = {"group_id": request.get("group_id"),
                        "node_id": children[0]["id"]}
                    prefetch_target = (request.get("group_id"), children[0]["id"])
                elif action == "navigate":
                    with self.navigation_guard() if callable(self.navigation_guard) else nullcontext():
                        self.focus.navigate(request.get("node_id"), base_revision=request.get("base_revision"))
                elif action == "exercise":
                    if request.get("node_id") != self.focus.snapshot()["node_id"]:
                        raise ValueError("canvas_focus_changed")
                    envelope["exercise_update"] = self.exercises.open(request.get("node_id"), request.get("exercise_id"), request_id)
                elif action in {"submit", "hint", "reveal", "exercise_status"}:
                    activity = self.exercises.handle(action, request)
                    envelope["exercise_update"] = activity
                    if action in {"submit", "exercise_status"} and activity["status"] == "completed":
                        self._assessment_event(activity["activity_id"])
                elif action == "ack_eris_focus":
                    self.focus.acknowledge(base_revision=request.get("base_revision"), cause_id=request.get("cause_id"))
                elif action != "open":
                    raise ValueError("unknown_canvas_action")
                focus = self.focus.snapshot()
                detail_id = request.get("node_id", focus["node_id"]) if action == "open" else focus["node_id"]
                if not isinstance(detail_id, str):
                    raise ValueError("unknown_canvas_node")
                exercise_response = "exercise_update" in envelope
                envelope["learning_canvas"] = self._snapshot(detail_node_id="" if exercise_response else detail_id,
                                                             include_activity=not exercise_response)
                # The validated pack already bounds detail; this also guards future changes.
                if len(json.dumps(envelope, ensure_ascii=False).encode("utf-8")) > 60000:
                    raise ValueError("canvas_response_too_large")
                self._requests[request_id] = (fingerprint, copy.deepcopy(envelope))
                if prefetch_target is not None:
                    # Sau khi commit thành công, không chặn ACK/UI vì Gemini.
                    self._schedule_prefetch(*prefetch_target)
                while len(self._requests) > 128:
                    self._requests.popitem(last=False)
                if action in {"graph_create", "graph_expand", "graph_select"} and callable(self.on_event):
                    # Root có thể đề xuất bài giảng / mở rộng thêm, không có quyền tự chấm mastery.
                    graph_state = envelope["learning_canvas"]["graph_workspace"]
                    current = graph_state.get("graph") or {}
                    selected_node = next((n for n in current.get("nodes", [])
                                          if n["id"] == current.get("selected_node_id")), {})
                    self.on_event({"action": action, "node_id": focus["node_id"],
                        "focus_revision": focus["focus_revision"],
                        "graph_group_id": graph_state["selected_group_id"],
                        "graph_node_id": current.get("selected_node_id", ""),
                        "graph_title": current.get("title", ""),
                        "graph_node_title": selected_node.get("title", ""),
                        "graph_node_summary": selected_node.get("summary", "")})
                if action == "navigate" and callable(self.on_event):
                    self.on_event({"action": "navigate", "node_id": focus["node_id"],
                                   "focus_revision": focus["focus_revision"], "learning_canvas": envelope["learning_canvas"]})
            except (ValueError, TypeError) as exc:
                reason = str(exc) if isinstance(exc, ValueError) else "invalid_canvas_request"
                envelope.update(status="conflict" if reason in {"stale_canvas_revision", "stale_graph_revision"} else "error", message=reason)
                envelope["learning_canvas"] = self._snapshot(detail_node_id=self.focus.snapshot()["node_id"])
            return envelope
