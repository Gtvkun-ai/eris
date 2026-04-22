import requests
import re


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
        response = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


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

        last_error = None
        seen_signatures = set()
        for candidate in variants:
            signature = tuple(sorted(candidate.keys()))
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)

            try:
                response = requests.post(
                    url,
                    headers=headers,
                    json=candidate,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return response.json()
            except requests.HTTPError as exc:
                last_error = exc
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code is not None and status_code < 500:
                    continue
                raise
            except Exception as exc:
                last_error = exc
                raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("OpenAICompatibleClient khong tao duoc request hop le.")
