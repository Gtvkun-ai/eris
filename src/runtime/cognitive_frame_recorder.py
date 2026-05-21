from __future__ import annotations

import re
import time
from dataclasses import replace

from cortex.contracts import CognitiveFrame, CognitiveMemoryUpdate
from domain import Decision


class CognitiveFrameRecorderMixin:
    def _remember_cognitive_frame(self, frame: CognitiveFrame) -> None:
        remember_cycle = getattr(self.memory_store, "remember_cycle", None)
        #Kiểm tra memory store có hỗ trợ ghi structured memory không
        if self.memory_state is None or not callable(remember_cycle):
            return

        timestamp = ""
        if frame.percepts: #Ưu tiên timestamp của percept đầu tiên trong frame.
            timestamp = frame.percepts[0].timestamp
        if not timestamp: #Nếu không có thì fallback sang thời gian started_at của cycle, hoặc time.now
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(frame.started_at or time.time()))

        # Ưu tiên nội dung từ frame.broadcast.items (tín hiệu đã được attention chọn).
        if frame.broadcast.items:#Nếu có broadcast items, lấy content của chúng làm "seen", vì đây là những thông tin đã được chọn để chú ý trong chu kỳ này.
            seen = tuple(item.content for item in frame.broadcast.items if item.content)
        elif frame.broadcast.content: #Nếu không có items nhưng có broadcast content, thì lấy content này làm "seen", vì đây là tín hiệu tổng quát đã được phát đi trong chu kỳ này.
            seen = (frame.broadcast.content,) 
        else: #Nếu vẫn không có thì fallback lấy tối đa 2 attention_candidates đầu tiên.
            seen = tuple(item.content for item in frame.attention_candidates[:2] if item.content)

        final_text = str(frame.final_decision.get("text", "") or "")
        parse_mode = str(frame.final_decision.get("parse_mode", "") or "")
        outcome = parse_mode or frame.action_plan.speech_intent or "cycle"
        if frame.action_plan.system_action:
            outcome = f"{outcome}:{frame.action_plan.system_action}"

        tags = tuple( #Tags giúp filter/truy vết episode sau này.
            item
            for item in (
                frame.channel,
                frame.action_plan.speech_intent,
                frame.action_plan.speech_act,
                frame.broadcast.label,
            )
            if item
        )
        explicit_user_facts = tuple(
            fact
            for fact in (
                self._extract_explicit_user_memory_fact(percept.content)
                for percept in tuple(frame.percepts or ())
                if percept.kind == "user_message"
            )
            if fact
        )
        semantic_fact = frame.memory_update.remembered_fact or (explicit_user_facts[0] if explicit_user_facts else "")
        before_episodes = len(getattr(self.memory_state, "episodic", []) or [])
        try:
            self.memory_state = remember_cycle(
                self.memory_state,
                cycle_id=frame.cycle_id,
                channel=frame.channel,
                timestamp=timestamp,
                seen=tuple(seen),
                said=final_text,
                outcome=outcome,
                salience=float(frame.broadcast.score or 0.0),
                tags=tags,
                semantic_fact=semantic_fact,
                system_action=frame.action_plan.system_action,
            )
            remember_fact = getattr(self.memory_store, "remember_semantic_fact", None)
            if callable(remember_fact):
                remaining_user_facts = explicit_user_facts[1:] if semantic_fact in explicit_user_facts else explicit_user_facts
                for fact in remaining_user_facts:
                    if fact and fact != semantic_fact:
                        self.memory_state = remember_fact(
                            self.memory_state,
                            fact,
                            source="explicit_user_statement",
                            timestamp=timestamp,
                        )
            self._remember_relationship_reflections(frame, timestamp=timestamp)
            if semantic_fact and not frame.memory_update.semantic_fact:
                frame.memory_update.semantic_fact = semantic_fact
            if getattr(self.memory_state, "working", None):
                frame.memory_update.working_summary = self.memory_state.working[-1].summary
            episodes = getattr(self.memory_state, "episodic", []) or []
            if len(episodes) > before_episodes:
                frame.memory_update.episodic_summary = episodes[-1].summary()
            self.long_term_memory = self._memory_recall_texts()
            self._save_memory_state()
        except Exception as exc:
            self.logger.warning("Cognitive memory commit error: %s", exc)

    def _remember_relationship_reflections(self, frame: CognitiveFrame, *, timestamp: str) -> None:
        remember_reflection = getattr(self.memory_store, "remember_relationship_reflection", None)
        if self.memory_state is None or not callable(remember_reflection):
            return

        reflections = self._derive_relationship_reflections(frame)
        if not reflections:
            return

        recorded: list[str] = []
        for pattern, text, evidence in reflections:
            self.memory_state = remember_reflection(
                self.memory_state,
                text,
                pattern=pattern,
                source="cognitive_frame_reflection",
                timestamp=timestamp,
                evidence=evidence,
            )
            recorded.append(text)
        frame.memory_update.relationship_reflection = " | ".join(recorded)[:260]

    def _derive_relationship_reflections(self, frame: CognitiveFrame) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
        reflections: list[tuple[str, str, tuple[str, ...]]] = []
        channel = str(frame.channel or "")
        speech_act = str(getattr(frame.action_plan, "speech_act", "") or "")
        parse_mode = str(frame.final_decision.get("parse_mode", "") or "")
        notes = tuple(str(item) for item in (getattr(frame.action_plan, "notes", ()) or ()))
        risk_flags = tuple(str(item) for item in (getattr(frame.action_plan, "risk_flags", ()) or ()))
        inner = getattr(frame, "inner_thought", None)
        inner_intent = str(getattr(inner, "intent", "") or "")
        inner_motive = str(getattr(inner, "motive", "") or "")
        inner_seed = str(getattr(inner, "topic_seed", "") or "")

        if channel == "force_speak" and parse_mode in {"inner_thought", "micro_presence"}:
            reflections.append(
                (
                    "force_speak_micro_presence",
                    "Ngài hay bấm force_speak khi muốn ERIS hiện diện hơn là cần thông tin.",
                    (
                        f"speech_act={speech_act}",
                        f"inner_intent={inner_intent}",
                        f"said={str(frame.final_decision.get('text', '') or '')[:80]}",
                    ),
                )
            )

        if parse_mode in {"inner_thought", "micro_presence"} and "no_screen_claim" in risk_flags:
            reflections.append(
                (
                    "no_screen_signal_social_fallback",
                    "Khi thiếu screen signal, ERIS nên hỏi lại hoặc mở một câu tò mò, không giả vờ thấy gì.",
                    (
                        f"channel={channel}",
                        f"motive={inner_motive}",
                        f"seed={inner_seed[:80]}",
                    ),
                )
            )

        user_texts = tuple(
            percept.content
            for percept in tuple(frame.percepts or ())
            if percept.kind == "user_message" and percept.content
        )
        for text in user_texts:
            style_reflection = self._extract_relationship_style_reflection(text)
            if style_reflection:
                reflections.append(style_reflection)

        if any("inner_thought=" in note for note in notes) and parse_mode == "inner_thought":
            reflections.append(
                (
                    "social_initiative_rhythm",
                    "ERIS có thể giữ nhịp hiện diện bằng một câu meta hoặc check-in ngắn, miễn là không dựng cảnh màn hình.",
                    (f"channel={channel}", f"speech_act={speech_act}"),
                )
            )

        deduped: list[tuple[str, str, tuple[str, ...]]] = []
        seen: set[str] = set()
        for pattern, text, evidence in reflections:
            key = self._normalize_user_message(f"{pattern} {text}")
            if key in seen:
                continue
            seen.add(key)
            deduped.append((pattern, text, evidence))
        return tuple(deduped[:4])

    def _extract_relationship_style_reflection(self, user_text: str) -> tuple[str, str, tuple[str, ...]] | None:
        normalized = self._normalize_user_message(user_text)
        if not normalized:
            return None

        likes_cold_soft = any(
            self._normalize_user_message(marker) in normalized
            for marker in (
                "giọng lạnh",
                "lạnh nhẹ",
                "giọng lạnh nhẹ",
                "cold soft",
                "hơi lạnh",
            )
        )
        dislikes_telemetry = any(
            self._normalize_user_message(marker) in normalized
            for marker in (
                "không thích báo cáo telemetry",
                "không thích giọng telemetry",
                "đừng báo cáo telemetry",
                "tránh báo cáo telemetry",
                "không như log",
                "đừng nói như log",
            )
        )
        if likes_cold_soft and dislikes_telemetry:
            return (
                "style_preference",
                "Ngài thích giọng lạnh nhẹ, nhưng không thích báo cáo telemetry.",
                (f"user_text={user_text[:120]}",),
            )
        if likes_cold_soft:
            return (
                "style_preference",
                "Ngài thích giọng lạnh nhẹ và có kiểm soát.",
                (f"user_text={user_text[:120]}",),
            )
        if dislikes_telemetry:
            return (
                "style_preference",
                "Ngài không thích ERIS nói như báo cáo telemetry hoặc log hệ thống.",
                (f"user_text={user_text[:120]}",),
            )
        return None

    def _extract_explicit_user_memory_fact(self, user_text: str) -> str:
        normalized = self._normalize_user_message(user_text)
        if not normalized:
            return ""

        stable_markers = (
            "tôi thích",
            "tôi không thích",
            "tôi thường",
            "tôi hay",
            "gọi tôi là",
            "cứ gọi tôi",
            "quy ước",
            "nhớ rằng",
            "hãy nhớ",
            "i prefer",
            "i usually",
            "call me",
            "remember that",
        )
        if not any(marker in normalized for marker in stable_markers):
            return ""
        compact = re.sub(r"\s+", " ", str(user_text or "").strip())
        if not compact:
            return ""
        return f"User stated: {compact[:180]}"

    def _next_cognitive_cycle_id(self, channel: str) -> str:
        self.cognitive_cycle_index += 1
        return f"{channel}-{self.cognitive_cycle_index}"

    def _bounded_float(self, value: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
        return max(minimum, min(maximum, float(value)))

    # _event_timestamp là hàm tạo “mốc thời gian” (timestamp dạng chuỗi) để gắn cho các event/percept trong một chu kỳ.
    def _event_timestamp(self, snapshot=None, *, started_at: float | None = None) -> str:
        captured_at = str(getattr(snapshot, "captured_at", "") or getattr(snapshot, "time", "") or "").strip()
        if captured_at:
            return captured_at
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started_at or time.time()))

    #chống “spam evidence”, tránh trùng lặp, và giữ payload gọn/ổn định khi log/telemetry.

    def _decision_to_frame_dict(self, decision: Decision | None) -> dict[str, object]:
        if decision is None:
            return {}
        return {
            "text": decision.text,
            "animation": decision.animation,
            "parse_mode": decision.parse_mode,
            "system_action": decision.system_action,
            "action_input": decision.action_input,
            "motion_intent": decision.resolve_motion_intent(),
            "motion_target_x": decision.resolve_motion_target_x(),
            "motion_facing": decision.resolve_motion_facing(),
            "debug_trace": decision.debug_trace,
        }

    def _set_cognitive_memory_update(
        self,
        frame: CognitiveFrame,
        *,
        decision: Decision | None = None,
        notes: tuple[str, ...] = (),
    ) -> None:
        remembered_fact = (decision.extracted_fact if decision else "") or ""
        norm_deviation = " | ".join(
            percept.content
            for percept in tuple(frame.percepts or ())
            if percept.kind == "norm_deviation" and percept.content
        )[:220]
        frame.memory_update = CognitiveMemoryUpdate(
            remembered_fact=remembered_fact,
            remembered_style_excerpt=(decision.text if decision else "")[:140] if decision else "",
            last_text=(self.last_text or "")[:140],
            system_action=(decision.system_action if decision else "") or "",
            notes=tuple(notes),
            semantic_fact=remembered_fact,
            norm_deviation=norm_deviation,
            relationship_reflection=getattr(frame.memory_update, "relationship_reflection", ""),
        )

    def _commit_internal_state_for_frame(
        self,
        frame: CognitiveFrame,
        *,
        snapshot=None,
        ti_report=None,
    ) -> None:
        base_state = frame.internal_state_before or self._get_internal_state()
        committed = self.internal_state_engine.commit_turn(
            base_state if frame.internal_state_after is None else frame.internal_state_after,
            channel=frame.channel,
            snapshot=snapshot,
            ti_report=ti_report,
            appraisal=frame.appraisal,
            speech_core=frame.speech_core,
            action_plan=frame.action_plan,
            inner_thought=frame.inner_thought,
            subconscious_seed=getattr(getattr(frame, "subconscious_report", None), "latest_seed", None),
            thought_surface=getattr(getattr(frame, "thought_stream_report", None), "latest_seed", None),
            self_state=frame.self_state,
            was_spoken=bool(str(frame.final_decision.get("text", "") or "").strip()),
        )
        committed = self._apply_post_relational_leak_restraint(
            committed,
            str(frame.final_decision.get("text", "") or ""),
        )
        frame.internal_state_after = committed
        self._set_internal_state(committed)

    def _apply_post_relational_leak_restraint(self, state: PersistentInternalState, text: str) -> PersistentInternalState:
        exposure = self.micro_line_policy.relational_exposure_score(text)
        if exposure < 0.66:
            return state
        mental_processes = state.mental_processes
        if mental_processes is not None:
            mental_processes = replace(
                mental_processes,
                restraint=mental_processes.restraint.excite(0.34),
                social_presence=mental_processes.social_presence.dampen(0.18),
                background_thought=mental_processes.background_thought.dampen(0.10),
            )
        notes = (*tuple(state.recent_notes or ()), "post_relational_leak_restraint: hold silence after exposure")[-8:]
        return replace(
            state,
            social_energy=max(0.0, min(1.0, state.social_energy * 0.90)),
            social_pressure=max(0.0, min(1.0, state.social_pressure * 0.62)),
            tender_pressure=max(0.0, min(1.0, state.tender_pressure * 0.74)),
            playful_pressure=max(0.0, min(1.0, state.playful_pressure * 0.70)),
            restraint_pressure=max(0.0, min(1.0, state.restraint_pressure + 0.24)),
            silence_pressure=max(0.0, min(1.0, state.silence_pressure + 0.04)),
            recent_notes=notes,
            mental_processes=mental_processes,
        )

    def _finalize_cognitive_frame(self, frame: CognitiveFrame) -> None:
        final_text = str((getattr(frame, "final_decision", {}) or {}).get("text", "") if isinstance(getattr(frame, "final_decision", {}), dict) else "")
        if final_text.strip():
            self.semantic_repeat_guard.remember(final_text, timestamp=float(getattr(frame, "started_at", 0.0) or time.time()))
            family = str(getattr(getattr(frame, "meaning_layer", None), "semantic_family", "") or "")
            if family:
                self.recent_meaning_families = (*tuple(getattr(self, "recent_meaning_families", ()) or ()), family)[-8:]
        self.last_cognitive_frame = frame
        self.cognitive_frames.append(frame)
        self.cognitive_frames = self.cognitive_frames[-12:]
        self._remember_cognitive_frame(frame)
        self.logger.info(
            "[cognitive_frame] id=%s | channel=%s | broadcast=%s:%.2f | speech=%s/%s | appraisal=%s | action=%s/%s | final=%s",
            frame.cycle_id,
            frame.channel,
            frame.broadcast.label or "<none>",
            frame.broadcast.score,
            frame.speech_core.speech_source or "none",
            frame.speech_core.utterance_type or "no_speech",
            frame.appraisal.stance,
            frame.action_plan.speech_intent,
            frame.action_plan.speech_act,
            self._preview_text(str(frame.final_decision.get("text", "")), limit=120),
        )

    def _log_pre_parser(self, channel: str, raw: str) -> None:
        self.logger.info("[%s pre_parser] raw=%s", channel, self._preview_text(raw, limit=320))

    def _log_decision_stage(self, channel: str, stage: str, decision: Decision) -> None:
        self.logger.info(
            "[%s %s] text=\"%s\" | animation=%s | parse_mode=%s | trace=%s | parser=%s",
            channel,
            stage,
            self._preview_text(decision.text),
            decision.animation,
            decision.parse_mode,
            self._preview_text(decision.debug_trace),
            self._preview_text(decision.parser_trace),
        )

