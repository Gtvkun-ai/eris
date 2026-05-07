from .contracts import InnerThought


class InnerThoughtEngine:
    """Builds a social motive; it never writes the final spoken line."""

    FORCE_SPEAK_CANDIDATES = (
        ("inner_whim", "user_requested_presence", "present_whim"),
        ("curious_question", "small_curiosity", "small_curiosity"),
        ("random_chatter", "light_presence", "light_presence"),
    )

    AUTONOMOUS_CANDIDATES = (
        ("inner_whim", "long_quiet_presence", "quiet_whim"),
        ("curious_question", "small_curiosity", "small_curiosity"),
        ("random_chatter", "quiet_presence", "quiet_presence"),
    )

    def evaluate(
        self,
        *,
        channel: str,
        snapshot=None,
        internal_state=None,
        appraisal=None,
        broadcast=None,
        style_memory=None,
        concrete_signals: tuple[str, ...] = (),
        last_text: str = "",
        repeat_count: int = 1,
        repeated_topic_tag: str = "",
        repeated_topic_streak: int = 0,
        recent_inner_intents: tuple[str, ...] = (),
        recent_inner_seeds: tuple[str, ...] = (),
    ) -> InnerThought:
        if concrete_signals:
            return InnerThought(
                motive="screen_signal_available",
                evidence_anchor=", ".join(concrete_signals[:2]),
                risk_flags=("prefer_observation",),
            )

        if channel == "force_speak":
            return self._force_speak_thought(
                broadcast=broadcast,
                internal_state=internal_state,
                style_memory=style_memory,
                recent_inner_intents=recent_inner_intents,
                recent_inner_seeds=recent_inner_seeds,
            )

        if channel == "autonomous":
            return self._autonomous_thought(
                snapshot=snapshot,
                internal_state=internal_state,
                appraisal=appraisal,
                broadcast=broadcast,
                style_memory=style_memory,
                repeat_count=repeat_count,
                repeated_topic_tag=repeated_topic_tag,
                repeated_topic_streak=repeated_topic_streak,
                recent_inner_intents=recent_inner_intents,
                recent_inner_seeds=recent_inner_seeds,
            )

        return InnerThought()

    def _force_speak_thought(
        self,
        *,
        broadcast,
        internal_state,
        style_memory,
        recent_inner_intents: tuple[str, ...],
        recent_inner_seeds: tuple[str, ...],
    ) -> InnerThought:
        candidates = self.FORCE_SPEAK_CANDIDATES
        attachment = self._float(getattr(internal_state, "attachment", 0.0) if internal_state is not None else 0.0)
        fatigue = self._float(getattr(internal_state, "fatigue", 0.0) if internal_state is not None else 0.0)
        if fatigue >= 0.44:
            candidates = (
                ("random_chatter", "light_presence", "light_presence"),
                ("inner_whim", "user_requested_presence", "present_whim"),
                ("curious_question", "small_curiosity", "small_curiosity"),
            )
        elif attachment >= 0.52:
            candidates = (
                ("inner_whim", "user_requested_presence", "present_whim"),
                ("curious_question", "small_curiosity", "small_curiosity"),
                ("random_chatter", "light_presence", "light_presence"),
            )
        intent, motive, seed = self._choose_candidate(
            candidates,
            style_memory=style_memory,
            recent_inner_intents=recent_inner_intents,
            recent_inner_seeds=recent_inner_seeds,
        )
        anchor = self._broadcast_anchor(broadcast) or "force_speak requested"
        return InnerThought(
            intent=intent,
            motive=motive,
            topic_seed=seed,
            evidence_anchor=anchor,
            certainty=0.66,
            should_surface=True,
            risk_flags=("no_screen_claim", "social_initiative", "needs_generation"),
            cooldown_seconds=0,
        )

    def _autonomous_thought(
        self,
        *,
        snapshot,
        internal_state,
        appraisal,
        broadcast,
        style_memory,
        repeat_count: int,
        repeated_topic_tag: str,
        repeated_topic_streak: int,
        recent_inner_intents: tuple[str, ...],
        recent_inner_seeds: tuple[str, ...],
    ) -> InnerThought:
        idle_seconds = self._float(getattr(snapshot, "idle_seconds", 0.0) if snapshot is not None else 0.0)
        silence_pressure = self._float(getattr(internal_state, "silence_pressure", 0.0) if internal_state is not None else 0.0)
        boredom = self._float(getattr(internal_state, "boredom", 0.0) if internal_state is not None else 0.0)
        social_energy = self._float(getattr(internal_state, "social_energy", 0.0) if internal_state is not None else 0.0)
        mode = str(getattr(style_memory, "last_mode", "") or "")
        tenderness = self._float(getattr(appraisal, "tenderness", 0.0) if appraisal is not None else 0.0)
        fatigue = self._float(getattr(appraisal, "fatigue", 0.0) if appraisal is not None else 0.0)
        certainty = self._float(getattr(appraisal, "certainty", 0.0) if appraisal is not None else 0.0)
        broadcast_score = self._float(getattr(broadcast, "score", 0.0) if broadcast is not None else 0.0)

        if repeat_count >= 2 or repeated_topic_streak >= 2 or repeated_topic_tag:
            return InnerThought(
                motive="repeat_guard",
                evidence_anchor="recent autonomous topic repeated",
                risk_flags=("repeat_guard", "no_screen_claim"),
            )

        long_quiet = idle_seconds >= 420 or silence_pressure >= 0.54
        socially_warm = tenderness >= 0.42 and (idle_seconds >= 240 or social_energy >= 0.52)
        tired_room = fatigue >= 0.30 and (idle_seconds >= 300 or boredom >= 0.40)
        low_enough_noise = broadcast_score <= 0.58 and certainty <= 0.72
        if not ((long_quiet or socially_warm or tired_room) and low_enough_noise):
            return InnerThought(
                motive="not_enough_social_motive",
                evidence_anchor=f"idle={int(idle_seconds)}s; silence={silence_pressure:.2f}",
                risk_flags=("no_screen_claim",),
            )

        intent, motive, seed = self._choose_candidate(
            self.AUTONOMOUS_CANDIDATES,
            style_memory=style_memory,
            recent_inner_intents=recent_inner_intents,
            recent_inner_seeds=recent_inner_seeds,
        )
        if mode == "comforting" and intent == "random_chatter":
            intent, motive, seed = self.AUTONOMOUS_CANDIDATES[0]

        return InnerThought(
            intent=intent,
            motive=motive,
            topic_seed=seed,
            evidence_anchor=f"quiet idle for {int(idle_seconds)}s",
            certainty=0.54,
            should_surface=True,
            risk_flags=("no_screen_claim", "no_desktop_claim", "social_initiative", "needs_generation"),
            cooldown_seconds=240,
        )

    def _choose_candidate(
        self,
        candidates,
        *,
        style_memory,
        recent_inner_intents: tuple[str, ...],
        recent_inner_seeds: tuple[str, ...],
    ) -> tuple[str, str, str]:
        last_intent = str(getattr(style_memory, "last_intent", "") or "")
        recent_intents = set(str(item) for item in recent_inner_intents[-2:])
        recent_seeds = set(str(item) for item in recent_inner_seeds[-3:])
        for intent, motive, seed in candidates:
            if intent != last_intent and intent not in recent_intents and seed not in recent_seeds:
                return intent, motive, seed
        for intent, motive, seed in candidates:
            if seed not in recent_seeds:
                return intent, motive, seed
        return candidates[0]

    def _broadcast_anchor(self, broadcast) -> str:
        label = str(getattr(broadcast, "label", "") or "")
        if label and label not in {"low_salience", "cycle_channel"}:
            return label
        return ""

    def _float(self, value) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if numeric != numeric:
            return 0.0
        return max(0.0, min(1.0, numeric)) if numeric <= 1.0 else numeric
