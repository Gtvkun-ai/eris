from __future__ import annotations

from collections.abc import Mapping
import json
import os
import random
import re
import threading
import time
import traceback
import unicodedata
from dataclasses import dataclass, replace

from cortex.contracts import (
    AgentSpeechCore,
    AttentionCandidate,
    CognitiveActionPlan,
    CognitiveAppraisal,
    CognitiveBroadcast,
    CognitiveDisturbance,
    CognitiveFrame,
    InnerThought,
    CognitiveMemoryUpdate,
    MeaningLayerResult,
    PersonalityLensResult,
    PerceptEvent,
    SessionRitualReport,
    SilenceState,
    SubconsciousReport,
    ThoughtStreamReport,
    TiPolicyReport,
)
from cortex.internal_state import PersistentInternalState
from memory.memory_commit_policy import MemoryCommitPolicy
from memory.memory_models import MemoryKind
from cortex.relationship_dynamics import RelationshipTurnEvent
from core.evidence import EvidenceItem, RawSignal
from cortex.modes import QUIET_MODES
from cortex.ni import NiStateMachine
from domain import Decision
from failure_meta import is_technical_failure_meta
from runtime.body_bias import BodyBiasProjector
from runtime.memory_recall_adapter import MemoryRecallAdapter
from runtime.relational_voice_seed_adapter import RelationalVoiceSeedAdapter
from runtime.affect_self_read import AffectSelfReadAdapter
from runtime.presence_controller import SocialPresenceEvent
from runtime.public_turn_ledger import PublicTurnLedger, infer_public_turn_channel, normalize_public_turn_channel
from runtime.session_turn_ledger import SessionTurnLedger
from runtime.speech_pipeline import SpeechIntentDecision




def _is_nonsemantic_fallback_decision(decision: Decision) -> bool:
    """True nếu decision chỉ là fallback kỹ thuật, không phải answer nội dung.

    Chú thích kiến trúc: public_turn có thể ghi để user thấy, nhưng semantic
    history/TurnGraph không được coi các câu này là bằng chứng hội thoại.
    """

    intent = str(getattr(decision, "intent", "") or "")
    parse_mode = str(getattr(decision, "parse_mode", "") or "")
    debug_trace = str(getattr(decision, "debug_trace", "") or "")
    text = str(getattr(decision, "text", "") or "").lower()
    fallback_intents = {"fallback_reply", "format_repair_fallback", "service_error", "no_fallback_block"}
    fallback_modes = {"format_repair_fallback", "service_error", "no_fallback_block"}
    if is_technical_failure_meta(getattr(decision, "failure_meta", None)):
        return True
    if intent in fallback_intents or parse_mode in fallback_modes:
        return True
    if "http_5xx_fallback" in debug_trace or "format_violation_recovered" in debug_trace:
        return True
    return "lỗi định dạng" in text or "loi dinh dang" in text or "vấn đề đường truyền" in text


