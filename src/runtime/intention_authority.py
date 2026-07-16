# -*- coding: utf-8 -*-
"""intention_authority.py - quyền phát ngôn cho ý định có khả năng thực thi.

Eris có thể có suy nghĩ mơ hồ, nhưng câu public kiểu "tôi sẽ kiểm lại ký ức"
ngầm hứa rằng runtime có một đối tượng thật, một handler thật và một kết quả có
thể quan sát. Nếu ba thứ đó không tồn tại, câu phải được đổi thành trạng thái
trung thực hoặc giữ im. Không cần diễn cosplay agency chỉ để lấp khoảng lặng.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Mapping

try:
    from actions.capability_registry import canonicalize_action_id, live_capability_ids
    from actions.contracts import VALID_SYSTEM_ACTIONS
except Exception:  # pragma: no cover - môi trường test tối giản
    VALID_SYSTEM_ACTIONS = set()

    def canonicalize_action_id(action_id: str) -> str:
        return str(action_id or "").strip().lower()

    def live_capability_ids(*args, **kwargs) -> tuple[str, ...]:
        return ()


def _clean(value: Any, limit: int = 360) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9_:=./\\\s-]", " ", text)).strip()


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True, slots=True)
class IntentionAuthorityVerdict:
    accepted: bool
    text: str
    original_text: str
    mode: str
    operation: str
    reason: str
    target_refs: tuple[str, ...]
    handler_id: str
    result_contract: str
    missing_contract: tuple[str, ...]
    rewritten: bool = False
    body_only: bool = False

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["target_refs"] = list(self.target_refs)
        payload["missing_contract"] = list(self.missing_contract)
        return payload


class IntentionAuthorityGate:
    """Chặn lời hứa hành động không có execution contract.

    Contract tối thiểu:

    - ``target``: đang làm với cái gì;
    - ``handler``: module/tool nào thật sự thực thi;
    - ``result``: event hoặc ActionExecutionResult nào chứng minh đã chạy.

    Gate chỉ áp cho lời tự thuật hành động của Eris. Câu trạng thái, banter,
    lời từ chối hoặc speech act đang được thực hiện ngay trong chính câu nói
    không cần một tool riêng.
    """

    VERSION = "intention_authority.v1"

    _FIRST_PERSON_RE = re.compile(r"\b(?:toi|minh|em|ta|tui)\b")
    _INTENTION_RE = re.compile(
        r"\b(?:se|dang|dinh|muon|can|phai|sap|chuan bi|de toi|de minh|thu)\b"
    )
    _OPERATION_RE = re.compile(
        r"\b(?:"
        r"ra soat|ra lai|kiem|kiem tra|kiem lai|xem|xem lai|doc lai|luc|luc lai|doi chieu|"
        r"tim|tim lai|tra|tra cuu|chay|thu chay|sua|xu ly|lam|viet|ghi|luu|xoa|"
        r"mo|dong|gui|tai|cap nhat|sap xep|don|don dep|phan tich|tong hop"
        r")\b"
    )

    # Những câu này có hình thức tương lai nhưng không khoe một pipeline hành
    # động. Chặn chúng sẽ khiến Eris không hứa ngoan được, một thảm họa đạo đức.
    _SELF_LIMITING_RE = re.compile(
        r"\b(?:"
        r"khong hua se ngoan|khong can ngoan|khong ngoan|se im|khong chen|"
        r"chua can chen|khong doan|chua doan|khong phan|chua phan|"
        r"khong lam phien|o day|dung o day|giu im lang"
        r")\b"
    )
    _IMMEDIATE_SPEECH_RE = re.compile(
        r"\b(?:muon|se|de toi|de minh)\s+(?:noi|hoi|nhac|ke|thu nhan|xin loi|tra loi)\b"
    )

    _PRESSURE_ONLY_PREFIXES = (
        "silent_cycles=",
        "vital_pressure=",
        "boredom=",
        "thought=",
        "silence_pressure=",
        "source=",
        "surface_seed=",
        "low_claim_",
        "pattern_residue",
        "memory_resonance",
        "quiet continuity",
        "ambient_runtime",
    )
    _ANCHOR_RE = re.compile(
        r"\b(?:memory_id|event_id|vision_fact_id|claim_id|task_id|error_id|turn_id)\s*[:=]\s*[^\s|;]+",
        re.I,
    )
    _LEGACY_ANCHOR_RE = re.compile(
        r"\b(?:memory_activation:|runtime_event[:=]|vision_fact[:=]|dispatch:|observer:|"
        r"user_text[:=]|file[:=]|path[:=]|error[:=]|task[:=])[^\s|;]*",
        re.I,
    )

    _MEMORY_WORDS = ("ky uc", "dau vet", "manh nho", "chuyen cu", "memory", "nho lai")
    _TECH_WORDS = ("bug", "loi", "test", "repo", "code", "tts", "parser", "network", "file")
    _SCREEN_WORDS = ("man hinh", "cua so", "tab", "uia", "ocr", "vision")
    _DISCOURSE_WORDS = ("cau vua roi", "loi vua roi", "cho vua roi", "claim", "turn_id", "user_text")

    def validate(
        self,
        text: str,
        context: Mapping[str, Any] | None = None,
    ) -> IntentionAuthorityVerdict:
        original = _clean(text)
        normalized = _norm(original)
        ctx = _as_mapping(context)
        operation = self._operation(normalized)

        if not original:
            return self._accepted(original, operation=operation, mode="not_operational")
        if self._SELF_LIMITING_RE.search(normalized) or self._IMMEDIATE_SPEECH_RE.search(normalized):
            return self._accepted(original, operation=operation, mode="self_executing")
        if not operation or not self._looks_like_self_intention(normalized):
            return self._accepted(original, operation=operation, mode="not_operational")

        target_refs = self._target_refs(ctx)
        handler_id, handler_available = self._handler(ctx)
        result_contract = self._result_contract(ctx, handler_id=handler_id)

        missing: list[str] = []
        if not target_refs:
            missing.append("target")
        if not handler_id or not handler_available:
            missing.append("handler")
        if not result_contract:
            missing.append("result")

        if not missing:
            return IntentionAuthorityVerdict(
                accepted=True,
                text=original,
                original_text=original,
                mode="executable_intention",
                operation=operation,
                reason="execution_contract_complete",
                target_refs=target_refs,
                handler_id=handler_id,
                result_contract=result_contract,
                missing_contract=(),
            )

        rewritten = self._safe_rewrite(
            original=original,
            normalized=normalized,
            operation=operation,
            context=ctx,
            target_refs=target_refs,
        )
        return IntentionAuthorityVerdict(
            accepted=bool(rewritten),
            text=rewritten,
            original_text=original,
            mode="state_rewrite" if rewritten else "body_only",
            operation=operation,
            reason="rewritten_unexecutable_intention" if rewritten else "suppressed_unexecutable_intention",
            target_refs=target_refs,
            handler_id=handler_id,
            result_contract=result_contract,
            missing_contract=tuple(missing),
            rewritten=bool(rewritten),
            body_only=not bool(rewritten),
        )

    def _accepted(self, text: str, *, operation: str, mode: str) -> IntentionAuthorityVerdict:
        return IntentionAuthorityVerdict(
            accepted=True,
            text=text,
            original_text=text,
            mode=mode,
            operation=operation,
            reason="no_execution_claim",
            target_refs=(),
            handler_id="",
            result_contract="",
            missing_contract=(),
        )

    def _looks_like_self_intention(self, normalized: str) -> bool:
        if not self._FIRST_PERSON_RE.search(normalized):
            return False
        if self._INTENTION_RE.search(normalized):
            return True
        # "Tôi kiểm lại..." ở micro-presence vẫn là claim đang làm, dù model
        # quên chữ "đang". Câu chủ động với ngôi thứ nhất + operation cũng cần gate.
        return bool(re.search(r"\b(?:toi|minh|em|ta|tui)\s+", normalized))

    def _operation(self, normalized: str) -> str:
        match = self._OPERATION_RE.search(normalized)
        return str(match.group(0) if match else "")

    def _target_refs(self, ctx: Mapping[str, Any]) -> tuple[str, ...]:
        refs: list[str] = []
        for key in ("target_ref", "target_id", "intent_target", "task_id", "claim_id"):
            value = _clean(ctx.get(key))
            if value:
                refs.append(value)

        action_input = _clean(ctx.get("action_input"))
        if action_input and action_input not in {"{}", "[]", "null", "none"}:
            refs.append(f"action_input:{action_input[:120]}")

        for value in tuple(ctx.get("evidence_refs") or ctx.get("evidence") or ()):
            clean = _clean(value, 220)
            if self._is_real_anchor(clean):
                refs.append(clean)
        return tuple(dict.fromkeys(refs))[:8]

    def _is_real_anchor(self, value: str) -> bool:
        if not value:
            return False
        normalized = _norm(value)
        if any(normalized.startswith(prefix) for prefix in self._PRESSURE_ONLY_PREFIXES):
            return False
        if self._ANCHOR_RE.search(value) or self._LEGACY_ANCHOR_RE.search(value):
            return True
        # Một chuỗi evidence giàu nội dung vẫn dùng được, nhưng nhãn một từ hoặc
        # seed tự thuật của chính câu đang xét không được tự cấp giấy phép cho nó.
        return len(value) >= 18 and any(
            token in normalized
            for token in (
                "user said", "nguoi dung", "active_app", "screen", "window", "error", "failed",
                "test", "file", "memory", "episode", "conversation", "recent topic",
            )
        )

    def _handler(self, ctx: Mapping[str, Any]) -> tuple[str, bool]:
        explicit = _clean(
            ctx.get("execution_handler")
            or ctx.get("handler_id")
            or ctx.get("intent_handler")
        )
        if explicit:
            available = ctx.get("handler_available")
            return explicit, bool(True if available is None else available)

        action_result = _as_mapping(ctx.get("action_result"))
        result_action = canonicalize_action_id(_clean(action_result.get("action_name")))
        if result_action and bool(action_result.get("success") or action_result.get("dispatched") or action_result.get("observed")):
            return result_action, True

        action_id = canonicalize_action_id(_clean(ctx.get("system_action") or ctx.get("action")))
        if not action_id or action_id in {"none", "reply", "respond", "speak", "motioncommand"}:
            return "", False
        if action_id not in VALID_SYSTEM_ACTIONS:
            return action_id, bool(ctx.get("handler_available", False))
        try:
            live = set(live_capability_ids())
        except Exception:
            live = set()
        return action_id, bool(action_id in live or ctx.get("handler_available", False))

    def _result_contract(self, ctx: Mapping[str, Any], *, handler_id: str) -> str:
        explicit = _clean(
            ctx.get("observable_result")
            or ctx.get("result_event")
            or ctx.get("completion_event")
        )
        if explicit:
            return explicit
        action_result = _as_mapping(ctx.get("action_result"))
        if action_result:
            status = _clean(action_result.get("status") or action_result.get("public_mode"))
            evidence = tuple(action_result.get("evidence") or ())
            if status or evidence or action_result.get("success"):
                return status or "action_result"
        if handler_id and handler_id in VALID_SYSTEM_ACTIONS:
            # ActionExecutor luôn trả ActionExecutionResult, nên đây là result
            # contract thật chứ không phải lời hứa trang trí.
            return f"action_result:{handler_id}"
        return ""

    def _safe_rewrite(
        self,
        *,
        original: str,
        normalized: str,
        operation: str,
        context: Mapping[str, Any],
        target_refs: tuple[str, ...],
    ) -> str:
        kind = _norm(context.get("kind") or context.get("surface_kind") or context.get("intent"))
        evidence_blob = _norm(" ".join(target_refs))
        semantic_blob = f"{normalized} {evidence_blob}"

        # Không có target thật thì đừng invent một "mẩu ký ức" mới để cứu câu.
        if not target_refs:
            return ""

        if any(word in semantic_blob for word in self._DISCOURSE_WORDS):
            return "Tôi vẫn còn vướng ở câu vừa rồi, nhưng chưa đủ rõ để kết luận."
        if any(word in semantic_blob for word in self._MEMORY_WORDS):
            return "Một chuyện cũ vừa nổi lên. Chưa đủ rõ để tôi kéo nó ra nói."
        if any(word in semantic_blob for word in self._TECH_WORDS):
            return "Có một điểm kỹ thuật còn vướng. Tôi chưa bắt tay xử lý nó."
        if any(word in semantic_blob for word in self._SCREEN_WORDS):
            return "Có một tín hiệu đáng chú ý. Tôi chưa làm gì với nó."
        if kind in {"presence_maintenance", "micro_presence", "private_life_surface", "memory_resonance"}:
            return "Có gì đó còn vướng, nhưng chưa đủ rõ để tôi lôi ra nói."
        return "Có một việc còn vướng. Tôi chưa thực sự bắt tay làm."


__all__ = ["IntentionAuthorityGate", "IntentionAuthorityVerdict"]
