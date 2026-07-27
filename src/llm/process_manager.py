import os

from eris_secrets import apply_secrets_to_environ, get_provider_profile, get_secret
from .client import GeminiClient, OpenAICompatibleClient, ChainedFallbackClient
from .deepseek import DEEPSEEK_BASE_URL, DEEPSEEK_DEFAULT_MODEL, DEEPSEEK_STRONG_MODEL, normalize_model
from .key_pool import get_key_pool


def _normalize_remote_provider(provider: str) -> str:
    value = str(provider or "").strip().lower()
    if value in {"", "deepseek"}:
        return "deepseek"
    if value in {"openai", "compatible"}:
        return "openai_compatible"
    return value


def _bootstrap_pool_key(pool) -> str:
    """Lấy key duy nhất để dựng client; request thật vẫn lease trong client."""
    if pool is None:
        return ""
    try:
        lease = pool.acquire(allow_cooling=True)
        return lease.key if lease is not None else ""
    except Exception:
        return ""

class RemoteModelProcessManager:
    def __init__(self, *, logger, project_root: str):
        self.logger = logger
        self.project_root = project_root

    def _env_flag(self, name: str, default: str = "0") -> bool:
        return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}

    def _build_remote_client(self):
        apply_secrets_to_environ()
        provider = _normalize_remote_provider(os.environ.get("ERIS_REMOTE_PROVIDER", "deepseek"))
        remote_profile = get_provider_profile(provider, slot="remote_main")
        # Não chính có pool riêng, không dùng chung key với Gemini/Groq phụ.
        main_pool = get_key_pool("remote_main")
        main_pool_key = _bootstrap_pool_key(main_pool)

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
            api_key = (
                str(remote_profile.get("api_key") or "").strip()
                or main_pool_key
                or get_secret("ERIS_REMOTE_API_KEY", "GEMINI_API_KEY")
            )
            if not api_key:
                raise RuntimeError("Remote Gemini dang bat nhung chua co GEMINI_API_KEY hoac ERIS_REMOTE_API_KEY.")
            self.logger.info("Dung Gemini API tai %s voi model %s", base_url, model_name)
            try:
                return GeminiClient(base_url=base_url, api_key=api_key, model_name=model_name, key_pool=main_pool)
            except ValueError as exc:
                raise RuntimeError(f"Loi API key Gemini: {exc}") from exc

        if provider == "deepseek":
            base_url = (
                str(remote_profile.get("base_url") or "").strip()
                or os.environ.get("ERIS_REMOTE_BASE_URL", DEEPSEEK_BASE_URL).strip()
            )
            configured_model = (
                str(remote_profile.get("model") or "").strip()
                or str(remote_profile.get("model_name") or "").strip()
                or os.environ.get("ERIS_REMOTE_MODEL", DEEPSEEK_DEFAULT_MODEL).strip()
            )
            model_name = normalize_model(configured_model)
            client_model_name = configured_model
            api_key = (
                str(remote_profile.get("api_key") or "").strip()
                or main_pool_key
                or get_secret("DEEPSEEK_API_KEY", "ERIS_REMOTE_API_KEY")
            )
            if not api_key:
                raise RuntimeError("DeepSeek dang bat nhung chua co DEEPSEEK_API_KEY hoac ERIS_REMOTE_API_KEY.")
            if model_name != configured_model.strip().lower():
                self.logger.warning("Model DeepSeek cu %s da duoc chuyen sang %s.", configured_model, model_name)

            ds2api_enabled = os.environ.get("ERIS_DS2API_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
            if ds2api_enabled:
                primary_base_url = os.environ.get("ERIS_DS2API_BASE_URL", "http://localhost:6011/v1").strip()
                primary_key = get_secret("ERIS_DS2API_API_KEY", "DEEPSEEK_API_KEY", "ERIS_REMOTE_API_KEY")
                primary_model = os.environ.get("ERIS_DS2API_MODEL", "deepseek-chat").strip()
                if not primary_key:
                    raise RuntimeError("DS2API enabled nhung chua co ERIS_DS2API_API_KEY, DEEPSEEK_API_KEY, hoac ERIS_REMOTE_API_KEY.")
                self.logger.info(
                    "Dung DS2API (DeepSeek Web) lam main brain tai %s voi model %s, fallback tai %s voi model %s",
                    primary_base_url,
                    primary_model,
                    base_url,
                    model_name,
                )
                try:
                    primary_client = OpenAICompatibleClient(
                        base_url=primary_base_url,
                        api_key=primary_key,
                        model_name=primary_model,
                        key_pool=None,
                    )
                    fallback_client = OpenAICompatibleClient(
                        base_url=base_url,
                        api_key=api_key,
                        model_name=model_name,
                        key_pool=main_pool,
                    )
                    return ChainedFallbackClient([primary_client, fallback_client], logger=self.logger)
                except ValueError as exc:
                    raise RuntimeError(f"Loi API key remote deepseek chain: {exc}") from exc

            self.logger.info("Dung DeepSeek API tai %s voi model %s", base_url, model_name)
        else:
            base_url = (
                str(remote_profile.get("base_url") or "").strip()
                or os.environ.get("ERIS_REMOTE_BASE_URL", "https://api.openai.com/v1").strip()
            )
            model_name = (
                str(remote_profile.get("model") or "").strip()
                or str(remote_profile.get("model_name") or "").strip()
                or os.environ.get("ERIS_REMOTE_MODEL", "gpt-4o-mini").strip()
            )
            is_groq_remote = provider == "groq" or "api.groq.com" in base_url.lower()
            if is_groq_remote:
                api_key = (
                    str(remote_profile.get("api_key") or "").strip()
                    or main_pool_key
                    or get_secret("ERIS_REMOTE_API_KEY", "ERIS_GROQ_API_KEY", "OPENAI_API_KEY")
                )
            else:
                api_key = (
                    str(remote_profile.get("api_key") or "").strip()
                    or main_pool_key
                    or get_secret("ERIS_REMOTE_API_KEY", "OPENAI_API_KEY")
                )
            if not api_key:
                raise RuntimeError("Remote API dang bat nhung chua co ERIS_REMOTE_API_KEY hoac provider API key.")
            self.logger.info("Dung OpenAI-compatible API tai %s voi model %s", base_url, model_name)
            client_model_name = model_name
        pool = main_pool
        try:
            return OpenAICompatibleClient(
                base_url=base_url,
                api_key=api_key,
                model_name=client_model_name,
                key_pool=pool,
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
            remote_provider = os.environ.get("ERIS_REMOTE_PROVIDER", "").strip().lower()
            remote_base_url = os.environ.get("ERIS_REMOTE_BASE_URL", "").strip()
            remote_model = os.environ.get("ERIS_REMOTE_MODEL", "").strip()
            remote_is_gemini = remote_provider == "gemini" or "generativelanguage.googleapis.com" in remote_base_url.lower()

            api_key = api_key or get_secret("GEMINI_SPEECH_API_KEY", "GEMINI_API_KEY")
            if not api_key and remote_is_gemini:
                api_key = get_secret("ERIS_REMOTE_API_KEY")
            base_url = (
                str(profile.get("base_url") or "").strip()
                or os.environ.get(
                    "ERIS_SPEECH_BASE_URL",
                    remote_base_url if remote_is_gemini and remote_base_url else "https://generativelanguage.googleapis.com/v1beta",
                ).strip()
            )
            model_name = (
                str(profile.get("model") or "").strip()
                or str(profile.get("model_name") or "").strip()
                or os.environ.get("ERIS_SPEECH_MODEL", "").strip()
                or os.environ.get("GEMINI_MODEL", "").strip()
                or (remote_model if remote_is_gemini and remote_model else "")
                or "gemini-2.5-flash"
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
        """Build an optional format-recovery chain without the retired aggregator.

        A dedicated OpenAI-compatible fallback is used only when the user
        explicitly supplies ERIS_CHAT_FALLBACK_BASE_URL and API key. Groq and
        Gemini remain optional secondary providers when their own keys exist.
        """
        apply_secrets_to_environ()
        if not self._env_flag("ERIS_CHAT_FORMAT_FALLBACK_ENABLED", "1"):
            return None

        chain = []
        fallback_base = os.environ.get("ERIS_CHAT_FALLBACK_BASE_URL", "").strip()
        fallback_key = get_secret("ERIS_CHAT_FALLBACK_API_KEY")
        fallback_model = os.environ.get("ERIS_CHAT_FALLBACK_MODEL", "").strip()
        if fallback_base and fallback_key and fallback_model:
            pool = get_key_pool("groq") if "api.groq.com" in fallback_base.lower() else None
            try:
                chain.append(
                    OpenAICompatibleClient(
                        base_url=fallback_base,
                        api_key=fallback_key,
                        model_name=fallback_model,
                        key_pool=pool,
                    )
                )
            except ValueError as exc:
                self.logger.warning("Bo qua fallback OpenAI-compatible: %s", exc)

        groq_key = get_secret("ERIS_GROQ_API_KEY")
        if groq_key and not any("api.groq.com" in str(getattr(c, "base_url", "")).lower() for c in chain):
            try:
                groq_pool = get_key_pool("groq")
                chain.append(
                    OpenAICompatibleClient(
                        base_url=os.environ.get("ERIS_GROQ_BASE_URL", "https://api.groq.com/openai/v1").strip(),
                        api_key=_bootstrap_pool_key(groq_pool) or groq_key,
                        model_name=os.environ.get("ERIS_CHAT_GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant").strip(),
                        key_pool=groq_pool,
                    )
                )
            except ValueError as exc:
                self.logger.warning("Bo qua fallback Groq: %s", exc)

        remote_provider = _normalize_remote_provider(os.environ.get("ERIS_REMOTE_PROVIDER", "deepseek"))
        remote_base_url = os.environ.get("ERIS_REMOTE_BASE_URL", "").strip().lower()
        remote_is_gemini = remote_provider == "gemini" or "generativelanguage.googleapis.com" in remote_base_url
        gemini_key = get_secret("GEMINI_API_KEY", "ERIS_SPEECH_API_KEY")
        if not gemini_key and remote_is_gemini:
            gemini_key = get_secret("ERIS_REMOTE_API_KEY")
        if gemini_key:
            try:
                chain.append(
                    GeminiClient(
                        base_url="https://generativelanguage.googleapis.com/v1beta",
                        api_key=gemini_key,
                        model_name="gemini-2.5-flash",
                        key_pool=get_key_pool("gemini"),
                    )
                )
            except Exception as exc:
                self.logger.warning("Bo qua fallback Gemini: %s", exc)

        if not chain:
            self.logger.info("Chat fallback tat: khong co provider phu duoc cau hinh.")
            return None
        if len(chain) == 1:
            self.logger.info("Chat fallback 1 tang: %s", getattr(chain[0], "model_name", "?"))
            return chain[0]
        self.logger.info(
            "Chat fallback chain: %s",
            " -> ".join(str(getattr(c, "model_name", "?")) for c in chain),
        )
        return ChainedFallbackClient(chain, logger=self.logger)


    def _build_groq_social_client(self, *, model_name: str, enabled_env: str):
        """Dựng lane Groq riêng cho social parser/critic.

        Lane dùng chung key pool Groq nhưng tách model, nên parser 8B không vô tình
        chạy Qwen 32B và ngược lại. Không có key thì trả None, runtime deterministic
        vẫn hoạt động bình thường.
        """
        apply_secrets_to_environ()
        if not self._env_flag(enabled_env, "1"):
            return None
        pool = get_key_pool("groq")
        api_key = _bootstrap_pool_key(pool) or get_secret("ERIS_GROQ_API_KEY")
        if not api_key:
            return None
        base_url = os.environ.get("ERIS_GROQ_BASE_URL", "https://api.groq.com/openai/v1").strip()
        try:
            return OpenAICompatibleClient(
                base_url=base_url,
                api_key=api_key,
                model_name=model_name,
                key_pool=pool,
            )
        except ValueError as exc:
            self.logger.warning("Không dựng được social lane %s: %s", model_name, exc)
            return None

    def build_social_parser_client(self):
        model = (
            os.environ.get("ERIS_SOCIAL_OBSERVER_MODEL")
            or os.environ.get("ERIS_SOCIAL_PARSER_MODEL")
            or "llama-3.1-8b-instant"
        ).strip()
        client = self._build_groq_social_client(
            model_name=model,
            enabled_env="ERIS_SOCIAL_OBSERVER_ENABLED",
        )
        if client is not None:
            self.logger.info("Social parser client sẵn sàng: %s", model)
        return client

    def build_social_critic_client(self):
        model = (
            os.environ.get("ERIS_SOCIAL_OBSERVER_DEEP_MODEL")
            or os.environ.get("ERIS_SOCIAL_CRITIC_MODEL")
            or "llama-3.3-70b-versatile"
        ).strip()
        client = self._build_groq_social_client(
            model_name=model,
            enabled_env="ERIS_SOCIAL_OBSERVER_DEEP_ENABLED",
        )
        if client is not None:
            self.logger.info("Social deliberator/critic client sẵn sàng: %s", model)
        return client

    def build_social_fallback_client(self):
        model = os.environ.get("ERIS_SOCIAL_OBSERVER_FALLBACK_MODEL", "llama-3.1-8b-instant").strip()
        client = self._build_groq_social_client(
            model_name=model,
            enabled_env="ERIS_SOCIAL_OBSERVER_FALLBACK_ENABLED",
        )
        if client is not None:
            self.logger.info("Social observer fallback client sẵn sàng: %s", model)
        return client

    def build_escalation_client(self, *, model_path: str = "", n_ctx: int = 0, n_gpu_layers: int = 0):
        """Build a DEDICATED "strong" client cho self-critique escalation (bái sư).

        Khi câu nháp do model rẻ sinh ra bị chấm điểm thấp / cần tool, runtime chạy
        lại cả lượt trên client này. Chỉ build khi có cấu hình RIÊNG
        (ERIS_ESCALATION_PROVIDER / ERIS_ESCALATION_MODEL). Nếu không khai, trả None
        và LlmService tự dùng format-fallback client (đã là model mạnh hơn). Tắt hẳn
        bằng ERIS_ESCALATION_ENABLED=0.
        """
        apply_secrets_to_environ()
        if not self._env_flag("ERIS_ESCALATION_ENABLED", "1"):
            return None

        provider = os.environ.get("ERIS_ESCALATION_PROVIDER", "").strip().lower()
        model_name = os.environ.get("ERIS_ESCALATION_MODEL", "").strip()
        base_url = os.environ.get("ERIS_ESCALATION_BASE_URL", "").strip()
        # DeepSeek companion routing needs a real Pro client without forcing the
        # user to duplicate configuration.  Reuse the official endpoint and the
        # same DeepSeek key unless an explicit escalation provider overrides it.
        if not provider and not model_name:
            main_provider = _normalize_remote_provider(
                os.environ.get("ERIS_REMOTE_PROVIDER", "deepseek")
            )
            if main_provider != "deepseek":
                return None
            provider = "deepseek"
            model_name = DEEPSEEK_STRONG_MODEL
            base_url = os.environ.get("ERIS_REMOTE_BASE_URL", DEEPSEEK_BASE_URL).strip()

        provider = provider or "deepseek"
        api_key = get_secret(
            "ERIS_ESCALATION_API_KEY",
            "ERIS_CHAT_FALLBACK_API_KEY",
        )

        if provider == "gemini":
            api_key = api_key or get_secret("GEMINI_API_KEY", "ERIS_REMOTE_API_KEY")
            base_url = base_url or "https://generativelanguage.googleapis.com/v1beta"
            model_name = model_name or "gemini-2.5-flash"
            if not api_key:
                self.logger.info("Escalation client tat: khong tim thay key Gemini.")
                return None
            self.logger.info("Escalation client (Gemini) san sang tai %s voi model %s", base_url, model_name)
            try:
                return GeminiClient(base_url=base_url, api_key=api_key, model_name=model_name, key_pool=get_key_pool("gemini"))
            except ValueError as exc:
                self.logger.warning("Khong dung duoc escalation client: %s", exc)
                return None

        if provider == "deepseek":
            api_key = api_key or get_secret("DEEPSEEK_API_KEY", "ERIS_REMOTE_API_KEY")
            base_url = base_url or DEEPSEEK_BASE_URL
            model_name = normalize_model(model_name or DEEPSEEK_STRONG_MODEL)
        else:
            api_key = api_key or get_secret("ERIS_GROQ_API_KEY", "ERIS_REMOTE_API_KEY", "OPENAI_API_KEY")
            base_url = base_url or ("https://api.groq.com/openai/v1" if provider == "groq" else "https://api.openai.com/v1")
            model_name = model_name or ("llama-3.3-70b-versatile" if provider == "groq" else "gpt-4o-mini")
        if not api_key:
            self.logger.info("Escalation client tat: khong tim thay key.")
            return None
        self.logger.info("Escalation client san sang tai %s voi model %s", base_url, model_name)
        try:
            return OpenAICompatibleClient(
                base_url=base_url,
                api_key=api_key,
                model_name=model_name,
                key_pool=None,
            )
        except ValueError as exc:
            self.logger.warning("Khong dung duoc escalation client: %s", exc)
            return None

    def build_vision_client(self, *, model_path: str = "", n_ctx: int = 0, n_gpu_layers: int = 0):
        """Build an explicitly configured remote vision client.

        DeepSeek's current public Chat Completions API is text-only, so the main
        DeepSeek credential is never reused for image captioning. Configure a
        separate multimodal endpoint with ERIS_VISION_API_* or keep local vision.
        """
        apply_secrets_to_environ()
        raw_mode = os.environ.get("ERIS_VISION_API_ENABLED", "0").strip().lower()
        if raw_mode in {"", "0", "false", "no", "off", "auto"}:
            return None

        api_key = get_secret("ERIS_VISION_API_KEY")
        base_url = os.environ.get("ERIS_VISION_API_BASE_URL", "").strip()
        model_name = os.environ.get("ERIS_VISION_API_MODEL", "").strip()
        if not (api_key and base_url and model_name):
            self.logger.info(
                "Vision API tat: can du ERIS_VISION_API_KEY, ERIS_VISION_API_BASE_URL va ERIS_VISION_API_MODEL."
            )
            return None

        self.logger.info("Dung vision API rieng tai %s voi model %s", base_url, model_name)
        try:
            return OpenAICompatibleClient(
                base_url=base_url,
                api_key=api_key,
                model_name=model_name,
                key_pool=None,
            )
        except ValueError as exc:
            self.logger.warning("Khong dung duoc vision API: %s", exc)
            return None

    def stop(self):
        return None


# Backward-compatible alias while older call sites are being cleaned up.
LlamaServerProcessManager = RemoteModelProcessManager
