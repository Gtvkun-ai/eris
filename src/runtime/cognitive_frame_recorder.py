from __future__ import annotations

import re
import time
from dataclasses import replace
from typing import Any, Mapping, Sequence

from cortex.contracts import CognitiveFrame, CognitiveMemoryUpdate
from domain import Decision
from runtime.liveliness_tracker import DecisionRecord, GROUNDED_SOURCES, LivelinessTracker


class CognitiveFrameRecorderMixin:
    """Ghi nhận frame theo commit protocol.

    Vai trò đúng của file này:
    - quan sát outcome cuối turn;
    - derive các StateCommitRequest từ frame;
    - append request vào frame;
    - gọi StateCommitter.commit(frame).

    File này không còn được phép gọi thẳng các hàm ghi memory ở store.
    Nếu recorder tự ghi memory thì StateCommitter
    chỉ còn là đồ trang trí kiến trúc, một loại bình hoa rất đắt nhưng vô dụng.
    """

    # ------------------------------------------------------------------
    # Commit request derivation
    # ------------------------------------------------------------------

    def _remember_cognitive_frame(self, frame: CognitiveFrame) -> None:
        """Tương thích tên hàm cũ, nhưng không ghi memory trực tiếp nữa.

        Tên `_remember_cognitive_frame` được giữ để coordinator cũ không gãy.
        Nội dung mới chỉ tạo request. Việc ghi thật được dồn về
        `StateCommitter.commit(frame)` trong `_finalize_cognitive_frame`.
        """

        requests = self._derive_state_commit_requests(frame)
        self._append_commit_requests(frame, requests)
        self._refresh_memory_update_from_commit_requests(frame, requests)

    def _is_ephemeral_micro_presence_observation(self, frame: CognitiveFrame, observation: Mapping[str, Any]) -> bool:
        final_decision = getattr(frame, "final_decision", {}) or {}
        if not isinstance(final_decision, Mapping):
            final_decision = {}
        parse_mode = str(observation.get("parse_mode", "") or final_decision.get("parse_mode", "") or "")
        tags = {str(item) for item in (observation.get("tags", ()) or ()) if str(item).strip()}
        intent = str(final_decision.get("intent", "") or getattr(frame.action_plan, "speech_intent", "") or "")
        action = str(final_decision.get("action", "") or "")
        reasoning_tags = {str(item) for item in (final_decision.get("reasoning_tags", ()) or ()) if str(item).strip()}
        ephemeral_parse_modes = {
            "presence_maintenance",
            "presence_maintenance_body_only",
            "micro_presence",
            "micro_observation",
            "micro_observation_body_only",
            "re_engagement_body_only",
            "guard_body_only",
            "no_speech_policy",
        }
        if parse_mode in ephemeral_parse_modes:
            return True
        if intent in {"presence_maintenance", "micro_presence", "micro_observation", "body_only_guard_repair"}:
            return True
        if "micro_presence" in tags or "micro_presence" in reasoning_tags or "body_only_motion" in reasoning_tags:
            return True
        if action == "MotionCommand" and not str(observation.get("final_text", "") or "").strip():
            return True
        return False

    def _derive_state_commit_requests(self, frame: CognitiveFrame) -> list[Mapping[str, Any]]:
        """Sinh toàn bộ StateCommitRequest từ frame hiện tại.

        Đây là lớp chuyển đổi từ outcome/runtime frame sang commit protocol.
        Mọi request đều có target, content, confidence, evidence_ids,
        permission_required, storage_permission, decay_policy và reason.
        """

        observation = self._observe_outcome_for_commit(frame)
        evidence_ids = list(observation["evidence_ids"])
        timestamp = str(observation["timestamp"])
        storage_permission = self._frame_storage_permission(frame)
        ephemeral_presence = self._is_ephemeral_micro_presence_observation(frame, observation)
        event_decay_policy = "session_only" if ephemeral_presence else "none"
        requests: list[Mapping[str, Any]] = []

        # 1. Event ledger: audit thô của turn. Đây là dấu vết, không phải ký ức
        # semantic đã được tin. Event ledger được phép không cần evidence_ids vì
        # chính nó là nơi ghi event/evidence gốc.
        requests.append(
            self._make_commit_request(
                target="event_ledger",
                content={
                    "cycle_id": frame.cycle_id,
                    "channel": frame.channel,
                    "timestamp": timestamp,
                    "seen": list(observation["seen"]),
                    "said": observation["final_text"],
                    "outcome": observation["outcome"],
                    "tags": [*list(observation["tags"]), *(["signal_buffer_only", "ephemeral_presence"] if ephemeral_presence else [])],
                    "system_action": observation["system_action"],
                    "salience": observation["salience"],
                    "parse_mode": observation["parse_mode"],
                },
                confidence=1.0,
                evidence_ids=evidence_ids,
                permission_required=False,
                storage_permission=storage_permission,
                decay_policy=event_decay_policy,
                reason="audit raw cognitive frame outcome" if not ephemeral_presence else "audit ephemeral micro-presence/body-only signal",
                tags=("cognitive_frame", "event_ledger", str(frame.channel or ""), *(("signal_buffer_only", "ephemeral_presence") if ephemeral_presence else ())),
                metadata={"source": "CognitiveFrameRecorder", "timestamp": timestamp, "ephemeral_presence": ephemeral_presence},
            )
        )

        # 2. Episodic memory: chuyện cụ thể vừa xảy ra. Nếu frame không có gì
        # đáng kể thì bỏ, tránh lưu một bãi episode rỗng chỉ để tự an ủi rằng
        # hệ thống có memory.
        if (not ephemeral_presence) and (observation["seen"] or observation["final_text"] or observation["system_action"]):
            requests.append(
                self._make_commit_request(
                    target="episodic_memory",
                    content={
                        "cycle_id": frame.cycle_id,
                        "channel": frame.channel,
                        "timestamp": timestamp,
                        "scene": list(observation["seen"]),
                        "eris_action": observation["final_text"],
                        "outcome": observation["outcome"],
                        "salience": observation["salience"],
                        "tags": list(observation["tags"]),
                        "system_action": observation["system_action"],
                    },
                    confidence=max(0.55, min(0.92, float(observation["salience"]) or 0.55)),
                    evidence_ids=evidence_ids,
                    permission_required=True,
                    storage_permission=storage_permission,
                    decay_policy="normal",
                    reason="store concrete cognitive turn as episodic memory",
                    tags=("episodic", "turn_outcome", str(frame.channel or "")),
                    metadata={"source": "CognitiveFrameRecorder", "timestamp": timestamp},
                )
            )

        # 3. Semantic memory: recorder KHÔNG tự mint semantic fact nữa.
        #
        # Chuẩn ERIS là: user_text -> MemoryCommitPolicy/MemoryKernel ->
        # SemanticParser -> ClaimBuilder -> Worthiness -> Retention -> StateCommitRequest.
        # Recorder chỉ quan sát outcome của frame, nên nếu nó tự lấy
        # `remembered_fact` hoặc `decision_extracted_fact` rồi đẩy thẳng vào
        # semantic_memory thì nó đã đi vòng qua judgement layer. Đó chính là
        # nguồn sinh mấy ký ức vô dụng kiểu greeting/slang/MemoryPacket.
        #
        # Các user fact thật đã được StateCommitServiceMixin thêm vào
        # frame.commit_requests bằng `_add_user_turn_memory_commit_requests(...)`
        # trước khi frame finalize. Ở đây chỉ giữ event/episodic/repair/audit.
        # Session query như "câu đầu tiên tôi nhắn là gì" thuộc
        # SessionTurnLedger, không được biến thành semantic memory dài hạn.

        # 4. Relationship/procedural/repair từ reflection. Hàm derive vẫn giữ tên
        # cũ, nhưng kết quả giờ thành request chứ không gọi store trực tiếp.
        for pattern, text, evidence in self._derive_relationship_reflections(frame):
            target = self._target_for_reflection(pattern)
            requests.append(
                self._make_commit_request(
                    target=target,
                    content={
                        "pattern": pattern,
                        "text": text,
                        "timestamp": timestamp,
                        "cycle_id": frame.cycle_id,
                        "evidence": list(evidence),
                    },
                    confidence=0.70 if target == "procedural_memory" else 0.64,
                    evidence_ids=evidence_ids or list(evidence),
                    permission_required=True,
                    storage_permission=storage_permission,
                    decay_policy="slow" if target in {"relational_memory", "procedural_memory"} else "normal",
                    reason=f"derive {target} from cognitive frame reflection",
                    tags=(target, pattern, "frame_reflection"),
                    metadata={"source": "CognitiveFrameRecorder", "timestamp": timestamp, "pattern": pattern},
                )
            )

        # 5. Repair memory: user correction phải ưu tiên repair. Không nhét vào
        # semantic như thể user vừa ban phát một fact ổn định. Họ đang sửa lỗi
        # hệ thống, vì vậy phải lưu lỗi và chiến lược tránh lặp.
        repair_request = self._derive_repair_commit_request(frame, observation, storage_permission=storage_permission)
        if repair_request:
            requests.append(repair_request)

        # 6. Affective residue: chỉ lưu pressure nội bộ có ích, không biến thành
        # lời tuyên bố cảm xúc. Residue là bias, không phải câu thoại sến.
        residue_request = self._derive_affective_residue_request(frame, observation, storage_permission=storage_permission)
        if residue_request:
            requests.append(residue_request)

        # 7. Active state: snapshot runtime sau turn. Đây thay thế việc recorder
        # tự ghi snapshot runtime rồi save state. Committer sẽ route sang
        # active_state / MemoryCognitionCore.
        active_state_request = self._derive_active_state_request(frame, observation, storage_permission=storage_permission)
        if active_state_request:
            requests.append(active_state_request)

        return self._dedupe_commit_requests(requests)

    def _observe_outcome_for_commit(self, frame: CognitiveFrame) -> dict[str, Any]:
        """Rút outcome cuối turn thành payload sạch để derive request."""

        timestamp = ""
        if frame.percepts:
            timestamp = str(getattr(frame.percepts[0], "timestamp", "") or "")
        if not timestamp:
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(frame.started_at or time.time()))

        if getattr(frame.broadcast, "items", None):
            seen = tuple(item.content for item in frame.broadcast.items if getattr(item, "content", None))
        elif getattr(frame.broadcast, "content", None):
            seen = (frame.broadcast.content,)
        else:
            seen = tuple(item.content for item in frame.attention_candidates[:2] if getattr(item, "content", None))

        final_decision = getattr(frame, "final_decision", {}) or {}
        if not isinstance(final_decision, Mapping):
            final_decision = {}
        final_text = str(final_decision.get("text", "") or "")
        parse_mode = str(final_decision.get("parse_mode", "") or "")
        outcome = parse_mode or frame.action_plan.speech_intent or "cycle"
        if frame.action_plan.system_action:
            outcome = f"{outcome}:{frame.action_plan.system_action}"

        tags = tuple(
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
                if getattr(percept, "kind", "") == "user_message"
            )
            if fact
        )
        remembered_fact = str(getattr(frame.memory_update, "remembered_fact", "") or "")
        # Không biến output đã bị policy reject/no_speech thành semantic candidate.
        # Event ledger vẫn có thể audit, nhưng semantic memory không cần ăn rác có nhãn "final".
        if parse_mode in {"no_speech_policy", "semantic_repair_failed", "source_grounding_guard"}:
            remembered_fact = ""
        semantic_facts = tuple(dict.fromkeys(fact for fact in (remembered_fact, *explicit_user_facts) if fact))

        return {
            "timestamp": timestamp,
            "seen": tuple(seen),
            "final_text": final_text,
            "parse_mode": parse_mode,
            "outcome": outcome,
            "tags": tags,
            "semantic_facts": semantic_facts,
            "explicit_user_facts": explicit_user_facts,
            "system_action": frame.action_plan.system_action,
            "salience": float(getattr(frame.broadcast, "score", 0.0) or 0.0),
            "evidence_ids": self._frame_evidence_ids(frame),
        }

    def _make_commit_request(
        self,
        *,
        target: str,
        content: Any,
        confidence: float,
        evidence_ids: Sequence[str] = (),
        permission_required: bool = True,
        storage_permission: bool = True,
        decay_policy: str = "normal",
        reason: str = "",
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Tạo request dạng dict tương thích StateCommitRequest.

        StateCommitter đã hỗ trợ dict/object/dataclass, nên dùng dict ở đây để
        tránh recorder phụ thuộc cứng vào contract đang còn di chuyển.
        """

        return {
            "target": target,
            "content": content,
            "confidence": self._bounded_float(confidence),
            "evidence_ids": list(dict.fromkeys(str(eid) for eid in evidence_ids if str(eid).strip())),
            "permission_required": bool(permission_required),
            "storage_permission": bool(storage_permission),
            "decay_policy": decay_policy,
            "reason": reason,
            "source_module": "CognitiveFrameRecorder",
            "tags": [str(tag) for tag in tags if str(tag).strip()],
            "metadata": dict(metadata or {}),
        }

    def _append_commit_requests(self, frame: CognitiveFrame, requests: Sequence[Any]) -> None:
        """Append request vào frame mà không phá contract frame cũ/mới."""

        if not requests:
            return

        add_commit_request = getattr(frame, "add_commit_request", None)
        if callable(add_commit_request):
            existing_keys = self._existing_commit_request_keys(getattr(frame, "commit_requests", ()) or ())
            for request in requests:
                key = self._commit_request_key(request)
                if key in existing_keys:
                    continue
                add_commit_request(request)
                existing_keys.add(key)
            return

        existing = list(getattr(frame, "commit_requests", []) or [])
        existing_keys = self._existing_commit_request_keys(existing)
        for request in requests:
            key = self._commit_request_key(request)
            if key in existing_keys:
                continue
            existing.append(request)
            existing_keys.add(key)
        try:
            frame.commit_requests = existing
        except Exception:
            # Nếu frame khóa attribute, ít nhất không làm chết runtime.
            self.logger.warning("Không append được StateCommitRequest vào frame; frame contract cần được mở commit_requests.")

    def _refresh_memory_update_from_commit_requests(
        self,
        frame: CognitiveFrame,
        requests: Sequence[Any],
    ) -> None:
        """Cập nhật summary debug trên frame.memory_update từ request vừa derive.

        Đây chỉ là metadata trong frame, không phải ghi memory.
        """

        semantic_facts: list[str] = []
        relation_notes: list[str] = []
        episodic_summary = ""
        for request in requests:
            target = self._commit_request_field(request, "target", "")
            content = self._commit_request_field(request, "content", None)
            if target == "semantic_memory":
                if isinstance(content, Mapping):
                    fact = str(content.get("fact", "") or "")
                else:
                    fact = str(content or "")
                if fact:
                    semantic_facts.append(fact)
            elif target == "relational_memory":
                text = str(content.get("text", "") if isinstance(content, Mapping) else content or "")
                if text:
                    relation_notes.append(text)
            elif target == "episodic_memory" and isinstance(content, Mapping):
                said = str(content.get("eris_action", "") or "")
                outcome = str(content.get("outcome", "") or "cycle")
                episodic_summary = f"{outcome}: {said[:120]}" if said else outcome

        if semantic_facts and not getattr(frame.memory_update, "semantic_fact", ""):
            frame.memory_update.semantic_fact = semantic_facts[0]
        if relation_notes:
            frame.memory_update.relationship_reflection = " | ".join(relation_notes)[:260]
        if episodic_summary and not getattr(frame.memory_update, "episodic_summary", ""):
            frame.memory_update.episodic_summary = episodic_summary[:260]
        if requests and not getattr(frame.memory_update, "working_summary", ""):
            frame.memory_update.working_summary = f"commit_requests={len(requests)}"

    # ------------------------------------------------------------------
    # Relationship / procedural reflection
    # ------------------------------------------------------------------

    def _remember_relationship_reflections(self, frame: CognitiveFrame, *, timestamp: str) -> None:
        """Tên cũ, hành vi mới: derive request, không ghi store trực tiếp."""

        storage_permission = self._frame_storage_permission(frame)
        evidence_ids = self._frame_evidence_ids(frame)
        requests: list[Mapping[str, Any]] = []
        for pattern, text, evidence in self._derive_relationship_reflections(frame):
            target = self._target_for_reflection(pattern)
            requests.append(
                self._make_commit_request(
                    target=target,
                    content={
                        "pattern": pattern,
                        "text": text,
                        "timestamp": timestamp,
                        "cycle_id": frame.cycle_id,
                        "evidence": list(evidence),
                    },
                    confidence=0.66,
                    evidence_ids=evidence_ids or list(evidence),
                    permission_required=True,
                    storage_permission=storage_permission,
                    decay_policy="slow",
                    reason=f"derive {target} from relationship reflection",
                    tags=(target, pattern, "relationship_reflection"),
                    metadata={"source": "CognitiveFrameRecorder", "timestamp": timestamp},
                )
            )
        self._append_commit_requests(frame, requests)
        self._refresh_memory_update_from_commit_requests(frame, requests)

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
                    "bạn hay bấm force_speak khi muốn ERIS hiện diện hơn là cần thông tin.",
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

    def _target_for_reflection(self, pattern: str) -> str:
        """Map reflection sang memory layer phù hợp."""

        if pattern in {"no_screen_signal_social_fallback", "social_initiative_rhythm"}:
            return "procedural_memory"
        if "repair" in pattern or "correction" in pattern or "misread" in pattern:
            return "repair_memory"
        return "relational_memory"

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
                "bạn thích giọng lạnh nhẹ, nhưng không thích báo cáo telemetry.",
                (f"user_text={user_text[:120]}",),
            )
        if likes_cold_soft:
            return (
                "style_preference",
                "bạn thích giọng lạnh nhẹ và có kiểm soát.",
                (f"user_text={user_text[:120]}",),
            )
        if dislikes_telemetry:
            return (
                "style_preference",
                "bạn không thích ERIS nói như báo cáo telemetry hoặc log hệ thống.",
                (f"user_text={user_text[:120]}",),
            )
        return None

    # ------------------------------------------------------------------
    # Specific request derivation
    # ------------------------------------------------------------------

    def _derive_repair_commit_request(
        self,
        frame: CognitiveFrame,
        observation: Mapping[str, Any],
        *,
        storage_permission: bool,
    ) -> Mapping[str, Any] | None:
        conversation = getattr(frame, "conversation_dynamics", None) or getattr(frame, "conversation_report", None)
        mode = str(getattr(conversation, "mode", "") or "")
        last_failure = str(getattr(conversation, "last_failure", "") or "")
        correction_streak = int(getattr(conversation, "correction_streak", 0) or 0)
        semantic_tension = float(getattr(conversation, "semantic_tension", 0.0) or 0.0)

        user_texts = tuple(
            str(percept.content or "")
            for percept in tuple(frame.percepts or ())
            if getattr(percept, "kind", "") == "user_message" and getattr(percept, "content", "")
        )
        correction_text = " | ".join(text[:180] for text in user_texts if self._looks_like_user_correction_text(text))

        needs_repair = (
            mode in {"repair", "relational_repair"}
            or correction_streak > 0
            or bool(correction_text)
            or last_failure not in {"", "none", "null"}
        )
        if not needs_repair:
            return None

        failure_type = last_failure if last_failure not in {"", "none", "null"} else "misread"
        if mode == "relational_repair" and failure_type == "misread":
            failure_type = "tone_mismatch"

        return self._make_commit_request(
            target="repair_memory",
            content={
                "failure_type": failure_type,
                "trigger_context": str(observation.get("outcome", "cycle")),
                "wrong_assumption": self._preview_text(str(getattr(conversation, "wrong_assumption", "") or ""), limit=220),
                "user_correction": correction_text,
                "repair_strategy": self._repair_strategy_for_failure(failure_type, mode),
                "future_suppression_rule": self._future_suppression_rule_for_failure(failure_type, mode),
                "semantic_tension": semantic_tension,
                "correction_streak": correction_streak,
                "cycle_id": frame.cycle_id,
                "timestamp": observation.get("timestamp"),
            },
            confidence=0.76 if correction_text else 0.58,
            evidence_ids=self._frame_evidence_ids(frame),
            permission_required=True,
            storage_permission=storage_permission,
            decay_policy="slow",
            reason="user correction or conversation repair detected; prioritize repair memory",
            tags=("repair", "user_correction" if correction_text else "conversation_repair", failure_type),
            metadata={
                "source": "CognitiveFrameRecorder",
                "user_correction": bool(correction_text),
                "conversation_mode": mode,
                "failure_type": failure_type,
            },
        )

    def _derive_affective_residue_request(
        self,
        frame: CognitiveFrame,
        observation: Mapping[str, Any],
        *,
        storage_permission: bool,
    ) -> Mapping[str, Any] | None:
        appraisal = getattr(frame, "appraisal", None)
        if appraisal is None:
            return None

        stance = str(getattr(appraisal, "stance", "") or "")
        threat = float(getattr(appraisal, "threat", 0.0) or 0.0)
        intimacy = float(getattr(appraisal, "intimacy", 0.0) or 0.0)
        tenderness = float(getattr(appraisal, "tenderness", 0.0) or 0.0)
        fatigue = float(getattr(appraisal, "fatigue", 0.0) or 0.0)
        residue_strength = max(threat, intimacy, tenderness, fatigue)

        if not stance or stance == "grounded" or residue_strength < 0.42:
            return None

        return self._make_commit_request(
            target="affective_residue_memory",
            content={
                "stance": stance,
                "residue_strength": residue_strength,
                "threat": threat,
                "intimacy": intimacy,
                "tenderness": tenderness,
                "fatigue": fatigue,
                "channel": frame.channel,
                "outcome": observation.get("outcome"),
                "cycle_id": frame.cycle_id,
                "timestamp": observation.get("timestamp"),
            },
            confidence=max(0.48, min(0.72, residue_strength)),
            evidence_ids=self._frame_evidence_ids(frame),
            permission_required=True,
            storage_permission=storage_permission,
            decay_policy="normal",
            reason="store affective residue as internal bias, not public fact",
            tags=("affective_residue", stance),
            metadata={"source": "CognitiveFrameRecorder", "public_surface_allowed": False},
        )

    def _derive_active_state_request(
        self,
        frame: CognitiveFrame,
        observation: Mapping[str, Any],
        *,
        storage_permission: bool,
    ) -> Mapping[str, Any] | None:
        state = getattr(frame, "internal_state_after", None)
        if state is None:
            return None

        return self._make_commit_request(
            target="active_state",
            content={
                "cycle_id": frame.cycle_id,
                "channel": frame.channel,
                "timestamp": observation.get("timestamp"),
                "internal_state": self._safe_state_payload(state),
                "last_text": str(observation.get("final_text", "") or "")[:240],
                "last_outcome": observation.get("outcome"),
                "last_speech_act": getattr(frame.action_plan, "speech_act", ""),
                "last_speech_intent": getattr(frame.action_plan, "speech_intent", ""),
                "semantic_family": str(getattr(getattr(frame, "meaning_layer", None), "semantic_family", "") or ""),
            },
            confidence=0.82,
            evidence_ids=self._frame_evidence_ids(frame),
            permission_required=False,
            storage_permission=storage_permission,
            decay_policy="session_only",
            reason="update active runtime state snapshot through commit protocol",
            tags=("active_state", "runtime_snapshot"),
            metadata={"source": "CognitiveFrameRecorder", "timestamp": observation.get("timestamp")},
        )

    # ------------------------------------------------------------------
    # Fact extraction / ids / permissions
    # ------------------------------------------------------------------

    def _semantic_fact_grounding_metadata(self, frame: CognitiveFrame, *, semantic_source: str) -> dict[str, Any]:
        report = getattr(frame, "source_grounding", None) or getattr(frame, "grounding", None)
        missing = tuple(getattr(report, "missing_evidence", ()) or ())
        preempt_mode = str(getattr(report, "preempt_mode", "") or "")
        grounding_source = str(getattr(report, "grounding_source", getattr(report, "primary_source", "unknown")) or "unknown")
        source_grounded = semantic_source == "explicit_user_statement"
        if semantic_source != "explicit_user_statement":
            source_grounded = not (
                preempt_mode
                or any(item in {"file_evidence", "screen_evidence", "web_access_or_search_result"} for item in missing)
            )
        return {
            "source_grounded": bool(source_grounded),
            "grounding_source": grounding_source,
            "grounding_missing_evidence": list(missing),
            "grounding_preempt_mode": preempt_mode,
        }

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

    def _frame_evidence_ids(self, frame: CognitiveFrame) -> list[str]:
        ids: list[str] = []
        for item in tuple(getattr(frame, "evidence", ()) or ()):  # core EvidenceItem path
            eid = getattr(item, "id", None) or getattr(item, "evidence_id", None)
            if eid:
                ids.append(str(eid))
        for item in tuple(getattr(frame.broadcast, "items", ()) or ()):  # legacy attention path
            eid = getattr(item, "evidence_id", None) or getattr(item, "id", None)
            if eid:
                ids.append(str(eid))
        for index, percept in enumerate(tuple(getattr(frame, "percepts", ()) or ())) :
            eid = getattr(percept, "evidence_id", None) or getattr(percept, "id", None)
            if eid:
                ids.append(str(eid))
            elif getattr(percept, "kind", "") == "user_message":
                timestamp = str(getattr(percept, "timestamp", "") or getattr(frame, "started_at", "") or "")
                ids.append(f"percept:user_message:{timestamp}:{index}")
        return list(dict.fromkeys(eid for eid in ids if eid))[:24]

    def _evidence_ids_for_fact(self, frame: CognitiveFrame, fact: str, *, fallback: Sequence[str]) -> list[str]:
        normalized_fact = self._normalize_user_message(fact)
        ids: list[str] = []
        for index, percept in enumerate(tuple(getattr(frame, "percepts", ()) or ())):
            if getattr(percept, "kind", "") != "user_message":
                continue
            content = str(getattr(percept, "content", "") or "")
            if content and self._normalize_user_message(content) in normalized_fact:
                eid = getattr(percept, "evidence_id", None) or getattr(percept, "id", None)
                ids.append(str(eid) if eid else f"percept:user_message:{getattr(percept, 'timestamp', '')}:{index}")
        return list(dict.fromkeys(ids or list(fallback)))[:8]

    def _frame_storage_permission(self, frame: CognitiveFrame) -> bool:
        permission = getattr(frame, "permission", None) or getattr(frame, "permission_report", None)
        if permission is None:
            return True
        value = getattr(permission, "memory_storable", None)
        if value is None and isinstance(permission, Mapping):
            value = permission.get("memory_storable")
        if value is None:
            return True
        return bool(value)

    def _looks_like_user_correction_text(self, text: str) -> bool:
        normalized = self._normalize_user_message(text)
        markers = (
            "khong phai",
            "không phải",
            "sai rồi",
            "sai roi",
            "thieu la",
            "thiếu là",
            "chưa đúng",
            "chua dung",
            "nhầm",
            "nham",
            "không đúng",
            "khong dung",
            "not what i mean",
            "wrong",
            "incorrect",
        )
        return any(self._normalize_user_message(marker) in normalized for marker in markers)

    # ------------------------------------------------------------------
    # Internal state commit request path
    # ------------------------------------------------------------------

    def _commit_internal_state_for_frame(
        self,
        frame: CognitiveFrame,
        *,
        snapshot=None,
        ti_report=None,
    ) -> None:
        """Tính internal_state_after, rồi tạo active_state request.

        Hàm cũ ghi state runtime trực tiếp. Bỏ. State sau turn
        phải đi qua StateCommitter như mọi memory/state khác. Nếu không, ta có
        hai đường ghi state song song, tức là tự đào hố rồi tự rơi xuống với vẻ
        mặt rất có hệ thống.
        """

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

        # Append ngay active_state request để kể cả caller chưa finalize vẫn có
        # request trong frame. `_finalize_cognitive_frame` sẽ dedupe trước commit.
        observation = self._observe_outcome_for_commit(frame)
        request = self._derive_active_state_request(
            frame,
            observation,
            storage_permission=self._frame_storage_permission(frame),
        )
        if request:
            self._append_commit_requests(frame, [request])

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

    # ------------------------------------------------------------------
    # Finalize + StateCommitter
    # ------------------------------------------------------------------

    def _liveliness_tracker(self) -> LivelinessTracker:
        tracker = getattr(self, "_liveliness_tracker_instance", None)
        if tracker is None:
            retention = 100
            cfg = getattr(self, "_liveliness_config", None)
            if cfg is not None:
                retention = int(getattr(cfg, "decision_retention", 100) or 100)
            tracker = LivelinessTracker(retention=retention)
            self._liveliness_tracker_instance = tracker
        return tracker

    def _record_liveliness_decision(self, frame: CognitiveFrame, final_text: str) -> None:
        """Emit one DecisionRecord per autonomous idle cycle (Req 5.5, 6)."""

        try:
            if str(getattr(frame, "channel", "") or "") not in {"autonomous", "background"}:
                return
            final = getattr(frame, "final_decision", {}) or {}
            parse_mode = str(final.get("parse_mode", "") if isinstance(final, Mapping) else "")
            animation = str(final.get("animation", "") if isinstance(final, Mapping) else "")
            text = (final_text or "").strip()

            seed_source = str(
                getattr(getattr(frame, "broadcast", None), "label", "") or ""
            ).strip() or "none"
            if text:
                emitted_kind = "grounded_line" if seed_source in GROUNDED_SOURCES else "spoken"
            elif animation:
                emitted_kind = "body_only"
            else:
                emitted_kind = "silence"

            no_seed_reason = ""
            if not text and parse_mode in {"no_speech", "ambient_silence"}:
                no_seed_reason = parse_mode

            record = DecisionRecord(
                cycle_id=str(getattr(frame, "cycle_id", "") or ""),
                emitted_kind=emitted_kind,
                seed_source=seed_source,
                seed_confidence=float(getattr(getattr(frame, "broadcast", None), "score", 0.0) or 0.0),
                candidate_count=0,
                grounding_evidence=(seed_source,) if seed_source != "none" else (),
                no_seed_reason=no_seed_reason,
                ambient_suppression=str(getattr(self, "_last_ambient_suppression_reason", "") or ""),
                text=text,
                timestamp=float(getattr(frame, "started_at", 0.0) or time.time()),
            )
            self._liveliness_tracker().record(record)
            # Reset the one-shot ambient suppression marker after recording.
            self._last_ambient_suppression_reason = ""
        except Exception:
            # Observability must never break the loop.
            pass

    def _finalize_cognitive_frame(self, frame: CognitiveFrame) -> None:
        final_text = str((getattr(frame, "final_decision", {}) or {}).get("text", "") if isinstance(getattr(frame, "final_decision", {}), dict) else "")
        if final_text.strip():
            self.semantic_repeat_guard.remember(final_text, timestamp=float(getattr(frame, "started_at", 0.0) or time.time()))
            family = str(getattr(getattr(frame, "meaning_layer", None), "semantic_family", "") or "")
            if family:
                self.recent_meaning_families = (*tuple(getattr(self, "recent_meaning_families", ()) or ()), family)[-8:]

        self._record_liveliness_decision(frame, final_text)

        self.last_cognitive_frame = frame
        self.cognitive_frames.append(frame)
        self.cognitive_frames = self.cognitive_frames[-12:]

        # Derive request trước, commit sau. Không có đường ghi memory phụ.
        self._observe_outcome_for_frame(frame)
        self._start_epistemic_episode(frame)
        self._reflect_self_observation_for_frame(frame)
        self._append_self_observation_repair_request(frame)
        # Khép vòng canonical V3 bằng đúng final_decision/grounding/execution/outcome
        # production vừa xảy ra. Không chạy lại cognition, không sinh quyết định thứ hai.
        finalize_v3 = getattr(self, "_finalize_v3_cognitive_frame", None)
        if callable(finalize_v3):
            finalize_v3(frame)
        self._remember_cognitive_frame(frame)
        self._dedupe_frame_commit_requests(frame)
        commit_report = self._commit_frame_through_state_committer(frame)
        self._sync_after_state_commit(frame, commit_report)

        self.logger.info(
            "[cognitive_frame] id=%s | channel=%s | broadcast=%s:%.2f | speech=%s/%s | appraisal=%s | action=%s/%s | final=%s | commits=%s/%s rejected=%s errors=%s",
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
            getattr(commit_report, "committed", 0) if commit_report else 0,
            getattr(commit_report, "requested", 0) if commit_report else 0,
            getattr(commit_report, "rejected", 0) if commit_report else 0,
            getattr(commit_report, "errors", 0) if commit_report else 0,
        )

    def _start_epistemic_episode(self, frame: CognitiveFrame) -> Any:
        kernel = getattr(self, "epistemic_kernel", None)
        if kernel is None:
            return None
        try:
            from .epistemic_bridge import start_episode
            return start_episode(kernel, frame)
        except Exception as exc:
            self.logger.warning("Epistemic V2 episode failed: %s", exc, exc_info=True)
            return None

    def _observe_outcome_for_frame(self, frame: CognitiveFrame) -> Any:
        observer = self._get_outcome_observer()
        if observer is None or not callable(getattr(observer, "observe", None)):
            return getattr(frame, "outcome", None)
        try:
            outcome = observer.observe(frame)
            self._feed_private_mind_outcome(outcome, frame=frame)
            return outcome
        except Exception as exc:
            self.logger.warning("OutcomeObserver.observe(frame) loi: %s", exc, exc_info=True)
            return getattr(frame, "outcome", None)

    def _feed_private_mind_outcome(self, outcome: Any, *, frame: CognitiveFrame | None = None) -> tuple[dict[str, Any], ...]:
        daemon = getattr(self, "private_mind_daemon", None)
        recorder = getattr(daemon, "record_outcome", None) if daemon is not None else None
        if callable(recorder):
            try:
                reports = tuple(recorder(outcome, frame=frame) or ())
            except Exception as exc:
                try:
                    self.logger.warning("PrivateMind outcome feedback error: %s", exc)
                except Exception:
                    pass
                return ()
        else:
            loop = getattr(self, "private_mind_loop", None)
            store = getattr(loop, "concern_store", None) if loop is not None else None
            updater = getattr(store, "update_from_outcome", None)
            if not callable(updater):
                return ()
            surface_outcome = None
            if frame is not None:
                surface_outcome = {
                    "channel": str(getattr(frame, "channel", "") or ""),
                    "cycle_id": str(getattr(frame, "cycle_id", "") or ""),
                    "debug_notes": list(getattr(frame, "debug_notes", []) or [])[-8:],
                    "final_decision": dict(getattr(frame, "final_decision", {}) or {}),
                }
            try:
                reports = tuple(updater(outcome, surface_outcome=surface_outcome) or ())
            except Exception as exc:
                try:
                    self.logger.warning("PrivateMind outcome feedback error: %s", exc)
                except Exception:
                    pass
                return ()
        if reports and frame is not None:
            try:
                frame.debug_notes.append(f"private_mind_outcome_feedback={len(reports)}")
            except Exception:
                pass
        digest_owner = getattr(self, "private_mind_daemon", None) or getattr(self, "private_mind_loop", None)
        digest_fn = getattr(digest_owner, "digest", None) if digest_owner is not None else None
        if callable(digest_fn):
            try:
                self.private_mind_digest = digest_fn(surface_queue=getattr(self, "private_mind_surface_queue", None))
            except Exception:
                pass
        return reports

    def _reflect_self_observation_for_frame(self, frame: CognitiveFrame) -> Any:
        observer = self._get_self_observer()
        if observer is None or not callable(getattr(observer, "reflect", None)):
            return getattr(frame, "self_observation", None)
        try:
            return observer.reflect(frame, outcome=getattr(frame, "outcome", None))
        except Exception as exc:
            self.logger.warning("SelfObserver.reflect(frame) loi: %s", exc, exc_info=True)
            return getattr(frame, "self_observation", None)

    def _append_self_observation_repair_request(self, frame: CognitiveFrame) -> Any:
        observer = self._get_self_observer()
        append_repair = getattr(observer, "append_repair_commit_request", None) if observer is not None else None
        if not callable(append_repair):
            return None
        try:
            return append_repair(
                frame,
                report=getattr(frame, "self_observation", None),
                evidence_ids=self._frame_evidence_ids(frame),
            )
        except Exception as exc:
            self.logger.warning("SelfObserver repair request loi: %s", exc, exc_info=True)
            return None

    def _get_outcome_observer(self) -> Any:
        existing = getattr(self, "outcome_observer", None)
        if existing is not None and callable(getattr(existing, "observe", None)):
            return existing
        try:
            from .outcome_observer import OutcomeObserver
        except Exception:
            try:
                from runtime.outcome_observer import OutcomeObserver
            except Exception as exc:
                self.logger.warning("Khong import duoc OutcomeObserver: %s", exc)
                return None
        observer = OutcomeObserver()
        try:
            self.outcome_observer = observer
        except Exception:
            pass
        return observer

    def _get_self_observer(self) -> Any:
        existing = getattr(self, "self_observer", None)
        if existing is not None and callable(getattr(existing, "reflect", None)):
            return existing
        try:
            from cortex.self_observation import SelfObservationEngine
        except Exception:
            try:
                from src.cortex.self_observation import SelfObservationEngine
            except Exception as exc:
                self.logger.warning("Khong import duoc SelfObservationEngine: %s", exc)
                return None
        observer = SelfObservationEngine()
        try:
            self.self_observer = observer
        except Exception:
            pass
        return observer

    def _commit_frame_through_state_committer(self, frame: CognitiveFrame) -> Any:
        """Gọi StateCommitter.commit(frame), không gọi memory core trực tiếp."""

        committer = self._get_state_committer()
        if committer is None:
            self.logger.warning("Không có StateCommitter/MemoryCognitionCore; bỏ state commit cho frame=%s", frame.cycle_id)
            return None

        try:
            requests = list(getattr(frame, "commit_requests", ()) or ())
            if not requests:
                try:
                    requests = self._derive_state_commit_requests(frame)
                    self._append_commit_requests(frame, requests)
                    self._dedupe_frame_commit_requests(frame)
                except Exception:
                    requests = []
            if callable(getattr(committer, "commit", None)):
                report = committer.commit(frame)
            elif requests and callable(getattr(committer, "commit_requests", None)):
                report = committer.commit_requests(requests, frame=frame)
            else:
                report = None
        except Exception as exc:
            self.logger.warning("StateCommitter.commit(frame) lỗi: %s", exc, exc_info=True)
            return None

        rejected = [decision for decision in getattr(report, "decisions", ()) if getattr(decision, "status", "") == "rejected"]
        if rejected:
            self.logger.info(
                "[cognitive_frame] state commits rejected=%s/%s first=%s",
                len(rejected),
                getattr(report, "requested", len(getattr(report, "decisions", ()))) or 0,
                getattr(rejected[0], "reason", "unknown"),
            )
        return report

    def _get_state_committer(self) -> Any:
        """Lấy hoặc tạo StateCommitter từ MemoryCognitionCore."""

        existing = getattr(self, "state_committer", None)
        if existing is not None and callable(getattr(existing, "commit", None)):
            return existing

        memory_cognition = (
            getattr(self, "memory_cognition", None)
            or getattr(self, "memory_cognition_core", None)
            or getattr(self, "memory_core", None)
        )
        if memory_cognition is None:
            return None

        try:
            from .state_committer import StateCommitter
        except Exception:
            try:
                from runtime.state_committer import StateCommitter
            except Exception as exc:
                self.logger.warning("Không import được StateCommitter: %s", exc)
                return None

        try:
            committer = StateCommitter(
                memory_cognition,
                logger=self.logger,
                epistemic_kernel=getattr(self, "epistemic_kernel", None),
            )
        except Exception as exc:
            self.logger.warning("Không tạo được StateCommitter: %s", exc)
            return None
        try:
            self.state_committer = committer
        except Exception:
            pass
        return committer

    def _sync_after_state_commit(self, frame: CognitiveFrame, report: Any) -> None:
        """Đồng bộ cache đọc sau commit, không ghi memory trực tiếp.

        `long_term_memory` là cache prompt context, nên refresh nó sau commit nếu
        helper recall tồn tại. Không ghi file state ở đây.
        """

        if report is None:
            return
        if callable(getattr(self, "_memory_recall_texts", None)):
            try:
                self.long_term_memory = self._memory_recall_texts()
            except Exception as exc:
                self.logger.debug("Không refresh được long_term_memory sau commit: %s", exc)

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _safe_state_payload(self, state: Any) -> Any:
        if hasattr(state, "to_dict") and callable(getattr(state, "to_dict")):
            try:
                return state.to_dict()
            except Exception:
                pass
        if hasattr(state, "__dict__"):
            try:
                return dict(state.__dict__)
            except Exception:
                pass
        return repr(state)

    def _repair_strategy_for_failure(self, failure_type: str, mode: str) -> str:
        if mode == "relational_repair":
            return "acknowledge rupture briefly, lower overread, answer current need without ending in a question"
        strategies = {
            "underacted": "execute the missing requested action first before explaining",
            "overexplained": "compress answer and avoid rebuilding the whole frame",
            "wrong_abstraction": "answer at the concrete level requested by user",
            "tone_mismatch": "lower intensity and match user register before expanding",
            "overread": "avoid expressing psychological inference without stronger evidence",
            "misread": "discard the wrong frame and restate the corrected intent briefly",
        }
        return strategies.get(failure_type, "prioritize user correction and avoid repeating the same failed frame")

    def _future_suppression_rule_for_failure(self, failure_type: str, mode: str) -> str:
        if mode == "relational_repair":
            return "do not ask the user to re-explain an already stated relational hurt"
        rules = {
            "underacted": "suppress long rationale until the requested missing action is done",
            "overexplained": "suppress architecture expansion when user asks for direct patch",
            "wrong_abstraction": "suppress symbolic interpretation during concrete technical request",
            "tone_mismatch": "suppress teasing when correction or frustration is active",
            "overread": "suppress direct mental-state claims unless confidence is high",
            "misread": "suppress reuse of invalidated assistant frame after user denial",
        }
        return rules.get(failure_type, "suppress repeated failed response pattern")

    def _dedupe_frame_commit_requests(self, frame: CognitiveFrame) -> None:
        requests = list(getattr(frame, "commit_requests", ()) or ())
        if not requests:
            return
        deduped = self._dedupe_commit_requests(requests)
        try:
            frame.commit_requests = deduped
        except Exception:
            pass

    def _dedupe_commit_requests(self, requests: Sequence[Any]) -> list[Any]:
        deduped: list[Any] = []
        seen: set[tuple[str, str, tuple[str, ...]]] = set()
        for request in requests:
            key = self._commit_request_key(request)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(request)
        return deduped

    def _existing_commit_request_keys(self, requests: Sequence[Any]) -> set[tuple[str, str, tuple[str, ...]]]:
        return {self._commit_request_key(request) for request in requests}

    def _commit_request_field(self, request: Any, field_name: str, default: Any = None) -> Any:
        if isinstance(request, Mapping):
            return request.get(field_name, default)
        return getattr(request, field_name, default)

    def _commit_request_key(self, request: Any) -> tuple[str, str, tuple[str, ...]]:
        target = str(self._commit_request_field(request, "target", ""))
        content = self._commit_request_field(request, "content", "")
        evidence_ids = self._commit_request_field(request, "evidence_ids", ()) or ()
        if isinstance(content, str):
            content_key = " ".join(content.split())[:512]
        else:
            content_key = repr(content)[:512]
        return target, content_key, tuple(sorted(str(eid) for eid in evidence_ids if str(eid).strip()))

    def _next_cognitive_cycle_id(self, channel: str) -> str:
        self.cognitive_cycle_index += 1
        return f"{channel}-{self.cognitive_cycle_index}"

    def _bounded_float(self, value: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
        return max(minimum, min(maximum, float(value)))

    # _event_timestamp là hàm tạo mốc thời gian dạng chuỗi để gắn cho event/percept.
    def _event_timestamp(self, snapshot=None, *, started_at: float | None = None) -> str:
        captured_at = str(getattr(snapshot, "captured_at", "") or getattr(snapshot, "time", "") or "").strip()
        if captured_at:
            return captured_at
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started_at or time.time()))

    # Chống spam evidence, tránh trùng lặp và giữ payload gọn khi log/telemetry.
    def _decision_to_frame_dict(self, decision: Decision | None) -> dict[str, object]:
        if decision is None:
            return {}
        payload = {
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
        if decision.parse_mode == "source_grounding_preempt":
            trace = str(decision.debug_trace or "")
            for part in trace.split(";"):
                if part.startswith("preempt="):
                    payload["grounding_preempt_mode"] = part.removeprefix("preempt=") or ""
                    break
            for part in trace.split(";"):
                if payload.get("grounding_preempt_mode"):
                    break
                if part.startswith("source="):
                    payload["grounding_preempt_mode"] = part.removeprefix("source=") or ""
                    break
        return payload

    def _set_cognitive_memory_update(
        self,
        frame: CognitiveFrame,
        *,
        decision: Decision | None = None,
        notes: tuple[str, ...] = (),
    ) -> None:
        remembered_fact = (decision.extracted_fact if decision else "") or ""
        repair_meta = {}
        try:
            repair_meta = dict((getattr(frame, "metadata", {}) or {}).get("dual_axis_repair", {}) or {})
        except Exception:
            repair_meta = {}
        if bool(repair_meta.get("blocks_assistant_fact_commit", False)):
            # Claim assistant đang rút không được sống lại qua CognitiveFrame.
            remembered_fact = ""
            if decision is not None:
                decision.extracted_fact = ""
        ephemeral_presence = False
        if decision is not None:
            parse_mode = str(getattr(decision, "parse_mode", "") or "")
            intent = str(getattr(decision, "intent", "") or "")
            tags = {str(item) for item in (getattr(decision, "reasoning_tags", ()) or ()) if str(item).strip()}
            ephemeral_presence = (
                parse_mode in {
                    "presence_maintenance",
                    "presence_maintenance_body_only",
                    "micro_presence",
                    "micro_observation",
                    "micro_observation_body_only",
                    "re_engagement_body_only",
                    "guard_body_only",
                    "no_speech_policy",
                }
                or intent in {"presence_maintenance", "micro_presence", "micro_observation", "body_only_guard_repair"}
                or "micro_presence" in tags
            )
            grounding = getattr(frame, "source_grounding", None) or getattr(frame, "grounding", None)
            if ephemeral_presence or parse_mode in {"no_speech_policy", "semantic_repair_failed", "source_grounding_guard"}:
                remembered_fact = ""
            elif grounding is not None and not bool(getattr(grounding, "memory_answer_allowed", True)):
                # Nếu turn này đang cần evidence hiện tại, extracted_fact từ model rất dễ là memory giả làm mắt.
                # Cho StateCommitter reject là tốt, nhưng đừng đẩy thêm mồi semantic vào frame nếu đã biết nguy cơ.
                remembered_fact = ""
        norm_deviation = " | ".join(
            percept.content
            for percept in tuple(frame.percepts or ())
            if percept.kind == "norm_deviation" and percept.content
        )[:220]
        frame.memory_update = CognitiveMemoryUpdate(
            remembered_fact=remembered_fact,
            remembered_style_excerpt="" if ephemeral_presence else ((decision.text if decision else "")[:140] if decision else ""),
            last_text=(self.last_text or "")[:140],
            system_action=(decision.system_action if decision else "") or "",
            notes=tuple((
                *notes,
                *(("ephemeral_presence_signal_buffer_only",) if ephemeral_presence else ()),
                *(("assistant_fact_commit_blocked_by_dual_axis_repair",) if bool(repair_meta.get("blocks_assistant_fact_commit", False)) else ()),
            )),
            semantic_fact=remembered_fact,
            norm_deviation=norm_deviation,
            relationship_reflection=getattr(frame.memory_update, "relationship_reflection", ""),
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
