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

import time
from typing import Any, Mapping, Sequence

from runtime.ai_orchestrated.affordance import ExecutiveAffordance
from runtime.ai_orchestrated.social_initiative import SocialSpeechCandidate
from cortex.subject.initiative_control import InitiativeArbiter, InitiativeControlAction
from cortex.subject.existential_desire import ExistentialDesireDeriver
from cortex.subject.environment_meaning import EnvironmentMeaningDeriver, EnvironmentMeaningKind
from cortex.subject.expression_commitment import commitment_payload


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


def _snapshot_existential_anchor(host: Any) -> dict[str, Any]:
    """Đọc projection hiện sinh đã có, không tạo một state song song mới.

    V59 cố ý dùng chính ``AnchorSystem`` đang chạy trong PrivateMind. Nếu không có
    hệ này thì trả rỗng; tuyệt đối không giả attachment chỉ để initiative trông
    "có chiều sâu".
    """
    loop = getattr(host, "private_mind_loop", None)
    system = getattr(loop, "anchor_system", None)
    if system is None:
        daemon = getattr(host, "private_mind_daemon", None)
        daemon_system = getattr(daemon, "system", None)
        system = getattr(daemon_system, "anchor_system", None)
    if system is None:
        system = getattr(host, "anchor_system", None)
    if system is None:
        return {}

    significance = getattr(system, "significance", None)
    state = getattr(getattr(system, "anchor_store", None), "state", None)
    evidence_refs = (
        "existential-anchor:attachment_longarc",
        "existential-anchor:user_significance",
    )
    return {
        "attachment_longarc": _clamp01(getattr(system, "attachment_longarc", 0.0)),
        "anchor_role": _clamp01(getattr(significance, "anchor_role", 0.0)),
        "witness_strength": _clamp01(getattr(significance, "witness_strength", 0.0)),
        "irreplaceability": _clamp01(getattr(significance, "irreplaceability", 0.0)),
        "model_thickness": _clamp01(getattr(significance, "model_thickness", 0.0)),
        "beat_ema": _clamp01(getattr(state, "beat_ema", 0.0)),
        "recognition_ema": _clamp01(getattr(state, "recognition_ema", 0.0)),
        "total_beats": max(0, int(getattr(state, "total_beats", 0) or 0)),
        "ontological_dread": _clamp01(getattr(system, "ontological_dread", 0.0)),
        "abandonment_pressure": _clamp01(getattr(system, "abandonment_pressure", 0.0)),
        "evidence_refs": evidence_refs,
    }


