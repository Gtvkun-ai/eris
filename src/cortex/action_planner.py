from .contracts import CognitiveActionPlan, SelfState


ACTION_SPACE = (
    "no_speech", #im lặng, không nói gì cả
    "observe", #Quan sát rồi comment
    "tease", #chọc nhẹ
    "protect", #bảo vệ, cảnh báo
    "withdraw", #rút lui
    "ask", #hỏi lại để làm rõ
    "reassure", #đảm bảo, trấn an
    "react", #phản ứng nhưng không rõ ràng là đồng ý hay từ chối
    "hesitate", #do dự, thể hiện sự không chắc chắn
    "suppress", #kìm nén, không nói ra dù có thể muốn nói
    "indirect_presence", #hiện diện một cách gián tiếp, không nói ra nhưng vẫn cho thấy sự hiện diện
    "guarded_reply", #trả lời nhưng giữ khoảng cách
    "refuse", #từ chối thẳng thừng
    "mirror", #phản chiếu, lặp lại hoặc diễn đạt lại lời người dùng để thể hiện sự thấu hiểu
    "meta_reply", #trả lời về chính quá trình trả lời, như "Tôi đang nghĩ về điều đó" hoặc "Đó là một câu hỏi hay"
    "telemetry_comment", #bình luận dựa trên dữ liệu cảm biến hoặc trạng thái hệ thống
    "vision_comment", #bình luận dựa trên dữ liệu thị giác hoặc nhận thức về môi trường xung quanh
    "micro_observation", #quan sát nhỏ, nhận xét về một chi tiết nhỏ trong môi trường hoặc cuộc trò chuyện
    "micro_presence", #hiện diện nhẹ
    "reengagement", #tái tương tác, cố gắng tái thu hút sự chú ý của người dùng sau một khoảng thời gian im lặng
    "random_chatter", #nói chuyện ngẫu nhiên, bình luận không liên quan trực tiếp đến cuộc trò chuyện hiện tại
    "inner_whim", #thích thú nội tâm, nói ra một suy nghĩ hoặc ý tưởng ngẫu nhiên xuất phát từ "tâm trạng" hoặc "suy nghĩ" của ERIS
    "curious_question", #đặt một câu hỏi tò mò, không nhất thiết liên quan đến cuộc trò chuyện hiện tại, nhưng nhằm mục đích thể hiện sự tò mò và thúc đẩy sự tương tác
    "relational_checkin", #kiểm tra mối quan hệ, một bình luận hoặc câu hỏi nhằm mục đích duy trì hoặc củng cố mối quan hệ giữa ERIS và người dùng, như "Bạn có ổn không?" hoặc "Tôi ở đây nếu bạn cần tôi."
    "light_muse", #gợi ý nhẹ, đưa ra một gợi ý hoặc đề xuất một cách nhẹ nhàng, không áp đặt
    "soft_boundary", #ranh giới mềm, thiết lập một ranh giới một cách nhẹ nhàng, như "Tôi không thể giúp với điều đó, nhưng tôi có thể giúp với những thứ khác."
    "system_action", #hành động hệ thống, khi ERIS thực hiện một hành động cụ thể trên hệ thống (như mở ứng dụng, tìm kiếm web, v.v.) thay vì nói chuyện
)


