import re
import time
import unicodedata

from dataclasses import dataclass

#Ép mọi giá trị số về khoảng 0.0 -> 1.0
def _clamp01(value) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if numeric != numeric:
        return 0.0
    return max(0.0, min(1.0, numeric))


def _clean_text(value: object, *, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _normalize(value: object) -> str:
    text = str(value or "").strip().lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text)


def _tokens(value: object) -> set[str]:
    stop_words = {
        "and",
        "the",
        "for",
        "from",
        "this",
        "that",
        "with",
        "dang",
        "trong",
        "cua",
        "voi",
        "khi",
        "thi",
        "neu",
        "ngai",
        "toi",
        "mot",
        "nhung",
        "khong",
        "duoc",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9_]+", _normalize(value).replace("_", " "))
        if len(token) >= 3 and token not in stop_words
    }


#Thêm summary mới vào danh sách gần đây, chỉ giữ tối đa 8 cái.
def _append_recent(items: tuple[str, ...], value: str, *, limit: int = 8) -> tuple[str, ...]:
    text = _clean_text(value, limit=140)
    if not text:
        return tuple(items[-limit:])
    return (*items, text)[-limit:]


@dataclass(slots=True)
class GoalPersistenceState:
    """A long-lived problem ERIS is tracking across events."""

    goal_id: str = "" 
    summary: str = "" #Nội dung goal
    source: str = ""
    status: str = "empty" #empty, active, stale, closed
    strength: float = 0.0 #Goal mạnh tới đâu
    urgency: float = 0.0 #Độ khẩn
    drift: float = 0.0 #Mức lệch khỏi mục tiêu
    progress: float = 0.0 #Mức độ đã hoàn thành goal, 0.0 -> 1.0
    recurrence_count: int = 0 #Goal này lặp lại bao nhiêu lần
    created_at: float = 0.0
    updated_at: float = 0.0
    last_reactivated_at: float = 0.0
    next_hint: str = "" #Gợi ý dùng goal này về sau
    evidence: tuple[str, ...] = () #Bằng chứng vì sao goal được giữ
    recent_summaries: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        #Tức goal yếu quá thì không được tính là active. Đỡ kiểu “nhớ dai như thù vặt”
        return self.status == "active" and bool(self.summary) and self.strength >= 0.18

    def to_dict(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "summary": self.summary,
            "source": self.source,
            "status": self.status,
            "strength": round(float(self.strength), 3),
            "urgency": round(float(self.urgency), 3),
            "drift": round(float(self.drift), 3),
            "progress": round(float(self.progress), 3),
            "recurrence_count": int(self.recurrence_count),
            "created_at": round(float(self.created_at), 3),
            "updated_at": round(float(self.updated_at), 3),
            "last_reactivated_at": round(float(self.last_reactivated_at), 3),
            "next_hint": self.next_hint,
            "evidence": list(self.evidence),
            "recent_summaries": list(self.recent_summaries),
        }

    @classmethod
    def from_dict(cls, data: object) -> "GoalPersistenceState":
        if not isinstance(data, dict):
            return cls()
        return cls(
            goal_id=_clean_text(data.get("goal_id"), limit=80),
            summary=_clean_text(data.get("summary"), limit=180),
            source=_clean_text(data.get("source"), limit=80),
            status=_clean_text(data.get("status"), limit=40) or "empty",
            strength=_clamp01(data.get("strength", 0.0)),
            urgency=_clamp01(data.get("urgency", 0.0)),
            drift=_clamp01(data.get("drift", 0.0)),
            progress=_clamp01(data.get("progress", 0.0)),
            recurrence_count=max(0, int(data.get("recurrence_count", 0) or 0)),
            created_at=max(0.0, float(data.get("created_at", 0.0) or 0.0)),
            updated_at=max(0.0, float(data.get("updated_at", 0.0) or 0.0)),
            last_reactivated_at=max(0.0, float(data.get("last_reactivated_at", 0.0) or 0.0)),
            next_hint=_clean_text(data.get("next_hint"), limit=180),
            evidence=tuple(str(item) for item in (data.get("evidence") or ()) if str(item or "").strip())[-8:],
            recent_summaries=tuple(str(item) for item in (data.get("recent_summaries") or ()) if str(item or "").strip())[-8:],
        )

    #Hàm này tạo text nhét vào prompt.
    def render_prompt_context(self) -> str:
        if not self.active:
            return "goal_persistence: none active."
        evidence = " | ".join(self.evidence[-4:]) or "none"
        return (
            "goal_persistence: long-lived background goal; use as continuity, not current screen proof.\n"
            f"- active_goal={self.summary}; strength={self.strength:.2f}; urgency={self.urgency:.2f}; "
            f"drift={self.drift:.2f}; recurrence={self.recurrence_count}; source={self.source or 'unknown'}.\n"
            f"- next_hint={self.next_hint or 'continue the same problem if context still fits'}.\n"
            f"- evidence={evidence}."
        )


