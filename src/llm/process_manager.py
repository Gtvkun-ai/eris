import os

from eris_secrets import apply_secrets_to_environ, get_provider_profile, get_secret
from .client import GeminiClient, OpenAICompatibleClient, ChainedFallbackClient
from .deepseek import DEEPSEEK_BASE_URL, DEEPSEEK_DEFAULT_MODEL, DEEPSEEK_STRONG_MODEL, normalize_model
from .key_pool import get_key_pool
from .model_catalog import DEFAULT_OPEN_MODEL_ID
from .deepseek_workers import JsonlWorkerClient, load_worker_spec, normalize_worker_role


def _normalize_remote_provider(provider: str) -> str:
    value = str(provider or "").strip().lower()
    if value in {"", "deepseek"}:
        return "deepseek"
    if value in {"deepseek_web", "deepseek-web", "ds2api", "whale2api", "whale"}:
        return "deepseek_web"
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
        self._deepseek_worker_clients = {}

    def _env_flag(self, name: str, default: str = "0") -> bool:
        return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}

    def _explicit_env_flag(self, name: str) -> bool | None:
        raw = os.environ.get(name)
        if raw is None:
            return None
        value = raw.strip().lower()
        if not value:
            return None
        return value in {"1", "true", "yes", "on"}

    def _build_remote_client(self):
        apply_secrets_to_environ()
        provider = _normalize_remote_provider(os.environ.get("ERIS_REMOTE_PROVIDER", "deepseek"))
        remote_profile = get_provider_profile(provider, slot="remote_main")
        # Não chính có pool riêng, không dùng chung key với Gemini/Groq phụ.
        main_pool = get_key_pool("remote_main")
        main_pool_key = _bootstrap_pool_key(main_pool)

        if provider == "deepseek_web":
            # Explicit provider means exactly one semantic authority: the
            # companion worker behind Whale2API/DS2API. Never append an official
            # DeepSeek/Gemini/Groq API fallback behind it, otherwise a late
            # response can silently change model identity and contract behavior.
            client = self.build_deepseek_worker_client("companion", required=True)
            spec = load_worker_spec("companion")
            self.logger.info(
                "Dung DeepSeek Web lam semantic authority duy nhat: base=%s model=%s role=companion",
                spec.base_url,
                spec.model,
            )
            return client

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
                or DEFAULT_OPEN_MODEL_ID
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
            companion_spec = load_worker_spec("companion")
            ds2api_flag = self._explicit_env_flag("ERIS_DS2API_ENABLED")
            ds2api_enabled = companion_spec.configured if ds2api_flag is None else ds2api_flag
            if not api_key and not ds2api_enabled:
                raise RuntimeError(
                    "DeepSeek dang bat nhung chua co ERIS_DS_COMPANION_API_KEY, "
                    "DEEPSEEK_API_KEY hoac ERIS_REMOTE_API_KEY."
                )
            if model_name != configured_model.strip().lower():
                self.logger.warning("Model DeepSeek cu %s da duoc chuyen sang %s.", configured_model, model_name)

            if ds2api_enabled:
                primary_base_url = (
                    companion_spec.base_url
                    if companion_spec.api_key
                    else os.environ.get("ERIS_DS2API_BASE_URL", "http://localhost:6011/v1").strip()
                )
                primary_key = (
                    companion_spec.api_key
                    or get_secret(
                        "ERIS_DS2API_API_KEY",
                        "DEEPSEEK_API_KEY",
                        "ERIS_REMOTE_API_KEY",
                    )
                )
                primary_model = (
                    companion_spec.model
                    if companion_spec.api_key
                    else os.environ.get("ERIS_DS2API_MODEL", "deepseek-chat").strip()
                )
                if not primary_key:
                    raise RuntimeError(
                        "DS2API enabled nhung chua co ERIS_DS_COMPANION_API_KEY, "
                        "ERIS_DS2API_API_KEY, DEEPSEEK_API_KEY, hoac ERIS_REMOTE_API_KEY."
                    )
                try:
                    primary_client = self.build_deepseek_worker_client("companion")
                    if primary_client is None:
                        primary_client = OpenAICompatibleClient(
                            base_url=primary_base_url,
                            api_key=primary_key,
                            model_name=primary_model,
                            key_pool=None,
                        )
                    if not api_key:
                        self.logger.info(
                            "Dung DS2API (DeepSeek Web) lam main brain tai %s voi model %s; official fallback chua cau hinh.",
                            primary_base_url,
                            primary_model,
                        )
                        return primary_client
                    self.logger.info(
                        "Dung DS2API (DeepSeek Web) lam main brain tai %s voi model %s, fallback tai %s voi model %s",
                        primary_base_url,
                        primary_model,
                        base_url,
                        model_name,
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
            or os.environ.get("ERIS_REMOTE_MODEL", DEFAULT_OPEN_MODEL_ID).strip()
        )
        if not api_key:
            raise RuntimeError("Speech API dang bat nhung chua co ERIS_SPEECH_API_KEY.")
        self.logger.info("Dung OpenAI-compatible speech API tai %s voi model %s", base_url, model_name)
        try:
            return OpenAICompatibleClient(base_url=base_url, api_key=api_key, model_name=model_name, key_pool=get_key_pool("groq"))
        except ValueError as exc:
            raise RuntimeError(f"Loi API key speech remote: {exc}") from exc

    def build_deepseek_worker_client(self, role: str, *, required: bool = False):
        """Build/cache one DeepSeek Web worker selected by its gateway API key.

        Whale2API remains unchanged: each ``ERIS_DS_<ROLE>_API_KEY`` is simply
        used as the bearer token for the shared OpenAI-compatible endpoint.  In
        PoolUI that gateway key can be pinned to one account or one role-specific
        account pool.  Missing optional keys return ``None`` so legacy providers
        continue to work during incremental rollout.
        """

        apply_secrets_to_environ()
        ds2api_flag = self._explicit_env_flag("ERIS_DS2API_ENABLED")
        if ds2api_flag is False:
            if required:
                raise RuntimeError(
                    f"DeepSeek worker {normalize_worker_role(role)!r} bi tat boi ERIS_DS2API_ENABLED=0."
                )
            return None

        normalized = normalize_worker_role(role)
        cached = self._deepseek_worker_clients.get(normalized)
        if cached is not None:
            return cached

        spec = load_worker_spec(normalized)
        if not spec.configured:
            if required:
                raise RuntimeError(
                    f"DeepSeek worker {normalized!r} chua co {normalized.upper()} API key/base/model."
                )
            return None

        try:
            raw_client = OpenAICompatibleClient(
                base_url=spec.base_url,
                api_key=spec.api_key,
                model_name=spec.model,
                key_pool=None,
                provider_circuit_id=f"{spec.base_url.rstrip('/')}#deepseek_web:{normalized}",
            )
            client = JsonlWorkerClient(
                raw_client,
                role=normalized,
                jsonl_enabled=spec.jsonl_enabled,
                repair_attempts=spec.jsonl_repair_attempts,
            )
        except ValueError as exc:
            if required:
                raise RuntimeError(f"DeepSeek worker {normalized} khong hop le: {exc}") from exc
            self.logger.warning("Bo qua DeepSeek worker %s: %s", normalized, exc)
            return None

        self._deepseek_worker_clients[normalized] = client
        self.logger.info(
            "DeepSeek Web worker san sang: role=%s model=%s jsonl=%s base=%s",
            normalized,
            spec.model,
            int(spec.jsonl_enabled),
            spec.base_url,
        )
        return client

    def build_executive_client(self):
        """Dựng Executive Cortex luôn dùng DeepSeek, không dùng Gemini.

        Thứ tự ưu tiên:
        1. DeepSeek worker ``executive`` qua DS2API/Whale2API (nếu ERIS_DS_EXECUTIVE_API_KEY có).
        2. Official DeepSeek API (nếu ERIS_REMOTE_PROVIDER==deepseek và có DEEPSEEK_API_KEY).
        3. Degrade qua Subject Core (trả None) — không fallback sang Gemini.

        Để kích hoạt DeepSeek executive: set ERIS_DS_EXECUTIVE_API_KEY, hoặc
        đảm bảo ERIS_DS2API_ENABLED=1 với ERIS_DS2API_API_KEY đã có.
        """

        apply_secrets_to_environ()
        if not self._env_flag("ERIS_EXECUTIVE_CORTEX_ENABLED", "1"):
            return None

        provider = _normalize_remote_provider(os.environ.get("ERIS_REMOTE_PROVIDER", "deepseek"))
        executive_spec = load_worker_spec("executive")
        ds2api_flag = self._explicit_env_flag("ERIS_DS2API_ENABLED")
        # Luôn thử DeepSeek executive worker nếu nó đã được cấu hình, bất kể
        # provider chính là gì. Trước đây chỉ thử khi provider==deepseek*, dẫn
        # đến fall-through sang Gemini dù user đã set ERIS_DS_EXECUTIVE_API_KEY.
        ds2api_enabled = bool(
            executive_spec.configured
            or provider == "deepseek_web"
            or (
                provider == "deepseek"
                and (True if ds2api_flag is None else ds2api_flag)
            )
        )

        ds2api_client = None
        if ds2api_enabled:
            try:
                ds2api_client = self.build_deepseek_worker_client(
                    "executive",
                    required=(provider == "deepseek_web"),
                )
            except RuntimeError as exc:
                self.logger.warning(
                    "Executive DS2API worker khong san sang: %s; se thu official fallback neu co",
                    exc,
                )
            if ds2api_client is not None:
                self.logger.info(
                    "Executive Cortex san sang: DS2API primary role=executive model=%s base=%s",
                    getattr(ds2api_client, "model_name", executive_spec.model),
                    getattr(ds2api_client, "base_url", executive_spec.base_url),
                )

        # Official DeepSeek fallback. Không dùng một ERIS_REMOTE_BASE_URL local làm
        # "official fallback" vì như thế fallback chỉ quay lại đúng daemon vừa chết.
        official_client = None
        if provider in {"deepseek", "deepseek_web"}:
            model_name = os.environ.get("ERIS_EXECUTIVE_MODEL", DEEPSEEK_STRONG_MODEL).strip()
            api_key = get_secret("DEEPSEEK_API_KEY", "ERIS_REMOTE_API_KEY")
            executive_base = str(os.environ.get("ERIS_EXECUTIVE_BASE_URL", "") or "").strip()
            remote_base = str(os.environ.get("ERIS_REMOTE_BASE_URL", "") or "").strip()
            remote_lower = remote_base.lower()
            remote_is_local_ds2api = bool(
                remote_base
                and (
                    "localhost" in remote_lower
                    or "127.0.0.1" in remote_lower
                    or ":6011" in remote_lower
                    or ":6012" in remote_lower
                    or ":6013" in remote_lower
                    or ":6014" in remote_lower
                    or ":6015" in remote_lower
                    or ":6016" in remote_lower
                )
            )
            base_url = executive_base or (remote_base if remote_base and not remote_is_local_ds2api else DEEPSEEK_BASE_URL)
            if api_key:
                try:
                    raw_official = OpenAICompatibleClient(
                        base_url=base_url,
                        api_key=api_key,
                        model_name=model_name,
                        key_pool=None,
                        timeout=max(5, int(float(os.environ.get("ERIS_EXECUTIVE_TIMEOUT_S", "18") or 18))),
                    )
                    official_client = JsonlWorkerClient(
                        raw_official,
                        role="executive",
                        jsonl_enabled=True,
                        repair_attempts=1,
                    )
                except ValueError as exc:
                    self.logger.warning("Khong dung duoc DeepSeek official cho Executive Cortex: %s", exc)

        if ds2api_client is not None and official_client is not None:
            self.logger.info(
                "Executive Cortex route: DS2API primary -> Official DeepSeek fallback model=%s",
                getattr(official_client, "model_name", ""),
            )
            return ChainedFallbackClient([ds2api_client, official_client], logger=self.logger)
        if ds2api_client is not None:
            self.logger.info("Executive Cortex route: DS2API primary; official fallback chua cau hinh")
            return ds2api_client
        if official_client is not None:
            self.logger.info(
                "Executive Cortex san sang: Official DeepSeek model=%s",
                getattr(official_client, "model_name", ""),
            )
            return official_client
        if provider == "deepseek_web":
            self.logger.warning("Executive Cortex deepseek_web khong co worker kha dung; semantic path se degrade qua Subject Core.")
            return None

        # Không dùng Gemini làm fallback cho Executive nữa.
        # Nếu không có DeepSeek executive worker thì degrade qua Subject Core.
        # Để dùng DeepSeek executive: set ERIS_DS_EXECUTIVE_API_KEY (hoặc để
        # worker dùng chung key qua ERIS_DS2API_API_KEY với ERIS_DS2API_ENABLED=1).
        self.logger.warning(
            "Executive Cortex: khong tim duoc DeepSeek executive worker; "
            "autonomous se degrade qua Subject Core. "
            "De bat: set ERIS_DS_EXECUTIVE_API_KEY hoac dam bao ERIS_DS2API_ENABLED=1."
        )
        return None

    def build_inner_client(self):
        return self.build_deepseek_worker_client("inner")

    def build_diary_client(self):
        """Chọn một DeepSeek worker cho V80 Deep Reflection.

        V80 không dùng DeepSeek để điền 5 ô Inner Diary nữa. Worker này chỉ chạy
        thưa để tổng hợp pattern/lesson từ lịch sử Gemma thought-shard. Giữ tên
        ``diary_client`` để tương thích wiring cũ, khỏi đổi nửa repository chỉ vì
        con người cuối cùng cũng chịu phân công lao động hợp lý.
        """

        requested = str(os.environ.get("ERIS_INNER_DIARY_WORKER_ROLE", "inner") or "inner").strip().lower()
        try:
            normalized = normalize_worker_role(requested)
        except ValueError:
            self.logger.warning(
                "Inner Diary worker role khong hop le: %s; fallback ve inner",
                requested,
            )
            normalized = "inner"
        client = self.build_deepseek_worker_client(normalized)
        if client is not None:
            self.logger.info("Inner Diary Deep Reflection owner: DeepSeek worker role=%s", normalized)
        return client

    def build_residue_curator_client(self):
        """Dựng Gemma private lane cho Thought Shards + Residue Curator.

        Gemma nuôi 5 micro-thought live và gom/dedupe residue. Nó không có quyền
        public speech hay apply identity. Thiếu key thì residue vẫn retention theo
        deterministic fallback, còn 5 shard dùng raw-state fallback ở renderer.
        """
        apply_secrets_to_environ()
        if not self._env_flag("ERIS_PRIVATE_RESIDUE_CURATOR_ENABLED", "1"):
            return None
        provider = str(os.environ.get("ERIS_PRIVATE_RESIDUE_CURATOR_PROVIDER", "gemini") or "gemini").strip().lower()
        model_name = str(os.environ.get("ERIS_PRIVATE_RESIDUE_CURATOR_MODEL", DEFAULT_OPEN_MODEL_ID) or DEFAULT_OPEN_MODEL_ID).strip()

        if provider == "gemini":
            pool = get_key_pool("gemini")
            remote_provider = _normalize_remote_provider(os.environ.get("ERIS_REMOTE_PROVIDER", "deepseek"))
            api_key = get_secret("ERIS_PRIVATE_RESIDUE_CURATOR_API_KEY", "GEMINI_API_KEY") or _bootstrap_pool_key(pool)
            if not api_key and remote_provider == "gemini":
                api_key = get_secret("ERIS_REMOTE_API_KEY")
            if not api_key:
                self.logger.info(
                    "Gemma private lane chua co key; residue retention + raw diary fallback van hoat dong."
                )
                return None
            base_url = str(os.environ.get(
                "ERIS_PRIVATE_RESIDUE_CURATOR_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta",
            ) or "https://generativelanguage.googleapis.com/v1beta").strip()
            try:
                client = GeminiClient(
                    base_url=base_url,
                    api_key=api_key,
                    model_name=model_name,
                    key_pool=get_key_pool("gemini"),
                )
                self.logger.info("Gemma Thought-Shards/Residue san sang: model=%s", model_name)
                return client
            except ValueError as exc:
                self.logger.warning("Khong dung duoc Gemma Residue Curator: %s", exc)
                return None

        # Có thể override sang OpenAI-compatible cho deployment riêng, nhưng
        # không có implicit fallback: user yêu cầu một curator rõ owner.
        base_url = str(os.environ.get("ERIS_PRIVATE_RESIDUE_CURATOR_BASE_URL", "") or "").strip()
        api_key = get_secret("ERIS_PRIVATE_RESIDUE_CURATOR_API_KEY")
        if not (base_url and api_key and model_name):
            self.logger.info("Residue Curator provider=%s chua du cau hinh.", provider)
            return None
        try:
            client = OpenAICompatibleClient(
                base_url=base_url,
                api_key=api_key,
                model_name=model_name,
                key_pool=None,
                provider_circuit_id=f"{base_url.rstrip('/')}#residue_curator",
            )
            self.logger.info("Residue Curator san sang: provider=%s model=%s", provider, model_name)
            return client
        except ValueError as exc:
            self.logger.warning("Khong dung duoc Residue Curator: %s", exc)
            return None

    def build_seed_client(self):
        """Dựng worker ``seed`` riêng cho premise chạy nền.

        Role này mặc định trỏ DS2API port 6015 và không fallback sang companion
        hay surface. Thiếu worker thì reservoir tắt, autonomous chỉ im khi không
        có topic cụ thể thay vì kéo một lane khác đi làm hộ.
        """

        client = self.build_deepseek_worker_client("seed")
        if client is None:
            self.logger.warning(
                "Seed worker chua cau hinh; random-chat reservoir se tat. "
                "Kiem tra ERIS_DS_SEED_BASE_URL/API_KEY va DS2API port 6015."
            )
        else:
            self.logger.info("Seed worker owner: background associative mental-material generator")
        return client

    def build_surface_client(self):
        """Dựng worker ``surface`` chỉ để viết public wording đã được duyệt."""

        client = self.build_deepseek_worker_client("surface")
        if client is None:
            self.logger.warning(
                "Surface worker chua cau hinh; autonomous wording se body-only. "
                "Kiem tra DS2API key/base/model."
            )
        else:
            self.logger.info("Surface worker owner: public wording only")
        return client

    def build_curator_client(self):
        """Worker chuyên trách dọn dẹp Memory và tổng hợp Identity."""
        return self.build_deepseek_worker_client("curator")

    def build_research_client(self):
        # Retired lane. Keep the method as a compatibility shim so old startup
        # paths do not fail, but do not alias research to curator/main.
        return None

    def build_tutor_client(self):
        """Retired lane: semantic tutor no longer owns a DeepSeek account pool."""
        return None

    def build_coding_client(self):
        """Build the dedicated remote coding brain.

        Coding is a first-class ownership lane, not an alias to companion, critic,
        escalation, WebAI or another agent runtime. If this lane is not configured, the coding
        Agent Harness stays unavailable instead of silently changing model owner.

        Configuration (highest precedence first):
        - providers.<provider>.coding in secrets.json
        - ERIS_CODING_* environment variables
        - provider-specific official API credentials

        ``ERIS_CODING_PROVIDER`` defaults to ``ERIS_REMOTE_PROVIDER``.  A
        ``deepseek_web`` companion configuration is intentionally translated to
        official ``deepseek`` for this lane; localhost endpoints are rejected by
        default so a web/session sidecar cannot become the coding authority by
        accident.
        """
        apply_secrets_to_environ()
        if not self._env_flag("ERIS_CODING_ENABLED", "1"):
            return None

        raw_remote_provider = os.environ.get("ERIS_REMOTE_PROVIDER", "deepseek").strip().lower() or "deepseek"
        remote_provider = _normalize_remote_provider(raw_remote_provider)
        configured_provider = os.environ.get("ERIS_CODING_PROVIDER", "").strip().lower()
        raw_provider = configured_provider or raw_remote_provider
        provider = _normalize_remote_provider(raw_provider)
        if provider == "deepseek_web":
            provider = "deepseek"

        slot = os.environ.get("ERIS_CODING_SLOT", "coding").strip() or "coding"
        # Secrets files tend to use human/provider names (e.g. ``openai``), while
        # runtime normalization may call the same protocol ``openai_compatible``.
        # Try the literal provider first so a dedicated ``providers.openai.coding``
        # profile is never made invisible by transport normalization.
        profile = get_provider_profile(raw_provider, slot=slot)
        if not profile and raw_provider != provider:
            profile = get_provider_profile(provider, slot=slot)
        explicit_base = str(profile.get("base_url") or "").strip() or os.environ.get("ERIS_CODING_BASE_URL", "").strip()
        explicit_model = (
            str(profile.get("model") or "").strip()
            or str(profile.get("model_name") or "").strip()
            or os.environ.get("ERIS_CODING_MODEL", "").strip()
        )
        explicit_key = str(profile.get("api_key") or "").strip() or get_secret("ERIS_CODING_API_KEY")

        def _reject_local(base_url: str) -> bool:
            allow_local = self._env_flag("ERIS_CODING_ALLOW_LOCAL", "0")
            lowered = str(base_url or "").strip().lower()
            return (not allow_local) and any(token in lowered for token in ("localhost", "127.0.0.1", "0.0.0.0"))

        try:
            if provider == "gemini":
                base_url = explicit_base or "https://generativelanguage.googleapis.com/v1beta"
                model_name = (
                    explicit_model
                    or (os.environ.get("ERIS_REMOTE_MODEL", "").strip() if remote_provider == "gemini" else "")
                    or os.environ.get("GEMINI_MODEL", "").strip()
                    or "gemini-2.5-pro"
                )
                api_key = explicit_key or get_secret("GEMINI_API_KEY")
                if not api_key and remote_provider == "gemini":
                    api_key = get_secret("ERIS_REMOTE_API_KEY")
                if not api_key:
                    self.logger.info("Coding brain tat: chua co ERIS_CODING_API_KEY/GEMINI_API_KEY.")
                    return None
                if _reject_local(base_url):
                    self.logger.warning("Coding brain tu choi local endpoint: %s", base_url)
                    return None
                client = GeminiClient(base_url=base_url, api_key=api_key, model_name=model_name, key_pool=None)

            elif provider == "deepseek":
                base_url = explicit_base or DEEPSEEK_BASE_URL
                model_name = normalize_model(explicit_model or DEEPSEEK_STRONG_MODEL)
                api_key = explicit_key or get_secret("DEEPSEEK_API_KEY")
                if not api_key and remote_provider == "deepseek":
                    api_key = get_secret("ERIS_REMOTE_API_KEY")
                if not api_key:
                    self.logger.info("Coding brain tat: chua co ERIS_CODING_API_KEY/DEEPSEEK_API_KEY.")
                    return None
                if _reject_local(base_url):
                    self.logger.warning("Coding brain tu choi local endpoint: %s", base_url)
                    return None
                client = OpenAICompatibleClient(
                    base_url=base_url, api_key=api_key, model_name=model_name, key_pool=None,
                    provider_circuit_id=f"{base_url.rstrip('/')}#coding",
                )

            else:
                # Generic remote OpenAI-compatible coding lane.  Require an
                # explicit model to avoid silently inheriting a cheap chat model.
                base_url = explicit_base or (
                    "https://api.openai.com/v1" if provider == "openai_compatible" and raw_provider == "openai" else
                    (os.environ.get("ERIS_REMOTE_BASE_URL", "").strip() if provider == remote_provider else "")
                )
                model_name = explicit_model or (
                    os.environ.get("ERIS_REMOTE_MODEL", "").strip() if provider == remote_provider else ""
                )
                api_key = explicit_key or get_secret("OPENAI_API_KEY")
                if provider == remote_provider:
                    api_key = api_key or get_secret("ERIS_REMOTE_API_KEY")
                if not base_url or not model_name or not api_key:
                    self.logger.info(
                        "Coding brain tat: provider=%s can ERIS_CODING_BASE_URL, ERIS_CODING_MODEL va ERIS_CODING_API_KEY.",
                        provider,
                    )
                    return None
                if _reject_local(base_url):
                    self.logger.warning("Coding brain tu choi local endpoint: %s", base_url)
                    return None
                client = OpenAICompatibleClient(
                    base_url=base_url, api_key=api_key, model_name=model_name, key_pool=None,
                    provider_circuit_id=f"{base_url.rstrip('/')}#coding",
                )
        except (RuntimeError, ValueError) as exc:
            self.logger.warning("Khong dung duoc coding brain provider=%s: %s", provider, exc)
            return None

        self.logger.info(
            "Coding brain official API san sang: provider=%s model=%s base=%s",
            provider, getattr(client, "model_name", model_name), getattr(client, "base_url", base_url),
        )
        return client

    def build_client(self, *, model_path: str = "", n_ctx: int = 0, n_gpu_layers: int = 0):
        if not self._env_flag("ERIS_REMOTE_API_ENABLED", "1"):
            raise RuntimeError("Local model runtime da bi go bo; hay bat ERIS_REMOTE_API_ENABLED=1.")
        return self._build_remote_client()

    def build_style_client(self, *, model_path: str = "", n_ctx: int = 0, n_gpu_layers: int = 0):
        # "style" is a runtime surface/repair capability, not a separate
        # account owner. Route it through critic so users only manage one
        # correction/format/style pool.
        worker = self.build_deepseek_worker_client("critic")
        if worker is not None:
            return worker
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
        critic_worker = self.build_deepseek_worker_client("critic")
        if critic_worker is not None:
            chain.append(critic_worker)

        if _normalize_remote_provider(os.environ.get("ERIS_REMOTE_PROVIDER", "deepseek")) == "deepseek_web":
            if critic_worker is None:
                self.logger.info(
                    "DeepSeek Web format fallback tat: khong co critic worker; khong tu chen provider API khac."
                )
                return None
            self.logger.info(
                "DeepSeek Web format fallback dung critic worker cung gateway; external API fallback bi khoa."
            )
            return critic_worker

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
        worker = self.build_deepseek_worker_client("observer")
        if worker is not None:
            return worker
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
        worker = self.build_deepseek_worker_client("critic")
        if worker is not None:
            return worker
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
        worker = self.build_deepseek_worker_client("observer")
        if worker is not None:
            return worker
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

        critic_worker = self.build_deepseek_worker_client("critic")
        if critic_worker is not None:
            return critic_worker

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
        separate multimodal endpoint with ERIS_VISION_API_* or use the Groq
        vision default when ERIS_GROQ_API_KEY is available.
        """
        apply_secrets_to_environ()
        raw_mode = os.environ.get("ERIS_VISION_API_ENABLED", "auto").strip().lower()
        # "auto" thực sự phải là auto: nếu có cấu hình/key multimodal thì dựng
        # client; chỉ các giá trị tắt rõ ràng mới vô hiệu hóa vision API.
        if raw_mode in {"0", "false", "no", "off", "disabled"}:
            return None

        provider = os.environ.get("ERIS_VISION_API_PROVIDER", os.environ.get("ERIS_VISION_PROVIDER", "")).strip().lower()
        base_url = os.environ.get("ERIS_VISION_API_BASE_URL", "").strip()
        model_name = os.environ.get("ERIS_VISION_API_MODEL", "").strip()
        groq_requested = (
            provider == "groq"
            or "api.groq.com" in base_url.lower()
            or model_name.startswith("qwen/")
        )
        groq_default = not base_url and not get_secret("ERIS_VISION_API_KEY") and get_secret("ERIS_GROQ_API_KEY")
        if groq_requested or groq_default:
            base_url = base_url or os.environ.get("ERIS_GROQ_BASE_URL", "https://api.groq.com/openai/v1").strip()
            if not model_name or (groq_default and model_name.startswith("gpt-")):
                model_name = os.environ.get("ERIS_GROQ_VISION_MODEL", "qwen/qwen3.6-27b").strip()
            pool = get_key_pool("groq")
            api_key = (
                get_secret("ERIS_VISION_API_KEY")
                or _bootstrap_pool_key(pool)
                or get_secret("ERIS_GROQ_API_KEY")
            )
        else:
            pool = None
            api_key = get_secret("ERIS_VISION_API_KEY")
        if not (api_key and base_url and model_name):
            self.logger.info(
                "Vision API tat: can ERIS_VISION_API_* hoac ERIS_GROQ_API_KEY cho Groq vision."
            )
            return None

        self.logger.info("Dung vision API rieng tai %s voi model %s", base_url, model_name)
        try:
            return OpenAICompatibleClient(
                base_url=base_url,
                api_key=api_key,
                model_name=model_name,
                key_pool=pool,
            )
        except ValueError as exc:
            self.logger.warning("Khong dung duoc vision API: %s", exc)
            return None

    def stop(self):
        return None


# Backward-compatible alias while older call sites are being cleaned up.
LlamaServerProcessManager = RemoteModelProcessManager
