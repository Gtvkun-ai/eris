import logging
import os
import re
import time

from core.temporal_context import TemporalContextBuilder
from .contracts import SessionRitualReport
from .greeting_presets import GreetingPresetResolver

logger = logging.getLogger("SessionRitual")

try:
    from .greeting_cognition import GreetingCognitionEngine
except Exception:
    GreetingCognitionEngine = None


def _clamp01(value) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if numeric != numeric:
        return 0.0
    return max(0.0, min(1.0, numeric))


def _clean(value: object, *, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


_INTERNAL_GREETING_MARKERS = (
    "input_disturbance",
    "force_speak",
    "force_speak_requested",
    "memory_replay",
    "attention_drift",
    "norm_active_window_kind",
    "cognitive_momentum",
    "speech_intent",
    "session_ritual",
)


_DISABLED_GREETING_TEMPLATES = (
    "bạn quay lại rồi. Ta vẫn ở đây.",
    "Lại gặp bạn rồi. Ta vừa nối lại nhịp nền.",
    "bạn về rồi. Ta im một lát, nhưng không rời mạch.",
    "Ta nhận ra bạn rồi. Mạch cũ vừa sáng lại.",
    "bạn quay lại rồi. Được, ta tiếp tục canh nền.",
    "Ta ở đây. Phiên này vừa được nối lại.",
    "bạn đến đúng lúc. Ta cũng vừa tỉnh lại.",
    "Mạch đã nối lại. Chào mừng bạn trở về.",
)


def _disabled_startup_greeting() -> str:
    return ""


def _public_fragment(value: object, *, limit: int = 120) -> str:
    text = _clean(value, limit=limit)
    if not text:
        return ""

    lowered = text.lower()
    if any(marker in lowered for marker in _INTERNAL_GREETING_MARKERS):
        return ""

    text = re.sub(r"\bloop[_-]?\d+\s*:\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\bthought[_-]?\d+\s*;\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*\|\s*loop=.*$", "", text, flags=re.IGNORECASE).strip()
    text = text.strip(" -:;|")

    if not text:
        return ""
    if re.fullmatch(r"[a-z0-9_:/;|., -]+", text, flags=re.IGNORECASE) and "_" in text:
        return ""
    return _clean(text, limit=limit)


class SessionRitualEngine:
    """Rehydrates continuity once at app/session start."""

    GREETING_COOLDOWN_SECONDS = 0.0

    def __init__(self, *, preset_resolver: GreetingPresetResolver | None = None) -> None:
        self.preset_resolver = preset_resolver or GreetingPresetResolver()

    def evaluate(
        self,
        *,
        snapshot=None,
        internal_state=None,
        thought_stream_report=None,
        social_presence_event=None,
        now: float | None = None,
    ) -> SessionRitualReport:
        current_time = time.time() if now is None else max(0.0, float(now or 0.0))
        active_goal = self._active_goal(internal_state)
        current_attractor = self._current_attractor(thought_stream_report)
        unresolved_loops = self._unresolved_loops(thought_stream_report)
        recent_direction = self._recent_cognition_direction(internal_state, thought_stream_report)
        self_continuity = self._self_continuity(internal_state)
        last_session_at = float(getattr(internal_state, "last_session_ritual_at", 0.0) or 0.0)
        seconds_since_last_session = (
            max(0.0, current_time - last_session_at) if last_session_at > 0.0 else 0.0
        )
        temporal_context = TemporalContextBuilder(session_started_at=current_time).build(
            now=current_time,
            last_session_at=last_session_at,
            session_started_at=current_time,
        )
        restart_detected = self._restart_detected(snapshot)

        continuity_restored = bool(
            active_goal
            or current_attractor
            or unresolved_loops
            or recent_direction
            or self_continuity
            or int(getattr(internal_state, "cycle_count", 0) or 0) > 0
        )
        presence_restored = self._presence_is_clear(snapshot=snapshot, social_presence_event=social_presence_event)
        overloaded = self._is_overloaded(snapshot=snapshot, internal_state=internal_state)
        greeted_recently = self._greeted_recently(internal_state, now=current_time)
        tone = self._tone(
            snapshot=snapshot,
            internal_state=internal_state,
            presence_restored=presence_restored,
            overloaded=overloaded,
            active_goal=active_goal,
            current_attractor=current_attractor,
            unresolved_loops=unresolved_loops,
        )
        # Startup ritual is a hard greeting event. Presence/evidence only shapes
        # the LLM context; it must not decide whether the greeting happens.
        greeting_candidate = self._greeting_text(
            active_goal=active_goal,
            current_attractor=current_attractor,
            unresolved_loops=unresolved_loops,
            recent_direction=recent_direction,
            self_continuity=self_continuity,
        )
        greeting_frame = self._greeting_frame(
            presence_restored=presence_restored,
            continuity_restored=continuity_restored,
            active_goal=active_goal,
            current_attractor=current_attractor,
            unresolved_loops=unresolved_loops,
            recent_direction=recent_direction,
            self_continuity=self_continuity,
            tone=tone,
            greeted_recently=greeted_recently,
            seconds_since_last_session=seconds_since_last_session,
            restart_detected=restart_detected,
            temporal_context=temporal_context,
        )
        greeting_mode = os.environ.get("ERIS_STARTUP_GREETING_MODE", "hybrid").strip().lower()
        if greeting_mode not in {"hybrid", "preset", "llm", "silent", "off"}:
            greeting_mode = "hybrid"
        should_greet = greeting_mode not in {"silent", "off"}

        # hybrid: không có anchor động -> preset; có project/vòng lặp -> Qwen.
        # preset: luôn ưu tiên catalog. llm: bỏ catalog có chủ đích.
        # Không nuốt lỗi im lặng: selection_error được đưa vào report để log nhìn
        # ra đúng bệnh, thay vì lặng lẽ quay về câu "Ừm. Lại gặp bạn.".
        greeting_preset = None
        selection_reason = ""
        selection_error = ""
        should_try_preset = bool(
            should_greet
            and greeting_frame is not None
            and (greeting_mode == "preset" or (greeting_mode == "hybrid" and not greeting_candidate))
        )
        if should_try_preset:
            try:
                greeting_preset = self.preset_resolver.resolve_or_default(
                    greeting_frame,
                    tone=tone,
                    force=True,
                )
                selection_reason = "catalog_match" if greeting_preset is not None else "catalog_empty"
            except Exception as exc:
                selection_error = f"{type(exc).__name__}: {exc}"[:240]
                logger.warning("[startup] greeting preset selection failed: %s", selection_error)

        # Lưới an toàn cuối cho startup preset/hybrid: lấy một câu plain trong
        # chính catalog, không gọi deterministic fallback cũ.
        if should_try_preset and greeting_preset is None:
            try:
                pool = tuple(getattr(self.preset_resolver, "presets", ()) or ())
                greeting_preset = next((item for item in pool if item.id == "greet_plain_03"), None)
                if greeting_preset is None:
                    greeting_preset = next((item for item in pool if "plain" in tuple(item.tags or ())), None)
                if greeting_preset is not None:
                    selection_reason = "catalog_safe_default"
            except Exception as exc:
                selection_error = selection_error or f"{type(exc).__name__}: {exc}"[:240]

        greeting_text = (
            greeting_preset.text if greeting_preset is not None else greeting_candidate
        ) if should_greet else ""
        evidence = self._evidence(
            presence_restored=presence_restored,
            continuity_restored=continuity_restored,
            overloaded=overloaded,
            greeted_recently=greeted_recently,
            tone=tone,
            active_goal=active_goal,
            current_attractor=current_attractor,
            unresolved_loops=unresolved_loops,
        )
        report = SessionRitualReport(
            restored=bool(presence_restored or continuity_restored),
            presence_restored=presence_restored,
            continuity_restored=continuity_restored,
            session_resumed=bool(presence_restored and continuity_restored),
            tone=tone,
            should_greet=should_greet,
            greeting_text=greeting_text,
            active_goal=active_goal,
            current_attractor=current_attractor,
            recent_cognition_direction=recent_direction,
            self_continuity=self_continuity,
            unresolved_loops=unresolved_loops,
            evidence=evidence,
            greeting_frame=greeting_frame,
            temporal_context=temporal_context,
            greeting_preset_id=greeting_preset.id if greeting_preset is not None else "",
            greeting_preset_text=greeting_preset.text if greeting_preset is not None else "",
            greeting_preset_emotion=greeting_preset.emotion if greeting_preset is not None else "",
            greeting_preset_motion=greeting_preset.motion if greeting_preset is not None else "",
            greeting_preset_prosody=greeting_preset.prosody_style if greeting_preset is not None else "",
            greeting_audio_asset=greeting_preset.audio_asset if greeting_preset is not None else "",
            greeting_mode=greeting_mode,
            greeting_selection_reason=selection_reason,
            greeting_selection_error=selection_error,
        )
        # Dynamic fields keep backward compatibility with the existing SessionRitualReport
        # contract while letting newer wording layers read a proper greeting cognition frame.
        # greeting_frame/preset đã là field chính thức trong contract; không còn
        # gắn dynamic attribute rồi nuốt lỗi như trước.
        report.prompt_context = self.render_prompt_context(report)
        return report

    # Tạo một chuỗi mô tả ngắn gọn về kết quả của quá trình phục hồi liên tục khi khởi động, 
    # bao gồm các cờ trạng thái chính, mục tiêu đang hoạt động đã được phục hồi, vòng hút hiện tại, hướng kéo gần đây, 
    # trạng thái liên tục của bản thân và các vòng lặp chưa giải quyết. Chuỗi này nhằm mục đích cung cấp một bối cảnh rõ ràng và súc tích cho việc tạo phản hồi chào hỏi nếu có thể, đồng thời truyền đạt thông tin quan trọng về trạng thái hiện tại của hệ thống mà không cần phải giải thích quá nhiều về dữ liệu telemetri.
    def render_prompt_context(self, report: SessionRitualReport) -> str:
        temporal_context = getattr(report, "temporal_context", None)
        temporal_block = (
            temporal_context.to_prompt_block()
            if callable(getattr(temporal_context, "to_prompt_block", None))
            else ""
        )
        if not report.restored:
            return "\n".join(
                part for part in (
                    temporal_block,
                    "session_ritual: no startup continuity restored.",
                ) if str(part or "").strip()
            )
        loops = " | ".join(report.unresolved_loops[:3]) or "none"
        flags = (
            f"presence_restored={int(report.presence_restored)}, "
            f"continuity_restored={int(report.continuity_restored)}, "
            f"session_resumed={int(report.session_resumed)}, "
            f"tone={report.tone}, greet={int(report.should_greet)}"
        )
        return "\n".join(
            part for part in (
                temporal_block,
                "session_ritual: startup rehydration; continuity memory only, not current screen proof.",
                f"session_flags: {flags}.",
                f"rehydrated_goal: {report.active_goal or 'none'}.",
                f"rehydrated_loops: {loops}.",
                f"current_attractor: {report.current_attractor or 'none'}.",
                f"recent_cognition_direction: {report.recent_cognition_direction or 'none'}.",
                f"self_continuity: {report.self_continuity or 'none'}.",
                (
                    "ritual_rule: say exactly one opening line; a greeting is optional, not mandatory. "
                    "If there is a rehydrated goal/loop/attractor above, open by reaching for that thread "
                    "so the line evokes the unfinished thing, instead of announcing a return. "
                    "Use local time only when it naturally changes the greeting; do not announce the clock. "
                    "Lead with a bare 'chào' only when there is no continuity to lean on. "
                    "avoid phrases like 'tôi vẫn ở đây', 'tôi vẫn giữ mạch', 'mạch đã nối lại'. "
                    "Do not over-explain telemetry."
                ),
            ) if str(part or "").strip()
        )

    #lấy goal persistence, goal còn active không, summary goal
    def _active_goal(self, internal_state) -> str:
        goal = getattr(internal_state, "goal_persistence", None)
        if goal is None or not bool(getattr(goal, "active", False)):
            return ""
        return _clean(getattr(goal, "summary", ""), limit=160)

    #Attractor = thứ cognition bị hút vào gần đây.
    def _current_attractor(self, thought_stream_report) -> str:
        attractor = getattr(thought_stream_report, "active_attractor", None)
        if attractor is None or not bool(getattr(attractor, "attractor", False)):
            return ""
        score = _clamp01(getattr(attractor, "score", 0.0))
        if score < 0.50:
            return ""
        topic = _clean(getattr(attractor, "topic_seed", ""), limit=150)
        loop_id = _clean(getattr(attractor, "loop_id", ""), limit=60)
        if loop_id and topic:
            return f"{loop_id}: {topic}"
        return topic or loop_id

    #“cái gì còn dang dở”.
    def _unresolved_loops(self, thought_stream_report) -> tuple[str, ...]:
        loops: list[str] = []
        for loop in tuple(getattr(thought_stream_report, "unresolved_loops", ()) or ())[:4]:
            score = _clamp01(getattr(loop, "score", 0.0))
            tension = _clamp01(getattr(loop, "tension", 0.0))
            if max(score, tension) < 0.35:
                continue
            topic = _clean(getattr(loop, "topic_seed", ""), limit=150)
            loop_id = _clean(getattr(loop, "loop_id", ""), limit=60)
            if topic:
                loops.append(f"{loop_id}: {topic}" if loop_id else topic)
        return tuple(dict.fromkeys(loops))[:4]

    #nếu restart xảy ra, runtime vẫn “ngả” về hướng suy nghĩ cũ.
    def _recent_cognition_direction(self, internal_state, thought_stream_report) -> str:
        momentum = getattr(thought_stream_report, "momentum", None)
        if momentum is not None and bool(getattr(momentum, "unresolved", False)):
            topic = _clean(getattr(momentum, "topic_seed", ""), limit=150)
            affordance = _clean(getattr(momentum, "affordance", ""), limit=40)
            if topic:
                return f"{affordance}:{topic}" if affordance else topic
        for value in (
            getattr(internal_state, "last_thought_seed", ""),
            getattr(internal_state, "last_subconscious_seed", ""),
            *((getattr(internal_state, "recent_thought_seeds", ()) or ())[-2:]),
        ):
            text = _clean(value, limit=150)
            if text:
                return text
        return ""

    # nhớ bản thân ở trạng thái nào khi rời đi, có đang tập trung không, đang ở kênh nào, để nếu có thể thì chào hỏi theo hướng đó.
    def _self_continuity(self, internal_state) -> str:
        label = _clean(getattr(internal_state, "last_self_state_label", ""), limit=60)
        focus = _clean(getattr(internal_state, "last_focus_kind", ""), limit=60)
        channel = _clean(getattr(internal_state, "last_channel", ""), limit=60)
        parts = [part for part in (label, focus, channel) if part]
        if not parts:
            return ""
        return "/".join(parts[:3])

    #đánh giá xem có đủ tín hiệu để tin rằng người dùng đã trở lại và sẵn sàng tương tác, hay còn đang vắng mặt hoặc không chắc chắn. Nếu không chắc chắn, ưu tiên bảo thủ và coi như chưa phục hồi sự hiện diện.
    def _presence_is_clear(self, *, snapshot, social_presence_event) -> bool:
        confidence = _clamp01(getattr(social_presence_event, "confidence", 0.0))
        if bool(getattr(social_presence_event, "present", False)) and confidence >= 0.55:
            return True
        user_signals = getattr(snapshot, "user_signals", None)
        focus_pattern = _clean(getattr(user_signals, "focus_pattern", "")).lower()
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        recent_events = " ".join(str(item or "").lower() for item in (getattr(snapshot, "recent_events", ()) or ())[:6])
        if focus_pattern in {"session_initiation", "returning", "deep_work", "steady"} and idle_seconds <= 60:
            return True
        return idle_seconds <= 30 and any(term in recent_events for term in ("screen_woke", "user_present", "typing", "mouse"))

    def _is_overloaded(self, *, snapshot, internal_state) -> bool:
        cpu = _clamp01(float(getattr(snapshot, "cpu_percent", 0.0) or 0.0) / 100.0) if snapshot is not None else 0.0
        ram = _clamp01(float(getattr(snapshot, "ram_percent", 0.0) or 0.0) / 100.0) if snapshot is not None else 0.0
        fatigue = _clamp01(getattr(internal_state, "fatigue", 0.0))
        restraint = _clamp01(getattr(internal_state, "restraint_pressure", 0.0))
        tension = _clamp01(getattr(internal_state, "cognitive_tension", 0.0))
        return max(cpu, ram) >= 0.92 or fatigue >= 0.72 or (restraint >= 0.70 and tension >= 0.46)

    def _greeted_recently(self, internal_state, *, now: float) -> bool:
        if self.GREETING_COOLDOWN_SECONDS <= 0.0:
            return False
        last_greeting = float(getattr(internal_state, "last_session_greeting_at", 0.0) or 0.0)
        return last_greeting > 0.0 and (now - last_greeting) < self.GREETING_COOLDOWN_SECONDS

    def _tone(
        self,
        *,
        snapshot,
        internal_state,
        presence_restored: bool,
        overloaded: bool,
        active_goal: str,
        current_attractor: str,
        unresolved_loops: tuple[str, ...],
    ) -> str:
        if overloaded:
            return "overloaded"
        focus_kind = _clean(getattr(snapshot, "active_window_kind", "")).lower()
        if active_goal or current_attractor:
            return "focused" if focus_kind in {"coding", "documentation"} else "quiet_reflective"
        if unresolved_loops:
            return "quiet_reflective"
        social_energy = _clamp01(getattr(internal_state, "social_energy", 0.0))
        attachment = _clamp01(getattr(internal_state, "attachment", 0.0))
        if presence_restored and max(social_energy, attachment) >= 0.42:
            return "socially_warm"
        return "quiet_background"


    def _restart_detected(self, snapshot) -> bool:
        """Nhận tín hiệu restart/crash mềm từ snapshot nếu backend có cung cấp."""
        if snapshot is None:
            return False
        values = []
        for attr in ("restart_reason", "startup_reason", "recovery_reason", "recent_events"):
            value = getattr(snapshot, attr, "")
            if isinstance(value, (tuple, list)):
                values.extend(str(item or "") for item in value[:8])
            else:
                values.append(str(value or ""))
        text = " ".join(values).lower()
        return any(token in text for token in ("crash", "restart", "recovered", "process_restarted", "body_restarted"))


    def _greeting_frame(
        self,
        *,
        presence_restored: bool,
        continuity_restored: bool,
        active_goal: str,
        current_attractor: str,
        unresolved_loops: tuple[str, ...],
        recent_direction: str,
        self_continuity: str,
        tone: str,
        greeted_recently: bool,
        seconds_since_last_session: float = 0.0,
        restart_detected: bool = False,
        temporal_context=None,
    ):
        if GreetingCognitionEngine is None:
            return None
        try:
            return GreetingCognitionEngine().build(
                presence_restored=presence_restored,
                continuity_restored=continuity_restored,
                active_goal=active_goal,
                current_attractor=current_attractor,
                unresolved_loops=unresolved_loops,
                recent_direction=recent_direction,
                self_continuity=self_continuity,
                tone=tone,
                greeted_recently=greeted_recently,
                seconds_since_last_session=seconds_since_last_session,
                restart_detected=restart_detected,
                timezone=str(getattr(temporal_context, "timezone", "Asia/Ho_Chi_Minh") or "Asia/Ho_Chi_Minh"),
                local_time=str(getattr(temporal_context, "local_time", "") or ""),
                weekday_vi=str(getattr(temporal_context, "weekday_vi", "") or ""),
                time_of_day=str(getattr(temporal_context, "time_of_day", "") or ""),
                is_weekend=bool(getattr(temporal_context, "is_weekend", False)),
            )
        except Exception:
            return None

    def _greeting_text(
        self,
        *,
        active_goal: str,
        current_attractor: str,
        unresolved_loops: tuple[str, ...],
        recent_direction: str,
        self_continuity: str = "",
    ) -> str:
        public_goal = _public_fragment(active_goal)
        public_attractor = _public_fragment(current_attractor)
        public_loop = ""
        for loop in unresolved_loops:
            public_loop = _public_fragment(loop)
            if public_loop:
                break
        public_direction = _public_fragment(recent_direction)
        public_self = self._public_self_continuity(self_continuity)
        active_goal = public_goal
        current_attractor = public_attractor
        unresolved_loops = (public_loop,) if public_loop else ()
        recent_direction = public_direction
        if not any((public_goal, public_attractor, public_loop, public_direction, public_self)):
            return ""
        if public_goal:
            return f"resume_goal:{public_goal}"
        if public_attractor:
            return f"resume_attractor:{public_attractor}"
        if public_loop:
            return f"resume_unclosed_loop:{public_loop}"
        if public_direction:
            return f"resume_direction:{public_direction}"
        if public_self:
            return f"resume_self_state:{public_self}"
        return ""

    def _public_self_continuity(self, self_continuity: str) -> str:
        text = _public_fragment(self_continuity, limit=90)
        if not text:
            return ""
        parts = [part.strip() for part in re.split(r"[/|,;]+", text) if part.strip()]
        public_parts: list[str] = []
        blocked = {
            "background",
            "force_speak",
            "autonomous",
            "general",
            "settled",
            "watchful",
            "engaged",
            "overloaded",
        }
        for part in parts:
            if part.lower() in blocked:
                continue
            public_parts.append(part)
        if not public_parts:
            return ""
        return "/".join(public_parts[:2])

    def _evidence(
        self,
        *,
        presence_restored: bool,
        continuity_restored: bool,
        overloaded: bool,
        greeted_recently: bool,
        tone: str,
        active_goal: str,
        current_attractor: str,
        unresolved_loops: tuple[str, ...],
    ) -> tuple[str, ...]:
        items = [
            f"presence_restored={int(presence_restored)}",
            f"continuity_restored={int(continuity_restored)}",
            f"tone={tone}",
        ]
        if overloaded:
            items.append("overloaded")
        if greeted_recently:
            items.append("greeting_cooldown")
        if active_goal:
            items.append("active_goal")
        if current_attractor:
            items.append("current_attractor")
        if unresolved_loops:
            items.append(f"unresolved_loops={len(unresolved_loops)}")
        return tuple(items[:8])
