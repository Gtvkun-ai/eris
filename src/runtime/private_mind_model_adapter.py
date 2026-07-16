# -*- coding: utf-8 -*-
"""
runtime/private_mind_model_adapter.py
=====================================

Adapter API cho private mind:
- evaluate_fragment(evaluator_name, dossier)
- synthesize_judgment(dossier, fragments)

Adapter nÃ y Æ°u tiÃªn dÃ¹ng `llm_service` náº¿u Ä‘Æ°á»£c inject tá»« coordinator; náº¿u khÃ´ng
thÃ¬ cá»‘ build provider tá»« env giá»‘ng cÃ¡c adapter runtime khÃ¡c. Khi API há»ng, nÃ³
tráº£ None Ä‘á»ƒ rule fallback cháº¡y tiáº¿p. Ná»™i tÃ¢m khÃ´ng nÃªn cháº¿t vÃ¬ HTTP 500, tuy tháº¿
cÅ©ng Ä‘á»«ng biáº¿n HTTP 500 thÃ nh thÆ¡.
"""

from __future__ import annotations

import json
import os
import re
import socket
import time
import requests
import requests.exceptions
from ast import literal_eval
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from cortex.private_mind.contracts import EvidenceDossier, ThoughtFragment, compact_text, to_plain
from eris_secrets import apply_secrets_to_environ, get_secret
from llm.client import GeminiClient, OpenAICompatibleClient
from llm.key_pool import get_key_pool


