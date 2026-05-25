import requests
import re


def _http_error_with_body(response: requests.Response) -> requests.HTTPError:
    message = f"{response.status_code} Client Error: {response.reason} for url: {response.url}"
    body = (response.text or "").strip()
    if body:
        message = f"{message} | body: {body[:1200]}"
    return requests.HTTPError(message, response=response)


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
    return variants


class LlamaServerClient:
    def __init__(self, base_url: str, timeout: int = 180):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.model_name = self._detect_model_name()
    # init này thiết lập URL cơ sở cho llama-server, 
    # đặt thời gian chờ mặc định cho các yêu cầu HTTP, 
    # và cố gắng phát hiện tên mô hình đang được sử dụng trên server. 
    # Việc phát hiện mô hình giúp client biết cách tương tác chính xác với 
    # server dựa trên khả năng của mô hình đó.
    def _detect_model_name(self) -> str:
        try:
            response = requests.get(f"{self.base_url}/models", timeout=15)
            # Gửi yêu cầu GET đến endpoint /models của llama-server để lấy thông tin về các mô hình đã load.
            response.raise_for_status()
            # Nếu yêu cầu thành công, phân tích phản hồi JSON để trích xuất tên mô hình.
            payload = response.json()
            models = payload.get("data", [])
            if models:
                return models[0].get("id", "local-model")
        except Exception:
            pass
        return "local-model"

    # create_chat_completion là phương thức chính để tạo phản 
    # hồi chat dựa trên các tin nhắn đầu vào và các tham số điều chỉnh như nhiệt độ,
    # tần suất phạt, sự hiện diện phạt, và số lượng token tối đa. 
    # Nó xây dựng một payload JSON và gửi yêu cầu POST đến endpoint /chat/completions
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
    ):
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

        # Gửi yêu cầu POST đến llama-server với payload 
        # đã xây dựng và trả về phản hồi JSON nếu thành công.
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
    def __init__(self, base_url: str, api_key: str, model_name: str, timeout: int = 180):
        self.base_url = base_url.rstrip("/")
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

        token_match = re.search(r"\bsk-[A-Za-z0-9._\-]+\b", candidate)
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
    ):
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

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"

        last_error = None
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
                if status_code is not None and status_code < 500:
                    continue
                raise last_error
            except Exception as exc:
                last_error = exc
                raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("OpenAICompatibleClient khong tao duoc request hop le.")


class GeminiClient:
    def __init__(self, base_url: str, api_key: str, model_name: str, timeout: int = 180):
        self.base_url = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        self.api_key = self._normalize_api_key(api_key)
        self.model_name = (model_name or "gemma-4-26b-a4b-it").strip()
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
    ):
        system_instruction, contents = self._convert_messages(messages)
        generation_config = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if self.model_name.startswith("gemini-2.5"):
            generation_config["thinkingConfig"] = {"thinkingBudget": 0}
        if response_format and response_format.get("type") == "json_object":
            generation_config["responseMimeType"] = "application/json"

        payload = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [self._text_part(system_instruction)]}

        response = requests.post(
            f"{self.base_url}/models/{self.model_name}:generateContent",
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout if timeout is None else timeout,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError:
            raise _http_error_with_body(response)
        return response.json()
