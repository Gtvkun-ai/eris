# src/cortex/vision_semantic_compressor.py
"""
VisionSemanticCompressor cho ERIS.

Vai trÃ²:
- Nháº­n screenshot/crop + OCR hint + ObserverFrame.
- Gá»i Qwen vision qua Ollama khi tháº­t sá»± cáº§n.
- NÃ©n mÃ n hÃ¬nh thÃ nh SemanticSceneNote nhá».
- KhÃ´ng tráº£ lá»i user.
- KhÃ´ng commit memory.
- KhÃ´ng tá»± báº­t speech/action.

NÃ³i ngáº¯n: Ä‘Ã¢y lÃ  máº¯t Ä‘á»c sÃ¢u theo yÃªu cáº§u cá»§a BackgroundObserver,
khÃ´ng pháº£i má»™t cÃ¡i miá»‡ng thá»© hai. Náº¿u module vision báº¯t Ä‘áº§u nÃ³i chuyá»‡n,
thÃ¬ repo Ä‘Ã£ má»c thÃªm má»™t nhÃ¢n váº­t phá»¥ khÃ´ng ai má»i.
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
        stable_hash,
    )
except Exception:  # pragma: no cover - fallback khi test rá»i file
    from .observer_contracts import (  # type: ignore
        ObserverFrame,
        SemanticSceneNote,
        SignalDiff,
        SignalSnapshot,
        clamp01,
        compact_text,
        coerce_activity_intent,
        normalize_ascii_fold,
        stable_hash,
    )

try:
    from llm.ollama_client import OllamaClient, OllamaResult
except Exception:  # pragma: no cover - cho phÃ©p import file khi chÆ°a cÃ³ llm package
    OllamaClient = Any  # type: ignore
    OllamaResult = Any  # type: ignore


class RemoteStructureClient:
    """Adapter: bá»c má»™t remote chat client (cÃ³ ``create_chat_completion``) Ä‘á»ƒ lá»™
    interface ``chat_json`` mÃ  VisionSemanticCompressor cáº§n cho Táº¦NG cáº¥u trÃºc-hoÃ¡.

    Má»¥c Ä‘Ã­ch: trÃªn mÃ¡y Ã­t VRAM, moondream caption cháº¡y local cÃ²n viá»‡c Ã©p JSON Ä‘áº©y
    sang remote (vd Gemma qua Gemini API) â€” khá»i náº¡p/swap text model local má»—i lÆ°á»£t.

    Gemma KHÃ”NG nháº­n responseSchema nÃªn ta váº«n gá»­i response_format=json_object vÃ 
    tá»± salvage JSON tá»« text tráº£ vá». Má»i lá»—i â‡’ tráº£ OllamaResult(ok=False) Ä‘á»ƒ compressor
    degrade vá» fallback (giá»¯ caption), khÃ´ng bao giá» raise ra hot path.
    """

    def __init__(self, client: Any, *, max_tokens: int = 512, logger: Any | None = None) -> None:
        self._client = client
        self._max_tokens = max_tokens
        self._logger = logger

    @staticmethod
    def _extract_text(response: Any) -> str:
        try:
            from llm.dds import extract_text
            return str(extract_text(response) or "")
        except Exception:
            pass
        # Fallback tá»‘i thiá»ƒu: OpenAI-shape.
        if isinstance(response, dict):
            choices = response.get("choices")
            if isinstance(choices, list) and choices:
                msg = choices[0].get("message") if isinstance(choices[0], dict) else None
                if isinstance(msg, dict):
                    return str(msg.get("content") or "")
        return str(response or "")

    @staticmethod
    def _parse_json_object(text: str) -> dict | None:
        try:
            if OllamaClient is not Any and callable(getattr(OllamaClient, "_parse_json_object", None)):
                return OllamaClient._parse_json_object(text)  # type: ignore[attr-defined]
        except Exception:
            pass
        import json as _json

        raw = str(text or "").strip()
        if not raw:
            return None
        try:
            obj = _json.loads(raw)
            return obj if isinstance(obj, dict) else None
        except Exception:
            start, end = raw.find("{"), raw.rfind("}")
            if 0 <= start < end:
                try:
                    obj = _json.loads(raw[start : end + 1])
                    return obj if isinstance(obj, dict) else None
                except Exception:
                    return None
        return None

    def chat_json(
        self,
        model: str,  # bá»‹ bá» qua: remote client dÃ¹ng model_name cá»§a chÃ­nh nÃ³
        messages: list[dict],
        *,
        schema: dict | None = None,
        keep_alive: Any | None = None,  # khÃ´ng Ã¡p dá»¥ng cho remote
        temperature: float = 0.0,
        **_: Any,
    ) -> Any:
        response_format: dict[str, Any] = {"type": "json_object"}
        if isinstance(schema, dict) and schema:
            response_format["schema"] = schema
        try:
            response = self._client.create_chat_completion(
                messages=messages,
                temperature=float(temperature),
                frequency_penalty=0.0,
                presence_penalty=0.0,
                max_tokens=self._max_tokens,
                response_format=response_format,
            )
        except Exception as exc:  # pragma: no cover - lá»—i máº¡ng/remote
            return OllamaResult(ok=False, error=f"{type(exc).__name__}:{exc}")

        content = self._extract_text(response)
        parsed = self._parse_json_object(content)
        if parsed is None:
            return OllamaResult(ok=False, content=content, error="json_parse_failed")
        return OllamaResult(ok=True, parsed=parsed, content=content)


class RemoteCaptionClient:
    """Adapter: bá»c client OpenAI-compatible remote (vd shopaikey grok-3-image) Ä‘á»ƒ
    lá»™ ``caption_image(image, ...)`` tráº£ caption text â€” thay cho moondream local.

    Gá»­i áº£nh theo Ä‘á»‹nh dáº¡ng OpenAI multimodal (image_url data URI). Má»i lá»—i â‡’ tráº£ ""
    Ä‘á»ƒ compressor degrade (structuring váº«n cháº¡y tá»« OCR), khÃ´ng raise ra hot path.
    """

    def __init__(self, client: Any, *, max_tokens: int = 320, logger: Any | None = None) -> None:
        self._client = client
        self._max_tokens = max_tokens
        self._logger = logger
        self.model_name = str(getattr(client, "model_name", "") or "vision_api")
        # Thu nhá» áº£nh trÆ°á»›c khi gá»­i API: full-screen PNG base64 ráº¥t to â†’ upload + suy
        # luáº­n cháº­m. Háº¡ vá» JPEG â‰¤ max_width giÃºp cáº¯t Ä‘á»™ trá»…. 0 = táº¯t downscale.
        try:
            self._max_width = int(os.getenv("ERIS_VISION_API_MAX_WIDTH", "1280") or 1280)
        except (TypeError, ValueError):
            self._max_width = 1280

    def _maybe_downscale(self, data_uri: str) -> str:
        if self._max_width <= 0 or not data_uri.startswith("data:"):
            return data_uri
        try:
            import base64
            import io

            from PIL import Image
        except Exception:
            return data_uri
        try:
            b64 = data_uri.split(",", 1)[1]
            raw = base64.b64decode(b64)
            im = Image.open(io.BytesIO(raw))
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            w, h = im.size
            if w > self._max_width:
                im = im.resize((self._max_width, max(1, int(h * self._max_width / w))), Image.LANCZOS)
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=75)
            return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")
        except Exception:
            return data_uri

    @staticmethod
    def _to_data_uri(image: str) -> str:
        s = str(image or "").strip()
        if not s:
            return ""
        if s.startswith("data:"):
            return s
        return f"data:image/png;base64,{s}"

    @staticmethod
    def _extract_text(response: Any) -> str:
        try:
            from llm.dds import extract_text
            return str(extract_text(response) or "")
        except Exception:
            pass
        if isinstance(response, dict):
            choices = response.get("choices")
            if isinstance(choices, list) and choices:
                msg = choices[0].get("message") if isinstance(choices[0], dict) else None
                if isinstance(msg, dict):
                    return str(msg.get("content") or "")
        return str(response or "")

    def caption_image(
        self,
        image: str,
        *,
        prompt: str = "Describe what is visible on this screen in concrete detail.",
        temperature: float = 0.2,
        max_tokens: int | None = None,
        keep_alive: Any | None = None,  # khÃ´ng Ã¡p dá»¥ng cho remote
    ) -> str:
        data_uri = self._maybe_downscale(self._to_data_uri(image))
        if not data_uri:
            return ""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ]
        try:
            response = self._client.create_chat_completion(
                messages=messages,
                temperature=float(temperature),
                frequency_penalty=0.0,
                presence_penalty=0.0,
                max_tokens=int(max_tokens or self._max_tokens),
            )
        except Exception as exc:  # pragma: no cover - lá»—i máº¡ng/remote
            if self._logger is not None and callable(getattr(self._logger, "warning", None)):
                try:
                    self._logger.warning("[vision caption remote] lá»—i: %s", exc)
                except Exception:
                    pass
            return ""
        return self._extract_text(response).strip()


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
    "lá»—i",
    "loi",
    "khÃ´ng cháº¡y",
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
    """Cáº¥u hÃ¬nh cho VisionSemanticCompressor.

    Máº·c Ä‘á»‹nh táº¯t báº±ng env Ä‘á»ƒ báº¡n kiá»ƒm observer trÆ°á»›c rá»“i má»›i báº­t vision.
    CÃ³ thá»ƒ báº­t báº±ng:
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
    structure_model: str = field(
        default_factory=lambda: os.getenv("ERIS_VISION_STRUCTURE_MODEL", "").strip()
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
    """NÃ©n áº£nh mÃ n hÃ¬nh thÃ nh SemanticSceneNote.

    Public API chÃ­nh:
        should_compress(observer_frame, signal_diff)
        compress(image_data_uri=..., ocr_text=..., observer_frame=...)

    File nÃ y khÃ´ng tá»± capture screenshot. Runtime/telemetry lÃ m chuyá»‡n Ä‘Ã³.
    Cáº¯t trÃ¡ch nhiá»‡m ra nhÆ° váº­y Ä‘á»ƒ khá»i cÃ³ thÃªm má»™t con daemon tá»± tiá»‡n nhÃ¬n mÃ n hÃ¬nh.
    """

    module_name = "vision_semantic_compressor"

    def __init__(
        self,
        config: VisionCompressorConfig | None = None,
        ollama_client: Any | None = None,
        logger: Any | None = None,
        structure_client: Any | None = None,
        caption_client: Any | None = None,
    ) -> None:
        self.config = config or VisionCompressorConfig()
        self.client = ollama_client if ollama_client is not None else self._make_default_client()
        # Client riÃªng cho Táº¦NG cáº¥u trÃºc-hoÃ¡ (caption â†’ JSON). Khi mÃ¡y Ã­t VRAM, ta
        # Ä‘á»ƒ moondream caption local nhÆ°ng Ä‘áº©y structuring sang remote (Gemma) Ä‘á»ƒ
        # khá»i náº¡p/swap text model local má»—i lÆ°á»£t. None â‡’ dÃ¹ng luÃ´n self.client.
        self.structure_client = structure_client
        # Client riÃªng cho Táº¦NG caption (áº£nh â†’ mÃ´ táº£). Khi set (vd shopaikey
        # grok-3-image), caption cháº¡y REMOTE thay cho moondream local. None â‡’ self.client.
        self.caption_client = caption_client
        self.logger = logger
        # Scene continuity: nhá»› scene trÆ°á»›c Ä‘á»ƒ delta/relation cÃ³ chá»— bÃ¡m. "Thay Ä‘á»•i"
        # chá»‰ pháº£n á»©ng Ä‘Æ°á»£c náº¿u cÃ³ cÃ¡i trÆ°á»›c Ä‘á»ƒ so.
        self._last_scene: dict[str, str] = {}

    def should_compress(
        self,
        *,
        observer_frame: ObserverFrame | None = None,
        signal_diff: SignalDiff | None = None,
    ) -> bool:
        """Quyáº¿t Ä‘á»‹nh cÃ³ nÃªn gá»i vision model khÃ´ng.

        ÄÃ¢y chá»‰ lÃ  policy cá»¥c bá»™. Coordinator váº«n nÃªn cÃ³ cooldown riÃªng.
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
        """Gá»i vision model vÃ  tráº£ SemanticSceneNote.

        Náº¿u thiáº¿u áº£nh/model/Ollama, tráº£ fallback OCR-only thay vÃ¬ lÃ m cháº¿t loop.
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

        # Hai táº§ng tÃ¡ch vai: caption_client (vd grok-3-image) chá»‰ Táº¢ báº±ng prompt Ä‘Æ¡n
        # giáº£n (nÃ³ lÃ m tá»‘t), structure_client (vd glm-4.5-flash) lo NÃ‰N captionâ†’JSON.
        # KHÃ”NG single-shot: nhá»“i schema vÃ o VLM vision khiáº¿n nÃ³ váº¹t láº¡i input.
        caption_client = self.caption_client or self.client
        caption_backend = "remote" if self.caption_client is not None else "local"
        if not callable(getattr(caption_client, "caption_image", None)):
            return self._compress_single_shot(
                image=image,
                ocr_text=ocr_text,
                observer_frame=observer_frame,
                signal_snapshot=signal_snapshot,
                extra_context=extra_context,
            )

        # â”€â”€ Táº§ng 1: caption Tá»° DO báº±ng vision model (moondream/local hoáº·c remote) â”€â”€
        caption = ""
        caption_error = ""
        try:
            caption = caption_client.caption_image(
                image,
                prompt=self._caption_prompt(),
                temperature=max(self.config.temperature, 0.1),
                keep_alive=self.config.keep_alive if self.config.unload_after_call else None,
            )
        except Exception as exc:  # caption lá»—i â†’ váº«n cáº¥u trÃºc hoÃ¡ tá»« OCR
            caption_error = f"{type(exc).__name__}:{exc}"
            self._log_warning("Vision caption stage failed: %s", caption_error)

        # â”€â”€ Táº§ng 2: text model cáº¥u trÃºc caption + OCR thÃ nh SemanticSceneNote â”€â”€
        # CÃ³ structure_client (remote, vd Gemma) â†’ cáº¥u trÃºc-hoÃ¡ cháº¡y remote, mÃ¡y
        # local KHá»ŽI náº¡p/swap text model. None â‡’ dÃ¹ng client local nhÆ° cÅ©.
        structure_client = self.structure_client or self.client
        structure_backend = "remote" if self.structure_client is not None else "local"
        messages = [
            {"role": "system", "content": self._structure_system_prompt()},
            {"role": "user", "content": self._structure_user_prompt(
                caption=caption,
                ocr_text=ocr_text,
                observer_frame=observer_frame,
                signal_snapshot=signal_snapshot,
                extra_context=extra_context,
            )},
        ]
        result = structure_client.chat_json(
            self._structure_model(),
            messages,
            schema=self._json_schema(),
            keep_alive=self.config.keep_alive,
            temperature=self.config.temperature,
        )

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            self._log_warning("Vision structuring failed: %s", err)
            if no_fallback_mode_enabled():
                raise RuntimeError(f"no_fallback_vision:structure_failed:{err}")
            # Táº§ng cáº¥u trÃºc lá»—i nhÆ°ng caption tháº­t váº«n cÃ²n giÃ¡ trá»‹ tri giÃ¡c.
            return self._fallback_ocr_note(
                ocr_text=ocr_text,
                observer_frame=observer_frame,
                signal_snapshot=signal_snapshot,
                reason=f"structure_failed:{err}",
                caption=caption,
            )

        parsed = getattr(result, "parsed", {}) or {}
        note = self._note_from_mapping(
            parsed,
            observer_frame=observer_frame,
            signal_snapshot=signal_snapshot,
            caption=caption,
            raw_debug={
                "model": self._source_label(),
                "structure_backend": structure_backend,
                "caption_backend": caption_backend,
                "vision_caption": compact_text(caption, 400),
                "caption_error": caption_error,
                "structure_preview": compact_text(str(getattr(result, "content", "") or ""), 400),
            },
            source_override=(
                str(getattr(self.caption_client, "model_name", "") or "")
                if self.caption_client is not None
                else ""
            ),
        )
        return note

    def _compress_single_shot(
        self,
        *,
        image: str,
        ocr_text: str,
        observer_frame: ObserverFrame | None,
        signal_snapshot: SignalSnapshot | None,
        extra_context: str,
    ) -> SemanticSceneNote:
        """ÄÆ°á»ng cÅ©: gá»i vision model má»™t phÃ¡t vá»›i schema (cho client khÃ´ng cÃ³
        caption_image, vd OllamaClient + VLM Ä‘á»§ máº¡nh)."""
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
            except Exception as exc:  # pragma: no cover - unload lá»—i khÃ´ng nÃªn phÃ¡ runtime
                self._log_warning("Vision compressor unload failed: %s", exc)

        return note

    def compress_from_ocr_only(
        self,
        *,
        ocr_text: str = "",
        observer_frame: ObserverFrame | None = None,
        signal_snapshot: SignalSnapshot | None = None,
    ) -> SemanticSceneNote:
        """Public fallback khi runtime chÆ°a cÃ³ áº£nh nhÆ°ng cÃ³ OCR."""

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
            "Describe the world content on screen and its affect honestly (a sad video is sad, "
            "a failing test is an error) â€” that is a fact about the screen.\n"
            "Do not infer the USER's hidden emotions, identity, private intent, or personality.\n"
            "Do not produce prose outside JSON.\n"
            "Prefer visible, grounded facts.\n"
            "If uncertain, lower confidence.\n"
            "Keep should_interrupt_user false unless the screenshot shows a clear urgent runtime hazard."
        )

    def _structure_model(self) -> str:
        """Model for the text-structuring stage when using OllamaClient."""
        return self.config.structure_model or "qwen3"

    @staticmethod
    def _caption_prompt() -> str:
        return (
            "Describe this screen concisely but concretely. "
            "Say what application or window is shown and what is being looked at. "
            "Copy any clearly readable title, label, or error message. "
            "If a video/image/game/media is shown, describe its content and emotional tone "
            "(for example: a melancholic video about an old cat). "
            "Write 1-3 plain sentences. Do not guess anything you cannot actually see."
        )

    @staticmethod
    def _structure_system_prompt() -> str:
        return (
            "You are ERIS VisionSemanticCompressor (structuring stage).\n"
            "You are given a vision caption and OCR text of the user's screen, plus observer signals "
            "and possibly the PREVIOUS scene.\n"
            "Compress them into ONE small json runtime note that matches the schema.\n"
            "Describe the world content and its affect honestly: a sad video is sad, a test failure "
            "is an error, a heated chat is tense. That is a fact about the screen, not about the user.\n"
            "Do NOT infer the user's hidden emotions, identity, private intent, or personality.\n"
            "Fields you must fill:\n"
            "- visible_context: what is actually on screen (do not echo these instructions).\n"
            "- content_summary: what the content IS or MEANS (e.g. 'a melancholic video about an old cat', "
            "'a failing pytest run on the vision loader').\n"
            "- content_affect: one short word for the content's emotional tone "
            "(sad|tense|joyful|calm|frustrating|neutral|...).\n"
            "- relation_to_user: how this scene relates to what the user was doing "
            "(e.g. 'switched away from code to watch something sad'). Empty if unclear.\n"
            "- delta: what CHANGED versus the previous scene given below. Empty if there is no previous "
            "scene or nothing meaningful changed.\n"
            "- semantic_family: short snake_case label for WHAT this scene is "
            "(e.g. test_failure_loop, sad_media, code_editing, docs_reading).\n"
            "Output json only. If evidence is thin, lower confidence.\n"
            "Keep should_interrupt_user false unless there is a clear urgent runtime hazard."
        )

    def _structure_user_prompt(
        self,
        *,
        caption: str,
        ocr_text: str,
        observer_frame: ObserverFrame | None,
        signal_snapshot: SignalSnapshot | None,
        extra_context: str,
    ) -> str:
        payload = {
            "vision_caption": compact_text(caption, 600),
            "ocr_text": compact_text(ocr_text, self.config.max_ocr_chars),
            "observer": self._observer_payload(observer_frame),
            "signal": self._signal_payload(signal_snapshot),
            "previous_scene": self._previous_scene_payload(),
            "extra_context": compact_text(extra_context, 500),
        }
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return compact_text(text, self.config.max_context_chars)

    def _previous_scene_payload(self) -> dict[str, str]:
        if not self._last_scene:
            return {}
        return {
            "content_summary": self._last_scene.get("content_summary", ""),
            "semantic_family": self._last_scene.get("semantic_family", ""),
            "content_affect": self._last_scene.get("content_affect", ""),
        }

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
                "content_summary": {"type": "string"},
                "content_affect": {"type": "string"},
                "relation_to_user": {"type": "string"},
                "delta": {"type": "string"},
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
        caption: str = "",
        raw_debug: Mapping[str, Any] | None = None,
        source_override: str = "",
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

        model_label = source_override or self.config.model
        evidence = [f"vision_model:{model_label}"]
        if observer_frame is not None:
            evidence.extend(str(item) for item in getattr(observer_frame, "evidence", [])[:4])
        if signal_snapshot is not None and getattr(signal_snapshot, "screen_hash", ""):
            evidence.append(f"screen_hash:{getattr(signal_snapshot, 'screen_hash')}")

        # visible_context pháº£i mang ná»™i dung tháº­t. Náº¿u model tráº£ rá»—ng hoáº·c nháº£ láº¡i
        # mÃ´ táº£ field (parrot), rÆ¡i vá» caption tá»± do cá»§a vision model.
        visible = compact_text(str(data.get("visible_context", "") or ""), 260)
        if self._looks_like_echo(visible) or not visible:
            visible = compact_text(caption, 260) or visible or "visible screen context"
        if caption:
            evidence.append(f"vision_caption:{compact_text(caption, 90)}")

        # Táº¦NG-1: nghÄ©a + thay Ä‘á»•i. Lá»c echo cho cÃ¡c trÆ°á»ng text.
        content_summary = self._clean_meaning(data.get("content_summary", ""), 260)
        if not content_summary:
            content_summary = visible
        content_affect = self._clean_meaning(data.get("content_affect", ""), 80)
        relation_to_user = self._clean_meaning(data.get("relation_to_user", ""), 200)
        delta = self._clean_meaning(data.get("delta", ""), 200)
        family = self._clean_family(data.get("semantic_family", "unknown"))

        note = SemanticSceneNote(
            visible_context=visible,
            important_text=important,
            activity_intent=coerce_activity_intent(data.get("activity_intent", "unknown")),
            semantic_family=family,
            novelty=novelty,
            salience=salience,
            possible_error=possible_error,
            should_interrupt_user=should_interrupt,
            confidence=confidence,
            content_summary=content_summary,
            content_affect=content_affect,
            relation_to_user=relation_to_user,
            delta=delta,
            source=source_override or self._source_label(),
            evidence=evidence[:10],
            debug={"raw": dict(raw_debug or {}), "observer_used": observer_frame is not None},
        )
        self._assign_scene_continuity(note)
        return note

    def _fallback_ocr_note(
        self,
        *,
        ocr_text: str,
        observer_frame: ObserverFrame | None,
        signal_snapshot: SignalSnapshot | None,
        reason: str,
        caption: str = "",
    ) -> SemanticSceneNote:
        source_text = ocr_text or str(getattr(signal_snapshot, "ocr_text", "") if signal_snapshot else "")
        folded = normalize_ascii_fold(f"{source_text}\n{caption}")
        observer_focus = str(getattr(observer_frame, "focus_kind", "unknown") if observer_frame else "unknown")
        observer_intent = str(getattr(observer_frame, "activity_intent", "unknown") if observer_frame else "unknown")
        observer_salience = clamp01(getattr(observer_frame, "salience", 0.0) if observer_frame else 0.0)
        observer_novelty = clamp01(getattr(observer_frame, "novelty", 0.0) if observer_frame else 0.0)
        observer_error = clamp01(getattr(observer_frame, "possible_error", 0.0) if observer_frame else 0.0)

        text_error = 1.0 if any(marker in folded for marker in _ERROR_MARKERS) else 0.0
        possible_error = max(observer_error, 0.78 if text_error else 0.0)
        intent = observer_intent if observer_intent != "unknown" else self._infer_intent_from_text(f"{source_text} {caption}", observer_focus)
        family = self._infer_family_from_text(f"{source_text} {caption}", possible_error=possible_error, focus_kind=observer_focus)
        # CÃ³ caption tháº­t tá»« vision model â†’ giá»¯ lÃ m visible_context, Ä‘á»«ng vá»©t.
        clean_caption = compact_text(caption, 260)
        if clean_caption and not self._looks_like_echo(clean_caption):
            visible = clean_caption
            source = "vision_caption_only"
            confidence = 0.50
            salience_floor = 0.28
            novelty_floor = 0.22
        else:
            visible = self._fallback_visible_context(signal_snapshot, observer_focus, intent)
            source = "ocr_only"
            confidence = 0.42 if source_text else 0.25
            salience_floor = 0.20 if source_text else 0.0
            novelty_floor = 0.18 if source_text else 0.0
        important = self._extract_important_lines(source_text)
        evidence = [reason]
        if clean_caption:
            evidence.append(f"vision_caption:{compact_text(clean_caption, 90)}")
        if observer_frame is not None:
            evidence.extend(str(x) for x in getattr(observer_frame, "evidence", [])[:4])

        note = SemanticSceneNote(
            visible_context=visible,
            important_text=important,
            activity_intent=coerce_activity_intent(intent),
            semantic_family=family,
            novelty=max(observer_novelty * 0.72, novelty_floor),
            salience=max(observer_salience * 0.65, possible_error * 0.72, salience_floor),
            possible_error=possible_error,
            should_interrupt_user=False,
            confidence=confidence,
            content_summary=visible if visible else "",
            source=source,
            evidence=evidence,
            debug={"fallback_reason": reason, "text_error_marker": bool(text_error), "has_caption": bool(clean_caption)},
        )
        self._assign_scene_continuity(note)
        return note

    def _clean_meaning(self, value: Any, limit: int) -> str:
        """Compact + loáº¡i echo cho cÃ¡c trÆ°á»ng nghÄ©a (content/affect/relation/delta)."""
        text = compact_text(str(value or ""), limit)
        if not text or self._looks_like_echo(text):
            return ""
        return text

    def _assign_scene_continuity(self, note: SemanticSceneNote) -> None:
        """GÃ¡n scene_id + prev_scene_id Ä‘á»ƒ 'thay Ä‘á»•i' cÃ³ chá»— bÃ¡m, cáº­p nháº­t scene cuá»‘i."""
        key = note.content_summary or note.visible_context
        scene_id = stable_hash(f"{note.semantic_family}|{key}")
        note.prev_scene_id = self._last_scene.get("scene_id", "")
        note.scene_id = scene_id
        # Model khÃ´ng cho delta nhÆ°ng scene Ä‘á»•i rÃµ â†’ ghi delta tá»‘i thiá»ƒu Ä‘á»ƒ runtime
        # váº«n tháº¥y cÃ³ chuyá»ƒn cáº£nh.
        if not note.delta and note.prev_scene_id and note.prev_scene_id != scene_id:
            prev_summary = self._last_scene.get("content_summary", "")
            if prev_summary and prev_summary != key:
                note.delta = compact_text(f"scene shifted from: {prev_summary}", 200)
        self._last_scene = {
            "scene_id": scene_id,
            "content_summary": note.content_summary,
            "semantic_family": note.semantic_family,
            "content_affect": note.content_affect,
        }

    @staticmethod
    def _looks_like_echo(text: str) -> bool:
        """Báº¯t trÆ°á»ng há»£p model nhá» nháº£ láº¡i mÃ´ táº£ field/instruction thay vÃ¬ ná»™i dung."""
        if not text:
            return False
        folded = normalize_ascii_fold(text)
        echo_markers = (
            "short description of what",
            "up to 8 short strings",
            "short snake_case label",
            "how new this scene",
            "how much runtime should care",
            "copied/paraphrased from visible text",
            "visible technical/runtime error likelihood",
        )
        return any(marker in folded for marker in echo_markers)

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
        """Tráº£ source label tá»« model name, dÃ¹ng cho SemanticSceneNote.source."""
        model = str(self.config.model or "").strip().lower().split(":")[0]
        return model or "vision_model"

    @staticmethod
    def _make_default_client() -> Any | None:
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