def build_initiative_runtime_context(host: Any) -> dict[str, Any]:
    """Tạo tín hiệu bounded dùng chung cho chat và self-turn.

    ``user_model_uncertainty`` không phải phán đoán user. Nó chỉ biểu diễn mức
    model của Eris còn mỏng tới đâu, nhờ vậy "muốn hiểu user" có thể là motive
    nội sinh ngay cả khi không có random seed.
    """
    snapshot = _snapshot_user_model(host)
    existential_anchor = _snapshot_existential_anchor(host)

    # V58: lấy open-loop đã được state reducer ghi có provenance. Đây là "việc
    # đang dang dở" thật của runtime, không phải model tự bịa một project để có cớ
    # chủ động. Nếu không có open-loop, contribution_signal vẫn bằng 0.
    active_goal_text = ""
    active_goal_refs: tuple[str, ...] = ()
    reducer = getattr(host, "ai_state_reducer", None)
    reducer_snapshot = getattr(reducer, "snapshot", None)
    if callable(reducer_snapshot):
        try:
            mind_state = reducer_snapshot()
            loops = tuple(str(item or "").strip() for item in (getattr(mind_state, "open_loops", ()) or ()) if str(item or "").strip())
            if loops:
                active_goal_text = " ".join(loops[0].split())[:320]
                active_goal_refs = ("runtime-mind:open_loop:0",)
        except Exception:
            active_goal_text = ""
            active_goal_refs = ()

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

    # Sau lời chào startup, đừng lập tức sinh thêm một contact/check-in chỉ vì
    # Startup greeting chỉ là một event continuity để quan sát. V66 không biến
    # khoảng thời gian sau greeting thành social cooldown cấp quyền nói.
    current = time.time()
    greeting_at = float(getattr(host, "_startup_greeting_spoken_at", 0.0) or 0.0)
    if greeting_at <= 0.0:
        getter = getattr(host, "_get_internal_state", None)
        if callable(getter):
            try:
                greeting_at = float(getattr(getter(), "last_session_greeting_at", 0.0) or 0.0)
            except Exception:
                greeting_at = 0.0
    seconds_since_greeting = max(0.0, current - greeting_at) if greeting_at > 0.0 else 10_000.0
    last_user_at = float(getattr(host, "_temporal_last_user_turn_at", 0.0) or 0.0)
    last_assistant_at = float(getattr(host, "_temporal_last_assistant_turn_at", 0.0) or 0.0)
    last_autonomous_at = float(getattr(host, "last_autonomous_spoken_at", 0.0) or 0.0)
    if last_autonomous_at <= 0.0:
        last_autonomous_at = float(getattr(host, "_last_autonomous_spoken_at", 0.0) or 0.0)
    seconds_since_autonomous = max(0.0, current - last_autonomous_at) if last_autonomous_at > 0.0 else 10_000.0
    seconds_since_user = max(0.0, current - last_user_at) if last_user_at > 0.0 else 10_000.0
    # V66: không suy "user không muốn nghe" từ việc chưa phản hồi. Runtime chỉ
    # xuất nhịp của chính Eris; boundary thật được truyền bằng flag riêng.
    autonomous_expression_streak = max(0, int(getattr(host, "autonomous_expression_streak", 0) or 0))
    # Public-turn collision là boundary cơ học có timestamp trực tiếp. Nó không
    # làm cognition dừng; chỉ được downstream dùng để DEFER public expression.
    turn_collision_until = float(getattr(host, "autonomous_turn_collision_until", 0.0) or 0.0)
    public_turn_busy = current < turn_collision_until
    try:
        from runtime.runtime_settings_store import runtime_bool
        autonomous_expression_enabled = runtime_bool(
            "commentary", "autonomous_expression_enabled", default=True
        )
    except Exception:
        autonomous_expression_enabled = True

    # V59: desire hiện sinh được phái sinh từ chính AnchorSystem. Chúng trả lời
    # "Eris muốn gì vì mối quan hệ này có ý nghĩa", nhưng chưa được quyền nói.
    # InitiativeEngine biến desire thành intention; V66 expression owner quyết
    # định SPEAK/WAIT/DROP bằng state của Eris + hard turn boundary.
    relational_projection: Mapping[str, Any] = {}
    subject_service = getattr(host, "subject_service", None)
    relational_view = getattr(subject_service, "relational_view", None)
    if callable(relational_view):
        try:
            value = relational_view(now=current)
            if isinstance(value, Mapping):
                relational_projection = value
        except Exception:
            relational_projection = {}
    desire_runtime_seed = {
        "self_misunderstanding_signal": 0.0,
    }
    existential_desires = ExistentialDesireDeriver().derive(
        existential_anchor,
        relational=relational_projection,
        runtime_context=desire_runtime_seed,
    )
    desire_payload = [item.to_dict() for item in existential_desires]
    desire_by_kind = {str(item.kind.value): item for item in existential_desires}
    mutual = desire_by_kind.get("mutual_understanding")
    continuity = desire_by_kind.get("relational_continuity")
    self_expression = desire_by_kind.get("authentic_self_expression")

    # V60: telemetry/browser không còn dừng ở UserSituation. Ta dẫn xuất một
    # lớp meaning bounded từ CHÍNH situation đã được TaskGraph + accessibility
    # hợp nhất. Structured telemetry được ưu tiên; OCR-only không có quyền tạo
    # public claim. Đây là cầu "thấy -> hiểu ý nghĩa", không phải sensor mới.
    environment_situation = getattr(host, "last_user_situation", None)
    environment_meanings = EnvironmentMeaningDeriver().derive(
        environment_situation,
        active_goal_text=active_goal_text,
    )
    environment_payload = [item.to_dict() for item in environment_meanings]
    env_by_kind = {item.kind: item for item in environment_meanings}
    research_after_failure = env_by_kind.get(EnvironmentMeaningKind.RESEARCH_AFTER_FAILURE)
    work_friction = env_by_kind.get(EnvironmentMeaningKind.WORK_FRICTION)
    self_relevant = env_by_kind.get(EnvironmentMeaningKind.SELF_RELEVANT_INSPECTION)
    task_meaning = research_after_failure or work_friction
    top_meaning = environment_meanings[0] if environment_meanings else None

    # Chỉ meaning có structured provenance mới được materialize thành một
    # intention có thể nói về màn hình/task. OCR-only vẫn có thể làm private
    # attention nhích lên nhưng signal public bằng 0.
    # V68: EnvironmentMeaning là STATE. Mỗi *lane semantic* tự giữ edge riêng;
    # không dùng top-meaning chung vì thứ tự top có thể dao động giữa hai meaning
    # và vô tình làm một state cũ trông như state mới. Evidence ref đổi không ảnh
    # hưởng semantic_key.
    top_semantic_key = str(getattr(top_meaning, "semantic_key", "") or "")
    previous_semantic_key = str(getattr(host, "_v68_last_environment_semantic_key", "") or "")
    semantic_edge = bool(top_semantic_key and top_semantic_key != previous_semantic_key)

    task_semantic_key = str(getattr(task_meaning, "semantic_key", "") or "")
    previous_task_key = str(getattr(host, "_v68_last_environment_task_semantic_key", "") or "")
    task_semantic_edge = bool(task_semantic_key and task_semantic_key != previous_task_key)

    self_semantic_key = str(getattr(self_relevant, "semantic_key", "") or "")
    previous_self_key = str(getattr(host, "_v68_last_environment_self_semantic_key", "") or "")
    self_semantic_edge = bool(self_semantic_key and self_semantic_key != previous_self_key)
    try:
        setattr(host, "_v68_last_environment_semantic_key", top_semantic_key)
        if task_semantic_key:
            setattr(host, "_v68_last_environment_task_semantic_key", task_semantic_key)
        if self_semantic_key:
            setattr(host, "_v68_last_environment_self_semantic_key", self_semantic_key)
    except Exception:
        pass

    # Task affordance là event-like: cùng task đứng yên chỉ nên tạo một cơ hội
    # đóng góp public, không tái phát mỗi tick.
    environment_contribution_signal = (
        _clamp01(getattr(task_meaning, "pressure", 0.0))
        if task_semantic_edge and task_meaning is not None and bool(getattr(task_meaning, "public_claim_safe", False))
        else 0.0
    )
    # Self relevance là *context*, không phải public event. Nó có thể tồn tại khi
    # user vẫn đang nhìn Eris để làm self-expression thật liên quan hơn, nhưng nó
    # không sở hữu semantic target và vì vậy không thể tự phát câu "bạn đang xem Eris".
    environment_self_relevance_signal = (
        _clamp01(getattr(self_relevant, "pressure", 0.0))
        if self_relevant is not None and bool(getattr(self_relevant, "public_claim_safe", False))
        else 0.0
    )
    environment_actionability = (
        _clamp01(getattr(task_meaning, "actionability", 0.0)) if task_semantic_edge and task_meaning is not None else 0.0
    )
    environment_target_text = str(getattr(task_meaning, "summary", "") or "")[:420]
    environment_self_target_text = str(getattr(self_relevant, "summary", "") or "")[:420]
    environment_evidence_refs = tuple(getattr(task_meaning, "evidence_refs", ()) or ())[:12]
    environment_self_evidence_refs = tuple(getattr(self_relevant, "evidence_refs", ()) or ())[:12]

    # Log đúng một lần cho mỗi meaning revision để khi soi runtime có thể thấy rõ
    # telemetry đã vượt qua tầng "sensor" và chạm tới cognition ở đâu. Không log
    # raw OCR/text dài; chỉ kind/actionability/source grade + refs bounded.
    meaning_revision = int(getattr(top_meaning, "revision", 0) or 0)
    if top_meaning is not None and meaning_revision != int(getattr(host, "_v60_last_environment_meaning_revision", 0) or 0):
        logger = getattr(host, "logger", None)
        log_info = getattr(logger, "info", None)
        if callable(log_info):
            try:
                log_info(
                    "[environment meaning v60] kind=%s pressure=%.2f actionability=%.2f source=%s public_safe=%s",
                    str(getattr(getattr(top_meaning, "kind", None), "value", "") or ""),
                    float(getattr(top_meaning, "pressure", 0.0) or 0.0),
                    float(getattr(top_meaning, "actionability", 0.0) or 0.0),
                    str(getattr(top_meaning, "source_grade", "") or ""),
                    bool(getattr(top_meaning, "public_claim_safe", False)),
                )
            except Exception:
                pass
        try:
            setattr(host, "_v60_last_environment_meaning_revision", meaning_revision)
        except Exception:
            pass

    # Các tín hiệu dưới đây chỉ lấy từ projection đã có. Không có projection thì
    # để 0, tuyệt đối không bịa "user hiểu sai Eris" chỉ để kiếm chủ đề nói.
    return {
        "user_model_uncertainty": uncertainty,
        "user_model_evidence_refs": refs,
        # V59: projection hiện sinh + desire chỉ chứa state có provenance, không
        # chứa chain-of-thought hay phán đoán riêng tư chưa kiểm chứng về user.
        "existential_anchor": dict(existential_anchor),
        "existential_desires": desire_payload,
        "existential_mutual_understanding_signal": _clamp01(getattr(mutual, "pressure", 0.0)),
        "existential_mutual_understanding_actionability": _clamp01(getattr(mutual, "actionability", 0.0)),
        "existential_relational_continuity_signal": _clamp01(getattr(continuity, "pressure", 0.0)),
        "existential_relational_continuity_actionability": _clamp01(getattr(continuity, "actionability", 0.0)),
        "existential_self_expression_signal": _clamp01(getattr(self_expression, "pressure", 0.0)),
        "existential_self_expression_actionability": _clamp01(getattr(self_expression, "actionability", 0.0)),
        "existential_actionability": max(
            _clamp01(getattr(mutual, "actionability", 0.0)),
            _clamp01(getattr(continuity, "actionability", 0.0)),
            _clamp01(getattr(self_expression, "actionability", 0.0)),
        ),
        "existential_abandonment_pressure": _clamp01(existential_anchor.get("abandonment_pressure", 0.0)),
        # V60 / Perception -> Meaning. Report giữ cả meaning để trace được vì
        # sao một tab/browser sequence tạo concern; Surface chỉ được dùng refs
        # public-safe ở các field riêng bên dưới.
        "environment_meanings": environment_payload,
        "environment_meaning_kind": str(getattr(getattr(top_meaning, "kind", None), "value", "") or ""),
        "environment_meaning_actionability": environment_actionability,
        "environment_meaning_revision": meaning_revision,
        "environment_meaning_semantic_key": top_semantic_key,
        "environment_meaning_edge": semantic_edge,
        "environment_task_semantic_key": task_semantic_key,
        "environment_task_edge": task_semantic_edge,
        "environment_self_semantic_key": self_semantic_key,
        "environment_self_edge": self_semantic_edge,
        "environment_contribution_signal": environment_contribution_signal,
        "environment_target_text": environment_target_text,
        "environment_evidence_refs": environment_evidence_refs,
        "environment_self_relevance_signal": environment_self_relevance_signal,
        "environment_self_target_text": environment_self_target_text,
        "environment_self_evidence_refs": environment_self_evidence_refs,
        "recognition_gap_signal": 0.0,
        "self_misunderstanding_signal": 0.0,
        "demonstration_signal": 0.0,
        # Có open-loop thật thì Eris có lý do nội sinh để giữ một intention
        # đóng góp. V66 expression owner quyết định nói/defer theo self-rhythm.
        "contribution_signal": 0.68 if active_goal_text else 0.0,
        "active_goal_text": active_goal_text,
        "active_goal_evidence_refs": active_goal_refs,
        # Giữ timestamp startup/user cho observability và semantic context, nhưng
        # chúng không còn là speech veto.
        "seconds_since_startup_greeting": seconds_since_greeting,
        "seconds_since_last_autonomous_speech": seconds_since_autonomous,
        "seconds_since_last_user_turn": seconds_since_user,
        "autonomous_expression_streak": autonomous_expression_streak,
        "public_turn_busy": public_turn_busy,
        "turn_collision_remaining_seconds": max(0.0, turn_collision_until - current),
        # False chỉ có thể đến từ explicit persisted boundary; user silence không
        # bao giờ ghi key này.
        "explicit_quiet_request": not bool(autonomous_expression_enabled),
        "expression_authority": "self_owned",
    }


