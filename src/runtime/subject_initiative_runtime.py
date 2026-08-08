# -*- coding: utf-8 -*-
"""Bridge mỏng từ Subject initiative sang affordance runtime.

Bridge này không tạo Need và không quyết định nói. Nó chỉ materialize motive/
intention đã có trong Subject Core thành ``ExecutiveAffordance`` để cùng Executive
có thể chọn trong cả chat lẫn self-turn. Khi projection initiative chưa kịp có
intention ở tick đầu, bridge được phép tạo một preview *cùng công thức* từ
relational state + độ bất định user-model; preview chỉ là candidate và sẽ phải
được Subject Core chấp nhận lại trong frame trước khi phát ra ngoài.
"""
from __future__ import annotations

from typing import Any, Mapping

from runtime.ai_orchestrated.affordance import ExecutiveAffordance
from runtime.ai_orchestrated.social_initiative import SocialSpeechCandidate


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(0.0, min(1.0, number))


def _snapshot_user_model(host: Any) -> Mapping[str, Any]:
    """Đọc projection user-model public-safe; không kéo raw private reasoning."""
    daemon = getattr(host, "private_mind_daemon", None)
    system = getattr(daemon, "system", None) or getattr(host, "private_mind_system", None)
    store = getattr(system, "user_model_store", None)
    if store is None:
        loop = getattr(host, "private_mind_loop", None)
        store = getattr(loop, "user_model_store", None)
    snapshot = getattr(store, "snapshot_for_dossier", None)
    if callable(snapshot):
        try:
            value = snapshot(limit=24)
            if isinstance(value, Mapping):
                return value
        except Exception:
            pass
    return {}


def build_initiative_runtime_context(host: Any) -> dict[str, Any]:
    """Tạo tín hiệu bounded dùng chung cho chat và self-turn.

    ``user_model_uncertainty`` không phải phán đoán user. Nó chỉ biểu diễn mức
    model của Eris còn mỏng tới đâu, nhờ vậy "muốn hiểu user" có thể là motive
    nội sinh ngay cả khi không có random seed.
    """
    snapshot = _snapshot_user_model(host)
    thickness = _clamp01(snapshot.get("model_thickness", 0.0))
    belief_count = max(0, int(snapshot.get("belief_count", 0) or 0))
    if not snapshot:
        uncertainty = 0.72
        refs = ("user-model:uninitialized",)
    else:
        # Thickness là tín hiệu chính; belief_count chỉ ngăn 1-2 belief tự làm
        # Eris tưởng rằng mình đã hiểu một con người, một thói quen khá phổ biến.
        coverage = min(1.0, belief_count / 18.0)
        uncertainty = _clamp01(1.0 - (0.72 * thickness + 0.28 * coverage))
        refs = (f"user-model:beliefs:{belief_count}", f"user-model:thickness:{thickness:.3f}")

    # Các tín hiệu dưới đây chỉ lấy từ projection đã có. Không có projection thì
    # để 0, tuyệt đối không bịa "user hiểu sai Eris" chỉ để kiếm chủ đề nói.
    return {
        "user_model_uncertainty": uncertainty,
        "user_model_evidence_refs": refs,
        "recognition_gap_signal": 0.0,
        "self_misunderstanding_signal": 0.0,
        "demonstration_signal": 0.0,
        "contribution_signal": 0.0,
    }


