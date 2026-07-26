import requests
import re
import os
import logging

from llm.token_budget import (
    detect_provider as _detect_provider,
    estimate_tokens as _estimate_tokens,
    enforce_prompt_cap as _enforce_prompt_cap,
    preflight as _preflight,
)
from llm.token_pressure import GLOBAL_TOKEN_PRESSURE_GOVERNOR
from runtime.observability import GLOBAL_OBSERVABILITY
from runtime.diagnostic_logging import safe_log
from runtime.inference_broker import (
    GLOBAL_INFERENCE_BROKER,
    current_inference_context,
)
from llm.key_pool import get_provider_circuit
from llm.deepseek import (
    is_deepseek,
    normalize_model as normalize_deepseek_model,
    reasoning_effort as deepseek_reasoning_effort,
    thinking_mode as deepseek_thinking_mode,
)

_LOGGER = logging.getLogger("LLM")


def _runtime_reasoning_effort() -> str:
    try:
        from runtime.runtime_settings_store import runtime_text
        return runtime_text("chat", "reasoning_effort", default="medium")
    except Exception:
        return str(os.environ.get("ERIS_REASONING_EFFORT", "medium") or "medium")


def _pressure_provider(base_url: str, model_name: str) -> str:
    return _detect_provider(base_url, model_name)


def _record_pressure_request(base_url: str, model_name: str, messages, max_tokens: int) -> str:
    """Ghi request ở tầng transport để mọi lane đều góp vào pressure window."""

    provider = _pressure_provider(base_url, model_name)
    try:
        prompt_tokens = _estimate_tokens(messages)
        lane = current_inference_context().lane or "transport"
        GLOBAL_TOKEN_PRESSURE_GOVERNOR.record_request(
            provider,
            lane=lane,
            prompt_tokens=prompt_tokens,
            output_tokens=max_tokens,
        )
        metric_tags = {"provider": provider, "lane": lane, "model": str(model_name or "unknown")[:80]}
        GLOBAL_OBSERVABILITY.observe("input_tokens_by_lane", prompt_tokens, tags=metric_tags)
        GLOBAL_OBSERVABILITY.observe("output_tokens_by_lane", max_tokens, tags=metric_tags)
        snapshot = GLOBAL_TOKEN_PRESSURE_GOVERNOR.snapshot(provider, lane=lane)
        GLOBAL_OBSERVABILITY.gauge("token_pressure_ratio", snapshot.pressure, tags={"provider": provider})
    except Exception as exc:
        safe_log(_LOGGER, "debug", "Token pressure request telemetry failed: %s", exc)
    return provider


def _record_pressure_success(provider: str) -> None:
    try:
        GLOBAL_TOKEN_PRESSURE_GOVERNOR.record_success(provider)
    except Exception:
        pass


def _record_pressure_429(
    provider: str,
    response,
    default: float = 20.0,
    *,
    model_name: str = "",
) -> None:
    try:
        retry_after = _retry_after_seconds(response, default)
        lane = current_inference_context().lane or "transport"
        GLOBAL_TOKEN_PRESSURE_GOVERNOR.record_rate_limit(
            provider,
            retry_after_s=retry_after,
            lane=lane,
        )
        GLOBAL_INFERENCE_BROKER.record_rate_limit(provider, retry_after_s=retry_after)
        tags = {
            "provider": provider,
            "lane": lane,
            "model": str(model_name or "unknown")[:80],
        }
        GLOBAL_OBSERVABILITY.increment("rate_limit_429_total", tags=tags)
        GLOBAL_OBSERVABILITY.observe("retry_after_seconds", retry_after, tags=tags)
    except Exception:
        pass


