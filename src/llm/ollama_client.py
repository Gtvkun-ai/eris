# src/llm/ollama_client.py
"""
Client mỏng cho Ollama.

Vai trò trong ERIS:
- Dùng một Ollama daemon duy nhất thay vì mở nhiều llama-server riêng.
- Gọi model nhỏ cho BackgroundObserver.
- Gọi model vision cho VisionSemanticCompressor về sau.
- Ép JSON càng nhiều càng tốt, nhưng vẫn có salvage nếu model trả hơi bẩn.

Không phụ thuộc requests để chạy được trong repo Python tối giản.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


class OllamaClientError(RuntimeError):
    """Lỗi gọi Ollama. Tách riêng để runtime có thể fallback sạch."""


@dataclass(frozen=True)
class OllamaResult:
    """Kết quả chuẩn hóa từ Ollama.

    `parsed` chỉ có giá trị khi output parse được thành JSON object.
    `raw` giữ nguyên response từ Ollama để debug khi cần.
    """

    ok: bool
    parsed: dict[str, Any] = field(default_factory=dict)
    content: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class OllamaClient:
    """Client gọi Ollama qua HTTP API.

    Ollama mặc định chạy ở http://localhost:11434/api.
    Có thể override bằng env `OLLAMA_BASE_URL`.
    """

    base_url: str = field(
        default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/api")
    )
    timeout: float = field(default_factory=lambda: float(os.getenv("OLLAMA_TIMEOUT_SEC", "60")))

    def chat_json(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        images: Optional[list[str]] = None,
        schema: Optional[dict[str, Any]] = None,
        keep_alive: str | int | None = "5m",
        temperature: float = 0.0,
        options: Optional[dict[str, Any]] = None,
    ) -> OllamaResult:
        """Gọi `/api/chat` và kỳ vọng JSON object.

        Parameters
        ----------
        model:
            Tên model trong Ollama, ví dụ `qwen3:0.6b`.
        messages:
            Chat messages theo format Ollama/OpenAI-like.
        images:
            Danh sách ảnh base64. Chỉ dùng cho model vision.
            Ollama đặt ảnh vào message cuối.
        schema:
            JSON schema nếu muốn ép chặt. Nếu không có, dùng `format="json"`.
        keep_alive:
            Điều khiển model nằm trong memory bao lâu.
            - "30m": giữ observer loaded lâu.
            - 0: unload ngay sau request, hợp với vision nặng.
        """

        if not model:
            return OllamaResult(ok=False, error="missing_model")

        payload: dict[str, Any] = {
            "model": model,
            "messages": self._attach_images(messages, images),
            "stream": False,
            "format": schema if schema else "json",
            "options": {"temperature": temperature, **(options or {})},
        }
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive

        try:
            raw = self._post_json("/chat", payload)
        except Exception as exc:  # runtime sẽ fallback, không để chết loop
            return OllamaResult(ok=False, error=str(exc))

        content = self._extract_chat_content(raw)
        parsed = self._parse_json_object(content)
        if parsed is None:
            return OllamaResult(
                ok=False,
                content=content,
                raw=raw,
                error="json_parse_failed",
            )

        return OllamaResult(ok=True, parsed=parsed, content=content, raw=raw)

    def generate_json(
        self,
        model: str,
        prompt: str,
        *,
        images: Optional[list[str]] = None,
        schema: Optional[dict[str, Any]] = None,
        keep_alive: str | int | None = "5m",
        temperature: float = 0.0,
        options: Optional[dict[str, Any]] = None,
    ) -> OllamaResult:
        """Gọi `/api/generate` và kỳ vọng JSON object.

        Dùng khi không cần multi-turn messages.
        """

        if not model:
            return OllamaResult(ok=False, error="missing_model")

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": schema if schema else "json",
            "options": {"temperature": temperature, **(options or {})},
        }
        if images:
            payload["images"] = images
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive

        try:
            raw = self._post_json("/generate", payload)
        except Exception as exc:
            return OllamaResult(ok=False, error=str(exc))

        content = str(raw.get("response") or "")
        parsed = self._parse_json_object(content)
        if parsed is None:
            return OllamaResult(
                ok=False,
                content=content,
                raw=raw,
                error="json_parse_failed",
            )

        return OllamaResult(ok=True, parsed=parsed, content=content, raw=raw)

    def unload(self, model: str) -> OllamaResult:
        """Yêu cầu Ollama unload model.

        Hữu ích cho model vision nặng: gọi xong thả khỏi memory.
        """

        if not model:
            return OllamaResult(ok=False, error="missing_model")

        payload = {
            "model": model,
            "messages": [],
            "stream": False,
            "keep_alive": 0,
        }
        try:
            raw = self._post_json("/chat", payload)
            return OllamaResult(ok=True, raw=raw)
        except Exception as exc:
            return OllamaResult(ok=False, error=str(exc))

    def list_models(self) -> OllamaResult:
        """Lấy danh sách model đã pull trong Ollama."""

        try:
            raw = self._get_json("/tags")
            return OllamaResult(ok=True, parsed=raw, raw=raw)
        except Exception as exc:
            return OllamaResult(ok=False, error=str(exc))

    @staticmethod
    def encode_image_file(path: str) -> str:
        """Encode ảnh thành base64 thuần, phù hợp field `images`."""

        with open(path, "rb") as fh:
            return base64.b64encode(fh.read()).decode("utf-8")

    @staticmethod
    def encode_image_bytes(data: bytes) -> str:
        return base64.b64encode(data).decode("utf-8")

    @staticmethod
    def data_uri_to_base64(data_uri_or_base64: str) -> str:
        """Nhận data URI hoặc base64 thuần, trả base64 thuần."""

        if not data_uri_or_base64:
            return ""
        if "," in data_uri_or_base64 and data_uri_or_base64.strip().startswith("data:"):
            return data_uri_or_base64.split(",", 1)[1]
        return data_uri_or_base64

    def _attach_images(
        self,
        messages: list[dict[str, Any]],
        images: Optional[list[str]],
    ) -> list[dict[str, Any]]:
        if not images:
            return messages
        if not messages:
            messages = [{"role": "user", "content": "Analyze the image."}]

        cloned = [dict(m) for m in messages]
        clean_images = [self.data_uri_to_base64(img) for img in images if img]
        cloned[-1]["images"] = clean_images
        return cloned

    def _post_json(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + path
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._open_json(req)

    def _get_json(self, path: str) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + path
        req = urllib.request.Request(url, method="GET")
        return self._open_json(req)

    def _open_json(self, req: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                if not body:
                    return {}
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise OllamaClientError(f"Ollama HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise OllamaClientError(f"Ollama connection failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise OllamaClientError(f"Ollama returned non-JSON response: {exc}") from exc

    @staticmethod
    def _extract_chat_content(raw: dict[str, Any]) -> str:
        msg = raw.get("message")
        if isinstance(msg, dict):
            return str(msg.get("content") or "")
        return str(raw.get("response") or raw.get("content") or "")

    @staticmethod
    def _parse_json_object(content: str) -> Optional[dict[str, Any]]:
        """Parse JSON object, có salvage khi model lỡ bọc thêm text.

        Với `format=json`, bình thường không cần salvage. Nhưng model nhỏ đôi khi vẫn
        trả kèm markdown hoặc giải thích. Vì loài người đã tạo model rồi lại phải
        dọn sau model, thật là vòng đời tao nhã.
        """

        if not content:
            return None

        text = content.strip()
        # Bỏ code fence nếu có.
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            pass

        # Salvage object đầu tiên.
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None

        candidate = text[start : end + 1]
        try:
            value = json.loads(candidate)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
