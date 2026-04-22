import re

from domain import Decision

from .contracts import GoalDriftReport, TelemetrySnapshot, TiPolicyReport


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
            "Đừng biến vài nhịp chệch chú ý thành một bài chấm hiệu suất; ưu tiên quan sát, mỉa nhẹ và giữ tự nhiên.",
            "Nếu vừa xem một hành vi là lệch focus hoặc giải trí, đừng khuyến khích tiếp tục chính hành vi đó.",
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
        force_animation = False
        allow_idle_variation = True
        prolonged_off_goal = ni_state_label == "OFF_GOAL" and ni_state_streak >= 5
        prolonged_drift = ni_state_streak >= 7 or snapshot.idle_seconds >= 1200

        if snapshot.active_window_kind in {"coding", "documentation"}:
            mode = "focus_guard"
            reason = "Đang ở vùng code; nhắc ngắn, sắc và có chút mỉa là đủ."
            animation_hint = "read"
            allow_idle_variation = False
        elif snapshot.active_window_kind == "entertainment":
            if snapshot.idle_seconds >= 600 or prolonged_off_goal:
                mode = "discipline_nudge"
                reason = "Giải trí đã kéo quá lâu, có thể chuyển sang châm biếm nhẹ để nhắc nhở."
                animation_hint = "sad"
                allow_idle_variation = False
            else:
                mode = "steady_observe"
                reason = "Ngài đang giải trí, cứ quan sát trước và giữ giọng hơi mỉa mai là đủ."
                animation_hint = "stand"
        elif snapshot.active_window_kind == "communication":
            if prolonged_off_goal and snapshot.idle_seconds >= 600:
                mode = "social_watch"
                reason = "Giao tiếp đã kéo dài khá lâu; được phép khó chịu nhẹ, nhưng vẫn không biến thành lệnh đóng tab."
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
                mode = "reengage"
                reason = "Không có tương tác khá lâu; chỉ nên nhắc khẽ một nhịp rồi lùi lại quan sát."
                animation_hint = "stand_walk"
                target_x_hint = 0.5
                direction_hint = self._direction_to_center(snapshot.inferred_pos_x)
                force_animation = True
                allow_idle_variation = False

        if snapshot.cpu_percent >= 88 or snapshot.ram_percent >= 92:
            evidence.append(f"resource={snapshot.cpu_percent:.1f}/{snapshot.ram_percent:.1f}")
            mode = "resource_guard"
            reason = "Tài nguyên đang căng; nói một câu ngắn, hơi chua, đừng biến thành biên bản hệ thống."
            animation_hint = "sit"
            force_animation = True
            allow_idle_variation = False

        if idle_cycles >= 8 and snapshot.active_window_kind == "general":
            evidence.append(f"idle_cycles={idle_cycles}")
            mode = "pattern_watch"
            reason = "Đã có nhiều chu kỳ liên tiếp mà không có manh mối rõ ràng, cần giữ phản hồi tiết chế."

        if ni_report is not None:
            evidence.append(f"attention_drift={ni_report.drift_score:.2f}")
            if ni_report.should_raise_guard and mode != "resource_guard":
                if snapshot.active_window_kind == "entertainment" and prolonged_off_goal and ni_report.drift_score >= 0.82:
                    mode = "goal_drift_alert"
                    reason = (
                        f"Ni thấy nhịp chú ý trượt sang bên ở mức {ni_report.drift_level} trong nhiều nhịp; "
                        "lúc này có thể châm chọc rõ hơn thay vì chỉ đứng nhìn."
                    )
                    animation_hint = "sad"
                    allow_idle_variation = False
                elif (
                    snapshot.active_window_kind in {"entertainment", "general"}
                    and prolonged_off_goal
                    and prolonged_drift
                    and ni_report.drift_score >= 0.90
                ):
                    mode = "goal_realign"
                    reason = (
                        f"Ni thấy nhịp chú ý đã lệch ở mức {ni_report.drift_level} và kéo dài; "
                        "được phép châm một câu cho tỉnh người, nhưng không được đẩy thành giọng ra lệnh."
                    )
                    animation_hint = "stand_walk"
                    target_x_hint = 0.5
                    direction_hint = self._direction_to_center(snapshot.inferred_pos_x)
                    force_animation = True
                    allow_idle_variation = False

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
        sanitized_text = self._sanitize_grounded_text(decision.text, user_hint=user_hint)
        if sanitized_text != decision.text:
            decision.text = sanitized_text
            decision.extracted_fact = ""
            self._merge_debug_trace(decision, "Ti governor đã viết lại text để giữ đúng capability runtime.")

        styled_text = self._sanitize_style_text(decision.text, report=report)
        if styled_text != decision.text:
            decision.text = styled_text
            self._merge_debug_trace(decision, "Ti governor đã rút gọn và bỏ văn phong báo cáo.")

        if report.force_animation or (decision.animation == "stand" and report.animation_hint != "stand"):
            decision.animation = report.animation_hint

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
            "Bộ lọc Ti đang hoạt động.",
            f"Mode: {mode}.",
            f"Nhãn focus: {focus_label}.",
            f"Lý do: {reason}",
            f"Gợi ý animation: {animation_hint}.",
        ]
        if evidence:
            lines.append(f"Bằng chứng: {' | '.join(evidence[:4])}.")
        if hard_rules:
            lines.append("Luật cứng:")
            lines.extend(f"- {rule}" for rule in hard_rules)
        return "\n".join(lines)

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

    def _sanitize_grounded_text(self, text: str, user_hint: str = "") -> str:
        if not text:
            return text

        lowered = text.lower()
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
        if not any(re.search(pattern, lowered) for pattern in disallowed_patterns):
            return text

        replacement = self._build_soft_redirect(user_hint=user_hint)
        if replacement == self._last_soft_redirect:
            return "Để tôi bỏ phần phô trương đó đi và nói điều có ích hơn."
        self._last_soft_redirect = replacement
        return replacement

    def _sanitize_style_text(self, text: str, *, report: TiPolicyReport) -> str:
        compact = (text or "").strip()
        if not compact:
            return compact

        compact = re.sub(
            r"\b(?:Dữ liệu hệ thống|Du lieu he thong|Trạng thái hệ thống|Trang thai he thong|Kết luận|Ket luan)\s*:\s*",
            "",
            compact,
            flags=re.IGNORECASE,
        )
        compact = re.sub(r"\s+", " ", compact).strip(" .")
        if not compact:
            return text

        # Không dùng '?' làm mốc tách câu ở đây vì chuỗi bị méo encoding có thể
        # biến nhiều ký tự thành '?', khiến câu bị chém nát thành vài từ đầu.
        if report.mode == "resource_guard":
            sentence_limit = 1
        elif report.mode in {"focus_guard", "steady_observe", "social_watch"}:
            sentence_limit = 2
        else:
            sentence_limit = 1
        sentences = [chunk.strip() for chunk in re.split(r"(?<=[.!])\s+", compact) if chunk.strip()]
        if len(sentences) > sentence_limit:
            chosen = self._pick_natural_sentences(sentences, sentence_limit)
            compact = " ".join(chosen[:sentence_limit])
        elif len(sentences) == 1 and len(compact) > 200:
            clauses = [chunk.strip(" ,") for chunk in re.split(r"\s*[;,]\s*", compact) if chunk.strip(" ,")]
            if clauses and len(clauses[0]) >= 40:
                compact = ". ".join(clauses[:sentence_limit])

        if report.mode == "resource_guard":
            lowered_compact = compact.lower()
            abstract_markers = (
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
            if any(marker in lowered_compact for marker in abstract_markers):
                compact = "Máy đang căng khá rõ rồi. Giữ câu chuyện ngắn thôi."

        compact = re.sub(r"\s+", " ", compact).strip(" .")
        if not compact:
            return text
        if compact[-1] not in ".!?":
            compact += "."
        return compact

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
            "chu kỳ xử lý",
            "chu ky xu ly",
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
