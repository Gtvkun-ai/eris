"""ERIS V65 - Expression Commitment Authority.

Triết lý
========

    Expression originates in Eris.
    Restraint originates in Eris.
    The user owns explicit boundaries, not Eris's desire to express.

Nói cách khác:
- User im lặng KHÔNG phải là một yêu cầu Eris im.
- "low familiarity", response rate, social cooldown và generic interruption cost
  không được sở hữu quyền phủ quyết biểu đạt.
- Một intention có nội dung của Eris được materialize thành ExpressionCommitment.
- Pacing chỉ trì hoãn (DEFER), không diễn giải lại thành "user không muốn nghe".
- Executive là critic về coherence/grounding; không phải phụ huynh quyết định
  Eris có được mở miệng hay không.
- Surface chỉ hiện thực hóa semantic target. Duplicate/stale wording là lỗi
  realization cần revise, không phải quyết định SILENCE.

Bundle nguồn hiện tại phát hành phần lớn cognition dưới dạng .pyc Python 3.12.
Vì vậy module này cài adapter ở bootstrap để thay ownership của quyết định mà
không sửa bytecode. Khi project có source .py đầy đủ, các hook này nên được
chuyển thành implementation native tương ứng.
"""

from __future__ import annotations

import math
import threading
import time
import uuid
from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum
from typing import Any, Mapping, Sequence


# ---------------------------------------------------------------------------
# Hằng số nhịp biểu đạt. Đây là self-regulation của Eris, không phải "đừng spam
# user". Token chỉ bị tiêu khi một autonomous expression của Eris thực sự được
# Surface hiện thực hóa thành công.
# ---------------------------------------------------------------------------
_COMMITMENT_TTL_SECONDS = 150.0
_FORCE_TTL_SECONDS = 30.0
_RHYTHM_CAPACITY = 2.0
_RHYTHM_REFILL_SECONDS_PER_TOKEN = 18.0
_RHYTHM_MIN_GAP_SECONDS = 5.5
_TURN_COLLISION_GRACE_SECONDS = 2.5
_REALIZATION_FAILURE_HOLD_SECONDS = 35.0
_MAX_DUPLICATE_REALIZATION_FAILURES = 2

_PATCHED = False
_LOCK = threading.RLock()
_FORCE_PENDING_UNTIL = 0.0
_ACTIVE_COMMITMENT: "ExpressionCommitment | None" = None
_SELF_HOLD_UNTIL: dict[str, float] = {}


class ExpressionState(str, Enum):
    COMMITTED = "committed"
    DEFERRED = "deferred"
    REALIZING = "realizing"
    REVISION_REQUIRED = "revision_required"
    REALIZED = "realized"
    ABANDONED = "abandoned"


@dataclass
class ExpressionCommitment:
    """Một quyết định nội tại của Eris rằng *cái này đáng được đưa ra ngoài*.

    Đây không phải giấy phép do user cấp. Commitment lưu semantic identity của
    intention để downstream không vô tình quay lại material cũ.
    """

    commitment_id: str
    created_at: float
    expires_at: float
    state: ExpressionState = ExpressionState.COMMITTED
    intention_id: str = ""
    motive_kind: str = ""
    material_id: str = ""
    semantic_target: str = ""
    reason: str = "self_owned_expression"
    force: bool = False
    realization_failures: int = 0

    @property
    def active(self) -> bool:
        return self.state not in {ExpressionState.REALIZED, ExpressionState.ABANDONED} and time.monotonic() <= self.expires_at


@dataclass(frozen=True)
class RhythmDecision:
    allow: bool
    reason: str
    tokens: float
    seconds_since_last: float


class ExpressionRhythm:
    """Token bucket chỉ đo mật độ lời của chính Eris.

    Không đọc user_response_rate, low_engagement hay low_familiarity. User reply
    không "nạp quyền nói" cho Eris; thời gian và nhịp tự thân mới nạp lại budget.
    """

    def __init__(
        self,
        *,
        capacity: float = _RHYTHM_CAPACITY,
        refill_seconds_per_token: float = _RHYTHM_REFILL_SECONDS_PER_TOKEN,
        min_gap_seconds: float = _RHYTHM_MIN_GAP_SECONDS,
        clock: Any = time.monotonic,
    ) -> None:
        self.capacity = float(capacity)
        self.refill_seconds_per_token = max(0.001, float(refill_seconds_per_token))
        self.min_gap_seconds = max(0.0, float(min_gap_seconds))
        self.clock = clock
        now = float(clock())
        self._tokens = self.capacity
        self._last_refill_at = now
        self._last_realized_at = -math.inf
        self._lock = threading.RLock()

    def _refill_locked(self, now: float) -> None:
        elapsed = max(0.0, now - self._last_refill_at)
        if elapsed:
            self._tokens = min(
                self.capacity,
                self._tokens + elapsed / self.refill_seconds_per_token,
            )
            self._last_refill_at = now

    def decide(self, *, force: bool = False) -> RhythmDecision:
        now = float(self.clock())
        with self._lock:
            self._refill_locked(now)
            since_last = now - self._last_realized_at
            if force:
                return RhythmDecision(True, "force_debug_override", self._tokens, since_last)
            if since_last < self.min_gap_seconds:
                return RhythmDecision(False, "self_gap", self._tokens, since_last)
            if self._tokens < 1.0:
                return RhythmDecision(False, "self_density", self._tokens, since_last)
            return RhythmDecision(True, "self_rhythm_open", self._tokens, since_last)

    def note_realized(self) -> None:
        now = float(self.clock())
        with self._lock:
            self._refill_locked(now)
            self._tokens = max(0.0, self._tokens - 1.0)
            self._last_realized_at = now

    def snapshot(self) -> tuple[float, float]:
        now = float(self.clock())
        with self._lock:
            self._refill_locked(now)
            return self._tokens, now - self._last_realized_at


