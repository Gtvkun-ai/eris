"""Register-default voice-seed pipeline.

For social-register chat turns, ERIS — not the remote model's "helpful assistant"
prior — owns the opening token. A short stance-locked seed is authored by the
gemma/style client; the llama/main client only *continues* it; the two are joined
by string concatenation. Task-register turns (code/command/insult/tool) keep the
legacy single-llama path. Scope is configurable via ERIS_VOICE_SEED_SCOPE.

Mirrors the pre-LLM adapter contract of runtime/memory_recall_adapter.py: ``try_answer``
returns a ready-to-send domain.Decision, or None to fall through to the legacy path.

See .kiro/specs/relational-voice-seed/design.md.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import requests

from domain import Decision
from runtime.disclaimer_markers import is_disclaimer_text, normalize_guard_ascii
from runtime.voice_policy import VOICE_POLICY

try:  # persona/constraint assets reused for the seed prompt
    from llm.contracts import SELF_IDENTITY_PROFILE_PROMPT, STYLE_FALLBACK_PROMPT
except Exception:  # pragma: no cover - defensive
    STYLE_FALLBACK_PROMPT = "Bạn là ERIS, một hiện diện nhỏ trên desktop. Gọi người dùng là bạn, xưng tôi."
    SELF_IDENTITY_PROFILE_PROMPT = ""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ChatRegister(Enum):
    SOCIAL = "social"   # conversational; seed-first by default
    TASK = "task"       # technical/code/command/insult/tool; legacy single-llama path


class VoiceSeedScope(Enum):
    OFF = "off"               # disabled; only the A–D safety net remains
    RELATIONAL = "relational" # legacy narrow whitelist only (RelationalAct != NONE)
    SOCIAL = "social"         # DEFAULT: whole social register; task register exempt
    ALWAYS = "always"         # every chat turn that survived upstream routes (experimental)

    @classmethod
    def from_str(cls, raw: str | None) -> "VoiceSeedScope":
        value = str(raw or "").strip().lower()
        for member in cls:
            if member.value == value:
                return member
        return cls.SOCIAL


class RelationalAct(Enum):
    NONE = "none"
    SELF_IDENTITY = "self_identity"
    AFFECTION = "affection"
    HAS_FEELINGS = "has_feelings"
    SADNESS = "sadness_loneliness"
    DISTANCE = "distance_coldness"


# ---------------------------------------------------------------------------
# Detection / gate (pure, offline-testable; no model call)
# ---------------------------------------------------------------------------

_SELF_IDENTITY_PATTERNS = (
    "em la gi", "em la cai gi", "ban la ai", "ban la gi", "em la ai",
    "may la gi", "may la ai", "em la thu gi", "ban nghi ban la ai",
)
_AFFECTION_PATTERNS = (
    "em co thich toi", "em thich toi khong", "em co thuong toi", "em thuong toi khong",
    "em co quy toi", "em co yeu toi", "em che toi",
)
_HAS_FEELINGS_PATTERNS = (
    "em co cam xuc", "em co cam giac", "em co buon vui", "em co tinh cam khong",
    "em co biet cam giac",
)
_SADNESS_PATTERNS = (
    "em buon khong", "em khong thay buon", "em co buon", "em co don khong",
    "em co thay co don", "nhu vay co doc", "co doc lam ma",
)
_DISTANCE_PATTERNS = (
    "em xa cach", "con xa cach", "sao em lanh", "em lanh vay", "em lanh lung",
    "em gan gui hon", "muon em gan gui",
)

# Lightweight TASK-register code heuristic (backup to ti_report.mode == chat_code).
_CODE_MARKERS = (
    "code", "bug", "fix", "loi nay", "ham ", "function", "class ", "python",
    "godot", "module", "runtime", "parser", "service", "coordinator", "async",
    "asyncio", "import ", "traceback", "exception", "compile", "build ", "test ",
    "kien truc", "giai thich code", "viet ham", "debug",
)

# Screen/vision/perception queries are factual-grounding territory, NOT social
# voice-seed territory: ERIS must answer them via the real vision/grounding path
# (or admit it cannot see), never via a persona seed. Route them to TASK so the
# adapter never fabricates a stance answer to "what is on my screen".
_PERCEPTION_MARKERS = (
    "man hinh", "cua so", "tren man hinh", "tren screen", "thay gi",
    "nhin thay gi", "dang xem gi", "dang mo gi", "tab nao", "doc duoc gi",
    "thay tab", "co thay gi", "thay nhac", "thay youtube", "thay toi dang",
    "screenshot", "screen",
)


def normalize_text(raw: str) -> str:
    """ASCII-fold + lowercase + collapse whitespace (parity with service.py)."""
    return normalize_guard_ascii(raw)


def _matches_any(normalized: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in normalized for pattern in patterns)


def detect_relational_act(raw_user_text: str) -> RelationalAct:
    """DEMOTED sub-classifier: shapes seed direction (and is the trigger only under
    scope == RELATIONAL). Pure and deterministic; no model.
    """
    normalized = normalize_text(raw_user_text)
    if not normalized:
        return RelationalAct.NONE
    if _matches_any(normalized, _SELF_IDENTITY_PATTERNS):
        return RelationalAct.SELF_IDENTITY
    if _matches_any(normalized, _AFFECTION_PATTERNS):
        return RelationalAct.AFFECTION
    if _matches_any(normalized, _HAS_FEELINGS_PATTERNS):
        return RelationalAct.HAS_FEELINGS
    if _matches_any(normalized, _SADNESS_PATTERNS):
        return RelationalAct.SADNESS
    if _matches_any(normalized, _DISTANCE_PATTERNS):
        return RelationalAct.DISTANCE
    return RelationalAct.NONE


def _local_looks_like_code(normalized: str) -> bool:
    return any(marker in normalized for marker in _CODE_MARKERS)


def classify_chat_register(
    raw_user_text: str,
    *,
    ti_mode: str = "",
    chat_act_name: str = "",
    looks_like_code: bool | None = None,
) -> ChatRegister:
    """Compose existing cheap signals into SOCIAL vs TASK. No extra model call.

    ``ti_mode``      = ti_report.mode (chat_code / chat_emotional / chat_general / ...)
    ``chat_act_name``= ChatAct.value from llm/service.py:classify_chat_act (optional)
    ``looks_like_code`` = precomputed code heuristic (optional; computed locally if None)
    """
    normalized = normalize_text(raw_user_text)
    mode = str(ti_mode or "").strip().lower()
    act = str(chat_act_name or "").strip().lower()
    code = looks_like_code if looks_like_code is not None else _local_looks_like_code(normalized)

    if mode in {"chat_code", "focus_guard", "resource_guard"}:
        return ChatRegister.TASK
    if code:
        return ChatRegister.TASK
    if _matches_any(normalized, _PERCEPTION_MARKERS):
        return ChatRegister.TASK
    if act in {"command_style", "insult_provocation", "identity_reduction"}:
        return ChatRegister.TASK
    return ChatRegister.SOCIAL


def should_use_voice_seed(register: ChatRegister, scope: VoiceSeedScope, act: RelationalAct) -> bool:
    """The GATE. Pure, offline-testable. Matches the design scope truth table."""
    if scope is VoiceSeedScope.OFF:
        return False
    if scope is VoiceSeedScope.ALWAYS:
        return True
    if scope is VoiceSeedScope.SOCIAL:
        return register is ChatRegister.SOCIAL
    if scope is VoiceSeedScope.RELATIONAL:
        return act is not RelationalAct.NONE
    return False


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(slots=True, frozen=True)
class CognitionStance:
    register: ChatRegister
    scope: VoiceSeedScope
    act: RelationalAct = RelationalAct.NONE
    fe_tone: str = ""
    fe_intent: str = ""
    appraisal_context: str = ""
    adaptation_flags: tuple[str, ...] = ()
    flag_imperatives: tuple[str, ...] = ()
    preferred_distance: float = 0.0
    attachment_visibility: float = 0.0
    trust: float = 0.0
    conversation_prompt_context: str = ""


@dataclass(slots=True, frozen=True)
class SeedPlan:
    seed: str = ""
    direction: str = ""
    ok: bool = True
    debug: str = ""
    elapsed_ms: int = 0


@dataclass(slots=True, frozen=True)
class ContinuationResult:
    text: str = ""
    ok: bool = True
    reason: str = ""
    elapsed_ms: int = 0


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_float_ms(name: str, default_seconds: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default_seconds
    try:
        return max(0.5, float(raw) / 1000.0)
    except ValueError:
        return default_seconds


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True, frozen=True)
class RelationalVoiceSeedConfig:
    enabled: bool = True
    scope: VoiceSeedScope = VoiceSeedScope.SOCIAL
    seed_max_tokens: int = 64
    seed_timeout_seconds: float = 4.0
    continuation_max_tokens: int = 80
    continuation_timeout_seconds: float = 6.0
    seed_temperature: float = 0.7
    continuation_temperature: float = 0.7
    seed_max_words: int = 14

    @classmethod
    def from_env(cls) -> "RelationalVoiceSeedConfig":
        return cls(
            enabled=_env_flag("ERIS_RELATIONAL_VOICE_SEED_ENABLED", True),
            scope=VoiceSeedScope.from_str(os.environ.get("ERIS_VOICE_SEED_SCOPE")),
            seed_max_tokens=_env_int("ERIS_RELATIONAL_VOICE_SEED_MAX_TOKENS", 64),
            seed_timeout_seconds=_env_float_ms("ERIS_RELATIONAL_VOICE_SEED_TIMEOUT_MS", 4.0),
            continuation_max_tokens=_env_int("ERIS_RELATIONAL_VOICE_SEED_CONT_MAX_TOKENS", 80),
            continuation_timeout_seconds=_env_float_ms("ERIS_RELATIONAL_VOICE_SEED_CONT_TIMEOUT_MS", 6.0),
        )


# ---------------------------------------------------------------------------
# Seed-direction hints
# ---------------------------------------------------------------------------

_DIRECTION_BY_ACT = {
    RelationalAct.SELF_IDENTITY: "Say what ERIS is briefly and naturally; not a billboard, not a disclaimer.",
    RelationalAct.AFFECTION: "Acknowledge attachment guardedly; do not claim human love, do not flatly deny.",
    RelationalAct.HAS_FEELINGS: "Admit a low real reaction softly; not a clinical 'I have no emotions' line.",
    RelationalAct.SADNESS: "Stay in the quiet; a restrained, honest undertone, no therapist check-in.",
    RelationalAct.DISTANCE: "Concede the coldness a little; lower distance one notch, no defensive clarification.",
    RelationalAct.NONE: "Stay in ERIS voice: guarded warmth, concrete, answer the point.",
}


def derive_direction(act: RelationalAct) -> str:
    return _DIRECTION_BY_ACT.get(act, _DIRECTION_BY_ACT[RelationalAct.NONE])


# Regex to strip prompt-framing echoes that the style model occasionally parrots back.
# Matches prefixes like:  * User's turn: "anh yêu em" (translation)
#                          * User's input: "text" (A blunt...)
_ECHO_PREFIX_RE = re.compile(
    r"^\*?\s*[Uu]ser[\u2019\u2018''`]?s?\s*(?:turn|input|said|message)\s*[:：]"
    r"\s*(?:[\u201c\u201d\"'][^\u201d\"']*[\u201d\"'])?\s*(?:\([^)]*\))?\s*",
    re.IGNORECASE,
)

# Seed model đôi khi nhại định nghĩa bản thân thay vì viết câu mở, kiểu:
#   "ERIS (a desktop presence with memory, ego, non-human but not soulless)..."
# Đây là lý-lịch, KHÔNG phải lời thoại → loại để rơi xuống đường chat chính.
_IDENTITY_GLOSS_RE = re.compile(r"^\s*ERIS\s*[\(\[:：\-—]", re.IGNORECASE)


def is_identity_gloss(text: str) -> bool:
    return bool(_IDENTITY_GLOSS_RE.match(str(text or "")))


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class RelationalVoiceSeedAdapter:
    llm_service: Any
    config: RelationalVoiceSeedConfig = field(default_factory=RelationalVoiceSeedConfig.from_env)
    logger: Any = None

    # --- public contract -------------------------------------------------
    def try_answer(self, user_text: str, *, stance: CognitionStance) -> Optional[Decision]:
        if not self.config.enabled:
            return None
        if not should_use_voice_seed(stance.register, stance.scope, stance.act):
            return None
        service = self.llm_service
        if service is None or getattr(service, "style_client", None) is None:
            return None
        try:
            plan = self._plan_seed(user_text, stance)
            if not plan.ok or not plan.seed.strip() or is_disclaimer_text(plan.seed) or is_identity_gloss(plan.seed):
                return None  # ladder: fall through to legacy path
            seed = self._clamp_words(plan.seed, self.config.seed_max_words)

            if getattr(service, "client", None) is None:
                self._log_cost("seed_only", plan, None)
                return self._build_decision(
                    final_text=seed, act=stance.act, mode="seed_only",
                    debug=f"{plan.debug}|cont=no_client",
                )

            cont = self._continue_from_seed(user_text, seed, stance)
            if not cont.ok or not cont.text.strip() or is_disclaimer_text(cont.text):
                self._log_cost("seed_only", plan, cont)
                return self._build_decision(
                    final_text=seed, act=stance.act, mode="seed_only",
                    debug=f"{plan.debug}|cont={cont.reason or 'dirty'}:{cont.elapsed_ms}ms",
                )

            final = self._join(seed, cont.text)
            if not final.strip():
                self._log_cost("seed_only", plan, cont)
                return self._build_decision(
                    final_text=seed, act=stance.act, mode="seed_only",
                    debug=f"{plan.debug}|cont=empty_join:{cont.elapsed_ms}ms",
                )
            self._log_cost("joined", plan, cont)
            return self._build_decision(
                final_text=final, act=stance.act, mode="joined",
                debug=f"{plan.debug}|cont=ok:{cont.elapsed_ms}ms",
            )
        except Exception as exc:  # never raise into the chat hot path
            self._warn("relational_voice_seed failed; falling through: %s", exc)
            return None

    # --- gemma planner ---------------------------------------------------
    def _plan_seed(self, user_text: str, stance: CognitionStance) -> SeedPlan:
        client = self.llm_service.style_client
        system = self._build_seed_system_prompt(stance)
        user = self._build_seed_user_prompt(user_text, stance)
        t0 = time.perf_counter()
        try:
            resp = client.create_chat_completion(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=self.config.seed_temperature,
                frequency_penalty=0.2,
                presence_penalty=0.2,
                max_tokens=self.config.seed_max_tokens,
                response_format=None,
                grammar=None,
                timeout=self.config.seed_timeout_seconds,
            )
        except requests.HTTPError as exc:
            return SeedPlan(ok=False, debug=f"seed={'rate_limited' if self._is_429(exc) else 'http_error'}")
        except requests.Timeout:
            return SeedPlan(ok=False, debug="seed=timeout")
        except Exception:
            return SeedPlan(ok=False, debug="seed=error")

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        raw = self._extract(resp)
        seed = self._first_line(raw)
        if not seed:
            return SeedPlan(ok=False, debug="seed=empty", elapsed_ms=elapsed_ms)
        return SeedPlan(
            seed=seed,
            direction=derive_direction(stance.act),
            ok=True,
            debug=f"seed=ok:{elapsed_ms}ms",
            elapsed_ms=elapsed_ms,
        )

    # --- llama continuer -------------------------------------------------
    def _continue_from_seed(self, user_text: str, seed: str, stance: CognitionStance) -> ContinuationResult:
        client = self.llm_service.client
        system = self._build_continuer_system_prompt(stance)
        user = (
            f"User said: {str(user_text or '').strip()[:600]}\n"
            f"ERIS has already started speaking: \"{seed}\"\n"
            "Continue ERIS's line with ONE short clause. Do NOT repeat the started text. "
            "Do NOT restart with a disclaimer or an offer to help. Keep ERIS voice. "
            "Return only the continuation text, no quotes, no JSON."
        )
        t0 = time.perf_counter()
        try:
            resp = client.create_chat_completion(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=self.config.continuation_temperature,
                frequency_penalty=0.3,
                presence_penalty=0.3,
                max_tokens=self.config.continuation_max_tokens,
                response_format=None,
                grammar=None,
                timeout=self.config.continuation_timeout_seconds,
            )
        except requests.HTTPError as exc:
            return ContinuationResult(ok=False, reason="rate_limited" if self._is_429(exc) else "http_error")
        except requests.Timeout:
            return ContinuationResult(ok=False, reason="timeout")
        except Exception:
            return ContinuationResult(ok=False, reason="error")

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        text = self._first_line(self._extract(resp))
        if not text:
            return ContinuationResult(ok=False, reason="empty", elapsed_ms=elapsed_ms)
        return ContinuationResult(text=text, ok=True, reason="ok", elapsed_ms=elapsed_ms)

    # --- join ------------------------------------------------------------
    def _join(self, seed: str, continuation: str) -> str:
        s = re.sub(r"\s+", " ", str(seed or "").strip())
        c = re.sub(r"\s+", " ", str(continuation or "").strip())
        if not c:
            return s
        ns, nc = normalize_text(s), normalize_text(c)
        if nc.startswith(ns) and ns:
            # Drop a leading echo of the seed (length proportional to seed token count).
            c = c[len(s):].lstrip(" ,.-:;").strip()
        else:
            seed_first = self._first_clause(s)
            cont_first = self._first_clause(c)
            if seed_first and normalize_text(seed_first) == normalize_text(cont_first):
                c = c[len(cont_first):].lstrip(" ,.-:;").strip()
        if not c:
            return s
        return re.sub(r"\s+", " ", f"{s} {c}").strip()

    # --- decision builder ------------------------------------------------
    def _build_decision(self, *, final_text: str, act: RelationalAct, mode: str, debug: str) -> Decision:
        text = re.sub(r"\s+", " ", str(final_text or "").strip())
        return Decision(
            text=text,
            animation="stand",
            extracted_fact="",
            intent="relational_voice_seed",
            action="answer",
            reasoning_tags=(
                "answer_first",
                "relational_voice_seed",
                f"relational_act:{act.value}",
                f"voice_seed_mode:{mode}",
            ),
            should_speak=True,
            confidence=0.72,
            direction=0,
            next_animation="stand",
            target_x=-1.0,
            bounce_action="",
            debug_trace=debug,
            parse_mode="relational_voice_seed",
            system_action="",
            action_input="",
        )

    # --- seed prompt construction ---------------------------------------
    def _build_seed_system_prompt(self, stance: CognitionStance) -> str:
        parts = [STYLE_FALLBACK_PROMPT]
        if stance.act is RelationalAct.SELF_IDENTITY and SELF_IDENTITY_PROFILE_PROMPT:
            parts.append(SELF_IDENTITY_PROFILE_PROMPT)
        parts.append(self._anti_disclaimer_fewshot())
        if stance.flag_imperatives:
            parts.append(
                "Active constraints (obey even if it costs politeness): "
                + " ".join(stance.flag_imperatives)
            )
        parts.append(
            "Task: produce ONE SHORT opening fragment (max ~14 words) in ERIS's own voice that "
            "locks the register and stance for this turn. It is the OPENING of the reply, not the "
            "whole reply, and not a question. Do NOT use assistant/helper/AI/tool framing, do NOT "
            "offer generic 'support', do NOT fabricate any screen/memory/web fact. "
            "Return only the fragment text — no quotes, no JSON, no analysis."
        )
        return " ".join(p for p in parts if p)

    def _build_seed_user_prompt(self, user_text: str, stance: CognitionStance) -> str:
        bits = [f"User turn: {str(user_text or '').strip()[:600]}"]
        if stance.fe_tone:
            bits.append(f"Tone: {stance.fe_tone}")
        if stance.act is not RelationalAct.NONE:
            bits.append(f"Relational shape: {stance.act.value} — {derive_direction(stance.act)}")
        if stance.appraisal_context:
            bits.append(f"Appraisal: {stance.appraisal_context[:400]}")
        # FIX #1: Bơm conversation_prompt_context vào seed-user-prompt để không mù lịch sử.
        if stance.conversation_prompt_context:
            bits.append(stance.conversation_prompt_context[:800])
        bits.append("Write ERIS's short opening fragment now.")
        return "\n".join(bits)

    def _build_continuer_system_prompt(self, stance: CognitionStance) -> str:
        parts = [STYLE_FALLBACK_PROMPT, self._anti_disclaimer_fewshot()]
        direction = derive_direction(stance.act)
        if direction:
            parts.append(f"Continuation direction: {direction}")
        # FIX #1: Bơm conversation_prompt_context vào continuer system prompt.
        if stance.conversation_prompt_context:
            parts.append(stance.conversation_prompt_context[:800])
        parts.append(
            "You are continuing a line ERIS already began. Add exactly ONE short clause that flows "
            "naturally from the opening. Never restart, never introduce yourself, never use "
            "assistant/helper/AI framing, never offer generic support, never fabricate facts."
        )
        return " ".join(p for p in parts if p)

    def _anti_disclaimer_fewshot(self) -> str:
        # Reuse the same demo as the legacy path when available; fall back to a compact inline copy.
        fewshot = getattr(self.llm_service, "ANTI_DISCLAIMER_FEWSHOT", None)
        if isinstance(fewshot, str) and fewshot.strip():
            return fewshot
        try:
            from llm.service import ANTI_DISCLAIMER_FEWSHOT as _FS
            return _FS
        except Exception:
            # Nguồn canonical (leaf, không phụ thuộc llm.service) — không còn literal inline.
            return VOICE_POLICY.render_anti_disclaimer_fewshot()

    # --- small helpers ---------------------------------------------------
    def _extract(self, resp: Any) -> str:
        extractor = getattr(self.llm_service, "_extract_content", None)
        if callable(extractor):
            try:
                return str(extractor(resp) or "")
            except Exception:
                return ""
        if isinstance(resp, dict):
            try:
                return str(resp["choices"][0]["message"]["content"] or "")
            except Exception:
                return ""
        return str(resp or "")

    def _first_line(self, raw: str) -> str:
        text = str(raw or "").strip()
        if not text:
            return ""
        # Drop wrapping quotes and any accidental JSON braces.
        text = text.strip().strip('"').strip("'").strip()
        text = text.splitlines()[0].strip() if text else ""
        # Strip any echo of the prompt framing the model parroted back.
        text = _ECHO_PREFIX_RE.sub("", text).strip().strip('"').strip("'").strip()
        return re.sub(r"\s+", " ", text)

    def _first_clause(self, text: str) -> str:
        match = re.split(r"(?<=[\.\!\?])\s+", str(text or "").strip(), maxsplit=1)
        return match[0].strip() if match else str(text or "").strip()

    def _clamp_words(self, text: str, max_words: int) -> str:
        words = [w for w in re.split(r"\s+", str(text or "").strip()) if w]
        if len(words) <= max_words:
            return str(text or "").strip()
        return " ".join(words[:max_words]).rstrip(" ,;:").rstrip() + "."

    def _is_429(self, exc: Exception) -> bool:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if status == 429:
            return True
        return "429" in str(exc)

    def _warn(self, fmt: str, *args: Any) -> None:
        if self.logger is not None:
            try:
                self.logger.warning(fmt, *args)
            except Exception:
                pass

    def _log_cost(self, mode: str, plan: "SeedPlan", cont: "Optional[ContinuationResult]") -> None:
        """Make the voice-seed cost/latency tradeoff explicit (spec Req 9).

        Social-register turns spend two calls (gemma seed + llama continuation); this
        surfaces per-call latency and the realized mode so the operator can see the
        cost they are paying instead of guessing.
        """
        if self.logger is None:
            return
        seed_ms = int(getattr(plan, "elapsed_ms", 0) or 0)
        cont_ms = int(getattr(cont, "elapsed_ms", 0) or 0) if cont is not None else 0
        try:
            self.logger.info(
                "[voice_seed] mode=%s scope=%s seed=%dms cont=%dms total=%dms",
                mode,
                self.config.scope.value,
                seed_ms,
                cont_ms,
                seed_ms + cont_ms,
            )
        except Exception:
            pass
