# src/cortex/vision_semantic_compressor.py
"""
VisionSemanticCompressor cho ERIS.

Vai trò:
- Nhận screenshot/crop + OCR hint + ObserverFrame.
- Gọi Qwen vision qua Ollama khi thật sự cần.
- Nén màn hình thành SemanticSceneNote nhỏ.
- Không trả lời user.
- Không commit memory.
- Không tự bật speech/action.

Nói ngắn: đây là mắt đọc sâu theo yêu cầu của BackgroundObserver,
không phải một cái miệng thứ hai. Nếu module vision bắt đầu nói chuyện,
thì repo đã mọc thêm một nhân vật phụ không ai mời.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional
from runtime.no_fallback_policy import no_fallback_mode_enabled

try:
    from cortex.observer_contracts import (
        ObserverFrame,
        SemanticSceneNote,
        SignalDiff,
        SignalSnapshot,
        clamp01,
        compact_text,
        coerce_activity_intent,
        normalize_ascii_fold,
    )
except Exception:  # pragma: no cover - fallback khi test rời file
    from .observer_contracts import (  # type: ignore
        ObserverFrame,
        SemanticSceneNote,
        SignalDiff,
        SignalSnapshot,
        clamp01,
        compact_text,
        coerce_activity_intent,
        normalize_ascii_fold,
    )

try:
    from llm.ollama_client import OllamaClient, OllamaResult
except Exception:  # pragma: no cover - cho phép import file khi chưa có llm package
    OllamaClient = Any  # type: ignore
    OllamaResult = Any  # type: ignore


_ERROR_MARKERS = (
    "traceback",
    "exception",
    "error",
    "failed",
    "failure",
    "assertionerror",
    "assertion failed",
    "compile failed",
    "build failed",
    "panic",
    "fatal",
    "lỗi",
    "loi",
    "không chạy",
    "khong chay",
    "test failed",
    "pytest failed",
)

_CODE_MARKERS = (
    "vscode",
    "visual studio code",
    "pycharm",
    "rider",
    "godot",
    "terminal",
    "powershell",
    "cmd.exe",
    "pytest",
    "python",
    ".py",
    ".cs",
    ".gd",
    ".ts",
    ".js",
)

_DOC_MARKERS = (
    "docs",
    "documentation",
    "readme",
    "stackoverflow",
    "stack overflow",
    "developer.mozilla",
    "learn.microsoft",
    "python.org",
    "github",
)

_COMM_MARKERS = (
    "discord",
    "messenger",
    "telegram",
    "gmail",
    "mail.google",
    "outlook",
    "zalo",
    "slack",
    "teams",
    "zoom",
)


@dataclass(slots=True)
class VisionCompressorConfig:
    """Cấu hình cho VisionSemanticCompressor.

    Mặc định tắt bằng env để Ngài kiểm observer trước rồi mới bật vision.
    Có thể bật bằng:
        ERIS_VISION_COMPRESSOR=1
        ERIS_VISION_COMPRESSOR_MODEL=<model vision trong Ollama>
    """

    enabled: bool = field(
        default_factory=lambda: os.getenv("ERIS_VISION_COMPRESSOR", "0").strip().lower()
        not in {"0", "false", "no", "off", ""}
    )
    model: str = field(
        default_factory=lambda: os.getenv("ERIS_VISION_COMPRESSOR_MODEL", "moondream").strip()
    )
    keep_alive: str | int | None = field(
        default_factory=lambda: _parse_keep_alive(os.getenv("ERIS_VISION_KEEP_ALIVE", "0"))
    )
    temperature: float = field(
        default_factory=lambda: _safe_float(os.getenv("ERIS_VISION_TEMPERATURE", "0"), 0.0)
    )

    min_salience: float = field(
        default_factory=lambda: clamp01(os.getenv("ERIS_VISION_MIN_SALIENCE", "0.70"), 0.70)
    )
    min_diff: float = field(
        default_factory=lambda: clamp01(os.getenv("ERIS_VISION_MIN_DIFF", "0.20"), 0.20)
    )
    max_ocr_chars: int = field(
        default_factory=lambda: max(240, int(_safe_float(os.getenv("ERIS_VISION_MAX_OCR_CHARS", "1600"), 1600)))
    )
    max_context_chars: int = 2400
    max_important_text: int = 8

    allow_interrupt: bool = False
    force_should_interrupt_false: bool = True
    unload_after_call: bool = field(
        default_factory=lambda: os.getenv("ERIS_VISION_UNLOAD_AFTER_CALL", "0").strip().lower()
        in {"1", "true", "yes", "on"}
    )


class VisionSemanticCompressor:
    """Nén ảnh màn hình thành SemanticSceneNote.

    Public API chính:
        should_compress(observer_frame, signal_diff)
        compress(image_data_uri=..., ocr_text=..., observer_frame=...)

    File này không tự capture screenshot. Runtime/telemetry làm chuyện đó.
    Cắt trách nhiệm ra như vậy để khỏi có thêm một con daemon tự tiện nhìn màn hình.
    """

    module_name = "vision_semantic_compressor"

    def __init__(
        self,
        config: VisionCompressorConfig | None = None,
        ollama_client: Any | None = None,
        logger: Any | None = None,
    ) -> None:
        self.config = config or VisionCompressorConfig()
        self.client = ollama_client if ollama_client is not None else self._make_default_client()
        self.logger = logger

    def should_compress(
        self,
        *,
        observer_frame: ObserverFrame | None = None,
        signal_diff: SignalDiff | None = None,
    ) -> bool:
        """Quyết định có nên gọi vision model không.

        Đây chỉ là policy cục bộ. Coordinator vẫn nên có cooldown riêng.
        """

        if not self.config.enabled:
            return False
        if observer_frame is None:
            return False

        salience = clamp01(getattr(observer_frame, "salience", 0.0))
        wants_vision = bool(getattr(observer_frame, "should_call_vision", False)) or str(
            getattr(observer_frame, "recommended_action", "") or ""
        ) == "call_vision_compressor"
        if not wants_vision and salience < self.config.min_salience:
            return False

        if signal_diff is None:
            return salience >= self.config.min_salience

        diff_score = clamp01(getattr(signal_diff, "diff_score", 0.0))
        if diff_score < self.config.min_diff and not bool(getattr(signal_diff, "ocr_changed", False)):
            return False
        return True

    def compress(
        self,
        *,
        image_data_uri: str = "",
        image_base64: str = "",
        image_path: str = "",
        ocr_text: str = "",
        observer_frame: ObserverFrame | None = None,
        signal_snapshot: SignalSnapshot | None = None,
        extra_context: str = "",
    ) -> SemanticSceneNote:
        """Gọi vision model và trả SemanticSceneNote.

        Nếu thiếu ảnh/model/Ollama, trả fallback OCR-only thay vì làm chết loop.
        """

        image = self._resolve_image_base64(
            image_data_uri=image_data_uri,
            image_base64=image_base64,
            image_path=image_path,
        )
        if not self.config.enabled:
            if no_fallback_mode_enabled():
                raise RuntimeError("no_fallback_vision:vision_compressor_disabled")
            return self._fallback_ocr_note(
                ocr_text=ocr_text,
                observer_frame=observer_frame,
                signal_snapshot=signal_snapshot,
                reason="vision_compressor_disabled",
            )
        if not self.config.model:
            if no_fallback_mode_enabled():
                raise RuntimeError("no_fallback_vision:missing_vision_model")
            return self._fallback_ocr_note(
                ocr_text=ocr_text,
                observer_frame=observer_frame,
                signal_snapshot=signal_snapshot,
                reason="missing_vision_model",
            )
        if not image:
            if no_fallback_mode_enabled():
                raise RuntimeError("no_fallback_vision:missing_image")
            return self._fallback_ocr_note(
                ocr_text=ocr_text,
                observer_frame=observer_frame,
                signal_snapshot=signal_snapshot,
                reason="missing_image",
            )
        if self.client is None or not callable(getattr(self.client, "chat_json", None)):
            if no_fallback_mode_enabled():
                raise RuntimeError("no_fallback_vision:missing_ollama_client")
            return self._fallback_ocr_note(
                ocr_text=ocr_text,
                observer_frame=observer_frame,
                signal_snapshot=signal_snapshot,
                reason="missing_ollama_client",
            )

        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": self._user_prompt(
                ocr_text=ocr_text,
                observer_frame=observer_frame,
                signal_snapshot=signal_snapshot,
                extra_context=extra_context,
            )},
        ]
        result = self.client.chat_json(
            self.config.model,
            messages,
            images=[image],
            schema=self._json_schema(),
            keep_alive=self.config.keep_alive,
            temperature=self.config.temperature,
        )

        if not getattr(result, "ok", False):
            self._log_warning("Vision compressor Ollama failed: %s", getattr(result, "error", "unknown"))
            if no_fallback_mode_enabled():
                raise RuntimeError(f"no_fallback_vision:ollama_failed:{getattr(result, 'error', 'unknown')}")
            return self._fallback_ocr_note(
                ocr_text=ocr_text,
                observer_frame=observer_frame,
                signal_snapshot=signal_snapshot,
                reason=f"ollama_failed:{getattr(result, 'error', 'unknown')}",
            )

        parsed = getattr(result, "parsed", {}) or {}
        note = self._note_from_mapping(
            parsed,
            observer_frame=observer_frame,
            signal_snapshot=signal_snapshot,
            raw_debug={
                "model": self.config.model,
                "ollama_content_preview": compact_text(str(getattr(result, "content", "") or ""), 500),
            },
        )

        if self.config.unload_after_call and callable(getattr(self.client, "unload", None)):
            try:
                self.client.unload(self.config.model)
            except Exception as exc:  # pragma: no cover - unload lỗi không nên phá runtime
                self._log_warning("Vision compressor unload failed: %s", exc)

        return note

    def compress_from_ocr_only(
        self,
        *,
        ocr_text: str = "",
        observer_frame: ObserverFrame | None = None,
        signal_snapshot: SignalSnapshot | None = None,
    ) -> SemanticSceneNote:
        """Public fallback khi runtime chưa có ảnh nhưng có OCR."""

        return self._fallback_ocr_note(
            ocr_text=ocr_text,
            observer_frame=observer_frame,
            signal_snapshot=signal_snapshot,
            reason="explicit_ocr_only",
        )

    # ------------------------------------------------------------------
    # Prompt / schema
    # ------------------------------------------------------------------

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are ERIS VisionSemanticCompressor.\n"
            "Your job is to read a screenshot/crop and compress it into a small runtime note.\n"
            "Do not answer the user.\n"
            "Do not infer hidden emotions, identity, private intent, or personality.\n"
            "Do not produce prose outside JSON.\n"
            "Prefer visible, grounded facts.\n"
            "If uncertain, lower confidence.\n"
            "Keep should_interrupt_user false unless the screenshot shows a clear urgent runtime hazard."
        )

    def _user_prompt(
        self,
        *,
        ocr_text: str,
        observer_frame: ObserverFrame | None,
        signal_snapshot: SignalSnapshot | None,
        extra_context: str,
    ) -> str:
        payload = {
            "observer": self._observer_payload(observer_frame),
            "signal": self._signal_payload(signal_snapshot),
            "ocr_hint": compact_text(ocr_text, self.config.max_ocr_chars),
            "extra_context": compact_text(extra_context, 500),
            "instructions": {
                "visible_context": "short description of what is visibly on screen",
                "important_text": "up to 8 short strings copied/paraphrased from visible text",
                "activity_intent": "debugging|designing|reading|searching|communicating|resting|fragmented|idle|unknown",
                "semantic_family": "short snake_case label, e.g. test_failure_loop, code_editing, docs_reading",
                "novelty": "0..1, how new this scene seems relative to observer diff",
                "salience": "0..1, how much runtime should care",
                "possible_error": "0..1, visible technical/runtime error likelihood",
                "should_interrupt_user": "normally false",
                "confidence": "0..1",
            },
        }
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return compact_text(text, self.config.max_context_chars)

    @staticmethod
    def _json_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "visible_context": {"type": "string"},
                "important_text": {"type": "array", "items": {"type": "string"}},
                "activity_intent": {
                    "type": "string",
                    "enum": [
                        "debugging",
                        "designing",
                        "reading",
                        "searching",
                        "communicating",
                        "resting",
                        "fragmented",
                        "idle",
                        "unknown",
                    ],
                },
                "semantic_family": {"type": "string"},
                "novelty": {"type": "number", "minimum": 0, "maximum": 1},
                "salience": {"type": "number", "minimum": 0, "maximum": 1},
                "possible_error": {"type": "number", "minimum": 0, "maximum": 1},
                "should_interrupt_user": {"type": "boolean"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": [
                "visible_context",
                "important_text",
                "activity_intent",
                "semantic_family",
                "novelty",
                "salience",
                "possible_error",
                "should_interrupt_user",
                "confidence",
            ],
        }

    # ------------------------------------------------------------------
    # Mapping / fallback
    # ------------------------------------------------------------------

    def _note_from_mapping(
        self,
        data: Mapping[str, Any],
        *,
        observer_frame: ObserverFrame | None,
        signal_snapshot: SignalSnapshot | None,
        raw_debug: Mapping[str, Any] | None = None,
    ) -> SemanticSceneNote:
        observer_error = clamp01(getattr(observer_frame, "possible_error", 0.0) if observer_frame else 0.0)
        observer_salience = clamp01(getattr(observer_frame, "salience", 0.0) if observer_frame else 0.0)
        important = self._coerce_text_list(data.get("important_text", []), limit=self.config.max_important_text)
        possible_error = max(clamp01(data.get("possible_error", 0.0)), observer_error * 0.75)
        salience = max(clamp01(data.get("salience", 0.0)), observer_salience * 0.72, possible_error * 0.78)
        novelty = max(clamp01(data.get("novelty", 0.0)), clamp01(getattr(observer_frame, "novelty", 0.0) if observer_frame else 0.0) * 0.70)
        confidence = clamp01(data.get("confidence", 0.0))
        if not important and signal_snapshot is not None:
            important = self._extract_important_lines(str(getattr(signal_snapshot, "ocr_text", "") or ""))

        should_interrupt = bool(data.get("should_interrupt_user", False))
        if self.config.force_should_interrupt_false:
            should_interrupt = False
        elif not self.config.allow_interrupt:
            should_interrupt = False

        evidence = [f"vision_model:{self.config.model}"]
        if observer_frame is not None:
            evidence.extend(str(item) for item in getattr(observer_frame, "evidence", [])[:4])
        if signal_snapshot is not None and getattr(signal_snapshot, "screen_hash", ""):
            evidence.append(f"screen_hash:{getattr(signal_snapshot, 'screen_hash')}")

        return SemanticSceneNote(
            visible_context=compact_text(str(data.get("visible_context", "") or "visible screen context"), 260),
            important_text=important,
            activity_intent=coerce_activity_intent(data.get("activity_intent", "unknown")),
            semantic_family=self._clean_family(data.get("semantic_family", "unknown")),
            novelty=novelty,
            salience=salience,
            possible_error=possible_error,
            should_interrupt_user=should_interrupt,
            confidence=confidence,
            source=self._source_label(),
            evidence=evidence[:10],
            debug={"raw": dict(raw_debug or {}), "observer_used": observer_frame is not None},
        )

    def _fallback_ocr_note(
        self,
        *,
        ocr_text: str,
        observer_frame: ObserverFrame | None,
        signal_snapshot: SignalSnapshot | None,
        reason: str,
    ) -> SemanticSceneNote:
        source_text = ocr_text or str(getattr(signal_snapshot, "ocr_text", "") if signal_snapshot else "")
        folded = normalize_ascii_fold(source_text)
        observer_focus = str(getattr(observer_frame, "focus_kind", "unknown") if observer_frame else "unknown")
        observer_intent = str(getattr(observer_frame, "activity_intent", "unknown") if observer_frame else "unknown")
        observer_salience = clamp01(getattr(observer_frame, "salience", 0.0) if observer_frame else 0.0)
        observer_novelty = clamp01(getattr(observer_frame, "novelty", 0.0) if observer_frame else 0.0)
        observer_error = clamp01(getattr(observer_frame, "possible_error", 0.0) if observer_frame else 0.0)

        text_error = 1.0 if any(marker in folded for marker in _ERROR_MARKERS) else 0.0
        possible_error = max(observer_error, 0.78 if text_error else 0.0)
        intent = observer_intent if observer_intent != "unknown" else self._infer_intent_from_text(source_text, observer_focus)
        family = self._infer_family_from_text(source_text, possible_error=possible_error, focus_kind=observer_focus)
        visible = self._fallback_visible_context(signal_snapshot, observer_focus, intent)
        important = self._extract_important_lines(source_text)

        return SemanticSceneNote(
            visible_context=visible,
            important_text=important,
            activity_intent=coerce_activity_intent(intent),
            semantic_family=family,
            novelty=max(observer_novelty * 0.72, 0.18 if source_text else 0.0),
            salience=max(observer_salience * 0.65, possible_error * 0.72, 0.20 if source_text else 0.0),
            possible_error=possible_error,
            should_interrupt_user=False,
            confidence=0.42 if source_text else 0.25,
            source="ocr_only",
            evidence=[reason, *(str(x) for x in getattr(observer_frame, "evidence", [])[:4])] if observer_frame else [reason],
            debug={"fallback_reason": reason, "text_error_marker": bool(text_error)},
        )

    def _extract_important_lines(self, text: str) -> list[str]:
        if not text:
            return []
        lines = [compact_text(line, 180) for line in re.split(r"[\r\n]+", text) if compact_text(line, 180)]
        if not lines:
            return []
        folded_lines = [(line, normalize_ascii_fold(line)) for line in lines]
        priority: list[str] = []
        for line, folded in folded_lines:
            if any(marker in folded for marker in _ERROR_MARKERS):
                priority.append(line)
        for line, folded in folded_lines:
            if any(marker in folded for marker in ("pytest", "assert", "traceback", "exception", "failed")) and line not in priority:
                priority.append(line)
        if not priority:
            priority = lines[: self.config.max_important_text]
        return list(dict.fromkeys(priority))[: self.config.max_important_text]

    def _infer_intent_from_text(self, text: str, focus_kind: str) -> str:
        folded = normalize_ascii_fold(text)
        if any(marker in folded for marker in _ERROR_MARKERS):
            return "debugging"
        if focus_kind == "code" or any(marker in folded for marker in _CODE_MARKERS):
            return "designing"
        if focus_kind == "docs" or any(marker in folded for marker in _DOC_MARKERS):
            return "reading"
        if focus_kind == "chat" or any(marker in folded for marker in _COMM_MARKERS):
            return "communicating"
        if focus_kind in {"media", "game"}:
            return "resting"
        return "unknown"

    def _infer_family_from_text(self, text: str, *, possible_error: float, focus_kind: str) -> str:
        folded = normalize_ascii_fold(text)
        if possible_error >= 0.55:
            if "pytest" in folded or "test" in folded:
                return "test_failure_loop"
            return "visible_error_signal"
        if focus_kind == "code" or any(marker in folded for marker in _CODE_MARKERS):
            return "code_workspace"
        if focus_kind == "docs" or any(marker in folded for marker in _DOC_MARKERS):
            return "docs_reference"
        if focus_kind == "chat" or any(marker in folded for marker in _COMM_MARKERS):
            return "communication_context"
        if focus_kind in {"media", "game"}:
            return "ambient_media"
        return "screen_context"

    @staticmethod
    def _fallback_visible_context(
        signal_snapshot: SignalSnapshot | None,
        focus_kind: str,
        intent: str,
    ) -> str:
        # No signal and no app/window means there is no real screen content to
        # describe. Returning a placeholder like "screen context inferred from
        # OCR; focus=unknown; intent=unknown" only manufactures a content-free
        # "fact" that later leaks as screen evidence. Prefer an empty context so
        # downstream fact extraction simply skips it.
        if signal_snapshot is None:
            return ""
        app = compact_text(str(getattr(signal_snapshot, "active_app", "") or ""), 80)
        win = compact_text(str(getattr(signal_snapshot, "active_window_title", "") or ""), 120)
        if app or win:
            return compact_text(f"{app or 'active app'} | {win or 'active window'} | focus={focus_kind}; intent={intent}", 260)
        return ""

    # ------------------------------------------------------------------
    # Payload helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _observer_payload(observer_frame: ObserverFrame | None) -> dict[str, Any]:
        if observer_frame is None:
            return {}
        return {
            "focus_kind": getattr(observer_frame, "focus_kind", "unknown"),
            "activity_intent": getattr(observer_frame, "activity_intent", "unknown"),
            "salience": round(clamp01(getattr(observer_frame, "salience", 0.0)), 3),
            "novelty": round(clamp01(getattr(observer_frame, "novelty", 0.0)), 3),
            "repetition": round(clamp01(getattr(observer_frame, "repetition", 0.0)), 3),
            "possible_error": round(clamp01(getattr(observer_frame, "possible_error", 0.0)), 3),
            "recommended_action": getattr(observer_frame, "recommended_action", "observe_only"),
            "confidence": round(clamp01(getattr(observer_frame, "confidence", 0.0)), 3),
        }

    @staticmethod
    def _signal_payload(signal_snapshot: SignalSnapshot | None) -> dict[str, Any]:
        if signal_snapshot is None:
            return {}
        return {
            "active_app": compact_text(str(getattr(signal_snapshot, "active_app", "") or ""), 90),
            "active_window": compact_text(str(getattr(signal_snapshot, "active_window_title", "") or ""), 140),
            "focus_hint": getattr(signal_snapshot, "focus_kind_hint", "unknown"),
            "idle_seconds": round(float(getattr(signal_snapshot, "idle_seconds", 0.0) or 0.0), 1),
            "recent_events": [compact_text(str(x), 90) for x in list(getattr(signal_snapshot, "recent_events", []) or [])[-6:]],
            "screen_hash": getattr(signal_snapshot, "screen_hash", ""),
            "ocr_hash": getattr(signal_snapshot, "ocr_hash", ""),
        }

    def _resolve_image_base64(
        self,
        *,
        image_data_uri: str,
        image_base64: str,
        image_path: str,
    ) -> str:
        if image_base64:
            return self._strip_data_uri(image_base64)
        if image_data_uri:
            return self._strip_data_uri(image_data_uri)
        if image_path:
            path = Path(image_path)
            if path.exists() and path.is_file():
                if self.client is not None and callable(getattr(self.client, "encode_image_file", None)):
                    return self.client.encode_image_file(str(path))
                import base64

                return base64.b64encode(path.read_bytes()).decode("utf-8")
        return ""

    @staticmethod
    def _strip_data_uri(value: str) -> str:
        text = str(value or "").strip()
        if text.startswith("data:") and "," in text:
            return text.split(",", 1)[1].strip()
        return text

    @staticmethod
    def _coerce_text_list(value: Any, *, limit: int) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = [value]
        elif isinstance(value, (list, tuple, set)):
            raw_items = list(value)
        else:
            raw_items = [value]
        out: list[str] = []
        for item in raw_items:
            text = compact_text(str(item or ""), 180)
            if text and text not in out:
                out.append(text)
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _clean_family(value: Any) -> str:
        text = str(value or "unknown").strip().lower()
        text = re.sub(r"[^a-z0-9_\-]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")
        return compact_text(text or "unknown", 80)

    def _source_label(self) -> str:
        """Trả source label từ model name, dùng cho SemanticSceneNote.source."""
        model = str(self.config.model or "").strip().lower().split(":")[0]
        return model or "vision_model"

    @staticmethod
    def _make_default_client() -> Any | None:
        try:
            from llm.local_llama_engine import build_local_or_ollama_client
            return build_local_or_ollama_client()
        except Exception:
            pass
        if OllamaClient is Any:  # type: ignore[comparison-overlap]
            return None
        try:
            return OllamaClient()
        except Exception:
            return None

    def _log_warning(self, msg: str, *args: Any) -> None:
        if self.logger is not None and callable(getattr(self.logger, "warning", None)):
            try:
                self.logger.warning(msg, *args)
            except Exception:
                pass


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _parse_keep_alive(value: str) -> str | int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.lower() in {"none", "null"}:
        return None
    if raw == "0":
        return 0
    return raw
