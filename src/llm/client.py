import requests
import re
import os
import logging

from llm.token_budget import preflight as _preflight

_LOGGER = logging.getLogger("LLM")


def _http_error_with_body(response: requests.Response) -> requests.HTTPError:
    message = f"{response.status_code} Client Error: {response.reason} for url: {response.url}"
    body = (response.text or "").strip()
    if body:
        message = f"{message} | body: {body[:1200]}"
    exc = requests.HTTPError(message, response=response)
    try:
        exc.response_json = response.json()
    except Exception:
        exc.response_json = {}
    return exc


def _is_empty_output_error(exc: requests.HTTPError) -> bool:
    """Detect lỗi Groq 'model output must contain either output text or tool calls'.

    Lỗi này xảy ra khi model thinking (Qwen3/GPT-OSS) với reasoning_effort=none
    + response_format=json_object tạo ra empty output. Cần retry mà không có
    response_format hoặc reasoning_effort.
    """
    try:
        body = exc.response.text or ""
        return "model output" in body and "tool calls" in body
    except Exception:
        return False


def _chat_payload_variants(payload: dict) -> list[dict]:
    variants = [payload]
    if "grammar" in payload:
        without_grammar = dict(payload)
        without_grammar.pop("grammar", None)
        variants.append(without_grammar)
    if "response_format" in payload:
        without_response_format = dict(payload)
        without_response_format.pop("response_format", None)
        variants.append(without_response_format)
    if "grammar" in payload and "response_format" in payload:
        minimal = dict(payload)
        minimal.pop("grammar", None)
        minimal.pop("response_format", None)
        variants.append(minimal)
    # Một số endpoint không nhận reasoning_effort → biến thể bỏ field này để
    # vẫn chạy được khi gặp 4xx (vd aggregator OpenAI-compatible thuần).
    if "reasoning_effort" in payload:
        for variant in list(variants):
            without_reasoning = dict(variant)
            without_reasoning.pop("reasoning_effort", None)
            variants.append(without_reasoning)
    return variants


def _model_supports_reasoning_toggle(model_name: str) -> bool:
    """Các model có chế độ "thinking" mà Groq cho tắt qua reasoning_effort.

    Chủ yếu Qwen3/Qwen và GPT-OSS. Trả về False cho llama/glm/gemma… để KHÔNG gửi
    field lạ lên endpoint không hỗ trợ.
    """

    name = (model_name or "").strip().lower()
    return "qwen" in name or "gpt-oss" in name


def _resolve_reasoning_effort() -> str:
    """Mức reasoning cho model có thinking. Mặc định "medium" để bật suy nghĩ.
    Đặt ERIS_REASONING_EFFORT=none/default/low/medium/high để thay đổi khi cần.
    """

    return (os.environ.get("ERIS_REASONING_EFFORT", "medium") or "medium").strip().lower()