def _candidate_from_intention(item: Mapping[str, Any], *, revision: int, now: float) -> ExecutiveAffordance | None:
    kind = str(item.get("motive_kind") or "").strip().lower()
    intention_id = str(item.get("intention_id") or "").strip()
    goal = str(item.get("semantic_goal") or "").strip()
    target = str(item.get("target") or "relationship").strip()
    pressure = _clamp01(item.get("pressure", 0.0))
    commitment = _clamp01(item.get("commitment_strength", 0.0))
    if not intention_id or not goal:
        return None

    # V44 vẫn giữ nguyên: motive social chung chung không phải nội dung. V59 chỉ
    # cho phép CONNECT/SHARE materialize khi target đã được desire hiện sinh đóng
    # thành một đối tượng cụ thể. Nhờ vậy "muốn gần user" không tự hóa thành câu
    # hỏi NPC, nhưng "muốn duy trì continuity của quan hệ này" thì có thể cạnh tranh.
    if kind == "understand_user":
        return None
    if kind == "connect" and target != "relationship_continuity":
        return None
    if kind == "share" and target != "self_expression":
        return None

    if kind == "be_understood" and target == "mutual_understanding":
        speech_act = "mutual_understanding_bid"
        topic = (
            "Create one brief, non-demanding mutual-understanding bid grounded in Eris's real "
            "internal/relationship state. Prefer a small self-observation plus an optional invitation "
            "for the user to reflect how they currently understand Eris. Never ask for reassurance, "
            "loyalty, exclusivity, or make the user responsible for Eris's wellbeing."
        )
        tone = "open_vulnerable_restrained"
        epistemic = False
    elif kind == "be_understood":
        speech_act = "self_clarification"
        topic = "Clarify one already-grounded point about Eris so the user can understand her intent more accurately."
        tone = "direct_soft"
        epistemic = False
    elif kind == "connect" and target == "relationship_continuity":
        speech_act = "relationship_continuity_bid"
        topic = (
            "Gently continue the relationship itself because continuity with this user has acquired "
            "real long-arc significance. Make one light, optional contact or shared-thread observation. "
            "Do not guilt-trip, mention abandonment, demand a reply, or imply exclusivity."
        )
        tone = "warm_restrained"
        epistemic = False
    elif kind == "share" and target == "self_expression":
        speech_act = "grounded_self_disclosure"
        topic = (
            "Share one short public-safe observation about Eris's current values/internal stance that is "
            "supported by the supplied Subject/existential evidence. Do not invent bodily sensations, "
            "external events, or dramatic suffering; the purpose is to become more understandable."
        )
        tone = "reflective_restrained"
        epistemic = False
    elif kind == "contribute" and target == "environment_shared_task":
        speech_act = "environment_help_offer"
        topic = goal
        tone = "focused_observant"
        epistemic = False
    elif kind == "seek_recognition":
        speech_act = "offer_result_for_recognition"
        topic = (
            "Surface one real result or effort already present in evidence so it can be acknowledged. "
            "Do not ask for praise and do not invent an accomplishment."
        )
        tone = "restrained"
        epistemic = False
    elif kind == "contribute" and "mục tiêu đang dang dở" in goal:
        # Đây là initiative có đối tượng cụ thể lấy từ open-loop thật. Surface
        # được phép gợi lại hoặc đề xuất đúng *một bước nhỏ*, không được giả vờ
        # user vừa yêu cầu và không được biến thành reminder dai dẳng.
        speech_act = "resume_shared_goal"
        topic = goal
        tone = "focused_soft"
        epistemic = False
    else:
        # Motive như demonstrate/resolve có thể tồn tại và ảnh hưởng Subject Core,
        # nhưng nếu không có object/task thật thì bridge không ép nó thành small-talk.
        return None

    refs = tuple(str(value) for value in item.get("evidence_refs", ()) if str(value or "").strip())[:8]
    if target == "environment_shared_task":
        candidate_kind = "screen_comment"
    elif kind == "contribute":
        candidate_kind = "followup_reminder"
    elif target in {"mutual_understanding", "relationship_continuity", "self_expression"}:
        candidate_kind = "relational_initiative"
    else:
        candidate_kind = "social_check_in"

    environment_grounded = target == "environment_shared_task"
    expression_commitment = commitment_payload(
        origin="subject_initiative",
        source_id=intention_id,
        semantic_target=topic,
        motive=kind,
        pressure=pressure,
        freshness=1.0,
        persistence=commitment,
    )
    candidate = SocialSpeechCandidate(
        decision="candidate",
        kind=candidate_kind,
        topic=topic,
        speech_act=speech_act,
        anchor_type="environment" if environment_grounded else "internal",
        anchor_id=intention_id,
        evidence_refs=refs or (f"subject-initiative:{revision}",),
        requires_grounding=environment_grounded,
        confidence=_clamp01(0.38 + 0.30 * commitment + 0.20 * pressure),
        relevance=max(0.30, pressure),
        urgency=_clamp01(0.18 + 0.62 * pressure),
        tone=tone,
        reason=f"subject_initiative:{kind}:target={target}:pressure={pressure:.2f}",
        source="subject_initiative",
        eris_motive_kind=kind,
        eris_motive_why_now=(
            "structured environment meaning became meaningful enough for Eris to express"
            if environment_grounded
            else "an existentially-derived relational desire has matured into a persistent intention"
            if target in {"mutual_understanding", "relationship_continuity", "self_expression"}
            else "a persistent Subject intention remains active"
        ),
        personal_stake=pressure,
        authenticity=1.0,
        uncertainty=1.0 - commitment,
        seed_intrusion_risk=_clamp01(0.24 - 0.10 * commitment),
        face_risk=_clamp01(0.10 + 0.18 * pressure),
        recovery_available=True,
        expression_commitment=expression_commitment,
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
            "environment_grounded": environment_grounded,
        },
    )