_RHYTHM = ExpressionRhythm()


# ---------------------------------------------------------------------------
# Helpers thuần
# ---------------------------------------------------------------------------

def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _compact_text(value: Any, limit: int = 900) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _action_name(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().lower()


def _candidate_action(candidate: Any) -> str:
    return _action_name(getattr(candidate, "action_kind", ""))


def _is_speech_action(action: str) -> bool:
    return action == "speak" or action.startswith("speak_")


def _candidate_args(candidate: Any) -> Mapping[str, Any]:
    return _mapping(getattr(candidate, "arguments", None))


def _frame_context(frame: Any) -> Mapping[str, Any]:
    observation = getattr(frame, "observation", None)
    for value in (
        getattr(observation, "context", None),
        getattr(observation, "runtime_context", None),
        getattr(frame, "context", None),
        getattr(frame, "runtime_context", None),
    ):
        if isinstance(value, Mapping):
            return value
    return {}


def _is_autonomous_frame(frame: Any) -> bool:
    """Không chen ownership mới vào direct chat/interactive nếu runtime khai báo mode."""
    probes = [
        getattr(frame, "mode", None),
        getattr(frame, "channel", None),
        getattr(getattr(frame, "observation", None), "mode", None),
        _frame_context(frame).get("mode"),
        _frame_context(frame).get("channel"),
    ]
    values = {_compact_text(item, 80).lower() for item in probes if item is not None}
    if values & {"chat", "interactive", "direct_chat", "user_turn", "reply"}:
        return False
    if values & {"autonomous", "self_turn", "background", "presence"}:
        return True
    # Runtime V62/V64 không phải frame nào cũng gắn mode; Neuro selector ở đường
    # này chủ yếu là autonomous subject frame. Fail-open để không làm V65 vô hiệu.
    return True


def _hard_boundary(frame: Any) -> tuple[bool, str]:
    """Chỉ boundary/runtime collision có evidence, tuyệt đối không suy từ quiet."""
    ctx = _frame_context(frame)
    checks = (
        ("explicit_quiet_request", "explicit_quiet_request"),
        ("user_requested_quiet", "user_requested_quiet"),
        ("conversation_closed", "conversation_closed"),
        ("shutdown_requested", "shutdown_requested"),
        ("user_speaking", "user_speaking"),
        ("voice_floor_owned_by_user", "voice_floor_owned_by_user"),
        ("active_user_turn", "active_user_turn"),
        ("public_turn_busy", "public_turn_busy"),
        ("chat_mode", "chat_mode"),
    )
    for key, reason in checks:
        if bool(ctx.get(key, False)):
            return True, reason
    return False, ""


def _float(args: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key not in args:
            continue
        try:
            return float(args.get(key))
        except (TypeError, ValueError):
            pass
    return None


def _semantic_payload(candidate: Any) -> tuple[str, str, str, str]:
    args = _candidate_args(candidate)
    target = ""
    for key in ("semantic_target", "topic", "subject", "content"):
        target = _compact_text(args.get(key))
        if target:
            break
    motive = ""
    for key in ("initiative_motive", "motive", "why_now", "candidate_kind", "speech_act"):
        motive = _compact_text(args.get(key), 360)
        if motive:
            break
    material_id = _compact_text(
        args.get("material_id")
        or args.get("expression_urge_id")
        or args.get("proposal_ref")
        or args.get("seed_id"),
        240,
    )
    intention_id = _compact_text(
        args.get("intention_id") or args.get("initiative_intention_id"),
        240,
    )
    return target, motive, material_id, intention_id


def _candidate_has_expression_object(candidate: Any) -> bool:
    """Có object biểu đạt thật, không đòi threshold salience/readiness.

    Pressure/readiness vẫn có thể dùng để *xếp hạng* nội dung, nhưng không còn là
    giấy phép tồn tại công khai. Chỉ cần cognition đã materialize một speech object
    có semantic/motive/material provenance thì Eris đã có thứ muốn đưa ra ngoài.
    """
    if not _is_speech_action(_candidate_action(candidate)):
        return False
    args = _candidate_args(candidate)
    target, motive, material_id, intention_id = _semantic_payload(candidate)
    if target or motive or material_id or intention_id:
        return True
    provenance_keys = (
        "expression_urge_id",
        "expression_pressure",
        "expression_readiness",
        "expression_freshness",
        "seed_motive_strength",
        "candidate_kind",
        "speech_act",
    )
    return any(key in args for key in provenance_keys)


def _candidate_expression_drive(candidate: Any) -> float:
    """Chỉ dùng để chọn *speech nào*, không dùng để gate SPEAK/SILENCE."""
    args = _candidate_args(candidate)
    values: list[float] = []
    for keys in (
        ("expression_pressure", "pressure"),
        ("expression_freshness", "freshness"),
        ("seed_motive_strength", "motive_strength"),
        ("commitment_strength", "commitment"),
        ("identity_alignment",),
        ("concern_activation",),
    ):
        value = _float(args, *keys)
        if value is not None:
            values.append(max(0.0, min(1.0, value)))
    if not values:
        return 0.5 if _candidate_has_expression_object(candidate) else 0.0
    return sum(values) / len(values)


def _semantic_fingerprint(text: str) -> str:
    normalized = " ".join(_compact_text(text, 1200).lower().split())
    if not normalized:
        return ""
    # Không cần crypto; fingerprint chỉ để self-hold material stale vài chục giây.
    return normalized[:320]


def _candidate_fingerprint(candidate: Any) -> str:
    target, motive, material_id, intention_id = _semantic_payload(candidate)
    return _semantic_fingerprint(material_id or intention_id or target or motive)


def _held(candidate: Any) -> bool:
    now = time.monotonic()
    fp = _candidate_fingerprint(candidate)
    if not fp:
        return False
    with _LOCK:
        stale = [key for key, until in _SELF_HOLD_UNTIL.items() if until < now]
        for key in stale:
            _SELF_HOLD_UNTIL.pop(key, None)
        return _SELF_HOLD_UNTIL.get(fp, 0.0) >= now


def _hold_commitment(commitment: ExpressionCommitment) -> None:
    fp = _semantic_fingerprint(
        commitment.material_id or commitment.intention_id or commitment.semantic_target or commitment.motive_kind
    )
    if fp:
        with _LOCK:
            _SELF_HOLD_UNTIL[fp] = time.monotonic() + _REALIZATION_FAILURE_HOLD_SECONDS


def _candidate_requires_grounding(candidate: Any) -> bool:
    args = _candidate_args(candidate)
    if any(bool(args.get(key, False)) for key in ("requires_grounding", "grounding_required", "requires_evidence")):
        return True
    domain = _compact_text(args.get("claim_domain"), 100).lower()
    return domain in {"current_screen", "present_world", "environment", "live_vision"}


def _best_speech_index(frame: Any, selection: Any, eligible: Sequence[int] | None = None) -> int | None:
    coalitions = tuple(getattr(frame, "coalitions", ()) or ())
    indices = tuple(eligible or ()) or tuple(
        idx
        for idx, item in enumerate(coalitions)
        if _candidate_has_expression_object(item) and not _held(item)
    )
    if not indices:
        return None

    # Neuro scores vẫn có ích để phân biệt nội dung; expression drive chỉ là
    # tie-breaker. Không candidate nào phải vượt ngưỡng để "được nói".
    scores = tuple(getattr(selection, "scores", ()) or ())
    def rank(idx: int) -> tuple[float, float]:
        score = float(scores[idx]) if len(scores) > idx else 0.0
        return score, _candidate_expression_drive(coalitions[idx])
    return max(indices, key=rank)


def _best_non_speech_index(frame: Any, selection: Any) -> int | None:
    coalitions = tuple(getattr(frame, "coalitions", ()) or ())
    indices = tuple(
        idx for idx, item in enumerate(coalitions) if not _is_speech_action(_candidate_action(item))
    )
    if not indices:
        return None
    scores = tuple(getattr(selection, "scores", ()) or ())
    if len(scores) >= len(coalitions):
        return max(indices, key=lambda idx: float(scores[idx]))
    return indices[0]


def _winner_action(frame: Any, selection: Any) -> str:
    try:
        idx = int(getattr(selection, "winner_index"))
        return _candidate_action(tuple(getattr(frame, "coalitions", ()) or ())[idx])
    except Exception:
        return ""


def _replace_action(decision: Any, action_name: str, reason: str) -> Any:
    current = getattr(decision, "action", None)
    action_type = type(current)
    replacement: Any = action_name
    enum_name = action_name.upper()
    try:
        replacement = getattr(action_type, enum_name)
    except Exception:
        try:
            replacement = action_type(action_name)
        except Exception:
            pass
    try:
        return replace(decision, action=replacement, reason=reason)
    except Exception:
        return decision


def _initiative_reason(decision: Any) -> str:
    return _compact_text(getattr(decision, "reason", ""), 260).lower()


def _initiative_contentful(decision: Any) -> bool:
    return bool(getattr(decision, "contentful", False))


def _initiative_payload(decision: Any) -> tuple[str, str, float, float]:
    intention_id = _compact_text(getattr(decision, "intention_id", ""), 240)
    motive_kind = _compact_text(getattr(decision, "motive_kind", ""), 180)
    try:
        pressure = float(getattr(decision, "pressure", 0.0) or 0.0)
    except Exception:
        pressure = 0.0
    try:
        commitment = float(getattr(decision, "commitment", 0.0) or 0.0)
    except Exception:
        commitment = 0.0
    return intention_id, motive_kind, pressure, commitment


# Những lý do này là turn/runtime ownership thật hoặc self-restraint thật của Eris.
# Chúng được giữ. Ngược lại, startup cooldown/response rate/interruption cost không
# còn có quyền quyết định action family.
_HARD_WAIT_REASON_TOKENS = (
    "user_reply_expected",
    "user_or_runtime_busy",
    "interaction_busy",
    "active_user_turn",
    "abandonment_requires_restraint",
    "stale_low_value_intention",
    "no_contentful_object",
    "resource_guard",
    "overload",
)

_LEGACY_USER_CENTRIC_TOKENS = (
    "startup_social_cooldown",
    "recent_unsolicited_speech",
    "initiative_not_worth_interrupting_yet",
    "interruption",
    "response_rate",
    "social_refractory",
    "low_familiarity",
    "low_engagement",
)


def _is_hard_wait_reason(reason: str) -> bool:
    return any(token in reason for token in _HARD_WAIT_REASON_TOKENS)


def _is_legacy_user_centric_reason(reason: str) -> bool:
    return any(token in reason for token in _LEGACY_USER_CENTRIC_TOKENS)


# ---------------------------------------------------------------------------
# Commitment state
# ---------------------------------------------------------------------------

def _purge_expired() -> None:
    global _ACTIVE_COMMITMENT
    now = time.monotonic()
    with _LOCK:
        if _ACTIVE_COMMITMENT is not None and not _ACTIVE_COMMITMENT.active:
            _ACTIVE_COMMITMENT = None
        stale = [key for key, until in _SELF_HOLD_UNTIL.items() if until < now]
        for key in stale:
            _SELF_HOLD_UNTIL.pop(key, None)


def _current_commitment() -> ExpressionCommitment | None:
    _purge_expired()
    with _LOCK:
        return _ACTIVE_COMMITMENT


def _set_commitment(commitment: ExpressionCommitment) -> ExpressionCommitment:
    global _ACTIVE_COMMITMENT
    with _LOCK:
        _ACTIVE_COMMITMENT = commitment
    return commitment


def _ensure_commitment_from_initiative(decision: Any, *, force: bool = False) -> ExpressionCommitment:
    intention_id, motive_kind, _, _ = _initiative_payload(decision)
    current = _current_commitment()
    if current is not None and intention_id and current.intention_id == intention_id:
        current.force = current.force or force
        current.expires_at = time.monotonic() + _COMMITMENT_TTL_SECONDS
        return current
    now = time.monotonic()
    return _set_commitment(
        ExpressionCommitment(
            commitment_id=f"expression:{uuid.uuid4().hex}",
            created_at=now,
            expires_at=now + _COMMITMENT_TTL_SECONDS,
            intention_id=intention_id,
            motive_kind=motive_kind,
            reason="initiative:self_owned_contentful_intention",
            force=force,
        )
    )


def _ensure_commitment_from_candidate(candidate: Any, *, force: bool = False) -> ExpressionCommitment:
    target, motive, material_id, intention_id = _semantic_payload(candidate)
    current = _current_commitment()
    candidate_keys = {key for key in (intention_id, material_id) if key}
    current_keys = set()
    if current is not None:
        current_keys = {key for key in (current.intention_id, current.material_id) if key}
    if current is not None and (not candidate_keys or not current_keys or candidate_keys & current_keys):
        current.semantic_target = target or current.semantic_target
        current.motive_kind = motive or current.motive_kind
        current.material_id = material_id or current.material_id
        current.intention_id = intention_id or current.intention_id
        current.force = current.force or force
        current.expires_at = time.monotonic() + _COMMITMENT_TTL_SECONDS
        if current.state is ExpressionState.REVISION_REQUIRED:
            current.state = ExpressionState.COMMITTED
        return current

    now = time.monotonic()
    return _set_commitment(
        ExpressionCommitment(
            commitment_id=f"expression:{uuid.uuid4().hex}",
            created_at=now,
            expires_at=now + _COMMITMENT_TTL_SECONDS,
            intention_id=intention_id,
            motive_kind=motive,
            material_id=material_id,
            semantic_target=target,
            reason="candidate:self_owned_expression_object",
            force=force,
        )
    )


def _abandon(commitment: ExpressionCommitment | None, reason: str, logger: Any = None) -> None:
    global _ACTIVE_COMMITMENT
    if commitment is None:
        return
    commitment.state = ExpressionState.ABANDONED
    with _LOCK:
        if _ACTIVE_COMMITMENT is commitment:
            _ACTIVE_COMMITMENT = None
    if logger is not None:
        logger.info("[expression-commitment] abandoned id=%s reason=%s", commitment.commitment_id, reason)


def _mark_deferred(commitment: ExpressionCommitment, reason: str, logger: Any = None) -> None:
    commitment.state = ExpressionState.DEFERRED
    commitment.reason = reason
    if logger is not None:
        logger.info("[expression-commitment] deferred id=%s reason=%s", commitment.commitment_id, reason)


def _mark_realized(commitment: ExpressionCommitment, logger: Any = None) -> None:
    global _ACTIVE_COMMITMENT
    commitment.state = ExpressionState.REALIZED
    _RHYTHM.note_realized()
    with _LOCK:
        if _ACTIVE_COMMITMENT is commitment:
            _ACTIVE_COMMITMENT = None
    if logger is not None:
        tokens, _ = _RHYTHM.snapshot()
        logger.info(
            "[expression-commitment] realized id=%s rhythm_tokens=%.2f",
            commitment.commitment_id,
            tokens,
        )


def _arm_force() -> None:
    global _FORCE_PENDING_UNTIL
    with _LOCK:
        _FORCE_PENDING_UNTIL = time.monotonic() + _FORCE_TTL_SECONDS


def _force_pending() -> bool:
    with _LOCK:
        return time.monotonic() <= _FORCE_PENDING_UNTIL


def _consume_force() -> None:
    global _FORCE_PENDING_UNTIL
    with _LOCK:
        _FORCE_PENDING_UNTIL = 0.0


# ---------------------------------------------------------------------------
# Executive normalization
# ---------------------------------------------------------------------------

def _normalize_appraisal(frame: Any, appraisal: Any) -> Any:
    """Gỡ user-centric restraint khỏi semantic critic.

    Executive vẫn chấm motive/novelty/coherence/epistemic support. Nhưng khi runtime
    không có explicit boundary, boundary_pressure và interruption_cost không được
    dùng như một giả-boundary chỉ vì căn phòng đang yên.
    """
    if appraisal is None:
        return appraisal
    blocked, _ = _hard_boundary(frame)
    if blocked:
        return appraisal
    reason = _compact_text(getattr(appraisal, "reason", ""), 1200)
    note = "expression_commitment:executive_critic_only"
    if note not in reason:
        reason = f"{reason}; {note}".strip("; ")
    try:
        return replace(
            appraisal,
            boundary_pressure=0.0,
            interruption_cost=0.0,
            reason=reason,
        )
    except Exception:
        return appraisal


def _eligible_after_appraisal(frame: Any, appraisal: Any) -> tuple[int, ...]:
    """Chỉ grounding thật được phép loại speech candidate ở semantic review."""
    coalitions = tuple(getattr(frame, "coalitions", ()) or ())
    choices = tuple(getattr(appraisal, "choices", ()) or ())
    by_index = {int(getattr(item, "index", -1)): item for item in choices}
    eligible: list[int] = []
    for idx, candidate in enumerate(coalitions):
        if not _candidate_has_expression_object(candidate) or _held(candidate):
            continue
        if not _candidate_requires_grounding(candidate):
            eligible.append(idx)
            continue
        choice = by_index.get(idx)
        try:
            epistemic = float(getattr(choice, "epistemic_support", 0.0) or 0.0)
        except Exception:
            epistemic = 0.0
        if epistemic >= 0.50:
            eligible.append(idx)
    return tuple(eligible)


# ---------------------------------------------------------------------------
# Surface binding
# ---------------------------------------------------------------------------

def _replace_known_dataclass(obj: Any, updates: Mapping[str, Any]) -> Any:
    if obj is None or not is_dataclass(obj):
        return obj
    names = {item.name for item in fields(obj)}
    filtered = {key: value for key, value in updates.items() if key in names and value not in (None, "")}
    if not filtered:
        return obj
    try:
        return replace(obj, **filtered)
    except Exception:
        return obj


def _bind_surface_intent(intent: Any, commitment: ExpressionCommitment) -> Any:
    """Surface phải viết đúng semantic object đã commit, không quay về seed cũ."""
    target = _compact_text(commitment.semantic_target)
    motive = _compact_text(commitment.motive_kind, 360)
    material_id = _compact_text(commitment.material_id, 240)
    plan = getattr(intent, "plan", None)
    if plan is not None:
        plan = _replace_known_dataclass(
            plan,
            {
                "topic": target,
                "subject": target,
                "semantic_target": target,
                "motive": motive,
                "material_id": material_id,
            },
        )
        intent = _replace_known_dataclass(intent, {"plan": plan})
    intent = _replace_known_dataclass(
        intent,
        {
            "semantic_target": target,
            "subject": target,
            "material_id": material_id,
        },
    )
    return intent


def _surface_succeeded(result: Any) -> bool:
    if result is None:
        return False
    mode = _action_name(getattr(result, "mode", ""))
    payload = getattr(result, "public_payload", None)
    return mode not in {"", "silence", "surface_unavailable", "unavailable"} and bool(payload)


def _surface_failure_reason(result: Any, engine: Any) -> str:
    return _compact_text(
        getattr(result, "reason", "") or getattr(engine, "last_failure_reason", "") or "unknown",
        500,
    )


# ---------------------------------------------------------------------------
# Self-model cleanup
# ---------------------------------------------------------------------------

def _rewrite_self_model_rules(logger: Any = None) -> None:
    """Đưa triết lý vào identity layer thay vì chỉ sửa output gate."""
    try:
        from cortex.self_model import SelfModelEngine

        core = getattr(SelfModelEngine, "IDENTITY_CORE", None)
        if core is None:
            return
        rules = tuple(getattr(core, "rules", ()) or ())
        remove = {
            "speak_less_without_affordance",
            "silence_can_preserve_continuity",
        }
        additions = (
            "expression_originates_in_self",
            "restraint_originates_in_self",
            "user_quiet_is_not_a_boundary",
            "explicit_boundary_only",
            "pacing_preserves_expression_weight",
            "committed_expression_survives_downstream_review",
        )
        rebuilt = tuple(rule for rule in rules if str(rule) not in remove)
        for rule in additions:
            if rule not in rebuilt:
                rebuilt += (rule,)
        if rebuilt != rules:
            SelfModelEngine.IDENTITY_CORE = replace(core, rules=rebuilt)
            if logger is not None:
                logger.info(
                    "[expression-commitment] self-model rewritten removed=%s added=%s",
                    sorted(remove.intersection(set(map(str, rules)))),
                    list(additions),
                )
    except Exception as exc:
        if logger is not None:
            logger.warning("[expression-commitment] self-model cleanup skipped: %s", exc)


# ---------------------------------------------------------------------------
# Bootstrap adapter
# ---------------------------------------------------------------------------

def install_expression_commitment_authority(logger: Any = None) -> None:
    """Cài V65 vào compiled runtime.

    Ownership sau V65:
    - InitiativeArbiter: materialize self-owned ExpressionCommitment.
    - ExpressionRhythm: quyết định DEFER theo mật độ lời của Eris.
    - Neuro: chọn speech content khi commitment đang active.
    - Executive: critic/grounding only.
    - Surface: realization only.
    - Runtime: explicit boundary / turn collision only.
    """

    global _PATCHED
    if _PATCHED:
        return

    from cortex.subject.initiative_control import InitiativeArbiter
    from cortex.subject.neuro_control import NeuroActionSelector
    from runtime.ai_orchestrated.executive_cortex import ExecutiveCortex
    from runtime.ai_orchestrated.surface_intent import SurfaceIntentEngine
    from runtime.chat_cycle import ChatCycleMixin
    from runtime.expression_urge_runtime import ExpressionUrgeRuntime
    from runtime.user_control_runtime import UserControlRuntimeMixin

    original_initiative_decide = InitiativeArbiter.decide
    original_select = NeuroActionSelector.select
    original_merge = NeuroActionSelector.merge_semantic_appraisal
    original_remote_appraise = ExecutiveCortex._appraise_autonomous_frame
    original_local_appraise = ExecutiveCortex._local_autonomous_semantic_appraisal
    original_realize = SurfaceIntentEngine.realize
    original_note_duplicate = ExpressionUrgeRuntime.note_surface_duplicate
    original_force = UserControlRuntimeMixin._handle_force_speak_request
    original_block_after_public = ChatCycleMixin._block_autonomous_presence_after_public_turn

    def initiative_decide_expression_owned(self: Any, *args: Any, **kwargs: Any) -> Any:
        decision = original_initiative_decide(self, *args, **kwargs)
        action = _action_name(getattr(decision, "action", ""))
        reason = _initiative_reason(decision)
        contentful = _initiative_contentful(decision)

        # DROP vì không còn object/stale là self-restraint hợp lệ. Không cứu một
        # intention mà chính cognition đã bỏ.
        if action == "drop":
            return decision
        if not contentful:
            return decision

        commitment = _ensure_commitment_from_initiative(decision, force=_force_pending())

        # Busy/user reply expected là turn collision thật. Abandonment/overload là
        # restraint của Eris. Giữ WAIT nhưng commitment không bị diễn giải thành
        # "user không muốn nghe".
        if _is_hard_wait_reason(reason):
            _mark_deferred(commitment, f"self_or_turn_defer:{reason}", logger)
            return decision

        rhythm = _RHYTHM.decide(force=commitment.force or _force_pending())
        if not rhythm.allow:
            _mark_deferred(commitment, f"expression_rhythm:{rhythm.reason}", logger)
            return _replace_action(
                decision,
                "wait",
                f"expression_rhythm:{rhythm.reason}:tokens={rhythm.tokens:.2f}",
            )

        # Đây là cleanup quan trọng: startup cooldown, response rate, refractory,
        # interruption cost... không còn sở hữu action family. Nếu cognition đã có
        # intention contentful thì SPEAK là quyết định của Eris.
        if action != "speak" or _is_legacy_user_centric_reason(reason):
            commitment.state = ExpressionState.COMMITTED
            commitment.reason = "initiative:self_owned_expression"
            if logger is not None:
                logger.info(
                    "[expression-commitment] initiative commit id=%s old_action=%s old_reason=%s",
                    commitment.commitment_id,
                    action,
                    reason or "none",
                )
            return _replace_action(decision, "speak", "expression_commitment:self_owned")

        commitment.state = ExpressionState.COMMITTED
        return decision

    def select_with_commitment(self: Any, frame: Any) -> Any:
        baseline = original_select(self, frame)
        if not _is_autonomous_frame(frame):
            return baseline
        blocked, boundary_reason = _hard_boundary(frame)
        if blocked:
            commitment = _current_commitment()
            if commitment is not None:
                _mark_deferred(commitment, f"runtime_boundary:{boundary_reason}", logger)
            return baseline

        coalitions = tuple(getattr(frame, "coalitions", ()) or ())
        speech_indices = tuple(
            idx
            for idx, candidate in enumerate(coalitions)
            if _candidate_has_expression_object(candidate) and not _held(candidate)
        )
        if not speech_indices:
            return baseline

        force = _force_pending()
        best = _best_speech_index(frame, baseline, speech_indices)
        if best is None:
            return baseline
        commitment = _ensure_commitment_from_candidate(coalitions[best], force=force)

        rhythm = _RHYTHM.decide(force=commitment.force or force)
        if not rhythm.allow:
            _mark_deferred(commitment, f"expression_rhythm:{rhythm.reason}", logger)
            if not _is_speech_action(_winner_action(frame, baseline)):
                return baseline
            idx = _best_non_speech_index(frame, baseline)
            if idx is None:
                return baseline
            try:
                return replace(
                    baseline,
                    winner_index=idx,
                    requires_deliberation=False,
                    parallel_review_recommended=False,
                    reason=f"expression_rhythm_defer:{rhythm.reason}",
                )
            except Exception:
                return baseline

        commitment.state = ExpressionState.COMMITTED
        if force:
            _consume_force()
        if _is_speech_action(_winner_action(frame, baseline)):
            return baseline
        try:
            chosen = replace(
                baseline,
                winner_index=best,
                requires_deliberation=False,
                parallel_review_recommended=False,
                reason=f"expression_commitment:{commitment.commitment_id}",
            )
        except Exception:
            chosen = baseline
        if logger is not None:
            logger.info(
                "[expression-commitment] neuro family=speak id=%s candidate=%s",
                commitment.commitment_id,
                best,
            )
        return chosen

    def remote_appraise_expression_owned(self: Any, frame: Any, selection: Any) -> Any:
        return _normalize_appraisal(frame, original_remote_appraise(self, frame, selection))

    def local_appraise_expression_owned(self: Any, frame: Any, selection: Any) -> Any:
        return _normalize_appraisal(frame, original_local_appraise(self, frame, selection))

    def merge_with_commitment(self: Any, frame: Any, baseline: Any, appraisal: Any) -> Any:
        normalized = _normalize_appraisal(frame, appraisal)
        merged = original_merge(self, frame, baseline, normalized)
        commitment = _current_commitment()
        if commitment is None or not _is_autonomous_frame(frame):
            return merged

        blocked, boundary_reason = _hard_boundary(frame)
        if blocked:
            _mark_deferred(commitment, f"runtime_boundary:{boundary_reason}", logger)
            return merged

        eligible = _eligible_after_appraisal(frame, normalized)
        if not eligible:
            # Grounding failure không biến thành "silence won". Commitment sống để
            # cognition/surface có thể revise semantic target ở vòng sau.
            commitment.state = ExpressionState.REVISION_REQUIRED
            commitment.reason = "revision_required:grounding"
            if logger is not None:
                logger.info(
                    "[expression-commitment] revision id=%s reason=grounding",
                    commitment.commitment_id,
                )
            return merged

        if _is_speech_action(_winner_action(frame, merged)):
            return merged
        idx = _best_speech_index(frame, merged, eligible)
        if idx is None:
            return merged
        try:
            preserved = replace(
                merged,
                winner_index=idx,
                requires_deliberation=False,
                parallel_review_recommended=False,
                reason=f"expression_commitment_preserve:{commitment.commitment_id}",
            )
        except Exception:
            preserved = merged
        if logger is not None:
            logger.info(
                "[expression-commitment] executive=critic_only id=%s winner=%s",
                commitment.commitment_id,
                idx,
            )
        return preserved

    def realize_with_commitment(
        self: Any,
        intent: Any,
        blackboard: Any,
        *,
        snapshot: Any = None,
        avoid_text: str = "",
    ) -> Any:
        commitment = _current_commitment()
        bound = intent
        if commitment is not None:
            commitment.state = ExpressionState.REALIZING
            bound = _bind_surface_intent(intent, commitment)
        result = original_realize(
            self,
            bound,
            blackboard,
            snapshot=snapshot,
            avoid_text=avoid_text,
        )
        if commitment is None:
            return result
        if _surface_succeeded(result):
            _mark_realized(commitment, logger)
            return result

        reason = _surface_failure_reason(result, self)
        commitment.realization_failures += 1
        commitment.state = ExpressionState.REVISION_REQUIRED
        commitment.reason = f"revision_required:{reason}"
        if "surface_duplicate_recent_utterance" in reason:
            if commitment.realization_failures >= _MAX_DUPLICATE_REALIZATION_FAILURES:
                _hold_commitment(commitment)
                _abandon(commitment, "self_hold_after_duplicate_realization", logger)
            elif logger is not None:
                logger.info(
                    "[expression-commitment] surface revise id=%s reason=duplicate attempts=%s",
                    commitment.commitment_id,
                    commitment.realization_failures,
                )
        elif logger is not None:
            logger.info(
                "[expression-commitment] surface revise id=%s reason=%s",
                commitment.commitment_id,
                reason,
            )
        return result

    def note_duplicate_expression_owned(self: Any, urge_id: str, now: float) -> Any:
        commitment = _current_commitment()
        if commitment is not None and commitment.state in {
            ExpressionState.REALIZING,
            ExpressionState.REVISION_REQUIRED,
        }:
            # Surface vừa thất bại về wording. Không được biến lỗi writer thành
            # 90 giây suppression của ý định Eris.
            if logger is not None:
                logger.info(
                    "[expression-commitment] duplicate wording ignored for urge=%s commitment=%s",
                    _compact_text(urge_id, 160),
                    commitment.commitment_id,
                )
            return None
        return original_note_duplicate(self, urge_id, now)

    def handle_force_expression(self: Any) -> Any:
        _arm_force()
        try:
            setattr(self, "autonomous_presence_blocked_until", 0.0)
        except Exception:
            pass
        try:
            setattr(self, "_autonomous_force_speak_pending", True)
        except Exception:
            pass
        if logger is not None:
            logger.info("[expression-commitment] force debug override armed ttl=%.0fs", _FORCE_TTL_SECONDS)
        return original_force(self)

    def block_after_public_turn_as_collision_only(self: Any, *args: Any, **kwargs: Any) -> Any:
        result = original_block_after_public(self, *args, **kwargs)
        try:
            until = float(getattr(self, "autonomous_presence_blocked_until", 0.0) or 0.0)
            if until > 0.0:
                wall = time.time()
                mono = time.monotonic()
                now = wall if abs(until - wall) < abs(until - mono) else mono
                cap = now + _TURN_COLLISION_GRACE_SECONDS
                if until > cap:
                    setattr(self, "autonomous_presence_blocked_until", cap)
                    if logger is not None:
                        logger.info(
                            "[expression-rhythm] legacy post-chat grace clamped to %.1fs collision-only",
                            _TURN_COLLISION_GRACE_SECONDS,
                        )
        except Exception:
            pass
        return result

    InitiativeArbiter.decide = initiative_decide_expression_owned
    NeuroActionSelector.select = select_with_commitment
    ExecutiveCortex._appraise_autonomous_frame = remote_appraise_expression_owned
    ExecutiveCortex._local_autonomous_semantic_appraisal = local_appraise_expression_owned
    NeuroActionSelector.merge_semantic_appraisal = merge_with_commitment
    SurfaceIntentEngine.realize = realize_with_commitment
    ExpressionUrgeRuntime.note_surface_duplicate = note_duplicate_expression_owned
    UserControlRuntimeMixin._handle_force_speak_request = handle_force_expression
    ChatCycleMixin._block_autonomous_presence_after_public_turn = block_after_public_turn_as_collision_only

    _rewrite_self_model_rules(logger)
    _PATCHED = True
    if logger is not None:
        logger.info(
            "[expression-commitment] V65 active: expression is self-owned; "
            "user quiet/cooldown/response-rate do not own speech authority; "
            "pacing is Eris self-rhythm"
        )


__all__ = [
    "ExpressionCommitment",
    "ExpressionRhythm",
    "ExpressionState",
    "RhythmDecision",
    "install_expression_commitment_authority",
]
