"""ERIS V64 - Speech Lease Authority.

Mục tiêu kiến trúc
==================
Một quyết định chỉ có một chủ sở hữu:

- SpeechLeaseAuthority: quyết định một ý định speech đã đủ điều kiện để giữ quyền nói hay chưa.
- Neuro: xếp hạng *nội dung speech nào* thắng khi lease đã tồn tại.
- Executive: critique về coherence / grounding / boundary thật; không được đổi action family vì quiet.
- Surface: viết câu từ semantic target đã khóa; không được dùng lỗi duplicate như một quyết định SILENCE.
- Runtime: giữ các hard boundary thật (user đang chiếm lượt, explicit quiet, shutdown...).

Source bundle hiện tại phát hành phần lớn runtime dưới dạng .pyc, vì vậy module này
cài adapter ở bootstrap thay vì sửa bytecode. Adapter chỉ thay quyền sở hữu quyết
định; nó không sửa trọng số appraisal và không bơm bias speak vào model.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Mapping, Sequence


# Lease ngắn hơn một vòng autonomous bình thường nhưng đủ để đi qua semantic review
# và Surface. Lease được consume khi Surface thành công, không phải ngay khi Neuro vote.
_LEASE_TTL_SECONDS = 45.0
_FORCE_TTL_SECONDS = 30.0
_PATCHED = False
_LOCK = threading.RLock()
_FORCE_PENDING_UNTIL = 0.0


class LeaseDecision(str, Enum):
    """Ba trạng thái authority hiểu được trước khi Neuro xếp hạng."""

    SPEAK = "speak"
    WAIT = "wait"
    UNCLAIMED = "unclaimed"


@dataclass(frozen=True)
class SpeechLease:
    """Quyền hiện thực hóa *một action family SPEAK* trong một frame.

    Lease khóa semantic target/motive để downstream không vô tình viết lại một
    intent cũ. Nó không chứa public wording và không tự tạo factual claim.
    """

    lease_id: str
    frame_id: str
    issued_at: float
    expires_at: float
    reason: str
    force: bool
    speech_indices: tuple[int, ...]
    semantic_target: str = ""
    motive: str = ""
    material_id: str = ""

    @property
    def active(self) -> bool:
        return time.monotonic() <= self.expires_at


@dataclass(frozen=True)
class LeaseEvaluation:
    decision: LeaseDecision
    reason: str
    speech_indices: tuple[int, ...] = ()
    semantic_target: str = ""
    motive: str = ""
    material_id: str = ""


_ACTIVE_BY_FRAME: dict[str, SpeechLease] = {}
_ACTIVE_SURFACE: SpeechLease | None = None
_WAIT_BY_FRAME: dict[str, float] = {}


# ------------------------------ helpers thuần ------------------------------

def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _compact_text(value: Any, limit: int = 900) -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:limit]


def _candidate_action(candidate: Any) -> str:
    return str(getattr(candidate, "action_kind", "") or "").strip().lower()


def _is_speech_action(action: str) -> bool:
    # Autonomous hiện dùng "speak"; giữ prefix để không gãy nếu runtime thêm
    # speak_from_* nhưng vẫn cùng action family.
    return action == "speak" or action.startswith("speak_")


def _candidate_args(candidate: Any) -> Mapping[str, Any]:
    return _mapping(getattr(candidate, "arguments", None))


def _frame_id(frame: Any) -> str:
    return str(getattr(frame, "frame_id", "") or f"frame:{id(frame)}")


def _frame_context(frame: Any) -> Mapping[str, Any]:
    observation = getattr(frame, "observation", None)
    for value in (
        getattr(observation, "context", None),
        getattr(frame, "context", None),
        getattr(frame, "runtime_context", None),
    ):
        if isinstance(value, Mapping):
            return value
    return {}


def _hard_boundary(frame: Any) -> tuple[bool, str]:
    """Chỉ nhận boundary có evidence runtime, không suy từ sự im lặng.

    Không có key kiểu ``no_user_text``, ``low_familiarity`` hay generic cooldown ở
    đây. User không gõ gì đơn giản là không có input mới, không phải yêu cầu Eris im.
    """

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
            continue
    return None


def _speech_strength(candidate: Any) -> tuple[float, bool]:
    """Đọc typed initiative signals đã có, không dùng score silence của Neuro.

    ``typed=True`` nghĩa candidate mang đủ dấu vết để authority quyết định. Nếu
    runtime cũ không có các field này, ta trả UNCLAIMED thay vì đoán bừa.
    """

    args = _candidate_args(candidate)
    weighted: list[tuple[float, float]] = []
    typed = False

    def add(keys: Sequence[str], weight: float) -> None:
        nonlocal typed
        value = _float(args, *keys)
        if value is None:
            return
        typed = True
        weighted.append((max(0.0, min(1.0, value)), weight))

    add(("expression_readiness",), 1.35)
    add(("expression_pressure", "pressure"), 1.15)
    add(("expression_freshness", "freshness"), 0.90)
    add(("seed_motive_strength", "motive_strength"), 1.15)

    # satisfaction cao nghĩa urge đã được giải tỏa, nên đây là tín hiệu ngược.
    satisfaction = _float(args, "expression_satisfaction", "satisfaction")
    if satisfaction is not None:
        typed = True
        weighted.append((1.0 - max(0.0, min(1.0, satisfaction)), 0.65))

    # initiative policy đã tính pacing/cadence. Dùng nó như pacing cost, không gọi
    # sự im lặng của user là "interruption".
    policy_cost = _float(args, "initiative_policy_cost", "policy_cost")
    max_cost = _float(args, "initiative_policy_max_cost")
    if policy_cost is not None:
        typed = True
        denom = max(0.001, max_cost if max_cost and max_cost > 0 else 1.0)
        normalized = max(0.0, min(1.0, policy_cost / denom))
        weighted.append((1.0 - normalized, 1.00))

    refractory = _float(args, "social_refractory_cost")
    if refractory is not None:
        typed = True
        weighted.append((1.0 - max(0.0, min(1.0, refractory)), 0.70))

    # Presence của typed motive/target là evidence nhị phân nhỏ. Nó không đủ tự
    # cấp lease, nhưng tránh việc một intent đầy đủ bị xem như scheduler noise.
    for key in (
        "expression_urge_id",
        "initiative_motive",
        "semantic_target",
        "candidate_kind",
        "speech_act",
        "material_id",
    ):
        if _compact_text(args.get(key)):
            typed = True
            weighted.append((1.0, 0.18))

    if not weighted:
        return 0.0, typed
    total_w = sum(weight for _, weight in weighted)
    score = sum(value * weight for value, weight in weighted) / max(total_w, 0.001)
    return max(0.0, min(1.0, score)), typed


def _semantic_payload(candidate: Any) -> tuple[str, str, str]:
    args = _candidate_args(candidate)
    target = ""
    for key in ("semantic_target", "topic", "content", "subject"):
        target = _compact_text(args.get(key))
        if target:
            break
    motive = ""
    for key in ("initiative_motive", "motive", "why_now", "candidate_kind"):
        motive = _compact_text(args.get(key), 360)
        if motive:
            break
    material_id = _compact_text(
        args.get("material_id") or args.get("expression_urge_id") or args.get("proposal_ref"),
        240,
    )
    return target, motive, material_id


def _best_speech_index(frame: Any, selection: Any, eligible: Sequence[int] | None = None) -> int | None:
    coalitions = tuple(getattr(frame, "coalitions", ()) or ())
    indices = tuple(eligible or ()) or tuple(
        idx for idx, item in enumerate(coalitions) if _is_speech_action(_candidate_action(item))
    )
    if not indices:
        return None
    scores = tuple(getattr(selection, "scores", ()) or ())
    if len(scores) >= len(coalitions):
        return max(indices, key=lambda idx: float(scores[idx]))
    return indices[0]


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


def _candidate_requires_grounding(candidate: Any) -> bool:
    args = _candidate_args(candidate)
    if any(bool(args.get(key, False)) for key in ("requires_grounding", "grounding_required", "requires_evidence")):
        return True
    domain = str(args.get("claim_domain", "") or "").strip().lower()
    return domain in {"current_screen", "present_world", "environment", "live_vision"}


def _eligible_after_appraisal(frame: Any, appraisal: Any, lease: SpeechLease) -> tuple[int, ...]:
    """Executive được loại speech candidate thiếu grounding, nhưng không đổi family vì quiet."""

    choices = tuple(getattr(appraisal, "choices", ()) or ())
    by_index = {int(getattr(item, "index", -1)): item for item in choices}
    coalitions = tuple(getattr(frame, "coalitions", ()) or ())
    eligible: list[int] = []
    for idx in lease.speech_indices:
        if idx >= len(coalitions):
            continue
        candidate = coalitions[idx]
        if not _candidate_requires_grounding(candidate):
            eligible.append(idx)
            continue
        choice = by_index.get(idx)
        epistemic = float(getattr(choice, "epistemic_support", 0.0) or 0.0) if choice is not None else 0.0
        if epistemic >= 0.50:
            eligible.append(idx)
    return tuple(eligible)


class SpeechLeaseAuthority:
    """Authority duy nhất cấp quyền chuyển action family sang SPEAK."""

    # Threshold chỉ áp trên typed initiative signals. Nó không liên quan đến
    # Neuro silence score hay Executive interruption_cost.
    READY_THRESHOLD = 0.58

    def evaluate(self, frame: Any, *, force: bool = False) -> LeaseEvaluation:
        blocked, reason = _hard_boundary(frame)
        if blocked:
            return LeaseEvaluation(LeaseDecision.WAIT, f"hard_boundary:{reason}")

        coalitions = tuple(getattr(frame, "coalitions", ()) or ())
        speech_indices = tuple(
            idx for idx, item in enumerate(coalitions) if _is_speech_action(_candidate_action(item))
        )
        if not speech_indices:
            return LeaseEvaluation(LeaseDecision.WAIT, "no_speech_candidate")

        if force:
            best = speech_indices[0]
            target, motive, material_id = _semantic_payload(coalitions[best])
            return LeaseEvaluation(
                LeaseDecision.SPEAK,
                "force_speak",
                speech_indices,
                target,
                motive,
                material_id,
            )

        ranked: list[tuple[float, int, bool]] = []
        any_typed = False
        for idx in speech_indices:
            score, typed = _speech_strength(coalitions[idx])
            any_typed = any_typed or typed
            ranked.append((score, idx, typed))

        # Runtime cũ thiếu typed initiative signals: không tự phát minh policy mới.
        # Khi đó adapter không claim action family và để legacy selector hoạt động.
        if not any_typed:
            return LeaseEvaluation(LeaseDecision.UNCLAIMED, "legacy_frame_without_typed_initiative")

        score, best_idx, _ = max(ranked, key=lambda item: item[0])
        if score < self.READY_THRESHOLD:
            return LeaseEvaluation(LeaseDecision.WAIT, f"pacing_wait:{score:.3f}")

        target, motive, material_id = _semantic_payload(coalitions[best_idx])
        return LeaseEvaluation(
            LeaseDecision.SPEAK,
            f"typed_initiative_ready:{score:.3f}",
            speech_indices,
            target,
            motive,
            material_id,
        )

    def issue(self, frame: Any, evaluation: LeaseEvaluation, *, force: bool = False) -> SpeechLease:
        now = time.monotonic()
        lease = SpeechLease(
            lease_id=f"speech-lease:{uuid.uuid4().hex}",
            frame_id=_frame_id(frame),
            issued_at=now,
            expires_at=now + _LEASE_TTL_SECONDS,
            reason=evaluation.reason,
            force=bool(force),
            speech_indices=tuple(evaluation.speech_indices),
            semantic_target=evaluation.semantic_target,
            motive=evaluation.motive,
            material_id=evaluation.material_id,
        )
        global _ACTIVE_SURFACE
        with _LOCK:
            _ACTIVE_BY_FRAME[lease.frame_id] = lease
            _ACTIVE_SURFACE = lease
        return lease


_AUTHORITY = SpeechLeaseAuthority()


# ------------------------------ lease state ------------------------------

def _purge_expired() -> None:
    global _ACTIVE_SURFACE
    now = time.monotonic()
    with _LOCK:
        stale = [key for key, value in _ACTIVE_BY_FRAME.items() if value.expires_at < now]
        for key in stale:
            _ACTIVE_BY_FRAME.pop(key, None)
        if _ACTIVE_SURFACE is not None and _ACTIVE_SURFACE.expires_at < now:
            _ACTIVE_SURFACE = None
        stale_wait = [key for key, expiry in _WAIT_BY_FRAME.items() if expiry < now]
        for key in stale_wait:
            _WAIT_BY_FRAME.pop(key, None)


def _lease_for_frame(frame: Any) -> SpeechLease | None:
    _purge_expired()
    with _LOCK:
        return _ACTIVE_BY_FRAME.get(_frame_id(frame))


def _surface_lease() -> SpeechLease | None:
    _purge_expired()
    with _LOCK:
        return _ACTIVE_SURFACE


def _mark_wait(frame: Any) -> None:
    with _LOCK:
        _WAIT_BY_FRAME[_frame_id(frame)] = time.monotonic() + _LEASE_TTL_SECONDS


def _wait_for_frame(frame: Any) -> bool:
    _purge_expired()
    with _LOCK:
        return _WAIT_BY_FRAME.get(_frame_id(frame), 0.0) >= time.monotonic()


def _revoke(lease: SpeechLease, reason: str, logger: Any = None) -> None:
    global _ACTIVE_SURFACE
    with _LOCK:
        _ACTIVE_BY_FRAME.pop(lease.frame_id, None)
        if _ACTIVE_SURFACE is not None and _ACTIVE_SURFACE.lease_id == lease.lease_id:
            _ACTIVE_SURFACE = None
    if logger is not None:
        logger.info("[speech-lease] revoked id=%s reason=%s", lease.lease_id, reason)


def _consume_surface_success(lease: SpeechLease, logger: Any = None) -> None:
    global _ACTIVE_SURFACE
    with _LOCK:
        _ACTIVE_BY_FRAME.pop(lease.frame_id, None)
        if _ACTIVE_SURFACE is not None and _ACTIVE_SURFACE.lease_id == lease.lease_id:
            _ACTIVE_SURFACE = None
    if logger is not None:
        logger.info("[speech-lease] consumed id=%s outcome=surface_realized", lease.lease_id)


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


# ------------------------------ Surface binding ------------------------------

def _bind_surface_intent(intent: Any, lease: SpeechLease) -> Any:
    """Khóa Surface vào semantic target của lease nếu plan bị stale.

    Không viết public text ở đây. Ta chỉ sửa semantic plan đã có bằng dataclass
    replace; DeepSeek Surface vẫn là writer duy nhất.
    """

    target = _compact_text(lease.semantic_target)
    motive = _compact_text(lease.motive, 360)
    if not target and not motive:
        return intent

    plan = getattr(intent, "plan", None)
    if plan is None:
        return intent

    updates: dict[str, Any] = {}
    current_topic = _compact_text(getattr(plan, "topic", None))
    current_motive = _compact_text(getattr(plan, "motive", None), 360)
    if target and current_topic != target:
        updates["topic"] = target
    if motive and not current_motive:
        updates["motive"] = motive
    if not updates:
        return intent

    try:
        bound_plan = replace(plan, **updates)
        return replace(intent, plan=bound_plan)
    except Exception:
        # Future runtime đổi dataclass shape thì fail-open về object cũ; không bịa text.
        return intent


def _surface_succeeded(result: Any) -> bool:
    if result is None:
        return False
    mode = str(getattr(result, "mode", "") or "").strip().lower()
    payload = getattr(result, "public_payload", None)
    return mode not in {"", "silence", "surface_unavailable", "unavailable"} and bool(payload)


def _surface_duplicate_failure(result: Any, engine: Any) -> bool:
    reason = str(getattr(result, "reason", "") or getattr(engine, "last_failure_reason", "") or "")
    return "surface_duplicate_recent_utterance" in reason


# ------------------------------ bootstrap adapter ------------------------------

def install_speech_lease_authority(logger: Any = None) -> None:
    """Cài authority adapter lên runtime compiled hiện tại.

    Adapter có bốn hook, mỗi hook chỉ làm đúng một việc:
    1) Neuro.select: cấp/thi hành lease trước competition action-family.
    2) Neuro.merge: giữ SPEAK family qua semantic critique, trừ hard boundary/grounding.
    3) Surface.realize: bind đúng semantic target; duplicate không consume lease.
    4) ExpressionUrge: duplicate wording không được cooldown đúng urge đang có lease.
    5) force_speak: arm one-shot lease authority rồi để handler gốc wake scheduler.
    """

    global _PATCHED
    if _PATCHED:
        return

    from cortex.subject.neuro_control import NeuroActionSelector
    from runtime.ai_orchestrated.surface_intent import SurfaceIntentEngine
    from runtime.expression_urge_runtime import ExpressionUrgeRuntime
    from runtime.user_control_runtime import UserControlRuntimeMixin

    original_select = NeuroActionSelector.select
    original_merge = NeuroActionSelector.merge_semantic_appraisal
    original_realize = SurfaceIntentEngine.realize
    original_note_duplicate = ExpressionUrgeRuntime.note_surface_duplicate
    original_force = UserControlRuntimeMixin._handle_force_speak_request

    def select_with_lease(self: Any, frame: Any) -> Any:
        baseline = original_select(self, frame)
        force = _force_pending()
        evaluation = _AUTHORITY.evaluate(frame, force=force)

        if evaluation.decision is LeaseDecision.UNCLAIMED:
            return baseline
        if evaluation.decision is LeaseDecision.WAIT:
            # Typed frame đã được authority quyết định WAIT: downstream không được
            # tự promote ngược sang SPEAK. Neuro vẫn chọn body/silence nào hợp nhất.
            _mark_wait(frame)
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
                    reason=f"speech_lease_wait:{evaluation.reason}",
                )
            except Exception:
                return baseline

        lease = _AUTHORITY.issue(frame, evaluation, force=force)
        if force:
            _consume_force()

        action = _winner_action(frame, baseline)
        if _is_speech_action(action):
            if logger is not None:
                logger.info(
                    "[speech-lease] issued id=%s frame=%s reason=%s winner=already_speak",
                    lease.lease_id,
                    lease.frame_id,
                    lease.reason,
                )
            return baseline

        idx = _best_speech_index(frame, baseline, lease.speech_indices)
        if idx is None:
            _revoke(lease, "speech_candidate_disappeared", logger)
            return baseline
        try:
            result = replace(
                baseline,
                winner_index=idx,
                requires_deliberation=False,
                parallel_review_recommended=False,
                reason=f"speech_lease:{lease.reason}",
            )
        except Exception:
            result = baseline
        if logger is not None:
            logger.info(
                "[speech-lease] issued id=%s frame=%s reason=%s fast_family=speak",
                lease.lease_id,
                lease.frame_id,
                lease.reason,
            )
        return result

    def merge_with_lease(self: Any, frame: Any, baseline: Any, appraisal: Any) -> Any:
        merged = original_merge(self, frame, baseline, appraisal)
        lease = _lease_for_frame(frame)
        if lease is None:
            if _wait_for_frame(frame) and _is_speech_action(_winner_action(frame, merged)):
                idx = _best_non_speech_index(frame, merged)
                if idx is not None:
                    try:
                        return replace(
                            merged,
                            winner_index=idx,
                            requires_deliberation=False,
                            parallel_review_recommended=False,
                            reason="speech_lease_preserve_wait_family",
                        )
                    except Exception:
                        pass
            return merged

        blocked, boundary_reason = _hard_boundary(frame)
        boundary_pressure = float(getattr(appraisal, "boundary_pressure", 0.0) or 0.0)
        if blocked or boundary_pressure >= 0.55:
            boundary_label = boundary_reason or f"semantic_pressure:{boundary_pressure:.2f}"
            _revoke(lease, f"hard_boundary:{boundary_label}", logger)
            return merged

        eligible = _eligible_after_appraisal(frame, appraisal, lease)
        if not eligible:
            _revoke(lease, "all_speech_candidates_failed_grounding", logger)
            return merged

        # Executive appraisal vẫn tác động scores; chỉ quyền đổi action family bị khóa.
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
                reason=f"speech_lease_preserve_family:{lease.lease_id}",
            )
        except Exception:
            preserved = merged
        if logger is not None:
            logger.info(
                "[speech-lease] preserve family id=%s executive=critic_only winner=%s",
                lease.lease_id,
                idx,
            )
        return preserved

    def realize_with_lease(
        self: Any,
        intent: Any,
        blackboard: Any,
        *,
        snapshot: Any = None,
        avoid_text: str = "",
    ) -> Any:
        lease = _surface_lease()
        bound_intent = _bind_surface_intent(intent, lease) if lease is not None else intent
        result = original_realize(
            self,
            bound_intent,
            blackboard,
            snapshot=snapshot,
            avoid_text=avoid_text,
        )
        if lease is None:
            return result

        if _surface_succeeded(result):
            _consume_surface_success(lease, logger)
            return result

        if _surface_duplicate_failure(result, self):
            # Duplicate là realization failure, không phải một quyết định SILENCE.
            # Giữ lease tới expiry để nhịp kế tiếp có thể realize lại đúng semantic target.
            if logger is not None:
                logger.info(
                    "[speech-lease] surface deferred id=%s reason=duplicate lease_kept=1",
                    lease.lease_id,
                )
            return result

        # Các lỗi Surface khác cũng không được giả làm "user không muốn nghe".
        # Lease tự hết hạn; hard grounding vẫn do Surface/Executive chặn như cũ.
        if logger is not None:
            logger.info(
                "[speech-lease] surface unavailable id=%s lease_kept=1 reason=%s",
                lease.lease_id,
                str(getattr(result, "reason", "") or getattr(self, "last_failure_reason", "") or "unknown"),
            )
        return result

    def note_surface_duplicate_with_lease(self: Any, urge_id: str, now: float) -> Any:
        lease = _surface_lease()
        if lease is not None:
            lease_material = _compact_text(lease.material_id, 240)
            current_urge = _compact_text(urge_id, 240)
            # Nếu duplicate xảy ra trong đúng lease/urge hiện tại thì đây là lỗi
            # wording của Surface, không phải bằng chứng rằng intent đã "cũ".
            # Giữ urge sống để vòng kế tiếp có thể realize lại semantic target.
            if lease_material and current_urge and (
                lease_material == current_urge
                or lease_material.endswith(current_urge)
                or current_urge.endswith(lease_material)
            ):
                if logger is not None:
                    logger.info(
                        "[speech-lease] duplicate wording did not suppress urge id=%s lease=%s",
                        current_urge,
                        lease.lease_id,
                    )
                return None
        return original_note_duplicate(self, urge_id, now)


    def handle_force_speak(self: Any) -> Any:
        _arm_force()
        # Force chỉ bypass pacing scheduler một lần; không bypass grounding hay user baton.
        try:
            setattr(self, "autonomous_presence_blocked_until", 0.0)
        except Exception:
            pass
        try:
            setattr(self, "_autonomous_force_speak_pending", True)
        except Exception:
            pass
        if logger is not None:
            logger.info("[speech-lease] force_speak armed ttl=%.0fs", _FORCE_TTL_SECONDS)
        return original_force(self)

    NeuroActionSelector.select = select_with_lease
    NeuroActionSelector.merge_semantic_appraisal = merge_with_lease
    SurfaceIntentEngine.realize = realize_with_lease
    ExpressionUrgeRuntime.note_surface_duplicate = note_surface_duplicate_with_lease
    UserControlRuntimeMixin._handle_force_speak_request = handle_force_speak

    _PATCHED = True
    if logger is not None:
        logger.info(
            "[speech-lease] V64 active: one authority owns SPEAK family; "
            "quiet/low-familiarity/cooldown are not boundaries"
        )


__all__ = [
    "LeaseDecision",
    "LeaseEvaluation",
    "SpeechLease",
    "SpeechLeaseAuthority",
    "install_speech_lease_authority",
]
