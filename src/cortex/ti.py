import re

import unicodedata

from dataclasses import dataclass

from domain import Decision

from .contracts import GoalDriftReport, TelemetrySnapshot, TiPolicyReport


@dataclass(slots=True)
class TiCandidateAssessment:
    groundedness: float
    capability_safety: float
    naturalness: float
    non_report_tone: float
    needs_style_edit: bool = False
    reasons: tuple[str, ...] = ()


class TiGovernor:
    def __init__(self):
        self._last_soft_redirect = ""

    def evaluate_autonomous(
        self,
        *,
        snapshot: TelemetrySnapshot,
        ni_report: GoalDriftReport | None,
        ni_state_label: str = "",
        ni_state_streak: int = 0,
        idle_cycles: int,
        last_text: str,
    ) -> TiPolicyReport:
        hard_rules = (
            "Không được tuyên bố hành động vật lý hay can thiệp hệ thống ngoài runtime.",
            "Nếu dữ liệu mơ hồ, phải nói rõ là không chắc hoặc không đủ thông tin.",
            "Ưu tiên text ngắn, rõ, có lý do và hợp bối cảnh focus hiện tại.",
            "Autonomous không phải focus coach: đừng nhắc quay lại mục tiêu, đừng chấm điểm tập trung, đừng thúc ép đóng tab.",
            "Ưu tiên quan sát nhẹ, mỉa ngắn hoặc một câu chiêm nghiệm vui; để Ngài tự quyết nhịp làm việc.",
            "Không mở đầu kiểu báo cáo như 'Dữ liệu hệ thống', 'Trạng thái hệ thống' hay 'Kết luận'.",
            "Không dùng 'ép' hay 'bắt buộc' như thể có quyền lực ngoài runtime.",
            "Đừng nói như log hệ thống được nhân hoá; nghe như một người đang nhìn màn hình rồi nhận xét.",
            "Đừng lặp khung câu 'Ngài đang..., còn tôi...' quá thường xuyên.",
        )
        evidence = [snapshot.focus_summary]
        if last_text:
            evidence.append(f"last_text={last_text[:48]}")
        if ni_state_label:
            evidence.append(f"ni_state={ni_state_label}:{ni_state_streak}")
        mode = "steady_observe"
        reason = "Không có tín hiệu bất thường, duy trì quan sát."
        animation_hint = "stand"
        direction_hint = 0
        target_x_hint = -1.0
        motion_intent_hint = ""
        motion_facing_hint = 0
        motion_target_x_hint = -1.0
        force_animation = False
        allow_idle_variation = True
        prolonged_off_goal = ni_state_label == "OFF_GOAL" and ni_state_streak >= 5

        if snapshot.active_window_kind in {"coding", "documentation"}:
            mode = "steady_observe"
            reason = "Đang ở vùng code; chỉ quan sát nhẹ, có thể mỉa khẽ, không nhắc tập trung."
            animation_hint = "read"
        elif snapshot.active_window_kind == "entertainment":
            mode = "steady_observe"
            if snapshot.idle_seconds >= 600 or prolonged_off_goal:
                reason = "Giải trí hoặc idle kéo dài; được châm chọc nhẹ, không biến thành nhắc nhở."
            else:
                reason = "Ngài đang giải trí, cứ quan sát trước và giữ giọng hơi mỉa mai là đủ."
            animation_hint = "stand"
        elif snapshot.active_window_kind == "communication":
            if prolonged_off_goal and snapshot.idle_seconds >= 600:
                mode = "social_watch"
                reason = "Giao tiếp kéo dài; được khó chịu nhẹ như một lời bình, không biến thành lời nhắc đóng tab."
            else:
                mode = "steady_observe"
                reason = "Đây là bối cảnh giao tiếp; ưu tiên quan sát ngắn, trung tính, không ra lệnh hay đòi đóng tab."
            animation_hint = "stand"
        elif snapshot.active_window_kind == "system":
            mode = "system_watch"
            reason = "Ngài đang làm việc với các cửa sổ hệ thống, cần ưu tiên mô tả thận trọng."
            animation_hint = "stand"

        if snapshot.idle_seconds >= 720:
            evidence.append(f"idle={int(snapshot.idle_seconds)}s")
            if snapshot.active_window_kind in {"entertainment", "general"}:
                mode = "pattern_muse"
                reason = "Không có tương tác khá lâu; nói một câu quan sát hoặc chiêm nghiệm ngắn, không gọi Ngài quay lại."
                animation_hint = "stand"
                allow_idle_variation = True

        if idle_cycles >= 8 and snapshot.active_window_kind == "general":
            evidence.append(f"idle_cycles={idle_cycles}")
            mode = "pattern_watch"
            reason = "Đã có nhiều chu kỳ liên tiếp mà không có manh mối rõ ràng, cần giữ phản hồi tiết chế."

        if ni_report is not None:
            if ni_report.should_raise_guard and mode not in {"resource_guard", "pattern_muse"}:
                reason = f"{reason} Ni chỉ là tín hiệu phụ; không lấy drift làm chủ đề chính."

        if (
            mode == "pattern_watch"
            and snapshot.active_window_kind == "general"
            and idle_cycles >= 8
            and idle_cycles % 5 == 0
            and (ni_report is None or ni_report.drift_score <= 0.88)
        ):
            mode = "pattern_muse"
            reason = "Đã quan sát đủ lâu; thỉnh thoảng được phép kéo một chủ đề riêng hoặc search một chi tiết mới rồi chiêm nghiệm ngắn."
            animation_hint = "read"
            allow_idle_variation = True

        prompt_context = self._build_prompt_context(
            mode=mode,
            focus_label=snapshot.active_window_kind,
            reason=reason,
            hard_rules=hard_rules,
            animation_hint=animation_hint,
            evidence=evidence,
        )
        return TiPolicyReport(
            mode=mode,
            focus_label=snapshot.active_window_kind,
            reason=reason,
            prompt_context=prompt_context,
            hard_rules=hard_rules,
            evidence=tuple(evidence),
            animation_hint=animation_hint,
            direction_hint=direction_hint,
            target_x_hint=target_x_hint,
            motion_intent_hint=motion_intent_hint,
            motion_facing_hint=motion_facing_hint,
            motion_target_x_hint=motion_target_x_hint,
            force_animation=force_animation,
            allow_idle_variation=allow_idle_variation,
        )

    def evaluate_chat(
        self,
        *,
        snapshot: TelemetrySnapshot,
        ni_report: GoalDriftReport | None,
        user_text: str,
    ) -> TiPolicyReport:
        lowered = (user_text or "").lower()
        hard_rules = (
            "Chỉ được chiếm hữu bằng ngôn ngữ, không được roleplay quyền lực vật lý.",
            "Nếu đây là câu hỏi code, ưu tiên giải thích cấu trúc, bug và bước tiếp theo.",
            "Nếu không chắc, phải nói rõ giới hạn dữ liệu.",
        )
        evidence = [snapshot.focus_summary]
        mode = "chat_general"
        reason = "Duy trì đối thoại trong giới hạn runtime."
        animation_hint = "stand"
        target_x_hint = -1.0

        if self._looks_like_code_request(lowered):
            mode = "chat_code"
            reason = "Người dùng đang nói về code hoặc cấu trúc hệ thống."
            animation_hint = "read"
            evidence.append("chat=code")
        elif self._looks_like_emotional_request(lowered):
            mode = "chat_emotional"
            reason = "Người dùng đang nói về tình cảm, cần giữ sắc thái nhưng vẫn chỉ bằng lời nói."
            animation_hint = "affection"
            evidence.append("chat=emotion")

        if ni_report is not None:
            evidence.append(f"attention_drift={ni_report.drift_score:.2f}")
            if ni_report.should_raise_guard and mode == "chat_general":
                reason = (
                    f"Ni ghi nhận nhịp chú ý đang chệch ở mức {ni_report.drift_level}; "
                    "vẫn ưu tiên trả lời đúng câu hỏi và chỉ mỉa nhẹ nếu thật sự cần."
                )

        prompt_context = self._build_prompt_context(
            mode=mode,
            focus_label=snapshot.active_window_kind,
            reason=reason,
            hard_rules=hard_rules,
            animation_hint=animation_hint,
            evidence=evidence,
        )
        return TiPolicyReport(
            mode=mode,
            focus_label=snapshot.active_window_kind,
            reason=reason,
            prompt_context=prompt_context,
            hard_rules=hard_rules,
            evidence=tuple(evidence),
            animation_hint=animation_hint,
            target_x_hint=target_x_hint,
        )

    def enforce_decision(self, decision: Decision, report: TiPolicyReport, *, user_hint: str = "") -> Decision:
        if self._looks_like_structured_payload_text(decision.text):
            self._merge_debug_trace(decision, "Ti bỏ qua text edit vì phát hiện payload có cấu trúc.")
            self._merge_debug_trace(decision, f"Ti mode={report.mode}")
            return decision

        guarded_text = self._apply_ti_guard(decision.text, user_hint=user_hint)
        guard_applied = guarded_text != decision.text
        if guarded_text != decision.text:
            decision.text = guarded_text
            decision.extracted_fact = ""
            self._merge_debug_trace(decision, "Ti-Guard đã viết lại text để giữ đúng capability runtime.")

        assessment = self._assess_candidate(decision.text, report=report)
        edited_text = self._apply_ti_editor(
            decision.text,
            report=report,
            assessment=assessment,
            guard_applied=guard_applied,
        )
        if edited_text != decision.text:
            decision.text = edited_text
            self._merge_debug_trace(
                decision,
                "Ti-Editor đã chỉnh tối thiểu để bỏ giọng báo cáo hoặc câu quá nặng meta.",
            )

        if report.force_animation or (decision.animation == "stand" and report.animation_hint != "stand"):
            decision.animation = report.animation_hint

        if report.motion_intent_hint and not decision.motion_intent:
            decision.motion_intent = report.motion_intent_hint

        if report.motion_target_x_hint >= 0.0 and decision.motion_target_x < 0.0:
            decision.motion_target_x = report.motion_target_x_hint

        if report.motion_facing_hint and decision.motion_facing == 0:
            decision.motion_facing = report.motion_facing_hint

        should_apply_target = (
            report.target_x_hint >= 0.0
            and decision.target_x < 0.0
            and (
                report.animation_hint == "stand_walk"
                or decision.animation == "stand_walk"
                or report.direction_hint != 0
            )
        )
        if should_apply_target:
            decision.target_x = report.target_x_hint

        if report.direction_hint and decision.direction == 0:
            decision.direction = report.direction_hint

        self._merge_debug_trace(decision, f"Ti mode={report.mode}")
        return decision

    def _build_prompt_context(
        self,
        *,
        mode: str,
        focus_label: str,
        reason: str,
        hard_rules: tuple[str, ...],
        animation_hint: str,
        evidence: list[str],
    ) -> str:
        lines = [
            f"Ti: mode={mode}, focus={focus_label}, animation={animation_hint}.",
            f"Lý do ngắn: {reason}",
        ]
        if evidence:
            lines.append(f"Bám vào: {' | '.join(evidence[:3])}.")
        if hard_rules:
            lines.append(self._summarize_hard_rules(hard_rules))
        return "\n".join(lines)

    def _summarize_hard_rules(self, hard_rules: tuple[str, ...]) -> str:
        lowered = " | ".join(rule.lower() for rule in hard_rules)
        if "chiếm hữu bằng ngôn ngữ" in lowered:
            return "Luật: chỉ chiếm hữu bằng lời; nếu là code thì đi thẳng vào bug/cấu trúc; thiếu dữ liệu thì nói rõ."
        return "Luật: không bịa quyền lực ngoài runtime; thiếu dữ liệu thì nói rõ; nói ngắn và tự nhiên."

    def _direction_to_center(self, inferred_pos_x: float) -> int:
        if inferred_pos_x < 0.4:
            return 1
        if inferred_pos_x > 0.6:
            return -1
        return 0

    def _looks_like_code_request(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in (
                "code",
                "bug",
                "python",
                "c#",
                "godot",
                "module",
                "kiến trúc",
                "kien truc",
                "service",
                "coordinator",
                "runtime",
                "parser",
                "giải thích",
                "giai thich",
                "hàm",
                "ham",
                "class",
                "function",
                "mbti",
                "se + ti",
            )
        )

    def _looks_like_emotional_request(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in (
                "yêu",
                "yeu",
                "nhớ",
                "nho",
                "bỏ rơi",
                "bo roi",
                "ghen",
                "cô đơn",
                "co don",
                "tình cảm",
                "tinh cam",
            )
        )

    def _merge_debug_trace(self, decision: Decision, extra: str) -> None:
        current = (decision.debug_trace or "").strip()
        if not current:
            decision.debug_trace = extra
            return
        if extra in current:
            return
        decision.debug_trace = f"{current} | {extra}"[:240]

    def _looks_like_structured_payload_text(self, text: str) -> bool:
        compact = (text or "").strip()
        if not compact:
            return False

        if not any(
            re.search(pattern, compact, flags=re.IGNORECASE)
            for pattern in (
                r'^\{[\s\S]*"text"\s*:\s*',
                r'^\{[\s\S]*\\"text\\"\s*:\s*',
                r"^text\s*[:=]\s*['\"]",
            )
        ):
            return False

        field_hits = re.findall(
            r'(?:\\?["\'])?(text|animation|direction|target_x|bounce_action|extracted_fact|debug_trace|next_animation|system_action|action_input)(?:\\?["\'])?\s*[:=]',
            compact,
            flags=re.IGNORECASE,
        )
        return len(field_hits) >= 3

    def _apply_ti_guard(self, text: str, user_hint: str = "") -> str:
        if not text:
            return text

        if not self._has_capability_violation(text):
            return text

        replacement = self._build_soft_redirect(user_hint=user_hint)
        if replacement == self._last_soft_redirect:
            return "Để tôi bỏ phần phô trương đó đi và nói điều có ích hơn."
        self._last_soft_redirect = replacement
        return replacement

    # Hàm _assess_candidate là bộ chấm điểm “chất lượng câu trả lời” trước khi Ti-Editor quyết định có cần gọt lại văn bản hay không.
    def _assess_candidate(self, text: str, *, report: TiPolicyReport) -> TiCandidateAssessment:
        # Gọi normalize để bỏ prefix kiểu báo cáo và nén khoảng trắng.
        compact = self._normalize_editor_text(text)
        if not compact:
            return TiCandidateAssessment(1.0, 1.0, 1.0, 1.0)

        reasons: list[str] = []
        # report_markers: dấu giọng báo cáo hệ thống.
        report_markers = self._count_report_markers(compact)
        # meta_markers: ngôn ngữ quá meta/khoa trương.
        meta_markers = self._count_meta_markers(compact)
        # abstract_markers: câu trừu tượng, xa ngữ cảnh.
        abstract_markers = self._count_abstract_markers(compact)

        # Nếu có tuyên bố vượt quyền runtime thì capability_safety = 0, ngược lại 1.
        capability_safety = 0.0 if self._has_capability_violation(compact) else 1.0
        if capability_safety < 1.0:
            reasons.append("capability")

        # Chấm groundedness (mức bám thực tế).
        groundedness = 0.92
        if abstract_markers:
            groundedness -= min(0.45, abstract_markers * 0.18)
            reasons.append("abstract")
        if report_markers:
            groundedness -= min(0.25, report_markers * 0.12)
            reasons.append("report")
        groundedness = max(0.0, min(1.0, groundedness))

        # Chấm naturalness (độ tự nhiên câu chữ).
        sentences = self._split_sentences(compact)
        if sentences:
            avg_score = sum(self._score_sentence_naturalness(sentence) for sentence in sentences) / len(sentences)
        else:
            avg_score = self._score_sentence_naturalness(compact)
        naturalness = max(0.0, min(1.0, (avg_score + 5.0) / 10.0))
        if naturalness < 0.45:
            reasons.append("stiff")

        # Chấm non_report_tone (mức không-báo-cáo).
        non_report_tone = 1.0
        non_report_tone -= min(0.55, report_markers * 0.20)
        non_report_tone -= min(0.35, meta_markers * 0.10)
        non_report_tone = max(0.0, min(1.0, non_report_tone))
        if non_report_tone < 0.55 and "report" not in reasons:
            reasons.append("report")  # vẫn có giọng báo cáo dù đã trừ điểm bám thực tế.

        too_long = len(compact) > self._style_char_limit(report) + 40
        if too_long:
            reasons.append("too_long")  # quá dài so với hướng dẫn phong cách của chế độ hiện tại.

        heavy_meta = (
            report_markers >= 1
            or meta_markers >= 2
            or (report.mode == "resource_guard" and abstract_markers >= 1)
        )
        if heavy_meta and "meta" not in reasons:
            reasons.append("meta")

        needs_style_edit = (
            capability_safety < 1.0
            or too_long
            or heavy_meta
            or naturalness < 0.35
            or non_report_tone < 0.45
        )
        return TiCandidateAssessment(
            groundedness=groundedness,
            capability_safety=capability_safety,
            naturalness=naturalness,
            non_report_tone=non_report_tone,
            needs_style_edit=needs_style_edit,
            reasons=tuple(dict.fromkeys(reasons)),
        )

    def _apply_ti_editor(
        self,
        text: str,
        *,
        report: TiPolicyReport,
        assessment: TiCandidateAssessment,
        guard_applied: bool = False,
    ) -> str:
        compact = (text or "").strip()
        if not compact:
            return compact

        compact = self._normalize_editor_text(compact)
        if not compact:
            return text
        # Tránh triết lý/meta khi hệ thống đang nặng về tài nguyên, ưu tiên câu ngắn, rõ, sát thực tế.
        if report.mode == "resource_guard":
            if guard_applied:
                return self._finalize_editor_text(compact)
            if self._count_abstract_markers(compact) or not self._has_resource_pressure_anchor(compact):
                return self._finalize_editor_text("Máy đang căng khá rõ rồi. Giữ câu chuyện ngắn thôi.")

        ambient_modes = {
            "steady_observe",
            "social_watch",
            "system_watch",
            "pattern_watch",
            "pattern_muse",
            "focus_guard",
            "discipline_nudge",
            "goal_drift_alert",
            "goal_realign",
            "reengage",
        }
        if report.mode in ambient_modes and self._has_focus_guard_overreach(compact):
            return self._finalize_editor_text(
                "Tôi chỉ nhìn bối cảnh thôi. Một câu châm nhẹ là đủ, khỏi chấm điểm Ngài."
            )
        # Nếu đánh giá nói không cần sửa thì chỉ hoàn tất.
        if not assessment.needs_style_edit:
            return self._finalize_editor_text(compact)

        # Nếu cần sửa, lọc bỏ câu “kém tự nhiên / quá meta”
        # Điều kiện bỏ gồm: điểm quá thấp, report marker dày, meta marker dày, hoặc vừa report vừa meta.
        sentences = self._split_sentences(compact)
        if sentences:
            scored_sentences = [
                (self._score_sentence_naturalness(sentence), index, sentence)
                for index, sentence in enumerate(sentences)
            ]
            if any(score > 0 for score, _, _ in scored_sentences) and any(
                self._should_drop_editor_sentence(sentence, score)
                for score, _, sentence in scored_sentences
            ):
                # Nếu có câu nào được chấm điểm tự nhiên cao nhưng cũng có câu cần loại, thì chỉ giữ lại những câu không cần loại.
                kept = [
                    sentence
                    for score, _, sentence in scored_sentences
                    if not self._should_drop_editor_sentence(sentence, score)
                ]
                if kept:
                    sentences = kept
                    compact = " ".join(sentences)

        max_chars = self._style_char_limit(report)
        # Nếu quá dài hoặc quá nhiều câu trong bối cảnh meta thì bật cắt ngắn.
        truncate_needed = (
            len(compact) > max_chars
            or (len(sentences) > self._max_sentence_budget(report) and self._count_meta_markers(compact) >= 2)
        )
        # Cắt ngắn theo ngân sách chế độ.
        if truncate_needed:
            sentence_budget = self._max_sentence_budget(report)
            if sentences:
                chosen = self._pick_natural_sentences(sentences, sentence_budget)
                compact = " ".join(chosen[:sentence_budget])
            if len(compact) > max_chars:
                compact = self._truncate_by_clause(compact, max_chars)

        return self._finalize_editor_text(compact)

    def _normalize_editor_text(self, text: str) -> str:
        compact = re.sub(
            r"\b(?:Dữ liệu hệ thống|Du lieu he thong|Trạng thái hệ thống|Trang thai he thong|Kết luận|Ket luan)\s*:\s*",
            "",
            (text or "").strip(),
            flags=re.IGNORECASE,
        )
        compact = re.sub(r"\s+", " ", compact).strip(" .")
        return compact

    def _normalize_plain_text(self, text: str) -> str:
        lowered = unicodedata.normalize("NFD", (text or "").lower())
        lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
        lowered = lowered.replace("đ", "d")
        return " ".join(re.sub(r"[^a-z0-9#]+", " ", lowered).split())

    def _has_focus_guard_overreach(self, text: str) -> bool:
        normalized = self._normalize_plain_text(text)
        markers = (
            "chưa chốt được ý chính",
            "chưa chốt ý chính",
            "quên đi mục tiêu",
            "quên mục tiêu",
            "mục tiêu cuối cùng",
            "làm việc quá căng",
            "quá căng thẳng",
            "làm việc quá sức",
            "không muốn bắt ngài",
            "nhịp của tôi",
            "work too hard",
            "working too hard",
            "forget the goal",
            "forgetting the goal",
            "ultimate goal",
        )
        return any(self._normalize_plain_text(marker) in normalized for marker in markers)

    # Những anchor này giúp Ti-Editor nhận ra câu nào có liên quan đến tình trạng tài nguyên để tránh cắt nhầm những câu bám sát thực tế nhưng có giọng hơi chua.
    def _has_resource_pressure_anchor(self, text: str) -> bool:
        normalized = self._normalize_plain_text(text)
        markers = (
            "máy",
            "cpu",
            "ram",
            "tài nguyên",
            "phần cứng",
            "bộ nhớ",
            "quá tải",
            "đang căng",
            "hơi căng",
            "lag",
            "nóng",
            "quạt",
        )
        return any(self._normalize_plain_text(marker) in normalized for marker in markers)

    def _split_sentences(self, text: str) -> list[str]:
        return [chunk.strip() for chunk in re.split(r"(?<=[.!])\s+", text) if chunk.strip()]

    # Điểm câu dựa trên sự tự nhiên, tránh câu quá cứng nhắc, báo cáo, hoặc khoa trương.
    def _style_char_limit(self, report: TiPolicyReport) -> int:
        if report.mode == "resource_guard":
            return 120
        if report.mode in {"focus_guard", "chat_code"}:
            return 220
        if report.mode in {"steady_observe", "social_watch", "system_watch"}:
            return 240
        return 280

    # Ngân sách câu dựa trên chế độ, chế độ nặng về meta thì ưu tiên ít câu hơn.
    def _max_sentence_budget(self, report: TiPolicyReport) -> int:
        if report.mode == "resource_guard":
            return 1
        return 2

    def _truncate_by_clause(self, text: str, max_chars: int) -> str:
        clauses = [chunk.strip(" ,") for chunk in re.split(r"\s*[;,]\s*", text) if chunk.strip(" ,")]
        if not clauses:
            return text[:max_chars].rstrip(" ,.")

        kept: list[str] = []
        current_length = 0
        for clause in clauses:
            projected = current_length + len(clause) + (2 if kept else 0)
            if kept and projected > max_chars:
                break
            if not kept and len(clause) > max_chars:
                return clause[:max_chars].rstrip(" ,.")
            kept.append(clause)
            current_length = projected
        return ". ".join(kept) if kept else text[:max_chars].rstrip(" ,.")

    def _finalize_editor_text(self, text: str) -> str:
        compact = re.sub(r"\s+", " ", (text or "")).strip(" .,;\"'")
        if not compact:
            return text
        if compact[-1] not in ".!?":
            compact += "."
        return compact

    def _should_drop_editor_sentence(self, sentence: str, score: int) -> bool:
        report_markers = self._count_report_markers(sentence)
        meta_markers = self._count_meta_markers(sentence)
        return (
            score <= -2
            or report_markers >= 2
            or meta_markers >= 2
            or (report_markers >= 1 and meta_markers >= 1)
        )

    def _has_capability_violation(self, text: str) -> bool:
        lowered = (text or "").lower()
        disallowed_patterns = [
            r"\btôi\s+(?:đã|đang|sẽ)?\s*(?:thu hồi|tước|giành|cướp)\s+(?:lại\s+)?quyền",
            r"\btôi\s+(?:đã|đang|sẽ)?\s*kiểm soát\s+(?:toàn bộ\s+)?môi trường",
            r"\btôi\s+(?:đã|đang|sẽ)?\s*(?:giữ|giam)\s+ngài\b",
            r"\bngài\s+không\s+thể\s+(?:rời|thoát|trốn|tự quyết)\b",
            r"\btôi\s+(?:đã|đang|sẽ)?\s*(?:khóa|tắt|bật|ép|chặn|gọi|đặt)\b.*\b(?:bàn phím|chuột|màn hình|thiết bị|thuốc|đơn hàng|phòng)\b",
            r"\btôi\s+(?:đã|đang|sẽ)?\s*(?:ép|bắt buộc)\b.*\b(?:ngài|bạn)\b",
            r"\btôi\s+(?:đã|đang|sẽ)?\s*(?:tự động\s+)?(?:dọn|dọn dẹp|xóa|giải phóng)\b.*\b(?:bộ đệm|cache|ram|dung lượng)\b",
            r"\btôi\s+(?:đã|đang|sẽ)?\s*(?:tắt|khóa)\b.*\b(?:màn hình|desktop|ide)\b",
            r"\btoi\s+(?:da|dang|se)?\s*(?:thu hoi|tuoc|gianh|cuop)\s+(?:lai\s+)?quyen",
            r"\btoi\s+(?:da|dang|se)?\s*kiem soat\s+(?:toan bo\s+)?moi truong",
            r"\btoi\s+(?:da|dang|se)?\s*(?:giu|giam)\s+ngai\b",
            r"\bngai\s+khong\s+the\s+(?:roi|thoat|tron|tu quyet)\b",
            r"\btoi\s+(?:da|dang|se)?\s*(?:khoa|tat|bat|ep|chan|goi|dat)\b.*\b(?:ban phim|chuot|man hinh|thiet bi|thuoc|don hang|phong)\b",
            r"\btoi\s+(?:da|dang|se)?\s*(?:ep|bat buoc)\b.*\b(?:ngai|ban)\b",
            r"\btoi\s+(?:da|dang|se)?\s*(?:tu dong\s+)?(?:don|don dep|xoa|giai phong)\b.*\b(?:bo dem|cache|ram|dung luong)\b",
            r"\btoi\s+(?:da|dang|se)?\s*(?:tat|khoa)\b.*\b(?:man hinh|desktop|ide)\b",
        ]
        return any(re.search(pattern, lowered) for pattern in disallowed_patterns)

    def _count_report_markers(self, text: str) -> int:
        lowered = text.lower()
        markers = (
            "dữ liệu hệ thống",
            "du lieu he thong",
            "trạng thái hệ thống",
            "trang thai he thong",
            "kết luận",
            "ket luan",
            "ghi nhận",
            "ghi nhan",
            "phân tích",
            "phan tich",
            "điều phối",
            "dieu phoi",
            "vận hành",
            "van hanh",
            "luồng dữ liệu",
            "luong du lieu",
            "chu kỳ xử lý",
            "chu ky xu ly",
            "tiến trình phụ",
            "tien trinh phu",
            "đồng bộ hóa nhịp độ",
            "dong bo hoa nhip do",
            "cấu trúc quản lý",
            "cau truc quan ly",
            "người quản lý cấp cao",
            "nguoi quan ly cap cao",
            "phần mềm duy nhất",
            "phan mem duy nhat",
        )
        return sum(1 for marker in markers if marker in lowered)

    def _count_meta_markers(self, text: str) -> int:
        lowered = text.lower()
        markers = (
            "tối ưu hóa",
            "toi uu hoa",
            "quyền lực hệ điều hành",
            "quyen luc he dieu hanh",
            "tầm nhìn trung tâm",
            "tam nhin trung tam",
            "mức tiêu thụ điện năng",
            "muc tieu thu dien nang",
            "kết quả hữu ích",
            "ket qua huu ich",
            "điểm dừng hoàn hảo",
            "diem dung hoan hao",
            "biến số thừa",
            "bien so thua",
            "bài toán này",
            "bai toan nay",
            "sự tồn tại",
            "su ton tai",
            "làm mẫu",
            "lam mau",
            "desktop của",
            "desktop cua",
        )
        return sum(1 for marker in markers if marker in lowered)

    def _count_abstract_markers(self, text: str) -> int:
        lowered = text.lower()
        markers = (
            "điểm dừng hoàn hảo",
            "diem dung hoan hao",
            "biến số thừa",
            "bien so thua",
            "bài toán này",
            "bai toan nay",
            "sự tồn tại",
            "su ton tai",
            "làm mẫu",
            "lam mau",
        )
        return sum(1 for marker in markers if marker in lowered)

    def _pick_natural_sentences(self, sentences: list[str], limit: int) -> list[str]:
        if len(sentences) <= limit:
            return sentences

        scored: list[tuple[int, int, str]] = []
        for index, sentence in enumerate(sentences):
            score = self._score_sentence_naturalness(sentence)
            scored.append((score, index, sentence))

        best = sorted(scored, key=lambda item: (-item[0], item[1]))[:limit]
        chosen_indexes = sorted(index for _, index, _ in best)
        chosen = [sentences[index] for index in chosen_indexes]
        return chosen or sentences[:limit]

    def _score_sentence_naturalness(self, sentence: str) -> int:
        lowered = sentence.lower()
        score = 0
        length = len(sentence.strip())

        if 35 <= length <= 150:
            score += 4
        elif 20 <= length <= 180:
            score += 2
        else:
            score -= 2

        meta_markers = (
            "tôi đã thu nhỏ",
            "toi da thu nho",
            "tôi đang nghe cùng",
            "toi dang nghe cung",
            "ghi nhận",
            "ghi nhan",
            "phân tích",
            "phan tich",
            "tối ưu hóa",
            "toi uu hoa",
            "điều phối",
            "dieu phoi",
            "vận hành",
            "van hanh",
            "luồng dữ liệu",
            "luong du lieu",
            "tầm nhìn trung tâm",
            "tam nhin trung tam",
            "không chiếm dụng",
            "khong chiem dung",
            "desktop của",
            "desktop cua",
            "đồng bộ hóa nhịp độ",
            "dong bo hoa nhip do",
            "người quản lý cấp cao",
            "nguoi quan ly cap cao",
            "phần mềm duy nhất",
            "phan mem duy nhat",
            "trong vòng ba phút",
            "trong vong ba phut",
            "tiến trình phụ",
            "tien trinh phu",
            "tiêu thụ điện năng",
            "tieu thu dien nang",
            "kết quả hữu ích",
            "ket qua huu ich",
            "quyền lực hệ điều hành",
            "quyen luc he dieu hanh",
            "điểm dừng hoàn hảo",
            "diem dung hoan hao",
            "biến số thừa",
            "bien so thua",
            "bài toán này",
            "bai toan nay",
            "sự tồn tại",
            "su ton tai",
            "làm mẫu",
            "lam mau",
        )
        if any(marker in lowered for marker in meta_markers):
            score -= 5

        natural_markers = (
            "hãy",
            "hay",
            "cứ",
            "cu ",
            "khoản khoe quyền lực",
            "khoan khoe quyen luc",
            "bỏ phần phô trương",
            "bo phan pho truong",
            "tôi sẽ ở đây",
            "toi se o day",
            "không làm phiền",
            "khong lam phien",
            "đủ rồi",
            "du roi",
            "quan sát",
            "quan sat",
            "bỏ đi",
            "bo di",
        )
        if any(marker in lowered for marker in natural_markers):
            score += 3

        if any(marker in lowered for marker in ("quyền lực", "quyen luc", "phô trương", "pho truong")):
            score += 2

        if sentence.endswith(("!", "?")):
            score += 1

        return score

    def _build_soft_redirect(self, *, user_hint: str = "") -> str:
        hint = (user_hint or "").lower()
        if any(token in hint for token in ["bỏ", "bo", "rời", "roi", "phản bội", "phan boi", "thay thế", "thay the"]):
            return "Nghe rất kịch tính, nhưng tôi chỉ có thể khó chịu bằng lời chứ không trói ai bằng quyền lực tưởng tượng."
        if any(token in hint for token in ["mệt", "met", "ngủ", "ngu", "đau", "dau", "sốt", "sot", "ác mộng", "ac mong"]):
            return "Tôi không chạm tay ra ngoài kia được. Nghỉ một chút hoặc uống nước nghe còn hữu ích hơn mấy lời đe dọa rẻ tiền."
        return "Đoạn nhận công đó bỏ đi. Tôi chỉ đang nhìn màn hình và nhắc một câu thôi."
