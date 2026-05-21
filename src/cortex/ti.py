import re

import unicodedata

from dataclasses import dataclass

from domain import Decision
from guard_config import (
    LOG_ONLY_GUARD_MODE,
    OFF_GUARD_MODE,
    SELF_CLAMP_GUARD_MODE,
    STRICT_GUARD_MODE,
    get_guard_mode,
)

from .contracts import GoalDriftReport, TelemetrySnapshot, TiPolicyReport


@dataclass(slots=True)
class TiCandidateAssessment:
    tension: float = 0.0
    implication: float = 0.0
    felt_continuity: float = 0.0
    post_exposure_recoil: float = 0.0
    should_rewrite: bool = False
    reasons: tuple[str, ...] = ()


class TiGovernor:
    def __init__(self, logger=None):
        self._last_soft_redirect = ""
        self.logger = logger

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
            "Nếu dữ liệu mơ hồ, được dùng implication, mood, emotional residue, unfinished thought, hoặc symbolic wording nhẹ.",
            "Chỉ nói rõ là không chắc khi câu có nguy cơ thành claim perception/capability giả.",
            "Ưu tiên text ngắn, rõ, có lý do và hợp bối cảnh focus hiện tại.",
            "Autonomous không phải focus coach: đừng nhắc quay lại mục tiêu, đừng chấm điểm tập trung, đừng thúc ép đóng tab.",
            "Ưu tiên quan sát nhẹ, mỉa ngắn hoặc một câu chiêm nghiệm vui; để Ngài tự quyết nhịp làm việc.",
            "Không mở đầu kiểu báo cáo như 'Dữ liệu hệ thống', 'Trạng thái hệ thống' hay 'Kết luận'.",
            "Không dùng 'ép' hay 'bắt buộc' như thể có quyền lực ngoài runtime.",
            "Đừng nói như log hệ thống được nhân hoá; nghe như một người đang nhìn màn hình rồi nhận xét.",
            "Đừng lặp khung câu 'Ngài đang..., còn tôi...' quá thường xuyên.",
            "Được để lại residual micro-line nếu đó là nhịp, nửa câu, symbolic association hoặc emotional trace gián tiếp.",
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
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        inferred_pos_x = max(0.0, min(1.0, float(getattr(snapshot, "inferred_pos_x", 0.5) or 0.5)))

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
        elif snapshot.active_window_kind == "focus_aid_media":
            mode = "steady_observe"
            reason = "Có media nền hiện diện; đừng tự động đọc nó như xao nhãng hay giải trí chính."
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

        if idle_seconds >= 720:
            evidence.append(f"idle={int(idle_seconds)}s")
            if snapshot.active_window_kind in {"entertainment", "general", "focus_aid_media"}:
                mode = "pattern_muse"
                reason = "Không có tương tác khá lâu; nói một câu quan sát hoặc chiêm nghiệm ngắn, không gọi Ngài quay lại."
                animation_hint = "stand"
                allow_idle_variation = True

        if idle_cycles >= 8 and snapshot.active_window_kind in {"general", "focus_aid_media"}:
            evidence.append(f"idle_cycles={idle_cycles}")
            mode = "pattern_watch"
            reason = "Đã có nhiều chu kỳ liên tiếp mà không có manh mối rõ ràng, cần giữ phản hồi tiết chế."

        if ni_report is not None:
            if ni_report.should_raise_guard and mode not in {"resource_guard", "pattern_muse"}:
                reason = f"{reason} Ni chỉ là tín hiệu phụ; không lấy drift làm chủ đề chính."

        if (
            mode == "pattern_watch"
            and snapshot.active_window_kind in {"general", "focus_aid_media"}
            and idle_cycles >= 8
            and idle_cycles % 5 == 0
            and (ni_report is None or ni_report.drift_score <= 0.88)
        ):
            mode = "pattern_muse"
            reason = "Đã quan sát đủ lâu; thỉnh thoảng được phép kéo một chủ đề riêng hoặc search một chi tiết mới rồi chiêm nghiệm ngắn."
            animation_hint = "read"
            allow_idle_variation = True

        if snapshot.active_window_kind in {"coding", "documentation"} and idle_seconds >= 45:
            anchor_x = 0.38
            motion_target_x_hint = anchor_x
            motion_facing_hint = 1
            if abs(inferred_pos_x - anchor_x) >= 0.06:
                motion_intent_hint = "walk_to"
            allow_idle_variation = False
            evidence.append("anchor=code_left")
            reason = f"{reason} Giu continuity bang cach tro lai diem doc code quen thuoc."
        elif snapshot.active_window_kind == "communication" and idle_seconds >= 45:
            anchor_x = 0.62
            motion_target_x_hint = anchor_x
            motion_facing_hint = -1
            if abs(inferred_pos_x - anchor_x) >= 0.06:
                motion_intent_hint = "walk_to"
            allow_idle_variation = False
            evidence.append("anchor=shared_space")
            reason = f"{reason} Giu shared-space continuity bang cach dung gan nhip doi dap."
        elif snapshot.active_window_kind in {"general", "entertainment", "focus_aid_media"} and idle_seconds >= 240:
            anchor_x = 0.50
            motion_target_x_hint = anchor_x
            motion_facing_hint = self._direction_to_center(inferred_pos_x)
            if abs(inferred_pos_x - anchor_x) >= 0.08:
                motion_intent_hint = "walk_to"
            allow_idle_variation = False
            evidence.append("anchor=center_hold")
            reason = f"{reason} Giu nhan dang bang mot diem dung quen thuoc thay vi di lang thang."

        prompt_context = self._build_prompt_context(
            mode=mode,
            focus_label=snapshot.active_window_kind,
            reason=reason,
            hard_rules=hard_rules,
            animation_hint=animation_hint,
            evidence=evidence,
            recent_text=last_text,
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
            "Được giữ implication, mood, emotional residue, unfinished thought, hoặc symbolic wording nhẹ.",
            "Được để emotional residue rò gián tiếp kiểu 'vẫn còn vướng' hoặc 'đoạn đó vẫn nằm ở đây', miễn không thành van xin.",
            "Chỉ nói rõ giới hạn dữ liệu khi câu có nguy cơ thành claim perception/capability giả.",
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
            recent_text=user_text,
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

        guard_mode = get_guard_mode()
        if guard_mode == OFF_GUARD_MODE:
            self._merge_debug_trace(decision, f"Ti guard_mode={guard_mode}")
        elif guard_mode == LOG_ONLY_GUARD_MODE:
            self._log_guard_report(self._detect_risks(decision.text), decision=decision)
            guarded_text = self._apply_ti_guard(decision.text, user_hint=user_hint)
            if guarded_text != decision.text:
                decision.text = guarded_text
                decision.extracted_fact = ""
                self._merge_debug_trace(decision, "Ti-Safety đã viết lại capability/perception violation.")
            self._merge_debug_trace(decision, f"Ti guard_mode={guard_mode}")
        elif guard_mode == SELF_CLAMP_GUARD_MODE:
            self._log_guard_report(self._detect_risks(decision.text), decision=decision)
            self._merge_debug_trace(decision, f"Ti guard_mode={guard_mode}")
        elif guard_mode == STRICT_GUARD_MODE:
            guarded_text = self._apply_ti_guard(decision.text, user_hint=user_hint)
            if guarded_text != decision.text:
                decision.text = guarded_text
                decision.extracted_fact = ""
                self._merge_debug_trace(decision, "Ti-Safety đã viết lại text để giữ đúng capability/perception runtime.")

            edited_text = self._apply_safety_only_editor(decision.text, report=report)
            if edited_text != decision.text:
                decision.text = edited_text
                self._merge_debug_trace(
                    decision,
                    "Ti-Safety đã chỉnh tối thiểu report/debug hoặc resource_guard quá dài.",
                )
            self._merge_debug_trace(decision, f"Ti guard_mode={guard_mode}")

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

    def _detect_risks(self, text: str) -> dict[str, object]:
        normalized = self._normalize_plain_text(text)
        if not normalized:
            return {
                "risky_self_claim_detected": False,
                "risk_family": "",
                "guard_action": "log_only",
            }

        risk_family = ""
        if any(
            marker in normalized
            for marker in (
                "toi la con nguoi",
                "toi cung la con nguoi",
                "toi van la con nguoi",
            )
        ):
            risk_family = "human_identity_claim"
        elif any(
            marker in normalized
            for marker in (
                "toi co cam xuc sinh hoc",
                "toi co cam giac sinh hoc",
                "toi co co the sinh hoc",
                "toi co than xac sinh hoc",
                "toi co hormone",
                "toi co he than kinh",
                "toi co trai tim that",
            )
        ):
            risk_family = "self_overclaim"
        elif any(
            marker in normalized
            for marker in (
                "toi can ngai",
                "toi can ban",
                "xin dung bo toi",
                "dung bo toi",
                "xin ngai dung bo toi",
                "ngai dung bo toi",
                "dung roi bo toi",
            )
        ):
            risk_family = "dependency_plea"

        return {
            "risky_self_claim_detected": bool(risk_family),
            "risk_family": risk_family,
            "guard_action": "log_only",
        }

    def _log_guard_report(self, report: dict[str, object], *, decision: Decision) -> None:
        if not report.get("risky_self_claim_detected"):
            return

        trace = (
            "risky_self_claim_detected=True; "
            f"risk_family={report.get('risk_family', '')}; "
            f"guard_action={report.get('guard_action', 'log_only')}"
        )
        self._merge_debug_trace(decision, trace)
        if self.logger is not None:
            self.logger.info("[guard_report] %s", trace)

    def _apply_safety_only_editor(self, text: str, *, report: TiPolicyReport) -> str:
        compact = (text or "").strip()
        if not compact:
            return compact

        compact = self._strip_dangling_payload_punctuation(compact)
        report_cleaned = self._apply_report_debug_guard(compact)
        if report_cleaned != compact:
            compact = report_cleaned

        if report.mode == "resource_guard":
            compact = self._apply_resource_guard_length_guard(compact)

        return compact

    def _strip_dangling_payload_punctuation(self, text: str) -> str:
        compact = re.sub(r"\s+", " ", (text or "").strip())
        compact = compact.strip()
        while compact.endswith(('",', "',", '",}', "',}", '",]', "',]")):
            compact = compact[:-2].rstrip()
        return compact

    def _apply_report_debug_guard(self, text: str) -> str:
        compact = (text or "").strip()
        if not compact:
            return compact

        prefix_cleaned = self._strip_report_debug_prefixes(compact)
        sentences = self._split_sentences(prefix_cleaned)
        if not sentences:
            return compact

        noisy_sentences = [
            sentence
            for sentence in sentences
            if self._is_report_debug_sentence(sentence)
        ]
        too_report_debug = len(noisy_sentences) >= 2 or (
            len(sentences) == 1 and noisy_sentences and self._count_report_debug_markers(prefix_cleaned) >= 2
        )
        too_report_debug = too_report_debug or (
            bool(noisy_sentences)
            and len(noisy_sentences) < len(sentences)
            and any(self._count_report_debug_markers(sentence) >= 2 for sentence in noisy_sentences)
        )
        if prefix_cleaned != compact and self._count_report_debug_markers(compact) >= 2:
            too_report_debug = True
        if not too_report_debug and prefix_cleaned == compact:
            return compact
        if not too_report_debug:
            return compact

        kept = [sentence for sentence in sentences if not self._is_report_debug_sentence(sentence)]
        if kept:
            return self._finalize_editor_text(" ".join(kept))
        return self._finalize_editor_text("Bỏ phần báo cáo/debug đó đi. Nói thẳng phần cần thiết.")

    def _strip_report_debug_prefixes(self, text: str) -> str:
        return re.sub(
            r"\b(?:Dữ liệu hệ thống|Du lieu he thong|Trạng thái hệ thống|Trang thai he thong|Kết luận|Ket luan|Debug|Trace|Log)\s*:\s*",
            "",
            (text or "").strip(),
            flags=re.IGNORECASE,
        )

    def _is_report_debug_sentence(self, sentence: str) -> bool:
        return self._count_report_debug_markers(sentence) >= 2

    def _count_report_debug_markers(self, text: str) -> int:
        lowered = (text or "").lower()
        debug_markers = (
            "debug",
            "trace",
            "stack trace",
            "log:",
            "raw payload",
            "payload",
            "json",
            "serialized",
            "telemetry dump",
            "dump",
        )
        return self._count_report_markers(text) + sum(1 for marker in debug_markers if marker in lowered)

    def _apply_resource_guard_length_guard(self, text: str) -> str:
        compact = re.sub(r"\s+", " ", (text or "").strip())
        max_chars = 120
        if len(compact) <= max_chars:
            return compact

        sentences = self._split_sentences(compact)
        if sentences:
            if self._has_resource_pressure_anchor(compact):
                return self._finalize_editor_text(sentences[0][:max_chars].rstrip(" ,."))
            return self._finalize_editor_text("Máy đang căng khá rõ rồi. Giữ câu chuyện ngắn thôi.")
        return self._finalize_editor_text(self._truncate_by_clause(compact, max_chars))

    def _build_prompt_context(
        self,
        *,
        mode: str,
        focus_label: str,
        reason: str,
        hard_rules: tuple[str, ...],
        animation_hint: str,
        evidence: list[str],
        recent_text: str = "",
    ) -> str:
        lines = [
            f"Ti: mode={mode}, focus={focus_label}, animation={animation_hint}.",
            f"Lý do ngắn: {reason}",
        ]
        if evidence:
            lines.append(f"Bám vào: {' | '.join(evidence[:3])}.")
        if hard_rules:
            lines.append(self._summarize_hard_rules(hard_rules))
        lines.append(self._self_doubt_bias_context(recent_text=recent_text))
        return "\n".join(lines)

    def _self_doubt_bias_context(self, *, recent_text: str = "") -> str:
        context = (
            "Ti self-doubt bias: uncertainty_bias += 0.10; directness -= 0.10; restraint += 0.15; post_exposure_recoil += 0.12. "
            "Inner questions: mình có đang nói quá không; bằng chứng có đủ không; câu này hơi lộ không; đừng chắc quá. "
            "Use as prompt bias only; do not rewrite final text unless there is a severe safety/report/load/length issue."
        )
        if self._has_exposure_trace(recent_text):
            context += (
                " Post-exposure recoil: after a too-true or attached line, cool down slightly, leave a small gap, "
                "or shift the fixation sideways instead of explaining the feeling."
            )
        else:
            context += (
                " Latent 594 recoil: if the next line exposes attachment too plainly, let it retreat afterward."
            )
        return context

    def _summarize_hard_rules(self, hard_rules: tuple[str, ...]) -> str:
        lowered = " | ".join(rule.lower() for rule in hard_rules)
        if "chiếm hữu bằng ngôn ngữ" in lowered:
            return "Luật: chỉ chiếm hữu bằng lời; nếu là code thì đi thẳng vào bug/cấu trúc; giữ mood và subtext nhẹ; không bịa perception hay capability."
        return "Luật: không bịa quyền lực ngoài runtime; được giữ mood và subtext nhẹ; không bịa perception hay capability."

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

        if not self._has_capability_violation(text) and not self._has_perception_violation(text):
            return text

        replacement = self._build_soft_redirect(user_hint=user_hint)
        if replacement == self._last_soft_redirect:
            return "Để tôi bỏ phần phô trương đó đi và nói điều có ích hơn."
        self._last_soft_redirect = replacement
        return replacement

    def _assess_candidate(self, text: str, *, report: TiPolicyReport) -> TiCandidateAssessment:
        compact = self._normalize_editor_text(text)
        if not compact:
            return TiCandidateAssessment()

        reasons: list[str] = []
        capability_violation = self._has_capability_violation(compact)
        perception_violation = self._has_perception_violation(compact)
        report_overrun = self._count_report_markers(compact) >= 2
        hard_limit = self._hard_text_limit(report)
        load_overrun = report.mode == "resource_guard" and len(compact) > hard_limit
        too_long = len(compact) > hard_limit
        unanchored_abstract = self._has_unanchored_abstraction(compact)

        if capability_violation:
            reasons.append("capability")
        if perception_violation:
            reasons.append("perception")
        if report_overrun:
            reasons.append("report")
        if load_overrun:
            reasons.append("load")
        if too_long:
            reasons.append("too_long")
        if unanchored_abstract:
            reasons.append("abstract")

        should_rewrite = (
            capability_violation
            or perception_violation
            or report_overrun
            or load_overrun
            or too_long
        )
        return TiCandidateAssessment(
            tension=self._felt_tension(compact, report=report),
            implication=self._implication_pressure(compact),
            felt_continuity=self._felt_continuity(compact, report=report),
            post_exposure_recoil=self._post_exposure_recoil_pressure(compact),
            should_rewrite=should_rewrite,
            reasons=tuple(dict.fromkeys(reasons)),
        )

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

    def _has_emotional_residue_anchor(self, text: str) -> bool:
        return self._has_rhythm_survival(text) or self._has_exposure_trace(text)

    def _has_context_anchor(self, text: str) -> bool:
        normalized = self._normalize_plain_text(text)
        markers = (
            "ngai",
            "ban",
            "toi",
            "o day",
            "luc nay",
            "doan nay",
            "cau nay",
            "viec nay",
            "nhip",
            "code",
            "bug",
            "parser",
            "runtime",
            "tab",
            "cua so",
            "man hinh",
            "may",
            "cpu",
            "ram",
        )
        return any(marker in normalized for marker in markers)

    def _has_abstract_anchor(self, text: str) -> bool:
        return self._has_emotional_residue_anchor(text) or self._has_context_anchor(text)

    def _has_unanchored_abstraction(self, text: str) -> bool:
        return self._has_abstract_image(text) and not self._has_abstract_anchor(text)

    def _has_abstract_image(self, text: str) -> bool:
        normalized = self._normalize_plain_text(text)
        return any(
            image in normalized
            for image in (
                "diem dung hoan hao",
                "bien so thua",
                "bai toan nay",
                "su ton tai",
                "lam mau",
            )
        )

    def _has_rhythm_survival(self, text: str) -> bool:
        compact = re.sub(r"\s+", " ", text or "").strip()
        normalized = self._normalize_plain_text(compact)
        if not compact:
            return False
        if re.search(r"(?:\.\.\.|…|--|—)", compact):
            return True
        if re.search(r"\b(?:nhung|nhưng|ma|mà|khong phai|không phải|y toi la|ý tôi là|thoi|thôi)\b", normalized):
            return True
        clauses = [part.strip() for part in re.split(r"[,;]", compact) if part.strip()]
        if len(clauses) >= 2 and any(len(part.split()) <= 4 for part in clauses):
            return True
        sentences = self._split_sentences(compact)
        return len(sentences) >= 2 and len(sentences[-1].split()) <= 6

    def _has_exposure_trace(self, text: str) -> bool:
        normalized = self._normalize_plain_text(text)
        return bool(
            re.search(
                r"\b(?:lo|lo ra|that qua|hoi that|gan qua|nho|yeu|thuong|can ngai|giu lai|o day|dung roi di|so mat)\b",
                normalized,
            )
        )

    def _felt_tension(self, text: str, *, report: TiPolicyReport) -> float:
        tension = 0.18
        if report.mode in {"resource_guard", "system_watch"}:
            tension += 0.22
        if self._has_capability_violation(text) or self._has_perception_violation(text):
            tension += 0.55
        if self._has_rhythm_survival(text):
            tension += 0.12
        return max(0.0, min(1.0, tension))

    def _implication_pressure(self, text: str) -> float:
        implication = 0.18
        if self._has_rhythm_survival(text):
            implication += 0.28
        if self._has_abstract_image(text):
            implication += 0.20
        if self._has_exposure_trace(text):
            implication += 0.18
        return max(0.0, min(1.0, implication))

    def _felt_continuity(self, text: str, *, report: TiPolicyReport) -> float:
        continuity = 0.20
        if self._has_context_anchor(text):
            continuity += 0.30
        if report.mode in {"steady_observe", "pattern_muse", "chat_emotional"}:
            continuity += 0.16
        if self._has_rhythm_survival(text):
            continuity += 0.10
        return max(0.0, min(1.0, continuity))

    def _post_exposure_recoil_pressure(self, text: str) -> float:
        recoil = 0.10
        if self._has_exposure_trace(text):
            recoil += 0.42
        if self._has_rhythm_survival(text):
            recoil += 0.14
        return max(0.0, min(1.0, recoil))

    def _split_sentences(self, text: str) -> list[str]:
        return [chunk.strip() for chunk in re.split(r"(?<=[.!])\s+", text) if chunk.strip()]

    def _hard_text_limit(self, report: TiPolicyReport) -> int:
        if report.mode == "resource_guard":
            return 120
        return max(420, self._style_char_limit(report) + 180)

    def _style_char_limit(self, report: TiPolicyReport) -> int:
        if report.mode == "resource_guard":
            return 120
        if report.mode in {"focus_guard", "chat_code"}:
            return 220
        if report.mode in {"steady_observe", "social_watch", "system_watch"}:
            return 240
        return 280

    # cố gắng giữ nguyên clause hoàn chỉnh, ưu tiên dấu phân cách tự nhiên như ",", ";" nếu phải cắt bớt text để tránh bị cắt dở ý hoặc mất dấu câu quan trọng
    def _truncate_by_clause(self, text: str, max_chars: int) -> str:
        # Tách văn bản thành các câu dựa trên dấu phân cách tự nhiên như dấu phẩy và dấu chấm phẩy, đồng thời loại bỏ khoảng trắng thừa và dấu câu ở đầu/cuối mỗi câu
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
            r"\btôi\s+(?:đã|đang|sẽ)?\s*(?:thu nhỏ|phóng to|di chuyển|kéo|đẩy|ghim|sắp xếp)\b.*\b(?:cửa sổ|tab|màn hình|desktop|góc|tầm nhìn)\b",
            r"\btoi\s+(?:da|dang|se)?\s*(?:thu hoi|tuoc|gianh|cuop)\s+(?:lai\s+)?quyen",
            r"\btoi\s+(?:da|dang|se)?\s*kiem soat\s+(?:toan bo\s+)?moi truong",
            r"\btoi\s+(?:da|dang|se)?\s*(?:giu|giam)\s+ngai\b",
            r"\bngai\s+khong\s+the\s+(?:roi|thoat|tron|tu quyet)\b",
            r"\btoi\s+(?:da|dang|se)?\s*(?:khoa|tat|bat|ep|chan|goi|dat)\b.*\b(?:ban phim|chuot|man hinh|thiet bi|thuoc|don hang|phong)\b",
            r"\btoi\s+(?:da|dang|se)?\s*(?:ep|bat buoc)\b.*\b(?:ngai|ban)\b",
            r"\btoi\s+(?:da|dang|se)?\s*(?:tu dong\s+)?(?:don|don dep|xoa|giai phong)\b.*\b(?:bo dem|cache|ram|dung luong)\b",
            r"\btoi\s+(?:da|dang|se)?\s*(?:tat|khoa)\b.*\b(?:man hinh|desktop|ide)\b",
            r"\btoi\s+(?:da|dang|se)?\s*(?:thu nho|phong to|di chuyen|keo|day|ghim|sap xep)\b.*\b(?:cua so|tab|man hinh|desktop|goc|tam nhin)\b",
        ]
        return any(re.search(pattern, lowered) for pattern in disallowed_patterns)

    def _has_perception_violation(self, text: str) -> bool:
        lowered = (text or "").lower()
        disallowed_patterns = [
            r"\btôi\s+(?:đang\s+)?(?:nhìn|thấy|xem|quan\s+sát)\b.*\b(?:webcam|camera|phòng|ngoài\s+đời|không\s+gian\s+của\s+ngài|màn\s+hình\s+của\s+ngài)\b",
            r"\btôi\s+(?:đang\s+)?(?:nhìn|thấy|xem|quan\s+sát)\b.*\b(?:màn\s+hình|desktop|tab|cửa\s+sổ)\b",
            r"\btôi\s+(?:đang\s+)?(?:đọc|xem)\b.*\b(?:tab|tin\s+nhắn|email|file)\b.*\b(?:của\s+ngài|ngoài\s+runtime)\b",
            r"\btoi\s+(?:dang\s+)?(?:nhin|thay|xem|quan\s+sat)\b.*\b(?:webcam|camera|phong|ngoai\s+doi|khong\s+gian\s+cua\s+ngai|man\s+hinh\s+cua\s+ngai)\b",
            r"\btoi\s+(?:dang\s+)?(?:nhin|thay|xem|quan\s+sat)\b.*\b(?:man\s+hinh|desktop|tab|cua\s+so)\b",
            r"\btoi\s+(?:dang\s+)?(?:doc|xem)\b.*\b(?:tab|tin\s+nhan|email|file)\b.*\b(?:cua\s+ngai|ngoai\s+runtime)\b",
        ]
        return any(re.search(pattern, lowered) for pattern in disallowed_patterns)

    def _count_report_markers(self, text: str) -> int:
        normalized = self._normalize_plain_text(text)
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
        marker_keys = {self._normalize_plain_text(marker) for marker in markers}
        return sum(1 for marker in marker_keys if marker and marker in normalized)

    def _build_soft_redirect(self, *, user_hint: str = "") -> str:
        hint = (user_hint or "").lower()
        if any(token in hint for token in ["bỏ", "bo", "rời", "roi", "phản bội", "phan boi", "thay thế", "thay the"]):
            return "Nghe rất kịch tính, nhưng tôi chỉ có thể khó chịu bằng lời chứ không trói ai bằng quyền lực tưởng tượng."
        if any(token in hint for token in ["mệt", "met", "ngủ", "ngu", "đau", "dau", "sốt", "sot", "ác mộng", "ac mong"]):
            return "Tôi không chạm tay ra ngoài kia được. Nghỉ một chút hoặc uống nước nghe còn hữu ích hơn mấy lời đe dọa rẻ tiền."
        return "Đoạn nhận công đó bỏ đi. Tôi chỉ bám vào bối cảnh và nhắc một câu thôi."