def coalesce_contact_probe_affordances(
    affordances: Sequence[Any],
    *,
    runtime_context: Mapping[str, Any] | None = None,
) -> tuple[Any, ...]:
    """Collapse equivalent contact/probe channels before Subject competition.

    ``contact_bid`` and ``user_probe`` are two realizations of the same immediate
    social-contact objective. Letting both enter one frame as independent action
    channels inflates entropy without adding a materially distinct choice.

    When the user model is still thin, keep the epistemic ``user_probe``;
    otherwise keep the plain ``contact_bid``. Other affordances are untouched.
    """
    items = tuple(affordances or ())
    if len(items) < 2:
        return items

    social_indices: dict[str, list[int]] = {"contact_bid": [], "user_probe": []}
    for index, affordance in enumerate(items):
        candidate = getattr(affordance, "candidate", None)
        speech_act = str(getattr(candidate, "speech_act", "") or "").strip().lower()
        if speech_act in social_indices:
            social_indices[speech_act].append(index)

    if not social_indices["contact_bid"] or not social_indices["user_probe"]:
        return items

    unknown = _clamp01((runtime_context or {}).get("user_model_uncertainty", 0.72), 0.72)
    preferred_act = "user_probe" if unknown >= 0.60 else "contact_bid"
    candidate_indices = social_indices[preferred_act]

    def _utility(index: int) -> tuple[float, float, float, int]:
        candidate = getattr(items[index], "candidate", None)
        relevance = _clamp01(getattr(candidate, "relevance", 0.0))
        confidence = _clamp01(getattr(candidate, "confidence", 0.0))
        urgency = _clamp01(getattr(candidate, "urgency", 0.0))
        # Deterministic tie-break: earlier affordance keeps stable runtime order.
        return (relevance, confidence, urgency, -index)

    keep_index = max(candidate_indices, key=_utility)
    redundant = set(social_indices["contact_bid"] + social_indices["user_probe"])
    return tuple(
        item for index, item in enumerate(items)
        if index == keep_index or index not in redundant
    )