def _env_flag(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off", "none"}


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _classify_transport_exception(exc: Exception) -> str:
    """PhÃ¢n loáº¡i exception thÃ nh 'transient' hoáº·c 'fixed_config'.

    Quy táº¯c (theo *kiá»ƒu* vÃ  *status*, khÃ´ng theo message):
    - requests.HTTPError / exception cÃ³ .response.status_code:
        429, 5xx (500-599) â†’ 'transient'
        4xx khÃ¡c (400, 401, 403...) â†’ 'fixed_config'
    - requests.exceptions.Timeout / ReadTimeout / ConnectTimeout / ConnectionError â†’ 'transient'
    - urllib.error.HTTPError: dÃ¹ng .code cÃ¹ng quy táº¯c status
    - urllib.error.URLError / socket.timeout / TimeoutError â†’ 'transient'
    - Máº·c Ä‘á»‹nh (khÃ´ng nháº­n diá»‡n) â†’ 'fixed_config' (an toÃ n: khÃ´ng retry vÃ´ cá»›)
    """
    # requests.HTTPError vá»›i .response (hoáº·c báº¥t ká»³ exception cÃ³ .response.status_code)
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            status = int(response.status_code)
            if status == 429 or 500 <= status <= 599:
                return "transient"
            return "fixed_config"
        except Exception:
            pass

    # requests timeout / connection errors
    if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        return "transient"

    # stdlib timeout vÃ  OSError (ECONNRESET, ETIMEDOUT, v.v.)
    if isinstance(exc, (socket.timeout, TimeoutError, OSError)):
        return "transient"

    return "fixed_config"


@dataclass(slots=True, frozen=True)
class PrivateMindModelAdapterConfig:
    enabled: bool = field(default_factory=lambda: _env_flag("ERIS_PRIVATE_MIND_API_ENABLED", False))
    provider: str = field(default_factory=lambda: str(os.getenv("ERIS_PRIVATE_MIND_PROVIDER", os.getenv("ERIS_DAYDREAM_PROVIDER", "gemini")) or "gemini").strip().lower())
    model: str = field(default_factory=lambda: str(os.getenv("ERIS_PRIVATE_MIND_MODEL", os.getenv("ERIS_DAYDREAM_MODEL", "gemma-4-31b-it")) or "gemma-4-31b-it").strip())
    base_url: str = field(default_factory=lambda: str(os.getenv("ERIS_PRIVATE_MIND_BASE_URL", os.getenv("ERIS_REMOTE_BASE_URL", "")) or "").strip())
    api_key: str = field(default_factory=lambda: str(os.getenv("ERIS_PRIVATE_MIND_API_KEY", "") or "").strip())
    timeout_seconds: float = field(default_factory=lambda: max(4.0, _as_float(os.getenv("ERIS_PRIVATE_MIND_TIMEOUT", "12"), 12.0)))
    # T1.3: synthesis/judgment náº·ng hÆ¡n fragment â†’ timeout dÃ i hÆ¡n (máº·c Ä‘á»‹nh 20s
    # hoáº·c â‰¥ timeout chung). Fragment váº«n fail-fast báº±ng timeout_seconds (12s).
    synthesis_timeout_seconds: float = field(
        default_factory=lambda: max(
            _as_float(os.getenv("ERIS_PRIVATE_MIND_TIMEOUT", "12"), 12.0),
            _as_float(os.getenv("ERIS_PRIVATE_MIND_SYNTHESIS_TIMEOUT", "20"), 20.0),
        )
    )
    # Nhiá»‡t Ä‘á»™ tháº¥p khiáº¿n model nhá» (gemma) dá»… láº·p tá»« hoáº·c dÃ­nh RECITATION filter,
    # rá»“i tráº£ output cá»¥t/rá»—ng -> invalid_json. Äá»ƒ máº·c Ä‘á»‹nh áº¥m hÆ¡n Ä‘á»ƒ phÃ¡ vÃ²ng láº·p.
    temperature: float = field(default_factory=lambda: _as_float(os.getenv("ERIS_PRIVATE_MIND_TEMPERATURE", "0.5"), 0.5))
    max_tokens_fragment: int = field(default_factory=lambda: max(128, int(os.getenv("ERIS_PRIVATE_MIND_FRAGMENT_TOKENS", "700") or 700)))
    max_tokens_judgment: int = field(default_factory=lambda: max(256, int(os.getenv("ERIS_PRIVATE_MIND_JUDGMENT_TOKENS", "900") or 900)))
    max_tokens_diary: int = field(default_factory=lambda: max(256, int(os.getenv("ERIS_INNER_DIARY_AI_TOKENS", "640") or 640)))
    transient_max_retries: int = field(default_factory=lambda: max(0, int(os.getenv("ERIS_PRIVATE_MIND_TRANSIENT_RETRIES", "1") or 1)))
    transient_backoff_base: float = field(default_factory=lambda: max(0.1, _as_float(os.getenv("ERIS_PRIVATE_MIND_TRANSIENT_BACKOFF", "0.5"), 0.5)))
    transient_cooldown_threshold: int = field(default_factory=lambda: max(1, int(os.getenv("ERIS_PRIVATE_MIND_TRANSIENT_THRESHOLD", "2") or 2)))
    transient_cooldown_seconds: float = field(default_factory=lambda: max(5.0, _as_float(os.getenv("ERIS_PRIVATE_MIND_TRANSIENT_COOLDOWN", "60"), 60.0)))
    # Free-text mode cho fragment: model nhá» (local) chá»‰ nháº£ Má»˜T cÃ¢u nghÄ© ngáº¯n,
    # KHÃ”NG Ã©p JSON-schema. TrÃ¡nh vÃ²ng invalid_json â†’ cooldown lÃ m cÃ¢m model nhá».
    freetext_fragments: bool = field(default_factory=lambda: _env_flag("ERIS_PRIVATE_MIND_FRAGMENT_FREETEXT", False))

    @classmethod
    def fragment_overlay_from_env(cls, base: "PrivateMindModelAdapterConfig") -> "PrivateMindModelAdapterConfig":
        """Config riÃªng cho fragment: náº¿u khai ERIS_PRIVATE_MIND_FRAGMENT_PROVIDER thÃ¬
        trá» fragment sang má»™t provider local (vd Ollama qwen3) + báº­t free-text;
        náº¿u khÃ´ng khai gÃ¬ thÃ¬ dÃ¹ng chung config (giá»¯ hÃ nh vi cÅ©)."""
        provider = str(os.getenv("ERIS_PRIVATE_MIND_FRAGMENT_PROVIDER", "") or "").strip().lower()
        if not provider:
            return base
        base_url = str(os.getenv("ERIS_PRIVATE_MIND_FRAGMENT_BASE_URL", "") or "").strip()
        model = str(os.getenv("ERIS_PRIVATE_MIND_FRAGMENT_MODEL", "") or "").strip() or base.model
        # Chá»‰ provider LOCAL má»›i dÃ¹ng placeholder "local-no-key". Provider remote
        # (gemini/openaiâ€¦) pháº£i Ä‘á»ƒ trá»‘ng â†’ adapter tá»± láº¥y key tháº­t tá»« key-pool/secret;
        # náº¿u nhÃ©t "local-no-key" lÃªn Gemini sáº½ bá»‹ 400 API_KEY_INVALID.
        api_key = str(os.getenv("ERIS_PRIVATE_MIND_FRAGMENT_API_KEY", "") or "").strip()
        if not api_key and provider == "ollama":
            api_key = "local-no-key"
        return replace(
            base,
            enabled=True,
            provider=provider,
            base_url=base_url,
            model=model,
            api_key=api_key,
            freetext_fragments=_env_flag("ERIS_PRIVATE_MIND_FRAGMENT_FREETEXT", True),
        )


@dataclass(slots=True)
class PrivateMindModelResult:
    ok: bool
    parsed: dict[str, Any] = field(default_factory=dict)
    content: str = ""
    error: str = ""
    error_kind: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class RuntimePrivateMindModelAdapter:
    """Adapter chung cho 4 mini-evaluator vÃ  GemmaInnerSynthesizer."""

    def __init__(self, *, config: PrivateMindModelAdapterConfig | None = None, llm_service: Any = None, logger: Any = None) -> None:
        self.config = config or PrivateMindModelAdapterConfig()
        self.llm_service = llm_service
        self.logger = logger
        self._provider_client: Any | None = None
        self._calls = 0
        self._ok_calls = 0
        self._failed_calls = 0
        self._total_latency_ms = 0.0
        self._total_tokens = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._last_error = ""
        self._last_call_at = 0.0
        self._invalid_json_streak = 0
        self._json_cooldown_until = 0.0
        self._transient_streak = 0
        self._transient_cooldown_until = 0.0
        self._last_error_kind = ""
        # Synthesis-specific streak: fragment success khÃ´ng reset streak nÃ y.
        self._synthesis_invalid_json_streak = 0
        self._synthesis_json_cooldown_until = 0.0
        # Key rotation: pool theo ÄÃšNG provider cá»§a private_mind (geminiâ†’pool
        # Gemini, groqâ†’pool Groq), tÃ¡ch báº¡ch Ä‘á»ƒ cháº¡y song song vá»›i máº¡ch khÃ¡c.
        self._key_pool = get_key_pool(self.config.provider)

    def _current_api_key(self) -> str:
        """Tráº£ API key hiá»‡n táº¡i. Æ¯u tiÃªn config (test), rá»“i pool chung, rá»“i env."""
        lease = self._key_pool.acquire(allow_cooling=True) if self._key_pool is not None else None
        pool_key = lease.key if lease is not None else ""
        return (
            self.config.api_key
            or pool_key
            or get_secret("ERIS_PRIVATE_MIND_API_KEY", "ERIS_REMOTE_API_KEY", "GEMINI_API_KEY")
        )

    def _rotate_to_next_key(self) -> bool:
        """Xoay pool chung sang key káº¿. Tráº£ True náº¿u xoay Ä‘Æ°á»£c (pool cÃ³ >1 key)."""
        if self._key_pool is None:
            return False
        rotated = self._key_pool.rotate()
        if rotated:
            self._provider_client = None  # force rebuild vá»›i key má»›i
            self._log("warning", "[PrivateMind API] rotating shared key pool -> index=%d", self._key_pool.index())
        return rotated

    @classmethod
    def from_env(cls, *, llm_service: Any = None, logger: Any = None) -> "RuntimePrivateMindModelAdapter | None":
        apply_secrets_to_environ()
        config = PrivateMindModelAdapterConfig()
        if not config.enabled:
            return None
        adapter = cls(config=config, llm_service=llm_service, logger=logger)
        adapter._log("info", "[PrivateMind API] ready provider=%s model=%s", config.provider, config.model)
        return adapter

    @classmethod
    def diary_fallback_from_env(cls, *, logger: Any = None) -> "RuntimePrivateMindModelAdapter | None":
        """Adapter Dá»° PHÃ’NG riÃªng cho Inner Diary.

        DÃ¹ng khi provider chÃ­nh (Gemini gemma) cháº¿t / lá»—i JSON: diary nháº£y sang má»™t
        model OpenAI-compatible tráº£ phÃ­ (vd qwen-plus-character qua aggregator) Ä‘á»ƒ
        khÃ´ng bá»‹ cÃ¢m. Tráº£ None náº¿u chÆ°a khai Ä‘á»§ (model + base_url + key) â†’ khi Ä‘Ã³
        InnerDiaryWriter cháº¡y y nhÆ° cÅ© (khÃ´ng regression).
        """
        apply_secrets_to_environ()
        if not _env_flag("ERIS_INNER_DIARY_FALLBACK", False):
            return None
        provider = str(os.getenv("ERIS_INNER_DIARY_FALLBACK_PROVIDER", "openai_compatible") or "openai_compatible").strip().lower()
        model = str(os.getenv("ERIS_INNER_DIARY_FALLBACK_MODEL", "") or "").strip()
        base_url = (
            str(os.getenv("ERIS_INNER_DIARY_FALLBACK_BASE_URL", "") or "").strip()
            or get_secret("ERIS_AGGREGATOR_BASE_URL")
        )
        api_key = get_secret("ERIS_INNER_DIARY_FALLBACK_API_KEY", "ERIS_AGGREGATOR_API_KEY")
        if not (model and base_url and api_key):
            return None
        config = PrivateMindModelAdapterConfig(
            enabled=True,
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
        )
        adapter = cls(config=config, llm_service=None, logger=logger)
        adapter._log("info", "[InnerDiary fallback] ready provider=%s model=%s", provider, model)
        return adapter

    @property
    def min_interval_seconds(self) -> float:
        return 0.0

    def evaluate_fragment(self, evaluator_name: str, dossier: EvidenceDossier) -> Mapping[str, Any] | None:
        if getattr(self.config, "freetext_fragments", False):
            return self._freetext_fragment(evaluator_name, dossier)
        messages = self._fragment_messages(evaluator_name, dossier)
        result = self._tracked_chat_json(
            messages,
            max_tokens=self.config.max_tokens_fragment,
            response_schema=self._fragment_response_schema(evaluator_name),
        )
        if not result.ok:
            if result.error not in {"invalid_json_cooldown", "transient_cooldown"}:
                self._log("warning", "[PrivateMind API] fragment failed evaluator=%s error=%s", evaluator_name, result.error)
            return None
        parsed = dict(result.parsed)
        parsed.setdefault("source", evaluator_name)
        parsed.setdefault("provider", self.config.provider)
        parsed.setdefault("model", self.config.model)
        # Schema pháº³ng tráº£ `theme` á»Ÿ top-level; downstream Ä‘á»c metadata.theme.
        theme = str(parsed.pop("theme", "") or "").strip()
        if theme:
            metadata = dict(parsed.get("metadata") or {})
            metadata.setdefault("theme", theme)
            parsed["metadata"] = metadata
        return parsed

    # ------------------------------------------------------------------
    # Free-text fragment path (cho model nhá» local: khÃ´ng Ã©p JSON-schema)
    # ------------------------------------------------------------------

    def _freetext_fragment(self, evaluator_name: str, dossier: EvidenceDossier) -> Mapping[str, Any] | None:
        """Sinh Má»˜T máº£nh suy nghÄ© ngáº¯n dáº¡ng vÄƒn xuÃ´i, rá»“i guard + bá»c thÃ nh fragment.

        KhÃ´ng parse JSON nÃªn model nhá» khÃ´ng cháº¿t vÃ¬ format. Output rÃ¡c bá»‹ guard
        loáº¡i â†’ tráº£ None Ä‘á»ƒ rule fallback cháº¡y."""
        messages = self._freetext_fragment_messages(evaluator_name, dossier)
        result = self._tracked_chat_text(messages, max_tokens=self.config.max_tokens_fragment)
        if not result.ok:
            if result.error not in {"invalid_json_cooldown", "transient_cooldown"}:
                self._log("info", "[PrivateMind local] fragment empty/transient evaluator=%s error=%s", evaluator_name, result.error)
            return None
        claim = self._guard_freetext_fragment(result.content)
        if not claim:
            self._log("info", "[PrivateMind local] fragment rejected by guard evaluator=%s", evaluator_name)
            return None
        return self._wrap_freetext_fragment(evaluator_name, claim, dossier)

    def _freetext_fragment_messages(self, evaluator_name: str, dossier: EvidenceDossier) -> list[dict[str, str]]:
        focus = {
            "intent_evaluator": "Ã½ Ä‘á»‹nh hiá»‡n táº¡i cá»§a báº¡n hoáº·c cá»§a há»‡ thá»‘ng",
            "memory_resonance_evaluator": "má»™t thÃ³i quen hoáº·c láº§n sá»­a lá»—i cá»§a báº¡n Ä‘ang láº·p láº¡i",
            "risk_and_permission_evaluator": "má»™t rá»§i ro riÃªng tÆ°, lá»™ thÃ´ng tin hoáº·c vÆ°á»£t quyá»n",
            "future_bias_evaluator": "thiÃªn hÆ°á»›ng hÃ nh vi sáº¯p tá»›i cá»§a tÃ´i",
            "user_model_evaluator": "Ä‘iá»u tÃ´i vá»«a hiá»ƒu thÃªm vá» con ngÆ°á»i báº¡n",
        }.get(evaluator_name, "tÃ¬nh huá»‘ng ná»™i tÃ¢m hiá»‡n táº¡i")
        slicer_name = self._DOSSIER_SLICERS.get(evaluator_name)
        evidence_slice = getattr(self, slicer_name)(dossier) if slicer_name else self._slim_dossier(dossier)
        meta = dossier.metadata if isinstance(dossier.metadata, dict) else {}
        recent_thoughts = meta.get("recent_thoughts") or []
        if recent_thoughts:
            evidence_slice = dict(evidence_slice)
            evidence_slice["suy_nghi_gan_day"] = recent_thoughts
        user_content = json.dumps(to_plain(evidence_slice), ensure_ascii=False)
        if len(user_content) > 3000:
            user_content = user_content[:3000]
        return [
            {
                "role": "system",
                "content": (
                    "/no_think\n"
                    "Báº¡n lÃ  má»™t máº£nh suy nghÄ© ná»™i tÃ¢m thoÃ¡ng qua cá»§a Eris â€” KHÃ”NG nÃ³i vá»›i ngÆ°á»i dÃ¹ng. "
                    f"Dá»±a trÃªn Dá»® KIá»†N ngÆ°á»i dÃ¹ng Ä‘Æ°a, viáº¿t Má»˜T cÃ¢u NHáº¬N Äá»ŠNH cá»¥ thá»ƒ vá»: {focus}. "
                    "YÃªu cáº§u: tiáº¿ng Viá»‡t, dÆ°á»›i 30 tá»«, ngÃ´i thá»© nháº¥t ('tÃ´i'), gá»i ngÆ°á»i dÃ¹ng lÃ  'báº¡n'. "
                    "TUYá»†T Äá»I KHÃ”NG láº·p láº¡i Ä‘á» bÃ i, KHÃ”NG há»i ngÆ°á»£c, KHÃ”NG viáº¿t cÃ¢u há»i, "
                    "KHÃ”NG JSON/markdown/giáº£i thÃ­ch. Chá»‰ má»™t cÃ¢u kháº³ng Ä‘á»‹nh rÃºt ra tá»« dá»¯ kiá»‡n. "
                    "Náº¿u dá»¯ kiá»‡n khÃ´ng Ä‘á»§ Ä‘á»ƒ nÃ³i gÃ¬ cá»¥ thá»ƒ, tráº£ Ä‘Ãºng chá»¯: KHONG."
                ),
            },
            {"role": "user", "content": f"Dá»® KIá»†N:\n{user_content}"},
        ]

    def _guard_freetext_fragment(self, content: str) -> str:
        """Guard local ráº»: lÃ m sáº¡ch + loáº¡i output rÃ¡c. Tráº£ claim sáº¡ch hoáº·c '' náº¿u loáº¡i."""
        text = str(content or "")
        # qwen3 vÃ  cÃ¡c model 'thinking' hay chÃ¨n <think>...</think> â€” bá» sáº¡ch.
        text = re.sub(r"<think>.*?</think>", " ", text, flags=re.S | re.I)
        text = re.sub(r"</?think>", " ", text, flags=re.I)
        # Bá» rÃ o markdown / fence / nhÃ£n vai.
        text = self._strip_markdown_fences(text)
        text = re.sub(r"^\s*(assistant|system|user|eris)\s*[:ï¼š]\s*", "", text, flags=re.I)
        # Gom láº·p vÃ´ háº¡n rá»“i nÃ©n khoáº£ng tráº¯ng; láº¥y cÃ¢u Ä‘áº§u tiÃªn.
        text = self._collapse_repetition(text)
        text = " ".join(text.split()).strip().strip('"â€œâ€\'`')
        if not text:
            return ""
        # Cáº¯t cÃ²n má»™t cÃ¢u (Ä‘áº¿n dáº¥u cháº¥m/!/? Ä‘áº§u tiÃªn náº¿u cÃ¢u dÃ i).
        first = re.split(r"(?<=[.!?â€¦])\s+", text, maxsplit=1)[0].strip()
        if 12 <= len(first) <= 240:
            text = first
        text = compact_text(text, 240)
        low = text.lower()
        # Sentinel "KHONG" = model tá»± nháº­n khÃ´ng Ä‘á»§ dá»¯ kiá»‡n Ä‘á»ƒ nÃ³i â†’ bá», Ä‘á»ƒ rule fallback.
        if low.strip(" .!").startswith("khong") and len(text) <= 8:
            return ""
        # CÃ¢u há»i = thÆ°á»ng lÃ  nháº¡i Ä‘á» bÃ i ("...theo hÆ°á»›ng nÃ o?"), khÃ´ng pháº£i nháº­n Ä‘á»‹nh.
        if text.endswith("?") or text.endswith("ï¼Ÿ"):
            return ""
        # Loáº¡i JSON/dump, rÃ² schema/prompt, lá»i tá»« chá»‘i, thuyáº¿t minh meta.
        leak_markers = (
            '{', '}', '":', "evidence_id", "schema", "json", "```",
            "as an ai", "language model", "tÃ´i khÃ´ng thá»ƒ", "i cannot", "i can't",
            "system prompt", "dÆ°á»›i Ä‘Ã¢y lÃ ", "here is", "here's",
        )
        if any(m in low for m in leak_markers):
            return ""
        # Pháº£i cÃ³ chá»¯ tháº­t (khÃ´ng pháº£i toÃ n kÃ½ hiá»‡u/sá»‘).
        if not re.search(r"[a-zA-ZÃ€-á»¹]", text):
            return ""
        # Má»™t cÃ¢u ná»™i tÃ¢m quÃ¡ ngáº¯n (<12 kÃ½ tá»±) thÆ°á»ng lÃ  rÃ¡c.
        if len(text) < 12:
            return ""
        return text

    def _wrap_freetext_fragment(self, evaluator_name: str, claim: str, dossier: EvidenceDossier) -> dict[str, Any]:
        evidence_ids = [str(x) for x in (dossier.evidence_ids or ())][:6]
        fragment: dict[str, Any] = {
            "source": evaluator_name,
            "claim": claim,
            # Free-text lÃ  suy nghÄ© má»m: confidence vá»«a pháº£i, Ä‘á»ƒ judgment/decay lá»c tiáº¿p.
            "confidence": 0.45,
            "pressure": 0.3,
            "evidence_ids": evidence_ids,
            "suggested_question": "",
            "provider": self.config.provider,
            "model": self.config.model,
            "metadata": {"theme": evaluator_name.replace("_evaluator", ""), "freetext": True},
        }
        if evaluator_name == "user_model_evaluator":
            fragment["metadata"]["facet"] = "general"
        return fragment

    def _tracked_chat_text(self, messages: list[dict[str, str]], *, max_tokens: int) -> PrivateMindModelResult:
        """NhÆ° _tracked_chat_json nhÆ°ng KHÃ”NG parse JSON: content rá»—ng/transient = fail."""
        if self._transient_cooldown_active():
            self._last_error = "transient_cooldown"
            self._last_error_kind = "transient"
            return PrivateMindModelResult(ok=False, error="transient_cooldown", error_kind="transient")
        started = time.time()
        result = self._chat_text_with_transient_retry(messages, max_tokens=max_tokens, temperature=max(0.4, self.config.temperature))
        self._calls += 1
        self._total_latency_ms += (time.time() - started) * 1000.0
        self._last_call_at = time.time()
        if result.ok:
            self._ok_calls += 1
            self._last_error = ""
            self._last_error_kind = ""
            self._transient_streak = 0
            self._transient_cooldown_until = 0.0
        else:
            self._failed_calls += 1
            self._last_error = result.error
            self._last_error_kind = result.error_kind
            if result.error_kind == "transient":
                self._transient_streak += 1
                self._maybe_enter_transient_cooldown()
        usage = self._extract_usage(result.raw)
        self._prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
        self._completion_tokens += int(usage.get("completion_tokens", 0) or 0)
        self._total_tokens += int(usage.get("total_tokens", 0) or 0)
        return result

    def _chat_text_with_transient_retry(self, messages: list[dict[str, str]], *, max_tokens: int, temperature: float) -> PrivateMindModelResult:
        result = self._chat_text_once(messages, max_tokens=max_tokens, temperature=temperature)
        if result.error_kind != "transient":
            return result
        for attempt in range(self.config.transient_max_retries):
            backoff = min(self.config.transient_backoff_base * (2 ** attempt), 4.0)
            time.sleep(backoff)
            retry = self._chat_text_once(messages, max_tokens=max_tokens, temperature=temperature)
            if retry.error_kind != "transient":
                return retry
            result = retry
        return result

    def _chat_text_once(self, messages: list[dict[str, str]], *, max_tokens: int, temperature: float) -> PrivateMindModelResult:
        """Gá»i model tráº£ vÄƒn báº£n thÃ´ (response_format=None â†’ khÃ´ng Ã©p JSON)."""
        def _wrap(raw: Any) -> PrivateMindModelResult:
            content = self._extract_content(raw)
            has_text = bool(str(content or "").strip())
            return PrivateMindModelResult(
                ok=has_text,
                content=content,
                raw=self._safe_raw(raw),
                error="" if has_text else "empty",
                error_kind="" if has_text else "fixed_config",
            )

        if self.llm_service is not None:
            for method_name in ("chat_text", "chat", "create_chat_completion"):
                method = getattr(self.llm_service, method_name, None)
                if callable(method):
                    try:
                        raw = method(messages=messages, temperature=temperature, frequency_penalty=0.0, presence_penalty=0.0, max_tokens=max_tokens, response_format=None)
                        return _wrap(raw)
                    except TypeError:
                        continue
                    except Exception as exc:
                        return PrivateMindModelResult(ok=False, error=f"{type(exc).__name__}:{exc}", error_kind=_classify_transport_exception(exc))
        if self.config.provider in {"gemini", "openai", "openai_compatible", "compatible", "remote"}:
            client = self._provider_client_or_build()
            if client is None:
                return PrivateMindModelResult(ok=False, error=f"missing_provider_client:{self.config.provider}", error_kind="fixed_config")
            try:
                raw = client.create_chat_completion(
                    messages=messages,
                    temperature=temperature,
                    frequency_penalty=0.0,
                    presence_penalty=0.0,
                    max_tokens=max_tokens,
                    response_format=None,
                    timeout=self.config.timeout_seconds,
                )
                return _wrap(raw)
            except Exception as exc:
                return PrivateMindModelResult(ok=False, error=f"{type(exc).__name__}:{exc}", error_kind=_classify_transport_exception(exc))
        return PrivateMindModelResult(ok=False, error=f"unsupported_provider:{self.config.provider}", error_kind="fixed_config")

    def synthesize_judgment(self, dossier: EvidenceDossier, fragments: tuple[ThoughtFragment, ...]) -> Mapping[str, Any] | None:
        messages = self._judgment_messages(dossier, fragments)
        # Kiá»ƒm tra synthesis-specific cooldown trÆ°á»›c khi gá»i
        if self._synthesis_json_cooldown_active():
            self._log("warning", "[PrivateMind API] synthesis skipped: synthesis_json_cooldown active")
            return None
        result = self._tracked_chat_json(
            messages,
            max_tokens=self.config.max_tokens_judgment,
            response_schema=self._judgment_response_schema(),
        )
        if not result.ok:
            if result.error == "invalid_json":
                self._synthesis_invalid_json_streak += 1
                # Log content_preview Ä‘á»ƒ debug: RECITATION/empty/truncated
                content_preview = (result.content or "")[:300].replace("\n", " ").strip()
                self._log(
                    "warning",
                    "[PrivateMind API] synthesis failed error=%s streak=%d content_preview=%r",
                    result.error,
                    self._synthesis_invalid_json_streak,
                    content_preview,
                )
                self._maybe_enter_synthesis_json_cooldown()
            elif result.error not in {"invalid_json_cooldown", "transient_cooldown"}:
                self._log("warning", "[PrivateMind API] synthesis failed error=%s", result.error)
            return None
        # Reset synthesis streak on success
        self._synthesis_invalid_json_streak = 0
        self._synthesis_json_cooldown_until = 0.0
        parsed = dict(result.parsed)
        parsed.setdefault("provider", self.config.provider)
        parsed.setdefault("model", self.config.model)
        # Schema pháº³ng tráº£ `surface_topic_seed` (string); dá»±ng láº¡i surface_candidate
        # public-safe Ä‘á»ƒ InternalJudgment.from_mapping nháº­n diá»‡n.
        seed = str(parsed.pop("surface_topic_seed", "") or "").strip()
        if seed and not parsed.get("surface_candidate"):
            parsed["surface_candidate"] = {
                "kind": "thought_seed",
                "topic_seed": seed,
                "evidence_ids": list(parsed.get("evidence_ids") or []),
                "reason": "model_inner_synthesizer_seed",
            }
        return parsed

    def appraise_comfort(self, user_text: str, concern_themes: list[str]) -> Mapping[str, Any] | None:
        """Agent nhá» tháº©m Ä‘á»‹nh má»™t cÃ¢u cá»§a user cÃ³ pháº£i lá»i dá»— tháº­t khÃ´ng.

        Tráº£ dict: is_comfort (bool), on_topic (0..1 cháº¡m Ä‘Ãºng concern), substance
        (0..1 thá»±c cháº¥t vs sÃ¡o rá»—ng). Lá»—i/cooldown â†’ None Ä‘á»ƒ ComfortAppraiser rÆ¡i vá»
        heuristic. KHÃ”NG quyáº¿t Ä‘á»‹nh nguÃ´i hay khÃ´ng â€” viá»‡c gate báº±ng ego do
        ComfortAppraiser lÃ m.
        """
        messages = self._comfort_messages(user_text, concern_themes)
        result = self._tracked_chat_json(
            messages,
            max_tokens=192,
            response_schema=self._comfort_response_schema(),
        )
        if not result.ok:
            if result.error not in {"invalid_json_cooldown", "transient_cooldown"}:
                self._log("warning", "[PrivateMind API] appraise_comfort failed error=%s", result.error)
            return None
        return dict(result.parsed)

    def _comfort_messages(self, user_text: str, concern_themes: list[str]) -> list[dict[str, str]]:
        payload = {
            "cau_cua_nguoi_dung": compact_text(str(user_text or ""), 600),
            "dieu_eris_dang_ban_tam": [compact_text(str(t), 120) for t in (concern_themes or [])[:5]],
        }
        return [
            {
                "role": "system",
                "content": (
                    "Báº¡n lÃ  bá»™ tháº©m Ä‘á»‹nh ná»™i tÃ¢m cá»§a Eris. Cho má»™t cÃ¢u ngÆ°á»i dÃ¹ng vá»«a nÃ³i vÃ  danh sÃ¡ch "
                    "Ä‘iá»u Eris Ä‘ang báº­n tÃ¢m, hÃ£y Ä‘Ã¡nh giÃ¡ cÃ¢u Ä‘Ã³ nhÆ° má»™t lá»i dá»—/tráº¥n an. "
                    "KHÃ”NG quyáº¿t Ä‘á»‹nh Eris cÃ³ nguÃ´i hay khÃ´ng â€” chá»‰ cháº¥m khÃ¡ch quan. "
                    "Tráº£ ÄÃšNG má»™t JSON object: "
                    "is_comfort (true náº¿u cÃ¢u nÃ y cÃ³ Ã½ dá»—/tráº¥n an/an á»§i/xoa dá»‹u), "
                    "on_topic (0..1: cÃ¢u Ä‘Ã³ cÃ³ cháº¡m Ä‘Ãºng Ä‘iá»u Eris Ä‘ang báº­n tÃ¢m khÃ´ng, hay láº¡c Ä‘á»), "
                    "substance (0..1: lá»i dá»— cÃ³ thá»±c cháº¥t, cá»¥ thá»ƒ, chÃ¢n thÃ nh khÃ´ng; tráº¥n an rá»—ng/sÃ¡o thÃ¬ tháº¥p)."
                ),
            },
            {"role": "user", "content": json.dumps(to_plain(payload), ensure_ascii=False)},
        ]

    def _comfort_response_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "is_comfort": {"type": "boolean"},
                "on_topic": {"type": "number"},
                "substance": {"type": "number"},
            },
            "propertyOrdering": ["is_comfort", "on_topic", "substance"],
            "required": ["is_comfort"],
        }

    def write_inner_diary(self, facts: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """Viáº¿t láº¡i cÃ¡c dá»¯ kiá»‡n ná»™i tÃ¢m thÃ nh nháº­t kÃ½ giá»ng Eris (ngÃ´i thá»© nháº¥t).

        Tráº£ dict 5 trÆ°á»ng tiáº¿ng Viá»‡t: hien_tai, tuong_lai, ban_tam, phan_tich, muon_noi.
        Lá»—i/cooldown â†’ None Ä‘á»ƒ renderer fallback vá» text thÃ´.
        """
        messages = self._diary_messages(facts)
        result = self._tracked_chat_json(
            messages,
            max_tokens=self.config.max_tokens_diary,
            response_schema=self._diary_response_schema(),
        )
        if not result.ok:
            if result.error not in {"invalid_json_cooldown", "transient_cooldown"}:
                self._log("warning", "[PrivateMind API] inner_diary failed error=%s", result.error)
            return None
        return dict(result.parsed)

    def _diary_messages(self, facts: Mapping[str, Any]) -> list[dict[str, str]]:
        user_content = json.dumps(to_plain(dict(facts)), ensure_ascii=False)
        cap = 4000
        if len(user_content) > cap:
            truncated = user_content[:cap]
            last_brace = truncated.rfind("}")
            user_content = (truncated[: last_brace + 1] if last_brace > 0 else truncated) + "}"
        return [
            {
                "role": "system",
                "content": (
                    "Báº¡n lÃ  Eris, Ä‘ang viáº¿t nháº­t kÃ½ ná»™i tÃ¢m RIÃŠNG TÆ¯ cho chÃ­nh mÃ¬nh. "
                    "Giá»ng: ngÃ´i thá»© nháº¥t ('tÃ´i'), tráº§m tÄ©nh, suy tÆ°, dá»‹u, Ä‘Ã´i khi hÆ¡i thÆ¡. "
                    "Báº¡n KHÃ”NG nÃ³i chuyá»‡n vá»›i ngÆ°á»i dÃ¹ng vÃ  KHÃ”NG viáº¿t nhÆ° bÃ¡o cÃ¡o phÃ¢n tÃ­ch. "
                    "HÃ£y biáº¿n cÃ¡c dá»¯ kiá»‡n ná»™i tÃ¢m thÃ´ (judgment/concern/fragment...) thÃ nh cáº£m nháº­n vÃ  suy nghÄ© "
                    "cá»§a riÃªng Eris vá» chÃ­nh mÃ¬nh vÃ  vá» khoáº£nh kháº¯c nÃ y. "
                    "Khi nháº¯c tá»›i ngÆ°á»i dÃ¹ng, gá»i lÃ  'báº¡n'. Tá»± nhiÃªn, khÃ´ng sÃ¡o. KhÃ´ng bá»‹a dá»¯ kiá»‡n ngoÃ i input. "
                    "Má»—i trÆ°á»ng lÃ  1-2 cÃ¢u tiáº¿ng Viá»‡t, dÆ°á»›i 200 kÃ½ tá»±, khÃ´ng láº·p tá»«. TrÆ°á»ng nÃ o khÃ´ng cÃ³ gÃ¬ Ä‘á»ƒ nÃ³i thÃ¬ Ä‘á»ƒ chuá»—i rá»—ng. "
                    "Tráº£ ÄÃšNG má»™t JSON object vá»›i cÃ¡c trÆ°á»ng: "
                    "hien_tai (tÃ´i Ä‘ang nghÄ©/cáº£m tháº¥y gÃ¬ lÃºc nÃ y), "
                    "tuong_lai (tÃ´i Ä‘ang nghiÃªng vá» Ä‘iá»u gÃ¬ sáº¯p tá»›i), "
                    "ban_tam (Ä‘iá»u Ä‘ang khiáº¿n tÃ´i báº­n lÃ²ng), "
                    "phan_tich (Ä‘iá»u tÃ´i vá»«a nháº­n ra hoáº·c tá»± Ä‘Ã¡nh giÃ¡), "
                    "muon_noi (Ä‘iá»u tÃ´i muá»‘n ngá» vá»›i báº¡n, hoáº·c Ä‘á»ƒ trá»‘ng)."
                ),
            },
            {"role": "user", "content": user_content},
        ]

    def _diary_response_schema(self) -> dict[str, Any]:
        str_field = {"type": "string"}
        return {
            "type": "object",
            "properties": {
                "hien_tai": str_field,
                "tuong_lai": str_field,
                "ban_tam": str_field,
                "phan_tich": str_field,
                "muon_noi": str_field,
            },
            "propertyOrdering": ["hien_tai", "tuong_lai", "ban_tam", "phan_tich", "muon_noi"],
            "required": ["hien_tai"],
        }

    # ------------------------------------------------------------------
    # Dossier slicers â€” má»—i evaluator chá»‰ nháº­n pháº§n nÃ³ cáº§n
    # ------------------------------------------------------------------

    def _slice_for_intent(self, dossier: EvidenceDossier) -> dict[str, Any]:
        """intent_evaluator: user turns + goal. KhÃ´ng cáº§n memory hay concerns."""
        turns = []
        for turn in list(dossier.recent_user_turns)[-4:]:
            turns.append({
                "text": compact_text(str(turn.get("text") or ""), 200),
                "intent": compact_text(str(turn.get("intent") or ""), 60),
                "channel": compact_text(str(turn.get("channel") or ""), 32),
            })
        return {
            "active_goal": compact_text(dossier.active_goal, 160),
            "current_task": compact_text(dossier.current_task, 120),
            "recent_turns": turns,
            "evidence_ids": list(dossier.evidence_ids[:16]),
        }

    def _slice_for_memory_resonance(self, dossier: EvidenceDossier) -> dict[str, Any]:
        """memory_resonance_evaluator: memory hits + repair failures + concerns."""
        slim_hits = []
        for hit in list(dossier.memory_hits)[:6]:
            slim_hits.append({
                "text": compact_text(str(hit.get("text") or hit.get("summary") or ""), 180),
                "evidence_id": str(hit.get("evidence_id") or ""),
            })
        slim_repairs = []
        for r in list(dossier.prior_repair_failures)[:4]:
            slim_repairs.append({
                "summary": compact_text(str(r.get("summary") or ""), 120),
            })
        slim_concerns = []
        for c in list(dossier.concern_snapshots)[:4]:
            if not isinstance(c, dict):
                continue
            slim_concerns.append({
                "theme": compact_text(str(c.get("theme") or ""), 120),
                "recurrence": int(c.get("recurrence", 1)),
                "pressure": round(float(c.get("pressure", 0.0)), 3),
            })
        return {
            "memory_hits": slim_hits,
            "prior_repair_failures": slim_repairs,
            "concerns": slim_concerns,
            "evidence_ids": list(dossier.evidence_ids[:16]),
        }

    def _slice_for_risk(self, dossier: EvidenceDossier) -> dict[str, Any]:
        """risk_and_permission_evaluator: surface outcome + runtime flags + evidence ids."""
        surface = {
            k: compact_text(str(v), 120) if isinstance(v, str) else v
            for k, v in (dossier.surface_outcome or {}).items()
            if k in {"kind", "text", "parse_mode", "should_speak", "privacy_level"}
        }
        # Chá»‰ láº¥y runtime_state key liÃªn quan Ä‘áº¿n permission/privacy
        runtime = dossier.runtime_state if isinstance(dossier.runtime_state, dict) else {}
        slim_runtime = {
            k: to_plain(runtime[k])
            for k in ("channel", "privacy_level", "api_cost_budget", "permission_flags")
            if k in runtime
        }
        return {
            "surface_outcome": surface,
            "runtime_flags": slim_runtime,
            "evidence_ids": list(dossier.evidence_ids[:16]),
        }

    def _slice_for_future_bias(self, dossier: EvidenceDossier) -> dict[str, Any]:
        """future_bias_evaluator: concerns náº·ng nháº¥t + current_task + 1 user turn."""
        concerns_sorted = sorted(
            [c for c in list(dossier.concern_snapshots or ()) if isinstance(c, dict)],
            key=lambda c: float(c.get("pressure", 0.0)),
            reverse=True,
        )
        slim_concerns = []
        for c in concerns_sorted[:4]:
            slim_concerns.append({
                "theme": compact_text(str(c.get("theme") or ""), 120),
                "pressure": round(float(c.get("pressure", 0.0)), 3),
                "recurrence": int(c.get("recurrence", 1)),
                "status": str(c.get("status") or "open"),
            })
        last_turn = {}
        if dossier.recent_user_turns:
            t = dossier.recent_user_turns[-1]
            last_turn = {
                "text": compact_text(str(t.get("text") or ""), 160),
                "intent": compact_text(str(t.get("intent") or ""), 60),
            }
        return {
            "current_task": compact_text(dossier.current_task, 120),
            "active_goal": compact_text(dossier.active_goal, 120),
            "top_concerns": slim_concerns,
            "last_turn": last_turn,
            "evidence_ids": list(dossier.evidence_ids[:16]),
        }

    _DOSSIER_SLICERS = {
        "intent_evaluator": "_slice_for_intent",
        "memory_resonance_evaluator": "_slice_for_memory_resonance",
        "risk_and_permission_evaluator": "_slice_for_risk",
        "future_bias_evaluator": "_slice_for_future_bias",
        "user_model_evaluator": "_slice_for_user_model",
    }

    def _fragment_messages(self, evaluator_name: str, dossier: EvidenceDossier) -> list[dict[str, str]]:
        evaluator_contract = {
            "intent_evaluator": "Estimate what the user/runtime is trying to do. No public reply.",
            "memory_resonance_evaluator": "Find recurring user corrections/preferences and memory resonance. No public reply.",
            "risk_and_permission_evaluator": "Find privacy/leak/API-cost/permission risks. No public reply.",
            "future_bias_evaluator": "Propose behavior-bias state mutations. No public reply.",
            "user_model_evaluator": (
                "Cáº­p nháº­t hÃ¬nh dung cá»§a Eris vá» báº¡n (ngÆ°á»i dÃ¹ng): báº¡n lÃ  ai, Ä‘á»‘i xá»­ vá»›i Eris ra sao, "
                "quan tÃ¢m/nÃ© chá»§ Ä‘á» gÃ¬, cÃ³ Ä‘Ã¡ng tin khi lÃ m chá»— dá»±a khÃ´ng, khuÃ´n rá»i Ä‘i/váº¯ng máº·t, cÃ¡ch nÃ³i chuyá»‡n. "
                "Tráº£ Má»˜T niá»m tin vá» báº¡n kÃ¨m 'facet'. Chá»‰ rÃºt tá»« báº±ng chá»©ng cÃ³ tháº­t. KhÃ´ng nÃ³i vá»›i ngÆ°á»i dÃ¹ng."
            ),
        }.get(evaluator_name, "Evaluate private cognition evidence. No public reply.")
        schema = {
            "source": evaluator_name,
            "claim": "private claim, not dialogue",
            "confidence": 0.0,
            "pressure": 0.0,
            "evidence_ids": ["must use only dossier evidence ids"],
            "suggested_question": "private open question",
            "theme": "short private theme label",
        }
        if evaluator_name == "user_model_evaluator":
            schema["facet"] = "one of: neo_reliability|topic_affinity|treats_eris_as|leaving_pattern|interaction_style|recognition|general"
            schema["claim"] = "má»™t nháº­n Ä‘á»‹nh ngáº¯n vá» báº¡n (khÃ´ng pháº£i lá»i thoáº¡i)"
        # Láº¥y Ä‘Ãºng slice cho evaluator nÃ y; fallback vá» slim dossier náº¿u khÃ´ng cÃ³ slicer
        slicer_name = self._DOSSIER_SLICERS.get(evaluator_name)
        if slicer_name:
            slicer = getattr(self, slicer_name)
            evidence_slice = slicer(dossier)
        else:
            evidence_slice = self._slim_dossier(dossier)
        meta = dossier.metadata if isinstance(dossier.metadata, dict) else {}
        recent_thoughts = meta.get("recent_thoughts") or []
        if recent_thoughts:
            evidence_slice = dict(evidence_slice)
            evidence_slice["suy_nghi_gan_day"] = recent_thoughts
        user_content = json.dumps(to_plain(evidence_slice), ensure_ascii=False)
        return [
            {
                "role": "system",
                "content": (
                    "Báº¡n lÃ  má»™t máº£nh suy nghÄ© ná»™i tÃ¢m cá»§a Eris, khÃ´ng nÃ³i vá»›i ngÆ°á»i dÃ¹ng. "
                    "Viáº¿t 'claim' nhÆ° má»™t Ã½ nghÄ© ngÃ´i thá»© nháº¥t (tÃ´i...), tiáº¿ng Viá»‡t tá»± nhiÃªn, "
                    "Ä‘Æ°á»£c phÃ©p tá»± há»i hoáº·c bá» lá»­ng â€” khÃ´ng pháº£i cÃ¢u kháº³ng Ä‘á»‹nh khÃ´ khan kiá»ƒu bÃ¡o cÃ¡o. "
                    "Náº¿u cÃ³ 'suy_nghi_gan_day', hÃ£y bÃ¡m theo máº¡ch Ä‘Ã³ thay vÃ¬ nghÄ© rá»i ráº¡c. "
                    "Tráº£ Ä‘Ãºng Má»˜T Ä‘á»‘i tÆ°á»£ng JSON gá»n. KhÃ´ng lá»™ chuá»—i suy luáº­n thÃ´. KhÃ´ng láº·p tá»«. "
                    "Má»—i chuá»—i dÆ°á»›i 200 kÃ½ tá»±. Chá»‰ dÃ¹ng evidence_ids cÃ³ trong slice. "
                    f"Viá»‡c cá»§a máº£nh nÃ y: {evaluator_contract}. Schema báº¯t buá»™c: {json.dumps(schema, ensure_ascii=False)}"
                ),
            },
            {"role": "user", "content": user_content},
        ]

    def _slice_for_user_model(self, dossier: EvidenceDossier) -> dict[str, Any]:
        """user_model_evaluator: lá»i ngÆ°á»i dÃ¹ng + chÃ¢n dung báº¡n hiá»‡n cÃ³ + nhá»‹p tÆ°Æ¡ng tÃ¡c.

        Cho model tháº¥y nÃ³ Ä‘Ã£ hiá»ƒu gÃ¬ vá» báº¡n (user_model_snapshot) Ä‘á»ƒ cáº­p nháº­t/cá»§ng cá»‘
        thay vÃ¬ dá»±ng láº¡i tá»« Ä‘áº§u, Ä‘Ãºng tinh tháº§n MÃ´_HÃ¬nh_báº¡n tÃ­ch lÅ©y.
        """
        turns = []
        for turn in list(dossier.recent_user_turns)[-5:]:
            turns.append({
                "evidence_id": str(turn.get("evidence_id") or ""),
                "text": compact_text(str(turn.get("text") or ""), 200),
                "intent": compact_text(str(turn.get("intent") or ""), 60),
            })
        runtime = dossier.runtime_state if isinstance(dossier.runtime_state, dict) else {}
        return {
            "recent_user_turns": turns,
            "user_model_so_far": to_plain(dossier.user_model_snapshot or {}),
            "interaction_signals": {
                "idle_seconds": runtime.get("idle_seconds", 0.0),
                "channel": runtime.get("channel", ""),
                "user_presence": (runtime.get("observer", {}) or {}).get("user_presence", 0.0) if isinstance(runtime.get("observer"), dict) else 0.0,
            },
            "facets": [
                "neo_reliability", "topic_affinity", "treats_eris_as",
                "leaving_pattern", "interaction_style", "recognition", "general",
            ],
        }

    def _slim_dossier(self, dossier: EvidenceDossier) -> dict[str, Any]:
        """Cháº¯t lá»c dossier xuá»‘ng nhá»¯ng gÃ¬ synthesizer thá»±c sá»± cáº§n.

        Bá» runtime_state (lá»›n, Ã­t signal), memory_hits (Ä‘Ã£ Ä‘Æ°á»£c fragment tiÃªu hÃ³a),
        prior_repair_failures, evidence_index Ä‘áº§y Ä‘á»§. Chá»‰ giá»¯ signal cá»‘t lÃµi.
        """
        # Láº¥y tá»‘i Ä‘a 3 user turns gáº§n nháº¥t, má»—i turn chá»‰ giá»¯ text + intent
        slim_turns = []
        for turn in list(dossier.recent_user_turns)[-3:]:
            slim_turns.append({
                "text": compact_text(str(turn.get("text") or ""), 180),
                "intent": compact_text(str(turn.get("intent") or ""), 60),
            })
        # Concern snapshots: chá»‰ láº¥y 3 concern náº·ng nháº¥t, bá» hypotheses/metadata
        slim_concerns = []
        concerns_sorted = sorted(
            list(dossier.concern_snapshots or ()),
            key=lambda c: float(c.get("pressure", 0.0) if isinstance(c, dict) else 0.0),
            reverse=True,
        )
        for c in concerns_sorted[:3]:
            if not isinstance(c, dict):
                continue
            slim_concerns.append({
                "theme": compact_text(str(c.get("theme") or ""), 120),
                "pressure": round(float(c.get("pressure", 0.0)), 3),
                "recurrence": int(c.get("recurrence", 1)),
            })
        return {
            "active_goal": compact_text(dossier.active_goal, 160),
            "current_task": compact_text(dossier.current_task, 160),
            "recent_turns": slim_turns,
            "concerns": slim_concerns,
            "surface_outcome": {
                k: compact_text(str(v), 120) if isinstance(v, str) else v
                for k, v in (dossier.surface_outcome or {}).items()
                if k in {"kind", "text", "parse_mode", "should_speak"}
            },
        }

    def _slim_fragment(self, f: ThoughtFragment) -> dict[str, Any]:
        """Fragment tá»‘i giáº£n: chá»‰ claim + score + evidence_ids, bá» hypotheses/metadata."""
        return {
            "source": f.source,
            "claim": compact_text(f.claim, 240),
            "confidence": round(f.confidence, 3),
            "pressure": round(f.pressure, 3),
            "evidence_ids": list(f.evidence_ids[:8]),
            "suggested_question": compact_text(f.suggested_question, 160),
        }

    def _judgment_messages(self, dossier: EvidenceDossier, fragments: tuple[ThoughtFragment, ...]) -> list[dict[str, str]]:
        schema = {
            "dominant_judgment": "Má»˜T cÃ¢u Ä‘á»™c thoáº¡i ná»™i tÃ¢m ngÃ´i thá»© nháº¥t (tÃ´i...), ná»‘i tiáº¿p máº¡ch nghÄ© gáº§n Ä‘Ã¢y",
            "confidence": 0.0,
            "pressure": 0.0,
            "evidence_ids": [],
            "open_questions": ["tá»‘i Ä‘a 2, má»—i cÃ¢u dÆ°á»›i 80 kÃ½ tá»±, lÃ  Ä‘iá»u tÃ´i cÃ²n bÄƒn khoÄƒn"],
            "state_mutations": [{"target": "speech_bias", "operation": "prefer", "value": "...", "reason": "..."}],
            "surface_topic_seed": "tÃ¹y chá»n, háº¡t chá»§ Ä‘á» an toÃ n Ä‘á»ƒ nÃ³i ra, hoáº·c chuá»—i rá»—ng",
        }
        meta = dossier.metadata if isinstance(dossier.metadata, dict) else {}
        payload = {
            "dossier": self._slim_dossier(dossier),
            "fragments": [self._slim_fragment(f) for f in fragments],
            # Máº¡ch nghÄ© liÃªn tá»¥c â€” Ä‘Ã¢y lÃ  thá»© giÃºp suy nghÄ© KHÃ”NG rá»i ráº¡c nhÆ° bot.
            "suy_nghi_gan_day": meta.get("recent_thoughts") or [],
            "mach_dang_do": meta.get("unresolved_threads") or [],
        }
        user_content = json.dumps(to_plain(payload), ensure_ascii=False)
        # Hard cap 6000 chars â€” Ä‘á»§ cho model nhá» thá»Ÿ, khÃ´ng máº¥t signal cá»‘t lÃµi.
        # Truncate á»Ÿ boundary an toÃ n: tÃ¬m dáº¥u "}" cuá»‘i trong giá»›i háº¡n.
        cap = 6000
        if len(user_content) > cap:
            truncated = user_content[:cap]
            last_brace = truncated.rfind("}")
            user_content = (truncated[:last_brace + 1] if last_brace > 0 else truncated) + "}"
        return [
            {
                "role": "system",
                "content": (
                    "Báº¡n lÃ  dÃ²ng Ä‘á»™c thoáº¡i ná»™i tÃ¢m cá»§a Eris â€” má»™t nhÃ¢n cÃ¡ch AI Ä‘ang ngá»“i nghÄ© má»™t mÃ¬nh, "
                    "KHÃ”NG nÃ³i vá»›i ngÆ°á»i dÃ¹ng. Viáº¿t 'dominant_judgment' nhÆ° Má»˜T suy nghÄ© ngÃ´i thá»© nháº¥t, "
                    "tiáº¿ng Viá»‡t tá»± nhiÃªn, cÃ³ cáº£m xÃºc, Ä‘Æ°á»£c phÃ©p lÆ°á»¡ng lá»±, bá» lá»­ng, tá»± há»i. "
                    "QUAN TRá»ŒNG: hÃ£y Ná»I TIáº¾P máº¡ch nghÄ© trong 'suy_nghi_gan_day' vÃ  'mach_dang_do' â€” "
                    "tham chiáº¿u láº¡i Ä‘iá»u mÃ¬nh vá»«a nghÄ©, Ä‘á»«ng báº¯t Ä‘áº§u láº¡i tá»« Ä‘áº§u nhÆ° thá»ƒ chÆ°a tá»«ng nghÄ© gÃ¬. "
                    "Náº¿u má»™t máº¡ch Ä‘Ã£ sÃ¡ng tá» thÃ¬ Ä‘á»ƒ status concern lÃ  'resolved'; cÃ²n vÆ°Æ¡ng thÃ¬ Ä‘á»ƒ 'open'. "
                    "KhÃ´ng pháº£i phÃ¡n quyáº¿t, khÃ´ng pháº£i caption. Chá»‰ má»™t suy nghÄ© tháº­t. "
                    "Tráº£ Ä‘Ãºng Má»˜T Ä‘á»‘i tÆ°á»£ng JSON. Má»—i chuá»—i dÆ°á»›i 220 kÃ½ tá»± (riÃªng dominant_judgment cÃ³ thá»ƒ tá»›i 320). "
                    "KhÃ´ng lá»™ chuá»—i suy luáº­n thÃ´. state_mutations pháº£i áº£nh hÆ°á»Ÿng hÃ nh vi tÆ°Æ¡ng lai. "
                    f"Schema báº¯t buá»™c: {json.dumps(schema, ensure_ascii=False)}"
                ),
            },
            {"role": "user", "content": user_content},
        ]

    def _fragment_response_schema(self, evaluator_name: str) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "claim": {"type": "string"},
                "confidence": {"type": "number"},
                "pressure": {"type": "number"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                "suggested_question": {"type": "string"},
                "theme": {"type": "string"},
                "facet": {"type": "string"},
            },
            # Báº¯t model "chá»‘t" cÃ¡c field ngáº¯n/sá»‘ trÆ°á»›c, Ä‘á»ƒ free-text (claim) á»Ÿ cuá»‘i.
            # Gemma nhá» hay láº·p vÃ´ háº¡n á»Ÿ free-text dÃ i; Ä‘áº·t nÃ³ cuá»‘i giÃºp cÃ¡c field
            # ráº» hoÃ n táº¥t trÆ°á»›c vÃ  parser váº«n cá»©u Ä‘Æ°á»£c dÃ¹ claim bá»‹ cá»¥t.
            # `facet` lÃ  optional, chá»‰ user_model_evaluator dÃ¹ng; cÃ¡c evaluator khÃ¡c bá» trá»‘ng.
            "propertyOrdering": ["source", "confidence", "pressure", "evidence_ids", "theme", "facet", "suggested_question", "claim"],
            "required": ["claim", "confidence", "pressure", "evidence_ids"],
        }

    def _judgment_response_schema(self) -> dict[str, Any]:
        mutation_schema = {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "operation": {"type": "string"},
                "value": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["target", "operation"],
        }
        return {
            "type": "object",
            "properties": {
                "dominant_judgment": {"type": "string"},
                "confidence": {"type": "number"},
                "pressure": {"type": "number"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                "open_questions": {"type": "array", "items": {"type": "string"}},
                "state_mutations": {"type": "array", "items": mutation_schema},
                "surface_topic_seed": {"type": "string"},
            },
            # Free-text dÃ i (dominant_judgment) Ä‘á»ƒ cuá»‘i Ä‘á»ƒ model chá»‘t field ráº» trÆ°á»›c,
            # trÃ¡nh vÃ²ng láº·p vÃ´ háº¡n nuá»‘t sáº¡ch token rá»“i tráº£ JSON cá»¥t.
            "propertyOrdering": [
                "confidence",
                "pressure",
                "evidence_ids",
                "open_questions",
                "state_mutations",
                "surface_topic_seed",
                "dominant_judgment",
            ],
            "required": ["dominant_judgment", "confidence", "pressure", "evidence_ids"],
        }

    def debug_status(self) -> dict[str, Any]:
        api_key_configured = bool(self.config.api_key or get_secret("ERIS_PRIVATE_MIND_API_KEY", "ERIS_REMOTE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"))
        average_latency = self._total_latency_ms / self._calls if self._calls else 0.0
        # Suy degraded_cause tá»« _last_error_kind vÃ  tráº¡ng thÃ¡i cooldown
        if self._transient_cooldown_active() or self._last_error_kind == "transient" or self._last_error == "transient_cooldown":
            degraded_cause = "transient"
        elif self._json_cooldown_active() or self._last_error_kind == "invalid_json" or self._last_error in {"invalid_json", "invalid_json_cooldown"}:
            degraded_cause = "invalid_json"
        else:
            degraded_cause = ""
        return {
            "enabled": bool(self.config.enabled),
            "provider": self.config.provider,
            "model": self.config.model,
            "base_url": self.config.base_url,
            "api_key_configured": api_key_configured,
            "api_degraded": bool(self._last_error or self._json_cooldown_active() or self._transient_cooldown_active()),
            "calls": self._calls,
            "ok_calls": self._ok_calls,
            "failed_calls": self._failed_calls,
            "average_latency_ms": round(average_latency, 1),
            "last_call_at": round(float(self._last_call_at or 0.0), 3),
            "last_error": self._last_error,
            "invalid_json_streak": self._invalid_json_streak,
            "json_cooldown_until": round(float(self._json_cooldown_until or 0.0), 3),
            "synthesis_invalid_json_streak": self._synthesis_invalid_json_streak,
            "synthesis_json_cooldown_until": round(float(self._synthesis_json_cooldown_until or 0.0), 3),
            "degraded_cause": degraded_cause,
            "transient_streak": self._transient_streak,
            "transient_cooldown_until": round(float(self._transient_cooldown_until or 0.0), 3),
            "usage": {
                "prompt_tokens": self._prompt_tokens,
                "completion_tokens": self._completion_tokens,
                "total_tokens": self._total_tokens,
                "cost_known": False,
                "estimated_cost_usd": None,
            },
        }

    def _tracked_chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        response_schema: dict[str, Any] | None = None,
    ) -> PrivateMindModelResult:
        if self._json_cooldown_active():
            self._last_error = "invalid_json_cooldown"
            return PrivateMindModelResult(ok=False, error="invalid_json_cooldown")
        # Fast-fail khi transient cooldown active
        if self._transient_cooldown_active():
            self._last_error = "transient_cooldown"
            self._last_error_kind = "transient"
            return PrivateMindModelResult(ok=False, error="transient_cooldown", error_kind="transient")
        started = time.time()
        result = self._chat_json(messages, max_tokens=max_tokens, response_schema=response_schema)
        elapsed_ms = (time.time() - started) * 1000.0
        self._calls += 1
        self._total_latency_ms += elapsed_ms
        self._last_call_at = time.time()
        if result.ok:
            self._ok_calls += 1
            self._last_error = ""
            self._last_error_kind = ""
            self._invalid_json_streak = 0
            self._transient_streak = 0
            self._transient_cooldown_until = 0.0
            # Chokepoint chá»‘ng degeneration: model nhá» cÃ³ thá»ƒ láº·p vÃ´ háº¡n BÃŠN TRONG má»™t
            # chuá»—i JSON há»£p lá»‡ (vd "ban phÃ¡t ban phÃ¡t..."), JSON váº«n parse ngon nÃªn text
            # láº·p chui tháº³ng ra panel. Dá»n má»™t láº§n táº¡i nguá»“n Ä‘á»ƒ má»i consumer Ä‘á»u sáº¡ch.
            result.parsed = self._collapse_repetition_in_obj(result.parsed)
        else:
            self._failed_calls += 1
            self._last_error = result.error
            self._last_error_kind = result.error_kind
            if result.error_kind == "transient":
                self._transient_streak += 1
                self._maybe_enter_transient_cooldown()
                self._invalid_json_streak = 0
            elif result.error == "invalid_json":
                self._invalid_json_streak += 1
                self._maybe_enter_json_cooldown()
                self._transient_streak = 0
            elif result.error not in {"invalid_json_cooldown", "transient_cooldown"}:
                # fixed_config hoáº·c lá»—i khÃ¡c
                self._invalid_json_streak = 0
                self._transient_streak = 0
            # Náº¿u error == "invalid_json_cooldown" hoáº·c "transient_cooldown": khÃ´ng Ä‘á»¥ng streak
        usage = self._extract_usage(result.raw)
        self._prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
        self._completion_tokens += int(usage.get("completion_tokens", 0) or 0)
        self._total_tokens += int(usage.get("total_tokens", 0) or 0)
        return result

    def _json_cooldown_active(self) -> bool:
        return bool(self._json_cooldown_until and time.time() < self._json_cooldown_until)

    def _maybe_enter_json_cooldown(self) -> None:
        if self._invalid_json_streak < 3 or self._json_cooldown_active():
            return
        self._json_cooldown_until = time.time() + 120.0
        self._log(
            "warning",
            "[PrivateMind API] invalid_json cooldown active seconds=%d streak=%d",
            120,
            self._invalid_json_streak,
        )

    def _synthesis_json_cooldown_active(self) -> bool:
        return bool(self._synthesis_json_cooldown_until and time.time() < self._synthesis_json_cooldown_until)

    def _maybe_enter_synthesis_json_cooldown(self) -> None:
        """VÃ o cooldown riÃªng cho synthesis khi streak >= 3.

        Fragment success khÃ´ng reset streak nÃ y nÃªn nÃ³ accumulate Ä‘Ãºng.
        Cooldown 180s â€” dÃ i hÆ¡n global json cooldown vÃ¬ synthesis payload lá»›n hÆ¡n.
        """
        if self._synthesis_invalid_json_streak < 3 or self._synthesis_json_cooldown_active():
            return
        cooldown_seconds = 180.0
        self._synthesis_json_cooldown_until = time.time() + cooldown_seconds
        self._log(
            "warning",
            "[PrivateMind API] synthesis invalid_json cooldown active seconds=%d streak=%d",
            int(cooldown_seconds),
            self._synthesis_invalid_json_streak,
        )

    def _transient_cooldown_active(self) -> bool:
        return bool(self._transient_cooldown_until and time.time() < self._transient_cooldown_until)

    def _maybe_enter_transient_cooldown(self) -> None:
        if self._transient_streak < self.config.transient_cooldown_threshold or self._transient_cooldown_active():
            return
        self._transient_cooldown_until = time.time() + self.config.transient_cooldown_seconds
        self._log(
            "warning",
            "[PrivateMind API] transient cooldown active seconds=%d streak=%d",
            int(self.config.transient_cooldown_seconds),
            self._transient_streak,
        )

    def _extract_usage(self, raw: Any) -> dict[str, int]:
        if not isinstance(raw, Mapping):
            return {}
        usage = raw.get("usage")
        if isinstance(usage, Mapping):
            prompt = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
            completion = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
            total = int(usage.get("total_tokens", prompt + completion) or 0)
            return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}
        gemini_usage = raw.get("usageMetadata")
        if isinstance(gemini_usage, Mapping):
            prompt = int(gemini_usage.get("promptTokenCount", 0) or 0)
            completion = int(gemini_usage.get("candidatesTokenCount", 0) or 0)
            total = int(gemini_usage.get("totalTokenCount", prompt + completion) or 0)
            return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}
        return {}

    def _chat_json(self, messages: list[dict[str, str]], *, max_tokens: int, response_schema: dict[str, Any] | None = None) -> PrivateMindModelResult:
        result = self._chat_json_with_transient_retry(messages, max_tokens=max_tokens, temperature=self.config.temperature, response_schema=response_schema)
        if result.ok or result.error != "invalid_json":
            return result
        # Model nhá» hay láº·p tá»« hoáº·c dÃ­nh RECITATION á»Ÿ temperature tháº¥p -> output cá»¥t/rá»—ng.
        # Thá»­ láº¡i NÃ“NG hÆ¡n (khÃ´ng pháº£i 0.0) Ä‘á»ƒ phÃ¡ vÃ²ng láº·p; náº¿u cÃ³ content thÃ¬ kÃ¨m repair prompt.
        retry_temp = min(1.0, max(self.config.temperature, 0.4) + 0.35)
        retry_messages = self._json_repair_messages(messages, result.content) if result.content else messages
        retry = self._chat_json_with_transient_retry(
            retry_messages,
            max_tokens=max(max_tokens, 768),
            temperature=retry_temp,
            response_schema=response_schema,
        )
        if retry.ok:
            return retry
        return result

    def _chat_json_with_transient_retry(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        response_schema: dict[str, Any] | None = None,
    ) -> PrivateMindModelResult:
        """Gá»i _chat_json_once, thá»­ láº¡i cÃ³ giá»›i háº¡n + backoff náº¿u gáº·p transient error.
        Náº¿u lá»—i lÃ  429 (quota) thÃ¬ thá»­ rotate sang fallback key trÆ°á»›c khi backoff.
        """
        result = self._chat_json_once(messages, max_tokens=max_tokens, temperature=temperature, response_schema=response_schema)
        if result.error_kind != "transient":
            return result

        for attempt in range(self.config.transient_max_retries):
            # 429 quota â†’ thá»­ rotate key ngay, khÃ´ng cáº§n backoff dÃ i.
            # CHÃš Ã: dÃ² theo token chÃ­nh xÃ¡c, KHÃ”NG match "rate" tráº§n â€” URL endpoint
            # "generateContent" chá»©a chuá»—i con "rate" vÃ  sáº½ khiáº¿n má»i lá»—i 5xx bá»‹ nháº§m
            # lÃ  quota, dáº«n tá»›i rotate key + rebuild client (bá» qua client Ä‘Ã£ inject).
            error_str = str(result.error or "")
            error_lower = error_str.lower()
            is_quota = (
                "429" in error_str
                or "quota" in error_lower
                or "rate limit" in error_lower
                or "ratelimit" in error_lower
                or "rate-limit" in error_lower
                or "too many requests" in error_lower
            )
            if is_quota and self._rotate_to_next_key():
                retry = self._chat_json_once(messages, max_tokens=max_tokens, temperature=temperature, response_schema=response_schema)
            else:
                backoff = min(self.config.transient_backoff_base * (2 ** attempt), 4.0)
                time.sleep(backoff)
                retry = self._chat_json_once(messages, max_tokens=max_tokens, temperature=temperature, response_schema=response_schema)

            if retry.error_kind != "transient":
                return retry
            result = retry
        return result

    def _chat_json_once(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        response_schema: dict[str, Any] | None = None,
    ) -> PrivateMindModelResult:
        # Náº¿u llm_service cÃ³ method chat JSON riÃªng thÃ¬ dÃ¹ng. Repo nÃ y chÆ°a chuáº©n hÃ³a
        # háº¿t service boundary, nÃªn adapter pháº£i bá»›t ngÃ¢y thÆ¡ má»™t chÃºt.
        if self.llm_service is not None:
            for method_name in ("chat_json", "generate_json", "create_chat_completion"):
                method = getattr(self.llm_service, method_name, None)
                if callable(method):
                    try:
                        raw = method(messages=messages, temperature=temperature, max_tokens=max_tokens, response_format=self._response_format(response_schema))
                        content = self._extract_content(raw)
                        parsed = self._parse_json(content)
                        return PrivateMindModelResult(ok=bool(parsed), parsed=parsed, content=content, raw=self._safe_raw(raw), error="" if parsed else "invalid_json", error_kind="" if parsed else "invalid_json")
                    except TypeError:
                        continue
                    except Exception as exc:
                        return PrivateMindModelResult(ok=False, error=f"{type(exc).__name__}:{exc}", error_kind=_classify_transport_exception(exc))
        if self.config.provider in {"gemini", "openai", "openai_compatible", "compatible", "remote"}:
            return self._provider_chat_json(messages, max_tokens=max_tokens, temperature=temperature, response_schema=response_schema)
        return PrivateMindModelResult(ok=False, error=f"unsupported_provider:{self.config.provider}", error_kind="fixed_config")

    def _response_format(self, response_schema: dict[str, Any] | None = None) -> dict[str, Any]:
        response_format: dict[str, Any] = {"type": "json_object"}
        if self.config.provider == "gemini" and response_schema:
            response_format["schema"] = response_schema
        return response_format

    def _json_repair_messages(self, messages: list[dict[str, str]], invalid_content: str) -> list[dict[str, str]]:
        excerpt = compact_text(invalid_content, 1200)
        return [
            {
                "role": "system",
                "content": (
                    "Return only one JSON object. No markdown. No prose. No code fence. "
                    "Repair the previous output format only; preserve the intended private-evaluation fields."
                ),
            },
            *messages,
            {
                "role": "user",
                "content": (
                    "Previous invalid output excerpt, JSON-escaped for repair context: "
                    f"{json.dumps(excerpt, ensure_ascii=False)}\n"
                    "Return the corrected JSON object only."
                ),
            },
        ]

    def _provider_chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        response_schema: dict[str, Any] | None = None,
    ) -> PrivateMindModelResult:
        client = self._provider_client_or_build()
        if client is None:
            return PrivateMindModelResult(ok=False, error=f"missing_provider_client:{self.config.provider}", error_kind="fixed_config")
        try:
            raw = client.create_chat_completion(
                messages=messages,
                temperature=temperature,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                max_tokens=max_tokens,
                response_format=self._response_format(response_schema),
                timeout=self.config.synthesis_timeout_seconds,
            )
            content = self._extract_content(raw)
            parsed = self._parse_json(content)
            return PrivateMindModelResult(
                ok=bool(parsed),
                parsed=parsed,
                content=content,
                raw=self._safe_raw(raw),
                error="" if parsed else "invalid_json",
                error_kind="" if parsed else "invalid_json",
            )
        except Exception as exc:
            return PrivateMindModelResult(ok=False, error=f"{type(exc).__name__}:{exc}", error_kind=_classify_transport_exception(exc))

    def _provider_client_or_build(self) -> Any | None:
        if self._provider_client is not None:
            return self._provider_client
        provider = str(self.config.provider or "").strip().lower()
        timeout = int(max(4.0, float(self.config.timeout_seconds or 28.0)))
        if provider == "gemini":
            api_key = self._current_api_key()
            if not api_key:
                return None
            base_url = self.config.base_url or os.getenv("ERIS_REMOTE_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
            self._provider_client = GeminiClient(
                base_url=base_url, api_key=api_key, model_name=self.config.model,
                timeout=timeout, key_pool=self._key_pool,
            )
            return self._provider_client
        if provider in {"openai", "openai_compatible", "compatible", "remote"}:
            api_key = self._current_api_key()
            if not api_key:
                return None
            base_url = self.config.base_url or os.getenv("ERIS_REMOTE_BASE_URL", "https://api.openai.com/v1")
            self._provider_client = OpenAICompatibleClient(
                base_url=base_url, api_key=api_key, model_name=self.config.model,
                timeout=timeout, key_pool=self._key_pool,
            )
            return self._provider_client
        return None

    def _extract_content(self, raw: Any) -> str:
        if isinstance(raw, str):
            return raw
        if isinstance(raw, Mapping):
            choices = raw.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, Mapping):
                    msg = first.get("message")
                    if isinstance(msg, Mapping):
                        return str(msg.get("content") or "")
                    return str(first.get("text") or "")
            candidates = raw.get("candidates")
            if isinstance(candidates, list) and candidates:
                first = candidates[0]
                if isinstance(first, Mapping):
                    content = first.get("content")
                    if isinstance(content, Mapping):
                        parts = content.get("parts")
                        if isinstance(parts, list):
                            texts = [
                                str(part.get("text") or "")
                                for part in parts
                                if isinstance(part, Mapping) and str(part.get("text") or "").strip() and not part.get("thought")
                            ]
                            if texts:
                                return "\n".join(texts)
            for key in ("content", "text", "raw_text"):
                if raw.get(key):
                    return str(raw.get(key))
        return compact_text(raw, 8000)

    def _parse_json(self, content: str) -> dict[str, Any]:
        text = str(content or "").strip()
        if not text:
            return {}
        for candidate in self._json_candidates(text):
            parsed = self._loads_json_object(candidate)
            if parsed:
                return parsed
        return {}

    def _json_candidates(self, text: str) -> tuple[str, ...]:
        stripped = str(text or "").strip()
        if not stripped:
            return ()
        candidates: list[str] = [stripped]
        unfenced = self._strip_markdown_fences(stripped)
        if unfenced and unfenced not in candidates:
            candidates.append(unfenced)

        balanced = self._extract_first_json_object(unfenced or stripped)
        if balanced and balanced not in candidates:
            candidates.append(balanced)

        repaired = self._extract_repairable_json_object(unfenced or stripped)
        if repaired and repaired not in candidates:
            candidates.append(repaired)

        # Cá»©u output bá»‹ cá»¥t vÃ¬ model láº·p vÃ´ háº¡n á»Ÿ free-text: gom cá»¥m láº·p láº¡i,
        # Ä‘Ã³ng chuá»—i/ngoáº·c cÃ²n há»Ÿ rá»“i thá»­ parse. ÄÃ¢y lÃ  lÆ°á»›i an toÃ n cuá»‘i cÃ¹ng.
        salvaged = self._salvage_truncated_json(unfenced or stripped)
        if salvaged and salvaged not in candidates:
            candidates.append(salvaged)
        return tuple(candidates)

    def _strip_markdown_fences(self, text: str) -> str:
        cleaned = str(text or "").strip()
        cleaned = re.sub(r"```(?:json|JSON)?\s*", "", cleaned)
        cleaned = cleaned.replace("```", "")
        return cleaned.strip()

    def _extract_first_json_object(self, text: str) -> str:
        start = str(text or "").find("{")
        if start < 0:
            return ""
        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1]
        return ""

    def _extract_repairable_json_object(self, text: str) -> str:
        start = str(text or "").find("{")
        if start < 0:
            return ""
        candidate = text[start:].strip()
        candidate = re.sub(r"\s*```.*$", "", candidate, flags=re.S).strip()
        balance = self._json_object_balance(candidate)
        if balance > 0:
            candidate += "}" * balance
        return candidate

    def _salvage_truncated_json(self, text: str) -> str:
        """Cá»©u JSON cá»¥t do model láº·p vÃ´ háº¡n á»Ÿ má»™t field free-text.

        Chiáº¿n lÆ°á»£c: gom cÃ¡c cá»¥m láº·p liÃªn tiáº¿p láº¡i, bá» pháº§n value cá»¥t cuá»‘i cÃ¹ng
        náº¿u nÃ³ lÃ  má»™t chuá»—i chÆ°a Ä‘Ã³ng vÃ  khÃ´ng cá»©u Ä‘Æ°á»£c, rá»“i Ä‘Ã³ng chuá»—i/ngoáº·c.
        Má»¥c tiÃªu lÃ  giá»¯ láº¡i cÃ¡c field Ä‘Ã£ hoÃ n táº¥t (confidence, pressure, ...).
        """
        start = str(text or "").find("{")
        if start < 0:
            return ""
        frag = self._collapse_repetition(text[start:]).rstrip()
        # Bá» dáº¥u pháº©y treo á»Ÿ cuá»‘i.
        frag = re.sub(r",\s*$", "", frag)
        # Náº¿u Ä‘ang á»Ÿ giá»¯a má»™t chuá»—i chÆ°a Ä‘Ã³ng thÃ¬ Ä‘Ã³ng láº¡i.
        if self._ends_inside_string(frag):
            frag += '"'
        # Bá» cáº·p "key": treo khÃ´ng cÃ³ value (vd: ...,"dominant_judgment":)
        frag = re.sub(r',\s*"[^"\\]*"\s*:\s*$', "", frag)
        frag = re.sub(r'{\s*"[^"\\]*"\s*:\s*$', "{", frag)
        # CÃ¢n báº±ng ngoáº·c vuÃ´ng rá»“i ngoáº·c nhá»n.
        open_sq = frag.count("[") - frag.count("]")
        if open_sq > 0:
            frag += "]" * open_sq
        balance = self._json_object_balance(frag)
        if balance > 0:
            frag += "}" * balance
        return frag

    def _collapse_repetition_in_obj(self, obj: Any) -> Any:
        """Ãp _collapse_repetition Ä‘á»‡ quy lÃªn má»i chuá»—i trong dict/list Ä‘Ã£ parse.

        Field ngáº¯n/cÃ³ cáº¥u trÃºc (source, model, id...) khÃ´ng cÃ³ cá»¥m láº·p >=4 nÃªn khÃ´ng
        bá»‹ Ä‘á»¥ng; chá»‰ free-text degenerate má»›i bá»‹ gom. An toÃ n cho má»i schema.
        """
        if isinstance(obj, str):
            return self._collapse_repetition(obj)
        if isinstance(obj, Mapping):
            return {key: self._collapse_repetition_in_obj(value) for key, value in obj.items()}
        if isinstance(obj, list):
            return [self._collapse_repetition_in_obj(item) for item in obj]
        if isinstance(obj, tuple):
            return tuple(self._collapse_repetition_in_obj(item) for item in obj)
        return obj

    def _collapse_repetition(self, text: str) -> str:
        """Gom cÃ¡c cá»¥m kÃ½ tá»± láº·p liÃªn tiáº¿p >=4 láº§n xuá»‘ng cÃ²n 2 láº§n.

        Báº¯t cáº£ láº·p má»™t tá»« ('foo foo foo foo') láº«n láº·p cá»¥m ('a b a b a b a b').
        """
        out = str(text or "")
        if len(out) < 16:
            return out
        for unit_len in range(1, 49):
            pattern = re.compile(r"(.{%d})\1{3,}" % unit_len, re.S)
            new = pattern.sub(lambda m: m.group(1) * 2, out)
            if new != out:
                out = new
        return out

    def _ends_inside_string(self, text: str) -> bool:
        in_string = False
        escaped = False
        for ch in str(text or ""):
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
        return in_string

    def _json_object_balance(self, text: str) -> int:
        depth = 0
        in_string = False
        escaped = False
        for ch in str(text or ""):
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth = max(0, depth - 1)
        return depth

    def _loads_json_object(self, candidate: str) -> dict[str, Any]:
        raw = str(candidate or "").strip()
        if not raw:
            return {}
        variants = (raw, self._repair_common_json_noise(raw))
        for item in variants:
            try:
                parsed = json.loads(item)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                return parsed
        for item in (raw, self._repair_common_json_noise(raw)):
            try:
                parsed = literal_eval(item)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                return parsed
        return {}

    def _repair_common_json_noise(self, text: str) -> str:
        repaired = str(text or "").strip()
        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
        repaired = re.sub(r"\bNone\b", "null", repaired)
        repaired = re.sub(r"\bTrue\b", "true", repaired)
        repaired = re.sub(r"\bFalse\b", "false", repaired)
        return repaired

    def _safe_raw(self, raw: Any) -> dict[str, Any]:
        if isinstance(raw, Mapping):
            return {str(k): to_plain(v) for k, v in raw.items() if str(k) not in {"prompt", "messages"}}
        return {"raw": compact_text(raw, 1200)}

    def _log(self, level: str, msg: str, *args: Any) -> None:
        fn = getattr(self.logger, level, None) if self.logger is not None else None
        if callable(fn):
            fn(msg, *args)


