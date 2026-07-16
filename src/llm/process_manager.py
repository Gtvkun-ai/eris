import os

from eris_secrets import apply_secrets_to_environ, get_provider_profile, get_secret
from .client import GeminiClient, OpenAICompatibleClient, ChainedFallbackClient
from .key_pool import get_key_pool


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
        provider = os.environ.get("ERIS_REMOTE_PROVIDER", "gemini").strip().lower()
        remote_profile = get_provider_profile(provider, slot="remote_main")

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
                or get_secret("ERIS_REMOTE_API_KEY", "GEMINI_API_KEY")
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
        is_groq_remote = provider == "groq" or "api.groq.com" in base_url.lower()
        pool = get_key_pool("groq") if is_groq_remote else None
        pool_key = _bootstrap_pool_key(pool) if pool is not None else ""
        if is_groq_remote:
            api_key = (
                str(remote_profile.get("api_key") or "").strip()
                or pool_key
                or get_secret("ERIS_GROQ_API_KEY", "ERIS_REMOTE_API_KEY", "OPENAI_API_KEY")
            )
        else:
            api_key = (
                str(remote_profile.get("api_key") or "").strip()
                or get_secret("ERIS_REMOTE_API_KEY", "ERIS_AGGREGATOR_API_KEY", "OPENAI_API_KEY")
            )
        if not api_key:
            raise RuntimeError("Remote API dang bat nhung chua co ERIS_REMOTE_API_KEY/ERIS_AGGREGATOR_API_KEY.")
        self.logger.info("Dung OpenAI-compatible API tai %s voi model %s", base_url, model_name)
        try:
            return OpenAICompatibleClient(
                base_url=base_url,
                api_key=api_key,
                model_name=model_name,
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

        # Opt-in: quay lại MỘT aggregator đơn (vd shopaikey gpt-4o-mini) khi cần,
        # bằng ERIS_CHAT_FALLBACK_FORCE_AGGREGATOR=1. Mặc định TẮT → đi chuỗi free.
        if self._env_flag("ERIS_CHAT_FALLBACK_FORCE_AGGREGATOR", "0"):
            dedicated_key = get_secret("ERIS_CHAT_FALLBACK_API_KEY", "ERIS_AGGREGATOR_API_KEY")
            base_url = (
                os.environ.get("ERIS_CHAT_FALLBACK_BASE_URL", "").strip()
                or get_secret("ERIS_AGGREGATOR_BASE_URL")
            )
            model_name = os.environ.get("ERIS_CHAT_FALLBACK_MODEL", "").strip() or "gpt-4o-mini"
            if dedicated_key and base_url:
                try:
                    self.logger.info("Chat fallback (aggregator) tai %s model %s", base_url, model_name)
                    return OpenAICompatibleClient(
                        base_url=base_url, api_key=dedicated_key, model_name=model_name, key_pool=None
                    )
                except ValueError as exc:
                    self.logger.warning("Khong dung duoc aggregator fallback: %s", exc)
                    return None

        # ── Chuỗi dự phòng cho chat: shopaikey aggregator hoặc Groq.
        chain = []

        agg_base = (
            os.environ.get("ERIS_CHAT_FALLBACK_BASE_URL", "").strip()
            or get_secret("ERIS_AGGREGATOR_BASE_URL")
        )
        is_groq = "groq" in agg_base.lower()
        if is_groq:
            pool = get_key_pool("groq")
            agg_key = get_secret("ERIS_CHAT_FALLBACK_API_KEY") or _bootstrap_pool_key(pool)
        else:
            pool = None
            agg_key = get_secret("ERIS_CHAT_FALLBACK_API_KEY", "ERIS_AGGREGATOR_API_KEY")

        if agg_key and agg_base:
            agg_model = os.environ.get("ERIS_CHAT_FALLBACK_MODEL", "").strip() or "gpt-4o-mini"
            try:
                chain.append(
                    OpenAICompatibleClient(base_url=agg_base, api_key=agg_key, model_name=agg_model, key_pool=pool)
                )
            except ValueError as exc:
                self.logger.warning("Bo qua tang fallback: %s", exc)

        remote_provider = os.environ.get("ERIS_REMOTE_PROVIDER", "").strip().lower()
        remote_base_url = os.environ.get("ERIS_REMOTE_BASE_URL", "").strip().lower()
        remote_is_gemini = remote_provider == "gemini" or "generativelanguage.googleapis.com" in remote_base_url
        gemini_key = get_secret("GEMINI_API_KEY") or get_secret("ERIS_SPEECH_API_KEY")
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
                self.logger.warning("Bo qua tang fallback Gemini: %s", exc)

        if not chain:
            self.logger.info("Chat fallback tat: khong tim thay key Groq/Gemini.")
            return None
        if len(chain) == 1:
            self.logger.info("Chat fallback 1 tang: %s", getattr(chain[0], "model_name", "?"))
            return chain[0]
        self.logger.info(
            "Chat fallback chain: %s",
            " -> ".join(str(getattr(c, "model_name", "?")) for c in chain),
        )
        return ChainedFallbackClient(chain, logger=self.logger)

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
        # Không khai cấu hình riêng -> để None, LlmService reuse fallback client.
        if not provider and not model_name:
            return None

        provider = provider or "openai_compatible"
        api_key = get_secret(
            "ERIS_ESCALATION_API_KEY",
            "ERIS_CHAT_FALLBACK_API_KEY",
            "ERIS_AGGREGATOR_API_KEY",
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

        api_key = api_key or get_secret("ERIS_GROQ_API_KEY", "ERIS_REMOTE_API_KEY", "OPENAI_API_KEY")
        base_url = base_url or get_secret("ERIS_AGGREGATOR_BASE_URL") or "https://api.groq.com/openai/v1"
        model_name = model_name or "gpt-4o-mini"
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
        """Build client vision REMOTE (OpenAI-compatible, vd shopaikey grok-3-image)
        thay cho captioner moondream local. Bat bang ERIS_VISION_API_ENABLED=1.

        Key/base_url mac dinh dung aggregator (shopaikey) da co san trong secrets:
        ERIS_AGGREGATOR_API_KEY + ERIS_AGGREGATOR_BASE_URL. Co the override rieng
        bang ERIS_VISION_API_KEY / ERIS_VISION_API_BASE_URL / ERIS_VISION_API_MODEL.
        Tra None khi tat hoac thieu key (caller degrade ve vision local/caption cu).
        """
        apply_secrets_to_environ()
        if not self._env_flag("ERIS_VISION_API_ENABLED", "0"):
            return None

        api_key = get_secret(
            "ERIS_VISION_API_KEY",
            "ERIS_AGGREGATOR_API_KEY",
            "ERIS_CHAT_FALLBACK_API_KEY",
            "ERIS_REMOTE_API_KEY",
        )
        base_url = (
            os.environ.get("ERIS_VISION_API_BASE_URL", "").strip()
            or get_secret("ERIS_AGGREGATOR_BASE_URL")
            or "https://api.shopaikey.com/v1"
        )
        model_name = os.environ.get("ERIS_VISION_API_MODEL", "").strip() or "grok-3-image"
        if not api_key:
            self.logger.info(
                "Vision API tat: khong tim thay key (ERIS_VISION_API_KEY/ERIS_AGGREGATOR_API_KEY)."
            )
            return None

        self.logger.info("Dung vision API tai %s voi model %s", base_url, model_name)
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
