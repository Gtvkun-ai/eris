import os

from eris_secrets import apply_secrets_to_environ, get_provider_profile, get_secret
from .client import GeminiClient, OpenAICompatibleClient
from .key_pool import get_key_pool


class RemoteModelProcessManager:
    def __init__(self, *, logger, project_root: str):
        self.logger = logger
        self.project_root = project_root

    def _env_flag(self, name: str, default: str = "0") -> bool:
        return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}

    def _build_remote_client(self):
        apply_secrets_to_environ()
        provider = os.environ.get("ERIS_REMOTE_PROVIDER", "gemini").strip().lower()
        remote_profile = get_provider_profile(provider, slot="remote_main")
        if provider in {"openai", "openai_compatible", "compatible", "remote", "groq"}:
            # Khi chạy Groq/OpenAI-compatible: ưu tiên key Groq + pool Groq riêng
            # (tách khỏi pool Gemini) để không gửi nhầm key Gemini sang Groq.
            pool = get_key_pool("groq")
            pool_key = pool.current_key() if pool is not None else ""
            api_key = (
                str(remote_profile.get("api_key") or "").strip()
                or pool_key
                or get_secret("ERIS_GROQ_API_KEY", "ERIS_REMOTE_API_KEY", "OPENAI_API_KEY")
            )
        else:
            api_key = (
                str(remote_profile.get("api_key") or "").strip()
                or get_secret("ERIS_REMOTE_API_KEY", "GEMINI_API_KEY")
            )

        if provider == "gemini":
            base_url = (
                str(remote_profile.get("base_url") or "").strip()
                or os.environ.get(
                    "ERIS_REMOTE_BASE_URL",
                    "https://generativelanguage.googleapis.com/v1beta",
                ).strip()
            )
            model_name = (
                str(remote_profile.get("model") or "").strip()
                or str(remote_profile.get("model_name") or "").strip()
                or os.environ.get("ERIS_REMOTE_MODEL", "").strip()
                or os.environ.get("GEMINI_MODEL", "").strip()
                or "gemma-4-31b-it"
            )
            if not api_key:
                raise RuntimeError("Remote Gemini dang bat nhung chua co GEMINI_API_KEY hoac ERIS_REMOTE_API_KEY.")
            self.logger.info("Dung Gemini API tai %s voi model %s", base_url, model_name)
            try:
                return GeminiClient(base_url=base_url, api_key=api_key, model_name=model_name, key_pool=get_key_pool("gemini"))
            except ValueError as exc:
                raise RuntimeError(f"Loi API key Gemini: {exc}") from exc

        base_url = (
            str(remote_profile.get("base_url") or "").strip()
            or os.environ.get("ERIS_REMOTE_BASE_URL", "https://api-v2.shopaikey.com/v1").strip()
        )
        model_name = (
            str(remote_profile.get("model") or "").strip()
            or str(remote_profile.get("model_name") or "").strip()
            or os.environ.get("ERIS_REMOTE_MODEL", "gemini-3-flash-preview").strip()
        )
        if not api_key:
            raise RuntimeError("Remote API dang bat nhung chua co ERIS_REMOTE_API_KEY.")
        self.logger.info("Dung OpenAI-compatible API tai %s voi model %s", base_url, model_name)
        try:
            return OpenAICompatibleClient(
                base_url=base_url,
                api_key=api_key,
                model_name=model_name,
                key_pool=get_key_pool("groq"),
            )
        except ValueError as exc:
            raise RuntimeError(f"Loi API key remote: {exc}") from exc

    def _speech_api_requested(self) -> bool:
        apply_secrets_to_environ()
        if self._env_flag("ERIS_SPEECH_API_ENABLED", "0"):
            return True
        if get_secret("ERIS_SPEECH_API_KEY", "ERIS_STYLE_API_KEY", "OPENAI_SPEECH_API_KEY", "GEMINI_SPEECH_API_KEY"):
            return True
        if os.environ.get("ERIS_SPEECH_PROVIDER", "").strip():
            return True
        profile_provider = os.environ.get("ERIS_SPEECH_PROVIDER", os.environ.get("ERIS_REMOTE_PROVIDER", "gemini")).strip().lower()
        return bool(get_provider_profile(profile_provider, slot=os.environ.get("ERIS_SPEECH_SLOT", "speech")))

    def _build_speech_client(self):
        apply_secrets_to_environ()
        provider = os.environ.get("ERIS_SPEECH_PROVIDER", os.environ.get("ERIS_REMOTE_PROVIDER", "gemini")).strip().lower()
        slot = os.environ.get("ERIS_SPEECH_SLOT", "speech").strip() or "speech"
        profile = get_provider_profile(provider, slot=slot)
        api_key = (
            str(profile.get("api_key") or "").strip()
            or get_secret("ERIS_SPEECH_API_KEY", "ERIS_STYLE_API_KEY")
        )

        if provider == "gemini":
            api_key = api_key or get_secret("GEMINI_SPEECH_API_KEY", "GEMINI_API_KEY", "ERIS_REMOTE_API_KEY")
            base_url = (
                str(profile.get("base_url") or "").strip()
                or os.environ.get(
                    "ERIS_SPEECH_BASE_URL",
                    os.environ.get("ERIS_REMOTE_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
                ).strip()
            )
            model_name = (
                str(profile.get("model") or "").strip()
                or str(profile.get("model_name") or "").strip()
                or os.environ.get("ERIS_SPEECH_MODEL", "").strip()
                or os.environ.get("ERIS_REMOTE_MODEL", "").strip()
                or os.environ.get("GEMINI_MODEL", "").strip()
                or "gemma-4-31b-it"
            )
            if not api_key:
                raise RuntimeError("Speech Gemini dang bat nhung chua co ERIS_SPEECH_API_KEY hoac GEMINI_API_KEY.")
            self.logger.info("Dung Gemini speech API tai %s voi model %s", base_url, model_name)
            try:
                return GeminiClient(base_url=base_url, api_key=api_key, model_name=model_name, key_pool=get_key_pool("gemini"))
            except ValueError as exc:
                raise RuntimeError(f"Loi API key speech Gemini: {exc}") from exc

        api_key = api_key or get_secret("OPENAI_SPEECH_API_KEY", "ERIS_GROQ_API_KEY", "ERIS_REMOTE_API_KEY", "OPENAI_API_KEY")
        base_url = (
            str(profile.get("base_url") or "").strip()
            or os.environ.get("ERIS_SPEECH_BASE_URL", os.environ.get("ERIS_REMOTE_BASE_URL", "https://api.openai.com/v1")).strip()
        )
        model_name = (
            str(profile.get("model") or "").strip()
            or str(profile.get("model_name") or "").strip()
            or os.environ.get("ERIS_SPEECH_MODEL", "").strip()
            or os.environ.get("ERIS_REMOTE_MODEL", "gemma-4-31b-it").strip()
        )
        if not api_key:
            raise RuntimeError("Speech API dang bat nhung chua co ERIS_SPEECH_API_KEY.")
        self.logger.info("Dung OpenAI-compatible speech API tai %s voi model %s", base_url, model_name)
        try:
            return OpenAICompatibleClient(base_url=base_url, api_key=api_key, model_name=model_name, key_pool=get_key_pool("groq"))
        except ValueError as exc:
            raise RuntimeError(f"Loi API key speech remote: {exc}") from exc

    def build_client(self, *, model_path: str = "", n_ctx: int = 0, n_gpu_layers: int = 0):
        if not self._env_flag("ERIS_REMOTE_API_ENABLED", "1"):
            raise RuntimeError("Local model runtime da bi go bo; hay bat ERIS_REMOTE_API_ENABLED=1.")
        return self._build_remote_client()

    def build_style_client(self, *, model_path: str = "", n_ctx: int = 0, n_gpu_layers: int = 0):
        if self._speech_api_requested():
            return self._build_speech_client()
        return None

    def build_format_fallback_client(self, *, model_path: str = "", n_ctx: int = 0, n_gpu_layers: int = 0):
        """Build a Groq (OpenAI-compatible) client used to rescue chat/directive
        decisions when the main provider leaks chain-of-thought or breaks the JSON
        contract.

        Groq llama models honour `response_format=json_object` and stop the
        "think out loud then truncate" failure that gemma falls into on emotionally
        loaded prompts, so they make a reliable format-recovery trier. Returns None
        when disabled or when no Groq key is configured (caller degrades gracefully).
        """
        apply_secrets_to_environ()
        if not self._env_flag("ERIS_CHAT_FORMAT_FALLBACK_ENABLED", "1"):
            return None

        provider = os.environ.get(
            "ERIS_CHAT_FALLBACK_PROVIDER", "openai_compatible"
        ).strip().lower()
        slot = os.environ.get("ERIS_CHAT_FALLBACK_SLOT", "remote_main").strip() or "remote_main"
        profile = get_provider_profile(provider, slot=slot)

        # Ưu tiên key RIÊNG cho fallback (vd aggregator OpenAI-compatible: glm-4.5-flash)
        # để không ép xài key Groq. Nếu KHÔNG khai key riêng thì giữ NGUYÊN hành vi cũ:
        # xoay groq pool với llama-3.3-70b (không regression khi chưa điền aggregator).
        dedicated_key = get_secret("ERIS_CHAT_FALLBACK_API_KEY", "ERIS_AGGREGATOR_API_KEY")
        aggregator_base = (
            os.environ.get("ERIS_CHAT_FALLBACK_BASE_URL", "").strip()
            or get_secret("ERIS_AGGREGATOR_BASE_URL")
        )
        # Chỉ đi đường aggregator khi CÓ ĐỦ key + base_url. Thiếu base_url → quay về
        # Groq llama (tránh gửi tên model lạ như glm lên endpoint Groq gây lỗi).
        if dedicated_key and aggregator_base:
            api_key = dedicated_key
            pool = None  # aggregator dùng 1 key riêng, không xoay groq pool
            base_url = aggregator_base
            model_name = (
                os.environ.get("ERIS_CHAT_FALLBACK_MODEL", "").strip()
                or "glm-4.5-flash"
            )
        else:
            pool = get_key_pool("groq")
            pool_key = pool.current_key() if pool is not None else ""
            api_key = (
                str(profile.get("api_key") or "").strip()
                or pool_key
                or get_secret("ERIS_GROQ_API_KEY", "ERIS_REMOTE_API_KEY", "OPENAI_API_KEY")
            )
            if not api_key:
                self.logger.info("Chat format fallback (Groq) tat: khong tim thay ERIS_GROQ_API_KEY.")
                return None
            # Khi chưa có key aggregator, BỎ QUA override model/base_url để tránh gửi
            # tên model lạ (glm) lên endpoint Groq → giữ đúng llama-3.3-70b trên Groq.
            base_url = str(profile.get("base_url") or "").strip() or "https://api.groq.com/openai/v1"
            model_name = (
                str(profile.get("model") or "").strip()
                or str(profile.get("model_name") or "").strip()
                or "llama-3.3-70b-versatile"
            )

        if not api_key:
            self.logger.info("Chat format fallback tat: khong tim thay key.")
            return None

        self.logger.info("Chat format fallback san sang tai %s voi model %s", base_url, model_name)
        try:
            return OpenAICompatibleClient(
                base_url=base_url,
                api_key=api_key,
                model_name=model_name,
                key_pool=pool,
            )
        except ValueError as exc:
            self.logger.warning("Khong dung duoc chat format fallback: %s", exc)
            return None

    def build_vision_client(self, *, model_path: str = "", n_ctx: int = 0, n_gpu_layers: int = 0):
        return None

    def stop(self):
        return None


# Backward-compatible alias while older call sites are being cleaned up.
LlamaServerProcessManager = RemoteModelProcessManager
