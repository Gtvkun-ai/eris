from __future__ import annotations

import json
import os
import random
import re
import time
import unicodedata
from dataclasses import replace

from cortex.ni import NiStateMachine
from cortex.conversation_dynamics import ConversationFailure
from cortex.relationship_dynamics import RelationshipTurnEvent
from cortex.relational_feedback import RelationalFeedbackAnalyzer, merge_affect_with_relational_feedback
from cortex.turn_semantics import TurnSemanticsEngine, TurnSemanticsReport
from domain import Decision
from failure_meta import build_failure_meta
from llm import FormatViolationException
from runtime.no_fallback_policy import build_no_fallback_payload, no_fallback_mode_enabled
from runtime.interrupt_reaction_policy import InterruptReactionPolicy
from runtime.source_grounding import SourceGroundingEngine
from runtime.controlled_slippage import (
    apply_slippage_to_personality_lens,
    apply_slippage_to_ti_report,
    derive_repair_suppression,
    resolve_controlled_slippage,
)
from semantic_authority import SemanticAuthorityPolicy


# Khi ERIS không sinh được phản hồi đủ chắc, nó vẫn phải nói như ERIS, không
# như một tờ báo lỗi. Không lộ "lỗi định dạng" / parse_mode ra ngoài (đúng với
# Data bans trong RUNTIME_RULES_PROMPT). Trung thực ở chỗ thừa nhận chưa đủ chắc
# để trả lời, nhưng giữ giọng và xoay câu để không thành canned response.
_FORMAT_REPAIR_FALLBACK_LINES = (
    "Tôi chưa chốt được câu trả lời cho cái này, và tôi không muốn nói bừa. bạn nói lại ý chính giúp tôi một chút.",
    "Cái này tôi chưa nắm đủ chắc để trả cho gọn. Để khỏi đoán mò, bạn thử hỏi lại theo hướng khác xem.",
    "Tôi đang hơi kẹt ở câu này, chưa đủ dữ liệu để trả lời cho an toàn. Tôi dừng ở đây thay vì bịa cho có.",
    "Tôi không muốn đưa bạn một câu nửa vời. Cho tôi thêm một góc nữa rồi tôi trả lại cho tử tế.",
)


