from dataclasses import dataclass

from .contracts import SocialPresenceEvent
from .event_semantics import EventSemanticProfile, EventSemanticProfiler
'''
Lớp SocialPresenceDetector không phân tích tin nhắn, mà dùng phương pháp heuristic
 (dựa trên trọng số cộng dồn) để đánh giá xem bạn có đang thực sự "ở đó" và "tập trung" hay không.
'''

def _clean(value: object) -> str:
    return str(value or "").strip()


def _clamp(value: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    if numeric != numeric:
        numeric = 0.0
    return max(0.0, min(1.0, numeric))


@dataclass(slots=True)
class PresenceFeatureVector:
    activity: float = 0.0
    focus_depth: float = 0.0
    task_continuity: float = 0.0
    interaction_density: float = 0.0
    companionship: float = 0.0
    passive_absence: float = 0.0
    switching_noise: float = 0.0
    anxious_motion: float = 0.0
    semantic_profiles: tuple[EventSemanticProfile, ...] = ()
    matched_event: str = ""

    def numeric_tuple(self) -> tuple[float, ...]:
        return (
            _clamp(self.activity),
            _clamp(self.focus_depth),
            _clamp(self.task_continuity),
            _clamp(self.interaction_density),
            _clamp(self.companionship),
            _clamp(self.passive_absence),
            _clamp(self.switching_noise),
            _clamp(self.anxious_motion),
        )


# PresenceMemory là một cấu trúc dữ liệu để lưu trữ trạng thái nội bộ của trình phát hiện sự hiện diện xã hội theo thời gian.
@dataclass(slots=True)
class PresenceMemory:
    ema_presence: float = 0.0 # Exponential Moving Average (EMA) của sự hiện diện, giúp làm mượt tín hiệu và duy trì trạng thái qua thời gian.
    ema_activity: float = 0.0 # EMA của hoạt động, theo dõi mức độ hoạt động tổng thể của người dùng.
    ema_focus_depth: float = 0.0 # EMA của độ sâu tập trung, đánh giá mức độ tập trung và chú ý của người dùng.
    ema_anxiety: float = 0.0 # EMA của sự lo lắng, theo dõi các tín hiệu cho thấy sự căng thẳng hoặc bất an (như chuyển động lo lắng hoặc lỗi liên quan đến ngữ cảnh).
    ema_fragmentation: float = 0.0 # EMA của sự phân mảnh, theo dõi mức độ gián đoạn trong hoạt động của người dùng.
    continuity_persistence: float = 0.0 # Đo lường mức độ nhất quán trong hành vi của người dùng theo thời gian.
    last_kind: str = "" # Loại sự hiện diện được phân loại gần đây nhất (ví dụ: "focused_co_presence", "passive_companionship", v.v.)
    kind_streak: int = 0



# SocialPresenceDetector là lớp chính để phát hiện sự hiện diện xã hội dựa trên các tín hiệu hành vi và ngữ nghĩa từ snapshot và trạng thái nội bộ. Nó sử dụng một bộ nhớ để duy trì trạng thái qua thời gian và một bộ phân tích ngữ nghĩa sự kiện để hiểu ý nghĩa của các hành động gần đây.
class SocialPresenceDetector:
    """Detects ambient co-presence without treating it as chat or speech intent."""

    NON_CHAT_CHANNELS = {"autonomous", "background"}
    ACTIVE_TYPING = {"slow", "medium", "fast", "high", "very_fast", "extreme_fluctuation", "low"}
    PRESENT_FOCUS = {
        "attentive_listening",
        "deep",
        "deep_work",
        "distracted_typing",
        "frantic_tweaking",
        "heavy_contemplation",
        "lost_in_thought",
        "perfectionism_paralysis",
        "searching_for_anchor",
        "stable",
        "steady",
        "sustained",
    }
    ABSENT_FOCUS = {"absent", "microsleep_nodding", "passive_consumption"}
    PRESENCE_EVENT_TERMS = (
        "active",
        "click",
        "cursor",
        "editing",
        "highlight",
        "key",
        "mouse",
        "scroll",
        "typing",
        "window_active",
    )
    PRESENCE_SYMBOLIC_TAGS = {
        "click",
        "coding",
        "editing",
        "hover",
        "keyboard",
        "mouse",
        "scroll",
        "selection",
        "window_active",
        "window_switch",
    }

    def __init__(self, *, semantic_profiler: EventSemanticProfiler | None = None):
        self.semantic_profiler = semantic_profiler or EventSemanticProfiler()
        self.memory = PresenceMemory()

    #Chế độ này bật allow_embedding=True. Khi đó, nếu có một hành vi máy tính mới 
    # toanh mà cache chưa có (vd: chuỗi text dài hơn 18 ký tự và chưa từng xuất hiện), 
    # nó sẽ tiến hành gọi đến model embedding.
    def learn_event_patterns(self, events) -> tuple[EventSemanticProfile, ...]:
        """Background path: enrich meaningful events without blocking detection."""
        return self.semantic_profiler.profile_events(events, allow_embedding=True)

    def detect(
        self,
        *,
        channel: str,
        snapshot=None,
        internal_state=None,
        user_text: str = "",
        force_speak: bool = False,
        timestamp: str = "",
    ) -> SocialPresenceEvent:
        channel_name = _clean(channel) or "autonomous"
        if channel_name not in self.NON_CHAT_CHANNELS or force_speak or _clean(user_text):
            return SocialPresenceEvent(timestamp=timestamp)

        user_signals = getattr(snapshot, "user_signals", None)
        typing_speed = _clean(getattr(user_signals, "typing_speed", "")).lower()
        switching = _clean(getattr(user_signals, "window_switching", "")).lower()
        focus_pattern = _clean(getattr(user_signals, "focus_pattern", "")).lower()
        focus_kind = _clean(getattr(snapshot, "active_window_kind", ""))
        previous_focus = _clean(getattr(internal_state, "last_focus_kind", ""))
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        recent_events = tuple(
            str(item or "").strip()
            for item in (getattr(snapshot, "recent_events", ()) or ())
            if str(item or "").strip()
        )
        #Nó chỉ lấy các vector đã được lưu sẵn trong bộ nhớ đệm (cache) ra dùng. 
        # Mục đích là để hàm detect() chạy chớp nhoáng (non-blocking) và không bị 
        # treo máy nếu model AI đang bận.
        #Đây là phần chuyển telemetry thành PresenceFeatureVector.
        v = self._build_feature_vector(
            typing_speed=typing_speed,
            switching=switching,
            focus_pattern=focus_pattern,
            focus_kind=focus_kind,
            previous_focus=previous_focus,
            idle_seconds=idle_seconds,
            recent_events=recent_events,
        )
        #tạo evidence debug
        evidence = list(
            self._vector_evidence(
                v,
                typing_speed=typing_speed,
                switching=switching,
                focus_pattern=focus_pattern,
                focus_kind=focus_kind,
                previous_focus=previous_focus,
                idle_seconds=idle_seconds,
            )
        )
        '''
        0.35 * activity
        + 0.22 * focus_depth
        + 0.18 * task_continuity
        + 0.12 * interaction_density
        + 0.18 * companionship
        - 0.22 * passive_absence
        - 0.10 * switching_noise
        '''
        # Điểm số thô (raw confidence) được tính toán dựa trên vector đặc trưng, sau đó được kết hợp với trạng thái bộ nhớ để đưa ra quyết định cuối cùng về sự hiện diện và loại hình sự hiện diện.
        raw_confidence = self._score_vector(v)
        #phân loại kind
        raw_kind = self._classify_presence_kind(v, idle_seconds=idle_seconds)
        #Nếu detector mới khởi tạo nhưng internal_state còn biết lần trước user đang present, nó khôi phục EMA từ đó. Cái này tốt cho continuity sau restart.
        self._hydrate_memory_from_internal_state(internal_state) 
        was_present = bool(getattr(internal_state, "last_social_presence_present", False)) # Kiểm tra xem trạng thái nội bộ gần đây có cho thấy sự hiện diện hay không.
        if not was_present: # Nếu trạng thái nội bộ không cho thấy sự hiện diện, nó sẽ dựa vào bộ nhớ EMA để ước tính xem người dùng có đang hiện diện hay không, với một ngưỡng nhất định (0.34) và loại hình sự hiện diện gần đây không phải là "absence".
            was_present = self.memory.ema_presence >= 0.34 and self.memory.last_kind not in {
                "presence_absent_or_fading",
                "ambient_presence_below_threshold",
            }
        memory = self._update_memory(v, raw_confidence, raw_kind)

        confidence = _clamp( # Điểm số cuối cùng được tính toán bằng cách kết hợp điểm số thô với các yếu tố từ bộ nhớ, với trọng số khác nhau để phản ánh tầm quan trọng của từng yếu tố.
            raw_confidence * 0.58 #58% frame hiện tại
            + memory.ema_presence * 0.32 #32% trạng thái tích lũy qua thời gian
            + memory.continuity_persistence * 0.10 #10% tính nhất quán của hành vi qua thời gian
        )
        # Ngưỡng để xác định xem người dùng có đang hiện diện hay không được điều chỉnh dựa trên việc họ đã được xem là hiện diện trong trạng thái nội bộ gần đây hay không, với một ngưỡng cao hơn (0.38) nếu họ chưa được xem là hiện diện, và một ngưỡng thấp hơn (0.30) nếu họ đã được xem là hiện diện.
        present_threshold = 0.38
        keep_present_threshold = 0.30
        present = confidence >= (keep_present_threshold if was_present else present_threshold)
        if memory.last_kind == raw_kind and memory.kind_streak >= 2:
            kind = raw_kind
        else:
            kind = "ambient_co_presence" if present else "ambient_presence_below_threshold"

        return SocialPresenceEvent(
            present=present,
            confidence=confidence,
            intensity=_clamp(0.20 + confidence * 0.62),
            kind=kind,
            reason=self._reason_for_kind(kind),
            evidence=tuple(dict.fromkeys(evidence))[:8],
            timestamp=timestamp,
            speech_allowed=False,
            presence_vector=v.numeric_tuple(),
            stability=_clamp(0.45 * memory.ema_presence + 0.35 * memory.ema_focus_depth + 0.20 * memory.continuity_persistence),
            continuity_persistence=memory.continuity_persistence,
            fragmentation=memory.ema_fragmentation,
            anxiety=memory.ema_anxiety,
        )

    def _build_feature_vector(
        self,
        *,
        typing_speed: str,
        switching: str,
        focus_pattern: str,
        focus_kind: str,
        previous_focus: str,
        idle_seconds: float,
        recent_events: tuple[str, ...],
    ) -> PresenceFeatureVector:
        semantic_profiles = self.semantic_profiler.profile_events(
            recent_events[:6],
            allow_embedding=False,
            use_cached_embedding=True,
        )
        matched_profile = next(
            (profile for profile in semantic_profiles if self._looks_like_presence_profile(profile)),
            None,
        )
        matched_event = str(getattr(matched_profile, "raw", "") or "")
        all_tags: set[str] = set()
        for profile in semantic_profiles:
            all_tags.update(profile.symbolic_tags)

        '''
        activity

        Cao khi:

        idle <= 12
        typing active
        có matched event
        có tag mouse/click/scroll/keyboard
        focus_depth

        Cao khi:

        deep_work, heavy_contemplation, sustained
        focus_kind là coding hoặc documentation

        Giảm nếu focus_pattern thuộc absent.

        task_continuity

        Cao khi:

        focus_kind giống previous_focus
        đang coding/docs/communication
        event tag có editing + coding
        interaction_density

        Cao khi:

        typing active
        switching có hoạt động
        có keyboard/selection/click
        companionship

        Đây là “ở gần nhưng không nhất thiết tương tác nhiều”. Cao khi:

        activity đủ
        focus_depth đủ
        focus_kind có ý nghĩa
        idle ngắn dù không có event
        passive_absence

        Cao khi:

        idle >= 300 hoặc 900
        focus absent/passive
        entertainment/passive/distraction

        Nhưng nếu vẫn có event hoặc typing thì giảm bớt.

        switching_noise

        Cao khi:

        switching high/very_high/extreme
        semantic tag có window_switch
        anxious_motion

        Cao khi:

        frantic_tweaking
        perfectionism_paralysis
        searching_for_anchor
        build_error + window_switch
        '''
        activity = 0.0
        if idle_seconds <= 12:
            activity = 0.88
        elif idle_seconds <= 90:
            activity = 0.58
        elif idle_seconds <= 300:
            activity = 0.24
        elif idle_seconds <= 900:
            activity = 0.08
        if typing_speed in self.ACTIVE_TYPING:
            activity = max(activity, 0.78)
        if matched_event:
            activity = max(activity, 0.68)
        if all_tags & {"mouse", "click", "scroll", "keyboard", "selection", "hover"}:
            activity = max(activity, 0.62)

        focus_depth = 0.0
        if focus_pattern in {"deep", "deep_work", "heavy_contemplation", "lost_in_thought", "sustained"}:
            focus_depth = 0.86
        elif focus_pattern in {"steady", "stable", "attentive_listening"}:
            focus_depth = 0.66
        elif focus_pattern in {"searching_for_anchor", "frantic_tweaking", "perfectionism_paralysis"}:
            focus_depth = 0.46
        elif focus_pattern in self.PRESENT_FOCUS:
            focus_depth = 0.52
        if focus_kind in {"coding", "documentation"}:
            focus_depth = max(focus_depth, 0.62)
        elif focus_kind == "communication":
            focus_depth = max(focus_depth, 0.44)
        if focus_pattern in self.ABSENT_FOCUS:
            focus_depth *= 0.35

        task_continuity = 0.0
        if focus_kind and previous_focus and focus_kind == previous_focus:
            task_continuity = 0.72
        elif focus_kind in {"coding", "documentation", "communication"}:
            task_continuity = 0.45
        if {"editing", "coding"} <= all_tags or {"coding", "stall"} <= all_tags:
            task_continuity = max(task_continuity, 0.82)
        elif all_tags & {"editing", "coding", "communication"}:
            task_continuity = max(task_continuity, 0.54)

        interaction_density = 0.0
        if typing_speed in self.ACTIVE_TYPING:
            interaction_density = 0.76
        elif typing_speed == "zero":
            interaction_density = 0.08
        if switching in {"low", "medium", "high"}:
            interaction_density = max(interaction_density, 0.24 if switching == "low" else 0.36)
        if all_tags & {"keyboard", "selection", "click"}:
            interaction_density = max(interaction_density, 0.58)
        elif all_tags & {"mouse", "scroll", "hover"}:
            interaction_density = max(interaction_density, 0.38)

        companionship = 0.0
        if activity >= 0.55 and focus_depth >= 0.40:
            companionship = 0.42
        if focus_kind in {"coding", "documentation", "communication"}:
            companionship = max(companionship, 0.36)
        if all_tags & {"window_active", "window_switch", "editing", "coding"}:
            companionship = max(companionship, 0.34)
        if idle_seconds <= 90 and not recent_events:
            companionship = max(companionship, 0.24)

        passive_absence = 0.0
        if idle_seconds >= 900:
            passive_absence = 0.92
        elif idle_seconds >= 300:
            passive_absence = 0.72
        elif idle_seconds >= 120:
            passive_absence = 0.36
        if focus_pattern in self.ABSENT_FOCUS:
            passive_absence = max(passive_absence, 0.70)
        if focus_kind in {"entertainment", "passive"} or all_tags & {"distraction"}:
            passive_absence = max(passive_absence, 0.46)
        if recent_events or typing_speed in self.ACTIVE_TYPING:
            passive_absence *= 0.70

        switching_noise = 0.0
        if switching in {"very_high", "extreme"}:
            switching_noise = 0.92
        elif switching == "high":
            switching_noise = 0.72
        elif switching == "medium":
            switching_noise = 0.45
        elif switching == "low":
            switching_noise = 0.18
        if {"window_switch", "restless"} <= all_tags:
            switching_noise = max(switching_noise, 0.72)
        elif "window_switch" in all_tags:
            switching_noise = max(switching_noise, 0.52)

        anxious_motion = 0.0
        if focus_pattern in {"frantic_tweaking", "perfectionism_paralysis", "searching_for_anchor"}:
            anxious_motion = 0.68
        if {"build_error", "window_switch"} <= all_tags:
            anxious_motion = max(anxious_motion, 0.76)
        elif all_tags & {"build_error", "stall"} and switching_noise >= 0.35:
            anxious_motion = max(anxious_motion, 0.58)

        return PresenceFeatureVector(
            activity=_clamp(activity),
            focus_depth=_clamp(focus_depth),
            task_continuity=_clamp(task_continuity),
            interaction_density=_clamp(interaction_density),
            companionship=_clamp(companionship),
            passive_absence=_clamp(passive_absence),
            switching_noise=_clamp(switching_noise),
            anxious_motion=_clamp(anxious_motion),
            semantic_profiles=semantic_profiles,
            matched_event=matched_event,
        )

    # Phương pháp này cập nhật bộ nhớ của trình phát hiện sự hiện diện xã hội dựa trên trạng thái nội bộ gần đây. Nếu trạng thái nội bộ cho thấy rằng người dùng đã được xem là hiện diện với một mức độ tự tin nhất định, nó sẽ khởi tạo bộ nhớ EMA và loại hình sự hiện diện gần đây để duy trì tính liên tục trong việc phát hiện sự hiện diện.
    def _hydrate_memory_from_internal_state(self, internal_state) -> None:
        if internal_state is None or self.memory.ema_presence > 0.0 or self.memory.last_kind:
            return
        was_present = bool(getattr(internal_state, "last_social_presence_present", False))
        previous_confidence = _clamp(getattr(internal_state, "last_social_presence_confidence", 0.0))
        if was_present and previous_confidence <= 0.0:
            previous_confidence = 0.38
        if previous_confidence <= 0.0:
            return
        self.memory.ema_presence = previous_confidence
        self.memory.continuity_persistence = 0.12 if was_present else 0.0
        self.memory.last_kind = _clean(getattr(internal_state, "last_social_presence_kind", ""))
        self.memory.kind_streak = 1 if self.memory.last_kind else 0

    def _score_vector(self, v: PresenceFeatureVector) -> float:
        return _clamp(
            0.35 * v.activity
            + 0.22 * v.focus_depth
            + 0.18 * v.task_continuity
            + 0.12 * v.interaction_density
            + 0.18 * v.companionship
            - 0.22 * v.passive_absence
            - 0.10 * v.switching_noise
        )

    def _ema(self, old: float, new: float, alpha: float) -> float:
        return _clamp(old * (1.0 - alpha) + new * alpha)

    def _update_memory(self, v: PresenceFeatureVector, raw_presence: float, kind: str) -> PresenceMemory:
        m = self.memory
        m.ema_presence = self._ema(m.ema_presence, raw_presence, 0.22)
        m.ema_activity = self._ema(m.ema_activity, v.activity, 0.28)
        m.ema_focus_depth = self._ema(m.ema_focus_depth, v.focus_depth, 0.18)
        m.ema_anxiety = self._ema(m.ema_anxiety, v.anxious_motion, 0.20)
        m.ema_fragmentation = self._ema(m.ema_fragmentation, v.switching_noise, 0.20)

        if kind == m.last_kind:
            m.kind_streak += 1
        else:
            m.kind_streak = 1
            m.last_kind = kind

        continuity_gain = 0.0
        if kind in {"focused_co_presence", "passive_companionship", "ambient_co_presence"}:
            continuity_gain = 0.12
        elif kind == "presence_absent_or_fading":
            continuity_gain = -0.18
        else:
            continuity_gain = -0.04

        m.continuity_persistence = _clamp(m.continuity_persistence * 0.94 + continuity_gain)
        return m

    def _classify_presence_kind(self, v: PresenceFeatureVector, *, idle_seconds: float) -> str:
        if v.passive_absence >= 0.70 and v.activity < 0.32:
            return "presence_absent_or_fading"
        if v.anxious_motion >= 0.55:
            return "anxious_hovering"
        if v.switching_noise >= 0.65 and v.activity >= 0.24:
            return "fragmented_multitasking"
        if v.focus_depth >= 0.60 and v.task_continuity >= 0.45 and v.passive_absence < 0.45:
            return "focused_co_presence"
        if idle_seconds <= 300 and v.companionship >= 0.32 and v.interaction_density < 0.35:
            return "passive_companionship"
        if v.activity >= 0.32 or v.companionship >= 0.30:
            return "ambient_co_presence"
        return "ambient_presence_below_threshold"

    def _reason_for_kind(self, kind: str) -> str:
        reasons = {
            "focused_co_presence": "Stable focus and task continuity suggest shared quiet work.",
            "passive_companionship": "The user appears nearby with low interaction rather than fully gone.",
            "anxious_hovering": "Rapid motion or error-adjacent context suggests unsettled hovering.",
            "fragmented_multitasking": "Window switching suggests fragmented attention while still active.",
            "ambient_co_presence": "Background activity suggests the user remains in the same cognitive space.",
            "presence_absent_or_fading": "Long idle or passive signals suggest presence is fading.",
            "ambient_presence_below_threshold": "Ambient signals were too weak to count as co-presence.",
        }
        return reasons.get(kind, reasons["ambient_co_presence"])

    def _vector_evidence(
        self,
        v: PresenceFeatureVector,
        *,
        typing_speed: str,
        switching: str,
        focus_pattern: str,
        focus_kind: str,
        previous_focus: str,
        idle_seconds: float,
    ) -> tuple[str, ...]:
        evidence: list[str] = []
        if idle_seconds <= 12:
            evidence.append("recent_activity")
        elif idle_seconds <= 90:
            evidence.append(f"short_idle={int(idle_seconds)}s")
        elif idle_seconds >= 300:
            evidence.append(f"long_idle={int(idle_seconds)}s")
        if idle_seconds >= 900:
            evidence.append(f"very_long_idle={int(idle_seconds)}s")
        if typing_speed and typing_speed != "unknown":
            evidence.append(f"typing={typing_speed}")
        if switching and switching != "unknown":
            evidence.append(f"window_switching={switching}")
        if focus_pattern and focus_pattern != "unknown":
            evidence.append(f"focus_pattern={focus_pattern}")
        if v.matched_event:
            evidence.append(f"recent_event={v.matched_event[:80]}")
        semantic_bonus, semantic_evidence = self._semantic_presence_bonus(v.semantic_profiles)
        if semantic_bonus > 0.0:
            evidence.extend(semantic_evidence)
        if focus_kind and previous_focus and focus_kind == previous_focus:
            evidence.append(f"same_focus_kind={focus_kind}")
        elif focus_kind in {"coding", "documentation", "communication"}:
            evidence.append(f"shared_space={focus_kind}")
        evidence.append(f"presence_raw={self._score_vector(v):.2f}")
        return tuple(evidence)

    def _looks_like_presence_event(self, event: str) -> bool:
        lowered = event.lower()
        return any(term in lowered for term in self.PRESENCE_EVENT_TERMS)

    def _looks_like_presence_profile(self, profile: EventSemanticProfile) -> bool:
        tags = set(profile.symbolic_tags)
        if tags & self.PRESENCE_SYMBOLIC_TAGS:
            return True
        return self._looks_like_presence_event(profile.raw)

    def _semantic_presence_bonus(
        self,
        profiles: tuple[EventSemanticProfile, ...],
    ) -> tuple[float, tuple[str, ...]]:
        best_score = 0.0
        best_profile: EventSemanticProfile | None = None
        for profile in profiles:
            tags = set(profile.symbolic_tags)
            score = 0.0
            if {"window_switch", "restless"} <= tags:
                score = max(score, 0.16)
            if {"editing", "coding"} <= tags:
                score = max(score, 0.14)
            if {"coding", "stall"} <= tags:
                score = max(score, 0.14)
            if {"build_error", "window_switch"} <= tags:
                score = max(score, 0.13)
            if tags & {"keyboard", "selection", "hover"}:
                score = max(score, 0.10)
            if profile.embedding and profile.cluster_id:
                score += min(0.04, profile.confidence * 0.04)
            if score > best_score:
                best_score = score
                best_profile = profile
        if best_profile is None or best_score <= 0.0:
            return 0.0, ()
        tags_text = ",".join(best_profile.symbolic_tags[:6])
        evidence = [f"event_tags={tags_text}"]
        if best_profile.cluster_id:
            evidence.append(f"event_cluster={best_profile.cluster_id}")
        return min(0.18, best_score), tuple(evidence)
