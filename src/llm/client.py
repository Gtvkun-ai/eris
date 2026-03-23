import requests


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