def _brokered_post(
    *,
    base_url: str,
    model_name: str,
    messages,
    max_tokens: int,
    timeout_seconds: float,
    url: str,
    **request_kwargs,
):
    """Reserve quota before the HTTP request, then report provider headers.

    PDF annotation, pages 6-10: every OpenAI/Gemini compatible transport call
    enters the same broker.  This is intentionally below LlmService so direct
    users such as PrivateMind and vision adapters cannot bypass admission.
    """

    provider = _pressure_provider(base_url, model_name)
    prompt_tokens = _estimate_tokens(messages)
    original_payload = request_kwargs.get("json")
    supports_input_degrade = bool(
        isinstance(original_payload, dict)
        and isinstance(original_payload.get("messages"), list)
    )
    supports_output_degrade = bool(
        isinstance(original_payload, dict)
        and (
            "max_tokens" in original_payload
            or "max_completion_tokens" in original_payload
            or isinstance(original_payload.get("generationConfig"), dict)
        )
    )
    request = GLOBAL_INFERENCE_BROKER.request_from_context(
        provider=provider,
        model=model_name,
        estimated_input_tokens=prompt_tokens,
        reserved_output_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
        metadata={
            "transport": "requests.post",
            # PDF annotation, page 8: required-lane degradation is legal only
            # when the adapter can actually rewrite the payload to match the
            # smaller reservation. The broker is an accountant, not a novelist.
            "input_degrade_supported": supports_input_degrade,
            "output_degrade_supported": supports_output_degrade,
        },
    )

    configured_timeout_seconds = float(timeout_seconds)

    def send(*, cancel_token=None, timeout_seconds=None, inference_request=None):
        # PDF annotation, pages 5, 7 and 10: cancellation/deadline must reach
        # the adapter, not merely discard a Future after quota is already gone.
        actual_request = inference_request or request
        if cancel_token is not None:
            cancel_token.raise_if_cancelled(actual_request)
        effective_timeout = max(
            0.05,
            min(
                float(timeout_seconds or configured_timeout_seconds),
                configured_timeout_seconds,
            ),
        )

        effective_messages = list(messages or [])
        if supports_input_degrade and actual_request.estimated_input_tokens < prompt_tokens:
            effective_messages, _trimmed = _enforce_prompt_cap(
                effective_messages, max(1, int(actual_request.estimated_input_tokens))
            )
        effective_max_tokens = max(1, min(int(max_tokens), int(actual_request.reserved_output_tokens)))

        effective_kwargs = dict(request_kwargs)
        payload = effective_kwargs.get("json")
        if isinstance(payload, dict):
            payload = dict(payload)
            if supports_input_degrade and "messages" in payload:
                payload["messages"] = effective_messages
            if "max_tokens" in payload:
                payload["max_tokens"] = effective_max_tokens
            if "max_completion_tokens" in payload:
                payload["max_completion_tokens"] = effective_max_tokens
            generation_config = payload.get("generationConfig")
            if isinstance(generation_config, dict):
                generation_config = dict(generation_config)
                generation_config["maxOutputTokens"] = effective_max_tokens
                payload["generationConfig"] = generation_config
            effective_kwargs["json"] = payload

        _record_pressure_request(
            base_url, model_name, effective_messages, effective_max_tokens
        )
        response = requests.post(url, timeout=effective_timeout, **effective_kwargs)
        if cancel_token is not None:
            cancel_token.raise_if_cancelled(actual_request)
        # retry-after, RPM and TPM headers are consumed once here.  The client
        # error path records a header-less 429 fallback only when necessary.
        GLOBAL_INFERENCE_BROKER.record_response_headers(provider, getattr(response, "headers", None))
        return response

    return GLOBAL_INFERENCE_BROKER.run(request, send)


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


def _retry_after_seconds(response, default: float = 60.0) -> float:
    """Đọc Retry-After/retryDelay từ response 429, fallback về ``default``."""

    try:
        raw = str((getattr(response, "headers", {}) or {}).get("Retry-After", "")).strip()
        if raw:
            return max(1.0, min(float(raw), 3600.0))
    except (TypeError, ValueError):
        pass
    try:
        body = str(getattr(response, "text", "") or "")
        match = re.search(r'"retryDelay"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)s?', body, flags=re.I)
        if match:
            return max(1.0, min(float(match.group(1)), 3600.0))
    except (TypeError, ValueError, OverflowError):
        pass
    return max(1.0, float(default))