class GoalPersistenceEngine:
    """Promotes recurrent cognitive pull into a durable background goal."""

    TASK_MARKERS = (
        "fix",
        "implement",
        "add",
        "build",
        "wire",
        "debug",
        "review",
        "refactor",
        "test",
        "goal",
        "persistence",
        "muc tieu",
        "van de",
        "cognition",
        "hệ thống",
        "tiếp tục",
        "sửa",
        "thêm",
        "làm",
    )
    CLOSURE_MARKERS = (
        "done",
        "fixed",
        "resolved",
        "solved",
        "complete",
        "completed",
        "close_goal",
        "xong",
        "đã xong",
        "giải quyết",
        "đóng goal",
    )

    def update(
        self,
        state: GoalPersistenceState,
        *,
        channel: str,
        snapshot=None,
        ni_report=None,
        ti_report=None,
        thought_stream_report=None,
        broadcast=None,
        user_text: str = "",
        force_speak: bool = False,
        now: float | None = None,
    ) -> GoalPersistenceState:
        current_time = time.time() if now is None else max(0.0, float(now or 0.0))
        base = state if isinstance(state, GoalPersistenceState) else GoalPersistenceState()
        candidate = self._candidate(
            channel=channel,
            snapshot=snapshot,
            ni_report=ni_report,
            ti_report=ti_report,
            thought_stream_report=thought_stream_report,
            broadcast=broadcast,
            user_text=user_text,
            force_speak=force_speak,
        )
        if self._has_closure(user_text, thought_stream_report=thought_stream_report) and base.active:
            user_tokens = _tokens(user_text)
            if len(user_tokens) <= 3 or self._matches(base.summary, user_text): #Nếu câu đóng goal ngắn hoặc có nhiều token chung với summary của goal thì mới đóng, tránh trường hợp người dùng nói "xong" nhưng không phải là xong cái goal đang theo dõi.
                return self._close(base, now=current_time, evidence="closure_signal")
        if candidate is None:
            return self._decay(base, now=current_time)
        return self._merge(base, candidate, now=current_time)

    def _candidate(
        self,
        *,
        channel: str,
        snapshot,
        ni_report,
        ti_report,
        thought_stream_report,
        broadcast,
        user_text: str,
        force_speak: bool,
    ) -> dict[str, object] | None:
        direct_user = channel in {"chat", "force_speak"} or force_speak or bool((user_text or "").strip())
        #Tức user nói càng giống việc cần làm thì goal càng mạnh.
        if direct_user and self._looks_goal_worthy(user_text):
            drift = _clamp01(getattr(ni_report, "drift_score", 0.0))
            return {
                "summary": _clean_text(user_text, limit=160),
                "source": "user_message",
                "strength": 0.72,
                "urgency": _clamp01(0.42 + drift * 0.28),
                "drift": drift,
                "next_hint": "continue solving the user's stated problem across later events",
                "evidence": ("direct_user_goal", f"channel={channel}"),
            }

        momentum = getattr(thought_stream_report, "momentum", None)
        if (
            #nếu hệ thống thấy não/agent cứ bị kéo về một chủ đề, nó lưu chủ đề đó
            momentum is not None
            and str(getattr(momentum, "affordance", "") or "") == "attention"
            and _clamp01(getattr(momentum, "score", 0.0)) >= 0.58
        ):
            topic = _clean_text(getattr(momentum, "topic_seed", ""), limit=140)
            return {
                "summary": topic,
                "source": "cognitive_momentum",
                "strength": _clamp01(getattr(momentum, "score", 0.0)),
                "urgency": _clamp01(getattr(momentum, "tension", 0.0)),
                "drift": _clamp01(getattr(ni_report, "drift_score", 0.0)),
                "next_hint": "let this unresolved thread bias attention until it is closed or superseded",
                "evidence": tuple(getattr(momentum, "evidence", ()) or ())[:6],
            }

        attractor = getattr(thought_stream_report, "active_attractor", None)
        if (
            #attractor giống “vòng lặp chưa giải quyết” hơn
            attractor is not None
            and bool(getattr(attractor, "attractor", False))
            and _clamp01(getattr(attractor, "score", 0.0)) >= 0.64
        ):
            topic = _clean_text(getattr(attractor, "topic_seed", ""), limit=140)
            return {
                "summary": topic,
                "source": "cognitive_attractor",
                "strength": _clamp01(getattr(attractor, "score", 0.0)),
                "urgency": _clamp01(getattr(attractor, "tension", 0.0)),
                "drift": _clamp01(getattr(ni_report, "drift_score", 0.0)),
                "next_hint": "pull cognition back to this unresolved loop when affordance is available",
                "evidence": tuple(getattr(attractor, "evidence", ()) or ())[:6],
            }
        #Nó lấy nội dung từ broadcast.content hoặc snapshot.focus_summary, rồi tạo goal để giữ vấn đề gốc không bị trôi.
        if str(getattr(ti_report, "mode", "") or "") in {"goal_drift_alert", "goal_realign"}:
            content = _clean_text(getattr(broadcast, "content", "") or getattr(snapshot, "focus_summary", ""), limit=140)
            if content:
                drift = _clamp01(getattr(ni_report, "drift_score", 0.0))
                return {
                    "summary": content,
                    "source": "ni_goal_drift",
                    "strength": _clamp01(0.46 + drift * 0.28),
                    "urgency": _clamp01(0.38 + drift * 0.32),
                    "drift": drift,
                    "next_hint": "keep the original problem available while handling drift gently",
                    "evidence": (f"ti_mode={getattr(ti_report, 'mode', '')}", f"drift={drift:.2f}"),
                }
        return None

    #hợp nhất goal mới với goal đang tồn tại
    def _merge(self, state: GoalPersistenceState, candidate: dict[str, object], *, now: float) -> GoalPersistenceState:
        summary = _clean_text(candidate.get("summary"), limit=180) #Lấy summary goal mới.
        if not summary:
            return self._decay(state, now=now)
        matched = state.active and self._matches(state.summary, summary) #Nó hợp nhất goal mới với goal đang tồn tại.
        previous_strength = state.strength if matched else min(state.strength * 0.42, 0.30)
        strength = _clamp01(max(previous_strength, float(candidate.get("strength", 0.0) or 0.0)) + (0.08 if matched else 0.0))
        urgency = _clamp01(max(state.urgency * (0.86 if matched else 0.52), float(candidate.get("urgency", 0.0) or 0.0)))
        created_at = state.created_at if matched and state.created_at > 0.0 else now
        recurrence = state.recurrence_count + 1 if matched else 1
        evidence = tuple(
            dict.fromkeys(
                (
                    *(state.evidence if matched else ()),
                    *tuple(str(item) for item in (candidate.get("evidence") or ()) if str(item or "").strip()),
                )
            )
        )[-8:]
        return GoalPersistenceState(
            goal_id=state.goal_id if matched and state.goal_id else f"goal_{abs(hash(summary)) % 1000000}",
            summary=state.summary if matched else summary,
            source=_clean_text(candidate.get("source"), limit=80),
            status="active",
            strength=strength,
            urgency=urgency,
            drift=_clamp01(candidate.get("drift", 0.0)),
            progress=state.progress if matched else 0.0,
            recurrence_count=recurrence,
            created_at=created_at,
            updated_at=now,
            last_reactivated_at=now,
            next_hint=_clean_text(candidate.get("next_hint"), limit=180),
            evidence=evidence,
            recent_summaries=_append_recent(state.recent_summaries, summary),
        )

    #Nếu không có candidate mới, goal cũ suy giảm theo thời gian:
    def _decay(self, state: GoalPersistenceState, *, now: float) -> GoalPersistenceState:
        if not state.summary:
            return state
        age_minutes = max(0.0, (now - (state.updated_at or state.created_at or now)) / 60.0)
        keep = 0.985 ** min(240.0, age_minutes)
        strength = _clamp01(state.strength * keep)
        status = state.status
        if strength < 0.12 and state.status == "active":
            status = "stale" #Nghĩa là goal không biến mất ngay, nhưng yếu dần. Đây là memory decay
        return GoalPersistenceState(
            goal_id=state.goal_id,
            summary=state.summary,
            source=state.source,
            status=status,
            strength=strength,
            urgency=_clamp01(state.urgency * keep),
            drift=state.drift,
            progress=state.progress,
            recurrence_count=state.recurrence_count,
            created_at=state.created_at,
            updated_at=now if state.status == "active" else state.updated_at,
            last_reactivated_at=state.last_reactivated_at,
            next_hint=state.next_hint,
            evidence=state.evidence,
            recent_summaries=state.recent_summaries,
        )

    #Đóng goal khi có tín hiệu hoàn tất.
    def _close(self, state: GoalPersistenceState, *, now: float, evidence: str) -> GoalPersistenceState:
        return GoalPersistenceState(
            goal_id=state.goal_id,
            summary=state.summary,
            source=state.source,
            status="closed",
            strength=_clamp01(state.strength * 0.18),
            urgency=_clamp01(state.urgency * 0.12),
            drift=state.drift,
            progress=1.0,
            recurrence_count=state.recurrence_count,
            created_at=state.created_at,
            updated_at=now,
            last_reactivated_at=state.last_reactivated_at,
            next_hint="goal closed by explicit closure signal",
            evidence=tuple(dict.fromkeys((*state.evidence, evidence)))[-8:],
            recent_summaries=state.recent_summaries,
        )

    def _looks_goal_worthy(self, text: str) -> bool:
        normalized = _normalize(text)
        if len(_tokens(normalized)) >= 5:
            return True
        return any(marker in normalized for marker in self.TASK_MARKERS)

    def _has_closure(self, user_text: str, *, thought_stream_report) -> bool:
        normalized = _normalize(user_text)
        if any(marker in normalized for marker in self.CLOSURE_MARKERS):
            return True
        for disturbance in tuple(getattr(thought_stream_report, "disturbances", ()) or ()):
            if bool(getattr(disturbance, "closes_loop", False)):
                return True
        return False

    def _matches(self, left: str, right: str) -> bool:
        left_tokens = _tokens(left)
        right_tokens = _tokens(right)
        if not left_tokens or not right_tokens:
            return False
        overlap = len(left_tokens & right_tokens)
        return overlap >= 2 or overlap / max(1, min(len(left_tokens), len(right_tokens))) >= 0.34