class StateCommitServiceMixin:
    def _memory_kernel(self):
        return getattr(self, "memory_kernel", None)

    def _ensure_session_turn_ledger(self) -> SessionTurnLedger:
        ledger = getattr(self, "session_turn_ledger", None)
        if isinstance(ledger, SessionTurnLedger):
            return ledger
        ledger = SessionTurnLedger()
        self.session_turn_ledger = ledger
        return ledger

    def _ensure_memory_commit_policy(self) -> MemoryCommitPolicy:
        policy = getattr(self, "memory_commit_policy", None)
        parser = getattr(self, "memory_semantic_parser", None)
        if isinstance(policy, MemoryCommitPolicy):
            if parser is not None and getattr(policy, "semantic_parser", None) is not parser:
                policy.set_semantic_parser(parser)
            return policy
        policy = MemoryCommitPolicy()
        if parser is not None:
            policy.set_semantic_parser(parser)
        self.memory_commit_policy = policy
        return policy

    def _ensure_memory_fast_commit_policy(self) -> MemoryCommitPolicy:
        """Policy nóng không gọi model semantic parser.

        Khi background memory digest đang bật, hot path chỉ nên giữ các fact/rule
        rẻ và rõ. Phần phân rã sâu bằng model.gguf chạy ở worker nền. Nếu không
        tách đường này, user phải ngồi chờ memory nhai xong rồi mới được nghe câu
        trả lời, một nghi lễ UX không ai yêu cầu.
        """

        policy = getattr(self, "memory_fast_commit_policy", None)
        if isinstance(policy, MemoryCommitPolicy):
            return policy
        policy = MemoryCommitPolicy()
        self.memory_fast_commit_policy = policy
        return policy

    def _background_memory_digest_enabled(self) -> bool:
        service = getattr(self, "background_memory_digest", None)
        return bool(service is not None and getattr(service, "enabled", False))

    def _enqueue_background_memory_digest(self, user_text: str, *, turn_id: str = "", source: str = "chat_turn", priority: str = "normal", context: dict | None = None) -> bool:
        service = getattr(self, "background_memory_digest", None)
        if service is None or not bool(getattr(service, "enabled", False)):
            return False
        enqueue = getattr(service, "enqueue_user_turn", None)
        if not callable(enqueue):
            return False
        try:
            return bool(enqueue(user_text, turn_id=turn_id, source=source, priority=priority, context=context))
        except Exception as exc:
            self.logger.warning("[memory digest] enqueue failed: %s", exc)
            return False

    def _set_background_memory_digest_remote_inflight(self, inflight: bool) -> None:
        service = getattr(self, "background_memory_digest", None)
        marker = getattr(service, "notify_remote_inflight", None)
        if callable(marker):
            try:
                marker(bool(inflight))
            except Exception:
                return

    def _memory_snapshot_for_lookup(self):
        core = getattr(self, "memory_core", None)
        loader = getattr(core, "load", None)
        if callable(loader):
            try:
                snapshot = loader()
            except Exception as exc:
                self.logger.warning("Memory snapshot load for recall failed: %s", exc)
            else:
                if snapshot is not None:
                    return snapshot
        return getattr(self, "memory_state", None)

    def _memory_snapshot_items(self, snapshot, collection_name: str) -> tuple[object, ...]:
        if snapshot is None:
            return ()
        if isinstance(snapshot, Mapping):
            items = snapshot.get(collection_name) or ()
        else:
            items = getattr(snapshot, collection_name, ()) or ()
        if isinstance(items, (list, tuple)):
            return tuple(items)
        return (items,)

    @staticmethod
    def _record_value(record: object, field_name: str, default=None):
        if isinstance(record, Mapping):
            return record.get(field_name, default)
        return getattr(record, field_name, default)

    def _record_metadata(self, record: object) -> dict[str, object]:
        metadata = self._record_value(record, "metadata", {}) or {}
        return dict(metadata) if isinstance(metadata, Mapping) else {}

    @staticmethod
    def _clean_memory_value(value: object) -> str:
        return str(value or "").strip().strip(" .,:;!?\"'“”")

    def _extract_semantic_value_from_record(self, record: object, kind: MemoryKind) -> str | None:
        metadata = self._record_metadata(record)
        fact_key = self._fact_key_for_memory_kind(kind)
        record_fact_key = str(metadata.get("fact_key") or self._record_value(record, "fact_key", "") or "").strip()
        if fact_key and record_fact_key and record_fact_key != fact_key:
            return None
        for direct_value in (metadata.get("value"), metadata.get("current_value")):
            if direct_value:
                return self._clean_memory_value(direct_value)

        raw_content = metadata.get("raw_content")
        if isinstance(raw_content, Mapping):
            raw_kind = str(raw_content.get("kind", "") or "").strip()
            if raw_kind == kind.value:
                raw_meta = raw_content.get("metadata")
                if isinstance(raw_meta, Mapping):
                    value = raw_meta.get("value")
                    if value:
                        return self._clean_memory_value(value)
                value = raw_content.get("value")
                if value:
                    return self._clean_memory_value(value)

        direct_kind = str(self._record_value(record, "kind", "") or metadata.get("kind", "") or "").strip()
        if direct_kind and direct_kind != kind.value:
            return None

        claim_text = " ".join(
            str(part or "").strip()
            for part in (
                self._record_value(record, "claim", ""),
                self._record_value(record, "content", ""),
                self._record_value(record, "surface", ""),
            )
            if str(part or "").strip()
        )
        lowered = claim_text.lower()

        if kind == MemoryKind.USER_NAME:
            patterns = (
                r"user'?s name is\s+(.+?)(?:[.!,;:]|$)",
                r"ten .* la\s+(.+?)(?:[.!,;:]|$)",
            )
        elif kind == getattr(MemoryKind, "USER_NICKNAME", None):
            patterns = (
                r"user'?s nickname is\s+(.+?)(?:[.!,;:]|$)",
                r"biet danh .* la\s+(.+?)(?:[.!,;:]|$)",
            )
        elif kind == MemoryKind.USER_BIRTH_MONTH:
            patterns = (
                r"birth month is\s+(\d{1,2})",
                r"thang sinh .* la thang\s+(\d{1,2})",
            )
        else:
            return None

        for pattern in patterns:
            match = re.search(pattern, lowered, flags=re.IGNORECASE)
            if not match:
                continue
            value = self._clean_memory_value(claim_text[match.start(1):match.end(1)])
            if value:
                return value
        return None

    def _semantic_memory_lookup(self, kind: MemoryKind):
        snapshot = self._memory_snapshot_for_lookup()
        candidates: list[tuple[tuple[float, float, float, str], str]] = []
        for record in self._memory_snapshot_items(snapshot, "semantic_memory"):
            value = self._extract_semantic_value_from_record(record, kind)
            if value:
                candidates.append((self._semantic_record_rank(record), value))
        if candidates:
            return max(candidates, key=lambda item: item[0])[1]
        return None

    @staticmethod
    def _fact_key_for_memory_kind(kind: MemoryKind) -> str:
        if kind == MemoryKind.USER_NAME:
            return "user.name"
        if kind == getattr(MemoryKind, "USER_NICKNAME", None):
            return "user.nickname"
        if kind == MemoryKind.USER_BIRTH_MONTH:
            return "user.birth_month"
        if kind == MemoryKind.USER_RESPONSE_STYLE:
            return "user.response_style"
        return ""

    def _semantic_record_rank(self, record: object) -> tuple[float, float, float, str]:
        metadata = self._record_metadata(record)
        status = str(self._record_value(record, "status", "") or metadata.get("status", "") or "").strip()
        status_rank = {"active": 2.0, "tentative": 1.0}.get(status, 0.5)
        updated_text = str(
            self._record_value(record, "updated_at", "")
            or metadata.get("updated_at", "")
            or metadata.get("last_accessed_at", "")
            or ""
        )
        updated_rank = 0.0
        if updated_text:
            try:
                updated_rank = time.mktime(time.strptime(updated_text, "%Y-%m-%dT%H:%M:%S%z"))
            except Exception:
                updated_rank = 0.0
        try:
            confidence = float(self._record_value(record, "confidence", metadata.get("confidence", 0.0)) or 0.0)
        except Exception:
            confidence = 0.0
        return (status_rank, updated_rank, confidence, str(self._record_value(record, "id", "") or ""))

    def _episodic_memory_lookup(self, query: str):
        recall = getattr(getattr(self, "memory_core", None), "recall", None)
        if callable(recall):
            try:
                packet = recall(query or "")
            except Exception as exc:
                self.logger.warning("Episodic recall lookup failed: %s", exc)
            else:
                episodic = tuple(getattr(packet, "episodic", ()) or ())
                if episodic:
                    return str(episodic[0] or "")

        snapshot = self._memory_snapshot_for_lookup()
        records = self._memory_snapshot_items(snapshot, "episodic_memory")
        if not records:
            return None

        tokens = set(re.findall(r"[a-z0-9]+", str(query or "").lower()))
        scored: list[tuple[int, str]] = []
        for record in records:
            text = " ".join(
                str(part or "").strip()
                for part in (
                    self._record_value(record, "summary", ""),
                    self._record_value(record, "content", ""),
                    self._record_value(record, "scene", ""),
                    self._record_metadata(record).get("gist", ""),
                )
                if str(part or "").strip()
            )
            if not text:
                continue
            if not tokens:
                scored.append((1, text))
                continue
            lowered = text.lower()
            overlap = sum(1 for token in tokens if token in lowered)
            if overlap:
                scored.append((overlap, text))

        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    def _ensure_memory_recall_adapter(self) -> MemoryRecallAdapter:
        adapter = getattr(self, "memory_recall_adapter", None)
        if isinstance(adapter, MemoryRecallAdapter):
            adapter.ledger = self._ensure_session_turn_ledger()
            adapter.memory_core = getattr(self, "memory_core", None)
            adapter.memory_kernel = self._memory_kernel()
            adapter.llm_service = getattr(self, "llm_service", None)
            adapter.semantic_lookup = self._semantic_memory_lookup
            adapter.episodic_lookup = self._episodic_memory_lookup
            adapter.compiler = None
            return adapter
        adapter = MemoryRecallAdapter(
            ledger=self._ensure_session_turn_ledger(),
            memory_core=getattr(self, "memory_core", None),
            memory_kernel=self._memory_kernel(),
            llm_service=getattr(self, "llm_service", None),
            semantic_lookup=self._semantic_memory_lookup,
            episodic_lookup=self._episodic_memory_lookup,
        )
        self.memory_recall_adapter = adapter
        return adapter

    def _build_memory_recall_decision(self, user_text: str) -> Decision | None:
        return self._ensure_memory_recall_adapter().try_answer(user_text)

    def _ensure_relational_voice_seed_adapter(self) -> RelationalVoiceSeedAdapter:
        adapter = getattr(self, "relational_voice_seed_adapter", None)
        if isinstance(adapter, RelationalVoiceSeedAdapter):
            adapter.llm_service = getattr(self, "llm_service", None)
            adapter.logger = getattr(self, "logger", None)
            return adapter
        adapter = RelationalVoiceSeedAdapter(
            llm_service=getattr(self, "llm_service", None),
            logger=getattr(self, "logger", None),
        )
        self.relational_voice_seed_adapter = adapter
        return adapter

    def _ensure_affect_self_read_adapter(self) -> AffectSelfReadAdapter:
        adapter = getattr(self, "affect_self_read_adapter", None)
        if isinstance(adapter, AffectSelfReadAdapter):
            adapter.llm_service = getattr(self, "llm_service", None)
            adapter.logger = getattr(self, "logger", None)
            return adapter
        adapter = AffectSelfReadAdapter(
            llm_service=getattr(self, "llm_service", None),
            logger=getattr(self, "logger", None),
        )
        self.affect_self_read_adapter = adapter
        return adapter

    def _frame_memory_storage_permission(self, frame) -> bool:
        permission = getattr(frame, "permission", None) or getattr(frame, "permission_report", None)
        if permission is None:
            return True
        if isinstance(permission, Mapping):
            value = permission.get("memory_storable")
        else:
            value = getattr(permission, "memory_storable", None)
        if value is None:
            return True
        return bool(value)

    def _user_turn_memory_evidence_id(self, *, frame=None, turn_id: str | None = None) -> str | None:
        if turn_id:
            return str(turn_id)
        turns = self._ensure_session_turn_ledger().user_turns()
        if turns:
            return f"session_turn:{turns[-1].index}"
        frame_id = str(getattr(frame, "frame_id", "") or getattr(frame, "id", "") or "").strip()
        if frame_id:
            return f"frame:{frame_id}"
        return None

    def _ingest_user_turn_via_memory_kernel(self, frame, user_text: str, *, turn_id: str | None = None) -> bool:
        kernel = self._memory_kernel()
        ingest = getattr(kernel, "ingest", None)
        if not callable(ingest):
            return False

        evidence_id = self._user_turn_memory_evidence_id(frame=frame, turn_id=turn_id)
        try:
            ingest(
                user_text,
                evidence_ids=[evidence_id] if evidence_id else None,
                turn_id=evidence_id,
                source="chat_turn",
                mode="fast",
                allow_candidate=False,
                storage_permission=self._frame_memory_storage_permission(frame),
                permission_required=False,
                context={
                    "frame_id": str(getattr(frame, "frame_id", "") or getattr(frame, "id", "") or "").strip(),
                    "channel": str(getattr(frame, "channel", "") or "").strip(),
                },
            )
            return True
        except Exception as exc:
            self.logger.warning("MemoryKernel ingest failed on hot path, falling back to commit policy: %s", exc)
            return False

    def _add_user_turn_memory_commit_requests(self, frame, user_text: str, *, turn_id: str | None = None) -> None:
        if frame is None:
            return
        if self._ingest_user_turn_via_memory_kernel(frame, user_text, turn_id=turn_id):
            return
        evidence_id = self._user_turn_memory_evidence_id(frame=frame, turn_id=turn_id)
        # Nếu worker nền đang bật, hot path dùng policy không model để tránh block trước
        # remote API. Semantic digestion sâu sẽ chạy song song qua background_memory_digest.
        policy = self._ensure_memory_fast_commit_policy() if self._background_memory_digest_enabled() else self._ensure_memory_commit_policy()
        decisions = policy.decide_from_user_turn(user_text, turn_id=evidence_id)
        if not decisions:
            return
        storage_permission = self._frame_memory_storage_permission(frame)

        add_commit_request = getattr(frame, "add_commit_request", None)
        if callable(add_commit_request):
            for decision in decisions:
                request = decision.to_state_commit_request(
                    storage_permission=storage_permission,
                    permission_required=False,
                )
                try:
                    add_commit_request(request, actor="memory_commit_policy")
                except TypeError:
                    add_commit_request(request)
            return

        existing = list(getattr(frame, "commit_requests", []) or [])
        for decision in decisions:
            existing.append(
                decision.to_state_commit_request(
                    storage_permission=storage_permission,
                    permission_required=False,
                )
            )
        try:
            frame.commit_requests = existing
        except Exception:
            return

    def _load_memory_state(self):
        core = getattr(self, "memory_core", None)
        loader = getattr(core, "load", None)
        if not callable(loader):
            return None
        try:
            return loader()
        except Exception as exc:
            self.logger.warning("Memory state load error: %s", exc)
            return None
    def _has_structured_memory_core(self) -> bool:
        core = getattr(self, "memory_core", None)
        return callable(getattr(core, "commit", None))
    def _ensure_internal_state(self) -> None:
        if self.memory_state is None:
            return
        if isinstance(self.memory_state, dict):
            self.memory_state.setdefault("internal_state", self._load_internal_state_payload())
            return
        # Nếu có memory nhưng chưa có internal state:
        if getattr(self.memory_state, "internal_state", None) is None:
            self.memory_state.internal_state = PersistentInternalState()
    def _apply_debug_overrides(self, state: PersistentInternalState) -> PersistentInternalState:
        overrides = getattr(self, "_debug_overrides", None)
        if not overrides:
            return state

        # Clean up expired overrides (older than 30 seconds)
        now = time.time()
        expired_keys = []
        for key, val in overrides.items():
            if isinstance(val, tuple) and len(val) == 2:
                _, timestamp = val
                if now - timestamp > 30.0:
                    expired_keys.append(key)
        for key in expired_keys:
            try:
                del overrides[key]
            except KeyError:
                pass

        if not overrides:
            return state

        from dataclasses import replace, is_dataclass
        affect_overrides = {}
        rel_overrides = {}
        for key, val in overrides.items():
            actual_val = val[0] if (isinstance(val, tuple) and len(val) == 2) else val
            if key.startswith("rel_"):
                rel_overrides[key[4:]] = actual_val
            else:
                affect_overrides[key] = actual_val

        if affect_overrides:
            state = replace(state, **{k: v for k, v in affect_overrides.items() if hasattr(state, k)})

        if rel_overrides and getattr(state, "relationship_dynamics", None) is not None:
            rel = getattr(state, "relationship_dynamics")
            if is_dataclass(rel):
                new_rel = replace(rel, **{k: v for k, v in rel_overrides.items() if hasattr(rel, k)})
                state = replace(state, relationship_dynamics=new_rel)

        return state

    def _get_internal_state(self) -> PersistentInternalState:
        state = None
        if isinstance(self.memory_state, dict):
            payload = self.memory_state.get("internal_state") or self._load_internal_state_payload()
            if isinstance(payload, dict):
                try:
                    state = PersistentInternalState.from_dict(payload)
                except Exception:
                    state = PersistentInternalState()
        if state is None:
            if self.memory_state is not None and getattr(self.memory_state, "internal_state", None) is not None:
                state = self.memory_state.internal_state
            else:
                state = PersistentInternalState()
        return self._apply_debug_overrides(state)

    def _set_internal_state(self, state: PersistentInternalState) -> None:
        if self.memory_state is None:
            return
        state = self._apply_debug_overrides(state)
        with self._state_lock:
            if isinstance(self.memory_state, dict):
                self.memory_state["internal_state"] = state.to_dict() if callable(getattr(state, "to_dict", None)) else dict(getattr(state, "__dict__", {}) or {})
                self._save_memory_state()
                return
            self.memory_state.internal_state = state
            self._save_memory_state()
    def _load_internal_state_payload(self) -> dict[str, object]:
        core = getattr(self, "memory_core", None)
        active_loader = getattr(core, "load_active_state", None)
        if callable(active_loader):
            try:
                active = active_loader()
                metadata = getattr(active, "metadata", {}) or {}
                payload = metadata.get("internal_state")
                return dict(payload) if isinstance(payload, dict) else {}
            except Exception:
                return {}
        return {}
    def _send_decision_to_body(self, decision: Decision, *, channel: str | None = None) -> None:
        payload = decision.to_payload()
        payload.update(self._build_body_bias_payload())
        self._record_public_turn(decision, payload=payload, channel=channel)
        self.transport.send_json(payload)
    def _record_public_turn(self, decision: Decision, *, payload: dict | None = None, channel: str | None = None):
        ledger = getattr(self, "public_turn_ledger", None)
        if ledger is None:
            ledger = PublicTurnLedger()
            self.public_turn_ledger = ledger

        text = str((payload or {}).get("text", getattr(decision, "text", "")) or "")
        should_speak = bool((payload or {}).get("should_speak", getattr(decision, "should_speak", True)))
        if not should_speak or not text.strip():
            return None

        frame = getattr(self, "last_cognitive_frame", None)
        frame_channel = str(getattr(frame, "channel", "") or "")
        fallback = channel or (normalize_public_turn_channel(frame_channel) if frame_channel else "chat" if getattr(self, "chat_mode", False) else "autonomous")
        public_channel = infer_public_turn_channel(decision, fallback=fallback)
        return ledger.append(
            channel=public_channel,
            text=text,
            parse_mode=str((payload or {}).get("parse_mode", getattr(decision, "parse_mode", "")) or ""),
            visible_to_user=True,
            can_be_replied_to=True,
        )
    def _build_body_bias_payload(self) -> dict[str, object]:
        frame = getattr(self, "last_cognitive_frame", None)
        action_plan = getattr(frame, "action_plan", None) if frame is not None else None
        impulse_hint = getattr(action_plan, "body_bias_hint", {}) if action_plan is not None else {}
        return self.body_bias_projector.build_payload(impulse_hint=impulse_hint)
    def _body_bias_clamp(value: object) -> float:
        return BodyBiasProjector.clamp(value)
    def _normalize_body_focus_kind(value: str) -> str:
        return BodyBiasProjector.normalize_focus_kind(value)
    def _save_memory_state(self) -> None:
        if self.memory_state is None:
            return
        saver = getattr(getattr(self, "memory_core", None), "save", None)
        if not callable(saver):
            return
        try:
            saver(self.memory_state)
        except Exception as exc:
            self.logger.warning("Memory state save error: %s", exc)
    def _memory_recall_packet(self, *, snapshot=None, query: str = ""):
        """Recall structured packet, không flatten quá sớm.

        PDF/Tongquat tách episodic/semantic/procedural vì mỗi layer có quyền surface khác nhau.
        Flatten tất cả thành list[str] là cách rất nhanh để memory đóng giả evidence hiện tại.
        """
        kernel = self._memory_kernel()
        if kernel is not None and callable(getattr(kernel, "build_packet", None)):
            try:
                return kernel.build_packet(query or self._memory_query_from_snapshot(snapshot))
            except Exception as exc:
                self.logger.warning("Memory kernel packet build error: %s", exc)
                return None
        recall = getattr(getattr(self, "memory_core", None), "recall", None)
        if not callable(recall):
            return None
        try:
            return recall(query or self._memory_query_from_snapshot(snapshot))
        except Exception as exc:
            self.logger.warning("Memory recall error: %s", exc)
            return None

    def _memory_recall_texts(self, *, snapshot=None, layers: tuple[str, ...] | None = None) -> list[str]:
        packet = self._memory_recall_packet(snapshot=snapshot)
        if packet is not None:
            texts: list[str] = []
            selected_layers = layers or ("repair", "procedural", "semantic", "relational", "affective_residue", "episodic")
            for name in selected_layers:
                texts.extend(str(item) for item in getattr(packet, name, ()) or ())
            return texts
        return list(getattr(self, "long_term_memory", []) or [])
    def _recall_memory_resonance(
        self,
        *,
        snapshot=None,
        user_text: str = "",
        channel: str = "",
        fragments: tuple[str, ...] = (),
    ):
        query = " ".join(str(item) for item in (channel, user_text, *tuple(fragments or ()), self._memory_query_from_snapshot(snapshot)) if str(item or "").strip())
        report = self._memory_recall_packet(snapshot=snapshot, query=query)
        if report is None:
            self.active_memory_resonance = None
            return None
        self.active_memory_resonance = report
        return report
    def _memory_attention_lines(self) -> tuple[str, ...]:
        report = getattr(self, "active_memory_resonance", None)
        to_attention_lines = getattr(report, "to_attention_lines", None)
        if not callable(to_attention_lines):
            return ()
        try:
            return tuple(to_attention_lines())
        except Exception as exc:
            self.logger.warning("Memory resonance attention render error: %s", exc)
            return ()
    def _norm_deviation_texts(self, snapshot) -> tuple[str, ...]:
        return ()
    def _note_norm_observation(self, snapshot) -> None:
        return
    def _memory_query_from_snapshot(self, snapshot) -> str:
        if snapshot is None:
            return ""
        parts = []
        for attr in ("focus_summary", "active_window_kind", "active_app", "active_window"):
            value = str(getattr(snapshot, attr, "") or "").strip()
            if value:
                parts.append(value)
        return " ".join(parts)
    def _event_timestamp(self, snapshot, *, started_at: float | None = None) -> str:
        captured_at = str(getattr(snapshot, "captured_at", "") or getattr(snapshot, "time", "") or "").strip()
        if captured_at:
            return captured_at
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started_at or time.time()))
    def _commit_chat_decision(self, decision: Decision, fe_plan, *, frame: CognitiveFrame | None = None) -> None:
        self.fe_style_memory = self.fe_renderer.remember_style(
            self.fe_style_memory,
            plan=fe_plan,
            rendered_text=decision.text,
        )
        self.last_chat_answer = decision.text
        self.last_system_action = decision.system_action
        invalid_for_semantic_history = _is_nonsemantic_fallback_decision(decision)
        # Fallback/service-error vẫn có thể hiện ra UI, nhưng không được đưa vào
        # LLM semantic history như một câu trả lời thật. Nếu không, prompt lượt sau
        # tự nhiễm câu "tôi bị lỗi định dạng" và TurnGraph nối nhầm ANSWERS.
        self._append_chat_history("assistant", decision.text, invalid=invalid_for_semantic_history)
        if bool(decision.should_speak) and str(decision.text or "").strip():
            assistant_meta = {
                "intent": decision.intent,
                "parse_mode": decision.parse_mode,
                "system_action": decision.system_action,
            }
            if invalid_for_semantic_history:
                assistant_meta.update({
                    "is_service_fallback": True,
                    "counts_as_answer": False,
                    "invalid_for_semantic_context": True,
                })
            self._ensure_session_turn_ledger().record_assistant(
                decision.text,
                meta=assistant_meta,
            )
        if len(self.chat_history) > 32:
            self.chat_history = self.chat_history[-32:]

        self._apply_position_update(decision)
        if frame is not None:
            frame.final_decision = self._decision_to_frame_dict(decision)
            grounding = getattr(frame, "source_grounding", None) or getattr(frame, "grounding", None)
            if grounding is not None:
                frame.final_decision["grounding_source"] = str(getattr(grounding, "grounding_source", "unknown") or "unknown")
                frame.final_decision["grounding_preempt_mode"] = str(getattr(grounding, "preempt_mode", "") or "")
                frame.final_decision["grounding_missing_evidence"] = list(getattr(grounding, "missing_evidence", ()) or ())
            self._set_cognitive_memory_update(frame, decision=decision, notes=("chat_commit",))
            self._commit_internal_state_for_frame(frame)
            self._send_decision_to_body(decision, channel="chat")
            self._finalize_cognitive_frame(frame)
        self.logger.info("ERIS: %s", decision.text)
        self.logger.info("[chat debug] parse_mode=%s | trace=%s", decision.parse_mode, decision.debug_trace or "<empty>")
        self.logger.info("[chat parser] %s", decision.parser_trace or "<empty>")

    def _apply_position_update(self, decision: Decision) -> None:
        intent = decision.resolve_motion_intent()
        tx = decision.resolve_motion_target_x()
        facing = decision.resolve_motion_facing()

        if intent in {"walk_to", "climb_to_top"} and 0.0 <= tx <= 1.0:
            self.inferred_pos_x = tx
        elif intent == "walk" and facing == -1:
            self.inferred_pos_x = max(0.0, self.inferred_pos_x - 0.4)
        elif intent == "walk" and facing == 1:
            self.inferred_pos_x = min(1.0, self.inferred_pos_x + 0.4)
    def _build_silent_motion_decision(self, ti_report: TiPolicyReport) -> Decision | None:
        motion_intent = str(getattr(ti_report, "motion_intent_hint", "") or "").strip()
        motion_target_x = float(getattr(ti_report, "motion_target_x_hint", -1.0) or -1.0)
        motion_facing = int(getattr(ti_report, "motion_facing_hint", 0) or 0)
        if not motion_intent:
            return None
        if motion_target_x < 0.0 and motion_facing == 0:
            return None
        return Decision(
            text="",
            animation=str(getattr(ti_report, "animation_hint", "") or "stand"),
            should_speak=False,
            confidence=0.54,
            parse_mode="motion_only",
            debug_trace=f"silent_motion; ti_mode={getattr(ti_report, 'mode', '')}",
            motion_intent=motion_intent,
            motion_target_x=motion_target_x,
            motion_facing=motion_facing,
        )
    def _build_direct_action_decision(self, user_text: str, ti_report, snapshot, *, repeat_count: int = 1) -> Decision | None:
        if self.action_router is None or self.action_executor is None:
            return None

        routed = self.action_router.route_chat(user_text, last_action=self.last_system_action)
        if not routed:
            return None

        action_name, action_input = routed
        result = self.action_executor.execute(action_name, action_input)
        text = self._action_result_to_text(result)
        if action_name == "get_now_playing" and not result.success:
            text = self._resolve_now_playing_text(snapshot) or text
        if repeat_count == 2:
            text = f"Ngài đang hỏi lại cùng một ý. {text}"
        elif repeat_count >= 3:
            text = f"Ngài đang spam cùng một ý. {text}"

        decision = Decision(
            text=text,
            animation=self._action_animation_hint(action_name, ti_report.animation_hint),
            debug_trace=f"Direct action route: {action_name}",
            parse_mode="direct_action",
            system_action=action_name,
            action_input=action_input,
        )
        if action_name in {"open_url", "focus_window", "launch_app"}:
            decision.motion_intent = "walk_to"
            decision.motion_target_x = 0.5
        return self.ti_governor.enforce_decision(decision, ti_report, user_hint=user_text)
    def _execute_system_action(self, decision: Decision, *, snapshot) -> Decision:
        if self.action_executor is None or not decision.system_action:
            return decision

        result = self.action_executor.execute(decision.system_action, decision.action_input)
        action_trace = f"action={decision.system_action}:{'ok' if result.success else 'fail'}"
        if decision.debug_trace:
            decision.debug_trace = f"{decision.debug_trace} | {action_trace}"[:240]
        else:
            decision.debug_trace = action_trace
        if not decision.text.strip():
            decision.text = self._action_result_to_text(result)
        elif decision.system_action in {"search_web", "get_weather"}:
            decision.text = self._action_result_to_text(result)
        if decision.system_action == "get_now_playing" and "media session" in decision.text.lower():
            decision.text = self._resolve_now_playing_text(snapshot) or decision.text
        return decision
    def _action_animation_hint(self, action_name: str, fallback: str) -> str:
        if action_name == "get_now_playing":
            return "read"
        if action_name in {"open_url", "focus_window", "launch_app"}:
            return "stand_walk"
        if action_name in {"copy_text", "set_volume", "play_pause_media"}:
            return "stand"
        return fallback or "stand"
    def _action_result_to_text(self, result) -> str:
        if result.action_name == "get_now_playing":
            title = result.data.get("title", "")
            artist = result.data.get("artist", "")
            if result.success and title and artist:
                return f"Tôi thấy bài đang phát là {title} của {artist}."
            if result.success and title:
                return f"Tôi thấy bài đang phát là {title}."
            return "Tôi chưa đọc được tên bài đang phát từ media session hiện tại."

        if result.action_name == "search_web":
            if not result.success:
                return result.message
            answer = (result.data.get("answer", "") or result.message or "").strip()
            query = (result.action_input or "một chủ đề lạ mặt").strip()
            if answer:
                return f"Tôi vừa kéo về một mẩu thế giới quanh {query}. {answer}"
            return f"Tôi vừa lục lại mạng cho chủ đề {query}, nhưng thứ kéo về vẫn còn quá ít để nói cho ra hồn."
        if result.action_name == "open_url":
            return f"Tôi đã gửi yêu cầu mở {result.data.get('url', result.action_input)}."
        if result.action_name == "focus_window":
            matched = result.data.get("matched_title", result.action_input)
            if result.success:
                return f"Tôi đã đưa cửa sổ {matched} lên foreground."
            return f"Tôi chưa tìm thấy cửa sổ khớp với {result.action_input}."
        if result.action_name == "set_volume":
            level = result.data.get("level", result.action_input or "mức yêu cầu")
            return f"Tôi đã gửi yêu cầu chỉnh âm lượng về khoảng {level} phần trăm." if result.success else result.message
        if result.action_name == "play_pause_media":
            return "Tôi đã gửi phím play/pause cho media session hiện tại." if result.success else result.message
        if result.action_name == "copy_text":
            return "Tôi đã đưa nội dung bạn yêu cầu vào clipboard." if result.success else result.message
        if result.action_name == "launch_app":
            command = result.data.get("command", result.action_input)
            return f"Tôi đã yêu cầu Windows mở {command}." if result.success else result.message
        return result.message or "Action đã được xử lý."
    def _resolve_now_playing_text(self, snapshot) -> str | None:
        title = self._extract_media_title_from_snapshot(snapshot)
        if not title:
            return None
        return f"Tôi thấy tab media hiện tại là {title}."
    def _extract_media_title_from_snapshot(self, snapshot) -> str:
        candidates = [snapshot.active_window, *snapshot.browser_tabs, *snapshot.open_windows]
        for candidate in candidates:
            title = self._extract_media_title(candidate)
            if title:
                return title
        return ""
    def _extract_media_title(self, raw_title: str) -> str:
        title = (raw_title or "").strip()
        if not title:
            return ""

        lowered = title.lower()
        if "youtube" in lowered:
            cleaned = title
            for suffix in (
                " - YouTube - Brave",
                " - YouTube - Google Chrome",
                " - YouTube - Microsoft Edge",
                " - YouTube",
                " - Brave",
                " - Google Chrome",
                " - Microsoft Edge",
            ):
                if cleaned.endswith(suffix):
                    cleaned = cleaned[: -len(suffix)]
            cleaned = cleaned.strip(" -|")
            if cleaned and cleaned.lower() != "youtube":
                return cleaned

        if "spotify" in lowered:
            cleaned = title
            for suffix in (
                " - Spotify Premium",
                " - Spotify",
                " - Brave",
                " - Google Chrome",
                " - Microsoft Edge",
            ):
                if cleaned.endswith(suffix):
                    cleaned = cleaned[: -len(suffix)]
            cleaned = cleaned.strip(" -|")
            if cleaned and cleaned.lower() != "spotify":
                return cleaned

        return ""
