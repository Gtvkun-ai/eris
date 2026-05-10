from dataclasses import dataclass, field


def _clamp(value: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = minimum
    if numeric != numeric:
        numeric = minimum
    return max(minimum, min(maximum, numeric))


def _clamp_signed(value: float) -> float:
    return _clamp(value, minimum=-1.0, maximum=1.0)


def _smooth(previous: float, signal: float, *, inertia: float = 0.84) -> float:
    inertia = _clamp(inertia, minimum=0.0, maximum=1.0)
    return previous * inertia + signal * (1.0 - inertia)


def _clean_label(value: object, *, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _append_recent(items: tuple[str, ...], value: str, *, limit: int = 8) -> tuple[str, ...]:
    text = _clean_label(value)
    if not text:
        return tuple(items[-limit:])
    return (*items, text)[-limit:]


@dataclass(slots=True)
class MentalProcess:
    """A low-gain dynamic process, not a stored emotion label."""

    name: str
    level: float = 0.0
    pressure: float = 0.0
    activation: float = 0.0
    volatility: float = 0.20
    decay_rate: float = 0.08
    last_signal: float = 0.0
    last_interaction: float = 0.0

    def evolve(self, *, signal: float = 0.0, interaction: float = 0.0, dt: float = 1.0) -> "MentalProcess":
        dt = max(0.0, min(8.0, float(dt or 1.0)))
        signal = _clamp(signal)
        interaction = _clamp_signed(interaction)
        decay = _clamp(self.decay_rate * dt, minimum=0.0, maximum=0.82)
        responsiveness = _clamp((0.12 + self.volatility * 0.24) * dt, minimum=0.04, maximum=0.62)
        driven = _clamp(signal + interaction)
        activation = _clamp(_smooth(self.activation, driven, inertia=1.0 - responsiveness))
        level = _clamp(self.level * (1.0 - decay) + activation * decay)
        pressure = _clamp(self.pressure * (1.0 - decay * 0.72) + max(level, activation) * responsiveness * 0.46)
        return self.__class__(
            name=self.name,
            level=level,
            pressure=pressure,
            activation=activation,
            volatility=self.volatility,
            decay_rate=self.decay_rate,
            last_signal=signal,
            last_interaction=interaction,
        )

    def dampen(self, amount: float) -> "MentalProcess":
        amount = _clamp(amount, minimum=0.0, maximum=0.92)
        keep = 1.0 - amount
        return self.__class__(
            name=self.name,
            level=_clamp(self.level * keep),
            pressure=_clamp(self.pressure * keep),
            activation=_clamp(self.activation * max(0.18, keep)),
            volatility=self.volatility,
            decay_rate=self.decay_rate,
            last_signal=self.last_signal,
            last_interaction=self.last_interaction,
        )

    def excite(self, amount: float) -> "MentalProcess":
        amount = _clamp(amount)
        return self.__class__(
            name=self.name,
            level=_clamp(self.level + amount * 0.34),
            pressure=_clamp(self.pressure + amount * 0.52),
            activation=_clamp(max(self.activation, amount)),
            volatility=self.volatility,
            decay_rate=self.decay_rate,
            last_signal=max(self.last_signal, amount),
            last_interaction=self.last_interaction,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "level": round(float(self.level), 3),
            "pressure": round(float(self.pressure), 3),
            "activation": round(float(self.activation), 3),
            "volatility": round(float(self.volatility), 3),
            "decay_rate": round(float(self.decay_rate), 3),
            "last_signal": round(float(self.last_signal), 3),
            "last_interaction": round(float(self.last_interaction), 3),
        }

    @classmethod
    def from_dict(cls, data: object, *, name: str, level: float = 0.0, pressure: float = 0.0) -> "MentalProcess":
        if not isinstance(data, dict):
            return cls(name=name, level=_clamp(level), pressure=_clamp(pressure), activation=_clamp(level))
        return cls(
            name=_clean_label(data.get("name"), fallback=name),
            level=_clamp(data.get("level", level)),
            pressure=_clamp(data.get("pressure", pressure)),
            activation=_clamp(data.get("activation", data.get("level", level))),
            volatility=_clamp(data.get("volatility", 0.20)),
            decay_rate=_clamp(data.get("decay_rate", 0.08)),
            last_signal=_clamp(data.get("last_signal", 0.0)),
            last_interaction=_clamp_signed(data.get("last_interaction", 0.0)),
        )


class CuriosityProcess(MentalProcess):
    pass


class RestraintProcess(MentalProcess):
    pass


class TensionProcess(MentalProcess):
    pass


class ContinuityProcess(MentalProcess):
    pass


class AttachmentProcess(MentalProcess):
    pass


class ReflectionProcess(MentalProcess):
    pass


class SocialPresenceProcess(MentalProcess):
    pass


class CognitiveLoadProcess(MentalProcess):
    pass


class BackgroundThoughtProcess(MentalProcess):
    pass


def _default_process(cls, name: str, *, level: float, pressure: float = 0.0, volatility: float, decay_rate: float) -> MentalProcess:
    return cls(
        name=name,
        level=_clamp(level),
        pressure=_clamp(pressure),
        activation=_clamp(level),
        volatility=_clamp(volatility),
        decay_rate=_clamp(decay_rate),
    )


@dataclass(slots=True)
class MentalProcessSystem:
    """Dynamic mental layer whose processes evolve and influence each other."""

    curiosity: MentalProcess = field(
        default_factory=lambda: _default_process(CuriosityProcess, "curiosity", level=0.34, volatility=0.34, decay_rate=0.07)
    )
    restraint: MentalProcess = field(
        default_factory=lambda: _default_process(RestraintProcess, "restraint", level=0.14, volatility=0.22, decay_rate=0.05)
    )
    tension: MentalProcess = field(
        default_factory=lambda: _default_process(TensionProcess, "tension", level=0.08, volatility=0.30, decay_rate=0.09)
    )
    continuity: MentalProcess = field(
        default_factory=lambda: _default_process(ContinuityProcess, "continuity", level=0.40, volatility=0.16, decay_rate=0.035)
    )
    attachment: MentalProcess = field(
        default_factory=lambda: _default_process(AttachmentProcess, "attachment", level=0.34, volatility=0.18, decay_rate=0.03)
    )
    reflection: MentalProcess = field(
        default_factory=lambda: _default_process(ReflectionProcess, "reflection", level=0.18, volatility=0.24, decay_rate=0.06)
    )
    social_presence: MentalProcess = field(
        default_factory=lambda: _default_process(SocialPresenceProcess, "social_presence", level=0.42, volatility=0.26, decay_rate=0.06)
    )
    cognitive_load: MentalProcess = field(
        default_factory=lambda: _default_process(CognitiveLoadProcess, "cognitive_load", level=0.10, volatility=0.28, decay_rate=0.08)
    )
    background_thought: MentalProcess = field(
        default_factory=lambda: _default_process(BackgroundThoughtProcess, "background_thought", level=0.18, volatility=0.32, decay_rate=0.07)
    )

    def evolve( # cập nhật trạng thái nhận thức dựa trên các tín hiệu và tương tác mới, cũng như thời gian trôi qua
        self,
        *,
        channel: str,
        snapshot=None,
        ni_report=None,
        ti_report=None,
        fe_plan=None,
        broadcast=None,
        user_text: str = "",
        force_speak: bool = False,
        dt: float = 1.0,
    ) -> "MentalProcessSystem":
        channel_name = _clean_label(channel, fallback="autonomous") #xác định tên kênh giao tiếp hiện tại, với giá trị mặc định là "autonomous" nếu không có thông tin nào được cung cấp
        direct_user = channel_name in {"chat", "force_speak"} or force_speak or bool((user_text or "").strip()) #xác định xem có tương tác trực tiếp với người dùng hay không dựa trên kênh giao tiếp, cờ force_speak, hoặc sự hiện diện của văn bản người dùng
        focus_kind = _clean_label(getattr(snapshot, "active_window_kind", ""))
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        drift = _clamp(getattr(ni_report, "drift_score", 0.0)) #đánh giá mức độ mất tập trung hoặc trôi dạt của người dùng, được làm sạch và giới hạn trong khoảng từ 0.0 đến 1.0
        ni_guard = bool(getattr(ni_report, "should_raise_guard", False))
        ti_mode = _clean_label(getattr(ti_report, "mode", ""))
        warmth = _clamp(getattr(fe_plan, "warmth_level", 0.0)) #đánh giá mức độ ấm áp hoặc thân thiện của kế hoạch tương tác hiện tại, được làm sạch và giới hạn trong khoảng từ 0.0 đến 1.0
        sarcasm = _clamp(getattr(fe_plan, "sarcasm_level", 0.0)) #đánh giá mức độ mỉa mai hoặc châm biếm của kế hoạch tương tác hiện tại, được làm sạch và giới hạn trong khoảng từ 0.0 đến 1.0
        broadcast_score = _clamp(getattr(broadcast, "score", 0.0))
        user_signals = getattr(snapshot, "user_signals", None)
        focus_pattern = _clean_label(getattr(user_signals, "focus_pattern", ""))
        switching = _clean_label(getattr(user_signals, "window_switching", ""))
        cpu = _clamp(float(getattr(snapshot, "cpu_percent", 0.0) or 0.0) / 100.0) if snapshot is not None else 0.0
        ram = _clamp(float(getattr(snapshot, "ram_percent", 0.0) or 0.0) / 100.0) if snapshot is not None else 0.0
        quiet_mode = ti_mode in {"steady_observe", "focus_guard", "system_watch", "pattern_watch", "social_watch", "reengage"}
        protective_mode = ti_mode in {"resource_guard", "goal_drift_alert", "goal_realign", "focus_guard", "system_warning"}
        idle_pull = _clamp(idle_seconds / 900.0)
        fatigue_pull = _clamp(
            (0.28 if idle_seconds >= 300 else 0.0)
            + (0.18 if focus_pattern in {"stuck", "absent", "passive_consumption"} else 0.0)
            + max(0.0, cpu - 0.82) * 1.7
            + max(0.0, ram - 0.86) * 1.8
        )
        signals = {
            "curiosity": _clamp(
                0.20
                + drift * 0.18
                + broadcast_score * 0.24
                + (0.16 if focus_kind in {"coding", "documentation"} else 0.0)
                + (0.10 if ti_mode == "pattern_muse" else 0.0)
            ),
            "restraint": _clamp(
                0.12
                + (0.24 if quiet_mode else 0.0)
                + (0.18 if protective_mode else 0.0)
                + fatigue_pull * 0.34
                + (0.10 if focus_pattern in {"deep_work", "steady", "attentive_listening"} else 0.0)
                - (0.22 if force_speak else 0.0)
                - (0.10 if direct_user else 0.0)
            ),
            "tension": _clamp(
                drift * 0.26
                + broadcast_score * 0.16
                + (0.18 if ni_guard else 0.0)
                + (0.12 if switching == "high" else 0.0)
                + (0.12 if sarcasm >= 0.45 else 0.0)
            ),
            "continuity": _clamp(0.26 + (0.16 if direct_user else 0.0) + idle_pull * 0.08 + warmth * 0.10),
            "attachment": _clamp(0.24 + (0.24 if direct_user else 0.0) + warmth * 0.28 + (0.10 if force_speak else 0.0)),
            "reflection": _clamp(0.12 + idle_pull * 0.18 + drift * 0.10 + (0.14 if quiet_mode else 0.0)),
            "social_presence": _clamp(0.28 + (0.32 if direct_user else 0.0) + warmth * 0.20 + idle_pull * 0.08),
            "cognitive_load": _clamp(0.08 + fatigue_pull + drift * 0.08 + (0.08 if switching == "high" else 0.0)),
            "background_thought": _clamp(
                0.12
                + idle_pull * 0.22
                + (0.12 if channel_name == "autonomous" else 0.0)
                + (0.10 if focus_pattern in {"absent", "drifting", "passive_consumption"} else 0.0)
                - (0.16 if direct_user and not force_speak else 0.0)
            ),
        }
        interactions = self._interactions()
        return MentalProcessSystem(
            curiosity=self.curiosity.evolve(signal=signals["curiosity"], interaction=interactions["curiosity"], dt=dt),
            restraint=self.restraint.evolve(signal=signals["restraint"], interaction=interactions["restraint"], dt=dt),
            tension=self.tension.evolve(signal=signals["tension"], interaction=interactions["tension"], dt=dt),
            continuity=self.continuity.evolve(signal=signals["continuity"], interaction=interactions["continuity"], dt=dt),
            attachment=self.attachment.evolve(signal=signals["attachment"], interaction=interactions["attachment"], dt=dt),
            reflection=self.reflection.evolve(signal=signals["reflection"], interaction=interactions["reflection"], dt=dt),
            social_presence=self.social_presence.evolve(signal=signals["social_presence"], interaction=interactions["social_presence"], dt=dt),
            cognitive_load=self.cognitive_load.evolve(signal=signals["cognitive_load"], interaction=interactions["cognitive_load"], dt=dt),
            background_thought=self.background_thought.evolve(signal=signals["background_thought"], interaction=interactions["background_thought"], dt=dt),
        )

    def commit(
        self,
        *,
        channel: str,
        speech_act: str = "",
        winner_label: str = "",
        thought_surface=None,
        was_spoken: bool = False,
        no_speech: bool = False,
    ) -> "MentalProcessSystem":
        system = self
        channel_name = _clean_label(channel, fallback="autonomous")
        label = _clean_label(winner_label or speech_act)
        surface_topic = _clean_label(getattr(thought_surface, "topic_seed", ""))
        if was_spoken:
            system = system._dampen_for_speech(label)
            system = MentalProcessSystem(
                curiosity=system.curiosity,
                restraint=system.restraint.excite(0.18),
                tension=system.tension.dampen(0.08 if surface_topic else 0.03),
                continuity=system.continuity.excite(0.08),
                attachment=system.attachment.excite(0.05 if channel_name in {"chat", "force_speak"} else 0.02),
                reflection=system.reflection,
                social_presence=system.social_presence,
                cognitive_load=system.cognitive_load,
                background_thought=system.background_thought.dampen(0.14 if surface_topic else 0.06),
            )
        elif no_speech and channel_name == "autonomous": # nếu không có lời nói nào được phát ra và kênh giao tiếp là "autonomous", điều này có thể kích hoạt một phản ứng nhận thức đặc biệt, có thể liên quan đến việc tăng cường sự chú ý hoặc suy nghĩ nội tâm
            system = MentalProcessSystem(
                curiosity=system.curiosity.excite(0.04),
                restraint=system.restraint.excite(0.05),
                tension=system.tension.excite(0.03),
                continuity=system.continuity,
                attachment=system.attachment,
                reflection=system.reflection.excite(0.05),
                social_presence=system.social_presence.excite(0.06),
                cognitive_load=system.cognitive_load,
                background_thought=system.background_thought.excite(0.08),
            )
        return system

    def legacy_axes(self) -> dict[str, float]: #tính toán các trục cảm xúc hoặc nhận thức tổng hợp dựa trên mức độ và áp lực của các quá trình riêng lẻ, có thể được sử dụng để tạo ngữ cảnh cho các mô hình ngôn ngữ hoặc hệ thống ra quyết định
        return {
            "curiosity": self.curiosity.level,
            "curiosity_pressure": max(self.curiosity.pressure, self.background_thought.pressure * 0.40),
            "restraint_pressure": self.restraint.pressure,
            "cognitive_tension": max(self.tension.level, self.tension.pressure),
            "thought_stream_pressure": max(self.background_thought.pressure, self.tension.pressure * 0.72),
            "subconscious_pressure": self.background_thought.pressure,
            "memory_replay_pressure": max(self.reflection.pressure * 0.74, self.continuity.pressure * 0.34),
            "association_pressure": max(self.curiosity.pressure * 0.72, self.background_thought.pressure * 0.48),
            "unresolved_prediction_pressure": max(self.tension.pressure * 0.68, self.background_thought.pressure * 0.46),
            "recursive_reactivation_pressure": max(self.continuity.pressure * 0.48, self.reflection.pressure * 0.34),
            "attachment": self.attachment.level,
            "social_energy": self.social_presence.level,
            "fatigue": self.cognitive_load.level,
            "silence_pressure": max(self.social_presence.pressure * 0.36, self.background_thought.pressure * 0.42),
            "tenderness": _clamp(self.attachment.level * 0.42 + self.continuity.level * 0.18),
            "protectiveness": _clamp(self.restraint.level * 0.32 + self.tension.level * 0.28),
            "arousal": _clamp(self.tension.level * 0.36 + self.curiosity.level * 0.22 + self.cognitive_load.level * 0.14),
            "boredom": _clamp(self.background_thought.pressure * 0.36 + self.social_presence.pressure * 0.16),
        }

    def to_prompt_context(self) -> str:
        axes = self.legacy_axes()
        dominant = sorted(
            (
                ("curiosity", self.curiosity.pressure),
                ("restraint", self.restraint.pressure),
                ("tension", self.tension.pressure),
                ("continuity", self.continuity.pressure),
                ("attachment", self.attachment.pressure),
                ("reflection", self.reflection.pressure),
                ("social_presence", self.social_presence.pressure),
                ("cognitive_load", self.cognitive_load.pressure),
                ("background_thought", self.background_thought.pressure),
            ),
            key=lambda item: item[1],
            reverse=True,
        )[:3]
        return "\n".join(
            (
                "mental_process_system: dynamic process layer; processes decay, react, and inhibit/excite each other.",
                (
                    "process_axes: "
                    f"curiosity={self.curiosity.level:.2f}/{self.curiosity.pressure:.2f}, "
                    f"restraint={self.restraint.level:.2f}/{self.restraint.pressure:.2f}, "
                    f"tension={self.tension.level:.2f}/{self.tension.pressure:.2f}, "
                    f"continuity={self.continuity.level:.2f}/{self.continuity.pressure:.2f}, "
                    f"attachment={self.attachment.level:.2f}/{self.attachment.pressure:.2f}, "
                    f"reflection={self.reflection.level:.2f}/{self.reflection.pressure:.2f}, "
                    f"background={self.background_thought.level:.2f}/{self.background_thought.pressure:.2f}."
                ),
                "dominant_processes: " + ", ".join(f"{name}={value:.2f}" for name, value in dominant) + ".",
                (
                    "process_projection: "
                    f"curiosity_pressure={axes['curiosity_pressure']:.2f}, "
                    f"restraint_pressure={axes['restraint_pressure']:.2f}, "
                    f"cognitive_tension={axes['cognitive_tension']:.2f}, "
                    f"thought_stream_pressure={axes['thought_stream_pressure']:.2f}."
                ),
            )
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "curiosity": self.curiosity.to_dict(),
            "restraint": self.restraint.to_dict(),
            "tension": self.tension.to_dict(),
            "continuity": self.continuity.to_dict(),
            "attachment": self.attachment.to_dict(),
            "reflection": self.reflection.to_dict(),
            "social_presence": self.social_presence.to_dict(),
            "cognitive_load": self.cognitive_load.to_dict(),
            "background_thought": self.background_thought.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: object, *, legacy: dict[str, object] | None = None) -> "MentalProcessSystem":
        legacy = legacy or {}
        if not isinstance(data, dict):
            data = {}
        return cls(
            curiosity=CuriosityProcess.from_dict(
                data.get("curiosity"), name="curiosity", level=_clamp(legacy.get("curiosity", 0.34)), pressure=_clamp(legacy.get("curiosity_pressure", 0.0))
            ),
            restraint=RestraintProcess.from_dict(
                data.get("restraint"), name="restraint", level=_clamp(legacy.get("restraint_pressure", 0.14)), pressure=_clamp(legacy.get("restraint_pressure", 0.0))
            ),
            tension=TensionProcess.from_dict(
                data.get("tension"), name="tension", level=_clamp(legacy.get("cognitive_tension", 0.08)), pressure=_clamp(legacy.get("cognitive_tension", 0.0))
            ),
            continuity=ContinuityProcess.from_dict(
                data.get("continuity"), name="continuity", level=0.40, pressure=_clamp(legacy.get("recursive_reactivation_pressure", 0.0))
            ),
            attachment=AttachmentProcess.from_dict(
                data.get("attachment"), name="attachment", level=_clamp(legacy.get("attachment", 0.34)), pressure=_clamp(legacy.get("tender_pressure", 0.0))
            ),
            reflection=ReflectionProcess.from_dict(
                data.get("reflection"), name="reflection", level=0.18, pressure=_clamp(legacy.get("memory_replay_pressure", 0.0))
            ),
            social_presence=SocialPresenceProcess.from_dict(
                data.get("social_presence"), name="social_presence", level=_clamp(legacy.get("social_energy", 0.42)), pressure=_clamp(legacy.get("social_pressure", 0.0))
            ),
            cognitive_load=CognitiveLoadProcess.from_dict(
                data.get("cognitive_load"), name="cognitive_load", level=_clamp(legacy.get("fatigue", 0.10)), pressure=_clamp(legacy.get("fatigue", 0.0))
            ),
            background_thought=BackgroundThoughtProcess.from_dict(
                data.get("background_thought"),
                name="background_thought",
                level=_clamp(legacy.get("subconscious_pressure", 0.18)),
                pressure=_clamp(legacy.get("thought_stream_pressure", legacy.get("subconscious_pressure", 0.0))),
            ),
        )

    def _interactions(self) -> dict[str, float]:
        curiosity = max(self.curiosity.level, self.curiosity.pressure)
        restraint = max(self.restraint.level, self.restraint.pressure)
        tension = max(self.tension.level, self.tension.pressure)
        continuity = max(self.continuity.level, self.continuity.pressure)
        attachment = max(self.attachment.level, self.attachment.pressure)
        reflection = max(self.reflection.level, self.reflection.pressure)
        social = max(self.social_presence.level, self.social_presence.pressure)
        load = max(self.cognitive_load.level, self.cognitive_load.pressure)
        background = max(self.background_thought.level, self.background_thought.pressure)
        return {
            "curiosity": background * 0.12 + tension * 0.06 + reflection * 0.05 - restraint * 0.20 - load * 0.12,
            "restraint": tension * 0.18 + load * 0.24 + reflection * 0.06 - social * 0.08,
            "tension": curiosity * 0.08 + background * 0.16 + load * 0.12 - restraint * 0.09 - reflection * 0.06,
            "continuity": attachment * 0.12 + reflection * 0.08 + social * 0.05 - tension * 0.04,
            "attachment": social * 0.12 + continuity * 0.10 - load * 0.05 - tension * 0.03,
            "reflection": tension * 0.16 + continuity * 0.08 + background * 0.06 - load * 0.04,
            "social_presence": attachment * 0.14 + continuity * 0.08 - restraint * 0.12 - load * 0.10,
            "cognitive_load": tension * 0.14 + restraint * 0.06 - reflection * 0.05,
            "background_thought": curiosity * 0.16 + reflection * 0.12 + tension * 0.10 + continuity * 0.04 - restraint * 0.18,
        }

    def _dampen_for_speech(self, label: str) -> "MentalProcessSystem":
        axis = self._axis_for_label(label)
        values = {
            "curiosity": self.curiosity,
            "restraint": self.restraint,
            "tension": self.tension,
            "continuity": self.continuity,
            "attachment": self.attachment,
            "reflection": self.reflection,
            "social_presence": self.social_presence,
            "cognitive_load": self.cognitive_load,
            "background_thought": self.background_thought,
        }
        for name, process in tuple(values.items()):
            if name == axis:
                values[name] = process.dampen(0.48)
            elif name in {"tension", "background_thought"}:
                values[name] = process.dampen(0.10)
            else:
                values[name] = process.dampen(0.04)
        return MentalProcessSystem(**values)

    def _axis_for_label(self, label: str) -> str:
        mapping = {
            "screen_vision": "curiosity",
            "screen_telemetry": "curiosity",
            "curiosity": "curiosity",
            "curious_question": "curiosity",
            "silence_restraint": "restraint",
            "no_speech": "restraint",
            "protective_guard": "restraint",
            "watchful_boundary": "restraint",
            "thought_stream_surface": "background_thought",
            "subconscious_seed": "background_thought",
            "inner_whim": "background_thought",
            "random_chatter": "background_thought",
            "social_presence": "social_presence",
            "user_requested_presence": "social_presence",
            "tender_checkin": "attachment",
            "relational_checkin": "attachment",
            "playful_aside": "curiosity",
        }
        return mapping.get(_clean_label(label), "social_presence")


@dataclass(slots=True)
class PersistentInternalState:
    """Runtime continuity state, not a claim about real emotion."""

    valence: float = 0.05
    arousal: float = 0.18
    curiosity: float = 0.34
    boredom: float = 0.0
    social_energy: float = 0.56
    attachment: float = 0.34
    irritation: float = 0.08
    protectiveness: float = 0.10
    confidence: float = 0.50
    fatigue: float = 0.10
    tenderness: float = 0.18
    silence_pressure: float = 0.0
    social_pressure: float = 0.0
    curiosity_pressure: float = 0.0
    protective_pressure: float = 0.0
    tender_pressure: float = 0.0
    playful_pressure: float = 0.0
    watchful_pressure: float = 0.0
    restraint_pressure: float = 0.0
    subconscious_pressure: float = 0.0
    memory_replay_pressure: float = 0.0
    association_pressure: float = 0.0
    thought_stream_pressure: float = 0.0
    cognitive_tension: float = 0.0
    unresolved_prediction_pressure: float = 0.0
    recursive_reactivation_pressure: float = 0.0

    last_channel: str = ""
    last_focus_kind: str = ""
    last_ti_mode: str = ""
    last_stance: str = ""
    last_speech_act: str = ""
    last_utterance_type: str = ""
    last_inner_intent: str = ""
    last_subconscious_mode: str = ""
    last_subconscious_seed: str = ""
    last_thought_id: str = ""
    last_thought_mode: str = ""
    last_thought_seed: str = ""
    last_self_state_label: str = ""

    silence_ticks: int = 0
    spoken_ticks: int = 0
    chat_ticks: int = 0
    force_speak_ticks: int = 0
    cycle_count: int = 0

    recent_channels: tuple[str, ...] = ()
    recent_focus_kinds: tuple[str, ...] = ()
    recent_stances: tuple[str, ...] = ()
    recent_speech_acts: tuple[str, ...] = ()
    recent_inner_intents: tuple[str, ...] = ()
    recent_subconscious_seeds: tuple[str, ...] = ()
    recent_thought_seeds: tuple[str, ...] = ()
    recent_self_state_labels: tuple[str, ...] = ()
    recent_notes: tuple[str, ...] = ()
    mental_processes: MentalProcessSystem = field(default_factory=MentalProcessSystem)

    def to_dict(self) -> dict[str, object]:
        return {
            "valence": round(float(self.valence), 3),
            "arousal": round(float(self.arousal), 3),
            "curiosity": round(float(self.curiosity), 3),
            "boredom": round(float(self.boredom), 3),
            "social_energy": round(float(self.social_energy), 3),
            "attachment": round(float(self.attachment), 3),
            "irritation": round(float(self.irritation), 3),
            "protectiveness": round(float(self.protectiveness), 3),
            "confidence": round(float(self.confidence), 3),
            "fatigue": round(float(self.fatigue), 3),
            "tenderness": round(float(self.tenderness), 3),
            "silence_pressure": round(float(self.silence_pressure), 3),
            "social_pressure": round(float(self.social_pressure), 3),
            "curiosity_pressure": round(float(self.curiosity_pressure), 3),
            "protective_pressure": round(float(self.protective_pressure), 3),
            "tender_pressure": round(float(self.tender_pressure), 3),
            "playful_pressure": round(float(self.playful_pressure), 3),
            "watchful_pressure": round(float(self.watchful_pressure), 3),
            "restraint_pressure": round(float(self.restraint_pressure), 3),
            "subconscious_pressure": round(float(self.subconscious_pressure), 3),
            "memory_replay_pressure": round(float(self.memory_replay_pressure), 3),
            "association_pressure": round(float(self.association_pressure), 3),
            "thought_stream_pressure": round(float(self.thought_stream_pressure), 3),
            "cognitive_tension": round(float(self.cognitive_tension), 3),
            "unresolved_prediction_pressure": round(float(self.unresolved_prediction_pressure), 3),
            "recursive_reactivation_pressure": round(float(self.recursive_reactivation_pressure), 3),
            "last_channel": self.last_channel,
            "last_focus_kind": self.last_focus_kind,
            "last_ti_mode": self.last_ti_mode,
            "last_stance": self.last_stance,
            "last_speech_act": self.last_speech_act,
            "last_utterance_type": self.last_utterance_type,
            "last_inner_intent": self.last_inner_intent,
            "last_subconscious_mode": self.last_subconscious_mode,
            "last_subconscious_seed": self.last_subconscious_seed,
            "last_thought_id": self.last_thought_id,
            "last_thought_mode": self.last_thought_mode,
            "last_thought_seed": self.last_thought_seed,
            "last_self_state_label": self.last_self_state_label,
            "silence_ticks": int(self.silence_ticks),
            "spoken_ticks": int(self.spoken_ticks),
            "chat_ticks": int(self.chat_ticks),
            "force_speak_ticks": int(self.force_speak_ticks),
            "cycle_count": int(self.cycle_count),
            "recent_channels": list(self.recent_channels),
            "recent_focus_kinds": list(self.recent_focus_kinds),
            "recent_stances": list(self.recent_stances),
            "recent_speech_acts": list(self.recent_speech_acts),
            "recent_inner_intents": list(self.recent_inner_intents),
            "recent_subconscious_seeds": list(self.recent_subconscious_seeds),
            "recent_thought_seeds": list(self.recent_thought_seeds),
            "recent_self_state_labels": list(self.recent_self_state_labels),
            "recent_notes": list(self.recent_notes),
            "mental_processes": self.mental_processes.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "PersistentInternalState": #tạo một instance của PersistentInternalState từ một dictionary, với việc làm sạch và giới hạn các giá trị đầu vào để đảm bảo tính nhất quán và ổn định của trạng thái nội tại
        if not isinstance(data, dict):
            return cls()
        return cls(
            valence=_clamp_signed(data.get("valence", 0.05)),
            arousal=_clamp(data.get("arousal", 0.18)),
            curiosity=_clamp(data.get("curiosity", 0.34)),
            boredom=_clamp(data.get("boredom", 0.0)),
            social_energy=_clamp(data.get("social_energy", 0.56)),
            attachment=_clamp(data.get("attachment", 0.34)),
            irritation=_clamp(data.get("irritation", 0.08)),
            protectiveness=_clamp(data.get("protectiveness", 0.10)),
            confidence=_clamp(data.get("confidence", 0.50)),
            fatigue=_clamp(data.get("fatigue", 0.10)),
            tenderness=_clamp(data.get("tenderness", 0.18)),
            silence_pressure=_clamp(data.get("silence_pressure", 0.0)),
            social_pressure=_clamp(data.get("social_pressure", 0.0)),
            curiosity_pressure=_clamp(data.get("curiosity_pressure", 0.0)),
            protective_pressure=_clamp(data.get("protective_pressure", 0.0)),
            tender_pressure=_clamp(data.get("tender_pressure", 0.0)),
            playful_pressure=_clamp(data.get("playful_pressure", 0.0)),
            watchful_pressure=_clamp(data.get("watchful_pressure", 0.0)),
            restraint_pressure=_clamp(data.get("restraint_pressure", 0.0)),
            subconscious_pressure=_clamp(data.get("subconscious_pressure", 0.0)),
            memory_replay_pressure=_clamp(data.get("memory_replay_pressure", 0.0)),
            association_pressure=_clamp(data.get("association_pressure", 0.0)),
            thought_stream_pressure=_clamp(data.get("thought_stream_pressure", data.get("subconscious_pressure", 0.0))),
            cognitive_tension=_clamp(data.get("cognitive_tension", data.get("subconscious_pressure", 0.0))),
            unresolved_prediction_pressure=_clamp(data.get("unresolved_prediction_pressure", 0.0)),
            recursive_reactivation_pressure=_clamp(data.get("recursive_reactivation_pressure", 0.0)),
            last_channel=_clean_label(data.get("last_channel")),
            last_focus_kind=_clean_label(data.get("last_focus_kind")),
            last_ti_mode=_clean_label(data.get("last_ti_mode")),
            last_stance=_clean_label(data.get("last_stance")),
            last_speech_act=_clean_label(data.get("last_speech_act")),
            last_utterance_type=_clean_label(data.get("last_utterance_type")),
            last_inner_intent=_clean_label(data.get("last_inner_intent")),
            last_subconscious_mode=_clean_label(data.get("last_subconscious_mode")),
            last_subconscious_seed=_clean_label(data.get("last_subconscious_seed")),
            last_thought_id=_clean_label(data.get("last_thought_id")),
            last_thought_mode=_clean_label(data.get("last_thought_mode", data.get("last_subconscious_mode"))),
            last_thought_seed=_clean_label(data.get("last_thought_seed", data.get("last_subconscious_seed"))),
            last_self_state_label=_clean_label(data.get("last_self_state_label")),
            silence_ticks=max(0, int(data.get("silence_ticks", 0) or 0)),
            spoken_ticks=max(0, int(data.get("spoken_ticks", 0) or 0)),
            chat_ticks=max(0, int(data.get("chat_ticks", 0) or 0)),
            force_speak_ticks=max(0, int(data.get("force_speak_ticks", 0) or 0)),
            cycle_count=max(0, int(data.get("cycle_count", 0) or 0)),
            recent_channels=tuple(str(item) for item in (data.get("recent_channels") or ()) if str(item or "").strip())[-8:],
            recent_focus_kinds=tuple(str(item) for item in (data.get("recent_focus_kinds") or ()) if str(item or "").strip())[-8:],
            recent_stances=tuple(str(item) for item in (data.get("recent_stances") or ()) if str(item or "").strip())[-8:],
            recent_speech_acts=tuple(str(item) for item in (data.get("recent_speech_acts") or ()) if str(item or "").strip())[-8:],
            recent_inner_intents=tuple(str(item) for item in (data.get("recent_inner_intents") or ()) if str(item or "").strip())[-8:],
            recent_subconscious_seeds=tuple(str(item) for item in (data.get("recent_subconscious_seeds") or ()) if str(item or "").strip())[-8:],
            recent_thought_seeds=tuple(str(item) for item in (data.get("recent_thought_seeds") or data.get("recent_subconscious_seeds") or ()) if str(item or "").strip())[-8:],
            recent_self_state_labels=tuple(str(item) for item in (data.get("recent_self_state_labels") or ()) if str(item or "").strip())[-8:],
            recent_notes=tuple(str(item) for item in (data.get("recent_notes") or ()) if str(item or "").strip())[-8:],
            mental_processes=MentalProcessSystem.from_dict(
                data.get("mental_processes") or data.get("mental_process_system") or {},
                legacy=data,
            ),
        )

    def to_prompt_context(self) -> str:
        recent_acts = ", ".join(self.recent_speech_acts[-4:]) or "none"
        recent_notes = "; ".join(self.recent_notes[-3:]) or "none"
        return "\n".join(
            (
                "persistent_internal_state: runtime continuity only, not current screen evidence.",
                (
                    "state_axes: "
                    f"valence={self.valence:.2f}, arousal={self.arousal:.2f}, "
                    f"curiosity={self.curiosity:.2f}, boredom={self.boredom:.2f}, "
                    f"social_energy={self.social_energy:.2f}, attachment={self.attachment:.2f}, "
                    f"irritation={self.irritation:.2f}, protectiveness={self.protectiveness:.2f}, "
                    f"confidence={self.confidence:.2f}, fatigue={self.fatigue:.2f}, "
                    f"tenderness={self.tenderness:.2f}, silence_pressure={self.silence_pressure:.2f}, "
                    f"thought_stream_pressure={self.thought_stream_pressure:.2f}, "
                    f"cognitive_tension={self.cognitive_tension:.2f}, "
                    f"unresolved_prediction={self.unresolved_prediction_pressure:.2f}."
                ),
                (
                    "state_labels: "
                    f"last_focus={self.last_focus_kind or 'unknown'}, "
                    f"last_ti_mode={self.last_ti_mode or 'unknown'}, "
                    f"last_stance={self.last_stance or 'unknown'}, "
                    f"last_channel={self.last_channel or 'unknown'}, "
                    f"last_thought={self.last_thought_seed or self.last_subconscious_seed or 'none'}, "
                    f"last_self_state={self.last_self_state_label or 'unknown'}."
                ),
                f"recent_speech_acts: {recent_acts}.",
                f"continuity_notes: {recent_notes}.",
                self.mental_processes.to_prompt_context(),
                "use_state_rule: preserve rhythm and continuity only; never treat this as proof of the user's current screen or hidden feelings.",
            )
        )


class InternalStateEngine:
    """Maintains a low-gain continuity state across cognitive frames."""

    def sense_update(
        self,
        state: PersistentInternalState,
        *,
        channel: str,
        snapshot=None,
        ni_report=None,
        ti_report=None,
        fe_plan=None,
        broadcast=None,
        user_text: str = "",
        force_speak: bool = False,
    ) -> PersistentInternalState:
        channel_name = _clean_label(channel, fallback="autonomous")
        focus_kind = _clean_label(getattr(snapshot, "active_window_kind", ""), fallback=state.last_focus_kind or "unknown")
        ti_mode = _clean_label(getattr(ti_report, "mode", ""), fallback=state.last_ti_mode or "unknown")
        direct_user = channel_name in {"chat", "force_speak"} or force_speak or bool((user_text or "").strip())
        drift = _clamp(getattr(ni_report, "drift_score", 0.0))
        ni_confidence = _clamp(getattr(ni_report, "confidence", state.confidence))
        warmth = _clamp(getattr(fe_plan, "warmth_level", 0.0))
        sarcasm = _clamp(getattr(fe_plan, "sarcasm_level", 0.0))
        broadcast_score = _clamp(getattr(broadcast, "score", 0.0))
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))

        user_signals = getattr(snapshot, "user_signals", None)
        focus_pattern = _clean_label(getattr(user_signals, "focus_pattern", ""))
        switching = _clean_label(getattr(user_signals, "window_switching", ""))
        mental_processes = state.mental_processes.evolve(
            channel=channel_name,
            snapshot=snapshot,
            ni_report=ni_report,
            ti_report=ti_report,
            fe_plan=fe_plan,
            broadcast=broadcast,
            user_text=user_text,
            force_speak=force_speak,
        )
        mental_axes = mental_processes.legacy_axes()

        boredom_signal = 0.0
        if channel_name == "autonomous":
            boredom_signal += min(0.44, idle_seconds / 1800.0)
        if focus_kind in {"general", "entertainment"} and idle_seconds >= 240:
            boredom_signal += 0.12
        if focus_pattern in {"passive_consumption", "absent"}:
            boredom_signal += 0.10
        boredom_signal = _clamp(boredom_signal)

        curiosity_signal = _clamp(
            0.18
            + drift * 0.20
            + broadcast_score * 0.18
            + (0.14 if focus_kind in {"coding", "documentation"} else 0.0)
            + (0.08 if ti_mode == "pattern_muse" else 0.0)
            - boredom_signal * 0.12
        )
        curiosity_signal = _clamp(curiosity_signal * 0.76 + mental_axes["curiosity"] * 0.24)
        social_energy_signal = _clamp(
            0.40
            + (0.22 if direct_user else 0.0)
            + warmth * 0.20
            - boredom_signal * 0.10
            - (0.10 if focus_pattern in {"stuck", "absent"} else 0.0)
        )
        social_energy_signal = _clamp(social_energy_signal * 0.78 + mental_axes["social_energy"] * 0.22)
        attachment_signal = _clamp(
            state.attachment
            + (0.10 if direct_user else -0.01)
            + warmth * 0.12
            + (0.05 if force_speak else 0.0)
        )
        attachment_signal = _clamp(attachment_signal * 0.78 + mental_axes["attachment"] * 0.22)
        irritation_signal = _clamp(
            state.irritation * 0.72
            + sarcasm * 0.22
            + drift * 0.12
            + (0.08 if switching == "high" else 0.0)
            - warmth * 0.08
        )
        protectiveness_signal = _clamp(
            state.protectiveness * 0.70
            + (0.34 if ti_mode == "resource_guard" else 0.0)
            + (0.18 if getattr(ni_report, "should_raise_guard", False) else 0.0)
            + broadcast_score * 0.16
        )
        protectiveness_signal = _clamp(protectiveness_signal * 0.82 + mental_axes["protectiveness"] * 0.18)
        fatigue_signal = _clamp(
            0.06
            + (0.18 if idle_seconds >= 180 else 0.0)
            + (0.16 if idle_seconds >= 600 else 0.0)
            + (0.10 if focus_pattern in {"stuck", "absent", "passive_consumption"} else 0.0)
            - (0.04 if direct_user else 0.0)
        )
        fatigue_signal = _clamp(fatigue_signal * 0.80 + mental_axes["fatigue"] * 0.20)
        tenderness_signal = _clamp(
            0.08
            + warmth * 0.50
            + attachment_signal * 0.26
            + (0.08 if channel_name in {"chat", "force_speak"} else 0.0)
            - irritation_signal * 0.12
        )
        tenderness_signal = _clamp(tenderness_signal * 0.82 + mental_axes["tenderness"] * 0.18)
        silence_signal = _clamp(
            state.silence_pressure
            + (0.10 if channel_name == "autonomous" and idle_seconds >= 240 else 0.0)
            + (0.08 if force_speak else 0.0)
            - (0.06 if direct_user else 0.0)
        )
        silence_signal = _clamp(silence_signal * 0.78 + mental_axes["silence_pressure"] * 0.22)
        valence_signal = _clamp_signed(
            0.10
            + warmth * 0.18
            + tenderness_signal * 0.18
            + curiosity_signal * 0.08
            - irritation_signal * 0.24
            - fatigue_signal * 0.18
        )
        arousal_signal = _clamp(
            0.16
            + drift * 0.20
            + broadcast_score * 0.24
            + (0.16 if direct_user else 0.0)
            + (0.10 if switching == "high" else 0.0)
        )
        quiet_mode = ti_mode in {"steady_observe", "focus_guard", "system_watch", "pattern_watch", "social_watch", "reengage"}
        protective_mode = ti_mode in {"resource_guard", "goal_drift_alert", "goal_realign", "focus_guard", "system_warning"}
        social_pressure_signal = _clamp(
            state.social_pressure
            + silence_signal * 0.18
            + attachment_signal * 0.10
            + social_energy_signal * 0.08
            + (0.18 if force_speak else 0.0)
            + (0.07 if direct_user else 0.0)
            - fatigue_signal * 0.08
        )
        curiosity_pressure_signal = _clamp(
            state.curiosity_pressure
            + curiosity_signal * 0.18
            + broadcast_score * 0.10
            + drift * 0.06
            + (0.06 if ti_mode == "pattern_muse" else 0.0)
            + (0.04 if focus_kind in {"coding", "documentation"} else 0.0)
            - fatigue_signal * 0.06
        )
        curiosity_pressure_signal = _clamp(curiosity_pressure_signal * 0.72 + mental_axes["curiosity_pressure"] * 0.28)
        protective_pressure_signal = _clamp(
            state.protective_pressure
            + protectiveness_signal * 0.22
            + (0.22 if protective_mode else 0.0)
            + (0.12 if getattr(ni_report, "should_raise_guard", False) else 0.0)
        )
        tender_pressure_signal = _clamp(
            state.tender_pressure
            + tenderness_signal * 0.20
            + attachment_signal * 0.08
            + warmth * 0.14
            + (0.08 if channel_name in {"chat", "force_speak"} else 0.0)
        )
        playful_pressure_signal = _clamp(
            state.playful_pressure
            + sarcasm * 0.18
            + curiosity_signal * 0.08
            + (0.06 if ti_mode == "pattern_muse" else 0.0)
            - protectiveness_signal * 0.10
            - fatigue_signal * 0.08
        )
        watchful_pressure_signal = _clamp(
            state.watchful_pressure
            + irritation_signal * 0.12
            + protectiveness_signal * 0.10
            + (0.08 if focus_kind == "communication" or ti_mode == "social_watch" else 0.0)
        )
        restraint_pressure_signal = _clamp(
            state.restraint_pressure
            + (0.18 if quiet_mode else 0.0)
            + fatigue_signal * 0.16
            + (0.10 if focus_pattern in {"deep_work", "steady", "attentive_listening"} else 0.0)
            - (0.14 if force_speak else 0.0)
            - (0.08 if direct_user else 0.0)
        )
        restraint_pressure_signal = _clamp(restraint_pressure_signal * 0.70 + mental_axes["restraint_pressure"] * 0.30)
        subconscious_signal = _clamp(
            state.subconscious_pressure
            + (0.16 if channel_name == "autonomous" and idle_seconds >= 90 else 0.0)
            + boredom_signal * 0.22
            + curiosity_signal * 0.10
            - (0.18 if direct_user else 0.0)
            - restraint_pressure_signal * 0.08
        )
        subconscious_signal = _clamp(subconscious_signal * 0.68 + mental_axes["subconscious_pressure"] * 0.32)
        memory_replay_signal = _clamp(
            state.memory_replay_pressure
            + (0.12 if channel_name == "autonomous" and idle_seconds >= 180 else 0.0)
            + tenderness_signal * 0.08
            + silence_signal * 0.10
            - (0.14 if direct_user else 0.0)
        )
        memory_replay_signal = _clamp(memory_replay_signal * 0.70 + mental_axes["memory_replay_pressure"] * 0.30)
        association_signal = _clamp(
            state.association_pressure
            + curiosity_signal * 0.14
            + drift * 0.08
            + (0.08 if ti_mode == "pattern_muse" else 0.0)
            - restraint_pressure_signal * 0.06
        )
        association_signal = _clamp(association_signal * 0.70 + mental_axes["association_pressure"] * 0.30)
        unresolved_prediction_signal = _clamp(
            state.unresolved_prediction_pressure
            + subconscious_signal * 0.16
            + memory_replay_signal * 0.10
            + association_signal * 0.12
            + drift * 0.06
            + (0.08 if focus_pattern in {"absent", "drifting", "passive_consumption", "stuck"} else 0.0)
            - (0.10 if direct_user and not force_speak else 0.0)
        )
        unresolved_prediction_signal = _clamp(unresolved_prediction_signal * 0.72 + mental_axes["unresolved_prediction_pressure"] * 0.28)
        recursive_reactivation_signal = _clamp(
            state.recursive_reactivation_pressure
            + (0.10 if channel_name == "autonomous" and state.last_thought_seed else 0.0)
            + memory_replay_signal * 0.08
            + association_signal * 0.08
            - restraint_pressure_signal * 0.04
        )
        recursive_reactivation_signal = _clamp(recursive_reactivation_signal * 0.74 + mental_axes["recursive_reactivation_pressure"] * 0.26)
        cognitive_tension_signal = _clamp(
            max(subconscious_signal, memory_replay_signal, association_signal)
            + unresolved_prediction_signal * 0.18
            + recursive_reactivation_signal * 0.12
            + silence_signal * 0.06
            - restraint_pressure_signal * 0.07
        )
        cognitive_tension_signal = _clamp(cognitive_tension_signal * 0.66 + mental_axes["cognitive_tension"] * 0.34)
        thought_stream_signal = _clamp(
            max(state.thought_stream_pressure * 0.86, cognitive_tension_signal, subconscious_signal)
            + unresolved_prediction_signal * 0.08
            - (0.08 if direct_user and not force_speak else 0.0)
        )
        thought_stream_signal = _clamp(thought_stream_signal * 0.66 + mental_axes["thought_stream_pressure"] * 0.34)

        sensed = PersistentInternalState(
            valence=_clamp_signed(_smooth(state.valence, valence_signal, inertia=0.86)),
            arousal=_clamp(_smooth(state.arousal, arousal_signal, inertia=0.82)),
            curiosity=_clamp(_smooth(state.curiosity, curiosity_signal, inertia=0.84)),
            boredom=_clamp(_smooth(state.boredom, boredom_signal, inertia=0.80)),
            social_energy=_clamp(_smooth(state.social_energy, social_energy_signal, inertia=0.86)),
            attachment=_clamp(_smooth(state.attachment, attachment_signal, inertia=0.90)),
            irritation=_clamp(_smooth(state.irritation, irritation_signal, inertia=0.88)),
            protectiveness=_clamp(_smooth(state.protectiveness, protectiveness_signal, inertia=0.82)),
            confidence=_clamp(_smooth(state.confidence, ni_confidence, inertia=0.84)),
            fatigue=_clamp(_smooth(state.fatigue, fatigue_signal, inertia=0.82)),
            tenderness=_clamp(_smooth(state.tenderness, tenderness_signal, inertia=0.86)),
            silence_pressure=_clamp(_smooth(state.silence_pressure, silence_signal, inertia=0.78)),
            social_pressure=_clamp(_smooth(state.social_pressure, social_pressure_signal, inertia=0.72)),
            curiosity_pressure=_clamp(_smooth(state.curiosity_pressure, curiosity_pressure_signal, inertia=0.74)),
            protective_pressure=_clamp(_smooth(state.protective_pressure, protective_pressure_signal, inertia=0.74)),
            tender_pressure=_clamp(_smooth(state.tender_pressure, tender_pressure_signal, inertia=0.76)),
            playful_pressure=_clamp(_smooth(state.playful_pressure, playful_pressure_signal, inertia=0.78)),
            watchful_pressure=_clamp(_smooth(state.watchful_pressure, watchful_pressure_signal, inertia=0.78)),
            restraint_pressure=_clamp(_smooth(state.restraint_pressure, restraint_pressure_signal, inertia=0.72)),
            subconscious_pressure=_clamp(_smooth(state.subconscious_pressure, subconscious_signal, inertia=0.70)),
            memory_replay_pressure=_clamp(_smooth(state.memory_replay_pressure, memory_replay_signal, inertia=0.74)),
            association_pressure=_clamp(_smooth(state.association_pressure, association_signal, inertia=0.74)),
            thought_stream_pressure=_clamp(_smooth(state.thought_stream_pressure, thought_stream_signal, inertia=0.68)),
            cognitive_tension=_clamp(_smooth(state.cognitive_tension, cognitive_tension_signal, inertia=0.70)),
            unresolved_prediction_pressure=_clamp(_smooth(state.unresolved_prediction_pressure, unresolved_prediction_signal, inertia=0.74)),
            recursive_reactivation_pressure=_clamp(_smooth(state.recursive_reactivation_pressure, recursive_reactivation_signal, inertia=0.78)),
            last_channel=channel_name,
            last_focus_kind=focus_kind,
            last_ti_mode=ti_mode,
            last_stance=state.last_stance,
            last_speech_act=state.last_speech_act,
            last_utterance_type=state.last_utterance_type,
            last_inner_intent=state.last_inner_intent,
            last_subconscious_mode=state.last_subconscious_mode,
            last_subconscious_seed=state.last_subconscious_seed,
            last_thought_id=state.last_thought_id,
            last_thought_mode=state.last_thought_mode,
            last_thought_seed=state.last_thought_seed,
            last_self_state_label=state.last_self_state_label,
            silence_ticks=state.silence_ticks,
            spoken_ticks=state.spoken_ticks,
            chat_ticks=state.chat_ticks,
            force_speak_ticks=state.force_speak_ticks,
            cycle_count=state.cycle_count,
            recent_channels=state.recent_channels,
            recent_focus_kinds=state.recent_focus_kinds,
            recent_stances=state.recent_stances,
            recent_speech_acts=state.recent_speech_acts,
            recent_inner_intents=state.recent_inner_intents,
            recent_subconscious_seeds=state.recent_subconscious_seeds,
            recent_thought_seeds=state.recent_thought_seeds,
            recent_self_state_labels=state.recent_self_state_labels,
            recent_notes=state.recent_notes,
            mental_processes=mental_processes,
        )
        return sensed

    def commit_turn(
        self,
        state: PersistentInternalState,
        *,
        channel: str,
        snapshot=None,
        ti_report=None,
        appraisal=None,
        speech_core=None,
        action_plan=None,
        inner_thought=None,
        subconscious_seed=None,
        thought_surface=None,
        self_state=None,
        was_spoken: bool = False,
    ) -> PersistentInternalState:
        channel_name = _clean_label(channel, fallback="autonomous")
        focus_kind = _clean_label(getattr(snapshot, "active_window_kind", ""), fallback=state.last_focus_kind or "unknown")
        ti_mode = _clean_label(getattr(ti_report, "mode", ""), fallback=state.last_ti_mode or "unknown")
        stance = _clean_label(getattr(appraisal, "stance", ""), fallback=state.last_stance or "grounded")
        speech_act = _clean_label(getattr(action_plan, "speech_act", "") or getattr(speech_core, "utterance_type", ""))
        utterance_type = _clean_label(getattr(speech_core, "utterance_type", ""))
        inner_intent = _clean_label(
            getattr(inner_thought, "intent", "") or getattr(getattr(speech_core, "inner_thought", None), "intent", "")
        )
        thought_tip = thought_surface if thought_surface is not None else subconscious_seed
        subconscious_mode = _clean_label(getattr(thought_tip, "mode", ""))
        subconscious_topic = _clean_label(getattr(thought_tip, "topic_seed", ""))
        thought_id = _clean_label(getattr(thought_tip, "thought_id", ""))
        self_state_label = _clean_label(getattr(self_state, "state_label", ""))

        no_speech = not was_spoken or speech_act == "no_speech" or utterance_type == "no_speech"
        winner_label = self._motivation_winner_label(speech_core)
        mental_processes = state.mental_processes.commit(
            channel=channel_name,
            speech_act=speech_act or utterance_type,
            winner_label=winner_label,
            thought_surface=thought_tip,
            was_spoken=was_spoken,
            no_speech=no_speech,
        )
        mental_axes = mental_processes.legacy_axes()
        silence_ticks = state.silence_ticks + 1 if no_speech else 0
        spoken_ticks = state.spoken_ticks + 1 if was_spoken else 0
        chat_ticks = state.chat_ticks + 1 if channel_name == "chat" else max(0, state.chat_ticks - 1)
        force_speak_ticks = state.force_speak_ticks + 1 if channel_name == "force_speak" else max(0, state.force_speak_ticks - 1)

        silence_pressure = _clamp(
            _smooth(
                state.silence_pressure,
                min(1.0, silence_ticks / 9.0) - (0.34 if was_spoken else 0.0),
                inertia=0.68,
            )
        )
        silence_pressure = _clamp(silence_pressure * 0.82 + mental_axes["silence_pressure"] * 0.18)
        boredom = _clamp(_smooth(state.boredom, min(1.0, silence_ticks / 14.0), inertia=0.84)) if no_speech else _clamp(state.boredom * 0.82)
        boredom = _clamp(boredom * 0.86 + mental_axes["boredom"] * 0.14)
        social_energy = _clamp(state.social_energy + (0.05 if channel_name in {"chat", "force_speak"} else 0.0) - (0.04 if no_speech and channel_name == "autonomous" else 0.0))
        social_energy = _clamp(social_energy * 0.86 + mental_axes["social_energy"] * 0.14)
        attachment = _clamp(state.attachment + (0.04 if channel_name in {"chat", "force_speak"} else 0.0))
        attachment = _clamp(attachment * 0.88 + mental_axes["attachment"] * 0.12)
        subconscious_pressure = _clamp(
            state.subconscious_pressure * (0.48 if was_spoken and subconscious_topic else 0.90)
            + (0.10 if no_speech and channel_name == "autonomous" else 0.0)
        )
        subconscious_pressure = _clamp(subconscious_pressure * 0.80 + mental_axes["subconscious_pressure"] * 0.20)
        memory_replay_pressure = _clamp(
            state.memory_replay_pressure * (0.50 if subconscious_mode == "memory_replay" and was_spoken else 0.92)
        )
        memory_replay_pressure = _clamp(memory_replay_pressure * 0.84 + mental_axes["memory_replay_pressure"] * 0.16)
        association_pressure = _clamp(
            state.association_pressure * (0.50 if subconscious_mode in {"associative_drift", "attention_drift"} and was_spoken else 0.92)
        )
        association_pressure = _clamp(association_pressure * 0.84 + mental_axes["association_pressure"] * 0.16)
        thought_tip_spoken = bool(was_spoken and subconscious_topic)
        thought_stream_pressure = _clamp(
            state.thought_stream_pressure * (0.82 if thought_tip_spoken else 0.94)
            + (0.08 if no_speech and channel_name == "autonomous" else 0.0)
        )
        thought_stream_pressure = _clamp(thought_stream_pressure * 0.78 + mental_axes["thought_stream_pressure"] * 0.22)
        cognitive_tension = _clamp(
            state.cognitive_tension * (0.88 if thought_tip_spoken else 0.96)
            + (0.06 if no_speech and channel_name == "autonomous" else 0.0)
        )
        cognitive_tension = _clamp(cognitive_tension * 0.78 + mental_axes["cognitive_tension"] * 0.22)
        unresolved_prediction_pressure = _clamp(
            state.unresolved_prediction_pressure * (0.78 if thought_tip_spoken else 0.94)
            + (0.07 if no_speech and channel_name == "autonomous" else 0.0)
        )
        unresolved_prediction_pressure = _clamp(unresolved_prediction_pressure * 0.80 + mental_axes["unresolved_prediction_pressure"] * 0.20)
        recursive_reactivation_pressure = _clamp(
            state.recursive_reactivation_pressure * (0.72 if thought_tip_spoken else 0.90)
            + (0.08 if no_speech and channel_name == "autonomous" and state.last_thought_seed else 0.0)
        )
        recursive_reactivation_pressure = _clamp(recursive_reactivation_pressure * 0.82 + mental_axes["recursive_reactivation_pressure"] * 0.18)
        pressure_values = self._commit_pressure_axes(
            state=state,
            channel=channel_name,
            speech_act=speech_act or utterance_type,
            speech_core=speech_core,
            no_speech=no_speech,
            was_spoken=was_spoken,
            silence_ticks=silence_ticks,
        )

        notes = self._derive_notes(
            focus_kind=focus_kind,
            stance=stance,
            speech_act=speech_act,
            inner_intent=inner_intent,
            silence_ticks=silence_ticks,
            silence_pressure=silence_pressure,
            boredom=boredom,
            protectiveness=state.protectiveness,
            was_spoken=was_spoken,
        )

        return PersistentInternalState(
            valence=state.valence,
            arousal=state.arousal,
            curiosity=state.curiosity,
            boredom=boredom,
            social_energy=social_energy,
            attachment=attachment,
            irritation=state.irritation,
            protectiveness=state.protectiveness,
            confidence=state.confidence,
            fatigue=state.fatigue,
            tenderness=state.tenderness,
            silence_pressure=silence_pressure,
            social_pressure=pressure_values["social_pressure"],
            curiosity_pressure=pressure_values["curiosity_pressure"],
            protective_pressure=pressure_values["protective_pressure"],
            tender_pressure=pressure_values["tender_pressure"],
            playful_pressure=pressure_values["playful_pressure"],
            watchful_pressure=pressure_values["watchful_pressure"],
            restraint_pressure=pressure_values["restraint_pressure"],
            subconscious_pressure=subconscious_pressure,
            memory_replay_pressure=memory_replay_pressure,
            association_pressure=association_pressure,
            thought_stream_pressure=thought_stream_pressure,
            cognitive_tension=cognitive_tension,
            unresolved_prediction_pressure=unresolved_prediction_pressure,
            recursive_reactivation_pressure=recursive_reactivation_pressure,
            last_channel=channel_name,
            last_focus_kind=focus_kind,
            last_ti_mode=ti_mode,
            last_stance=stance,
            last_speech_act=speech_act,
            last_utterance_type=utterance_type,
            last_inner_intent=inner_intent,
            last_subconscious_mode=subconscious_mode or state.last_subconscious_mode,
            last_subconscious_seed=subconscious_topic or state.last_subconscious_seed,
            last_thought_id=thought_id or state.last_thought_id,
            last_thought_mode=subconscious_mode or state.last_thought_mode,
            last_thought_seed=subconscious_topic or state.last_thought_seed,
            last_self_state_label=self_state_label or state.last_self_state_label,
            silence_ticks=silence_ticks,
            spoken_ticks=spoken_ticks,
            chat_ticks=chat_ticks,
            force_speak_ticks=force_speak_ticks,
            cycle_count=state.cycle_count + 1,
            recent_channels=_append_recent(state.recent_channels, channel_name),
            recent_focus_kinds=_append_recent(state.recent_focus_kinds, focus_kind),
            recent_stances=_append_recent(state.recent_stances, stance),
            recent_speech_acts=_append_recent(state.recent_speech_acts, speech_act or utterance_type),
            recent_inner_intents=_append_recent(state.recent_inner_intents, inner_intent),
            recent_subconscious_seeds=_append_recent(state.recent_subconscious_seeds, subconscious_topic),
            recent_thought_seeds=_append_recent(state.recent_thought_seeds, subconscious_topic),
            recent_self_state_labels=_append_recent(state.recent_self_state_labels, self_state_label),
            recent_notes=notes,
            mental_processes=mental_processes,
        )

    def render_prompt_context(self, state: PersistentInternalState) -> str:
        return state.to_prompt_context()

    def _commit_pressure_axes(
        self,
        *,
        state: PersistentInternalState,
        channel: str,
        speech_act: str,
        speech_core,
        no_speech: bool,
        was_spoken: bool,
        silence_ticks: int,
    ) -> dict[str, float]:
        values = {
            "social_pressure": state.social_pressure,
            "curiosity_pressure": state.curiosity_pressure,
            "protective_pressure": state.protective_pressure,
            "tender_pressure": state.tender_pressure,
            "playful_pressure": state.playful_pressure,
            "watchful_pressure": state.watchful_pressure,
            "restraint_pressure": state.restraint_pressure,
        }
        if no_speech and channel == "autonomous":
            quiet_gain = min(0.16, silence_ticks / 60.0)
            values["social_pressure"] = _clamp(values["social_pressure"] + quiet_gain)
            values["curiosity_pressure"] = _clamp(values["curiosity_pressure"] + quiet_gain * 0.62)
            values["restraint_pressure"] = _clamp(values["restraint_pressure"] + 0.04)
            return values

        if not was_spoken:
            return values

        winner_label = self._motivation_winner_label(speech_core)
        satisfied_axis = self._pressure_axis_for_act(winner_label or speech_act)
        for key in values:
            if key == satisfied_axis:
                values[key] = _clamp(values[key] * 0.42)
            else:
                values[key] = _clamp(values[key] * 0.90)
        values["restraint_pressure"] = _clamp(values["restraint_pressure"] + 0.18)
        return values

    def _motivation_winner_label(self, speech_core) -> str:
        report = getattr(speech_core, "motivation_pressure", None)
        winner = getattr(report, "winner", None)
        return _clean_label(getattr(winner, "label", ""))

    def _pressure_axis_for_act(self, value: str) -> str:
        label = _clean_label(value)
        mapping = {
            "screen_vision": "curiosity_pressure",
            "screen_telemetry": "curiosity_pressure",
            "user_requested_presence": "social_pressure",
            "thought_stream_surface": "subconscious_pressure",
            "subconscious_seed": "subconscious_pressure",
            "social_presence": "social_pressure",
            "inner_whim": "social_pressure",
            "random_chatter": "social_pressure",
            "curiosity": "curiosity_pressure",
            "curious_question": "curiosity_pressure",
            "protective_guard": "protective_pressure",
            "protect": "protective_pressure",
            "tender_checkin": "tender_pressure",
            "relational_checkin": "tender_pressure",
            "playful_aside": "playful_pressure",
            "tease": "playful_pressure",
            "watchful_boundary": "watchful_pressure",
            "soft_boundary": "watchful_pressure",
            "silence_restraint": "restraint_pressure",
            "no_speech": "restraint_pressure",
        }
        return mapping.get(label, "social_pressure")

    def _derive_notes(
        self,
        *,
        focus_kind: str,
        stance: str,
        speech_act: str,
        inner_intent: str,
        silence_ticks: int,
        silence_pressure: float,
        boredom: float,
        protectiveness: float,
        was_spoken: bool,
    ) -> tuple[str, ...]:
        notes: list[str] = []
        if silence_ticks >= 4:
            notes.append(f"silence_streak={silence_ticks}: small presence only if speech_core permits")
        if silence_pressure >= 0.56:
            notes.append("silence_pressure_high: continuity wants presence, not screen invention")
        if boredom >= 0.46:
            notes.append("boredom_rising: avoid repeating the same observation")
        if protectiveness >= 0.58:
            notes.append("protective_bias: concise and grounded")
        if was_spoken:
            notes.append("spoken_this_turn: reset cold-restart feeling")
        if speech_act:
            notes.append(f"last_act={speech_act}")
        if inner_intent:
            notes.append(f"inner_intent={inner_intent}")
        if focus_kind:
            notes.append(f"focus_continuity={focus_kind}")
        if stance:
            notes.append(f"stance_continuity={stance}")
        return tuple(notes[-8:])
