# -*- coding: utf-8 -*-
"""ERIS runtime composition root.

Behavior lives in typed services and compatibility mixins. This module keeps the
public ``RuntimeCoordinator`` import stable while refusing to become a second
implementation of every subsystem again. Humanity has tried the god-object
pattern often enough to know how that movie ends.
"""
from __future__ import annotations

from domain import Decision
from failure_meta import is_technical_failure_meta
from runtime.autonomous_loop_runtime import AutonomousLoopRuntimeMixin
from runtime.chat_cycle import ChatCycleMixin
from runtime.cognitive_event_runtime import CognitiveEventRuntimeMixin
from runtime.coordinator_bootstrap import CoordinatorBootstrapMixin
from runtime.coordinator_shutdown import CoordinatorShutdownMixin
from runtime.incoming_protocol_runtime import IncomingProtocolRuntimeMixin
from runtime.mental_process_runtime import MentalProcessRuntimeMixin
from runtime.model_memory_runtime import ModelMemoryRuntimeMixin
from runtime.observer_private_runtime import ObserverPrivateRuntimeMixin
from runtime.presence_controller import PresenceControllerMixin
from runtime.prompt_context_builder import PromptContextBuilderMixin
from runtime.provider_action_runtime import ProviderActionRuntimeMixin
from runtime.public_output_runtime import PublicOutputRuntimeMixin
from runtime.screen_vision_runtime import ScreenVisionRuntimeMixin
from runtime.settings_control_runtime import SettingsControlRuntimeMixin
from runtime.state_commit_service import StateCommitServiceMixin
from runtime.tutor_research_runtime import TutorResearchRuntimeMixin
from runtime.user_control_runtime import UserControlRuntimeMixin

VISION_TRACE_MARKER = "vision_facts_attached"

FALLBACK_BY_INTENT: dict[str, tuple[str, ...]] = {
    "random_chatter": (
        "bạn gọi tôi ra chỉ để nghe tôi nói linh tinh à.",
        "Tín hiệu mờ quá. Tôi lùi lại một nhịp.",
    ),
    "inner_whim": ("Mạch này vẫn hơi nghẽn lại.", "Nhịp này cứ để nhỏ thôi."),
    "micro_presence": ("Mạch này vẫn hơi nghẽn.", "Nhịp này vẫn còn ở đây."),
    "curious_question": ("Có chỗ nào đang vướng nhẹ không?", "Đoạn này còn mắc ở đâu à?"),
    "screen_observation": (
        "Tôi chỉ dám bám vào chỗ này: file_saved.",
        "Tôi giữ câu này sát phần đang hiện ra thôi.",
    ),
}


def _is_nonsemantic_fallback_decision(decision: Decision) -> bool:
    """Return whether a public decision is only a technical fallback."""

    intent = str(getattr(decision, "intent", "") or "")
    parse_mode = str(getattr(decision, "parse_mode", "") or "")
    debug_trace = str(getattr(decision, "debug_trace", "") or "")
    text = str(getattr(decision, "text", "") or "").lower()
    fallback_intents = {"fallback_reply", "format_repair_fallback", "service_error", "no_fallback_block"}
    fallback_modes = {"format_repair_fallback", "service_error", "no_fallback_block"}
    if is_technical_failure_meta(getattr(decision, "failure_meta", None)):
        return True
    if intent in fallback_intents or parse_mode in fallback_modes:
        return True
    if "http_5xx_fallback" in debug_trace or "format_violation_recovered" in debug_trace:
        return True
    return "lỗi định dạng" in text or "loi dinh dang" in text or "vấn đề đường truyền" in text


