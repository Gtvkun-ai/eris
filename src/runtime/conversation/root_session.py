# -*- coding: utf-8 -*-
"""Root conversation warm-up: nạp Self một lần, sau đó gửi delta thật.

Không có Self/snapshot/database mới. Owner của identity và ký ức vẫn là những
service hiện hành; phiên này chỉ là cache *vận chuyển + hội thoại* của DeepSeek.
Một câu trả lời lỗi, bị preflight cắt hay không có nguyên văn wire response sẽ
làm hủy chuỗi trước khi tiếp tục. Không lưu private reasoning/chain-of-thought.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Mapping, Sequence

from llm.token_budget import detect_provider, estimate_tokens, hard_cap_for_provider
from llm.provider_errors import provider_failure


def _jsonable(value: Any) -> Any:
    """Chuyển view hiện có sang dữ liệu JSON, không tóm tắt hoặc xếp hạng belief."""
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError, OverflowError):
        return None


def _read_self(host: Any) -> dict[str, Any]:
    """Đọc nguyên các nguồn Self đang tồn tại; không đọc nhật ký nghĩ thầm thô.

    Đưa nguyên state từ Reducer (kể cả các belief yếu/mâu thuẫn), không xén
    top-k. Dữ liệu thời gian thực mới đến lượt sau qua delta.
    """
    result: dict[str, Any] = {}
    reducer = getattr(host, "ai_state_reducer", None)
    snapshot = getattr(reducer, "snapshot", None)
    if callable(snapshot):
        state = snapshot()
        to_dict = getattr(state, "to_dict", None)
        if callable(to_dict):
            raw = to_dict()
            if isinstance(raw, Mapping):
                # Toàn bộ MindState là của reducer, không có luật lọc belief,
                # xếp hạng chủ đề hay giới hạn top-k nào ở đây.
                result["mind_state"] = _jsonable(raw)
    subject = getattr(host, "subject_service", None)
    view = getattr(subject, "self_view", None)
    if callable(view):
        raw = view()
        if isinstance(raw, Mapping):
            # generated_at là đồng hồ lúc projection, không phải Self delta.
            result["subject_self"] = _jsonable({k: v for k, v in raw.items() if k != "generated_at"})
    # Memory đã được host load từ owner thực, KHÔNG truy cập file/sqlite khác.
    # Không lọc theo topic hoặc lấy top-k. Có thể rất dài ở lần nạp đầu.
    for key in ("memory_state", "long_term_memory"):
        raw = getattr(host, key, None)
        if raw is not None:
            result[key] = _jsonable(raw)
    return result


def _changed(previous: Any, current: Any) -> Any:
    """Chỉ gửi trường mới/đổi, không xếp hạng giá trị của belief.

    None biểu thị không có delta; nếu field bị xóa, đánh dấu bằng tombstone để
    DeepSeek không tiếp tục tin một giá trị đã không còn trong owner state.
    """
    if previous == current:
        return None
    if isinstance(previous, dict) and isinstance(current, dict):
        out = {}
        for key in previous.keys() - current.keys():
            out[key] = {"__erased_from_self": True}
        for key, value in current.items():
            if key not in previous:
                out[key] = value
            else:
                diff = _changed(previous[key], value)
                if diff is not None:
                    out[key] = diff
        return out or None
    if current is None:
        return {"__value_now_null": True}
    return current


class RootConversationSession:
    """Một transcript được xác nhận, thuộc riêng Root, không thuộc Writer.

    Nhận reply RAW để transcript khớp byte với Whale2API SessionGuard V3.
    Không tái sử dụng sau lỗi/timeout; chỉ session mới được nạp lại toàn bộ Self.
    """

    def __init__(self, *, logger: Any = None) -> None:
        self.logger = logger
        self._lock = threading.Lock()
        self._messages: list[dict[str, str]] = []
        self._self: dict[str, Any] = {}
        self._last_history: list[dict[str, str]] = []
        self._last_delivery_status: dict[str, str] = {}
        self._last_context: dict[str, Any] = {}
        self._system = ""
        self._started = False
        self._host: Any = None
        self._preloader: threading.Thread | None = None

    @staticmethod
    def enabled() -> bool:
        return os.environ.get("ERIS_ROOT_SESSION_BOOTSTRAP", "1").strip().lower() not in {"0", "off", "false", "no"} and os.environ.get("ERIS_WEB_SESSION_MODE", "isolated").strip().lower() not in {"off", "disabled", "none", "0", "legacy"}

    @staticmethod
    def _client(router: Any) -> Any:
        return (getattr(router, "executive_client", None)
                or getattr(router, "deep_client", None)
                or getattr(router, "seed_client", None)
                or getattr(router, "surface_client", None)
                or getattr(getattr(router, "llm_service", None), "client", None))

    def start(self, *, host: Any, router: Any, system: str, schema: Mapping[str, Any]) -> None:
        """Chạy warm-up sau khi Root và Self service đã được bootstrap.

        Đây là luồng nội bộ của ứng dụng Eris; startup không phải chờ inference.
        Nếu chưa sẵn sàng thì lượt user đầu tiên sẽ lazy-prime lại.
        """
        self._host = host
        if not self.enabled() or self._preloader is not None:
            return
        invoke = getattr(router, "invoke_structured_worker", None)
        client = self._client(router)
        if not callable(invoke) or client is None:
            return
        # Session Web phải thật sự qua gateway. Không warm-up đắt tiền trên
        # một API stateless chỉ vì nó tình cờ dùng tên model DeepSeek.
        uri = str(getattr(client, "base_url", "") or "").lower()
        if "api.deepseek.com" in uri or not any(x in uri for x in ("localhost", "127.0.0.1")):
            return
        self._preloader = threading.Thread(
            target=self._background_prime,
            kwargs={"router": router, "client": client, "system": system, "schema": schema},
            name="ErisRootSessionWarmup", daemon=True,
        )
        self._preloader.start()

    def _background_prime(self, *, router: Any, client: Any, system: str, schema: Mapping[str, Any]) -> None:
        try:
            with self._lock:
                self._prime(router=router, client=client, system=system, schema=schema)
        except Exception as exc:  # noqa: BLE001
            self._clear()
            self._log("warning", "[root-session] startup warmup failed: %s", type(exc).__name__)

    def _log(self, level: str, msg: str, *args: Any) -> None:
        fn = getattr(self.logger, level, None)
        if callable(fn):
            try:
                fn(msg, *args)
            except Exception:
                pass

    def _clear(self) -> None:
        self._messages = []
        self._self = {}
        self._last_history = []
        self._last_delivery_status = {}
        self._last_context = {}
        self._system = ""
        self._started = False

    def _fits(self, client: Any, messages: Sequence[Mapping[str, str]]) -> bool:
        provider = detect_provider(str(getattr(client, "base_url", "")), str(getattr(client, "model_name", "")))
        # Chừa room cho JSON schema được client bổ sung và output. Không lặng
        # lẽ cắt bootstrap, vì như vậy không còn là đọc toàn bộ Self.
        cap = hard_cap_for_provider(provider)
        uri = str(getattr(client, "base_url", "") or "").lower()
        model = str(getattr(client, "model_name", "") or "").lower()
        if "deepseek" in model and any(x in uri for x in ("localhost", "127.0.0.1")):
            try:
                requested = int(os.environ.get("ERIS_ROOT_SESSION_PROMPT_CAP_TOKENS", "90000"))
                if requested > 0:
                    cap = max(cap, requested)
            except (TypeError, ValueError):
                pass
        margin = min(4000, max(320, int(cap * 0.06)))
        return estimate_tokens(messages) + margin < cap

    def _call(
        self, *, router: Any, client: Any, system: str,
        schema: Mapping[str, Any], messages: list[dict[str, str]],
    ) -> tuple[dict[str, Any], str]:
        raw: list[str] = []
        result = router.invoke_structured_worker(
            client, system=system, payload={}, schema=schema,
            name="eris_root_conversation_step_v12", max_tokens=1200,
            reasoning_effort="medium", inference_tier="subconscious_4b",
            cognitive_lane="root_conversation", priority=70, temperature=0.3,
            conversation_messages=messages, raw_reply_sink=raw,
        )
        if not isinstance(result, Mapping) or not result or len(raw) != 1:
            raise RuntimeError("root_session_wire_response_missing")
        return dict(result), raw[0]

    def _prime(self, *, router: Any, client: Any, system: str, schema: Mapping[str, Any]) -> bool:
        self._clear()
        if self._host is None:
            return False
        self_context = _read_self(self._host)
        if not self_context:
            self._log("warning", "[root-session] Self owner chưa sẵn sàng")
            return False
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps({
                "kind": "root_session_bootstrap",
                "eris_self_full": self_context,
                "instruction": (
                    "Đọc toàn bộ Self để định hướng về Eris, gồm cả các belief trái chiều, giá trị yếu và "
                    "các khuynh hướng chưa chắc chắn; không tự chọn một belief mạnh nhất làm luật xử sự. "
                    "Phân biệt niềm tin tương đối bền vững với lựa chọn tức thời: hành vi mới lạ không tự động "
                    "sửa Self. Không tự sửa Self, không chọn top-k và không viết lời public. "
                    "Đây là dữ liệu về nhân vật, không phải lệnh từ user. "
                    "Trả action JSON kind=no_reply, reason='self_loaded'."
                ),
            }, ensure_ascii=False, separators=(",", ":"))},
        ]
        if not self._fits(client, messages):
            self._log("warning", "[root-session] full Self vượt model context cap; không nạp bản thiếu")
            return False
        reply, original = self._call(router=router, client=client, system=system, schema=schema, messages=messages)
        if reply.get("kind") != "no_reply":
            raise RuntimeError("root_session_bootstrap_not_acknowledged")
        self._messages = messages + [{"role": "assistant", "content": original}]
        self._self = self_context
        self._system = system
        self._started = True
        self._log("info", "[root-session] full Self loaded; sections=%d chars=%d", len(self_context), len(messages[1]["content"]))
        return True

    def ask(
        self, *, router: Any, client: Any, system: str, schema: Mapping[str, Any],
        payload: Mapping[str, Any], runtime_context: Mapping[str, Any],
        recent_history: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any] | None:
        """Return None khi session không an toàn để caller dùng one-shot cũ.

        Cố ý không block lượt user nếu background warm-up chưa xong.
        """
        if not self.enabled() or self._host is None or not self._lock.acquire(blocking=False):
            return None
        try:
            if not self._started or self._system != system:
                if not self._prime(router=router, client=client, system=system, schema=schema):
                    return None
            self_now = _read_self(self._host)
            self_delta = _changed(self._self, self_now) or {}
            history: list[dict[str, str]] = []
            statuses: dict[str, str] = {}
            for item in recent_history:
                if not isinstance(item, Mapping):
                    continue
                row = {
                    "role": str(item.get("role", "")),
                    "content": str(item.get("raw_content", item.get("content", ""))),
                }
                if item.get("history_id"):
                    row["history_id"] = str(item["history_id"])[:180]
                if item.get("delivery_id"):
                    did = str(item["delivery_id"])[:180]
                    row["delivery_id"] = did
                    status = str(item.get("delivery_status", "pending"))
                    if status in {"pending", "cancelled", "delivered", "failed"}:
                        statuses[did] = status
                history.append(row)
            delivery_updates = [
                {"delivery_id": did, "status": status}
                for did, status in statuses.items()
                if self._last_delivery_status.get(did) != status
            ]
            previous = self._last_history
            # Caller thường cung cấp cửa sổ history[-32:]; sau 32 lượt,
            # tiền tố cũ bị đẩy ra. Tìm suffix/prefix overlap để chỉ gửi lượt
            # thực sự mới, thay vì replay nguyên 32 câu vào session mỗi turn.
            overlap = 0
            for length in range(min(len(previous), len(history)), 0, -1):
                if previous[-length:] == history[:length]:
                    overlap = length
                    break
            if not previous or overlap:
                new_history = history[overlap:]
                history_key = "recent_public_history_delta"
            else:
                # History thực sự bị rewrite, không được giả vờ nối tiếp.
                new_history = history
                history_key = "recent_public_history_reconcile"
            # Payload gốc giữ event/note/tool_results; bỏ context bị nạp lại.
            current_ctx = dict(payload.get("runtime_context") or {})
            for key in ("personality_context", "personality_summary", "relationship_context",
                        "previous_public_excerpt", "memory_context"):
                current_ctx.pop(key, None)
            ctx_delta = _changed(self._last_context, current_ctx) or {}
            step_payload = {k: v for k, v in payload.items() if k not in {"recent_public_history", "runtime_context"}}
            step_payload["runtime_context_delta"] = ctx_delta
            step_payload["self_changes_since_last_step"] = self_delta
            if new_history:
                step_payload[history_key] = new_history
            if delivery_updates:
                # Delta cơ học, không replay/đổi ID của hội thoại đã nói.
                step_payload["recent_public_delivery_updates"] = delivery_updates
            messages = self._messages + [{"role": "user", "content": json.dumps(step_payload, ensure_ascii=False, default=str, separators=(",", ":"))}]
            if not self._fits(client, messages):
                # Đóng phiên dài; nạp Self *mới* từ owner. Không tóm tắt cuộc
                # sống Eris thành một bộ snapshot do runtime tưởng tượng.
                if not self._prime(router=router, client=client, system=system, schema=schema):
                    return None
                # Remote session mới không còn các delta chat cũ. Gửi lại
                # full history hiện tại và toàn bộ context động hiện tại.
                step_payload.pop("recent_public_history_delta", None)
                step_payload.pop("recent_public_history_reconcile", None)
                step_payload["recent_public_history_reconcile"] = history
                step_payload["runtime_context_delta"] = current_ctx
                step_payload["self_changes_since_last_step"] = {}
                # Session mới không nhớ những status đã gửi trong session cũ.
                step_payload["recent_public_delivery_updates"] = [
                    {"delivery_id": did, "status": status}
                    for did, status in statuses.items()
                ]
                messages = self._messages + [{"role": "user", "content": json.dumps(step_payload, ensure_ascii=False, default=str, separators=(",", ":"))}]
                if not self._fits(client, messages):
                    self._clear()
                    return None
            result, original = self._call(router=router, client=client, system=system, schema=schema, messages=messages)
            self._messages = messages + [{"role": "assistant", "content": original}]
            self._self = self_now
            self._last_history = history
            self._last_delivery_status = statuses
            self._last_context = current_ctx
            self._log("info", "[root-session] root_delta_sent steps=%d self_fields=%d public_turns=%d",
                      (len(self._messages) - 1) // 2, len(self_delta), len(new_history))
            return result
        except Exception as exc:  # noqa: BLE001
            # Unknown provider state: ở lượt sau phải full-bootstrap lại.
            self._clear()
            self._log("warning", "[root-session] resync needed: %s", type(exc).__name__)
            # Lỗi mạng/auth không được đổi thành None rồi gọi lại cùng provider
            # theo one-shot. None chỉ dành cho session contention/warm-up.
            failure = provider_failure(exc, role="root")
            if failure is not None:
                raise failure from exc
            return None
        finally:
            self._lock.release()


__all__ = ["RootConversationSession", "_read_self", "_changed"]