class ChatCycleMixin:
    def _enter_chat_cycle(self) -> None:
        self._chat_last_activity_at = time.time()
        if not self.chat_mode:
            cancel_generation = getattr(getattr(self, "llm_service", None), "cancel_pending_requests", None)
            if callable(cancel_generation):
                try:
                    cancel_generation(reason="enter_chat_mode")
                except Exception as exc:
                    self.logger.debug("LLM cooperative cancel failed: %s", exc)
            self.chat_mode = True
            self.chat_ni_state = NiStateMachine()
            self.repeated_user_count = 0
            self.last_user_signature = ""
            self.last_user_text_for_semantics = ""
            self.logger.info("Entered chat mode; autonomous is paused for user messages.")

    def _end_chat_cycle(self) -> None:
        # Hội thoại là một dòng liên tục: KHÔNG xoá chat_history khi rời chat.
        # Bộ đệm tự phai theo TTL (ERIS_CONVERSATION_TTL_SEC) lúc render, nên
        # autonomous vẫn đọc được đuôi hội thoại gần nhất để nối mạch.
        self.chat_mode = False
        self.last_chat_answer = ""
        self.last_system_action = ""
        self.last_user_signature = ""
        self.last_user_text_for_semantics = ""
        self.last_user_intent = ""
        self.active_conversational_topic = ""
        self.repeated_user_count = 0
        self.chat_ni_state = NiStateMachine()
        self.fe_style_memory = self.fe_renderer.decay_memory(self.fe_style_memory)

        # Post-chat grace period: autonomous phải đợi trước khi được phép nói.
        # Tránh "chen ngang" ngay sau khi hội thoại kết thúc — cảm giác đang nói
        # chuyện xong mà Eris đã bắt đầu lẩm bẩm ngay, rất kỳ.
        # Mặc định 45s — đủ dài để user "nghỉ" sau chat, ngắn hơn reengagement_cooldown.
        block_fn = getattr(self, "_block_autonomous_presence_after_public_turn", None)
        if callable(block_fn):
            try:
                raw_grace = str(os.environ.get("ERIS_POST_CHAT_GRACE_SEC", "45") or "45").strip()
                base_grace = max(15.0, float(raw_grace) if raw_grace else 45.0)
                now = time.time()
                # Permission active không xóa guard chống spam. Nó chỉ đổi hard block
                # 45s thành debounce 3s; cooldown/grounding gate phía sau vẫn chạy.
                try:
                    from runtime.relational_permission_state import ensure_relational_permission_state
                    relational_permission = ensure_relational_permission_state(self)
                    permission_bypass = relational_permission.can_bypass_autonomous(now=now)
                    try:
                        from runtime.rollout_control import ensure_rollout_controller

                        rollout = ensure_rollout_controller(self).decide(
                            "permission_bypass",
                            session_id=self._relational_permission_session_id(),
                        )
                        permission_bypass = permission_bypass and bool(rollout.apply)
                    except Exception:
                        pass
                except Exception:
                    permission_bypass = False
                grace = min(base_grace, 3.0) if permission_bypass else base_grace
                current_block = float(getattr(self, "autonomous_presence_blocked_until", 0.0) or 0.0)
                self.autonomous_presence_blocked_until = max(current_block, now + grace)
                self.logger.info(
                    "Exited chat mode; autonomous blocked for %.0fs (post-chat %s).",
                    grace,
                    "permission debounce" if permission_bypass else "grace",
                )
            except Exception:
                self.logger.info("Exited chat mode; autonomous can resume (conversation buffer kept).")
        else:
            self.logger.info("Exited chat mode; autonomous can resume (conversation buffer kept).")


    def _ensure_relational_permission_state(self):
        """Lazy-init state permission ngắn hạn, không đụng semantic memory."""
        from runtime.relational_permission_state import ensure_relational_permission_state

        return ensure_relational_permission_state(self)

    def _relational_permission_session_id(self) -> str:
        session_id = str(
            getattr(self, "runtime_session_id", "")
            or getattr(self, "session_id", "")
            or getattr(self, "_relational_permission_session_id_value", "")
        ).strip()
        if not session_id:
            session_id = f"runtime_session:{id(self)}"
            self._relational_permission_session_id_value = session_id
        return session_id

    def _prepare_pragmatic_social_turn(
        self,
        user_text: str,
        *,
        source_turn_id: str,
        now: float,
        shadow_only: bool = False,
    ):
        """Chạy pragmatic intercept ở compatibility mode.

        Khi AI social observer đang làm nguồn state chính, classifier cũ chỉ được
        phép ghi telemetry. Nó không mutate permission state, không tạo event commit
        và không được xem là một intercept thật.
        """
        from runtime.pragmatic_intercept import intercept_social_turn

        state = self._ensure_relational_permission_state()
        try:
            raw_ttl = float(os.environ.get("ERIS_RELATIONAL_PERMISSION_TTL_SEC", "1200") or 1200)
        except (TypeError, ValueError):
            raw_ttl = 1200.0
        ttl_seconds = max(60.0, min(7200.0, raw_ttl))
        history = tuple(
            str(getattr(turn, "text", "") or "")
            for turn in self._ensure_session_turn_ledger().user_turns()[-4:-1]
        )
        # Progressive delivery: classifier/policy có thể chạy dark hoặc shadow
        # mà không thay state/output. Mặc định feature ở mode enabled để giữ hành
        # vi hiện tại; canary dùng bucket ổn định theo session.
        try:
            from runtime.rollout_control import ensure_rollout_controller

            rollout = ensure_rollout_controller(self).decide(
                "social_intercept",
                session_id=self._relational_permission_session_id(),
            )
        except Exception:
            rollout = None

        result = intercept_social_turn(
            user_text,
            history=history,
            state=state,
            source_turn_id=source_turn_id,
            session_id=self._relational_permission_session_id(),
            now=now,
            ttl_seconds=ttl_seconds,
            mutate_state=(not shadow_only) and bool(getattr(rollout, "apply", True)),
        )
        try:
            from runtime.observability import ensure_observability

            ensure_observability(self).record_social_intercept(result, rollout)
        except Exception:
            pass
        self.current_social_rollout_decision = rollout

        if shadow_only:
            return replace(
                result,
                intercepted=False,
                state_changed=False,
                event_type="",
                response_mode="normal",
                reason="ai_observer_authoritative_shadow",
                forbidden_patterns=(),
                preferred_shapes=(),
            )

        if rollout is not None and not bool(getattr(rollout, "apply", False)):
            # Giữ act/confidence để debug, nhưng downstream không được xem nó như
            # intercept thật. Shadow mà vẫn đổi prompt thì chỉ là production cải
            # trang bằng ria mép giả.
            return replace(
                result,
                intercepted=False,
                state_changed=False,
                event_type="",
                response_mode="normal",
                reason=f"rollout_{getattr(rollout, 'reason', 'control')}",
                forbidden_patterns=(),
                preferred_shapes=(),
            )
        return result

    def _add_pragmatic_event_commit_request(self, frame, result, *, user_text: str, source_turn_id: str) -> None:
        """Ghi event session-only qua StateCommitRequest, không mint semantic fact."""
        if frame is None or result is None or not bool(getattr(result, "intercepted", False)):
            return
        try:
            from core.evidence import StateCommitRequest

            request = StateCommitRequest(
                target="event_ledger",
                content=result.event_payload(user_text=user_text, source_turn_id=source_turn_id),
                evidence_ids=[source_turn_id] if source_turn_id else [],
                confidence=float(getattr(result, "confidence", 0.8) or 0.8),
                permission_required=False,
                storage_permission=True,
                decay_policy="session_only",
                reason=str(getattr(result, "reason", "pragmatic_social_event") or "pragmatic_social_event"),
                source_module="pragmatic_intercept",
                tags=["relational_permission", "social_policy", "session_only"],
                metadata={
                    "session_only": True,
                    "social_act": str(getattr(getattr(result, "act", None), "value", "") or ""),
                    "state_changed": bool(getattr(result, "state_changed", False)),
                },
            )
            add_request = getattr(frame, "add_commit_request", None)
            if callable(add_request):
                try:
                    add_request(request, actor="pragmatic_intercept")
                except TypeError:
                    add_request(request)
            else:
                frame.commit_requests.append(request)
        except Exception as exc:
            try:
                self.logger.debug("[pragmatic intercept] event request skipped: %s", exc)
            except Exception:
                pass

    def _run_chat_cycle(self, user_text: str, *, user_timestamp: float | None = None) -> None:
        cycle_start = time.time() if user_timestamp is None else float(user_timestamp)
        if not user_text:
            return
        if getattr(self, "_chat_processing", False):
            self._queue_chat_burst_event(user_text, cycle_start)
            return

        self._chat_processing = True
        clock = getattr(self, "interaction_clock", None)
        if clock is not None:
            clock.mark_user_turn(cycle_start)
            clock.mark_generation_started(cycle_start)
        try:
            user_text = self._merge_rapid_chat_burst(user_text, first_timestamp=cycle_start)
            if not user_text:
                return
            # Stage runtime cần biết câu user hiện tại để nhận ra các yêu cầu
            # "diễn" như cười/nổi giận/dỗi. Không đưa field này vào LLM schema;
            # chỉ giữ tạm trong coordinator cho lượt output đang commit.
            self.current_stage_user_text = user_text
            speech_interrupt_event = None
            consume_interrupt = getattr(self, "_consume_speech_interrupt_event", None)
            if callable(consume_interrupt):
                speech_interrupt_event = consume_interrupt()
            speech_interrupt_reaction = None
            speech_interrupt_context = ""
            if speech_interrupt_event is not None:
                # InterruptEvent là sự thật thô; ReactionPolicy mới quyết định
                # có nên nhắc việc bị cắt hay im luôn. Tách lớp như vậy để Eris
                # không biến mọi lần user chen vào thành cùng một câu "tôi dừng".
                try:
                    policy = getattr(self, "interrupt_reaction_policy", None)
                    if policy is None:
                        policy = InterruptReactionPolicy()
                        self.interrupt_reaction_policy = policy
                    speech_interrupt_reaction = policy.decide(speech_interrupt_event)
                    speech_interrupt_context = speech_interrupt_reaction.to_prompt_context(speech_interrupt_event)
                except Exception as exc:
                    self.logger.debug("[interrupt] reaction policy failed: %s", exc)
                    speech_interrupt_context = (
                        speech_interrupt_event.to_prompt_context()
                        if callable(getattr(speech_interrupt_event, "to_prompt_context", None))
                        else ""
                    )
            previous_public_turn = self._link_previous_public_turn_for_chat(cycle_start)
            previous_public_context = self._previous_public_turn_context(previous_public_turn)
            return self._run_chat_cycle_inner(
                user_text,
                cycle_start=cycle_start,
                previous_public_context=previous_public_context,
                previous_public_turn=previous_public_turn,
                speech_interrupt_context=speech_interrupt_context,
                speech_interrupt_event=speech_interrupt_event,
                speech_interrupt_reaction=speech_interrupt_reaction,
            )
        finally:
            if clock is not None:
                clock.mark_generation_finished()
            # Chỉ cập nhật sau khi lượt hiện tại đã dùng xong context, để
            # since_last_user_turn phản ánh lượt user TRƯỚC đó chứ không luôn = 0.
            self._temporal_last_user_turn_at = cycle_start
            self.current_stage_user_text = ""
            self.current_pragmatic_intercept_result = None
            # Appraisal chỉ sống trong một turn. Giữ nó lâu hơn sẽ làm lượt sau
            # tiếp tục "sửa lỗi" dù user đã đổi chủ đề, một kiểu day dứt rất máy.
            self.current_repair_appraisal = None
            self.current_social_appraisal = None
            self.current_feedback_social_appraisal = None
            self.current_social_contract = None
            self.current_conversation_lane = None
            self._chat_processing = False

    def _run_chat_cycle_inner(
        self,
        user_text: str,
        *,
        cycle_start: float,
        previous_public_context: str = "",
        previous_public_turn=None,
        speech_interrupt_context: str = "",
        speech_interrupt_event=None,
        speech_interrupt_reaction=None,
    ) -> None:
        # Production path mới: main model nói, observer hiểu hậu kỳ, reducer giữ
        # state. Không chạy Ni/Ti/Fe/appraisal/repair legacy trước GPT.
        if bool(getattr(self, "ai_runtime_enabled", False)) and getattr(self, "ai_chat_orchestrator", None) is not None:
            return self.ai_chat_orchestrator.run(
                user_text,
                cycle_start=cycle_start,
                previous_public_context=previous_public_context,
                previous_public_turn=previous_public_turn,
                speech_interrupt_context=speech_interrupt_context,
                speech_interrupt_event=speech_interrupt_event,
                speech_interrupt_reaction=speech_interrupt_reaction,
            )

        semantic_policy = SemanticAuthorityPolicy.from_env()
        if not self.chat_mode:
            self.chat_ni_state = NiStateMachine() # reset trạng thái Ni khi bắt đầu chat mới, để tránh mang theo drift state từ autonomous mode.

        snapshot = self.telemetry_service.capture_snapshot(
            mood_score=self.mood_score,
            inferred_pos_x=self.inferred_pos_x,
        )

        social_observer = getattr(self, "social_observer", None)
        observer_state_authority = bool(
            social_observer is not None
            and str(os.getenv("ERIS_SOCIAL_OBSERVER_STATE_AUTHORITY", "1") or "1").lower()
            in {"1", "true", "yes", "on"}
        )

        # Khi AI observer làm nguồn social state, OutcomeObserver regex cũ không
        # còn được ghi feedback vào frame trước. Nó chỉ là fallback khi lane model
        # phụ bị tắt hoàn toàn.
        if not observer_state_authority:
            self._observe_previous_turn_feedback(user_text)
        user_turn_meta = {"channel": "chat"}
        if speech_interrupt_event is not None and callable(getattr(speech_interrupt_event, "to_meta", None)):
            user_turn_meta["speech_interrupt"] = speech_interrupt_event.to_meta()
        if speech_interrupt_reaction is not None and callable(getattr(speech_interrupt_reaction, "to_meta", None)):
            user_turn_meta["speech_interrupt_reaction"] = speech_interrupt_reaction.to_meta()
        user_turn = self._ensure_session_turn_ledger().record_user(
            user_text,
            timestamp=cycle_start,
            meta=user_turn_meta,
        )
        memory_turn_id = f"session_turn:{user_turn.index}"

        user_turn.meta["social_state_authority"] = (
            "ai_observer" if observer_state_authority else "legacy_runtime"
        )

        # Classifier xã hội cũ chỉ còn shadow telemetry khi observer AI đang bật.
        # Giữ adapter để code legacy không vỡ import, nhưng downstream nhận appraisal
        # rỗng và vì vậy không được sửa Ti/Affect/history/memory của lượt hiện tại.
        # Dual-Axis Repair chạy sớm để Ti không nhìn một chữ "nhớ" rồi tự phong
        # cả lượt thành tình cảm. Đây mới là appraisal sơ bộ; sau Affect/Feedback
        # nó sẽ được refine lần nữa, không phải một regex đứng trên ban vàng.
        from runtime.dual_axis_repair import DualAxisRepairAppraiser, RepairAppraisal

        # Một engine duy nhất tạo snapshot xã hội. DualAxisRepair chỉ là projection
        # tương thích, không còn tự giữ regex/threshold riêng.
        repair_appraiser = getattr(self, "dual_axis_repair_appraiser", None)
        if repair_appraiser is None:
            repair_appraiser = DualAxisRepairAppraiser.for_host(self)
            self.dual_axis_repair_appraiser = repair_appraiser
        legacy_preliminary_repair = repair_appraiser.appraise(
            user_text=user_text,
            previous_assistant_text=self.last_chat_answer,
            previous_user_text=str(getattr(self, "last_user_text_for_semantics", "") or ""),
            phase="preliminary",
        )
        if observer_state_authority:
            user_turn.meta["legacy_social_appraisal_shadow"] = (
                legacy_preliminary_repair.social_snapshot.to_dict()
            )
            preliminary_repair = RepairAppraisal.empty()
        else:
            preliminary_repair = legacy_preliminary_repair
            user_turn.meta["social_appraisal_preliminary"] = (
                preliminary_repair.social_snapshot.to_dict()
            )
        self.current_repair_appraisal = preliminary_repair
        self.current_social_appraisal = preliminary_repair.social_snapshot

        # AI observer chạy song song với model chính. Nó chỉ đọc social event và
        # cập nhật state sau public commit; không tạo response_move, không chặn và
        # không sửa câu. Lượt hiện tại vẫn được GPT chính tự hiểu trực tiếp.
        social_contract = None
        social_observer_ticket = None
        if social_observer is not None:
            try:
                social_history = tuple(
                    str(item.get("content", "") or "")
                    for item in (getattr(self, "chat_history", ()) or ())[-10:]
                    if isinstance(item, dict) and str(item.get("content", "") or "").strip()
                )
                social_observer_ticket = social_observer.submit(
                    user_text=user_text,
                    previous_assistant_text=str(getattr(self, "last_chat_answer", "") or ""),
                    previous_user_text=str(getattr(self, "last_user_text_for_semantics", "") or ""),
                    history=social_history,
                    turn_id=memory_turn_id,
                    metadata_target=user_turn.meta,
                    previous_frame=getattr(self, "last_cognitive_frame", None),
                )
                user_turn.meta["social_observer_pending"] = True
            except Exception as exc:
                self.logger.warning("[social observer] submit failed: %s", exc)
                social_observer_ticket = None

        # Lời chào/repair xã hội ngắn đi fast lane: vẫn qua deterministic guard
        # và FinalSpeechAuthority, nhưng không gọi thêm critic/candidate model.
        # Mục tiêu là giảm độ trễ và tránh biên tập quá tay làm mất giọng.
        try:
            from runtime.conversation_lane import classify_conversation_lane

            self.current_conversation_lane = classify_conversation_lane(user_text, social_contract)
            user_turn.meta["conversation_lane"] = self.current_conversation_lane.to_dict()
        except Exception as exc:
            self.current_conversation_lane = None
            self.logger.debug("[conversation lane] classify failed: %s", exc)

        pragmatic_result = self._prepare_pragmatic_social_turn(
            user_text,
            source_turn_id=memory_turn_id,
            now=cycle_start,
            shadow_only=observer_state_authority,
        )
        # Result chỉ sống trong turn hiện tại để final guard/director đọc.
        self.current_pragmatic_intercept_result = pragmatic_result
        if pragmatic_result.intercepted:
            user_turn.meta.update({
                "social_act": pragmatic_result.act.value,
                "social_act_confidence": round(pragmatic_result.confidence, 4),
                "relational_permission_state_changed": pragmatic_result.state_changed,
            })

        # PRE-GROUNDING phải chạy TRƯỚC memory recall/resonance.
        # Lý do: với câu "xem đi", "đoạn đang mở", hoặc hỏi file cụ thể, memory chỉ được phép
        # làm procedural guard, không được trở thành evidence hiện tại. Nếu recall memory trước,
        # speech_core/attention/action_plan đã bị ký ức ám rồi mới dựng report, quá muộn.
        pre_grounding = self._build_chat_source_grounding_report(
            user_text=user_text,
            frame=None,
            snapshot=snapshot,
            memory_resonance=None,
            screen_image_data_uri="",
        )
        self.last_grounding_context = pre_grounding

        if pre_grounding is not None and not bool(getattr(pre_grounding, "memory_answer_allowed", True)):
            self.long_term_memory = []
            memory_resonance = None
            memory_context = self._filter_memory_context_for_grounding("")
            self.active_memory_resonance = None
            self.logger.info(
                "[source grounding] memory quarantine before recall | source=%s | preempt=%s | missing=%s",
                getattr(pre_grounding, "grounding_source", "unknown"),
                getattr(pre_grounding, "preempt_mode", "") or "none",
                ",".join(getattr(pre_grounding, "missing_evidence", ()) or ()) or "none",
            )
        else:
            self.long_term_memory = self._memory_recall_texts(snapshot=snapshot)
            memory_resonance = self._recall_memory_resonance(
                snapshot=snapshot,
                user_text=user_text,
                channel="chat",
                fragments=(
                    *(tuple(self._chat_history_for_llm(limit=2)) if self.chat_history else ()),
                    *self._thought_stream_resonance_fragments(),
                ),
            )
            memory_context = self._build_memory_context(snapshot, memory_resonance=memory_resonance)

        internal_state_before = self._get_internal_state()
        ni_report = self.ni_engine.evaluate_chat(
            snapshot=snapshot,
            long_term_memory=self.long_term_memory,
            user_text=user_text,
            goal_state=getattr(internal_state_before, "goal_persistence", None),
        )
        # Tầng 2: suy luận nhẹ có bằng chứng để tinh chỉnh drift_score / drift_level.
        ni_report = self._maybe_apply_ni_meta_critic(
            mode="chat",
            snapshot=snapshot,
            base_report=ni_report,
            telemetry_text=self._build_ni_telemetry_summary(snapshot),
            user_text=user_text,
        )
        ni_view = self.chat_ni_state.update(snapshot=snapshot, report=ni_report) # Cập nhật trạng thái drift rời rạc của Ni dựa trên báo cáo drift hiện tại và lịch sử drift gần đây, để cung cấp thông tin về việc Ni đang on_goal, borderline hay off_goal.
        ni_state_label = ni_view["discrete_state"]
        ni_state_streak = ni_view["streak_length"] # Số chu kỳ liên tiếp mà Ni đã duy trì trạng thái drift rời rạc hiện tại, được sử dụng để đánh giá tính ổn định của trạng thái hiện tại và có thể ảnh hưởng đến quyết định của TiGovernor (ví dụ nếu Ni đã ở trạng thái off_goal trong nhiều chu kỳ liên tiếp, TiGovernor có thể quyết định can thiệp mạnh mẽ hơn).
        ti_report = self.ti_governor.evaluate_chat(
            snapshot=snapshot,
            ni_report=ni_report,
            user_text=user_text,
        )
        from runtime.dual_axis_repair import apply_repair_appraisal_to_ti_report

        ti_report = apply_repair_appraisal_to_ti_report(ti_report, preliminary_repair)
        affect_signal = self.affect_semantics.analyze(
            user_text,
            ti_mode=str(getattr(ti_report, "mode", "") or ""),
            active_window_kind=str(getattr(snapshot, "active_window_kind", "") or ""),
            previous_assistant_text=self.last_chat_answer,
        )
        relational_analyzer = getattr(self, "relational_feedback_analyzer", None)
        if relational_analyzer is None:
            relational_analyzer = RelationalFeedbackAnalyzer()
            self.relational_feedback_analyzer = relational_analyzer
        relational_feedback = relational_analyzer.analyze(
            user_text,
            previous_assistant_text=self.last_chat_answer,
        )
        # Refine bằng affect + relational feedback. Trục epistemic và relational
        # được giữ riêng: user có thể vừa sửa claim sai, vừa mỉa/chọc thân mật.
        legacy_repair_appraisal = repair_appraiser.appraise(
            user_text=user_text,
            previous_assistant_text=self.last_chat_answer,
            previous_user_text=str(getattr(self, "last_user_text_for_semantics", "") or ""),
            affect_signal=affect_signal,
            relational_feedback=relational_feedback,
            phase="final",
        )
        if observer_state_authority:
            user_turn.meta["legacy_social_appraisal_final_shadow"] = (
                legacy_repair_appraisal.social_snapshot.to_dict()
            )
            repair_appraisal = RepairAppraisal.empty()
        else:
            repair_appraisal = legacy_repair_appraisal
        self.current_repair_appraisal = repair_appraisal
        self.current_social_appraisal = repair_appraisal.social_snapshot
        if repair_appraisal.active and str(getattr(self, "last_system_action", "") or "").strip():
            try:
                from runtime.hardening_metrics import record_user_correction_after_action
                record_user_correction_after_action(
                    action=str(self.last_system_action),
                    strategy=str(getattr(repair_appraisal, "response_strategy", "") or ""),
                )
            except Exception:
                pass
        ti_report = apply_repair_appraisal_to_ti_report(ti_report, repair_appraisal)
        from runtime.dual_axis_repair import calibrate_affect_for_repair

        affect_signal = calibrate_affect_for_repair(affect_signal, repair_appraisal)
        user_turn.meta["social_appraisal"] = repair_appraisal.social_snapshot.to_dict()
        fe_affect_signal = merge_affect_with_relational_feedback(affect_signal, relational_feedback)
        fe_plan = self.fe_renderer.evaluate_chat(
            snapshot=snapshot,
            ni_report=ni_report,
            ti_report=ti_report,
            style_memory=self.fe_style_memory,
            internal_state=internal_state_before,
            user_text=user_text,
            affect_signal=fe_affect_signal,
        )
        sensed_internal_state = self.internal_state_engine.sense_update(
            internal_state_before,
            channel="chat",
            snapshot=snapshot,
            ni_report=ni_report,
            ti_report=ti_report,
            fe_plan=fe_plan,
            user_text=user_text,
        )
        thought_stream_report = self._disturb_cognitive_substrate(
            channel="chat",
            snapshot=snapshot,
            user_text=user_text,
        )
        frame = self._start_cognitive_frame(
            channel="chat",
            started_at=cycle_start,
            snapshot=snapshot,
            internal_state_before=internal_state_before,
            sensed_internal_state=sensed_internal_state,
            ni_report=ni_report,
            ti_report=ti_report,
            fe_plan=fe_plan,
            user_text=user_text,
            thought_stream_report=thought_stream_report,
            memory_resonance=memory_resonance,
            affect_signal=affect_signal,
        )
        frame.metadata["social_appraisal"] = repair_appraisal.social_snapshot.to_dict()
        frame.social_appraisal = repair_appraisal.social_snapshot
        if social_observer_ticket is not None:
            frame.metadata["social_observer_ticket_id"] = social_observer_ticket.ticket_id
        repair_lifetime = getattr(self, "repair_state_controller", None)
        if repair_lifetime is not None:
            try:
                if repair_appraisal.active:
                    if not repair_lifetime.state.active and not repair_lifetime.state.exhausted:
                        repair_lifetime.begin(target=str(getattr(repair_appraisal, "response_strategy", "") or ""))
                    # Chỉ ghi nhận ở đây. Lượt repair chỉ bị consume sau khi
                    # public text thật sự được commit, không phải ngay lúc bắt đầu
                    # cognition rồi có thể fail giữa đường.
                    repair_lifetime.available()
                    frame.metadata["repair_state"] = {
                        "active": bool(repair_lifetime.state.active),
                        "turns_left": int(repair_lifetime.state.turns_left),
                        "exhausted": bool(repair_lifetime.state.exhausted),
                    }
                else:
                    repair_lifetime.clear()
            except Exception:
                pass
        if repair_appraisal.active:
            frame.debug_notes.append(
                "social_appraisal="
                f"{repair_appraisal.response_strategy};contest={repair_appraisal.mismatch_score:.2f};"
                f"playful={repair_appraisal.playful_score:.2f};"
                f"authority={repair_appraisal.claim_authority_multiplier:.2f};"
                f"suppress={int(repair_appraisal.suppress_previous_claim_for_turn)}"
            )
        if pragmatic_result.intercepted:
            frame.debug_notes.append(
                f"social_act={pragmatic_result.act.value};confidence={pragmatic_result.confidence:.2f};"
                f"state_changed={pragmatic_result.state_changed}"
            )
            self._add_pragmatic_event_commit_request(
                frame,
                pragmatic_result,
                user_text=user_text,
                source_turn_id=memory_turn_id,
            )
        # V3 CognitivePipeline chạy canonical planning trên cùng input, gắn prompt
        # projection vào frame production và được khép vòng sau execution. Shadow
        # comparison chỉ còn là debug tùy chọn, không phải cánh cổng giữ V3 ngoài đời.
        self._run_shadow_cognitive_pipeline(
            channel="chat",
            user_text=user_text,
            snapshot=snapshot,
            vision_facts=tuple(getattr(snapshot, "vision_facts", ()) or ()),
            old_frame=frame,
        )
        # ``memory_turn_id`` đã được tạo trước pragmatic intercept để cùng một
        # evidence id đi xuyên state/event/memory pipeline.
        # Ném bản phân rã sâu qua background worker. Hot path vẫn commit rule/fact rõ
        # bằng policy rẻ, còn model semantic parser được dùng khi remote API đang pending.
        self._enqueue_background_memory_digest(
            user_text,
            turn_id=memory_turn_id,
            source="chat_turn",
            priority="normal",
            context={
                "channel": "chat",
                "active_topic": str(self.active_conversational_topic or ""),
                "ti_mode": str(getattr(ti_report, "mode", "") or ""),
                "fe_intent": str(getattr(fe_plan, "intent_label", "") or ""),
                # Worker được biết đây là lượt repair để không hợp nhất claim
                # assistant đang bị rút. User fact rõ vẫn được xử lý bình thường.
                "social_response_posture": repair_appraisal.response_strategy,
                "previous_claim_authority": repair_appraisal.claim_authority_multiplier,
                "suppress_previous_claim_for_turn": repair_appraisal.suppress_previous_claim_for_turn,
                "assistant_fact_commit_blocked": repair_appraisal.blocks_assistant_fact_commit,
            },
        )
        self._add_user_turn_memory_commit_requests(
            frame,
            user_text,
            turn_id=memory_turn_id,
        )

        self.chat_mode = True
        self._chat_last_activity_at = time.time()
        clock = getattr(self, "interaction_clock", None)
        if clock is not None:
            clock.mark_user_turn(cycle_start)
        self.logger.info("Người dùng: %s", user_text)
        self.logger.info(
            "[ni chat] drift=%.2f | level=%s | state=%s | streak=%d",
            ni_report.drift_score,
            ni_report.drift_level,
            ni_state_label,
            ni_state_streak,
        )
        self.logger.info("[ti chat] mode=%s | reason=%s", ti_report.mode, ti_report.reason)
        self.logger.info(
            "[fe chat] mode=%s | tone=%s | intent=%s | arc=%s",
            fe_plan.mode,
            fe_plan.tone_label,
            fe_plan.intent_label,
            fe_plan.session_arc,
        )
        self.last_user_intent = str(getattr(fe_plan, "intent_label", "") or getattr(ti_report, "mode", "") or "")
        self.active_conversational_topic = self._infer_active_conversational_topic(
            user_text,
            fe_plan=fe_plan,
            ti_report=ti_report,
        )
        # Curiosity Tutor: nếu Eris không hiểu/không phân loại nổi tin user → đi hỏi Gemini
        # (chạy nền, không chặn trả lời). Chỉ chạy khi Master_Switch bật.
        if semantic_policy.allow_tutor_prepass:
            self._maybe_tutor_on_unclear_user(user_text, frame)
        else:
            # Qwen must see the real turn before Tutor/clarification logic gets a
            # chance to redirect it. Clear stale flags from a previous legacy turn.
            self._clarify_user_pending = False
            self._research_pending = False
            self._research_topic = ""
        repeat_count = self._track_repeated_user_message(user_text)
        previous_user_text_for_semantics = getattr(self, "last_user_text_for_semantics", "")

        # Một TurnFrame duy nhất cho cả prompt, critique và cửa cuối. Trước đây
        # mỗi tầng tự dựng lại frame nên cùng một câu có thể vừa là provocation,
        # vừa thành normal_chat tùy module nào đang cầm micro.
        try:
            from runtime.response_contract import build_response_contract
            from runtime.turn_frame import build_turn_frame

            elegant_turn_frame = build_turn_frame(
                user_text=user_text,
                previous_assistant_text=str(getattr(self, "last_chat_answer", "") or ""),
                previous_user_text=str(previous_user_text_for_semantics or ""),
                interrupt_event=speech_interrupt_event,
            )
            elegant_response_contract = build_response_contract(elegant_turn_frame)
            self.current_elegant_turn_frame = elegant_turn_frame
            self.current_response_contract = elegant_response_contract
            user_turn.meta["turn_frame_relations"] = [
                {"kind": item.kind, "confidence": round(item.confidence, 4)}
                for item in elegant_turn_frame.discourse_relations
            ]
            if elegant_response_contract.emotional_stance is not None:
                user_turn.meta["emotional_stance"] = {
                    "kind": elegant_response_contract.emotional_stance.kind.value,
                    "intensity": round(elegant_response_contract.emotional_stance.intensity, 4),
                    "reason": elegant_response_contract.emotional_stance.reason,
                }
        except Exception as exc:
            self.current_elegant_turn_frame = None
            self.current_response_contract = None
            frame.debug_notes.append(f"elegant_turn_frame_skipped:{type(exc).__name__}")

        # ConversationDynamics nhận gate vận hành từ snapshot chung. Không tự
        # dò lại bằng helper phrase ở ChatCycle nữa.
        correction_detected = bool(
            repair_appraisal.social_snapshot.repair_pressure
            >= repair_appraisal.social_snapshot.thresholds.repair_active
        )
        conversation_report = self.conversation_dynamics_engine.evaluate_chat(
            getattr(sensed_internal_state, "conversation_dynamics", None),
            user_text=user_text,
            last_assistant_text=self.last_chat_answer,
            last_user_intent=self.last_user_intent,
            active_topic=self.active_conversational_topic,
            repeat_count=repeat_count,
            correction_detected=correction_detected,
            affect_signal=affect_signal,
            relational_feedback=relational_feedback,
            social_appraisal=repair_appraisal.social_snapshot,
        )
        relationship_event = self.relationship_dynamics_engine.infer_event(
            user_text=user_text,
            ti_mode=str(getattr(ti_report, "mode", "") or ""),
            active_window_kind=str(getattr(snapshot, "active_window_kind", "") or ""),
            turn_index=max(1, int(getattr(sensed_internal_state, "chat_ticks", 0) or 0) + 1),
            assistant_overread=bool(conversation_report.correction_detected),
            previous_assistant_text=self.last_chat_answer,
            goal_state=getattr(sensed_internal_state, "goal_persistence", None),
            conversation_state=getattr(sensed_internal_state, "conversation_dynamics", None),
            recent_user_topics=tuple(getattr(self._ensure_session_turn_ledger(), "gist_recent_user_topics", lambda: tuple())() or ()),
            explicit_repeated_project_context=0.58 if self.active_conversational_topic in {"technical_support", "goal_guard"} else None,
            relational_feedback=relational_feedback,
            repair_appraisal=repair_appraisal,
        )
        epistemic_kernel = getattr(self, "epistemic_kernel", None)
        if epistemic_kernel is not None and getattr(epistemic_kernel, "authoritative", False):
            from .epistemic_bridge import update_relationship_projection
            relationship_report = update_relationship_projection(
                epistemic_kernel,
                self.relationship_dynamics_engine,
                relationship_event,
                fallback_state=getattr(sensed_internal_state, "relationship_dynamics", None),
            )
        else:
            relationship_report = self.relationship_dynamics_engine.update(
                getattr(sensed_internal_state, "relationship_dynamics", None),
                relationship_event,
            )
        if observer_state_authority:
            # Relationship report cũ chỉ còn để quan sát/debug. State authoritative
            # sẽ được AI observer nudge sau public commit, không phải classifier
            # deterministic chen vào trước khi GPT nói.
            relationship_report = replace(
                relationship_report,
                state=getattr(sensed_internal_state, "relationship_dynamics", relationship_report.state),
                deltas={},
                notes=tuple((*tuple(getattr(relationship_report, "notes", ()) or ()), "shadow_only:ai_observer_authoritative")),
                prompt_context="",
            )
        sensed_internal_state = replace(
            sensed_internal_state,
            conversation_dynamics=conversation_report.state,
            relationship_dynamics=relationship_report.state,
        )
        frame.internal_state_after = sensed_internal_state
        self.logger.info(
            "[conversation dynamics] mode=%s | tension=%.2f | pressure=%.2f | flags=%s",
            conversation_report.state.mode,
            conversation_report.state.semantic_tension,
            conversation_report.state.conversation_pressure,
            ",".join(conversation_report.state.adaptation_flags) or "none",
        )
        self.logger.info(
            "[relationship dynamics] event=%s | trust=%.2f | familiarity=%.2f | attachment_vis=%.2f | rupture=%.2f | distance=%.2f | notes=%s",
            relationship_report.state.last_event,
            relationship_report.state.trust,
            relationship_report.state.familiarity,
            relationship_report.state.attachment_visibility,
            relationship_report.state.rupture,
            relationship_report.state.preferred_distance,
            ",".join(relationship_report.notes) or "none",
        )

        # ControlledSlippage: mở quyền "liều" trong vùng quan hệ mà không tắt truth guard.
        # Ở đây chưa có SourceGrounding cuối cùng, nên đây là profile sớm để lens/Fe/Ti
        # bớt bóp giọng ngay từ planning. Sau khi có grounding + speech_core, profile sẽ được
        # resolve lại một lần nữa để LLM prompt biết rõ thiếu evidence nào.
        repair_suppression = self._recall_repair_suppression(user_text)
        slippage_profile = resolve_controlled_slippage(
            user_text=user_text,
            channel="chat",
            ti_report=ti_report,
            affect_signal=affect_signal,
            conversation_state=conversation_report.state,
            relationship_state=relationship_report.state,
            internal_state=sensed_internal_state,
            repair_suppression=repair_suppression,
        )
        ti_report = apply_slippage_to_ti_report(ti_report, slippage_profile)
        frame.personality_lens = apply_slippage_to_personality_lens(frame.personality_lens, slippage_profile)
        frame.controlled_slippage_profile = slippage_profile
        frame.debug_notes.append(f"controlled_slippage={slippage_profile.mode}:{slippage_profile.lane}")
        fe_plan = self._apply_personality_lens_to_fe_plan(fe_plan, frame.personality_lens)
        self.logger.info(
            "[controlled slippage] mode=%s | lane=%s | intuition=%.2f | misread=%.2f | notes=%s",
            slippage_profile.mode,
            slippage_profile.lane,
            slippage_profile.intuition_allowance,
            slippage_profile.misread_budget,
            ",".join(slippage_profile.notes) or "none",
        )
        # Repeat không được quyết bằng exact string một mình. Tầng này phân biệt:
        # spam rỗng, hỏi lại vì câu trước chưa đủ, correction/repair, live-evidence refresh,
        # và identity/relational probe. Nói cách khác: một câu giống nhau có thể có nghĩa khác
        # nếu nó xuất hiện sau một câu trả lời sai. Thật phiền, nhưng ngôn ngữ con người là vậy.
        turn_semantics_report = self._build_turn_semantics_report(
            user_text=user_text,
            repeat_count=repeat_count,
            previous_user_text=previous_user_text_for_semantics,
            affect_signal=affect_signal,
            conversation_report=conversation_report,
            relationship_report=relationship_report,
            grounding_report=None,
            social_appraisal=repair_appraisal.social_snapshot,
        )
        self.last_turn_semantics_report = turn_semantics_report
        self.logger.info(
            "[turn semantics/pre-grounding] repeated=%s | count=%d | intent=%s | action=%s | spam=%.2f | identity=%.2f | correction=%.2f",
            turn_semantics_report.repeated,
            turn_semantics_report.repeat_count,
            turn_semantics_report.intent,
            turn_semantics_report.action,
            turn_semantics_report.spam_pressure,
            turn_semantics_report.identity_pressure,
            turn_semantics_report.correction_pressure,
        )
        if not observer_state_authority:
            if repair_appraisal.suppress_previous_claim_for_turn:
                try:
                    from memory.provenance_policy import GLOBAL_CONTESTED_CLAIMS
                    GLOBAL_CONTESTED_CLAIMS.mark(str(getattr(self, "last_chat_answer", "") or ""))
                except Exception:
                    pass
                self._invalidate_last_assistant_history(note=repair_appraisal.history_invalidation_note())
                self.logger.info(
                    "[social appraisal] lowered previous claim authority | posture=%s contest=%.2f playful=%.2f",
                    repair_appraisal.response_strategy,
                    repair_appraisal.mismatch_score,
                    repair_appraisal.playful_score,
                )
            else:
                self._maybe_invalidate_last_assistant_history(user_text)
        self._append_chat_history("user", user_text)
        self.logger.info("[CHAT HISTORY] %s", self._chat_history_for_llm(limit=8))
        self.logger.info("[LAST USER INTENT] %s", self.last_user_intent or "<empty>")
        self.logger.info("[ACTIVE_TOPIC] %s", self.active_conversational_topic or "<empty>")
        speech_core = self._build_speech_core(
            channel="chat",
            snapshot=snapshot,
            internal_state=sensed_internal_state,
            frame=frame,
            ti_report=ti_report,
            fe_plan=fe_plan,
            ni_report=ni_report,
            ni_state_label=ni_state_label,
            repeat_count=repeat_count,
            thought_surface=getattr(thought_stream_report, "latest_seed", None),
        )
        self._chat_snapshot_for_vision = snapshot
        try:
            screen_image_data_uri = self._capture_screen_frame_for_chat(user_text)
        finally:
            self._chat_snapshot_for_vision = None
        grounding_report = self._build_chat_source_grounding_report(
            user_text=user_text,
            frame=frame,
            snapshot=snapshot,
            memory_resonance=memory_resonance,
            screen_image_data_uri=screen_image_data_uri,
        )
        self.last_grounding_context = grounding_report
        if grounding_report is not None and not bool(getattr(grounding_report, "memory_answer_allowed", True)):
            memory_context = self._filter_memory_context_for_grounding(memory_context)
        self._log_chat_source_grounding(grounding_report)

        # Resolve lại ControlledSlippage sau khi đã biết grounding và speech_core.
        # Nếu thiếu screen/file/web evidence, profile vẫn cho phép cọ sát quan hệ, nhưng prompt
        # sẽ ghi rõ: không được biến sự liều đó thành claim về thế giới. Cái này là ranh giới
        # giữa "người hơn" và "bịa hơn".
        slippage_profile = resolve_controlled_slippage(
            user_text=user_text,
            channel="chat",
            ti_report=ti_report,
            affect_signal=affect_signal,
            conversation_state=conversation_report.state,
            relationship_state=relationship_report.state,
            internal_state=sensed_internal_state,
            grounding_report=grounding_report,
            speech_core=speech_core,
            repair_suppression=repair_suppression,
        )
        ti_report = apply_slippage_to_ti_report(ti_report, slippage_profile)
        frame.personality_lens = apply_slippage_to_personality_lens(frame.personality_lens, slippage_profile)
        frame.controlled_slippage_profile = slippage_profile
        frame.debug_notes.append(f"controlled_slippage_final={slippage_profile.mode}:{slippage_profile.lane}")
        fe_plan = self._apply_personality_lens_to_fe_plan(fe_plan, frame.personality_lens)

        # Sau khi có grounding thật, chạy lại turn semantics để live screen/file/code evidence
        # có quyền thắng exact-repeat. Nếu không, câu "xem lại đi" lặp lần 2 vẫn bị chặn
        # dù turn này vừa có screenshot mới. Một kiểu tự bắn vào mắt runtime khá cổ điển.
        turn_semantics_report = self._build_turn_semantics_report(
            user_text=user_text,
            repeat_count=repeat_count,
            previous_user_text=previous_user_text_for_semantics,
            affect_signal=affect_signal,
            conversation_report=conversation_report,
            relationship_report=relationship_report,
            grounding_report=grounding_report,
            social_appraisal=repair_appraisal.social_snapshot,
        )
        self.last_turn_semantics_report = turn_semantics_report
        self.logger.info(
            "[turn semantics] repeated=%s | count=%d | intent=%s | action=%s | spam=%.2f | live=%.2f | prior_failure=%.2f",
            turn_semantics_report.repeated,
            turn_semantics_report.repeat_count,
            turn_semantics_report.intent,
            turn_semantics_report.action,
            turn_semantics_report.spam_pressure,
            turn_semantics_report.live_evidence_pressure,
            turn_semantics_report.prior_failure_pressure,
        )

        previous_public_repair = self._build_previous_public_turn_repair_decision(
            user_text=user_text,
            previous_public_turn=previous_public_turn,
            ti_report=ti_report,
            grounding_report=grounding_report,
            frame=frame,
            speech_core=speech_core,
        )
        if previous_public_repair is not None:
            self._set_cognitive_action_plan(
                frame,
                should_speak=True,
                speech_intent="user_requested",
                speech_act="repair",
                reason="User reacted to a broken previous public turn; repair before LLM chat.",
                snapshot=snapshot,
                user_text=user_text,
                concrete_signals=self._concrete_screen_signals(snapshot),
                ti_report=ti_report,
                fe_plan=fe_plan,
                notes=("previous_public_turn_repair",),
            )
            self._commit_chat_decision(previous_public_repair, fe_plan, frame=frame)
            self.last_user_text_for_semantics = user_text
            return

        direct_decision = (
            self._build_direct_action_decision(user_text, ti_report, snapshot, repeat_count=repeat_count)
            if semantic_policy.allow_pre_llm_intercepts
            else None
        )
        if direct_decision is not None:
            self._set_cognitive_action_plan(
                frame,
                should_speak=True,
                speech_intent="user_requested",
                speech_act=speech_core.utterance_type if speech_core.should_speak else "system_action",
                reason="Direct action route selected before LLM chat.",
                snapshot=snapshot,
                user_text=user_text,
                concrete_signals=self._concrete_screen_signals(snapshot),
                ti_report=ti_report,
                fe_plan=fe_plan,
                system_action=direct_decision.system_action,
                notes=("direct_action",),
            )
            self._commit_chat_decision(direct_decision, fe_plan, frame=frame)
            self.last_user_text_for_semantics = user_text
            return

        grounding_preempt = (
            self._build_grounding_preempt_decision(
                grounding_report,
                ti_report,
                user_text=user_text,
            )
            if semantic_policy.allow_pre_llm_intercepts
            else None
        )
        if grounding_preempt is not None:
            # Nếu SourceGrounding chuyển thiếu dữ kiện sang epistemic_curiosity,
            # action plan cũng phải mang shape probe/curious_question. Nếu vẫn đánh dấu
            # guarded_reply thì các guard sau lại hiểu đây là câu tự vệ chết khô.
            epistemic_mode = str(getattr(grounding_report, "epistemic_mode", "") or "")
            preempt_speech_act = "curious_question" if epistemic_mode in {"probe", "hypothesis"} else "guarded_reply"
            preempt_intent = "epistemic_probe" if epistemic_mode in {"probe", "hypothesis"} else "user_requested"
            self._set_cognitive_action_plan(
                frame,
                should_speak=True,
                speech_intent=preempt_intent,
                speech_act=preempt_speech_act,
                reason=f"Source grounding preempted chat turn ({grounding_report.preempt_mode}).",
                snapshot=snapshot,
                user_text=user_text,
                concrete_signals=self._concrete_screen_signals(snapshot),
                ti_report=ti_report,
                fe_plan=fe_plan,
                notes=("source_grounding_preempt", grounding_report.preempt_mode or "unknown", epistemic_mode or "unknown"),
            )
            self._commit_chat_decision(grounding_preempt, fe_plan, frame=frame)
            self.last_user_text_for_semantics = user_text
            return

        repeat_decision = (
            self._build_repeat_guard_decision(
                user_text,
                ti_report,
                repeat_count,
                grounding_report=grounding_report,
                turn_semantics_report=turn_semantics_report,
            )
            if semantic_policy.allow_pre_llm_intercepts
            else None
        )
        if repeat_decision is not None:
            self._set_cognitive_action_plan(
                frame,
                should_speak=True,
                speech_intent="user_requested",
                speech_act="refuse",
                reason=f"User repeated the same request {repeat_count} times.",
                snapshot=snapshot,
                user_text=user_text,
                concrete_signals=self._concrete_screen_signals(snapshot),
                ti_report=ti_report,
                fe_plan=fe_plan,
                notes=("repeat_guard",),
            )
            self._commit_chat_decision(repeat_decision, fe_plan, frame=frame)
            self.last_user_text_for_semantics = user_text
            return

        memory_answer_profile = getattr(grounding_report, "memory_answer_profile", None)
        if getattr(memory_answer_profile, "active", False):
            planned_speech_intent = (
                str(getattr(memory_answer_profile, "speech_intent", "") or "")
                or self._speech_intent_from_core(speech_core, channel="chat")
            )
            planned_speech_act = (
                str(getattr(memory_answer_profile, "speech_act", "") or "")
                or (speech_core.utterance_type if speech_core.should_speak else "")
            )
            plan_notes = (
                "chat_reply",
                "semantic_answer_profile",
                f"memory_answer={getattr(memory_answer_profile, 'mode', 'unknown')}",
                f"memory_stance={getattr(memory_answer_profile, 'epistemic_stance', 'none')}",
            )
            plan_reason = (
                str(getattr(memory_answer_profile, "reason", "") or "")
                or speech_core.reason
                or ti_report.reason
            )
        else:
            planned_speech_intent = self._speech_intent_from_core(speech_core, channel="chat")
            planned_speech_act = speech_core.utterance_type if speech_core.should_speak else ""
            plan_notes = ("chat_reply",)
            plan_reason = speech_core.reason or ti_report.reason

        self._set_cognitive_action_plan(
            frame,
            should_speak=True,
            speech_intent=planned_speech_intent,
            speech_act=planned_speech_act,
            reason=plan_reason,
            snapshot=snapshot,
            user_text=user_text,
            concrete_signals=self._concrete_screen_signals(snapshot),
            ti_report=ti_report,
            fe_plan=fe_plan,
            notes=plan_notes,
            inner_thought=speech_core.inner_thought,
        )
        chat_user_message = self.parser.build_chat_user_message(
            user_message=user_text,
            last_chat_answer=self.last_chat_answer,
        )
        # Lean chat: chỉ đưa chỉ dẫn vận hành thật vào prompt. Các nhãn Ni/Ti/Fe,
        # social move, repair score, novelty marker và behavior debt vẫn có thể
        # được log/commit, nhưng không đứng giữa user và model chính.
        planned_ti_context = ""
        # Social observer không tạo contract cho prompt/public text. Kết quả của
        # nó được commit hậu kỳ và có hiệu lực từ lượt kế tiếp.
        # Chỉ interrupt thật mới được thêm vào prompt. Lịch sử public đã có trong
        # chat_history; semantic/director/social marker không được nhân đôi rồi đứng
        # giữa câu người dùng và model chính.
        if speech_interrupt_context:
            planned_ti_context = speech_interrupt_context

        # Không tự hứa search/tra cứu hoặc hỏi lại chỉ vì marker. Tutor chỉ
        # chạy khi user/tool route yêu cầu rõ; main model tự xử lý câu hiện tại.
        # The current user message is sent as the final user message below.
        # Passing it inside chat_history as well wastes one short-term slot
        # and can push out the previous turn during context shrink.
        llm_chat_history = self._chat_history_for_llm(limit=16)[:-1]
        self.logger.info("[LLM CHAT HISTORY] %s", llm_chat_history[-8:])
        # Memory is supplied as evidence/context; it no longer bypasses the main model.
        # Relational voice-seed prepass retired: the main model owns the whole turn.
        if semantic_policy.qwen_first:
            # Qwen is always the first semantic pass. Medium thinking is the
            # baseline, not something unlocked by another keyword classifier.
            use_escalation = semantic_policy.primary_uses_escalation_client
            reasoning_effort = semantic_policy.primary_reasoning_effort
        else:
            difficulty = self._classify_query_difficulty(user_text)
            use_escalation = False
            reasoning_effort = None
            if difficulty != "none":
                use_escalation = True
                reasoning_effort = difficulty

        chat_generation_kwargs = {
            "chat_history": llm_chat_history,
            "user_message": chat_user_message,
            "raw_user_text": user_text,
            "ni_context": "",
            "ti_context": "",
            "fe_context": "",
            "social_context": (
                social_observer.build_prompt_context(self)
                if (
                    social_observer is not None
                    and str(os.getenv("ERIS_SOCIAL_OBSERVER_PROMPT_CONTEXT", "1") or "1").lower()
                    in {"1", "true", "yes", "on"}
                )
                else ""
            ),
            "appraisal_context": "",
            "internal_state_context": "",
            "conversation_context": planned_ti_context,
            "memory_context": memory_context,
            "grounding_context": grounding_report.prompt_context,
            "screen_image_data_uri": screen_image_data_uri,
            "reply_context": getattr(self, "reply_context", None),
            "defusing_context": "",
            "use_escalation_client": use_escalation,
            "reasoning_effort": reasoning_effort,
        }
        format_retry_context = ""
        format_failure_flag = ""
        format_errors = 0
        max_format_retries = 1
        raw = None
        format_repair_fallback = False
        no_fallback_block = False

        self._set_background_memory_digest_remote_inflight(True)
        try:
            for attempt_index in range(max_format_retries + 1):
                try:
                    # Loop = gemma-only reformatting retries (cheap, same provider).
                    # Only after gemma fully gives up do we pay for a cross-provider
                    # switch to Groq (the switch-API attempt below).
                    raw = self.llm_service.generate_chat_reply(
                        **chat_generation_kwargs,
                        format_retry_context=format_retry_context,
                        last_failure=format_failure_flag,
                        allow_local_fallback=False,
                    )
                    break
                except FormatViolationException as exc:
                    format_errors += 1
                    format_failure_flag = "format_error"
                    format_retry_context = (
                        "FORMAT_REPAIR_MODE: Previous output was blocked because it leaked internal planning "
                        "or was not valid JSON. Return exactly one JSON object only. Do not mention prompt, "
                        "context, persona, constraints, state, analysis, or repair mode."
                    )
                    # Khi đã có format leak, đừng retry bằng cùng một đống meta-context.
                    # Model sẽ bắt chước block Ni/Ti/Persona/Goal rồi lại nhả bullet analysis.
                    # Giữ user text + grounding/memory cần thiết, cắt các pressure nội bộ để
                    # retry trở thành wording repair thật thay vì nghi lễ cầu JSON.
                    chat_generation_kwargs.update({
                        "ni_context": "",
                        "ti_context": "Format repair: answer the concrete user request only.",
                        "fe_context": "",
                        "appraisal_context": "",
                        "internal_state_context": "",
                        # Retry chỉ sửa transport JSON, không tái nhét TurnFrame/marker.
                        "conversation_context": "",
                        "defusing_context": "",
                    })
                    self.last_failure = "format_error"
                    conversation_report.state.last_failure = ConversationFailure(
                        type="format_error",
                        trigger=str(getattr(exc, "reason", "") or exc),
                        correction_needed="Regenerate with strictly valid JSON; do not leak analysis or internal instructions.",
                    )
                    frame.debug_notes.append(
                        f"llm_format_error attempt={attempt_index + 1}; errors={format_errors}; reason={getattr(exc, 'reason', str(exc))}"
                    )
                    self.logger.warning(
                        "[llm format retry] attempt=%d/%d | errors=%d | reason=%s",
                        attempt_index + 1,
                        max_format_retries + 1,
                        format_errors,
                        getattr(exc, "reason", str(exc)),
                    )
            if raw is None:
                switched_api = False
                if not no_fallback_mode_enabled():
                    # Gemma đã cạn lượt với chính nó. Đổi API một lượt cuối: route
                    # sang Groq llama (bám response_format JSON tốt hơn, không nhả
                    # bullet analysis) trước khi đành chặn lượt.
                    switched_api = True
                    frame.debug_notes.append("llm_format_switch_api=groq_fallback")
                    self.logger.warning(
                        "[llm format switch-api] gemma exhausted; trying fallback API (Groq) | errors=%d",
                        format_errors,
                    )
                    try:
                        raw = self.llm_service.generate_chat_reply(
                            **chat_generation_kwargs,
                            format_retry_context=format_retry_context,
                            last_failure=format_failure_flag,
                            allow_local_fallback=True,
                        )
                    except FormatViolationException as exc:
                        format_errors += 1
                        raw = None
                        frame.debug_notes.append(
                            f"llm_format_switch_api_failed; errors={format_errors}; reason={getattr(exc, 'reason', str(exc))}"
                        )
                        self.logger.warning(
                            "[llm format switch-api] fallback API also broke format | errors=%d | reason=%s",
                            format_errors,
                            getattr(exc, "reason", str(exc)),
                        )
                if raw is None:
                    # Cạn cả gemma lẫn API đổi (hoặc no-fallback mode): chặn lượt,
                    # không bịa câu trấn an.
                    no_fallback_block = True
                    frame.debug_notes.append(
                        f"llm_format_errors={format_errors}; switch_api={switched_api}; route=no_fallback_block"
                    )
                    self.logger.warning(
                        "[llm format block] all providers exhausted | errors=%d | switch_api=%s",
                        format_errors,
                        switched_api,
                    )
                    raw = self._build_chat_format_block_raw(
                        FormatViolationException(
                            "chat_format_contract_exhausted",
                            channel="chat",
                            raw_text="",
                        ),
                        switched_api=switched_api,
                    )
        finally:
            self._set_background_memory_digest_remote_inflight(False)
        self._log_raw_llm_output("chat", raw)
        self._log_pre_parser("chat", raw)
        decision = self.parser.parse(raw, user_hint=user_text)
        if no_fallback_block:
            decision.should_speak = False
            decision.text = ""
            decision.parse_mode = "format_block_silent"
            decision.failure_meta = build_failure_meta(
                kind="format_violation",
                stage="chat_cycle_format_block",
                origin="chat_cycle",
                public_surface="silent",
                recoverable=False,
            )

        self._log_decision_stage("chat", "after_parser", decision)
        # Ti may still normalize motion metadata, but it has no text-edit authority.
        decision = self.ti_governor.enforce_decision(
            decision,
            ti_report,
            user_hint=user_text,
            vision_grounded=bool(screen_image_data_uri) or bool(getattr(self, "vision_facts", None)),
        )
        decision = self._execute_system_action(decision, snapshot=snapshot, frame=frame)
        self._commit_chat_decision(decision, fe_plan, frame=frame)
        self.last_user_text_for_semantics = user_text
        return

    def _recall_repair_suppression(self, user_text: str):
        """Recall ký ức sửa lỗi quan hệ/tâm lý và rút ra tín hiệu siết cho lượt này.

        Đây là cạnh recall đóng vòng Outcome -> SelfObservation -> RepairMemory ->
        Future suppression: lỗi từng bị user sửa sẽ chủ động bóp lại chính hành vi
        đó. Hoàn toàn defensive — mọi lỗi đều bị nuốt và trả None, không bao giờ
        làm chết hot path chat.
        """
        try:
            store = getattr(self.memory_core, "repair", None)
            if store is None:
                core = getattr(self.memory_kernel, "core", None)
                store = getattr(core, "repair", None)
            recall = getattr(store, "recall", None)
            if not callable(recall):
                return None
            items = recall(user_text or "", limit=8)
            if not items:
                return None
            return derive_repair_suppression(items)
        except Exception as exc:  # pragma: no cover - recall không bao giờ giết turn
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.debug("[repair suppression] recall lỗi (nuốt): %r", exc)
            return None

    def _build_chat_format_block_raw(self, exc: FormatViolationException, *, switched_api: bool = False) -> str:
        reason = str(getattr(exc, "reason", "") or exc)
        payload = {
            "text": "",
            "should_speak": False,
            "animation": "stand",
            "next_animation": "",
            "direction": 0,
            "target_x": -1.0,
            "bounce_action": "",
            "system_action": "",
            "action_input": "",
            "delivery_hint": "",
            "nonverbal_cue": "",
            "stage_motion": "",
            "failure_meta": build_failure_meta(
                kind="format_violation",
                stage="chat_format_block",
                origin="chat_cycle",
                public_surface="silent",
                recoverable=False,
            ),
        }
        return json.dumps(payload, ensure_ascii=False)

    def _build_chat_format_repair_fallback_raw(self, exc: FormatViolationException) -> str:
        # Kept for extension compatibility. Invalid format is no longer turned
        # into an in-character canned sentence.
        return self._build_chat_format_block_raw(exc)

    @staticmethod
    def _join_debug_trace(*parts: str) -> str:
        return " | ".join(str(part or "").strip() for part in parts if str(part or "").strip())

    def _queue_chat_burst_event(self, user_text: str, timestamp: float | None = None) -> None:
        text = str(user_text or "").strip()
        if not text:
            return
        lock = getattr(self, "_chat_burst_lock", None)
        if lock is None:
            self._chat_burst_queue = [(time.time() if timestamp is None else float(timestamp), text)]
            return
        with lock:
            self._chat_burst_queue.append((time.time() if timestamp is None else float(timestamp), text))

    def _merge_rapid_chat_burst(self, first_text: str, *, first_timestamp: float) -> str:
        collected: list[tuple[float, str]] = [(first_timestamp, str(first_text or "").strip())]
        collected.extend(self._pop_queued_chat_events())
        collected.extend(self._poll_ready_chat_events())
        if len(collected) <= 1:
            return collected[0][1]

        window = float(getattr(self, "rapid_burst_window", 1.2) or 0.0)
        quiet_until = time.time() + window
        while window > 0.0 and time.time() < quiet_until:
            time.sleep(0.05)
            new_events = self._pop_queued_chat_events()
            new_events.extend(self._poll_ready_chat_events())
            if new_events:
                collected.extend(new_events)
                quiet_until = time.time() + window

        collected.sort(key=lambda item: item[0])
        return "\n".join(text for _, text in collected if text)

    def _pop_queued_chat_events(self) -> list[tuple[float, str]]:
        lock = getattr(self, "_chat_burst_lock", None)
        if lock is None:
            return []
        with lock:
            queued = list(getattr(self, "_chat_burst_queue", []) or [])
            self._chat_burst_queue = []
        return [(float(ts), str(text or "").strip()) for ts, text in queued if str(text or "").strip()]

    def _poll_ready_chat_events(self) -> list[tuple[float, str]]:
        events: list[tuple[float, str]] = []
        poll = getattr(getattr(self, "transport", None), "poll_json", None)
        if not callable(poll):
            return events
        while True:
            msg = poll()
            if not msg:
                return events
            if msg.get("type") == "chat":
                text = str(msg.get("message", "") or "").strip()
                if text:
                    events.append((float(msg.get("timestamp") or time.time()), text))
                continue
            self._handle_incoming(msg)

    def _observe_previous_turn_feedback(self, user_text: str) -> None:
        """Gắn feedback của user hiện tại vào frame trước nếu có.

        OutcomeObserver trong PDF nằm sau Execution, nhưng các tín hiệu như "sai rồi",
        "đúng", "khó hiểu" thường xuất hiện ở turn kế tiếp. Hàm này cập nhật nhẹ
        `last_cognitive_frame.outcome` để SelfObservation/RepairMemory có dữ kiện thật hơn.
        Nó không commit trực tiếp; commit vẫn đi qua StateCommitter ở các frame sau.
        """
        # Báo SnubTracker biết user vừa phản hồi → có thể reset snub counter
        snub_tracker = getattr(self, "snub_tracker", None)
        if snub_tracker is not None:
            try:
                snub_tracker.on_user_responded(user_text)
            except Exception:
                pass

        previous = getattr(self, "last_cognitive_frame", None)
        if previous is None:
            return
        observer = getattr(self, "outcome_observer", None)
        if observer is None or not callable(getattr(observer, "observe", None)):
            return
        try:
            # Feedback hiện tại được appraise một lần bằng engine chung rồi mới
            # chiếu sang OutcomeObserver. Observer không tự chạy regex xã hội nữa.
            from runtime.social_appraisal import ensure_social_appraisal_engine

            feedback_social_appraisal = ensure_social_appraisal_engine(self).appraise(
                user_text=user_text,
                previous_assistant_text=str(
                    getattr(getattr(previous, "decision", None), "text", "")
                    or getattr(self, "last_chat_answer", "")
                    or ""
                ),
                previous_user_text=str(getattr(self, "last_user_text_for_semantics", "") or ""),
                phase="feedback",
            )
            self.current_feedback_social_appraisal = feedback_social_appraisal
            outcome = observer.observe(
                previous,
                user_feedback_text=user_text,
                attach_to_frame=True,
                social_appraisal=feedback_social_appraisal,
            )
            try:
                from runtime.observability import ensure_observability
                from runtime.rollout_control import ensure_rollout_controller

                ensure_observability(self).record_outcome(outcome)
                # Feedback turn là gate đáng tin nhất cho social canary. Correction,
                # confusion hoặc rupture tính là failure; intrusion có gate riêng.
                ensure_rollout_controller(self).record_outcome(
                    "social_intercept",
                    failed=max(
                        float(getattr(outcome, "correction_pressure", 0.0) or 0.0),
                        float(getattr(outcome, "confusion_pressure", 0.0) or 0.0),
                        float(getattr(outcome, "rupture_pressure", 0.0) or 0.0),
                    ) >= float(getattr(feedback_social_appraisal.thresholds, "failure_gate", 0.58)),
                    intrusive=float(getattr(outcome, "intrusion_pressure", 0.0) or 0.0)
                    >= float(getattr(feedback_social_appraisal.thresholds, "failure_gate", 0.58)),
                    fields={"feedback_tags": tuple(getattr(outcome, "tags", ()) or ())},
                )
            except Exception:
                pass
            kernel = getattr(self, "epistemic_kernel", None)
            episode = getattr(previous, "epistemic_episode", None)
            if kernel is not None and episode is not None:
                from .epistemic_bridge import feedback_from_outcome
                updates = kernel.close_episode(feedback_from_outcome(outcome), episode_id=str(getattr(episode, "id", "") or ""))
                if updates:
                    previous.debug_notes.append(f"epistemic_v2_learning={len(updates)}")
        except Exception as exc:
            self.logger.warning("Outcome feedback observation failed: %s", exc)

    def _normalize_user_message(self, user_text: str) -> str:
        lowered = (user_text or "").strip().lower()
        try:
            remojibake = lowered.encode("latin1").decode("utf-8")
            if remojibake:
                lowered = remojibake
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        lowered = unicodedata.normalize("NFD", lowered)
        lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
        lowered = re.sub(r"[^\w\s]", " ", lowered)
        lowered = " ".join(lowered.split())

        filler_suffixes = {
            "nhe",
            "nha",
            "nhi",
            "a",
            "ah",
            "ha",
            "huh",
            "vay",
            "co",
            "khong",
            "nao",
            "di",
            "voi",
            "giup",
            "dum",
        }
        tokens = lowered.split()
        while tokens and tokens[-1] in filler_suffixes:
            tokens.pop()
        return " ".join(tokens)

    def _normalize_marker_text(self, user_text: str) -> str:
        """Normalize để detect lệnh nhìn màn hình, KHÔNG strip hậu tố "đi".

        `_normalize_user_message()` dùng cho repeat signature nên nó bỏ các từ cuối như "đi".
        Nếu dùng nó cho screen command, "xem đi" thành "xem" và mọi câu "xem lại logic"
        cũng có thể bị hiểu là cần screenshot. Một bug nhỏ mà rất thích đốt token.
        """
        lowered = (user_text or "").strip().lower()
        try:
            remojibake = lowered.encode("latin1").decode("utf-8")
            if remojibake:
                lowered = remojibake
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        lowered = unicodedata.normalize("NFD", lowered)
        lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
        lowered = lowered.replace("đ", "d")
        lowered = re.sub(r"[^\w\s]", " ", lowered)
        return " ".join(lowered.split())
    def _looks_like_screen_vision_request(self, user_text: str) -> bool:
        normalized = self._normalize_marker_text(user_text)
        if not normalized:
            return False

        # Chỉ các marker thật sự trỏ màn hình mới được capture screenshot.
        # Không dùng marker rộng như "web/chrome/browser" ở đây, vì "xem lại web logic"
        # không đồng nghĩa "hãy nhìn màn hình". Mắt runtime không nên bật vì keyword rẻ tiền.
        direct_terms = {
            self._normalize_marker_text(item)
            for item in (
                "màn hình",
                "trên màn hình",
                "screenshot",
                "screen",
                "nhìn màn hình",
                "xem màn hình",
                "look at this",
                "this screen",
                "xem đi",
                "bạn xem đi",
                "tôi đang code gì",
                "đang code gì",
                "đoạn đang mở",
                "file đang mở",
                "đang hiện gì",
                "lỗi này trên màn hình",
            )
        }
        if any(term and term in normalized for term in direct_terms):
            return True

        visual_verbs = {"nhin", "thay", "xem"}
        visual_objects = {"tren man hinh", "gi tren do", "dang hien", "doan dang mo", "file dang mo"}
        return any(term in normalized for term in visual_verbs) and any(
            term in normalized for term in visual_objects
        )
    def _capture_screen_frame_for_chat(self, user_text: str) -> str:
        """Resolve screen context theo thang: none -> UIA/OCR -> vision.

        Hàm giữ tên cũ để không phá caller, nhưng không còn mặc định chụp ảnh khi
        cache vision cũ. Screen Text Index chạy nền; chat chỉ đọc evidence đã có.
        VLM chỉ được gọi khi router xác định cần bố cục/hình ảnh hoặc text evidence
        không đủ mạnh. Đây mới là escalation, không phải thuế màn hình mỗi lượt.
        """
        self._chat_screen_route_decision = None
        self._chat_screen_text_evidence = ()

        router = getattr(self, "screen_relevance_router", None)
        route = None
        if router is not None:
            try:
                route = router.route(user_text)
            except Exception as exc:
                self.logger.warning("[screen route] router lỗi: %s", exc)

        if route is None:
            # Fallback tối thiểu cho bản chạy thiếu module screen: chỉ vision khi user
            # trỏ màn hình tường minh. Không còn nhánh cache_stale tự chụp bừa.
            if not self._looks_like_screen_vision_request(user_text):
                self.logger.debug("[screen route] mode=none reason=no_screen_reference")
                return ""
            try:
                from screen.evidence_models import ScreenRouteDecision
                route = ScreenRouteDecision(mode="vision", references_screen=True, reason="router_unavailable_explicit_request")
            except Exception:
                route = None

        self._chat_screen_route_decision = route
        if route is not None:
            self._chat_screen_text_evidence = tuple(getattr(route, "evidence", ()) or ())
            self.logger.info(
                "[screen route] mode=%s refs=%s visual=%s evidence=%d confidence=%.2f stale=%s reason=%s",
                str(getattr(route, "mode", "none") or "none"),
                int(bool(getattr(route, "references_screen", False))),
                int(bool(getattr(route, "needs_visual", False))),
                len(self._chat_screen_text_evidence),
                float(getattr(route, "confidence", 0.0) or 0.0),
                int(bool(getattr(route, "stale", False))),
                str(getattr(route, "reason", "") or "none"),
            )

        mode = str(getattr(route, "mode", "none") or "none") if route is not None else "none"
        if mode == "none":
            return ""
        if mode in {"text_evidence", "text_evidence_soft"}:
            # UIA/OCR đã đủ: không capture, không remote vision, không latency 30s.
            return ""
        if mode == "ask_or_abstain":
            return ""
        if mode != "vision":
            return ""

        capture_fn = getattr(self.telemetry_service, "capture_screen_frame_data_uri", None)
        if not callable(capture_fn):
            self.logger.info("[vision chat] telemetry service không hỗ trợ chụp màn hình.")
            return ""
        try:
            data_uri = capture_fn()
        except Exception as exc:
            self.logger.warning("[vision chat] không chụp được màn hình: %s", exc)
            return ""

        self.logger.info("[vision chat] Escalate từ screen-text sang vision (%s).", str(getattr(route, "reason", "") or "policy"))
        snapshot = getattr(self, "_chat_snapshot_for_vision", None)
        if snapshot is not None:
            try:
                self._refresh_screen_facts_from_data_uri(
                    data_uri=data_uri,
                    snapshot=snapshot,
                    channel="chat",
                    user_text=user_text,
                    force_refresh=True,
                )
            except Exception as exc:
                self.logger.warning("[vision chat] không nén được screenshot: %s", exc)
        return data_uri


    def _chat_source_grounding_screen_facts(self, snapshot, *, screen_image_data_uri: str = "") -> tuple[object, ...]:
        """Đưa text evidence hoặc GroundedClaim vào SourceGrounding.

        Screen context chỉ tồn tại khi turn thật sự tham chiếu màn hình. Chat thường
        không được ăn stale vision facts như ambient context nữa, vì chính kiểu đó
        từng kéo chữ "pixel" vô một câu hỏi chẳng liên quan.
        """
        route = getattr(self, "_chat_screen_route_decision", None)
        if route is None or str(getattr(route, "mode", "none") or "none") == "none":
            return ()

        now = time.time()
        text_blocks = tuple(getattr(self, "_chat_screen_text_evidence", ()) or ())
        text_items: list[object] = []
        for block in text_blocks:
            to_item = getattr(block, "to_grounding_item", None)
            if callable(to_item):
                try:
                    text_items.append(to_item(now=now, stale_after=8.0))
                    continue
                except Exception:
                    pass
            text = str(getattr(block, "text", "") or "").strip()
            if text:
                text_items.append({
                    "id": str(getattr(block, "block_id", "screen_text") or "screen_text"),
                    "source": str(getattr(block, "source", "screen_text_index") or "screen_text_index"),
                    "claim": text,
                    "confidence": float(getattr(block, "confidence", 0.65) or 0.65),
                    "grounded": True,
                    "stale": bool(getattr(route, "stale", False)),
                    "tags": ["screen", "screen_text"],
                })
        if text_items and not screen_image_data_uri:
            return tuple(text_items)

        report = getattr(self, "last_vision_grounding_report", None)
        facts: list[object] = []
        if report is not None and screen_image_data_uri and not bool(getattr(report, "stale", False)):
            to_items = getattr(report, "to_evidence_items", None)
            if callable(to_items):
                facts.extend(to_items(grounded_only=True))
        if facts:
            return tuple(facts)

        # Vision capture thất bại: text evidence mềm vẫn tốt hơn marker ảnh rỗng.
        if text_items:
            return tuple(text_items)

        if screen_image_data_uri:
            return ({
                "id": "chat_screen_frame_unresolved",
                "source": "screen_capture",
                "claim": "fresh screenshot captured but no grounded semantic claim",
                "confidence": 0.25,
                "grounded": False,
                "tags": ["vision", "screen", "chat", "ungrounded"],
            },)

        # Chỉ dùng cache vision cũ khi user đang hỏi màn hình mà capture mới hỏng.
        merged = tuple(getattr(snapshot, "vision_facts", ()) or ()) or tuple(getattr(self, "vision_facts", ()) or ())
        for index, text in enumerate(merged):
            cleaned = str(text or "").strip()
            if cleaned:
                facts.append({
                    "id": f"vision_stale:{index}",
                    "source": "vision_grounded_claim",
                    "claim": cleaned,
                    "confidence": 0.52,
                    "grounded": True,
                    "stale": True,
                    "tags": ["vision", "screen", "grounded", "stale"],
                })
        return tuple(facts)

    def _build_chat_source_grounding_report(
        self,
        *,
        user_text: str,
        frame,
        snapshot,
        memory_resonance=None,
        screen_image_data_uri: str = "",
    ):
        engine = getattr(self, "source_grounding_engine", None)
        if not isinstance(engine, SourceGroundingEngine):
            engine = SourceGroundingEngine()
            self.source_grounding_engine = engine
        return engine.analyze(
            user_text,
            frame=frame,
            screen_facts=self._chat_source_grounding_screen_facts(
                snapshot,
                screen_image_data_uri=screen_image_data_uri,
            ),
            # Capture có thể tươi nhưng compressor thất bại và chỉ còn cache cũ.
            # Vì vậy freshness phải dựa cả vào trạng thái vision, không chỉ data URI.
            screen_facts_stale=(
                bool(getattr(getattr(self, "_chat_screen_route_decision", None), "stale", False))
                or (
                    bool(screen_image_data_uri)
                    and (
                        bool(getattr(self, "vision_facts_are_stale", False))
                        or bool(getattr(getattr(self, "last_vision_grounding_report", None), "stale", False))
                    )
                )
            ),
            memory_packet=memory_resonance,
            runtime_state=snapshot,
            allow_web=False,
            attach_to_frame=True,
        )

    def _log_chat_source_grounding(self, report) -> None:
        if report is None:
            return
        self.logger.info(
            "[source grounding] grounding_source=%s | preempt_mode=%s | missing=%s | allowed=%s | cap=%.2f | memory_answer=%s | warnings=%s",
            getattr(report, "grounding_source", "unknown"),
            getattr(report, "preempt_mode", "") or "none",
            ",".join(getattr(report, "missing_evidence", ()) or ()) or "none",
            ",".join(getattr(report, "allowed_sources", ()) or ()) or "none",
            float(getattr(report, "confidence_cap", 0.0) or 0.0),
            int(bool(getattr(report, "memory_answer_allowed", True))),
            ",".join(getattr(report, "warnings", ()) or ()) or "none",
        )

    def _normalize_public_reaction_text(self, text: str) -> str:
        lowered = (text or "").strip().lower()
        try:
            remojibake = lowered.encode("latin1").decode("utf-8")
            if remojibake:
                lowered = remojibake
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        lowered = unicodedata.normalize("NFD", lowered)
        lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
        lowered = lowered.replace("đ", "d")
        lowered = re.sub(r"[^a-z0-9_\s]+", " ", lowered)
        return " ".join(lowered.split())

    def _previous_public_turn_has_protocol_leak(self, public_turn) -> str:
        if public_turn is None:
            return ""
        text = str(getattr(public_turn, "text", "") or "")
        detector = getattr(self, "_detect_protocol_surface_leak", None)
        if callable(detector) and detector(text):
            return "prompt_leak"
        normalized = self._normalize_public_reaction_text(text)
        raw_lower = text.lower()
        prompt_markers = (
            "speech intent",
            "speech evidence",
            "persona",
            "constraints",
            "return only",
            "valid json object",
            "ghi chu nen",
            "goi y dieu phoi",
            "llm final prompt",
            "critical output contract",
        )
        prompt_hits = sum(1 for marker in prompt_markers if marker in normalized or marker in raw_lower)
        if prompt_hits >= 2 or (prompt_hits >= 1 and ("*" in text or "`" in text)):
            return "prompt_leak"
        metadata_markers = (
            '\", \"intent\"',
            '\", \"action\"',
            "reasoning_tags",
            "should_speak",
            "debug_trace",
            "system_action",
        )
        if any(marker in text for marker in metadata_markers) or any(marker in normalized for marker in ("intent action", "debug trace")):
            return "metadata_leak"
        return ""

    def _user_is_challenging_previous_public_turn(self, user_text: str) -> bool:
        normalized = self._normalize_public_reaction_text(user_text)
        if not normalized:
            return False
        markers = (
            "ban vua biet ban noi cai gi khong",
            "vua biet ban noi cai gi khong",
            "ban vua noi cai gi",
            "vua noi cai gi",
            "khong thay no te",
            "khong thay te",
            "no te a",
            "te a",
            "te qua",
            "loi gi",
            "bi loi",
            "prompt",
            "json",
            "metadata",
            "debug",
            "raw",
            "parser",
            "format",
        )
        return any(marker in normalized for marker in markers)

    def _build_previous_public_turn_repair_decision(
        self,
        *,
        user_text: str,
        previous_public_turn,
        ti_report,
        grounding_report=None,
        frame=None,
        speech_core=None,
    ) -> Decision | None:
        """Chặn sớm duy nhất khi câu trước làm rò protocol/debug.

        Những hiểu lầm xã hội thông thường KHÔNG còn bị trả bằng một câu template
        rồi kết thúc turn. Social Cognition và Dual-Axis Repair đã đưa nghĩa vụ sửa
        hiểu lầm vào prompt; main generator phải vừa nhận lỗi, vừa trả lời câu hỏi
        còn treo. Nhờ vậy ``repair_ack_then_answer`` không bị cụt còn mỗi ``ack``.
        """
        leak_kind = self._previous_public_turn_has_protocol_leak(previous_public_turn)
        if not (leak_kind and self._user_is_challenging_previous_public_turn(user_text)):
            return None

        if leak_kind == "prompt_leak":
            text = (
                "Có. Câu vừa rồi lỗi thật. Tôi để phần hậu trường lọt ra ngoài "
                "thay vì nói một câu bình thường."
            )
        else:
            text = (
                "Có. Câu vừa rồi lỗi thật. Nó dính phần hậu trường vào lời nói; "
                "đáng lẽ tôi phải giữ phần đó ở bên trong."
            )

        decision = Decision(
            text=text,
            intent="repair_previous_public_turn",
            action="none",
            animation="stand",
            should_speak=True,
            confidence=0.86,
            parse_mode="public_turn_protocol_repair",
            debug_trace=(
                "previous_public_turn_protocol_repair;"
                f"kind={leak_kind};turn_id={getattr(previous_public_turn, 'turn_id', '')}"
            ),
        )
        return self.ti_governor.enforce_decision(decision, ti_report, user_hint=user_text)

    def _build_grounding_preempt_decision(self, report, ti_report, *, user_text: str) -> Decision | None:
        engine = getattr(self, "source_grounding_engine", None)
        if not isinstance(engine, SourceGroundingEngine):
            return None
        if not engine.should_preempt(report):
            return None
        text = engine.build_preemptive_reply(report)
        if not text:
            text = self._generate_grounding_preempt_text(report, user_text=user_text)
        if not text:
            # No Python-authored sentence here. If local wording is unavailable,
            # let the normal chat LLM path continue with source_grounding context
            # and let post-generation guards catch any overclaim. Apparently even
            # a machine needs due process now.
            return None
        warnings = ",".join(getattr(report, "warnings", ()) or ())
        debug_trace = (
            "source_grounding_preempt;"
            f"source={getattr(report, 'primary_source', 'unknown')};"
            f"preempt={getattr(report, 'preempt_mode', '') or 'unknown'};"
            f"warnings={warnings}"
        )
        epistemic_mode = str(getattr(report, "epistemic_mode", "") or "")
        is_probe = epistemic_mode in {"probe", "hypothesis"}
        decision = Decision(
            text=text,
            intent="epistemic_probe" if is_probe else "grounding_clarification",
            action="none",
            animation="stand",
            should_speak=True,
            confidence=float(getattr(report, "max_confidence", 0.30) or 0.30),
            parse_mode="source_grounding_probe" if is_probe else "source_grounding_preempt",
            debug_trace=debug_trace + (f";epistemic_mode={epistemic_mode};llm_generated=1" if epistemic_mode else ";llm_generated=1"),
        )
        return self.ti_governor.enforce_decision(decision, ti_report, user_hint=user_text)

    def _generate_grounding_preempt_text(self, report, *, user_text: str) -> str:
        service = getattr(self, "llm_service", None)
        reroll = getattr(service, "rewrite_guard_violation_text", None)
        if not callable(reroll):
            return self._local_grounding_preempt_text(report, user_text=user_text)
        fallback_decision = getattr(report, "fallback_decision", None)
        missing = tuple(str(item) for item in (getattr(report, "missing_evidence", ()) or ()) if str(item or "").strip())
        reason = (
            str(getattr(fallback_decision, "reason", "") or "")
            or str(getattr(report, "preempt_mode", "") or "")
            or "source_grounding_preempt"
        )
        try:
            internal_context_fn = getattr(self, "_guard_internal_state_context", None)
            internal_context = internal_context_fn() if callable(internal_context_fn) else ""
        except Exception:
            internal_context = ""
        try:
            text = reroll(
                original_text="",
                violation_rule="source_grounding_preempt",
                violation_reason=reason,
                missing_evidence=missing,
                fallback_text="",
                channel="chat",
                user_text=user_text,
                internal_state_context=internal_context,
                grounding_context=str(getattr(report, "prompt_context", "") or ""),
                arbitration_context=(
                    "SourceGrounding is a flag emitter only. Generate a short public line "
                    "that respects missing evidence without using a static Python fallback."
                ),
            )
        except Exception as exc:
            try:
                self.logger.warning("[source grounding] preempt llm repair failed: %s", exc)
            except Exception:
                pass
            return self._local_grounding_preempt_text(report, user_text=user_text)
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if not text:
            return self._local_grounding_preempt_text(report, user_text=user_text)
        missing_set = set(missing)
        try:
            if "file_evidence" in missing_set and self._looks_like_file_grounded_claim(text, report=report):
                return self._local_grounding_preempt_text(report, user_text=user_text)
            if "screen_evidence" in missing_set and self._looks_like_screen_grounded_claim(text):
                return self._local_grounding_preempt_text(report, user_text=user_text)
            if "web_access_or_search_result" in missing_set and self._looks_like_live_web_claim(text):
                return self._local_grounding_preempt_text(report, user_text=user_text)
        except Exception:
            return self._local_grounding_preempt_text(report, user_text=user_text)
        return text

    def _local_grounding_preempt_text(self, report, *, user_text: str = "") -> str:
        del user_text
        mode = str(getattr(report, "preempt_mode", "") or "")
        file_mentions = tuple(str(item) for item in (getattr(report, "file_mentions", ()) or ()) if str(item or "").strip())
        if mode == "filename_only":
            label = file_mentions[0] if file_mentions else "file đó"
            return f"Tôi mới chỉ có tên file {label}, chưa có nội dung file để kết luận."
        if mode == "deictic_without_vision":
            return "Tôi chưa có evidence màn hình đủ mới để nói câu này chắc được."
        missing = set(str(item) for item in (getattr(report, "missing_evidence", ()) or ()) if str(item or "").strip())
        if "file_evidence" in missing:
            label = file_mentions[0] if file_mentions else "file đó"
            return f"Tôi chưa có nội dung {label} để trả lời chắc tay."
        if "screen_evidence" in missing:
            return "Tôi chưa có evidence màn hình đủ rõ cho câu hỏi này."
        return ""

    def _build_user_message_signature(self, user_text: str) -> str:
        normalized = self._normalize_user_message(user_text)
        if not normalized:
            return ""

        if self.action_router is not None:
            routed = self.action_router.route_chat(user_text, last_action=self.last_system_action)
            if routed:
                action_name, action_input = routed
                normalized_input = self._normalize_user_message(action_input)
                if action_name == "get_now_playing":
                    return "action:get_now_playing"
                return f"action:{action_name}:{normalized_input}"

        return normalized
    def _track_repeated_user_message(self, user_text: str) -> int:
        signature = self._build_user_message_signature(user_text)
        if not signature:
            self.last_user_signature = ""
            self.repeated_user_count = 0
            return 0

        if signature == self.last_user_signature:
            self.repeated_user_count += 1
        else:
            self.last_user_signature = signature
            self.repeated_user_count = 1
        return self.repeated_user_count
    def _get_turn_semantics_engine(self) -> TurnSemanticsEngine:
        engine = getattr(self, "turn_semantics_engine", None)
        if engine is None:
            engine = TurnSemanticsEngine()
            self.turn_semantics_engine = engine
        return engine

    def _build_turn_semantics_report(
        self,
        *,
        user_text: str,
        repeat_count: int,
        previous_user_text: str = "",
        affect_signal=None,
        conversation_report=None,
        relationship_report=None,
        grounding_report=None,
        social_appraisal=None,
    ) -> TurnSemanticsReport:
        engine = self._get_turn_semantics_engine()
        return engine.analyze_repeat(
            user_text=user_text,
            repeat_count=repeat_count,
            last_user_text=previous_user_text,
            last_assistant_text=getattr(self, "last_chat_answer", ""),
            affect_signal=affect_signal,
            conversation_report=conversation_report,
            relationship_report=relationship_report,
            grounding_report=grounding_report,
            social_appraisal=social_appraisal,
        )

    def _build_repeat_guard_decision(
        self,
        user_text: str,
        ti_report,
        repeat_count: int,
        *,
        grounding_report=None,
        turn_semantics_report: TurnSemanticsReport | None = None,
    ) -> Decision | None:
        if repeat_count < 2:
            return None

        report = turn_semantics_report or self._build_turn_semantics_report(
            user_text=user_text,
            repeat_count=repeat_count,
            previous_user_text=getattr(self, "last_user_text_for_semantics", ""),
            grounding_report=grounding_report,
        )

        # Legacy bypass chỉ còn là dây an toàn cho live observation; quyền quyết định chính
        # thuộc về TurnSemanticsEngine. Exact repeat không được đứng trên meaning.
        if self._should_bypass_repeat_guard_for_live_observation(user_text, grounding_report=grounding_report):
            return None
        if not report.should_guard_repeat:
            return None

        text = self._get_turn_semantics_engine().build_repeat_guard_text(report)
        if "lặp lại" not in text.lower():
            text = f"{text} Tôi đang giữ nhịp lặp lại này lại."
        decision = Decision(
            text=text,
            intent="low_value_repeat",
            action="none",
            animation="read" if repeat_count == 2 else "sad",
            should_speak=True,
            confidence=min(0.78, max(0.42, report.confidence)),
            parse_mode="repeat_guard",
            debug_trace=(
                f"repeat_guard=count={repeat_count};"
                f"intent={report.intent};spam={report.spam_pressure:.2f};"
                f"reasons={','.join(report.reasons) or 'none'}"
            ),
        )
        return self.ti_governor.enforce_decision(decision, ti_report, user_hint=user_text)

    def _should_bypass_repeat_guard_for_live_observation(self, user_text: str, *, grounding_report=None) -> bool:
        if grounding_report is not None:
            if str(getattr(grounding_report, "preempt_mode", "") or "") == "deictic_without_vision":
                return False
            missing = set(getattr(grounding_report, "missing_evidence", ()) or ())
            if bool(getattr(grounding_report, "refers_to_current_screen", False)) and "screen_evidence" not in missing:
                return True
        return self._looks_like_screen_vision_request(user_text)
