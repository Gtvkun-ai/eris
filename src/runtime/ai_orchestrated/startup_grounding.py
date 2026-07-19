# -*- coding: utf-8 -*-
"""Grounding cho câu mở đầu của Architecture C.

Startup cũ chạy trước Screen Text worker nên Main AI chỉ nhận một event ``startup``
rỗng. Kết quả dễ rơi vào hai cực đều dở: câu chào onboarding nhạt, hoặc dựng một
premise không tồn tại như thể user đang định "thay đổi" thứ gì đó.

Module này làm ba việc, và cố ý chỉ ba việc:

1. Khởi động UIA/OCR sớm rồi chờ ngắn cho snapshot đầu tiên.
2. Đóng gói text thật đang thấy thành evidence có provenance.
3. Cho planner/Main AI quyền tạo một *giả thuyết xã hội rủi ro thấp* từ evidence,
   nhưng không được biến giả thuyết ấy thành fact hay memory.

Runtime vẫn là type-checker của sự thật. Model mới là bên chọn câu nói. Con người
đã thử để regex viết lời chào thay mình đủ lâu rồi.
"""

from __future__ import annotations

import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .contracts import IntentionPlan


def _norm(text: str) -> str:
    value = unicodedata.normalize("NFD", str(text or "").lower()).replace("đ", "d")
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9_#+.\-]+", " ", value).strip()