def _key_pool_attempt_limit(_model_name: str, pool_size: int) -> int:
    """Giới hạn số project một request được phép thử khi gặp 429.

    PDF annotation, pages 6-9 and 19-20: retry fan-out is governed by one
    provider-wide setting.  Removed-model compatibility must not silently
    create a second quota policy.
    """

    size = max(1, int(pool_size or 1))
    raw = str(os.environ.get("ERIS_KEY_POOL_MAX_ATTEMPTS", "") or "").strip()
    if not raw:
        return size
    try:
        return max(1, min(size, int(raw)))
    except (TypeError, ValueError):
        return size


def _is_empty_output_error(exc: requests.HTTPError) -> bool:
    """Detect lỗi Groq 'model output must contain either output text or tool calls'.

    Lỗi này xảy ra khi model thinking Qwen với reasoning_effort=none
    + response_format=json_object tạo ra empty output. Cần retry mà không có
    response_format hoặc reasoning_effort.
    """
    try:
        body = exc.response.text or ""
        return "model output" in body and "tool calls" in body
    except Exception:
        return False


def _chat_payload_variants(payload: dict) -> list[dict]:
    """Sinh các payload tương thích nhưng không vô tình tắt reasoning trước.

    Biến thể đầu luôn là payload mạnh nhất. Chỉ khi endpoint trả 4xx vì không hiểu
    field mới lần lượt bỏ grammar/response_format/reasoning metadata. Với endpoint
    OpenAI-compatible cũ, ``max_completion_tokens`` cũng có biến thể ``max_tokens``.
    """

    variants = [payload]

    if "max_completion_tokens" in payload:
        legacy_tokens = dict(payload)
        legacy_tokens["max_tokens"] = legacy_tokens.pop("max_completion_tokens")
        variants.append(legacy_tokens)

    base_variants = list(variants)
    for base in base_variants:
        if "grammar" in base:
            without_grammar = dict(base)
            without_grammar.pop("grammar", None)
            variants.append(without_grammar)
        if "response_format" in base:
            without_response_format = dict(base)
            without_response_format.pop("response_format", None)
            variants.append(without_response_format)
        if "grammar" in base and "response_format" in base:
            minimal = dict(base)
            minimal.pop("grammar", None)
            minimal.pop("response_format", None)
            variants.append(minimal)

    # Aggregator OpenAI-compatible thuần có thể không nhận các field reasoning.
    # Bỏ chúng ở cuối cùng, sau khi đã thử đường parsed reasoning chuẩn.
    for optional_key in ("reasoning_effort", "reasoning_format", "include_reasoning", "thinking"):
        if any(optional_key in variant for variant in variants):
            for variant in list(variants):
                if optional_key not in variant:
                    continue
                relaxed = dict(variant)
                relaxed.pop(optional_key, None)
                variants.append(relaxed)
    return variants


def _is_groq_endpoint(base_url: str) -> bool:
    return "api.groq.com" in (base_url or "").strip().lower()


def _is_qwen_model(model_name: str) -> bool:
    return "qwen" in (model_name or "").strip().lower()


def _model_supports_reasoning_format(model_name: str) -> bool:
    """Return whether the configured, supported model family exposes parsed reasoning."""

    return "qwen" in (model_name or "").strip().lower()


def _normalize_reasoning_effort(model_name: str, requested: str | None) -> str | None:
    """Ánh xạ effort cho các họ Qwen còn được ERIS hỗ trợ.

    PDF cleanup annotation: removed-model compatibility left the model stack, so this
    adapter no longer carries dormant payload rules for it.
    """

    name = (model_name or "").strip().lower()
    raw = (requested or _runtime_reasoning_effort() or "").strip().lower()
    if "qwen3-32b" in name:
        return None
    if "qwen3.6" in name:
        return "none" if raw in {"none", "off", "0", "false"} else "default"
    return None