class LlamaServerClient:
    def __init__(self, base_url: str, timeout: int = 180):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.model_name = self._detect_model_name()

    def _detect_model_name(self) -> str:
        try:
            response = requests.get(f"{self.base_url}/models", timeout=15)
            response.raise_for_status()
            payload = response.json()
            models = payload.get("data", [])
            if models:
                return models[0].get("id", "local-model")
        except Exception:
            pass
        return "local-model"

    def create_chat_completion(
        self,
        *,
        messages,
        temperature,
        frequency_penalty,
        presence_penalty,
        max_tokens,
        response_format=None,
        grammar=None,
        timeout=None,
        reasoning_effort=None,
    ):
        messages = _preflight(messages, base_url=self.base_url, model=self.model_name)
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "frequency_penalty": frequency_penalty,
            "presence_penalty": presence_penalty,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if grammar is not None:
            payload["grammar"] = grammar

        last_error = None
        seen_signatures = set()
        for candidate in _chat_payload_variants(payload):
            signature = tuple(sorted(candidate.keys()))
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)

            response = requests.post(
                f"{self.base_url}/chat/completions",
                json=candidate,
                timeout=self.timeout if timeout is None else timeout,
            )
            try:
                response.raise_for_status()
                return response.json()
            except requests.HTTPError as exc:
                last_error = _http_error_with_body(response)
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code is not None and status_code < 500:
                    continue
                raise last_error

        if last_error is not None:
            raise last_error
        raise RuntimeError("LlamaServerClient khong tao duoc request hop le.")


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str, model_name: str, timeout: int = 180, key_pool=None):
        self.base_url = base_url.rstrip("/")
        self.key_pool = key_pool
        if not (api_key or "").strip() and key_pool is not None:
            api_key = key_pool.current_key()
        self.api_key = self._normalize_api_key(api_key)
        self.model_name = model_name.strip() or "gpt-5.4-nano"
        self.timeout = timeout

    def _normalize_api_key(self, raw_value: str) -> str:
        candidate = (raw_value or "").strip()
        if not candidate:
            return ""

        # Allow users to paste a whole code snippet like api_key="sk-..."
        quoted = re.search(r'api_key\s*=\s*["\']([^"\']+)["\']', candidate, flags=re.IGNORECASE)
        if quoted:
            candidate = quoted.group(1).strip()

        token_match = re.search(r"\bg?sk[-_][A-Za-z0-9._\-]+\b", candidate)
        if token_match:
            candidate = token_match.group(0)

        candidate = candidate.strip()
        try:
            candidate.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError(
                "API key khong hop le. Hay chi dan dung gia tri key ASCII, vi du bat dau bang 'sk-'."
            ) from exc

        return candidate

    def create_chat_completion(
        self,
        *,
        messages,
        temperature,
        frequency_penalty,
        presence_penalty,
        max_tokens,
        response_format=None,
        grammar=None,
        timeout=None,
        reasoning_effort=None,
    ):
        messages = _preflight(messages, base_url=self.base_url, model=self.model_name)
        if response_format and response_format.get("type") == "json_object":
            last_msg_has_json = False
            if messages:
                last_msg = messages[-1]
                content = last_msg.get("content", "")
                if isinstance(content, str) and "json" in content.lower():
                    last_msg_has_json = True
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and "json" in part.get("text", "").lower():
                            last_msg_has_json = True
                            break
            if not last_msg_has_json and messages:
                messages = list(messages)
                last_msg = dict(messages[-1])
                if isinstance(last_msg.get("content"), str):
                    last_msg["content"] = last_msg["content"] + "\n\nReturn the output in json format."
                elif isinstance(last_msg.get("content"), list):
                    last_msg["content"] = list(last_msg["content"]) + [{"type": "text", "text": "\n\nReturn the output in json format."}]
                messages[-1] = last_msg

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "frequency_penalty": frequency_penalty,
            "presence_penalty": presence_penalty,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if grammar is not None:
            payload["grammar"] = grammar
        if _model_supports_reasoning_toggle(self.model_name):
            effort = reasoning_effort or _resolve_reasoning_effort()
            if effort and effort != "off" and effort != "none":
                payload["reasoning_effort"] = effort

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"

        # Có pool: gặp 429 thì xoay key kế và thử lại, tối đa bằng số key trong pool.
        max_attempts = self.key_pool.size if (self.key_pool is not None and self.key_pool.size > 0) else 1
        last_error = None
        for attempt in range(max(1, max_attempts)):
            if self.key_pool is not None:
                pool_key = self.key_pool.current_key()
                if pool_key:
                    self.api_key = self._normalize_api_key(pool_key)
                    headers["Authorization"] = f"Bearer {self.api_key}"

            rate_limited = False
            server_error = False
            seen_signatures = set()
            for candidate in _chat_payload_variants(payload):
                signature = tuple(sorted(candidate.keys()))
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)

                try:
                    response = requests.post(
                        url,
                        headers=headers,
                        json=candidate,
                        timeout=self.timeout if timeout is None else timeout,
                    )
                    response.raise_for_status()
                    return response.json()
                except requests.HTTPError as exc:
                    last_error = _http_error_with_body(exc.response) if exc.response is not None else exc
                    status_code = exc.response.status_code if exc.response is not None else None
                    if status_code == 429:
                        rate_limited = True
                        break  # thoát vòng variant để xoay key
                    if status_code in (500, 502, 503, 504):
                        server_error = True
                        break  # lỗi tạm thời phía provider → xoay key thử lại
                    if status_code is not None and status_code < 500:
                        continue  # thử biến thể payload kế (vd bỏ grammar/response_format)
                    raise last_error
                except Exception as exc:
                    last_error = exc
                    raise

            if (
                (rate_limited or server_error)
                and self.key_pool is not None
                and attempt < max_attempts - 1
            ):
                self.key_pool.mark_dead(60.0 if rate_limited else 15.0)
                if self.key_pool.rotate():
                    continue
            break

        if last_error is not None:
            raise last_error
        raise RuntimeError("OpenAICompatibleClient khong tao duoc request hop le.")