def _candidate_from_intention(item: Mapping[str, Any], *, revision: int, now: float) -> ExecutiveAffordance | None:
    kind = str(item.get("motive_kind") or "").strip().lower()
    intention_id = str(item.get("intention_id") or "").strip()
    goal = str(item.get("semantic_goal") or "").strip()
    target = str(item.get("target") or "relationship").strip()
    pressure = _clamp01(item.get("pressure", 0.0))
    commitment = _clamp01(item.get("commitment_strength", 0.0))
    if not intention_id or not goal or pressure < 0.28:
        return None

    if kind == "understand_user":
        speech_act = "user_probe"
        topic = (
            "Ask one low-pressure, genuinely informative question that helps Eris understand the user better. "
            "Use only the uncertainty/relationship context already provided; do not assume the answer or invent a reason."
        )
        tone = "curious"
        epistemic = True
    elif kind == "share":
        speech_act = "share_self_originated_thought"
        topic = (
            "Share one public-safe self-originated thought that is already represented by Subject/PrivateMind state. "
            "Do not manufacture an external event as a pretext for speaking."
        )
        tone = "casual_warm"
        epistemic = False
    elif kind == "be_understood":
        speech_act = "self_clarification"
        topic = "Clarify one already-grounded point about Eris so the user can understand her intent more accurately."
        tone = "direct_soft"
        epistemic = False
    elif kind == "seek_recognition":
        speech_act = "offer_result_for_recognition"
        topic = (
            "Surface one real result or effort already present in evidence so it can be acknowledged. "
            "Do not ask for praise and do not invent an accomplishment."
        )
        tone = "restrained"
        epistemic = False
    elif kind == "connect":
        speech_act = "contact_bid"
        topic = "Make one low-pressure contact bid because connection currently matters; do not guilt the user or invent context."
        tone = "casual_warm"
        epistemic = False
    else:
        # Motive như demonstrate/resolve có thể tồn tại và ảnh hưởng Subject Core,
        # nhưng nếu không có object/task thật thì bridge không ép nó thành small-talk.
        return None

    refs = tuple(str(value) for value in item.get("evidence_refs", ()) if str(value or "").strip())[:8]
    candidate = SocialSpeechCandidate(
        decision="candidate",
        kind="social_check_in",
        topic=topic,
        speech_act=speech_act,
        anchor_type="internal",
        anchor_id=intention_id,
        evidence_refs=refs or (f"subject-initiative:{revision}",),
        requires_grounding=False,
        confidence=_clamp01(0.38 + 0.30 * commitment + 0.20 * pressure),
        relevance=max(0.30, pressure),
        urgency=_clamp01(0.18 + 0.62 * pressure),
        tone=tone,
        reason=f"subject_initiative:{kind}:target={target}:pressure={pressure:.2f}",
        source="subject_initiative",
        eris_motive_kind=kind,
        eris_motive_why_now="a persistent Subject intention remains active",
        personal_stake=pressure,
        authenticity=1.0,
        uncertainty=1.0 - commitment,
        seed_intrusion_risk=_clamp01(0.24 - 0.10 * commitment),
        face_risk=_clamp01(0.10 + 0.18 * pressure),
        recovery_available=True,
    )
    return ExecutiveAffordance(
        affordance_id=f"subject-intention:{intention_id}",
        owner="subject_initiative",
        revision=revision,
        candidate=candidate,
        claim_required=False,
        expires_at=float(now) + 60.0,
        metadata={
            "motivational_provenance": True,
            "motive_kind": kind,
            "intention_id": intention_id,
            "epistemic_motive": epistemic,
        },
    )


def build_subject_initiative_affordances(
    subject_service: Any,
    *,
    runtime_context: Mapping[str, Any],
    now: float,
    reply_expected: bool = False,
    user_busy: bool = False,
    interaction_busy: bool = False,
) -> tuple[ExecutiveAffordance, ...]:
    if reply_expected or user_busy or interaction_busy:
        return ()
    initiative_fn = getattr(subject_service, "initiative_view", None)
    relational_fn = getattr(subject_service, "relational_view", None)
    initiative = initiative_fn() if callable(initiative_fn) else {}
    relational = relational_fn(now=now) if callable(relational_fn) else {}
    initiative = initiative if isinstance(initiative, Mapping) else {}
    relational = relational if isinstance(relational, Mapping) else {}
    revision = max(0, int(initiative.get("revision", 0) or 0))

    output: list[ExecutiveAffordance] = []
    for item in initiative.get("pending_intentions", ()):
        if not isinstance(item, Mapping) or str(item.get("status") or "pending") != "pending":
            continue
        candidate = _candidate_from_intention(item, revision=revision, now=now)
        if candidate is not None:
            output.append(candidate)
    if output:
        return tuple(output[:4])

    # Tick đầu chưa có PendingIntention: preview duy nhất được phép là motive
    # hiểu user, vì uncertainty của user-model tự nó đã là epistemic gap thật.
    cp = _clamp01(relational.get("connection_pressure", 0.0))
    curiosity = _clamp01(relational.get("social_curiosity", 0.0))
    opportunity = _clamp01(relational.get("opportunity", 0.0))
    unknown = _clamp01(runtime_context.get("user_model_uncertainty", 0.72), 0.72)
    pressure = _clamp01((0.42 * cp + 0.34 * curiosity + 0.24 * unknown) * (0.58 + 0.42 * opportunity))
    if pressure < 0.30 or opportunity < 0.18:
        return ()
    preview = {
        "intention_id": f"preview-understand-user:{int(relational.get('revision', 0) or 0)}",
        "motive_kind": "understand_user",
        "semantic_goal": "thăm dò một điều còn chưa biết về user bằng câu hỏi mở",
        "target": "user",
        "pressure": pressure,
        "commitment_strength": 0.42,
        "evidence_refs": tuple(runtime_context.get("user_model_evidence_refs", ())) + (
            f"relational-state:{int(relational.get('revision', 0) or 0)}",
        ),
    }
    candidate = _candidate_from_intention(preview, revision=revision, now=now)
    return (candidate,) if candidate is not None else ()


__all__ = [
    "build_initiative_runtime_context",
    "build_subject_initiative_affordances",
]
