"""Root's native Canvas tool. P3 cho phép đề xuất nhánh, không tự gán điểm học."""
from __future__ import annotations

import uuid


class CanvasCapability:
    def __init__(self, host):
        self.host = host

    def invoke_for_root(self, *, arguments, event, recent_history=()):
        canvas = getattr(self.host, "learning_canvas_service", None)
        if canvas is None:
            return {"status": "unavailable", "reason": "canvas_not_ready"}
        operation = arguments.get("operation", "snapshot")
        try:
            with canvas._lock:
                if operation == "library":
                    graph_workspace = canvas.graphs.snapshot()
                    return {"status": "completed", "groups": [
                        {"group_id": canvas.pack.group_id, "title": canvas.pack.path.title,
                         "nodes": list(canvas.pack.path.kp_ids)}]
                        + graph_workspace["groups"][1:], "graph_revision": graph_workspace["revision"]}
                graph_update = None
                if operation in {"graph_create", "graph_expand", "graph_select"}:
                    current = canvas.graphs.snapshot()
                    base = arguments.get("base_graph_revision", current["revision"])
                    if operation == "graph_create":
                        graph = canvas.graphs.create(arguments.get("title"),
                            base_revision=base, origin="eris_proposed", follow=False)
                        graph_update = {"group_id": graph["group_id"], "node_id": graph["selected_node_id"]}
                    elif operation == "graph_expand":
                        additions = canvas.graphs.expand(arguments.get("group_id"), arguments.get("parent_id"),
                            arguments.get("nodes"), base_revision=base, origin="eris_proposed", follow=False)
                        graph_update = {"nodes": additions, "group_id": arguments.get("group_id")}
                    elif operation == "graph_select":
                        # Chỉ nhảy sang bản đồ khi Root có lý do rõ ràng; không đổi focus Java.
                        canvas.graphs.select(arguments.get("group_id"), base_revision=base,
                                             node_id=arguments.get("node_id", ""))
                elif operation == "open_group":
                    if arguments.get("group_id") != canvas.pack.group_id:
                        raise ValueError("unknown_canvas_group")
                elif operation in {"focus", "accept_focus"}:
                    base = arguments.get("base_revision", canvas.focus.snapshot()["revision"])
                    if operation == "accept_focus":
                        if getattr(event, "kind", "") != "user_turn" or not getattr(event, "text", "").strip():
                            raise ValueError("canvas_accept_requires_user_turn")
                        canvas.focus.accept_suggestion(arguments.get("node_id"), base_revision=base)
                    else:
                        canvas.focus.eris_focus(arguments.get("node_id"), base_revision=base,
                                               cause_id=f"root:{uuid.uuid4().hex}")
                elif operation != "snapshot":
                    raise ValueError("unknown_canvas_operation")
                packet = canvas.state_packet()
                if operation in {"open_group", "focus", "accept_focus", "graph_create", "graph_expand", "graph_select"}:
                    packet["open_panel"] = operation in {"open_group", "graph_select"}
                    accepted = self.host._send_runtime_json(packet, channel="learning_canvas")
                    if accepted is False:
                        return {"status": "failed", "reason": "canvas_transport_failed"}
                kernel = getattr(self.host, "conversation_kernel", None)
                bind = getattr(kernel, "bind_canvas_scope", None)
                focus = canvas.focus.snapshot()
                if callable(bind):
                    bind(event.session_id, {"node_id": focus["node_id"], "focus_revision": focus["focus_revision"]})
                applied = not focus["pinned"] and focus["node_id"] == arguments.get("node_id")
                return {"status": "completed", "operation": operation,
                        "learning_canvas": packet["learning_canvas"],
                        **({"applied": applied, "reason": "applied" if applied else "user_pinned"}
                           if operation in {"focus", "accept_focus"} else {}),
                        **({"graph_update": graph_update} if graph_update is not None else {}),
                        "receipt": "state_sent" if operation != "snapshot" else "snapshot_read",
                        "caution": "Đồ thị khám phá chưa phải bằng chứng mastery; Root sở hữu quyết định nói."}
        except (ValueError, TypeError) as exc:
            return {"status": "failed", "reason": str(exc)}


def canvas_capability_for_host(host):
    capability = getattr(host, "canvas_capability", None)
    if not isinstance(capability, CanvasCapability):
        capability = host.canvas_capability = CanvasCapability(host)
    return capability