def _compact(text: Any, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _env_float(name: str, default: float, *, low: float, high: float) -> float:
    try:
        value = float(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _is_generic_window(title: str) -> bool:
    normalized = _norm(title)
    return normalized in {"", "desktop", "program manager", "khong xac dinh", "unknown"}


def _looks_like_telemetry_surface(text: str) -> bool:
    normalized = _norm(text)
    markers = (
        "telemetry",
        "observability",
        "runtime panel",
        "debug panel",
        "metrics",
        "performance monitor",
        "monitoring",
    )
    return any(marker in normalized for marker in markers)


def _screen_block_payload(block: Any) -> dict[str, Any]:
    return {
        "id": str(getattr(block, "block_id", "") or ""),
        "source": str(getattr(block, "source", "") or "screen_text"),
        "text": _compact(getattr(block, "text", ""), 360),
        "confidence": round(max(0.0, min(1.0, float(getattr(block, "confidence", 0.0) or 0.0))), 3),
        "window_title": _compact(getattr(block, "window_title", ""), 180),
        "captured_at": float(getattr(block, "captured_at", 0.0) or 0.0),
    }


def _startup_block_score(payload: Mapping[str, Any], *, now: float) -> float:
    """Ưu tiên nội dung có nghĩa, không ưu tiên nút Minimize chỉ vì nó đứng đầu UI tree."""

    text = str(payload.get("text", "") or "")
    normalized = _norm(text)
    confidence = float(payload.get("confidence", 0.0) or 0.0)
    captured_at = float(payload.get("captured_at", 0.0) or 0.0)
    freshness = max(0.0, 1.0 - max(0.0, now - captured_at) / 12.0)
    score = 0.58 * confidence + 0.18 * freshness

    if _looks_like_telemetry_surface(text):
        score += 0.34
    if any(
        marker in normalized
        for marker in (
            "status", "queue", "latency", "tts", "observer", "model", "warning",
            "error", "cooldown", "token", "runtime", "memory", "grounding", "429",
            "ms", "percent", "cpu", "ram", "active", "enabled", "disabled",
        )
    ):
        score += 0.28
    if any(ch.isdigit() for ch in text):
        score += 0.08
    if normalized in {
        "telemetry", "settings", "close", "minimize", "maximize", "restore",
        "menu", "file", "edit", "view", "help",
    }:
        score -= 0.30
    return score


@dataclass(frozen=True, slots=True)
class StartupGroundingBundle:
    active_window: str = ""
    focus_summary: str = ""
    backend: str = ""
    screen_revision: int = 0
    privacy_blocked: bool = False
    evidence: tuple[Mapping[str, Any], ...] = ()
    telemetry_surface_visible: bool = False
    waited_seconds: float = 0.0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        refs: list[str] = []
        for item in self.evidence[:5]:
            block_id = str(item.get("id", "") or "").strip()
            if block_id:
                refs.append(f"screen:{block_id}")
        if not refs and self.active_window and not _is_generic_window(self.active_window):
            refs.append("screen:active_window_title")
        return tuple(refs)

    @property
    def strongest_confidence(self) -> float:
        values = [float(item.get("confidence", 0.0) or 0.0) for item in self.evidence]
        if values:
            return max(values)
        return 0.68 if self.active_window and not _is_generic_window(self.active_window) else 0.0

    @property
    def has_direct_screen_evidence(self) -> bool:
        return bool(
            not self.privacy_blocked
            and (
                any(str(item.get("text", "") or "").strip() for item in self.evidence)
                or (self.active_window and not _is_generic_window(self.active_window))
            )
        )

    @property
    def has_strong_opening_anchor(self) -> bool:
        if not self.has_direct_screen_evidence:
            return False
        if self.telemetry_surface_visible:
            return bool(self.evidence) and self.strongest_confidence >= 0.62
        return self.strongest_confidence >= 0.72 and bool(self.evidence)

    def planner_context(self) -> dict[str, Any]:
        return {
            "direct_screen_evidence": self.has_direct_screen_evidence,
            "strong_opening_anchor": self.has_strong_opening_anchor,
            "active_window": self.active_window,
            "focus_summary": self.focus_summary,
            "screen_backend": self.backend,
            "screen_revision": self.screen_revision,
            "privacy_blocked": self.privacy_blocked,
            "telemetry_surface_visible": self.telemetry_surface_visible,
            "visible_text": [dict(item) for item in self.evidence[:12]],
            "evidence_refs": list(self.evidence_refs),
            "epistemic_policy": {
                "observed_screen_fact": "may_state_directly_with_evidence_ref",
                "user_state_or_intent": "low_risk_hypothesis_only; hedge_and_invite_correction",
                "technical_execution": "direct_runtime_result_required",
                "memory_commit": "forbidden_for_unconfirmed_hypothesis",
            },
            "opening_policy": (
                "Use one concrete visible detail as the conversational anchor. "
                "A restrained inference or curious question is allowed when its basis is explicit. "
                "Never invent that the user is starting, changing, fixing, or feeling something."
            ),
        }

    def prompt_context(self) -> str:
        if not self.has_direct_screen_evidence:
            return (
                "startup_grounding: no current direct screen evidence. "
                "Do not fabricate user activity, intent, mood, a planned change, or a task. "
                "Prefer silence over a generic availability/onboarding line."
            )

        lines = [
            "startup_grounding: direct current-screen evidence is available.",
            f"active_window: {self.active_window or '<unknown>'}",
            f"focus_summary: {self.focus_summary or '<unknown>'}",
            f"screen_backend: {self.backend or 'unknown'}; telemetry_surface_visible={str(self.telemetry_surface_visible).lower()}",
            "visible_screen_evidence:",
        ]
        for item in self.evidence[:12]:
            lines.append(
                "- [{id}|{source}|confidence={confidence}] {text}".format(
                    id=item.get("id", "screen"),
                    source=item.get("source", "screen_text"),
                    confidence=item.get("confidence", 0.0),
                    text=item.get("text", ""),
                )
            )
        lines.extend(
            (
                "epistemic_contract:",
                "- You may directly mention a concrete visible item above.",
                "- You may infer a low-risk mood/intent only as a hypothesis: state the basis, hedge it, and leave room for correction.",
                "- Do not infer that the user plans to start/change/fix something merely from words such as startup, mode, runtime, or telemetry.",
                "- Do not claim a tool action, successful read, file edit, or runtime result unless a direct result is present.",
                "- For a visible Telemetry panel, prefer one real status/metric/label/change on the panel over saying only that Telemetry is open.",
                "- The opening must feel like ERIS noticed something, not like onboarding copy. Avoid 'Tôi ở đây', 'bắt đầu thôi', or generic service offers.",
            )
        )
        return "\n".join(lines)


def collect_startup_grounding(host: Any, *, timeout_seconds: float | None = None) -> StartupGroundingBundle:
    """Prime UIA/OCR và thu evidence hiện tại mà không gọi VLM.

    Timeout ngắn và có giới hạn cứng. UIA thường publish ngay ở vòng đầu; nếu
    Windows/OCR đang bận thì startup vẫn tiếp tục thay vì biến câu chào thành một
    nghi lễ chờ đợi đầy tính hành chính.
    """

    timeout = (
        _env_float("ERIS_STARTUP_SCREEN_PRIME_SEC", 1.4, low=0.0, high=3.0)
        if timeout_seconds is None
        else max(0.0, min(3.0, float(timeout_seconds)))
    )
    started_at = time.time()
    notes: list[str] = []

    worker = getattr(host, "screen_text_worker", None)
    store = getattr(host, "screen_evidence_store", None)
    if worker is not None:
        try:
            worker.start()
        except Exception as exc:  # pragma: no cover - phụ thuộc Windows/runtime thật
            notes.append(f"screen_worker_start_failed:{type(exc).__name__}")

    screen_snapshot = None
    if store is not None:
        deadline = started_at + timeout
        while True:
            try:
                screen_snapshot = store.snapshot()
            except Exception as exc:  # pragma: no cover
                notes.append(f"screen_store_failed:{type(exc).__name__}")
                break
            if int(getattr(screen_snapshot, "revision", 0) or 0) > 0:
                break
            if time.time() >= deadline:
                notes.append("screen_prime_timeout")
                break
            # Nếu user đã bắt đầu nói, ưu tiên chat hơn một câu chào. Khá hiển nhiên,
            # nhưng runtime cũ từng mất hơn một phút đọc báo lúc user đang chat.
            if bool(getattr(host, "chat_mode", False)) or bool(getattr(host, "_chat_processing", False)):
                notes.append("screen_prime_preempted_by_chat")
                break
            time.sleep(0.04)

    telemetry_snapshot = None
    service = getattr(host, "telemetry_service", None)
    if service is not None:
        try:
            telemetry_snapshot = service.capture_snapshot(
                mood_score=getattr(host, "mood_score", 0),
                inferred_pos_x=getattr(host, "inferred_pos_x", 0.5),
            )
        except Exception as exc:  # pragma: no cover
            notes.append(f"telemetry_capture_failed:{type(exc).__name__}")

    active_window = ""
    focus_summary = ""
    backend = ""
    revision = 0
    privacy_blocked = False
    raw_blocks: Sequence[Any] = ()

    if screen_snapshot is not None:
        window = getattr(screen_snapshot, "window", None)
        active_window = _compact(getattr(window, "title", ""), 220)
        backend = _compact(getattr(screen_snapshot, "backend", ""), 40)
        revision = max(0, int(getattr(screen_snapshot, "revision", 0) or 0))
        privacy_blocked = bool(getattr(screen_snapshot, "privacy_blocked", False))
        raw_blocks = tuple(getattr(screen_snapshot, "blocks", ()) or ())

    if telemetry_snapshot is not None:
        telemetry_window = _compact(
            getattr(telemetry_snapshot, "active_window", "")
            or getattr(telemetry_snapshot, "active_app", ""),
            220,
        )
        if not active_window or (_is_generic_window(active_window) and not _is_generic_window(telemetry_window)):
            active_window = telemetry_window
        focus_summary = _compact(getattr(telemetry_snapshot, "focus_summary", ""), 280)

    now = time.time()
    candidates: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for block in raw_blocks:
        captured_at = float(getattr(block, "captured_at", 0.0) or 0.0)
        age = max(0.0, now - captured_at)
        if age > 12.0:
            continue
        text = _compact(getattr(block, "text", ""), 360)
        if len(text) < 2:
            continue
        key = _norm(text)
        if not key or key in seen:
            continue
        seen.add(key)
        candidates.append(_screen_block_payload(block))
        if len(candidates) >= 120:
            break

    # TelemetrySnapshot đã gom accessibility/DOM/OCR cache có freshness riêng.
    # Dùng nó làm fallback/supplement khi worker foreground chưa publish đủ text.
    content_meta = getattr(telemetry_snapshot, "content_metadata", {}) if telemetry_snapshot is not None else {}
    if isinstance(content_meta, Mapping):
        privacy = _norm(content_meta.get("privacy_level", "normal"))
        try:
            meta_confidence = max(0.0, min(1.0, float(content_meta.get("confidence", 0.0) or 0.0)))
        except (TypeError, ValueError):
            meta_confidence = 0.0
        if privacy not in {"private", "sensitive"} and meta_confidence >= 0.42:
            source = str(content_meta.get("source", "content_metadata") or "content_metadata")
            for field_name in ("visible_text_sample", "caption_sample", "title"):
                text = _compact(content_meta.get(field_name, ""), 520)
                key = _norm(text)
                if len(text) < 2 or not key or key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    {
                        "id": f"content:{source}:{field_name}",
                        "source": source,
                        "text": text,
                        "confidence": round(meta_confidence, 3),
                        "window_title": active_window,
                        "captured_at": now,
                    }
                )

    candidates.sort(key=lambda item: _startup_block_score(item, now=now), reverse=True)
    evidence = candidates[:18]

    evidence_blob = " ".join(
        [active_window, focus_summary, *(str(item.get("text", "")) for item in evidence)]
    )
    telemetry_visible = _looks_like_telemetry_surface(evidence_blob)

    return StartupGroundingBundle(
        active_window=active_window,
        focus_summary=focus_summary,
        backend=backend,
        screen_revision=revision,
        privacy_blocked=privacy_blocked,
        evidence=tuple(evidence),
        telemetry_surface_visible=telemetry_visible,
        waited_seconds=max(0.0, time.time() - started_at),
        notes=tuple(notes),
    )


def ensure_grounded_startup_plan(
    plan: IntentionPlan,
    bundle: StartupGroundingBundle,
    *,
    force_screen_opening: bool = True,
) -> IntentionPlan:
    """Gắn provenance vào plan và cứu planner khỏi lời chào chung chung.

    Khi có Telemetry/UIA evidence đủ mạnh, user đã cấu hình startup greeting và
    planner lại chọn im vì snapshot cũ thiếu environment, ta tạo *intention* có
    căn cứ. Main model vẫn toàn quyền viết câu public.
    """

    data = plan.to_dict()
    refs = tuple(dict.fromkeys((*tuple(plan.evidence_refs), *bundle.evidence_refs)))[:5]

    if bundle.has_strong_opening_anchor and force_screen_opening:
        if not plan.speak or plan.confidence < 0.56 or plan.importance < 0.42:
            data.update(
                {
                    "speak": True,
                    "motive": "startup_opening",
                    "strategy": "grounded_environment_opening",
                    "value_focus": "curiosity",
                    "importance": max(0.62, float(plan.importance or 0.0)),
                    "intrusion_risk": min(0.22, float(plan.intrusion_risk or 0.16)),
                    "confidence": max(0.78, float(plan.confidence or 0.0)),
                    "performance_hint": plan.performance_hint or "curious",
                    "notes": "strong current-screen anchor; startup opener is grounded",
                }
            )
        data["topic"] = (
            "Use one concrete item from startup_screen_evidence. For Telemetry, react to one real "
            "status/metric/label/change. A low-pressure question or hedged inference is allowed. "
            "Do not invent user intent, plans, changes, fixes, or feelings."
        )
        data["evidence_refs"] = list(refs)
    elif plan.speak:
        data["evidence_refs"] = list(refs)
        if not bundle.has_direct_screen_evidence and not plan.evidence_refs:
            data["notes"] = (
                f"{plan.notes}; no direct startup anchor: avoid generic onboarding and unsupported user claims"
            ).strip("; ")

    return IntentionPlan.from_mapping(data, channel=plan.channel)


__all__ = [
    "StartupGroundingBundle",
    "collect_startup_grounding",
    "ensure_grounded_startup_plan",
]