class ChainedFallbackClient:
    """Gộp nhiều client dự phòng thành MỘT, thử lần lượt cho tới khi có cái chạy.

    Dùng làm ``fallback_client`` của LlmService: khi main (OpenRouter) chết, service
    gọi client này MỘT lần; bên trong nó thử Groq (pool 8 key) trước, hỏng thì sang
    Gemini/gemma (pool 7 key). Mỗi sub-client tự xoay key trong pool của nó khi 429,
    nên đây là tầng "đổi NHÀ CUNG CẤP" sau khi đã vắt cạn pool của nhà trước.

    Giao diện trùng OpenAICompatibleClient/GeminiClient (chỉ cần create_chat_completion)
    nên không phải đụng vào logic failover của service.
    """

    def __init__(self, clients, logger=None):
        self._clients = [c for c in (clients or []) if c is not None]
        if not self._clients:
            raise ValueError("ChainedFallbackClient can it nhat mot client.")
        self._logger = logger or logging.getLogger("LLM")
        first = self._clients[0]
        # Mượn thuộc tính của client đầu để log/route (cap token) hoạt động như cũ.
        self.base_url = getattr(first, "base_url", "")
        self.model_name = getattr(first, "model_name", "")
        self.key_pool = getattr(first, "key_pool", None)

    def create_chat_completion(self, **kwargs):
        last_error: Exception | None = None
        for idx, client in enumerate(self._clients):
            try:
                return client.create_chat_completion(**kwargs)
            except Exception as exc:  # noqa: BLE001 - thử nhà kế tiếp
                last_error = exc
                self._logger.warning(
                    "[FALLBACK CHAIN] tier %d/%d (%s) loi: %s -> thu tier ke",
                    idx + 1,
                    len(self._clients),
                    getattr(client, "model_name", "?"),
                    exc,
                )
                continue
        if last_error is not None:
            raise last_error
        raise RuntimeError("ChainedFallbackClient khong co client kha dung.")