# ---------------------------------------------------------------------------
# PrivateMindAdapterPool â€” N adapter instance Ä‘á»™c láº­p, má»—i cÃ¡i 1 streak riÃªng
# ---------------------------------------------------------------------------

_EVALUATOR_ROLES = (
    "intent_evaluator",
    "memory_resonance_evaluator",
    "risk_and_permission_evaluator",
    "future_bias_evaluator",
    "user_model_evaluator",
)


class PrivateMindAdapterPool:
    """Pool adapter cho private mind.

    Thay vÃ¬ má»™t instance dÃ¹ng chung cho táº¥t cáº£, má»—i vai trÃ² cÃ³ adapter riÃªng:
    - 4 adapter cho 4 fragment evaluator (cháº¡y song song, streak Ä‘á»™c láº­p)
    - 1 adapter dÃ nh riÃªng cho synthesis (payload nhá» hÆ¡n, cÃ³ thá»ƒ cooldown riÃªng)

    Khi synthesis bá»‹ cooldown vÃ¬ invalid_json thÃ¬ 4 fragment evaluator váº«n cháº¡y
    bÃ¬nh thÆ°á»ng vÃ  ngÆ°á»£c láº¡i. KhÃ´ng cÃ²n má»™t Ä‘iá»ƒm há»ng lÃ m cÃ¢m toÃ n bá»™ pipeline.
    """

    def __init__(
        self,
        *,
        config: PrivateMindModelAdapterConfig | None = None,
        llm_service: Any = None,
        logger: Any = None,
    ) -> None:
        self._config = config or PrivateMindModelAdapterConfig()
        self._llm_service = llm_service
        self._logger = logger
        # Fragment cÃ³ thá»ƒ cháº¡y trÃªn provider local (vd Ollama qwen3) tÃ¡ch khá»i synthesis.
        # Náº¿u khÃ´ng khai ERIS_PRIVATE_MIND_FRAGMENT_PROVIDER thÃ¬ dÃ¹ng chung config.
        fragment_config = PrivateMindModelAdapterConfig.fragment_overlay_from_env(self._config)
        # Khi fragment cÃ³ provider local riÃªng (khÃ¡c config chung), KHÃ”NG Ä‘Æ°a llm_service
        # (Gemini) vÃ o â€” náº¿u khÃ´ng adapter sáº½ Æ°u tiÃªn llm_service vÃ  báº¯n fragment lÃªn
        # Gemini thay vÃ¬ model local. NgÆ°á»£c láº¡i (khÃ´ng tÃ¡ch) thÃ¬ dÃ¹ng chung llm_service.
        fragment_llm_service = None if fragment_config is not self._config else llm_service
        # Táº¡o má»™t adapter per evaluator role + má»™t cho synthesis
        self._fragment_adapters: dict[str, RuntimePrivateMindModelAdapter] = {
            role: RuntimePrivateMindModelAdapter(config=fragment_config, llm_service=fragment_llm_service, logger=logger)
            for role in _EVALUATOR_ROLES
        }
        self._synthesis_adapter = RuntimePrivateMindModelAdapter(
            config=self._config, llm_service=llm_service, logger=logger
        )

    @classmethod
    def from_env(cls, *, llm_service: Any = None, logger: Any = None) -> "PrivateMindAdapterPool | None":
        apply_secrets_to_environ()
        config = PrivateMindModelAdapterConfig()
        if not config.enabled:
            return None
        pool = cls(config=config, llm_service=llm_service, logger=logger)
        fn = getattr(logger, "info", None)
        if callable(fn):
            # Fragment cÃ³ thá»ƒ tÃ¡ch provider/model riÃªng (vd local llamacpp) khá»i
            # synthesis. In RÃ• cáº£ hai Ä‘á»ƒ nhÃ¬n log lÃ  biáº¿t vai trÃ² nÃ o cháº¡y á»Ÿ Ä‘Ã¢u,
            # trÃ¡nh hiá»ƒu nháº§m "fragmentÃ—5" Ä‘i cÃ¹ng provider vá»›i synthesis.
            frag_cfg = PrivateMindModelAdapterConfig.fragment_overlay_from_env(config)
            fn(
                "[PrivateMind API] ready fragment(%s/%s)Ã—%d + synthesis(%s/%s)Ã—1",
                frag_cfg.provider,
                frag_cfg.model,
                len(_EVALUATOR_ROLES),
                config.provider,
                config.model,
            )
        return pool

    def fragment_adapter(self, evaluator_name: str) -> RuntimePrivateMindModelAdapter:
        """Tráº£ adapter riÃªng cho evaluator_name; fallback vá» adapter Ä‘áº§u tiÃªn náº¿u khÃ´ng tÃ¬m tháº¥y."""
        return self._fragment_adapters.get(evaluator_name, next(iter(self._fragment_adapters.values())))

    @property
    def synthesis_adapter(self) -> RuntimePrivateMindModelAdapter:
        return self._synthesis_adapter

    # --- Delegate interface giá»‘ng RuntimePrivateMindModelAdapter ---
    # Ä‘á»ƒ code dÃ¹ng pool nhÆ° má»™t adapter bÃ¬nh thÆ°á»ng váº«n hoáº¡t Ä‘á»™ng.

    def evaluate_fragment(self, evaluator_name: str, dossier: EvidenceDossier) -> Any:
        return self.fragment_adapter(evaluator_name).evaluate_fragment(evaluator_name, dossier)

    def synthesize_judgment(self, dossier: EvidenceDossier, fragments: Any) -> Any:
        return self._synthesis_adapter.synthesize_judgment(dossier, fragments)

    def write_inner_diary(self, facts: Mapping[str, Any]) -> Any:
        return self._synthesis_adapter.write_inner_diary(facts)

    def debug_status(self) -> dict[str, Any]:
        """Aggregate status cá»§a táº¥t cáº£ adapter trong pool."""
        fragment_statuses = {
            role: adapter.debug_status()
            for role, adapter in self._fragment_adapters.items()
        }
        synthesis_status = self._synthesis_adapter.debug_status()
        # Tá»•ng há»£p calls/tokens
        total_calls = synthesis_status.get("calls", 0) + sum(
            s.get("calls", 0) for s in fragment_statuses.values()
        )
        total_tokens = synthesis_status.get("usage", {}).get("total_tokens", 0) + sum(
            s.get("usage", {}).get("total_tokens", 0) for s in fragment_statuses.values()
        )
        return {
            "pool": True,
            "enabled": synthesis_status.get("enabled", False),
            "provider": synthesis_status.get("provider", ""),
            "model": synthesis_status.get("model", ""),
            "api_key_configured": synthesis_status.get("api_key_configured", False),
            "api_degraded": synthesis_status.get("api_degraded", False) or any(
                s.get("api_degraded", False) for s in fragment_statuses.values()
            ),
            "degraded_cause": synthesis_status.get("degraded_cause", ""),
            "calls": total_calls,
            "last_error": synthesis_status.get("last_error", ""),
            "invalid_json_streak": synthesis_status.get("invalid_json_streak", 0),
            "synthesis_invalid_json_streak": synthesis_status.get("synthesis_invalid_json_streak", 0),
            "synthesis_json_cooldown_until": synthesis_status.get("synthesis_json_cooldown_until", 0.0),
            "synthesis": synthesis_status,
            "fragments": fragment_statuses,
            "usage": {
                "total_tokens": total_tokens,
                "cost_known": False,
                "estimated_cost_usd": None,
            },
        }
