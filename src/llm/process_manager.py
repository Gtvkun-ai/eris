import os

from eris_secrets import apply_secrets_to_environ, get_provider_profile, get_secret
from .client import GeminiClient, OpenAICompatibleClient


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
                or "gemma-4-26b-a4b-it"
            )
            if not api_key:
                raise RuntimeError("Remote Gemini dang bat nhung chua co GEMINI_API_KEY hoac ERIS_REMOTE_API_KEY.")
            self.logger.info("Dung Gemini API tai %s voi model %s", base_url, model_name)
            try:
                return GeminiClient(base_url=base_url, api_key=api_key, model_name=model_name)
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
                or "gemma-4-26b-a4b-it"
            )
            if not api_key:
                raise RuntimeError("Speech Gemini dang bat nhung chua co ERIS_SPEECH_API_KEY hoac GEMINI_API_KEY.")
            self.logger.info("Dung Gemini speech API tai %s voi model %s", base_url, model_name)
            try:
                return GeminiClient(base_url=base_url, api_key=api_key, model_name=model_name)
            except ValueError as exc:
                raise RuntimeError(f"Loi API key speech Gemini: {exc}") from exc

        api_key = api_key or get_secret("OPENAI_SPEECH_API_KEY", "ERIS_REMOTE_API_KEY", "OPENAI_API_KEY")
        base_url = (
            str(profile.get("base_url") or "").strip()
            or os.environ.get("ERIS_SPEECH_BASE_URL", os.environ.get("ERIS_REMOTE_BASE_URL", "https://api.openai.com/v1")).strip()
        )
        model_name = (
            str(profile.get("model") or "").strip()
            or str(profile.get("model_name") or "").strip()
            or os.environ.get("ERIS_SPEECH_MODEL", "").strip()
            or os.environ.get("ERIS_REMOTE_MODEL", "gemma-4-26b-a4b-it").strip()
        )
        if not api_key:
            raise RuntimeError("Speech API dang bat nhung chua co ERIS_SPEECH_API_KEY.")
        self.logger.info("Dung OpenAI-compatible speech API tai %s voi model %s", base_url, model_name)
        try:
            return OpenAICompatibleClient(base_url=base_url, api_key=api_key, model_name=model_name)
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

    def build_vision_client(self, *, model_path: str = "", n_ctx: int = 0, n_gpu_layers: int = 0):
        return None

    def stop(self):
        return None


# Backward-compatible alias while older call sites are being cleaned up.
LlamaServerProcessManager = RemoteModelProcessManager