class GeminiClient:
    def __init__(self, base_url: str, api_key: str, model_name: str, timeout: int = 180, key_pool=None):
        self.base_url = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        self.key_pool = key_pool
        # Nếu có pool dùng chung mà chưa truyền key cứng thì lấy key hiện tại của pool.
        if not (api_key or "").strip() and key_pool is not None:
            api_key = key_pool.current_key()
        self.api_key = self._normalize_api_key(api_key)
        self.model_name = (model_name or "gemma-4-31b-it").strip()
        self.timeout = timeout

    def _normalize_api_key(self, raw_value: str) -> str:
        candidate = (raw_value or "").strip()
        if not candidate:
            return ""

        quoted = re.search(r'(?:api_key|GEMINI_API_KEY)\s*=\s*["\']([^"\']+)["\']', candidate, flags=re.IGNORECASE)
        if quoted:
            candidate = quoted.group(1).strip()

        try:
            candidate.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("Gemini API key khong hop le. Hay chi dan key ASCII.") from exc

        return candidate

    def _text_part(self, text: str) -> dict:
        return {"text": str(text or "")}

    def _image_part_from_url(self, url: str) -> dict:
        url = str(url or "")
        if url.startswith("data:") and ";base64," in url:
            header, data = url.split(";base64,", 1)
            mime_type = header.removeprefix("data:") or "image/jpeg"
            return {"inlineData": {"mimeType": mime_type, "data": data}}
        return {"fileData": {"fileUri": url}}

    def _parts_from_content(self, content) -> list[dict]:
        if isinstance(content, str):
            return [self._text_part(content)]
        if isinstance(content, list):
            parts: list[dict] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(self._text_part(item))
                    continue
                if not isinstance(item, dict):
                    parts.append(self._text_part(str(item)))
                    continue
                if item.get("type") == "text":
                    parts.append(self._text_part(item.get("text", "")))
                    continue
                if item.get("type") == "image_url":
                    image_url = item.get("image_url") or {}
                    if isinstance(image_url, dict):
                        parts.append(self._image_part_from_url(image_url.get("url", "")))
                    elif isinstance(image_url, str):
                        parts.append(self._image_part_from_url(image_url))
                    continue
                if "text" in item:
                    parts.append(self._text_part(item.get("text", "")))
                    continue
                parts.append(self._text_part(str(item)))
            return parts or [self._text_part("")]
        if isinstance(content, dict):
            if "text" in content:
                return [self._text_part(content.get("text", ""))]
            return [self._text_part(str(content))]
        return [self._text_part(str(content or ""))]

    def _convert_messages(self, messages: list[dict]) -> tuple[str, list[dict]]:
        system_parts: list[str] = []
        contents: list[dict] = []

        for message in messages or []:
            role = str(message.get("role") or "user")
            content = message.get("content", "")
            if role == "system":
                system_parts.extend(part.get("text", "") for part in self._parts_from_content(content) if "text" in part)
                continue

            gemini_role = "model" if role == "assistant" else "user"
            parts = self._parts_from_content(content)
            contents.append({"role": gemini_role, "parts": parts})

        if not contents:
            contents.append({"role": "user", "parts": [self._text_part("")]})
        return "\n\n".join(part for part in system_parts if part), contents

    def _is_gemma(self) -> bool:
        """Gemma trên Gemini API KHÔNG nhận system_instruction và KHÔNG nhận ảnh
        inline → gửi như vậy là 500. Phát hiện để gập system vào user-turn và
        tước ảnh (xem Phase 1: request hygiene)."""

        return self.model_name.strip().lower().startswith("gemma")

    @staticmethod
    def _is_text_part(part: dict) -> bool:
        return isinstance(part, dict) and "text" in part

    def _apply_gemma_hygiene(
        self, system_instruction: str, contents: list[dict]
    ) -> tuple[str, list[dict]]:
        """Chuẩn hoá payload cho Gemma: bỏ ảnh, gập system vào lượt user đầu tiên.

        - Mọi part không phải text (inlineData/fileData) bị loại; nếu một content
          mất hết part thì thay bằng ghi chú text để không gửi parts rỗng.
        - ``system_instruction`` (nếu có) được ghép làm tiền tố text của content
          user đầu tiên, rồi xoá khỏi field riêng (trả "").
        """

        cleaned: list[dict] = []
        dropped_images = False
        for content in contents:
            parts = content.get("parts") or []
            text_parts = [p for p in parts if self._is_text_part(p)]
            if len(text_parts) != len(parts):
                dropped_images = True
            if not text_parts:
                text_parts = [self._text_part("[ảnh đã được mô tả thành văn bản ở nơi khác]")]
            cleaned.append({"role": content.get("role", "user"), "parts": text_parts})

        if not cleaned:
            cleaned.append({"role": "user", "parts": [self._text_part("")]})

        if system_instruction:
            # Tìm content user đầu tiên để ghép; nếu không có, chèn một content mới.
            target = next((c for c in cleaned if c.get("role") == "user"), None)
            prefix = self._text_part(f"[Hướng dẫn hệ thống]\n{system_instruction}\n\n")
            if target is None:
                cleaned.insert(0, {"role": "user", "parts": [prefix]})
            else:
                target["parts"] = [prefix, *target["parts"]]

        if dropped_images:
            _LOGGER.debug("[GEMINI HYGIENE] stripped image part(s) for gemma model=%s", self.model_name)
        return "", cleaned

    def create_chat_completion(
        self,
        *,
        messages,
        temperature,
        frequency_penalty,
        presence_penalty,
        max_tokens,
        response_format=None,
        grammar=None,
        timeout=None,
        reasoning_effort=None,
    ):
        messages = _preflight(messages, base_url=self.base_url, model=self.model_name)
        system_instruction, contents = self._convert_messages(messages)
        is_gemma = self._is_gemma()
        if is_gemma:
            system_instruction, contents = self._apply_gemma_hygiene(system_instruction, contents)
        generation_config = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        effort = reasoning_effort or _resolve_reasoning_effort()
        if "gemini-2.5" in self.model_name or "thinking" in self.model_name or "gemini-2.0" in self.model_name:
            if effort == "none" or effort == "off":
                generation_config["thinkingConfig"] = {"thinkingBudget": 0}
            else:
                budget = 2048 if effort == "high" else 1024
                generation_config["thinkingConfig"] = {"thinkingBudget": budget}
        # Gemma (open model trên Gemini API) KHÔNG hỗ trợ controlled generation
        # (responseMimeType/responseSchema) — gửi kèm sẽ 400/500. Bỏ cho gemma;
        # adapter tự salvage JSON từ text thường.
        if response_format and response_format.get("type") == "json_object" and not is_gemma:
            generation_config["responseMimeType"] = "application/json"
            schema = response_format.get("responseSchema") or response_format.get("schema")
            if isinstance(schema, dict) and schema:
                generation_config["responseSchema"] = schema

        payload = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        # Gemma KHÔNG nhận field safetySettings → kèm vào là 500. Chỉ gửi cho
        # các model Gemini thật.
        if not is_gemma:
            payload["safetySettings"] = [
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            ]
        if system_instruction:
            payload["systemInstruction"] = {"parts": [self._text_part(system_instruction)]}

        # Có pool dùng chung: gặp 429 (hết quota project) thì xoay sang key kế và
        # thử lại, tối đa bằng số key trong pool. Không pool → đúng một lần như cũ.
        max_attempts = self.key_pool.size if (self.key_pool is not None and self.key_pool.size > 0) else 1
        last_response = None
        for attempt in range(max(1, max_attempts)):
            if self.key_pool is not None:
                pool_key = self.key_pool.current_key()
                if pool_key:
                    self.api_key = self._normalize_api_key(pool_key)
            last_response = requests.post(
                f"{self.base_url}/models/{self.model_name}:generateContent",
                headers={
                    "x-goog-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout if timeout is None else timeout,
            )
            status = last_response.status_code
            if (
                status in (429, 500, 502, 503, 504)
                and self.key_pool is not None
                and attempt < max_attempts - 1
            ):
                # 429 = hết quota key (nghỉ lâu); 5xx = lỗi tạm thời (nghỉ ngắn).
                self.key_pool.mark_dead(60.0 if status == 429 else 15.0)
                if self.key_pool.rotate():
                    _LOGGER.warning(
                        "[GEMINI RETRY] status=%s attempt=%d/%d → rotate key",
                        status,
                        attempt + 1,
                        max_attempts,
                    )
                    continue
            break

        response = last_response
        try:
            response.raise_for_status()
        except requests.HTTPError:
            self._maybe_dump_4xx(payload, response)
            raise _http_error_with_body(response)
        return response.json()

    def _maybe_dump_4xx(self, payload: dict, response) -> None:
        """Debug: khi gặp 4xx và bật ERIS_LLM_DEBUG_4XX, ghi payload + body đầy đủ
        ra file để soi (log C# cắt cụt body). Nuốt mọi lỗi."""
        try:
            status = getattr(response, "status_code", 0)
            if status < 400 or status >= 500:
                return
            if (os.environ.get("ERIS_LLM_DEBUG_4XX", "") or "").strip().lower() not in {"1", "true", "yes", "on"}:
                return
            import json as _json
            root = os.environ.get("ERIS_PROJECT_ROOT", "").strip() or os.getcwd()
            path = os.path.join(root, "_llm_4xx_debug.log")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"\n===== {self.model_name} status={status} =====\n")
                fh.write("PAYLOAD:\n" + _json.dumps(payload, ensure_ascii=False)[:4000] + "\n")
                fh.write("BODY:\n" + (response.text or "")[:2000] + "\n")
        except Exception:
            pass
