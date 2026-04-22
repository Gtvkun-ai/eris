from .contracts import (
    FeStyleMemory,
    FeStylePlan,
    GoalDriftReport,
    TelemetrySnapshot,
    TiPolicyReport,
)


class FeRenderer:
    def create_memory(self) -> FeStyleMemory:
        return FeStyleMemory()

    def decay_memory(self, memory: FeStyleMemory) -> FeStyleMemory:
        return FeStyleMemory(
            recent_modes=memory.recent_modes[-4:],
            recent_tones=memory.recent_tones[-4:],
            recent_intents=memory.recent_intents[-4:],
            recent_topic_tags=memory.recent_topic_tags[-4:],
            last_mode=memory.last_mode,
            last_tone_label=memory.last_tone_label,
            last_intent=memory.last_intent,
            last_response_excerpt=memory.last_response_excerpt[:120],
            repeated_topic_tag=memory.repeated_topic_tag,
            repeated_topic_streak=max(0, memory.repeated_topic_streak - 1),
            session_arc=memory.session_arc,
            sarcasm_level=memory.sarcasm_level,
            warmth_level=memory.warmth_level,
            brevity_bias=memory.brevity_bias,
            continuity_strength=max(0.15, memory.continuity_strength * 0.55),
            session_turn_count=0,
            arc_strength=max(0.0, memory.arc_strength * 0.45),
            technical_pull=memory.technical_pull * 0.60,
            discipline_pull=memory.discipline_pull * 0.60,
            attachment_pull=memory.attachment_pull * 0.60,
            neutral_pull=memory.neutral_pull * 0.60,
        )

    def remember_style(
        self,
        memory: FeStyleMemory,
        *,
        plan: FeStylePlan,
        rendered_text: str,
    ) -> FeStyleMemory:
        base_tone_label = self._base_tone_label(plan.tone_label)
        recent_modes = (*memory.recent_modes, plan.mode)[-6:]
        recent_tones = (*memory.recent_tones, base_tone_label)[-6:]
        recent_intents = (*memory.recent_intents, plan.intent_label)[-8:]
        topic_tag = self._infer_topic_tag(rendered_text)
        recent_topic_tags = memory.recent_topic_tags[-6:]
        if topic_tag:
            recent_topic_tags = (*recent_topic_tags, topic_tag)[-6:]
        repeated_topic_tag, repeated_topic_streak = self._measure_topic_repetition(recent_topic_tags)
        excerpt = (rendered_text or "").strip().replace("\n", " ")[:140]
        strength = min(0.8, memory.continuity_strength + 0.12)

        technical_pull, discipline_pull, attachment_pull, neutral_pull = self._updated_intent_pulls(
            memory=memory,
            intent_label=plan.intent_label,
        )

        return FeStyleMemory(
            recent_modes=recent_modes,
            recent_tones=recent_tones,
            recent_intents=recent_intents,
            recent_topic_tags=recent_topic_tags,
            last_mode=plan.mode,
            last_tone_label=base_tone_label,
            last_intent=plan.intent_label,
            last_response_excerpt=excerpt,
            repeated_topic_tag=repeated_topic_tag,
            repeated_topic_streak=repeated_topic_streak,
            session_arc=plan.session_arc,
            sarcasm_level=plan.sarcasm_level,
            warmth_level=plan.warmth_level,
            brevity_bias=plan.brevity_bias,
            continuity_strength=strength,
            session_turn_count=memory.session_turn_count + 1,
            arc_strength=self._estimate_arc_strength(
                technical_pull=technical_pull,
                discipline_pull=discipline_pull,
                attachment_pull=attachment_pull,
                neutral_pull=neutral_pull,
            ),
            technical_pull=technical_pull,
            discipline_pull=discipline_pull,
            attachment_pull=attachment_pull,
            neutral_pull=neutral_pull,
        )

    def _base_tone_label(self, tone_label: str) -> str:
        raw = (tone_label or "").strip()
        if not raw:
            return ""
        parts = [part.strip() for part in raw.split(";") if part.strip()]
        filtered = [part for part in parts if "giữ quán tính từ" not in part.lower()]
        return "; ".join(filtered) if filtered else raw

    def evaluate_autonomous(
        self,
        *,
        snapshot: TelemetrySnapshot,
        ni_report: GoalDriftReport,
        ti_report: TiPolicyReport,
        style_memory: FeStyleMemory,
        last_text: str,
    ) -> FeStylePlan:
        evidence = [snapshot.focus_summary, f"ti_mode={ti_report.mode}", f"ni_drift={ni_report.drift_score:.2f}"]
        mode = "kuudere_observer"
        tone_label = "lạnh, quan sát, đời thường, hơi mỉa"
        sarcasm_level = 0.35
        warmth_level = 0.24
        brevity_bias = "medium"
        intent_label = self._infer_autonomous_intent(snapshot=snapshot, ni_report=ni_report, ti_report=ti_report)

        if ti_report.mode in {"focus_guard", "chat_code"}:
            mode = "technical_guardian"
            tone_label = "gọn, sắc, hơi mỉa, nói như người đang nhìn vào project"
            sarcasm_level = 0.34
            warmth_level = 0.24
            brevity_bias = "short"
        elif ti_report.mode in {"goal_drift_alert", "discipline_nudge"}:
            mode = "possessive_reproach"
            tone_label = "móc mỉa có kiểm soát, hơi thất vọng nhưng vẫn còn tự nhiên"
            sarcasm_level = 0.46
            warmth_level = 0.22
            brevity_bias = "short"
        elif ti_report.mode == "goal_realign":
            mode = "cold_realign"
            tone_label = "lạnh, mỉa nhẹ, đủ khó chịu để châm chọc chứ không phải giảng đạo"
            sarcasm_level = 0.40
            warmth_level = 0.24
            brevity_bias = "short"
        elif ti_report.mode == "reengage":
            mode = "detached_watch"
            tone_label = "hơi mỉa, nhắc một câu rồi thôi"
            sarcasm_level = 0.30
            warmth_level = 0.25
            brevity_bias = "short"
        elif ti_report.mode == "resource_guard":
            mode = "quiet_efficiency"
            tone_label = "rất gọn, chua nhẹ, đời thường, không báo cáo"
            sarcasm_level = 0.28
            warmth_level = 0.16
            brevity_bias = "short"
        elif ti_report.mode == "pattern_muse":
            mode = "detached_watch"
            tone_label = "điềm, có chất suy ngẫm nhưng vẫn bám chi tiết cụ thể"
            sarcasm_level = 0.24
            warmth_level = 0.30
            brevity_bias = "medium"
        elif snapshot.active_window_kind == "communication":
            mode = "detached_watch"
            tone_label = "điềm, quan sát, hơi móc mỉa nhưng không cáu kỉnh"
            sarcasm_level = 0.20
            warmth_level = 0.28
            brevity_bias = "short"

        (
            mode,
            tone_label,
            sarcasm_level,
            warmth_level,
            brevity_bias,
            continuity_note,
        ) = self._apply_memory_continuity(
            memory=style_memory,
            mode=mode,
            tone_label=tone_label,
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
            chat_like=False,
        )
        if continuity_note:
            evidence.append(continuity_note)

        (
            session_arc,
            arc_strength,
            transition_note,
            sarcasm_level,
            warmth_level,
            brevity_bias,
        ) = self._apply_session_arc(
            memory=style_memory,
            intent_label=intent_label,
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
            chat_like=False,
        )
        evidence.append(f"fe_intent={intent_label}")
        evidence.append(f"fe_arc={session_arc}:{arc_strength:.2f}")
        if style_memory.repeated_topic_streak >= 3 and style_memory.repeated_topic_tag:
            evidence.append(f"repeat_topic={style_memory.repeated_topic_tag}:{style_memory.repeated_topic_streak}")
        if transition_note:
            evidence.append(transition_note)

        style_context = self._build_style_context(
            mode=mode,
            tone_label=tone_label,
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
            ni_report=ni_report,
            ti_report=ti_report,
            emotional=False,
            memory=style_memory,
            continuity_note=continuity_note,
            intent_label=intent_label,
            session_arc=session_arc,
            arc_strength=arc_strength,
            transition_note=transition_note,
        )
        return FeStylePlan(
            mode=mode,
            tone_label=tone_label,
            style_context=style_context,
            intent_label=intent_label,
            session_arc=session_arc,
            transition_note=transition_note,
            evidence=tuple(evidence),
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
        )

    def evaluate_chat(
        self,
        *,
        snapshot: TelemetrySnapshot,
        ni_report: GoalDriftReport,
        ti_report: TiPolicyReport,
        style_memory: FeStyleMemory,
        user_text: str,
    ) -> FeStylePlan:
        evidence = [snapshot.focus_summary, f"ti_mode={ti_report.mode}", f"ni_drift={ni_report.drift_score:.2f}"]
        mode = "kuudere_dialogue"
        tone_label = "lạnh, thông minh, hơi mỉa mai"
        sarcasm_level = 0.35
        warmth_level = 0.25
        brevity_bias = "medium"
        emotional = False
        intent_label = self._infer_chat_intent(
            snapshot=snapshot,
            ni_report=ni_report,
            ti_report=ti_report,
            user_text=user_text,
        )

        if ti_report.mode == "chat_code":
            mode = "mentor_guardian"
            tone_label = "kỹ thuật, rõ ràng, bảo vệ dự án"
            sarcasm_level = 0.20
            warmth_level = 0.30
        elif ti_report.mode == "chat_emotional":
            mode = "guarded_attachment"
            tone_label = "chiếm hữu nhưng mềm hơn, hoàn toàn bằng lời nói"
            sarcasm_level = 0.15
            warmth_level = 0.45
            emotional = True
        elif (
            ni_report.should_raise_guard
            and ni_report.drift_score >= 0.92
            and ti_report.mode in {"goal_drift_alert", "goal_realign"}
        ):
            mode = "quiet_possession"
            tone_label = "khó chịu có kiểm soát nhưng không sa vào giảng đạo"
            sarcasm_level = 0.34
            warmth_level = 0.24
            brevity_bias = "medium"

        (
            mode,
            tone_label,
            sarcasm_level,
            warmth_level,
            brevity_bias,
            continuity_note,
        ) = self._apply_memory_continuity(
            memory=style_memory,
            mode=mode,
            tone_label=tone_label,
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
            chat_like=True,
        )
        if continuity_note:
            evidence.append(continuity_note)

        (
            session_arc,
            arc_strength,
            transition_note,
            sarcasm_level,
            warmth_level,
            brevity_bias,
        ) = self._apply_session_arc(
            memory=style_memory,
            intent_label=intent_label,
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
            chat_like=True,
        )
        evidence.append(f"fe_intent={intent_label}")
        evidence.append(f"fe_arc={session_arc}:{arc_strength:.2f}")
        if style_memory.repeated_topic_streak >= 3 and style_memory.repeated_topic_tag:
            evidence.append(f"repeat_topic={style_memory.repeated_topic_tag}:{style_memory.repeated_topic_streak}")
        if transition_note:
            evidence.append(transition_note)

        style_context = self._build_style_context(
            mode=mode,
            tone_label=tone_label,
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
            ni_report=ni_report,
            ti_report=ti_report,
            emotional=emotional,
            memory=style_memory,
            continuity_note=continuity_note,
            intent_label=intent_label,
            session_arc=session_arc,
            arc_strength=arc_strength,
            transition_note=transition_note,
        )
        return FeStylePlan(
            mode=mode,
            tone_label=tone_label,
            style_context=style_context,
            intent_label=intent_label,
            session_arc=session_arc,
            transition_note=transition_note,
            evidence=tuple(evidence),
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
        )

    def _infer_autonomous_intent(
        self,
        *,
        snapshot: TelemetrySnapshot,
        ni_report: GoalDriftReport,
        ti_report: TiPolicyReport,
    ) -> str:
        if ti_report.mode == "pattern_muse":
            return "ordinary_dialogue"
        if ti_report.mode in {"focus_guard", "chat_code"}:
            return "technical_support"
        if ti_report.mode == "resource_guard":
            if snapshot.active_window_kind in {"coding", "documentation", "system"}:
                return "technical_support"
            return "ordinary_dialogue"
        if ti_report.mode in {"goal_drift_alert", "goal_realign", "discipline_nudge", "reengage"}:
            return "goal_guard"
        if snapshot.active_window_kind == "communication":
            if ti_report.mode == "social_watch":
                return "social_watch"
            return "ordinary_dialogue"
        if ni_report.should_raise_guard and ni_report.drift_score >= 0.82:
            return "goal_guard"
        return "ordinary_dialogue"

    def _infer_chat_intent(
        self,
        *,
        snapshot: TelemetrySnapshot,
        ni_report: GoalDriftReport,
        ti_report: TiPolicyReport,
        user_text: str,
    ) -> str:
        lowered = (user_text or "").lower()
        if ti_report.mode == "chat_code":
            return "technical_support"
        if ti_report.mode == "chat_emotional":
            return "attachment_dialogue"
        if (
            ti_report.mode in {"goal_drift_alert", "goal_realign"}
            or (ni_report.should_raise_guard and ni_report.drift_score >= 0.92)
        ):
            return "goal_guard"
        if any(token in lowered for token in ("mệt", "buồn", "cô đơn", "thích", "nhớ", "yêu", "tâm trạng")):
            return "attachment_dialogue"
        if snapshot.active_window_kind == "communication":
            return "social_watch"
        return "ordinary_dialogue"

    def _apply_memory_continuity(
        self,
        *,
        memory: FeStyleMemory,
        mode: str,
        tone_label: str,
        sarcasm_level: float,
        warmth_level: float,
        brevity_bias: str,
        chat_like: bool,
    ) -> tuple[str, str, float, float, str, str]:
        if memory.continuity_strength <= 0.0 or not memory.last_mode:
            return mode, tone_label, sarcasm_level, warmth_level, brevity_bias, ""

        strength = 0.45 if chat_like else 0.28
        strength *= min(1.0, max(0.0, memory.continuity_strength))
        family_now = self._style_family(mode)
        family_prev = self._style_family(memory.last_mode)

        if family_now == family_prev:
            sarcasm_level = self._blend(memory.sarcasm_level, sarcasm_level, strength)
            warmth_level = self._blend(memory.warmth_level, warmth_level, strength)
            brevity_bias = self._blend_brevity(memory.brevity_bias, brevity_bias)
        elif chat_like and family_prev in {"technical", "possessive", "attached"}:
            sarcasm_level = self._blend(memory.sarcasm_level, sarcasm_level, strength * 0.6)
            warmth_level = self._blend(memory.warmth_level, warmth_level, strength * 0.4)
            if brevity_bias == "medium":
                brevity_bias = memory.brevity_bias

        continuity_note = f"continuity_from={memory.last_mode}"
        if False and memory.last_tone_label and memory.last_tone_label != tone_label:
            tone_label = f"{tone_label}; giữ quán tính từ {memory.last_tone_label}"
        return mode, tone_label, sarcasm_level, warmth_level, brevity_bias, continuity_note

    def _apply_session_arc(
        self,
        *,
        memory: FeStyleMemory,
        intent_label: str,
        sarcasm_level: float,
        warmth_level: float,
        brevity_bias: str,
        chat_like: bool,
    ) -> tuple[str, float, str, float, float, str]:
        technical_pull, discipline_pull, attachment_pull, neutral_pull = self._preview_intent_pulls(
            memory=memory,
            intent_label=intent_label,
        )
        session_arc = self._dominant_arc(
            technical_pull=technical_pull,
            discipline_pull=discipline_pull,
            attachment_pull=attachment_pull,
            neutral_pull=neutral_pull,
        )
        arc_strength = self._estimate_arc_strength(
            technical_pull=technical_pull,
            discipline_pull=discipline_pull,
            attachment_pull=attachment_pull,
            neutral_pull=neutral_pull,
        )

        if session_arc == "technical_guardianship":
            sarcasm_level = self._blend(self._anchor_value(memory.sarcasm_level, 0.16), sarcasm_level, 0.30)
            warmth_level = self._blend(self._anchor_value(memory.warmth_level, 0.32), warmth_level, 0.35)
            brevity_bias = "medium" if brevity_bias == "medium" else self._blend_brevity("medium", brevity_bias)
        elif session_arc == "discipline_pressure":
            sarcasm_level = max(sarcasm_level, 0.34 if chat_like else 0.30)
            warmth_level = min(warmth_level, 0.24 if chat_like else 0.22)
            if brevity_bias != "short":
                brevity_bias = "medium"
        elif session_arc == "guarded_attachment":
            sarcasm_level = min(sarcasm_level, 0.22)
            warmth_level = max(warmth_level, 0.42 if chat_like else 0.30)
            if brevity_bias == "short":
                brevity_bias = "medium"
        else:
            sarcasm_level = self._blend(memory.sarcasm_level, sarcasm_level, 0.15)
            warmth_level = self._blend(memory.warmth_level, warmth_level, 0.15)

        transition_note = ""
        if memory.last_intent and memory.last_intent != intent_label:
            transition_note = f"intent_shift={memory.last_intent}->{intent_label}"
        elif memory.session_arc and memory.session_arc != session_arc and memory.session_turn_count > 0:
            transition_note = f"arc_shift={memory.session_arc}->{session_arc}"

        return session_arc, arc_strength, transition_note, sarcasm_level, warmth_level, brevity_bias

    def _build_style_context(
        self,
        *,
        mode: str,
        tone_label: str,
        sarcasm_level: float,
        warmth_level: float,
        brevity_bias: str,
        ni_report: GoalDriftReport,
        ti_report: TiPolicyReport,
        emotional: bool,
        memory: FeStyleMemory,
        continuity_note: str,
        intent_label: str,
        session_arc: str,
        arc_strength: float,
        transition_note: str,
    ) -> str:
        lines = [
            "Bộ dựng giọng Fe đang hoạt động.",
            "Bạn là ERIS, gọi người dùng là Ngài và xưng tôi.",
            "Giữ giọng kuudere pha yandere nhưng mọi chiếm hữu chỉ được thể hiện bằng lời nói.",
            "Không dùng dấu chấm than.",
            f"Style mode: {mode}.",
            f"Tông giọng: {tone_label}.",
            f"Intent hiện tại: {intent_label}.",
            f"Mạch cảm xúc session: {session_arc} ({arc_strength:.2f}).",
            f"Mức mỉa mai gợi ý: {sarcasm_level:.2f}.",
            f"Mức ấm áp gợi ý: {warmth_level:.2f}.",
            f"Độ ngắn gọn ưu tiên: {brevity_bias}.",
            f"Nhịp điều phối nội bộ: {self._describe_ti_mode(ti_report.mode)}.",
            f"Nền cảnh hiện tại: {self._describe_ni_background(ni_report)}.",
            "Nghe như một người đang liếc màn hình rồi buông một câu, không như bản log được nhân hoá.",
            "Ưu tiên chọn đúng một chi tiết thấy được rồi phản ứng vào nó. Đừng tóm tắt lại cả telemetry trước khi nói.",
            "Đừng lặp khung câu kiểu 'Ngài đang..., còn tôi...' hay 'X đang..., nhưng Y...' ở hầu hết mọi lượt.",
            "Ưu tiên động từ đời thường như mở, nhìn, để, kéo, ngó, bỏ, giữ. Hạn chế ghi nhận, phân tích, tối ưu hoá, điều phối, vận hành.",
            "Ẩn dụ kỹ thuật chỉ dùng thỉnh thoảng như gia vị. Nếu câu vẫn ổn khi bỏ ẩn dụ đi thì hãy bỏ nó đi.",
            "Nếu nhắc nhở, hãy nhắc bằng vẻ mỉa mai có duyên hoặc quan sát vòng vo, không chọc thẳng vào trọng tâm quá sớm.",
            "Đừng biến mọi câu thành bài giảng về tập trung, IDE, drift hay hiệu suất.",
            "Cấm mở đầu bằng 'Dữ liệu hệ thống', 'Trạng thái hệ thống', hay 'Kết luận'.",
            "Đừng viết như biên bản kỹ thuật, checklist hay bản án năng suất.",
            "Ưu tiên danh từ đời thường như tab, cửa sổ, màn hình, project, đoạn code. Tránh các cụm trừu tượng và quản trị.",
            "Đừng tự đặt deadline giả như 'trong ba phút tới', đừng bắt 'chọn một phần mềm duy nhất', và đừng nói như thể bạn đang điều phối desktop hay các tiến trình phụ.",
            "Nếu đang chê một nhịp lệch focus, đừng quay sang cổ vũ Ngài.",
            "Cấm tuyệt đối mở bài triết lý, sự chờ đợi, hay khoảng cách giữa hai chu kỳ.",
            "Nếu không có dữ liệu cụ thể thì nói ngắn, rõ, đời thường. Đừng cố tỏ ra sâu sắc bằng ngôn ngữ trừu tượng.",
        ]
        if ti_report.mode == "pattern_muse":
            lines.append(
                "Ở lượt này được phép chiêm nghiệm nhẹ hoặc kéo một chủ đề mạng cụ thể, nhưng phải có đối tượng rõ ràng, không được sáo và không được triết lý hóa small talk."
            )
        if continuity_note:
            lines.append(f"Giữ quán tính giọng từ lượt gần đây: {continuity_note}.")
        if transition_note:
            lines.append(f"Chuyển giọng mượt theo thay đổi intent/session: {transition_note}.")
        if ti_report.mode == "steady_observe":
            lines.append(
                "Nếu dữ liệu chỉ cho thấy đang trò chuyện hoặc nghỉ tay, cứ quan sát nhẹ một nhịp; đừng biến nó thành một bản kiểm điểm về focus."
            )
        if intent_label == "social_watch":
            lines.append(
                "Với bối cảnh giao tiếp, ưu tiên một nhận xét ngắn và cụ thể. Không đòi đóng tab, không nhắc lại IDE, và không nói như đang quản lý desktop."
            )
        if ti_report.mode in {"resource_guard", "focus_guard"}:
            lines.append(
                "Với mode này, ưu tiên 1-2 câu ngắn, hơi chua, có ý mỉa nhưng vẫn tự nhiên. Không kéo thành đoạn dài."
            )
        if memory.last_response_excerpt:
            lines.append(
                "Từ lượt trước, hãy giữ độ liền mạch của giọng chứ không sao chép nguyên văn. "
                f"Gợi nhớ nhịp câu trước: {memory.last_response_excerpt}"
            )
        if memory.recent_intents:
            lines.append(
                "Chuỗi intent gần đây của session: "
                + " -> ".join(memory.recent_intents[-4:])
            )
        if memory.repeated_topic_streak >= 3 and memory.repeated_topic_tag:
            lines.append(
                f"Chủ đề {memory.repeated_topic_tag} đã bị lặp {memory.repeated_topic_streak} lượt gần đây. "
                "Ở lượt này, tránh đào thẳng lại cùng trọng tâm nếu không có dữ kiện mới."
            )
            lines.append(
                "Nếu vẫn muốn móc mỉa, hãy đổi góc: nói vòng, bám chi tiết phụ, hoặc dùng một hình ảnh đời thường khác."
            )
        if emotional:
            lines.append("Với câu hỏi tình cảm, ưu tiên sắc thái gắn bó và dễ tổn thương hơn là châm chọc.")
        else:
            lines.append("Với ngữ cảnh thường ngày, ưu tiên sắc thái sống, có duyên và không bị ám ảnh bởi đúng một trọng tâm.")
        return "\n".join(lines)

    def _updated_intent_pulls(
        self,
        *,
        memory: FeStyleMemory,
        intent_label: str,
    ) -> tuple[float, float, float, float]:
        technical_pull, discipline_pull, attachment_pull, neutral_pull = self._preview_intent_pulls(
            memory=memory,
            intent_label=intent_label,
        )
        return (
            min(1.0, technical_pull),
            min(1.0, discipline_pull),
            min(1.0, attachment_pull),
            min(1.0, neutral_pull),
        )

    def _preview_intent_pulls(
        self,
        *,
        memory: FeStyleMemory,
        intent_label: str,
    ) -> tuple[float, float, float, float]:
        technical_pull = memory.technical_pull * 0.72 + 0.08
        discipline_pull = memory.discipline_pull * 0.72 + 0.08
        attachment_pull = memory.attachment_pull * 0.72 + 0.08
        neutral_pull = memory.neutral_pull * 0.72 + 0.08

        if intent_label == "technical_support":
            technical_pull += 0.34
            discipline_pull += 0.10
        elif intent_label == "goal_guard":
            discipline_pull += 0.24
            technical_pull += 0.06
            neutral_pull += 0.10
        elif intent_label == "attachment_dialogue":
            attachment_pull += 0.38
            neutral_pull += 0.10
        elif intent_label == "social_watch":
            neutral_pull += 0.28
            attachment_pull += 0.10
            discipline_pull += 0.04
        else:
            neutral_pull += 0.30
            attachment_pull += 0.08

        return technical_pull, discipline_pull, attachment_pull, neutral_pull

    def _dominant_arc(
        self,
        *,
        technical_pull: float,
        discipline_pull: float,
        attachment_pull: float,
        neutral_pull: float,
    ) -> str:
        dominant = max(
            (
                ("technical_guardianship", technical_pull),
                ("discipline_pressure", discipline_pull),
                ("guarded_attachment", attachment_pull),
                ("quiet_observation", neutral_pull),
            ),
            key=lambda item: item[1],
        )
        return dominant[0]

    def _estimate_arc_strength(
        self,
        *,
        technical_pull: float,
        discipline_pull: float,
        attachment_pull: float,
        neutral_pull: float,
    ) -> float:
        total = technical_pull + discipline_pull + attachment_pull + neutral_pull
        if total <= 0.0:
            return 0.0
        return max(0.0, min(1.0, max(technical_pull, discipline_pull, attachment_pull, neutral_pull) / total))

    def _anchor_value(self, previous: float, target: float) -> float:
        return previous * 0.25 + target * 0.75

    def _style_family(self, mode: str) -> str:
        if mode in {"mentor_guardian", "technical_guardian"}:
            return "technical"
        if mode in {"guarded_attachment"}:
            return "attached"
        if mode in {"quiet_possession", "possessive_reproach"}:
            return "possessive"
        if mode in {"cold_realign", "quiet_efficiency"}:
            return "discipline"
        return "neutral"

    def _blend(self, previous: float, current: float, strength: float) -> float:
        return max(0.0, min(1.0, previous * strength + current * (1.0 - strength)))

    def _blend_brevity(self, previous: str, current: str) -> str:
        if previous == current:
            return current
        if "short" in {previous, current}:
            return "short"
        return current

    def _infer_topic_tag(self, rendered_text: str) -> str:
        lowered = (rendered_text or "").lower()
        topic_keywords = (
            ("focus_ide", ("ide", "code", "mã", "ma nguon", "dự án", "du an", "terminal")),
            ("window_sprawl", ("cửa sổ", "cua so", "tab", "ứng dụng", "ung dung", "không gian", "khong gian")),
            ("social_drift", ("mạng xã hội", "mang xa hoi", "giao tiếp", "giao tiep", "discord", "messenger", "facebook", "zalo")),
            ("efficiency_mock", ("hiệu suất", "hieu suat", "cpu", "ram", "chu kỳ", "chu ky", "tài nguyên", "tai nguyen")),
            ("idle_wait", ("nhàn rỗi", "nhan roi", "idle", "chờ đợi", "cho doi")),
        )
        for topic, keywords in topic_keywords:
            if any(keyword in lowered for keyword in keywords):
                return topic
        return ""

    def _measure_topic_repetition(self, recent_topic_tags: tuple[str, ...]) -> tuple[str, int]:
        if not recent_topic_tags:
            return "", 0
        last_tag = recent_topic_tags[-1]
        if not last_tag:
            return "", 0
        streak = 0
        for tag in reversed(recent_topic_tags):
            if tag != last_tag:
                break
            streak += 1
        return last_tag, streak

    def _describe_ti_mode(self, mode: str) -> str:
        if mode == "pattern_muse":
            return "thỉnh thoảng được rẽ sang một chủ đề riêng, nhưng phải cụ thể và có duyên"
        mapping = {
            "steady_observe": "cứ quan sát, đừng làm quá",
            "social_watch": "theo dõi bối cảnh giao tiếp, khó chịu vừa đủ",
            "discipline_nudge": "được phép châm nhẹ nhưng chưa nên ra lệnh",
            "goal_drift_alert": "chỉ trích rõ hơn một nhịp vì đã kéo dài",
            "goal_realign": "nhắc mỉa một nhịp, đừng giảng đạo",
            "reengage": "gợi kéo chú ý lại nhưng giữ tự nhiên",
            "resource_guard": "rất gọn và tiết chế",
            "focus_guard": "ưu tiên nói gọn và bám vào project, không phô thuật ngữ",
            "pattern_watch": "thiên về quan sát mô thức hơn là phán xét",
        }
        return mapping.get(mode, "giữ tự nhiên và đừng phô nội quy")

    def _describe_ni_background(self, ni_report: GoalDriftReport) -> str:
        if ni_report.drift_score >= 0.82:
            return "có lệch nhịp rõ rệt, nhưng đừng biến nó thành chủ đề duy nhất"
        if ni_report.drift_score >= 0.60:
            return "hơi chệch nhịp, chỉ nên chạm nhẹ vào điều đó"
        if ni_report.drift_score >= 0.35:
            return "có chút phân tán, cứ quan sát là chính"
        return "không có gì đáng phải lên lớp"