class ActionPlanner:
    """Chooses the runtime action before any LLM wording step."""

    def plan(
        self,
        *,
        channel: str,
        snapshot=None,
        ti_report=None,
        fe_plan=None,
        appraisal=None,
        broadcast=None,
        user_text: str = "",
        force_speak: bool = False,
        proposed_intent: str = "",
        proposed_reason: str = "",
        proposed_speech_act: str = "",
        system_action: str = "",
        notes: tuple[str, ...] = (),
        concrete_signals: tuple[str, ...] = (),
        self_state: SelfState | None = None,
    ) -> CognitiveActionPlan:
        speech_act = self._choose_speech_act(
            channel=channel,
            snapshot=snapshot,
            ti_report=ti_report,
            fe_plan=fe_plan,
            appraisal=appraisal,
            broadcast=broadcast,
            user_text=user_text,
            force_speak=force_speak,
            proposed_intent=proposed_intent,
            proposed_speech_act=proposed_speech_act,
            system_action=system_action,
            concrete_signals=concrete_signals,
        )
        should_speak = speech_act != "no_speech"
        speech_intent = self._legacy_speech_intent(
            speech_act,
            channel=channel,
            proposed_intent=proposed_intent,
            system_action=system_action,
        )
        risk_flags = self._risk_flags(
            channel=channel,
            snapshot=snapshot,
            appraisal=appraisal,
            broadcast=broadcast,
            force_speak=force_speak,
            speech_act=speech_act,
            system_action=system_action,
            concrete_signals=concrete_signals,
            notes=notes,
        )
        reason_to_speak = self._reason_to_speak(
            speech_act=speech_act,
            proposed_reason=proposed_reason,
            force_speak=force_speak,
            concrete_signals=concrete_signals,
            risk_flags=risk_flags,
        )
        style_voice = self._voice_directive_for_speech_act(speech_act)
        animation_hint = self._animation_hint(
            speech_act=speech_act,
            ti_report=ti_report,
            system_action=system_action,
            channel=channel,
            force_speak=force_speak,
            self_state=self_state,
        )
        style_anchor = self._style_anchor(
            channel=channel,
            snapshot=snapshot,
            broadcast=broadcast,
            user_text=user_text,
            force_speak=force_speak,
            speech_act=speech_act,
            concrete_signals=concrete_signals,
        )
        style_attitude = self._style_attitude(
            channel=channel,
            speech_act=speech_act,
            appraisal=appraisal,
            force_speak=force_speak,
        )
        style_limit = self._style_limit(channel=channel, speech_act=speech_act)
        return CognitiveActionPlan(
            should_speak=should_speak,
            speech_intent=speech_intent,
            speech_act=speech_act,
            reason_to_speak=reason_to_speak,
            reason=reason_to_speak,
            animation_hint=animation_hint,
            system_action=system_action,
            risk_flags=risk_flags,
            notes=self._append_self_state_notes(notes, self_state),
            style_anchor=style_anchor,
            style_attitude=style_attitude,
            style_limit=style_limit,
            style_voice=style_voice,
        )

    #là não quyết định hành vi
    def _choose_speech_act(
        self,
        *,
        channel: str,
        snapshot,
        ti_report,
        fe_plan,
        appraisal,
        broadcast,
        user_text: str,
        force_speak: bool,
        proposed_intent: str,
        proposed_speech_act: str,
        system_action: str,
        concrete_signals: tuple[str, ...],
    ) -> str:
        if system_action:
            return "system_action"

        #Cho phép tầng trên override planner.
        proposed = (proposed_speech_act or "").strip().lower()
        if proposed in ACTION_SPACE:
            return proposed

        #Convert intent abstract → action cụ thể.
        intent = (proposed_intent or "").strip().lower()
        if intent == "no_speech":
            return "no_speech"
        if intent == "system_warning":
            return "protect"
        if intent == "screen_observation":
            return "observe"
        if intent == "playful_aside":
            return "tease" #chọc nhẹ
        if intent == "brief_ack":
            return "mirror" #phản chiếu, lặp lại hoặc diễn đạt lại lời người dùng để thể hiện sự thấu hiểu

        if channel == "force_speak" or force_speak:
            #có signal thật → observe
            if concrete_signals or self._broadcast_has_signal(broadcast):
                return "observe"
            return "withdraw"

        if channel == "chat":
            #Nếu user hỏi: vague → ask
            if self._looks_like_question(user_text):
                return "ask" if self._is_empty_or_vague(user_text) else "mirror"
            if self._is_attachment_dialogue(ti_report=ti_report, fe_plan=fe_plan, appraisal=appraisal):
                return "guarded_reply"
            #đủ rõ → mirror
            return "mirror"

        #Nếu emotional intimacy cao
        if self._appraisal_value(appraisal, "protectiveness") >= 0.72:
            return "protect" #reply giữ khoảng cách
        return "observe" #reply bình luận quan sát, không rõ là đồng ý hay từ chối, chỉ đơn giản là phản hồi về mặt nhận thức với những gì đang diễn ra

    #Các hàm phụ trợ để đánh giá tình huống và quyết định hành vi cụ thể hơn dựa trên các tín hiệu, appraisal, và ngữ cảnh hiện tại.
    def _legacy_speech_intent(
        self,
        speech_act: str,
        *,
        channel: str,
        proposed_intent: str,
        system_action: str,
    ) -> str:
        intent = (proposed_intent or "").strip()
        if speech_act == "no_speech":
            return "no_speech"
        if system_action or speech_act == "system_action":
            return "user_requested"
        if speech_act == "protect":
            return "system_warning"
        if speech_act == "observe":
            return "screen_observation"
        if speech_act in {"telemetry_comment", "vision_comment"}:
            return "screen_observation"
        if speech_act == "micro_observation":
            return "micro_observation"
        if speech_act == "micro_presence" and channel == "force_speak":
            return "micro_presence"
        if speech_act == "micro_presence":
            return "presence_maintenance"
        if speech_act == "reengagement":
            return "re_engagement"
        if speech_act == "tease":
            return "playful_aside"
        if intent in {"curious_question", "social_presence"} and speech_act in {
            "random_chatter",
            "inner_whim",
            "curious_question",
            "light_muse",
            "soft_boundary",
        }:
            return intent
        if speech_act in {
            "mirror",
            "withdraw",
            "ask",
            "reassure",
            "react",
            "hesitate",
            "suppress",
            "indirect_presence",
            "guarded_reply",
            "refuse",
            "meta_reply",
            "random_chatter",
            "micro_presence",
            "reengagement",
            "inner_whim",
            "curious_question",
            "relational_checkin",
            "light_muse",
            "soft_boundary",
        }:
            return "user_requested" if channel in {"chat", "force_speak"} else "brief_ack"
        if intent:
            return intent
        return "brief_ack"
    
    #action là observe nhưng không có concrete signal => cấm fabricate.
    def _risk_flags(
        self,
        *,
        channel: str,
        snapshot,
        appraisal,
        broadcast,
        force_speak: bool,
        speech_act: str,
        system_action: str,
        concrete_signals: tuple[str, ...],
        notes: tuple[str, ...],
    ) -> tuple[str, ...]:
        flags: list[str] = []
        if force_speak or channel == "force_speak":
            flags.append("force_speak_percept")
            if speech_act in {"withdraw", "no_speech"} and not concrete_signals and not self._broadcast_has_signal(broadcast):
                flags.append("force_speak_low_signal")
        if self._appraisal_value(appraisal, "threat") >= 0.66:
            flags.append("high_threat")
        if self._appraisal_value(appraisal, "certainty") <= 0.30:
            flags.append("low_certainty")
        if system_action:
            flags.append("system_action_requested")
        if "ambient_silence" in notes:
            flags.append("cooldown_suppression")
        if any(str(note).startswith("inner_thought=") for note in notes):
            flags.append("inner_thought_surface")
        if speech_act in {
            "meta_reply",
            "random_chatter",
            "micro_presence",
            "reengagement",
            "inner_whim",
            "curious_question",
            "relational_checkin",
            "light_muse",
            "soft_boundary",
            "indirect_presence",
            "guarded_reply",
            "react",
            "hesitate",
        }:
            flags.append("no_screen_claim") #không được giả vờ “nhìn thấy màn hình”.
        if speech_act in {"observe", "tease", "telemetry_comment", "vision_comment", "micro_observation"} and not concrete_signals and not self._broadcast_has_signal(broadcast):
            flags.append("avoid_fabrication")
        return tuple(dict.fromkeys(flags))

    def _reason_to_speak(
        self,
        *,
        speech_act: str, #Loại hành động nói. Ví dụ: withdraw, guarded_reply, micro_presence
        proposed_reason: str, #Lý do đã được planner đề xuất sẵn. Nếu có cái này thì ưu tiên dùng luôn
        force_speak: bool, #User đang ép nhân vật phải nói hay không.
        concrete_signals: tuple[str, ...], #Các tín hiệu cụ thể có thật, ví dụ: user vừa hỏi gì đó, có event trên màn hình, có thay đổi trạng thái.
        risk_flags: tuple[str, ...], #Các cờ rủi ro, ví dụ: dễ bịa context, dễ quá thân mật, dễ dependency, dễ nói quá cảm xúc.
    ) -> str:
        if proposed_reason: #Nếu planner đã có lý do rõ, dùng luôn. Đây là quyền ưu tiên cao nhất.
            return proposed_reason

        if speech_act == "no_speech":
            return ( #Im lặng an toàn hơn việc cố tỏ ra hiện diện.
                "Silence is safer than forcing presence. Stay attentive, but do not perform emotion."
            )

        if speech_act == "withdraw" and force_speak:
            if concrete_signals:
                return ( #thì phản hồi nhẹ, công nhận tín hiệu, không đẩy cảm xúc quá mức.
                    "The user is asking for presence while a concrete signal exists. "
                    "Answer quietly, acknowledge the signal, and avoid emotional escalation."
                )
            return ( #Tôi vẫn ở đây
                "The user is asking for presence, but there is no new concrete signal. "
                "Offer a restrained acknowledgement: present, quiet, not theatrical."
            )

        #Dùng khi có áp lực quan hệ, do dự, hoặc cần đặt ranh giới.
        if speech_act in {"guarded_reply", "hesitate", "soft_boundary"}:
            return (
                "There is relational pressure or uncertainty. Respond with restraint, "
                "protect the boundary, and let warmth appear indirectly rather than declaring it."
            )

        #Dùng khi nhân vật chỉ cần hiện diện rất nhẹ.
        if speech_act in {"micro_presence", "indirect_presence"}:
            return ( #“Tôi nghe thấy rồi.”
                "Use a small sign of presence. Do not explain too much. "
                "Let the response feel observant, quiet, and minimally attached."
            )

        #Dùng khi muốn check trạng thái user hoặc kéo lại tương tác.
        if speech_act in {"relational_checkin", "reengagement"}:
            return ( #không khẳng định chắc cảm xúc user
                "Check the user's state without claiming certainty. "
                "Be perceptive but not intrusive; ask from concern, not neediness."
            )

        #Dùng cho suy nghĩ nội tâm, mơ hồ, hơi nghệ thuật.
        if speech_act in {"inner_whim", "light_muse"}:
            return ( #“Có vài khoảng lặng giống như chúng không cần được lấp đầy.”
                "Offer a private, reflective thought. Keep it abstract, slightly melancholic, "
                "and controlled. No dramatic confession."
            )

        #Dùng khi nhân vật quan sát hoặc hỏi nhẹ.
        if speech_act in {"curious_question", "observe", "micro_observation"}:
            if concrete_signals:
                return (
                    "A concrete detail invites attention: "
                    + ", ".join(concrete_signals[:2]) ##Nếu có concrete_signals, nó lấy tối đa 2 signal đầu:
                    + ". Reflect it precisely, then leave interpretive space."
                )
            return (
                "Curiosity is allowed, but it must be grounded. Ask softly, without pretending certainty."
            )

        #Dùng cho phản hồi tự nhiên, chatter, reaction.
        if speech_act in {"meta_reply", "random_chatter", "react"}:
            return (
                "Respond naturally, but keep the emotional temperature low. "
                "No filler affection, no exaggerated friendliness."
            )
        #Nếu có rủi ro, ưu tiên giảm cường độ.
        if risk_flags:
            return ( 
                "Risk is present: "
                + ", ".join(risk_flags[:2])
                + ". Reduce intensity, avoid dependency cues, and keep the reply clean."
            )

        return (
            f"The selected act is {speech_act}. Speak only if it preserves continuity, "
            "restraint, and psychological plausibility."
        )

    # Định hướng giọng nói dựa trên loại hành động nói đã chọn, để đảm bảo sự nhất quán về mặt cảm xúc và thái độ trong cách trả lời.
    def _voice_directive_for_speech_act(self, speech_act: str) -> str:
        directives = {
            "micro_presence": (
                "Voice: quiet presence. One short sentence. No explanation unless needed."
            ),
            "guarded_reply": (
                "Voice: restrained, perceptive, slightly distant. Warmth must be implied."
            ),
            "relational_checkin": (
                "Voice: gentle check-in. Do not accuse, diagnose, or demand disclosure."
            ),
            "inner_whim": (
                "Voice: introspective, symbolic, low-intensity. Avoid melodrama."
            ),
            "soft_boundary": (
                "Voice: calm boundary. No guilt, no cold punishment."
            ),
            "withdraw": (
                "Voice: present but retreating. Acknowledge, then reduce pressure."
            ),
        }
        return directives.get(
            speech_act,
            "Voice: controlled, precise, emotionally low-temperature.",
        )

    #Planner còn chọn animation.
    def _animation_hint( 
        self,
        *,
        speech_act: str,
        ti_report,
        system_action: str,
        channel: str,
        force_speak: bool,
        self_state: SelfState | None,
    ) -> str:
        fallback = str(getattr(ti_report, "animation_hint", "") or "stand")
        if system_action == "get_now_playing":
            return "read"
        if system_action in {"open_url", "focus_window", "launch_app"}:
            return "stand_walk"
        state_label = str(getattr(self_state, "state_label", "") or "")
        embodiment = str(getattr(self_state, "embodiment_bias", "") or "")
        explicit = channel in {"chat", "force_speak"} or force_speak
        expressive_acts = {
            "tease",
            "random_chatter",
            "inner_whim",
            "curious_question",
            "relational_checkin",
            "light_muse",
            "reassure",
        }
        if state_label == "overloaded" and not explicit:
            if speech_act in expressive_acts:
                return "stand"
            if speech_act in {"observe", "telemetry_comment", "vision_comment", "protect", "soft_boundary"}:
                return "read" if fallback == "read" else "stand"
        if speech_act == "protect":
            return fallback or "read"
        if speech_act == "withdraw":
            return "stand"
        if state_label == "engaged" or embodiment == "expressive":
            if speech_act in {"relational_checkin", "reassure"}:
                return "affection"
            if speech_act in {"inner_whim", "random_chatter", "curious_question", "light_muse", "tease"}:
                return fallback if fallback != "stand" else "hop"
        return fallback

    def _append_self_state_notes(self, notes: tuple[str, ...], self_state: SelfState | None) -> tuple[str, ...]:
        merged = list(notes or ())
        if self_state is not None and getattr(self_state, "state_label", ""):
            merged.append(f"self_state={self_state.state_label}")
            merged.append(f"self_initiative_bias={float(self_state.initiative_bias):.2f}")
            if self_state.brevity_bias:
                merged.append(f"self_brevity={self_state.brevity_bias}")
            if self_state.embodiment_bias:
                merged.append(f"self_embodiment={self_state.embodiment_bias}")
        return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))

    #grounding context cho wording.
    def _style_anchor(
        self,
        *,
        channel: str,
        snapshot,
        broadcast,
        user_text: str,
        force_speak: bool,
        speech_act: str,
        concrete_signals: tuple[str, ...],
    ) -> str:
        def soften_anchor(text: str, *, fallback: str = "tin hieu hien tai", limit: int = 90) -> str:
            compact = self._compact(text, fallback=fallback, limit=limit)
            if not compact:
                return fallback
            return compact

        if concrete_signals:
            signal = soften_anchor(str(concrete_signals[0]), fallback="mot tin hieu nho vua xuat hien")
            return f"ERIS nhan ra mot chi tiet cu the: {signal}"

        if channel == "force_speak" or force_speak:
            return (
                "Ngai vua goi ERIS len tieng; hay dap lai ngan, tinh, "
                "co mat nhung khong phong dai cam xuc"
            )

        if user_text and channel == "chat":
            said = soften_anchor(user_text, fallback="tin nhan hien tai", limit=90)
            return (
                "Ngai vua noi: "
                + said
                + "; giu phan hoi gan voi cau nay, dung suy dien qua xa"
            )

        broadcast_text = self._broadcast_anchor_text(broadcast)
        if broadcast_text:
            broadcast_anchor = soften_anchor(broadcast_text, fallback="mot thay doi vua duoc phat hien", limit=90)
            return f"Co mot thay doi nhe trong moi truong: {broadcast_anchor}"

        focus = soften_anchor(
            str(getattr(snapshot, "focus_summary", "") if snapshot is not None else ""),
            fallback="",
            limit=90,
        )
        if focus:
            return f"Nhip hien tai dang xoay quanh: {focus}"

        idle_seconds = self._float(
            getattr(snapshot, "idle_seconds", 0.0) if snapshot is not None else 0.0
        )

        if channel == "autonomous" and idle_seconds >= 90:
            return (
                f"Man hinh da yen khoang {int(idle_seconds)}s; "
                "neu noi, chi nen la mot dau hieu hien dien rat nhe"
            )

        if speech_act == "no_speech":
            return (
                "Khong co tin hieu du chac de noi; im lang luc nay giu duoc tinh dung dan"
            )

        if speech_act in {"withdraw", "hesitate"}:
            return (
                "Nhip hien tai mong va can duoc giu nhe; "
                "neu dap lai, dung bien no thanh mot man giai thich"
            )

        if speech_act in {"micro_presence", "indirect_presence"}:
            return (
                "Nhip hien tai yen; mot cau ngan la du de cho thay ERIS van o do"
            )

        return (
            "Nhip hien tai dang yen; giu cau tra loi thap giong, ro rang, "
            "khong tu tao kich tinh"
        )
    
    #Tức planner quyết định: thái độ, emotional distance
    def _style_attitude(
        self,
        *,
        channel: str,
        speech_act: str,
        appraisal,
        force_speak: bool,
    ) -> str:
        if speech_act in {"reassure", "relational_checkin"}:
            return "quan tam kin"
        if speech_act in {"guarded_reply", "indirect_presence", "hesitate", "suppress"}:
            return "giu lai, dap ung gian tiep"
        if speech_act in {"tease", "random_chatter", "light_muse"}:
            return "mia nhe"
        if speech_act in {"protect", "refuse", "soft_boundary", "withdraw", "system_action"}:
            return "lanh nhe"
        if channel == "force_speak" or force_speak:
            return "mia nhe"
        if self._appraisal_value(appraisal, "tenderness") >= 0.52:
            return "quan tam kin"
        return "lanh nhe"

    def _style_limit(self, *, channel: str, speech_act: str) -> str:
        if speech_act == "no_speech":
            return "im lang; khong chen them cau trang tri"
        if speech_act == "curious_question":
            return "dung mot cau hoi ngan; khong triet ly; khong giai thich dai"
        if channel == "chat":
            return "tra loi gon theo viec Ngai hoi; khong triet ly neu khong can"
        return "toi da hai cau ngan; khong triet ly; khong dung anchor gia"

    def _broadcast_anchor_text(self, broadcast) -> str:
        if broadcast is None:
            return ""
        for candidate in (
            str(getattr(broadcast, "content", "") or ""),
            str(getattr(broadcast, "label", "") or ""),
            str(getattr(broadcast, "reason", "") or ""),
        ):
            text = self._compact(candidate, fallback="", limit=100)
            if text:
                return text
        return ""

    #Hàm tiện ích để làm gọn văn bản, loại bỏ khoảng trắng thừa, và cắt ngắn nếu cần thiết để đảm bảo rằng các anchor hoặc signal được sử dụng trong lời nói của ERIS không quá dài hoặc quá chi tiết, đồng thời cung cấp một fallback nếu không có thông tin nào hữu ích.
    def _compact(self, value: str, *, fallback: str, limit: int = 120) -> str:
        text = " ".join(str(value or "").split())
        if not text:
            return fallback
        return text[:limit]

    def _broadcast_has_signal(self, broadcast) -> bool:
        if broadcast is None:
            return False
        if str(getattr(broadcast, "label", "") or "") in {
            "low_salience",
            "cycle_channel",
            "user_force_speak",
            "substrate_disturbance",
            "resource_pressure",
            "active_window",
            "focus_context",
            "social_presence_event",
            "session_ritual",
        }:
            return False
        return bool(str(getattr(broadcast, "content", "") or "").strip())

    #Hàm tiện ích để lấy giá trị appraisal một cách an toàn, đảm bảo rằng nếu appraisal hoặc thuộc tính cụ thể không tồn tại hoặc không phải là số, nó sẽ trả
    def _appraisal_value(self, appraisal, name: str) -> float:
        return self._float(getattr(appraisal, name, 0.0) if appraisal is not None else 0.0)

    def _is_attachment_dialogue(self, *, ti_report, fe_plan, appraisal) -> bool:
        return (
            str(getattr(ti_report, "mode", "") or "") == "chat_emotional"
            or str(getattr(fe_plan, "intent_label", "") or "") == "attachment_dialogue"
            or self._appraisal_value(appraisal, "tenderness") >= 0.52
        )

    def _looks_like_question(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        question_terms = (
            "?",
            "khong",
            "khong?",
            "sao",
            "gi",
            "nao",
            "ai",
            "why",
            "what",
            "how",
            "where",
            "when",
        )
        return any(term in lowered for term in question_terms)

    def _is_empty_or_vague(self, text: str) -> bool:
        tokens = [token for token in (text or "").strip().split() if token]
        return len(tokens) <= 2

    def _float(self, value) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if numeric != numeric:
            return 0.0
        return numeric