class RuntimeCoordinator(
    CoordinatorBootstrapMixin,
    ModelMemoryRuntimeMixin,
    PublicOutputRuntimeMixin,
    UserControlRuntimeMixin,
    CoordinatorShutdownMixin,
    AutonomousLoopRuntimeMixin,
    ObserverPrivateRuntimeMixin,
    CognitiveEventRuntimeMixin,
    MentalProcessRuntimeMixin,
    IncomingProtocolRuntimeMixin,
    SettingsControlRuntimeMixin,
    TutorResearchRuntimeMixin,
    ScreenVisionRuntimeMixin,
    ProviderActionRuntimeMixin,
    ChatCycleMixin,
    StateCommitServiceMixin,
    PromptContextBuilderMixin,
    PresenceControllerMixin,
):
    """Stable facade over the composed ERIS runtime services."""

    _CHAT_VISION_THROTTLE_SEC = 6.0
    _LIGHT_TUTOR_RESEARCH_CUES = (
        "nghiên cứu", "nghien cuu", "đào sâu", "dao sau", "kiểm chứng", "kiem chung",
        "hỏi gemini", "hoi gemini", "hỏi sư phụ", "hoi su phu", "fix elegant", "deep research",
    )
    _LIGHT_TUTOR_COMMAND_WORDS = (
        "hỏi", "hoi", "nhờ", "nho", "kêu", "keu", "gemini", "tutor", "sư phụ", "su phu",
    )
    _LIGHT_TUTOR_REFERENT_ONLY = (
        "cái này", "cai nay", "cái đó", "cai do", "phần này", "phan nay",
        "phần đó", "phan do", "ý này", "y nay",
    )
    _KNOWLEDGE_QUESTION_MARKERS = (
        "hỏi gemini", "hoi gemini", "hỏi sư phụ", "hoi su phu", "nhờ gemini",
        "nho gemini", "kêu gemini", "keu gemini", "tra gemini",
        "là gì", "là ai", "là con gì", "là cái gì", "là chất gì", "là nước nào",
        "là bệnh gì", "là môn gì", "là ngôn ngữ gì", "nghĩa là gì", "viết tắt của",
        "tại sao", "vì sao", "do đâu", "nguyên nhân", "ở đâu", "khi nào", "năm nào",
        "thế kỷ", "ai phát minh", "ai sáng", "ai là người", "khác nhau", "khác gì",
        "so với", "có tác dụng gì", "hoạt động như thế nào", "hoạt động ra sao", "định nghĩa",
    )

    def __init__(
        self,
        *,
        logger,
        transport,
        llm_service,
        parser,
        telemetry_service,
        memory_core,
        body_running_fn,
        action_executor=None,
        memory_semantic_parser=None,
    ):
        super().__init__(
            logger=logger,
            transport=transport,
            llm_service=llm_service,
            parser=parser,
            telemetry_service=telemetry_service,
            memory_core=memory_core,
            body_running_fn=body_running_fn,
            action_executor=action_executor,
            memory_semantic_parser=memory_semantic_parser,
        )
        # Agent Console là projection/control plane độc lập với cognition. Gắn bridge
        # ở composition root để Subject Core có thể comment/advisory/redirect/veto
        # executor mà không phải import LangGraph hay biết schema tool của Gemini.
        try:
            from runtime.agent_harness.task_store import AgentTaskStore
            from runtime.agent_harness.event_bus import AgentEventBus
            from runtime.agent_harness.supervisor_bridge import AgentSupervisorBridge

            self.agent_task_store = AgentTaskStore()
            self.agent_event_bus = AgentEventBus(self.agent_task_store, logger=logger)
            self.agent_supervisor = AgentSupervisorBridge(
                self.agent_task_store,
                self.agent_event_bus,
                logger=logger,
            )
            self._agent_supervisor_marks = {}
            add_listener = getattr(self.agent_event_bus, "add_listener", None)
            if callable(add_listener):
                add_listener(self._supervise_agent_event)
        except Exception as exc:
            self.agent_task_store = None
            self.agent_event_bus = None
            self.agent_supervisor = None
            self._agent_supervisor_marks = {}
            debug = getattr(logger, "debug", None)
            if callable(debug):
                debug("[agent-console] supervisor bridge unavailable: %s", exc)

        # Agent Harness V2: Gemini chỉ quyết định tool call; side effect thật vẫn
        # đi qua ActionExecutor/SandboxWorld. Import lazy để Eris vẫn boot được
        # trên máy chưa cài optional LangGraph dependency.
        self.agent_harness = None
        self.agent_executor_backend = None
        self.agent_capability_self_model = None
        self._agent_task_threads = {}
        self._agent_last_started_task_id = ""
        self.agent_default_workspace = ""
        if action_executor is not None:
            try:
                import os
                from pathlib import Path
                from runtime.agent_harness.gemini_cli_executor import GeminiCliDecisionExecutor
                from runtime.agent_harness.graph_builder import AgentHarness
                from runtime.agent_harness.native_tool_adapter import NativeCapabilityToolAdapter

                source_root = Path(__file__).resolve().parents[1]
                workspace_root = source_root
                for candidate in (source_root, *source_root.parents):
                    if (candidate / ".git").is_dir():
                        workspace_root = candidate
                        break
                self.agent_default_workspace = str(workspace_root)
                native_tools = NativeCapabilityToolAdapter(action_executor)
                gemini = GeminiCliDecisionExecutor(
                    workspace=workspace_root,
                    model=os.environ.get("ERIS_GEMINI_AGENT_MODEL", "auto"),
                    logger=logger,
                )
                self.agent_executor_backend = gemini
                self.agent_harness = AgentHarness(
                    gemini,
                    str(source_root / "powers"),
                    tool_registry=native_tools.registry(),
                    tool_specs=native_tools.tool_specs(),
                    task_store=self.agent_task_store,
                    event_bus=self.agent_event_bus,
                    executor_name="gemini-cli",
                    model_name=gemini.model,
                    logger=logger,
                )
                ok, reason = gemini.health()
                from runtime.agent_harness.capability_self_model import CapabilitySelfModel
                self.agent_capability_self_model = CapabilitySelfModel(
                    harness=self.agent_harness,
                    harness_ready=ok,
                )
                info = getattr(logger, "info", None)
                if callable(info):
                    info(
                        "[agent-harness] ready graph=langgraph executor=gemini-cli health=%s detail=%s skills=%s tools=%s",
                        ok, reason, len(self.agent_harness.discovery.capabilities), len(native_tools.agent_ids()),
                    )
                    info(
                        "[capability-self] instant=%s long_skills=%s executor_ready=%s",
                        len(self.agent_capability_self_model.instant_capabilities()),
                        len(self.agent_capability_self_model.long_skills()),
                        self.agent_capability_self_model.harness_ready,
                    )
            except Exception as exc:
                self.agent_harness = None
                self.agent_capability_self_model = None
                debug = getattr(logger, "debug", None)
                if callable(debug):
                    debug("[agent-harness] unavailable: %s", exc)

        # Self-model tồn tại ngay cả khi Gemini CLI/LangGraph đang unavailable.
        # Eris vẫn phải biết các native capability nhanh của chính mình thay vì
        # suy ra "không làm được" chỉ vì backstage executor đang chết.
        if self.agent_capability_self_model is None:
            try:
                from runtime.agent_harness.capability_self_model import CapabilitySelfModel
                self.agent_capability_self_model = CapabilitySelfModel(
                    harness=None,
                    harness_ready=False,
                )
            except Exception:
                self.agent_capability_self_model = None

    def _supervise_agent_event(self, event: dict) -> None:
        """Deterministic first-line technical supervision for Gemini execution.

        This is intentionally narrow: only intervene on observable anti-patterns
        with low false-positive risk. Subject Core/model review can add richer
        judgment later through the same AgentSupervisorBridge.
        """
        if not isinstance(event, dict):
            return
        event_type = str(event.get("type", "") or "").strip().lower()
        if event_type.startswith("supervisor_") or event_type in {"user_directive", "directive_consumed"}:
            return
        task_id = str(event.get("task_id", "") or "").strip()
        if not task_id:
            # Events persisted by the store do not currently duplicate task_id;
            # derive it by locating the matching event id in recent tasks.
            event_id = str(event.get("event_id", "") or "")
            store = getattr(self, "agent_task_store", None)
            if store is not None and event_id:
                snapshot = store.snapshot(task_limit=8, event_limit=40)
                for task in snapshot.get("tasks", []):
                    if any(str(item.get("event_id", "")) == event_id for item in task.get("events", [])):
                        task_id = str(task.get("task_id", "") or "")
                        break
        if not task_id:
            return

        store = getattr(self, "agent_task_store", None)
        supervisor = getattr(self, "agent_supervisor", None)
        if store is None or supervisor is None:
            return
        task = store.get_task(task_id, event_limit=48)
        if not isinstance(task, dict):
            return
        events = [item for item in task.get("events", []) if isinstance(item, dict)]
        marks = self._agent_supervisor_marks.setdefault(task_id, set())

        def _mark_once(key: str, instruction: str, reason: str) -> None:
            if key in marks:
                return
            marks.add(key)
            try:
                supervisor.advisory(task_id, instruction, reason=reason)
            except Exception:
                marks.discard(key)

        # Patch should follow evidence. If Gemini tries to write before it has
        # inspected any project source, push it back toward root-cause work.
        if event_type == "tool_started":
            tool = str((event.get("data") or {}).get("tool", "") if isinstance(event.get("data"), dict) else "")
            if tool == "project_apply_patch":
                inspected = any(
                    str((item.get("data") or {}).get("tool", "")) in {
                        "project_read_file", "project_search_text", "project_find_symbol", "project_git_diff",
                        "read_current_error", "inspect_runtime_log",
                    }
                    for item in events
                    if isinstance(item.get("data"), dict)
                )
                if not inspected:
                    _mark_once(
                        "patch_before_inspection",
                        "Dừng vá ngay. Đọc implementation/caller và evidence hiện có trước, rồi mới chọn patch nhỏ nhất.",
                        "Gemini bắt đầu project_apply_patch trước khi có inspection evidence trong task.",
                    )

        # Repeated failures are a replan signal, not a retry invitation.
        failed_tools = [
            str((item.get("data") or {}).get("tool", ""))
            for item in events
            if str(item.get("type", "")) == "tool_failed" and isinstance(item.get("data"), dict)
        ]
        if len(failed_tools) >= 2 and failed_tools[-1] and failed_tools[-1] == failed_tools[-2]:
            _mark_once(
                f"repeat_fail:{failed_tools[-1]}",
                f"Đừng retry {failed_tools[-1]} theo cùng cách. Đọc failure mới, đổi giả thuyết hoặc đổi tool rồi replan.",
                "Cùng một tool vừa thất bại liên tiếp.",
            )

        test_failures = sum(
            1 for item in events
            if str(item.get("type", "")) == "test_result"
            and isinstance(item.get("data"), dict)
            and int((item.get("data") or {}).get("failed", 0) or 0) > 0
        )
        if test_failures >= 2:
            _mark_once(
                "repeated_test_failure",
                "Hai vòng test đã fail. Dừng sửa nối tiếp theo triệu chứng; quay lại failure gần nhất và xác minh root cause trước patch tiếp.",
                "Verification thất bại lặp lại trong cùng task.",
            )

        changed_files = list(task.get("changed_files", []) or [])
        if len(changed_files) >= 10:
            _mark_once(
                "scope_expansion",
                "Scope đang phình quá rộng. Kiểm tra lại xem có thể giải quyết bằng ít file hơn và tái sử dụng abstraction hiện hữu không.",
                f"Task đã chạm {len(changed_files)} file.",
            )

        # Close the autonomy loop: terminal Gemini work becomes fresh Eris context
        # and wakes the self-turn loop. We do not make the executor speak directly;
        # Subject Core still owns wording/personality and can judge the result.
        if event_type in {"task_completed", "task_failed"}:
            terminal_key = f"frontstage_terminal:{event_type}"
            if terminal_key not in marks:
                marks.add(terminal_key)
                try:
                    data = event.get("data") if isinstance(event.get("data"), dict) else {}
                    final_text = str(data.get("final", "") or event.get("detail", "") or event.get("summary", "") or "").strip()
                    goal = str(task.get("clarified_goal", "") or task.get("goal", "") or "").strip()
                    status_label = "COMPLETED" if event_type == "task_completed" else "FAILED"
                    note = (
                        f"[BACKSTAGE AGENT {status_label}]\n"
                        f"Task: {goal[:1200]}\n"
                        f"Result: {final_text[:6000]}\n"
                        "This is fresh execution evidence from Gemini/LangGraph. Review it as Eris, "
                        "then proactively tell the user the meaningful result when appropriate. "
                        "Do not pretend you personally performed steps that were executed by Gemini."
                    )
                    append_history = getattr(self, "_append_chat_history", None)
                    if callable(append_history):
                        append_history("system", note)
                    wake = getattr(self, "_wake_autonomous_loop", None)
                    if callable(wake):
                        wake(f"agent_{event_type}:{task_id}")
                except Exception as exc:
                    logger = getattr(self, "logger", None)
                    debug = getattr(logger, "debug", None)
                    if callable(debug):
                        debug("[agent-harness] terminal frontstage bridge degraded task=%s error=%s", task_id, exc)

    def execute_agent_task(
        self,
        goal: str,
        *,
        thread_id: str = "",
        clarified_goal: str = "",
        task_id: str = "",
        task_mode: str = "execute",
        source: str = "eris_chat",
    ):
        """Run one Unified Agent Harness task synchronously.

        Chat normally uses ``start_agent_task_async`` so Gemini execution never
        blocks the public reply. Tests/CLI can still call this synchronous entry.
        """
        harness = getattr(self, "agent_harness", None)
        if harness is None:
            raise RuntimeError("agent_harness_unavailable")
        import uuid
        resolved_thread = str(thread_id or f"agent_{uuid.uuid4().hex[:12]}")
        import inspect
        invoke = harness.invoke
        kwargs = {
            "thread_id": resolved_thread,
            "task_id": str(task_id or ""),
            "clarified_goal": clarified_goal,
        }
        try:
            signature = inspect.signature(invoke)
            parameters = signature.parameters
            accepts_var_kwargs = any(
                item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values()
            )
            if accepts_var_kwargs or "task_mode" in parameters:
                kwargs["task_mode"] = str(task_mode or "execute")
            if accepts_var_kwargs or "source" in parameters:
                kwargs["source"] = str(source or "eris_chat")
        except (TypeError, ValueError):
            # C-extension/mock callables may not expose a signature. Real AgentHarness
            # does, so falling back to the legacy four arguments is safe here.
            pass
        return invoke(goal, **kwargs)

    def start_agent_task_async(
        self,
        goal: str,
        *,
        thread_id: str = "",
        clarified_goal: str = "",
        source_turn_id: str = "",
        source: str = "eris_chat",
        task_mode: str = "execute",
    ) -> dict:
        """Start Gemini/LangGraph in a daemon worker and return immediately.

        The task id is reserved before the thread starts, so the foreground
        writer and Agent Console can refer to one stable execution session.
        """
        harness = getattr(self, "agent_harness", None)
        if harness is None:
            return {"status": "unavailable", "reason": "agent_harness_unavailable", "task_id": ""}

        import threading
        import uuid

        # An explicit execution request authorizes selecting the current Eris
        # workspace as context when no workspace is active yet. This does not
        # modify files; it only makes the existing project tools dynamically live.
        try:
            manager = getattr(self, "workspace_manager", None)
            active_record = getattr(manager, "active_record", None)
            active = active_record() if callable(active_record) else None
            default_workspace = str(getattr(self, "agent_default_workspace", "") or "").strip()
            if active is None and manager is not None and default_workspace:
                manager.join(default_workspace, activate=True)
        except Exception as exc:
            logger = getattr(self, "logger", None)
            debug = getattr(logger, "debug", None)
            if callable(debug):
                debug("[agent-harness] default workspace activation degraded: %s", exc)

        task_id = f"task_{uuid.uuid4().hex[:12]}"
        resolved_thread = str(thread_id or source_turn_id or f"agent_{uuid.uuid4().hex[:12]}")
        self._agent_last_started_task_id = task_id

        # Reserve the task synchronously so Agent Console never races a just-
        # started worker and shows an empty screen for the first snapshot.
        store = getattr(self, "agent_task_store", None)
        if store is not None:
            try:
                executor = str(getattr(harness, "executor_name", "gemini") or "gemini")
                model = str(getattr(harness, "model_name", "") or "")
                store.create_task(
                    clarified_goal or goal,
                    task_id=task_id,
                    executor=executor,
                    model=model,
                    thread_id=resolved_thread,
                    metadata={
                        "source_turn_id": source_turn_id,
                        "original_goal": goal,
                        "source": str(source or "eris_chat"),
                        "task_mode": str(task_mode or "execute"),
                    },
                )
                store.update_task(task_id, clarified_goal=clarified_goal or goal)
                supervisor = getattr(self, "agent_supervisor", None)
                if supervisor is not None:
                    supervisor.comment(
                        task_id,
                        (
                            "Tôi đang theo dõi phiên consult này; Gemini chỉ được inspect, không được sửa workspace."
                            if str(task_mode or "execute").lower() == "inspect"
                            else "Tôi đang theo dõi task này. Nếu hướng thực thi phình, lặp lỗi hoặc vá trước khi hiểu root cause, tôi sẽ can thiệp."
                        ),
                        importance=0.58,
                    )
            except Exception as exc:
                logger = getattr(self, "logger", None)
                debug = getattr(logger, "debug", None)
                if callable(debug):
                    debug("[agent-harness] precreate task degraded: %s", exc)

        def _worker() -> None:
            try:
                self.execute_agent_task(
                    goal,
                    thread_id=resolved_thread,
                    clarified_goal=clarified_goal,
                    task_id=task_id,
                    task_mode=task_mode,
                    source=source,
                )
            except Exception as exc:
                logger = getattr(self, "logger", None)
                warning = getattr(logger, "warning", None)
                if callable(warning):
                    warning("[agent-harness] async task failed task=%s error=%s", task_id, exc)
            finally:
                try:
                    self._agent_task_threads.pop(task_id, None)
                except Exception:
                    pass

        thread = threading.Thread(
            target=_worker,
            name=f"eris-agent-{task_id[-6:]}",
            daemon=True,
        )
        self._agent_task_threads[task_id] = thread
        thread.start()
        return {
            "status": "started",
            "task_id": task_id,
            "thread_id": resolved_thread,
            "goal": clarified_goal or goal,
            "source": str(source or "eris_chat"),
            "task_mode": str(task_mode or "execute"),
        }

    def route_agent_user_turn(
        self,
        user_text: str,
        *,
        previous_assistant_text: str = "",
        turn_id: str = "",
    ) -> dict:
        """Conservative foreground routing into the execution harness.

        Returns a public-safe projection used by the normal Eris writer.  A
        ``clarify`` route never starts Gemini; ``execute`` starts it in parallel.
        """
        try:
            from runtime.agent_harness.chat_router import classify_agent_chat_route
            self_model = getattr(self, "agent_capability_self_model", None)
            refresh_self_model = getattr(self_model, "refresh", None)
            if callable(refresh_self_model):
                refresh_self_model()
            route = classify_agent_chat_route(
                user_text,
                previous_assistant_text=previous_assistant_text,
                self_model=self_model,
            )
        except Exception as exc:
            return {
                "action": "none",
                "goal": "",
                "reason": f"router_error:{type(exc).__name__}",
                "confidence": 0.0,
                "clarification": "",
            }

        payload = route.to_dict()
        self_model = getattr(self, "agent_capability_self_model", None)
        if self_model is not None:
            try:
                assessment = self_model.assess(user_text)
                payload["self_model"] = assessment.to_dict()
                if route.reason == "capability_query":
                    payload["self_model_context"] = self_model.prompt_summary()
            except Exception:
                pass
        if route.action not in {"execute", "consult"}:
            return payload

        task_mode = "inspect" if route.action == "consult" else "execute"
        started = self.start_agent_task_async(
            route.goal or user_text,
            thread_id=turn_id,
            clarified_goal=route.goal or user_text,
            source_turn_id=turn_id,
            source="eris_chat",
            task_mode=task_mode,
        )
        payload.update({
            "task_id": str(started.get("task_id", "") or ""),
            "start_status": str(started.get("status", "") or ""),
            "start_reason": str(started.get("reason", "") or ""),
            "task_mode": str(started.get("task_mode", task_mode) or task_mode),
            "source": str(started.get("source", "eris_chat") or "eris_chat"),
        })
        return payload