class LlamaServerClient:
    def __init__(self, base_url: str, timeout: int = 30):
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
        except (requests.RequestException, TypeError, ValueError, KeyError) as exc:
            safe_log(_LOGGER, "debug", "Local model discovery failed: %s", exc)
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
        reasoning_format=None,
    ):
        messages = _preflight(messages, base_url=self.base_url, model=self.model_name)
        pressure_provider = _pressure_provider(self.base_url, self.model_name)
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

            actual_timeout = self.timeout if timeout is None else timeout
            response = _brokered_post(
                base_url=self.base_url,
                model_name=self.model_name,
                messages=messages,
                max_tokens=max_tokens,
                timeout_seconds=actual_timeout,
                url=f"{self.base_url}/chat/completions",
                json=candidate,
            )
            try:
                response.raise_for_status()
                _record_pressure_success(pressure_provider)
                return response.json()
            except requests.HTTPError as exc:
                last_error = _http_error_with_body(response)
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code == 429:
                    _record_pressure_429(pressure_provider, response, model_name=model_name)
                if status_code is not None and status_code < 500:
                    continue
                raise last_error

        if last_error is not None:
            raise last_error
        raise RuntimeError("LlamaServerClient khong tao duoc request hop le.")


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str, model_name: str, timeout: int = 30, key_pool=None):
        self.base_url = base_url.rstrip("/")
        self.key_pool = key_pool
        if not (api_key or "").strip() and key_pool is not None:
            lease = key_pool.acquire(allow_cooling=True)
            api_key = lease.key if lease is not None else ""
        self.api_key = self._normalize_api_key(api_key)
        configured_model = model_name.strip() or "gpt-5.4-nano"
        self.configured_model_name = configured_model
        self.model_name = (
            normalize_deepseek_model(configured_model)
            if is_deepseek(self.base_url, configured_model)
            else configured_model
        )
        self.timeout = timeout
        self._provider_circuit = get_provider_circuit(self.base_url)

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
        reasoning_format=None,
    ):
        messages = _preflight(messages, base_url=self.base_url, model=self.model_name)
        pressure_provider = _pressure_provider(self.base_url, self.model_name)
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

        deepseek_request = is_deepseek(self.base_url, self.model_name)
        groq_reasoning = _is_groq_endpoint(self.base_url) and _model_supports_reasoning_format(self.model_name)
        payload = {
            "model": self.model_name,
            "messages": messages,
        }
        if deepseek_request:
            mode = deepseek_thinking_mode(self.configured_model_name)
            payload["thinking"] = {"type": mode}
            payload["max_tokens"] = max_tokens
            if mode == "enabled":
                payload["reasoning_effort"] = deepseek_reasoning_effort(reasoning_effort)
            else:
                # Sampling controls are meaningful only in non-thinking mode.
                payload["temperature"] = temperature
                payload["frequency_penalty"] = frequency_penalty
                payload["presence_penalty"] = presence_penalty
        else:
            payload.update({
                "temperature": temperature,
                "frequency_penalty": frequency_penalty,
                "presence_penalty": presence_penalty,
            })
            # Groq tính reasoning + final answer chung trong completion budget.
            if groq_reasoning:
                payload["max_completion_tokens"] = max_tokens
                payload["top_p"] = 0.95
            else:
                payload["max_tokens"] = max_tokens
        if response_format is not None:
            payload["response_format"] = response_format
        if grammar is not None:
            payload["grammar"] = grammar

        if groq_reasoning:
            # JSON mode không cho reasoning_format=raw. parsed giữ nguyên năng lực
            # suy luận nhưng tách nó sang message.reasoning, content chỉ còn JSON.
            payload["reasoning_format"] = reasoning_format or "parsed"
            effort = _normalize_reasoning_effort(self.model_name, reasoning_effort)
            if effort is not None:
                payload["reasoning_effort"] = effort

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"

        # Có pool: gặp 429 thì xoay key kế và thử lại, tối đa bằng số key trong pool.
        pool_size = self.key_pool.size if (self.key_pool is not None and self.key_pool.size > 0) else 1
        max_attempts = _key_pool_attempt_limit(self.model_name, pool_size)
        last_error = None
        attempted_indices: set[int] = set()
        for attempt in range(max(1, max_attempts)):
            lease = None
            if self.key_pool is not None:
                lease = self.key_pool.acquire(exclude_indices=attempted_indices)
                if lease is None:
                    wait_s = self.key_pool.next_available_in()
                    raise RuntimeError(f"API key pool đang cooldown; thử lại sau khoảng {wait_s:.1f}s")
                attempted_indices.add(lease.index)
                self.api_key = self._normalize_api_key(lease.key)
                headers["Authorization"] = f"Bearer {self.api_key}"

            rate_limited = False
            auth_failed = False
            server_error = False
            seen_signatures = set()
            for candidate in _chat_payload_variants(payload):
                signature = tuple(sorted(candidate.keys()))
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)

                try:
                    self._provider_circuit.before_request(self.base_url)
                    actual_timeout = self.timeout if timeout is None else timeout
                    response = _brokered_post(
                        base_url=self.base_url,
                        model_name=self.model_name,
                        messages=messages,
                        max_tokens=max_tokens,
                        timeout_seconds=actual_timeout,
                        url=url,
                        headers=headers,
                        json=candidate,
                    )
                    response.raise_for_status()
                    try:
                        payload_json = response.json()
                    except ValueError as exc:
                        last_error = exc
                        continue
                    self._provider_circuit.record_success()
                    _record_pressure_success(pressure_provider)
                    if self.key_pool is not None and lease is not None:
                        self.key_pool.mark_success(lease=lease)
                    return payload_json
                except requests.HTTPError as exc:
                    last_error = _http_error_with_body(exc.response) if exc.response is not None else exc
                    status_code = exc.response.status_code if exc.response is not None else None
                    if status_code == 429:
                        rate_limited = True
                        _record_pressure_429(pressure_provider, exc.response, model_name=model_name)
                        break  # thoát vòng variant để xoay key
                    if status_code in (401, 403):
                        auth_failed = True
                        break
                    if status_code in (500, 502, 503, 504):
                        server_error = True
                        break  # lỗi tạm thời phía provider, không phải lỗi key
                    if status_code is not None and status_code < 500:
                        continue  # thử biến thể payload kế (vd bỏ grammar/response_format)
                    raise last_error
                except Exception as exc:
                    last_error = exc
                    raise

            if rate_limited and self.key_pool is not None:
                retry_s = _retry_after_seconds(getattr(last_error, "response", None), 60.0)
                may_rotate = self.key_pool.mark_rate_limited(
                    retry_s, lease=lease, reason=f"http_429:{self.model_name}"
                )
                if may_rotate and attempt < max_attempts - 1:
                    continue
            if auth_failed and self.key_pool is not None:
                try:
                    from llm.provider_errors import ProviderErrorKind, classify_provider_error
                    kind = classify_provider_error(last_error)
                except Exception:
                    kind = None
                if str(kind) == "key_revoked":
                    self.key_pool.mark_permanently_dead(lease=lease, reason="http_auth_key_revoked")
                else:
                    self.key_pool.mark_dead(3600.0, lease=lease, reason="http_auth_or_permission")
                if attempt < max_attempts - 1:
                    continue
            if server_error:
                # 5xx thuộc provider/model, không đầu độc API key. Mở circuit
                # và để fallback chain xử lý provider khác.
                status = getattr(getattr(last_error, "response", None), "status_code", None)
                self._provider_circuit.record_failure(provider=self.base_url, status=status)
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
    def __init__(self, base_url: str, api_key: str, model_name: str, timeout: int = 30, key_pool=None):
        self.base_url = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        self.key_pool = key_pool
        # Nếu có pool dùng chung mà chưa truyền key cứng thì lấy key hiện tại của pool.
        if not (api_key or "").strip() and key_pool is not None:
            lease = key_pool.acquire(allow_cooling=True)
            api_key = lease.key if lease is not None else ""
        self.api_key = self._normalize_api_key(api_key)
        self.model_name = (model_name or "gemma-4-31b-it").strip()
        self.timeout = timeout
        self._provider_circuit = get_provider_circuit(self.base_url)

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
        reasoning_format=None,
    ):
        messages = _preflight(messages, base_url=self.base_url, model=self.model_name)
        pressure_provider = _pressure_provider(self.base_url, self.model_name)
        system_instruction, contents = self._convert_messages(messages)
        is_gemma = self._is_gemma()
        if is_gemma:
            system_instruction, contents = self._apply_gemma_hygiene(system_instruction, contents)
        generation_config = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        effort = (reasoning_effort or _runtime_reasoning_effort() or "medium").strip().lower()
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
        pool_size = self.key_pool.size if (self.key_pool is not None and self.key_pool.size > 0) else 1
        max_attempts = _key_pool_attempt_limit(self.model_name, pool_size)
        last_response = None
        attempted_indices: set[int] = set()
        for attempt in range(max(1, max_attempts)):
            lease = None
            if self.key_pool is not None:
                lease = self.key_pool.acquire(exclude_indices=attempted_indices)
                if lease is None:
                    wait_s = self.key_pool.next_available_in()
                    raise RuntimeError(f"Gemini key pool đang cooldown; thử lại sau khoảng {wait_s:.1f}s")
                attempted_indices.add(lease.index)
                self.api_key = self._normalize_api_key(lease.key)
            self._provider_circuit.before_request(self.base_url)
            actual_timeout = self.timeout if timeout is None else timeout
            last_response = _brokered_post(
                base_url=self.base_url,
                model_name=self.model_name,
                messages=messages,
                max_tokens=max_tokens,
                timeout_seconds=actual_timeout,
                url=f"{self.base_url}/models/{self.model_name}:generateContent",
                headers={
                    "x-goog-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            status = last_response.status_code
            if status == 429:
                _record_pressure_429(pressure_provider, last_response, 60.0, model_name=model_name)
            if status == 429 and self.key_pool is not None:
                retry_s = _retry_after_seconds(last_response, 60.0)
                may_rotate = self.key_pool.mark_rate_limited(
                    retry_s, lease=lease, reason=f"http_429:{self.model_name}"
                )
                if may_rotate and attempt < max_attempts - 1:
                    _LOGGER.warning(
                        "[GEMINI RETRY] status=429 attempt=%d/%d failed_index=%s → acquire key khác",
                        attempt + 1,
                        max_attempts,
                        getattr(lease, "index", "?"),
                    )
                    continue
            elif status in (401, 403) and self.key_pool is not None:
                try:
                    from llm.provider_errors import classify_provider_error
                    kind = classify_provider_error(last_response.text or f"http {status}", status_code=status)
                except Exception:
                    kind = None
                if str(kind) == "key_revoked":
                    self.key_pool.mark_permanently_dead(lease=lease, reason="http_auth_key_revoked")
                else:
                    self.key_pool.mark_dead(3600.0, lease=lease, reason="http_auth_or_permission")
                if attempt < max_attempts - 1:
                    continue
            elif status in (500, 502, 503, 504):
                self._provider_circuit.record_failure(provider=self.base_url, status=status)
                # Không xoay/mark-dead key vì mọi key cùng đập một provider đang lỗi.
            elif 200 <= status < 300:
                self._provider_circuit.record_success()
                _record_pressure_success(pressure_provider)
                if self.key_pool is not None and lease is not None:
                    self.key_pool.mark_success(lease=lease)
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
        except (OSError, TypeError, ValueError) as exc:
            safe_log(_LOGGER, "debug", "LLM debug dump failed: %s", exc)
