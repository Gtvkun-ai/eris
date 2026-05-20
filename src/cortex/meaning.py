import re
import unicodedata

from .contracts import MeaningLayerResult
'''
snapshot / broadcast / internal_state / thought_stream / user_text
        ↓
_infer_fact()
        ↓
FACT_MAP
        ↓
MeaningLayerResult
        ↓
prompt_context cho tầng sau
'''

class MeaningLayer:
    """Maps Se/telemetry facts into private pressure signals before speech."""

    FACT_MAP = {
        "code_idle_long": (
            "cognitive_stall",
            ("overthinking", "unfinished_intention"),
            "quiet_observe",
            "dry concern",
            "notice the stall without coaching",
        ),
        "tiktok_opened_after_code": (
            "decompression",
            ("avoidance", "fatigue_release"),
            "soft_tease",
            "amused restraint",
            "notice the dodge lightly",
        ),
        "alt_tab_many": (
            "scattered_attention",
            ("restless_search",),
            "dry_marker",
            "cool concern",
            "name the scatter without scolding",
        ),
        "youtube_after_error": (
            "escape_from_friction",
            ("frustration_avoidance",),
            "quiet_tease",
            "dry concern",
            "poke the escape, then stop",
        ),
        "error_visible": (
            "friction_point",
            ("blocked_progress",),
            "focused_concern",
            "practical restraint",
            "notice the friction and stay useful",
        ),
        "meeting_open_idle": (
            "social_waiting",
            ("held_presence",),
            "quiet_observe",
            "cool watchful",
            "notice the waiting room without filling it",
        ),
        "ambient_idle": (
            "ambient_stillness",
            ("continuity",),
            "quiet_presence",
            "low-key restraint",
            "let the silence exist",
        ),
        "user_requested_presence": (
            "requested_presence",
            ("relationship_pull", "continuity"),
            "relationship_ack",
            "present but restrained",
            "answer the pull without overperforming",
        ),
    }

    def evaluate(
        self,
        *,
        snapshot=None,
        broadcast=None,
        internal_state=None,
        thought_stream_report=None,
        channel: str = "",
        user_text: str = "",
        force_speak: bool = False,
        recent_families: tuple[str, ...] = (),
    ) -> MeaningLayerResult:
        channel_name = str(channel or "").strip().lower()
        recent = tuple(str(item or "").strip() for item in tuple(recent_families or ())[-3:] if str(item or "").strip())

        if channel_name == "force_speak" or force_speak:
            #Nó hiểu đây là “user gọi mình lên tiếng”
            return self._build_result(
                "user_requested_presence",
                recent_families=recent,
                meaning_shift=True,
                meaning_signal="meaning_shift",
                shift_reason="force_speak_is_user_requested_presence",
                evidence=("ui_request", *self._safe_evidence(snapshot, broadcast)[:3]),
            )

        #Nó gom dữ kiện từ snapshot, broadcast, thought stream, text user rồi suy ra fact.
        fact, evidence = self._infer_fact(
            snapshot=snapshot,
            broadcast=broadcast,
            internal_state=internal_state,
            thought_stream_report=thought_stream_report,
            user_text=user_text,
        )
        if not fact: #Nếu không có fact mạnh
            ambient_fact, ambient_evidence = self._infer_ambient_fact(snapshot=snapshot, internal_state=internal_state)
            if ambient_fact: #Nếu idle lâu, silence pressure cao, boredom cao thì tạo
                return self._build_result( #Đây là meaning mềm. Không phải bằng chứng cứng.
                    ambient_fact,
                    recent_families=recent,
                    meaning_shift=False,
                    meaning_signal="ambient_meaning",
                    shift_reason="ambient_long_silence_without_hard_shift",
                    evidence=ambient_evidence,
                )
            result = MeaningLayerResult( #: im đi, đừng bịa
                meaning_shift=False,
                meaning_signal="none",
                shift_reason="no_meaningful_fact",
                recent_families=recent,
            )
            result.prompt_context = self._render_empty_context(result)
            return result

        meaning = self.FACT_MAP[fact][0]
        #Nếu semantic family này vừa xuất hiện gần đây, nó không coi là ý nghĩa mới nữa.
        meaning_shift = meaning not in recent
        shift_reason = "new_semantic_family" if meaning_shift else f"recent_semantic_family={meaning}"
        return self._build_result( # ERIS không lặp đi lặp lại cùng một kiểu nhận xét.
            fact,
            recent_families=recent,
            meaning_shift=meaning_shift,
            meaning_signal="meaning_shift" if meaning_shift else "weak_meaning",
            shift_reason=shift_reason,
            evidence=evidence,
        )

    #Hàm này đóng gói mọi thứ thành MeaningLayerResult.
    def _build_result(
        self,
        source_fact: str,
        *,
        recent_families: tuple[str, ...],
        meaning_shift: bool,
        meaning_signal: str,
        shift_reason: str,
        evidence: tuple[str, ...] = (),
    ) -> MeaningLayerResult:
        meaning, secondary, reaction, attitude, surface_intent = self.FACT_MAP[source_fact]
        confidence = 0.92 if source_fact == "user_requested_presence" else 0.72
        if source_fact in {"error_visible", "youtube_after_error"}:
            confidence = 0.82
        mood_residue, emotional_pressure, attention_bias, reaction_impulse = self._private_signals(
            source_fact=source_fact,
            meaning=meaning,
            reaction=reaction,
            attitude=attitude,
        )
        result = MeaningLayerResult(
            source_fact=source_fact,
            meaning=meaning,
            secondary_meanings=secondary,
            semantic_family=meaning,
            confidence=confidence,
            reaction=reaction,
            attitude=attitude,
            surface_intent=surface_intent,
            mood_residue=mood_residue,
            emotional_pressure=emotional_pressure,
            attention_bias=attention_bias,
            reaction_impulse=reaction_impulse,
            meaning_shift=meaning_shift,
            meaning_signal=meaning_signal,
            shift_reason=shift_reason,
            recent_families=recent_families,
            evidence=tuple(str(item) for item in tuple(evidence or ()) if str(item or "").strip())[:6],
        )
        result.prompt_context = self.render_prompt_context(result)
        return result

    #Đây là lớp chuyển meaning thành áp lực nội bộ:
    #thấy lỗi thì nên nghiêng về hỗ trợ thực tế, không phải trêu nhảm
    def _private_signals(
        self,
        *,
        source_fact: str,
        meaning: str,
        reaction: str,
        attitude: str,
    ) -> tuple[str, float, tuple[str, ...], str]:
        pressure_by_fact = {
            "code_idle_long": 0.46,
            "tiktok_opened_after_code": 0.42,
            "alt_tab_many": 0.38,
            "youtube_after_error": 0.52,
            "error_visible": 0.58,
            "meeting_open_idle": 0.36,
            "ambient_idle": 0.24,
            "user_requested_presence": 0.50,
        }
        attention_by_fact = {
            "code_idle_long": ("hesitation", "unfinished_intention"),
            "tiktok_opened_after_code": ("avoidance", "decompression"),
            "alt_tab_many": ("scattered_attention", "hesitation"),
            "youtube_after_error": ("avoidance", "friction_residue"),
            "error_visible": ("friction_point", "practical_attention"),
            "meeting_open_idle": ("social_waiting", "indirect_presence"),
            "ambient_idle": ("ambient_stillness", "indirect_presence"),
            "user_requested_presence": ("relationship_pull", "indirect_presence"),
        }
        residue_by_reaction = {
            "quiet_tease": "dry_warm_residue",
            "soft_tease": "soft_dry_residue",
            "dry_marker": "cool_watchful_residue",
            "focused_concern": "practical_pressure",
            "relationship_ack": "guarded_nearness",
        }
        impulse_by_reaction = {
            "quiet_tease": "react_with_small_concrete_tease",
            "soft_tease": "react_with_soft_aside",
            "dry_marker": "mark_the_shift_briefly",
            "focused_concern": "turn_toward_practical_friction",
            "relationship_ack": "answer_indirectly",
        }
        return (
            residue_by_reaction.get(reaction, attitude or meaning),
            pressure_by_fact.get(source_fact, 0.32),
            attention_by_fact.get(source_fact, (meaning,)),
            impulse_by_reaction.get(reaction, "brief_indirect_reaction"),
        )

    #Hàm này tạo context cho LLM/tầng sau.
    def render_prompt_context(self, result: MeaningLayerResult) -> str:
        if not result.meaning:
            return self._render_empty_context(result.recent_families)
        secondary = ", ".join(result.secondary_meanings) if result.secondary_meanings else "none"
        evidence = " | ".join(result.evidence[:3]) if result.evidence else "none"
        recent = ", ".join(result.recent_families) if result.recent_families else "none"
        return "\n".join(
            (
                "MeaningLayer: private pressure layer, not speech and not wording.",
                (
                    "meaning_layer_internal: "
                    f"fact={result.source_fact}; internal_family={result.semantic_family}; secondary={secondary}; "
                    f"confidence={result.confidence:.2f}. Do not say the internal_family out loud."
                ),
                (
                    "meaning_shift_gate: "
                    f"shift={str(result.meaning_shift).lower()}; reason={result.shift_reason}; "
                    f"signal={result.meaning_signal or 'none'}; recent_3_families={recent}."
                ),
                (
                    "private_speech_inputs: "
                    f"mood_residue={result.mood_residue}; emotional_pressure={result.emotional_pressure:.2f}; "
                    f"attention_bias={','.join(result.attention_bias) or 'none'}; "
                    f"reaction_impulse={result.reaction_impulse}."
                ),
                f"meaning_evidence: {evidence}.",
                "Rule: meaning is not speech. Never verbalize labels like escape_from_friction, cognitive_stall, avoidance, or scattered_attention; wording must come from concrete evidence plus a small reaction.",
            )
        )

    def _render_empty_context(self, result_or_recent) -> str:
        if isinstance(result_or_recent, MeaningLayerResult):
            recent_families = result_or_recent.recent_families
            reason = result_or_recent.shift_reason or "no_meaningful_fact"
            signal = result_or_recent.meaning_signal or "none"
        else:
            recent_families = tuple(result_or_recent or ())
            reason = "no_meaningful_fact"
            signal = "none"
        recent = ", ".join(recent_families) if recent_families else "none"
        return "\n".join(
            (
                "MeaningLayer: no stable meaning was inferred from this frame.",
                f"meaning_shift_gate: shift=false; reason={reason}; signal={signal}; recent_3_families={recent}.",
                "Rule: without a hard shift, allow only weak/ambient/vibe speech, never a hard factual claim.",
            )
        )

    def _infer_ambient_fact(self, *, snapshot, internal_state) -> tuple[str, tuple[str, ...]]:
        idle_seconds = max(0.0, self._float(getattr(snapshot, "idle_seconds", 0.0) if snapshot is not None else 0.0))
        silence_pressure = self._float(getattr(internal_state, "silence_pressure", 0.0) if internal_state is not None else 0.0)
        boredom = self._float(getattr(internal_state, "boredom", 0.0) if internal_state is not None else 0.0)
        if idle_seconds >= 240 or silence_pressure >= 0.58 or boredom >= 0.50:
            return "ambient_idle", tuple(
                item
                for item in (
                    f"idle={int(idle_seconds)}s" if idle_seconds else "",
                    f"silence_pressure={silence_pressure:.2f}" if silence_pressure else "",
                    f"boredom={boredom:.2f}" if boredom else "",
                )
                if item
            )
        return "", ()

    #Đây là bộ detector chính.
    def _infer_fact(
        self,
        *,
        snapshot,
        broadcast,
        internal_state,
        thought_stream_report,
        user_text: str,
    ) -> tuple[str, tuple[str, ...]]:
        parts = self._text_parts(snapshot, broadcast, thought_stream_report, user_text)
        haystack = self._normalize(" ".join(parts))
        focus_kind = str(getattr(snapshot, "active_window_kind", "") or "").strip().lower()
        idle_seconds = max(0.0, self._float(getattr(snapshot, "idle_seconds", 0.0) if snapshot is not None else 0.0))
        user_signals = getattr(snapshot, "user_signals", None)
        focus_pattern = str(getattr(user_signals, "focus_pattern", "") or "").strip().lower()
        switching = str(getattr(user_signals, "window_switching", "") or "").strip().lower()
        recent_focus = tuple(str(item or "").strip().lower() for item in getattr(internal_state, "recent_focus_kinds", ()) or ())
        last_focus = str(getattr(internal_state, "last_focus_kind", "") or "").strip().lower()
        previous_focuses = tuple(item for item in (*recent_focus[-4:], last_focus) if item)

        has_code_context = focus_kind in {"coding", "documentation"} or any(
            term in haystack
            for term in (
                "code",
                "debug",
                "vscode",
                "visual studio",
                "python",
                "terminal",
                "godot",
                "traceback",
            )
        )
        has_error = any(term in haystack for term in ("traceback", "exception", " error", " loi", " bug", "failed", "failure"))
        has_youtube = "youtube" in haystack or "youtu.be" in haystack
        has_tiktok = "tiktok" in haystack
        was_coding = any(item in {"coding", "documentation"} for item in previous_focuses) or has_code_context

        if has_youtube and has_error:
            return "youtube_after_error", self._safe_evidence(snapshot, broadcast, extra=("youtube", "error"))
        if has_tiktok and was_coding:
            return "tiktok_opened_after_code", self._safe_evidence(snapshot, broadcast, extra=("tiktok", "previous_code_context"))
        if switching == "high" or "alt_tab_many" in haystack or "many_windows_open" in haystack or "many_browser_tabs_visible" in haystack:
            return "alt_tab_many", self._safe_evidence(snapshot, broadcast, extra=(switching or "window_switching",))
        if has_error:
            return "error_visible", self._safe_evidence(snapshot, broadcast, extra=("error",))
        if has_code_context and (idle_seconds >= 90 or focus_pattern in {"stuck", "hesitant"}):
            return "code_idle_long", self._safe_evidence(snapshot, broadcast, extra=(f"idle={int(idle_seconds)}s", focus_pattern))
        if focus_kind == "communication" and idle_seconds >= 75 and any(term in haystack for term in ("meet", "zoom", "teams", "call")):
            return "meeting_open_idle", self._safe_evidence(snapshot, broadcast, extra=(f"idle={int(idle_seconds)}s",))
        return "", ()

    def _text_parts(self, snapshot, broadcast, thought_stream_report, user_text: str) -> tuple[str, ...]:
        parts: list[str] = [str(user_text or "")]
        if snapshot is not None:
            user_signals = getattr(snapshot, "user_signals", None)
            parts.extend(
                str(item or "")
                for item in (
                    getattr(snapshot, "active_window", ""),
                    getattr(snapshot, "active_app", ""),
                    getattr(snapshot, "active_window_kind", ""),
                    getattr(snapshot, "focus_summary", ""),
                    getattr(snapshot, "browser_url", ""),
                    getattr(snapshot, "idle_label", ""),
                    getattr(user_signals, "typing_speed", "") if user_signals is not None else "",
                    getattr(user_signals, "window_switching", "") if user_signals is not None else "",
                    getattr(user_signals, "focus_pattern", "") if user_signals is not None else "",
                )
            )
            for collection_name in ("browser_tabs", "open_windows", "recent_events", "evidence", "vision_facts"):
                parts.extend(str(item or "") for item in tuple(getattr(snapshot, collection_name, ()) or ()))
        if broadcast is not None:
            parts.extend(
                str(item or "")
                for item in (
                    getattr(broadcast, "label", ""),
                    getattr(broadcast, "content", ""),
                    getattr(broadcast, "reason", ""),
                    " ".join(str(item) for item in tuple(getattr(broadcast, "evidence", ()) or ())),
                )
            )
            for item in tuple(getattr(broadcast, "items", ()) or ()):
                parts.extend(
                    str(value or "")
                    for value in (
                        getattr(item, "label", ""),
                        getattr(item, "content", ""),
                        getattr(item, "reason", ""),
                        " ".join(str(ev) for ev in tuple(getattr(item, "evidence", ()) or ())),
                    )
                )
        if thought_stream_report is not None:
            latest = getattr(thought_stream_report, "latest_seed", None)
            momentum = getattr(thought_stream_report, "momentum", None)
            parts.extend(
                str(item or "")
                for item in (
                    getattr(latest, "topic_seed", "") if latest is not None else "",
                    getattr(latest, "partial_text", "") if latest is not None else "",
                    getattr(momentum, "topic_seed", "") if momentum is not None else "",
                )
            )
        return tuple(part for part in parts if str(part or "").strip())

    def _safe_evidence(self, snapshot, broadcast, *, extra: tuple[str, ...] = ()) -> tuple[str, ...]:
        evidence: list[str] = [str(item) for item in extra if str(item or "").strip()]
        if snapshot is not None:
            for collection_name in ("recent_events", "evidence", "vision_facts"):
                evidence.extend(str(item) for item in tuple(getattr(snapshot, collection_name, ()) or ())[:3] if str(item or "").strip())
        if broadcast is not None:
            for value in (getattr(broadcast, "label", ""), getattr(broadcast, "content", "")):
                if str(value or "").strip():
                    evidence.append(str(value))
        return tuple(dict.fromkeys(evidence))[:6]

    def _normalize(self, text: str) -> str:
        lowered = str(text or "").strip().lower()
        try:
            remojibake = lowered.encode("latin1").decode("utf-8")
            if remojibake:
                lowered = remojibake
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        lowered = unicodedata.normalize("NFD", lowered)
        lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
        lowered = lowered.replace("đ", "d")
        lowered = re.sub(r"[^a-z0-9_#./:\s-]+", " ", lowered)
        return " ".join(lowered.split())

    def _float(self, value) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if numeric != numeric:
            return 0.0
        return max(0.0, numeric)