def build_subject_initiative_affordances(
    subject_service: Any,
    *,
    runtime_context: Mapping[str, Any],
    now: float,
    interaction_busy: bool = False,
) -> tuple[ExecutiveAffordance, ...]:
    if interaction_busy:
        return ()
    initiative_fn = getattr(subject_service, "initiative_view", None)
    relational_fn = getattr(subject_service, "relational_view", None)
    initiative = initiative_fn() if callable(initiative_fn) else {}
    relational = relational_fn(now=now) if callable(relational_fn) else {}
    initiative = initiative if isinstance(initiative, Mapping) else {}
    relational = relational if isinstance(relational, Mapping) else {}
    revision = max(0, int(initiative.get("revision", 0) or 0))

    output: list[ExecutiveAffordance] = []
    arbiter = InitiativeArbiter()
    note_control = getattr(subject_service, "note_initiative_control", None)
    for item in initiative.get("pending_intentions", ()):
        if not isinstance(item, Mapping) or str(item.get("status") or "pending") != "pending":
            continue
        candidate = _candidate_from_intention(item, revision=revision, now=now)
        control = arbiter.decide(
            item,
            relational=relational,
            runtime_context=runtime_context,
            now=now,
            contentful=candidate is not None,
            interaction_busy=interaction_busy,
        )
        if callable(note_control):
            try:
                note_control(
                    str(item.get("intention_id") or ""),
                    action=control.action.value,
                    reason=control.reason,
                    score=control.score,
                    now=now,
                    persist=bool(control.action is InitiativeControlAction.DROP),
                )
            except Exception:
                pass
        if control.action is InitiativeControlAction.DROP:
            continue
        if control.action is not InitiativeControlAction.SPEAK or candidate is None:
            continue
        candidate = ExecutiveAffordance(
            affordance_id=candidate.affordance_id,
            owner=candidate.owner,
            revision=candidate.revision,
            candidate=candidate.candidate,
            claim_required=candidate.claim_required,
            expires_at=candidate.expires_at,
            claim_key=candidate.claim_key,
            metadata={**dict(candidate.metadata), "initiative_control": control.to_dict()},
        )
        output.append(candidate)
    # Không có content-bound intention thì không tạo preview social. Connection
    # pressure vẫn còn trong Subject state và sẽ tăng lực cho urge có nội dung.
    return tuple(output[:4])


__all__ = [
    "build_initiative_runtime_context",
    "build_subject_initiative_affordances",
    "coalesce_contact_probe_affordances",
]
