# -*- coding: utf-8 -*-
"""Facade cấp cao cho living user memory.

Runtime chỉ nên gọi service này, thay vì tự mở profile store, episode store rồi
trộn business rule vào chat cycle. Một facade có ích là facade làm giảm quyền của
caller, không phải chỉ đổi tên sáu method rồi thêm logo kiến trúc.
"""
from __future__ import annotations
from core.di import resolve_dependency

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .action_memory import ActionMemoryStore, ActionMemoryOperation, GoalRecord, CommitmentRecord, WorkflowRecord
from .authority import UserMemoryAuthorityEvent, UserMemoryAuthorityLedger
from .clarification import MemoryClarificationPolicy
from .context_compiler import ProfileContextCompiler, ProfileContextCompilerConfig
from .dreamer import UserProfileDreamer
from .episode_builder import UserEpisodeBuilder
from .episode_store import UserEpisodeStore
from .episode_rollup import EpisodeRollupStore
from .extractor import UserProfileExtractor, UserProfileModelAdapter
from .models import DreamReport, ProfileContextPacket, ProfileOperation, UserEpisode, UserMemoryScope
from .sources import MemoryExplanation, MemorySourceTracker
from .store import ApplyResult, UserProfileStore, UserProfileStoreConfig
from .trace import MemoryReplayDebugger, MemoryTraceJournal
from memory.memory_feed_trace import MemoryFeedTraceJournal


@dataclass(slots=True)
class LivingUserMemoryConfig:
    enabled: bool = True
    auto_observe_turns: bool = True
    auto_sync_semantic: bool = True
    auto_dream_on_maintenance: bool = True
    episode_rollup_enabled: bool = True
    context_token_budget: int = 900
    profile_filename: str = "living_user_profile.json"
    episode_filename: str = "living_user_episodes.json"
    action_filename: str = "living_user_actions.json"
    trace_filename: str = "living_user_trace.jsonl"
    authority_filename: str = "living_user_authority.json"

    @classmethod
    def from_env(cls) -> "LivingUserMemoryConfig":
        return cls(
            enabled=_env_flag("ERIS_LIVING_USER_MODEL_ENABLED", True),
            auto_observe_turns=_env_flag("ERIS_LIVING_USER_AUTO_OBSERVE", True),
            auto_sync_semantic=_env_flag("ERIS_LIVING_USER_SYNC_SEMANTIC", True),
            auto_dream_on_maintenance=_env_flag("ERIS_LIVING_USER_AUTO_DREAM", True),
            episode_rollup_enabled=_env_flag("ERIS_LIVING_USER_EPISODE_ROLLUP", True),
            context_token_budget=max(200, int(os.getenv("ERIS_LIVING_USER_CONTEXT_TOKENS", "900") or 900)),
        )


@dataclass(slots=True)
class UserTurnObservation:
    applied: int = 0
    rejected: int = 0
    operations: tuple[ProfileOperation | ActionMemoryOperation, ...] = ()
    diagnostics: tuple[str, ...] = ()


class LivingUserMemoryService:
    """Một service nối profile, episodes, dreaming, context và source tracking."""

    def __init__(
        self,
        base_dir: str | os.PathLike[str],
        *,
        semantic_store: Any = None,
        episodic_store: Any = None,
        event_ledger: Any = None,
        embedding_index: Any = None,
        model_adapter: UserProfileModelAdapter | None = None,
        config: LivingUserMemoryConfig | None = None,
        profile_store_config: UserProfileStoreConfig | None = None,
        memory_feed_trace: MemoryFeedTraceJournal | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.config = resolve_dependency(config, LivingUserMemoryConfig.from_env)
        self.semantic_store = semantic_store
        self.episodic_store = episodic_store
        self.event_ledger = event_ledger
        self.embedding_index = embedding_index
        self.model_adapter = model_adapter
        self.profile_store = UserProfileStore(self.base_dir / self.config.profile_filename, config=profile_store_config)
        # Authority ledger là nguồn chân lý cho correction/forget/scope do user chọn.
        # Profile bên dưới chỉ còn là projection có thể dựng lại.
        self.authority_ledger = UserMemoryAuthorityLedger(self.base_dir / self.config.authority_filename)
        self.episode_store = UserEpisodeStore(self.base_dir / self.config.episode_filename)
        self.episode_rollups = EpisodeRollupStore(self.base_dir / "living_user_episode_rollups.json",
                                                 self.episode_store, authority=self.authority_ledger.all)
        self.action_store = ActionMemoryStore(self.base_dir / self.config.action_filename)
        self.trace_journal = MemoryTraceJournal(self.base_dir / self.config.trace_filename)
        self.memory_feed_trace = memory_feed_trace or MemoryFeedTraceJournal(self.base_dir / "memory_feed_trace.jsonl")
        self.replay_debugger = MemoryReplayDebugger(self.trace_journal)
        self.clarification_policy = MemoryClarificationPolicy()
        self.extractor = UserProfileExtractor(model_adapter=model_adapter)
        self.episode_builder = UserEpisodeBuilder(model_adapter=model_adapter)
        self.dreamer = UserProfileDreamer(self.profile_store, model_adapter=model_adapter)
        self.context_compiler = ProfileContextCompiler(
            self.profile_store,
            self.episode_store,
            embedding_index=embedding_index,
            action_store=self.action_store,
            clarification_policy=self.clarification_policy,
            config=ProfileContextCompilerConfig(default_token_budget=self.config.context_token_budget),
            episode_rollups=self.episode_rollups if self.config.episode_rollup_enabled else None,
        )
        self.sources = MemorySourceTracker(
            event_ledger=event_ledger,
            episodic_store=episodic_store,
            semantic_store=semantic_store,
        )
        self.last_dream_report: DreamReport | None = None
        # Journal ngắn để tạo episode từ hội thoại thật. Nó không thay raw event
        # ledger và được xóa/thu gọn sau khi consolidate.
        self._turn_buffer_path = self.base_dir / "living_user_turn_buffer.json"
        self._turn_buffer_lock = threading.RLock()
        self._turn_buffer: list[dict[str, Any]] = []
        self._active_session_id = ""
        self._load_turn_buffer()
        self._reapply_authority_projection()

    def bind_model_adapter(self, adapter: UserProfileModelAdapter | None) -> None:
        """Nối model sau bootstrap mà không tạo lại store."""
        self.model_adapter = adapter
        self.extractor.model_adapter = adapter
        self.episode_builder.model_adapter = adapter
        self.dreamer.model_adapter = adapter

    def record_conversation_turn(
        self,
        role: str,
        text: str,
        *,
        session_id: str = "",
        turn_id: str = "",
        context: Mapping[str, Any] | None = None,
    ) -> str | None:
        """Ghi lượt vào journal ngắn để episode builder có đủ hai phía hội thoại."""
        if not self.config.enabled:
            return
        clean = " ".join(str(text or "").split())
        if not clean or role not in {"user", "assistant", "eris"}:
            return
        sid = str(session_id or self._active_session_id or "runtime_session").strip()
        action_scope = _scope_from_context(context, session_id=sid)
        evidence_id = str(turn_id or f"conversation:{sid}:{uuid.uuid4().hex}")
        self.trace_journal.append("conversation_turn", {
            "role": role, "session_id": sid, "evidence_id": evidence_id,
            "project_id": action_scope.key if action_scope.kind == "project" else "",
        })
        with self._turn_buffer_lock:
            if self._active_session_id and sid != self._active_session_id and self._turn_buffer:
                self._flush_buffer_locked(run_dream=True)
            self._active_session_id = sid
            self._turn_buffer.append({
                "id": evidence_id,
                "role": "assistant" if role == "eris" else role,
                "text": clean[:1800],
                "text_truncated": len(clean) > 1800,
                "session_id": sid,
                "timestamp": time.time(),
                "context": dict(context or {}),
            })
            self._turn_buffer = self._turn_buffer[-48:]
            self._save_turn_buffer_locked()
            # Phiên dài được checkpoint thành episode giữa chừng, nhưng giữ vài
            # lượt cuối để mạch tiếp theo không bị cắt cụt.
            if len(self._turn_buffer) >= 28 and role in {"assistant", "eris"}:
                self._flush_buffer_locked(run_dream=False, keep_tail=4)
        return evidence_id

    def flush_session(self, *, run_dream: bool = True) -> UserEpisode | None:
        with self._turn_buffer_lock:
            return self._flush_buffer_locked(run_dream=run_dream)

    def _flush_buffer_locked(self, *, run_dream: bool, keep_tail: int = 0) -> UserEpisode | None:
        if len(self._turn_buffer) < 2:
            return None
        turns = list(self._turn_buffer)
        sid = self._active_session_id or "runtime_session"
        context = turns[-1].get("context") if turns else {}
        project_id = str((context or {}).get("project_id") or (context or {}).get("project") or "")
        scope = UserMemoryScope("project", project_id) if project_id else UserMemoryScope()
        episode = self.consolidate_session(
            turns,
            session_id=sid,
            scope=scope,
            metadata={"source": "turn_buffer", "turn_count": len(turns)},
            run_dream=run_dream,
        )
        self._turn_buffer = turns[-keep_tail:] if keep_tail else []
        self._save_turn_buffer_locked()
        return episode

    def _load_turn_buffer(self) -> None:
        try:
            if not self._turn_buffer_path.is_file():
                return
            raw = json.loads(self._turn_buffer_path.read_text(encoding="utf-8"))
            self._active_session_id = str(raw.get("session_id") or "") if isinstance(raw, Mapping) else ""
            rows = raw.get("turns") if isinstance(raw, Mapping) else []
            self._turn_buffer = [dict(x) for x in rows or [] if isinstance(x, Mapping)][-48:]
        except Exception:
            self._turn_buffer = []
            self._active_session_id = ""

    def _save_turn_buffer_locked(self) -> None:
        from memory.json_store_io import atomic_write_json
        atomic_write_json(self._turn_buffer_path, {
            "schema_version": 1,
            "session_id": self._active_session_id,
            "turns": self._turn_buffer[-48:],
        })

    def capture_interpretation_context(self, *, evidence_ids=(), cutoff=None, context=None, scopes=()) -> dict[str, Any]:
        """Read-only snapshot; no model/retrieval/network on the enqueue path."""
        from .evidence_context import build_evidence_context
        with self._turn_buffer_lock:
            turns = [dict(row) for row in self._turn_buffer]
            session = self._active_session_id
        payload = dict(context or {})
        allowed = tuple(scopes) or (_scope_from_context(payload, session_id=str(payload.get("session_id") or session)),)
        episodes = [episode for episode in self.episode_store.all()
                    if any(episode.scope.matches(scope) for scope in allowed)]
        project = str(payload.get("project_id") or payload.get("project") or "")
        if not scopes:
            turns = [row for row in turns if str((row.get("context") or {}).get("project_id") or "") in {"", project}]
        return build_evidence_context(turns=turns, episodes=episodes,
                                      evidence_ids=evidence_ids, cutoff=cutoff, session_id=session)

    def propose_turn_operations(
        self,
        user_text: str,
        *,
        evidence_ids: Iterable[str],
        context: Mapping[str, Any] | None = None,
    ) -> tuple[ProfileOperation | ActionMemoryOperation, ...]:
        """Extract profile operations without mutating living-user state.

        Curator/model work belongs on a proposal lane.  Authority checks and
        durable writes deliberately happen later at the single mutation
        boundary, so a slow model can run in parallel without becoming a
        second state owner.
        """
        if not self.config.enabled or not self.config.auto_observe_turns:
            return ()
        if self.model_adapter is None:
            from .runtime_adapter import CuratorInferenceError
            raise CuratorInferenceError("unavailable")
        evidence_ids = tuple(evidence_ids)
        proposal_context = dict(context or {})
        action_scope = _scope_from_context(proposal_context, session_id=str(proposal_context.get("session_id") or self._active_session_id))
        supplied_actions = [
            row.to_dict() for row in (
                *self.action_store.goals(scope=action_scope),
                *self.action_store.commitments(scope=action_scope),
                *self.action_store.workflows(scope=action_scope),
            )
        ]
        proposal_context["action_scope"] = action_scope.to_dict()
        proposal_context["existing_actions"] = supplied_actions
        evidence_context = proposal_context.get("interpretation_context")
        if not isinstance(evidence_context, Mapping):
            evidence_context = self.capture_interpretation_context(
                evidence_ids=evidence_ids, cutoff=proposal_context.get("evidence_created_at"), context=proposal_context)
        proposal_context["interpretation_context"] = evidence_context
        proposal_context["recent_conversation"] = list(evidence_context.get("recent_conversation", ()))
        ops = self.extractor.from_turn(
            user_text,
            evidence_ids=evidence_ids,
            context=proposal_context,
            existing_profile=self.profile_store.snapshot(limit=100),
        )
        return tuple(ops or ())

    def apply_turn_operations(
        self,
        operations: Iterable[ProfileOperation | ActionMemoryOperation],
        *,
        trace_context: Mapping[str, Any] | None = None,
    ) -> UserTurnObservation:
        """Apply already-extracted operations at the authoritative boundary."""
        if not self.config.enabled or not self.config.auto_observe_turns:
            return UserTurnObservation(diagnostics=("living_user_disabled",))
        ops = tuple(operations or ())
        profile_ops = tuple(op for op in ops if isinstance(op, ProfileOperation))
        action_ops = tuple(op for op in ops if isinstance(op, ActionMemoryOperation))
        guarded_ops, authority_rejected = self.authority_ledger.guard_operations(profile_ops)
        result = self.profile_store.apply(guarded_ops, checkpoint_reason="observe_user_turn")
        self._reapply_authority_projection()
        action_result = self.action_store.apply_model_operations(action_ops)
        rejected = tuple((*result.rejected, *authority_rejected, *action_result["rejected"]))
        payload = {
            "applied": len(result.record_ids) + action_result["applied"], "rejected_count": len(rejected),
            "operation_count": len(ops), "paths": [op.path for op in guarded_ops],
            "operations": [op.to_dict() for op in guarded_ops],
            "authority_rejected": list(authority_rejected),
            "action_record_ids": action_result["record_ids"],
        }
        if trace_context:
            payload["context"] = {key: value for key, value in trace_context.items()
                                  if key not in {"interpretation_context", "recent_conversation"}}
        self.trace_journal.append("observe_turn", payload)
        return UserTurnObservation(
            applied=len(result.record_ids) + action_result["applied"],
            rejected=len(rejected),
            operations=(*guarded_ops, *action_ops),
            diagnostics=rejected,
        )

    def observe_turn(
        self,
        user_text: str,
        *,
        evidence_ids: Iterable[str],
        context: Mapping[str, Any] | None = None,
    ) -> UserTurnObservation:
        """Compatibility facade: propose then apply synchronously.

        Runtime turn-memory code uses the two explicit phases above; legacy
        callers retain the old one-call behavior.
        """
        if not self.config.enabled or not self.config.auto_observe_turns:
            return UserTurnObservation(diagnostics=("living_user_disabled",))
        ops = self.propose_turn_operations(
            user_text,
            evidence_ids=evidence_ids,
            context=context,
        )
        return self.apply_turn_operations(ops, trace_context=context)

    def record_interaction_preference(
        self,
        path: str,
        value: Any,
        *,
        explicitness: str = "observed",
        confidence: float = 0.72,
        evidence_ids: Iterable[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> ApplyResult:
        """Persist a public-safe interaction preference learned from repeated outcomes.

        This is intentionally narrower than ``observe_turn``: callers provide one
        already-evaluated preference and its evidence. The authority ledger still
        gets final say, because even a friendly autonomous companion should not
        quietly promote its guesses to divine revelation.
        """
        if not self.config.enabled:
            return ApplyResult(False, rejected=("living_user_disabled",), version=self.profile_store.version)
        clean_path = str(path or "").strip()
        evidence = tuple(dict.fromkeys(str(item) for item in evidence_ids if str(item).strip()))[:32]
        if not clean_path:
            return ApplyResult(False, rejected=("empty_path",), version=self.profile_store.version)
        if not evidence:
            return ApplyResult(False, rejected=("missing_evidence",), version=self.profile_store.version)
        level = str(explicitness or "observed").strip().lower()
        if level not in {"explicit", "observed"}:
            level = "observed"
        try:
            score = float(confidence)
        except (TypeError, ValueError):
            score = 0.72
        operation = ProfileOperation(
            op="add",
            path=clean_path,
            value=value,
            confidence=max(0.0, min(1.0, score)),
            explicitness=level,  # type: ignore[arg-type]
            sensitivity="normal",
            scope=UserMemoryScope(),
            cardinality="single",
            evidence_ids=evidence,
            reason="Pattern learned from autonomous random-chat outcomes.",
            source="random_chat_seed_outcome",
            metadata={"learned_by": "random_chat_seed", **dict(metadata or {})},
        )
        guarded, authority_rejected = self.authority_ledger.guard_operations((operation,))
        result = self.profile_store.apply(guarded, checkpoint_reason="random_chat_seed_preference")
        self._reapply_authority_projection()
        rejected = tuple((*result.rejected, *authority_rejected))
        self.trace_journal.append("random_chat_seed_preference", {
            "path": operation.path,
            "explicitness": operation.explicitness,
            "confidence": operation.confidence,
            "evidence_ids": list(evidence),
            "record_ids": list(result.record_ids),
            "rejected": list(rejected),
            "metadata": dict(metadata or {}),
        })
        if rejected:
            return ApplyResult(result.changed, result.record_ids, rejected, self.profile_store.version)
        return result

    def sync_semantic_memory(self, *, scope: UserMemoryScope | None = None) -> ApplyResult:
        if not self.config.enabled or not self.config.auto_sync_semantic:
            return ApplyResult(False, version=self.profile_store.version)
        loader = getattr(self.semantic_store, "load", None)
        if not callable(loader):
            return ApplyResult(False, rejected=("semantic_store_unavailable",), version=self.profile_store.version)
        try:
            items = loader()
        except Exception as exc:
            return ApplyResult(False, rejected=(f"semantic_load_failed:{type(exc).__name__}",), version=self.profile_store.version)
        ops = self.extractor.from_semantic_items(items, scope=scope)
        guarded_ops, authority_rejected = self.authority_ledger.guard_operations(ops)
        result = self.profile_store.apply(guarded_ops, checkpoint_reason="semantic_sync")
        self._reapply_authority_projection()
        if authority_rejected:
            return ApplyResult(
                result.changed,
                result.record_ids,
                tuple((*result.rejected, *authority_rejected)),
                self.profile_store.version,
            )
        return result

    def consolidate_session(
        self,
        turns: Iterable[Mapping[str, Any]],
        *,
        session_id: str,
        scope: UserMemoryScope | None = None,
        metadata: Mapping[str, Any] | None = None,
        run_dream: bool = True,
    ) -> UserEpisode | None:
        if not self.config.enabled:
            return None
        episode = self.episode_builder.build(
            turns,
            session_id=session_id,
            scope=scope,
            metadata=metadata,
        )
        if episode is None:
            return None
        saved = self.episode_store.add(episode)
        if run_dream:
            semantic_ops = self._semantic_operations(scope=scope)
            self.last_dream_report = self.dreamer.consolidate((saved,), semantic_operations=semantic_ops, reason="session_end", scope=scope)
        return saved

    def dream(
        self,
        *,
        reason: str = "idle",
        scope: UserMemoryScope | None = None,
        episode_limit: int = 12,
    ) -> DreamReport:
        if not self.config.enabled:
            return DreamReport(diagnostics=("living_user_disabled",))
        # Idle/reflection là lúc hợp lý để biến turn journal thành episode.
        if len(self._turn_buffer) >= 4:
            try:
                self.flush_session(run_dream=False)
            except Exception:
                pass
        semantic_ops = self._semantic_operations(scope=scope)
        episodes = self.episode_store.recent(limit=episode_limit, scope=scope)
        report = self.dreamer.consolidate(episodes, semantic_operations=semantic_ops, reason=reason, scope=scope)
        decayed = self.profile_store.decay()
        compacted_profile = self.profile_store.compact()
        compacted_episodes = self.episode_store.compact()
        archived_actions = self.action_store.archive_stale()
        self.trace_journal.append("dream", {
            "applied": report.applied, "rejected_count": report.rejected,
            "operation_count": len(report.operations), "episode_ids": list(report.episode_ids),
            "decayed": decayed, "compacted_profile": compacted_profile,
            "compacted_episodes": compacted_episodes, "archived_actions": archived_actions,
        })
        self.last_dream_report = report
        return report

    def rollup_episodes(self, *, now: float | None = None) -> dict[str, Any]:
        """Maintenance-only; never invoked while reading Self/context."""
        if not self.config.enabled or not self.config.episode_rollup_enabled:
            return {"status": "disabled", "calls": 0}
        result = self.episode_rollups.run(self.model_adapter, now=now, active_session_id=self._active_session_id)
        self.trace_journal.append("episode_rollup", result)
        return result

    def episode_prompt_view(self, *, scope: UserMemoryScope | None = None,
                            include_sensitive: bool = False, now: float | None = None) -> dict[str, Any]:
        if not self.config.enabled:
            return {"recent_episodes": [], "episode_recap": ""}
        if not self.config.episode_rollup_enabled:
            return {"recent_episodes": [x.to_dict() for x in self.episode_store.recent(limit=8, scope=scope or UserMemoryScope())],
                    "episode_recap": ""}
        return self.episode_rollups.prompt_view(scope=scope, include_sensitive=include_sensitive, now=now)

    def compile_context(
        self,
        query: str,
        *,
        project_id: str = "",
        session_id: str = "",
        domain: str | None = None,
        token_budget: int | None = None,
        include_sensitive: bool = False,
        include_proactive: bool = False,
        session_context: Mapping[str, Any] | None = None,
    ) -> ProfileContextPacket:
        scope = UserMemoryScope("project", project_id) if project_id else (UserMemoryScope("session", session_id) if session_id else UserMemoryScope())
        packet = self.context_compiler.compile(
            query,
            scope=scope,
            domain=domain,
            token_budget=token_budget,
            include_sensitive=include_sensitive,
            include_proactive=include_proactive,
            session_context=session_context,
        )
        self.trace_journal.append("compile_context", {
            "query": query[:500], "domain": packet.domain,
            "selected_paths": [item.path for item in packet.items],
            "use_modes": {item.path: item.use_mode for item in packet.items},
            "episode_ids": [episode.id for episode in packet.episodes],
            "goal_ids": [goal.id for goal in getattr(packet.action_context, "goals", ())],
            "workflow_ids": [flow.id for flow in getattr(packet.action_context, "workflows", ())],
            "diagnostics": list(packet.diagnostics),
        })
        try:
            # diagnostics dùng dạng reject:PATH:reason; trace chỉ giữ ID + lý do, không sao chép text memory.
            rejected = []
            for row in packet.diagnostics:
                text = str(row)
                if not text.startswith("reject:"):
                    continue
                payload = text[len("reject:"):]
                path, _, reason = payload.partition(":")
                rejected.append({"record_id": path, "layer": "living_user", "reason": reason or "admission_rejected"})
            admitted = [
                {"record_id": item.path, "layer": "living_user", "reason": item.use_mode, "score": round(float(item.score), 3)}
                for item in packet.items
            ]
            self.memory_feed_trace.record_retrieval(
                query=query,
                retrieved=len(packet.items) + len(rejected),
                admitted=admitted,
                rejected=rejected,
                rendered_ids=[item.path for item in packet.items],
                channel="living_user",
            )
        except Exception:
            pass
        return packet

    def compile_proactive_cue(
        self,
        *,
        project_id: str = "",
        session_id: str = "",
        now: float | None = None,
        session_context: Mapping[str, Any] | None = None,
    ) -> str:
        """Biên dịch gợi ý chủ động dựa trên nhịp thời gian, cảm xúc phiên trước và việc còn mở."""
        scope = UserMemoryScope("project", project_id) if project_id else (UserMemoryScope("session", session_id) if session_id else UserMemoryScope())
        return self.context_compiler.compile_proactive_cue(scope, now=now, session_context=session_context)

    def summary(self, *, include_sensitive: bool = False, limit: int = 60) -> dict[str, Any]:
        records = self.profile_store.snapshot(include_sensitive=include_sensitive, limit=limit)
        return {
            "profile": records,
            **self.episode_prompt_view(include_sensitive=include_sensitive),
            "actions": self.action_store.snapshot(),
            "replay": self.replay_debugger.report(limit=200).to_dict(),
            "last_dream_report": asdict(self.last_dream_report) if self.last_dream_report else None,
            "pending_turns": len(self._turn_buffer),
            "active_session_id": self._active_session_id,
        }

    def render_summary(
        self,
        *,
        include_inferred: bool = False,
        include_sensitive: bool = False,
        limit: int = 36,
    ) -> str:
        """Render bản tổng hợp người dùng có thể đọc và sửa.

        Câu chữ cố tình phân biệt điều user nói rõ với khuynh hướng/suy luận. Bản summary
        này phù hợp cho lệnh kiểu "bạn đang nhớ gì về tôi?" hoặc màn hình quản lý.
        """
        records = [
            r for r in self.profile_store.all()
            if (include_sensitive or r.sensitivity not in {"private", "sensitive"})
            and (include_inferred or r.explicitness != "inferred")
        ][: max(0, limit)]
        if not records:
            return "Tôi chưa có đủ thông tin bền vững để tổng hợp về bạn."
        headings = {
            "user": "Thông tin bạn đã chia sẻ",
            "identity": "Danh tính và bối cảnh",
            "communication": "Cách bạn muốn tôi giao tiếp",
            "technical": "Cách bạn làm việc kỹ thuật",
            "workflow": "Cách bạn muốn nhận kết quả",
            "projects": "Dự án",
            "goals": "Mục tiêu và việc đang theo đuổi",
            "preferences": "Sở thích",
            "relationship": "Mẫu tương tác",
            "health": "Sức khỏe",
            "constraints": "Ràng buộc",
        }
        grouped: dict[str, list[str]] = {}
        for record in records:
            root = record.path.split(".", 1)[0]
            label = _humanize_profile_path(record.path)
            value = str(record.value)
            if record.explicitness == "explicit":
                line = f"{label}: {value}"
            elif record.explicitness == "observed":
                line = f"Qua các lần tương tác, tôi nhận thấy khuynh hướng: {label.lower()} — {value}"
            else:
                line = f"Tôi đang suy đoán thận trọng rằng {label.lower()}: {value}"
            if record.scope.kind == "project":
                line += f" (trong dự án {record.scope.key})"
            grouped.setdefault(root, []).append(line)
        lines = ["Đây là những gì tôi đang dùng để hiểu và cá nhân hóa cho bạn:"]
        for root, values in grouped.items():
            lines.append(f"\n{headings.get(root, root.replace('_', ' ').title())}:")
            lines.extend(f"- {value}" for value in values)
        lines.append("\nBạn có thể yêu cầu tôi sửa hoặc quên từng mục; suy luận không được coi là thông tin chắc chắn.")
        return "\n".join(lines)

    def list_memories(
        self,
        *,
        include_inferred: bool = True,
        include_sensitive: bool = False,
        project_id: str = "",
        limit: int = 120,
    ) -> tuple[Any, ...]:
        """Đọc projection qua service boundary cho UI/runtime."""
        rows = []
        for record in self.profile_store.all():
            if not include_sensitive and record.sensitivity in {"private", "sensitive"}:
                continue
            if not include_inferred and record.explicitness == "inferred":
                continue
            if record.scope.kind == "project" and project_id and record.scope.key != project_id:
                continue
            rows.append(record)
            if len(rows) >= max(1, int(limit)):
                break
        return tuple(rows)

    def action_snapshot(self) -> dict[str, Any]:
        """Snapshot action memory qua facade, dành cho panel và diagnostics."""
        return self.action_store.snapshot()

    def get_memory(self, path: str, *, project_id: str = "") -> Any | None:
        scope = UserMemoryScope("project", project_id) if project_id else None
        rows = self.profile_store.get(path, scope=scope)
        return rows[0] if rows else None

    def explain(self, path: str, *, project_id: str = "") -> tuple[MemoryExplanation, ...]:
        scope = UserMemoryScope("project", project_id) if project_id else None
        return tuple(self.sources.explain(record) for record in self.profile_store.get(path, scope=scope))

    def forget(self, path_or_prefix: str, *, project_id: str = "", hard: bool = False) -> int:
        """Ghi tombstone canonical rồi cập nhật mọi projection liên quan."""
        scope = UserMemoryScope("project", project_id) if project_id else UserMemoryScope()
        evidence_ids = self._collect_memory_evidence(path_or_prefix, scope=scope)
        self._retire_episode_interpretations(evidence_ids, hard=hard)
        authority = self.authority_ledger.append(
            "forget", path_or_prefix, scope=scope, hard=hard, evidence_ids=() if hard else evidence_ids,
            source="user_panel", metadata={"project_id": project_id},
        )
        changed = self.profile_store.forget(path_or_prefix, scope=scope, hard=hard, reason="user_authority_forget")
        semantic = self._apply_semantic_authority(authority)
        evidence_ids.update(str(x) for x in semantic.get("evidence_ids", ()) if str(x).strip())
        if hard:
            self._scrub_hard_delete(path_or_prefix, evidence_ids)
            self.trace_journal.scrub_prefix(path_or_prefix)
            # Không ghi lại path vừa xóa vào trace public. Authority ledger chỉ giữ
            # tombstone path, không giữ value đã bị xóa.
            self.trace_journal.append("forget", {"path": "<hard-deleted>", "changed": changed, "hard": True})
        else:
            self.trace_journal.append("forget", {"path": path_or_prefix, "changed": changed, "hard": False})
        return max(changed, int(semantic.get("changed", 0) or 0))

    def correct(
        self,
        path: str,
        value: Any,
        *,
        evidence_ids: Iterable[str],
        project_id: str = "",
    ) -> ApplyResult:
        scope = UserMemoryScope("project", project_id) if project_id else UserMemoryScope()
        self._retire_episode_interpretations(self._collect_memory_evidence(path, scope=scope))
        authority = self.authority_ledger.append(
            "correct", path, scope=scope, value=value, evidence_ids=evidence_ids, source="user_panel",
        )
        result = self.profile_store.correct(
            path, value, evidence_ids=(f"authority:{authority.id}", *authority.evidence_ids), scope=scope,
        )
        self._apply_semantic_authority(authority)
        self.trace_journal.append("correct", {"path": path, "changed": len(result.record_ids), "rejected_count": len(result.rejected)})
        return result

    def confirm(self, path: str, *, project_id: str = "", evidence_ids: Iterable[str] = ()) -> ApplyResult:
        record = self.get_memory(path, project_id=project_id)
        if record is None:
            return ApplyResult(False, rejected=(f"memory_not_found:{path}",), version=self.profile_store.version)
        scope = UserMemoryScope("project", project_id) if project_id else UserMemoryScope()
        authority = self.authority_ledger.append(
            "confirm", path, scope=scope, value=record.value, evidence_ids=evidence_ids, source="user_panel",
        )
        result = self.profile_store.correct(
            path, record.value, evidence_ids=(f"authority:{authority.id}", *authority.evidence_ids), scope=scope,
        )
        self._apply_semantic_authority(authority)
        return result

    def move_scope(
        self,
        path: str,
        *,
        project_id: str = "",
        target_scope_kind: str = "global",
        target_scope_key: str = "",
    ) -> ApplyResult:
        source_scope = UserMemoryScope("project", project_id) if project_id else UserMemoryScope()
        record = self.get_memory(path, project_id=project_id)
        if record is None:
            return ApplyResult(False, rejected=(f"memory_not_found:{path}",), version=self.profile_store.version)
        if target_scope_kind not in {"global", "project"}:
            return ApplyResult(False, rejected=("unsupported_scope",), version=self.profile_store.version)
        if target_scope_kind == "project" and not str(target_scope_key or "").strip():
            return ApplyResult(False, rejected=("missing_project_id",), version=self.profile_store.version)
        target_scope = UserMemoryScope(target_scope_kind, target_scope_key if target_scope_kind == "project" else "")
        if target_scope.identity == source_scope.identity:
            return ApplyResult(False, rejected=("scope_unchanged",), version=self.profile_store.version)
        self._retire_episode_interpretations(self._collect_memory_evidence(path, scope=source_scope))
        authority = self.authority_ledger.append(
            "move_scope", path, scope=source_scope, value=record.value, target_scope=target_scope,
            evidence_ids=record.evidence_ids, source="user_panel",
        )
        self.profile_store.forget(path, scope=source_scope, hard=False, reason="user_authority_scope_move")
        result = self.profile_store.correct(
            path, record.value, evidence_ids=(f"authority:{authority.id}", *record.evidence_ids), scope=target_scope,
        )
        self._apply_semantic_authority(authority)
        return result

    def active_work(self, query: str = "", *, project_id: str = "", session_id: str = ""):
        """Structured goals, commitments và workflow liên quan đến query."""
        scope = UserMemoryScope("project", project_id) if project_id else (UserMemoryScope("session", session_id) if session_id else UserMemoryScope())
        return self.action_store.context(query, scope=scope)

    def add_goal(
        self, title: str, *, evidence_ids: Iterable[str], project_id: str = "",
        description: str = "", next_actions: Iterable[str] = (), priority: float = 0.7,
    ) -> GoalRecord:
        scope = UserMemoryScope("project", project_id) if project_id else UserMemoryScope()
        goal = GoalRecord(id="", title=title, description=description, priority=priority, confidence=0.95,
                          scope=scope, evidence_ids=tuple(evidence_ids), next_actions=tuple(next_actions))
        saved = self.action_store.upsert_goal(goal)
        self.trace_journal.append("goal_upsert", {"goal_id": saved.id, "title": saved.title, "status": saved.status})
        return saved

    def add_workflow(
        self, trigger: str, steps: Iterable[str], *, evidence_ids: Iterable[str], project_id: str = "",
    ) -> WorkflowRecord:
        scope = UserMemoryScope("project", project_id) if project_id else UserMemoryScope()
        flow = WorkflowRecord(id="", trigger=trigger, steps=tuple(steps), scope=scope, confidence=0.95, evidence_ids=tuple(evidence_ids))
        saved = self.action_store.upsert_workflow(flow)
        self.trace_journal.append("workflow_upsert", {"workflow_id": saved.id, "trigger": saved.trigger})
        return saved

    def replay_report(self, *, limit: int = 500):
        return self.replay_debugger.report(limit=limit)

    def import_legacy_beliefs(self, beliefs: Iterable[Any]) -> ApplyResult:
        """Migrate belief của private_mind cũ mà không buộc runtime đổi ngay."""
        ops: list[ProfileOperation] = []
        for belief in beliefs:
            claim = str(getattr(belief, "claim", "") or "").strip()
            ids = tuple(getattr(belief, "evidence_ids", ()) or ())
            if not claim or not ids:
                continue
            facet = str(getattr(belief, "facet", "general") or "general")
            ops.append(ProfileOperation(
                op="reinforce",
                path=f"relationship.private_mind.{facet}",
                value=claim,
                confidence=float(getattr(belief, "confidence", 0.5) or 0.5),
                explicitness="inferred",
                scope=UserMemoryScope("private"),
                cardinality="multi",
                evidence_ids=ids,
                reason="Migrate từ UserModelStore legacy.",
                source="legacy_user_model_import",
            ))
        return self.profile_store.apply(ops, checkpoint_reason="legacy_import")

    def _semantic_operations(self, *, scope: UserMemoryScope | None = None) -> tuple[ProfileOperation, ...]:
        loader = getattr(self.semantic_store, "load", None)
        if not callable(loader):
            return ()
        try:
            operations = self.extractor.from_semantic_items(loader(), scope=scope)
            guarded, _ = self.authority_ledger.guard_operations(operations)
            return guarded
        except Exception:
            return ()

    def _reapply_authority_projection(self) -> None:
        """Replay ledger theo đúng thứ tự thời gian lên profile projection.

        Không nhóm correction và forget thành hai lượt riêng: làm vậy sẽ khiến một
        correction cũ chạy lại sau tombstone mới hơn và hồi sinh dữ liệu đã quên.
        Event sourcing chỉ elegant khi thứ tự event được tôn trọng, một chi tiết nhỏ
        mà dữ liệu cá nhân có xu hướng nhớ rất lâu nếu ta làm sai.
        """
        for event in self.authority_ledger.all():
            evidence = (f"authority:{event.id}", *event.evidence_ids)
            if event.action in {"correct", "confirm"}:
                self.profile_store.correct(event.path, event.value, evidence_ids=evidence, scope=event.scope)
            elif event.action == "forget":
                self.profile_store.forget(event.path, scope=event.scope, hard=event.hard, reason="authority_replay")
            elif event.action == "move_scope" and event.target_scope is not None:
                self.profile_store.forget(event.path, scope=event.scope, hard=False, reason="authority_replay_scope")
                self.profile_store.correct(event.path, event.value, evidence_ids=evidence, scope=event.target_scope)

    def _apply_semantic_authority(self, event: UserMemoryAuthorityEvent) -> dict[str, Any]:
        mutator = getattr(self.semantic_store, "apply_user_authority", None)
        if not callable(mutator):
            return {"changed": 0, "evidence_ids": []}
        target_scope = event.target_scope or event.scope
        try:
            return dict(mutator(
                action=event.action,
                fact_key=event.path,
                value=event.value,
                evidence_ids=event.evidence_ids,
                scope_kind=target_scope.kind,
                scope_key=target_scope.key,
                hard=event.hard,
                authority_event_id=event.id,
            ) or {})
        except Exception:
            return {"changed": 0, "evidence_ids": []}

    def _collect_memory_evidence(self, path_or_prefix: str, *, scope: UserMemoryScope) -> set[str]:
        root = str(path_or_prefix or "").strip().lower()
        evidence: set[str] = set()
        for record in self.profile_store.all(include_inactive=True):
            if record.scope.identity != scope.identity:
                continue
            if record.path == root or record.path.startswith(root + "."):
                evidence.update(record.evidence_ids)
                evidence.add(record.id)
        loader = getattr(self.semantic_store, "load", None)
        if callable(loader):
            try:
                for item in loader():
                    fact_key = str(getattr(item, "fact_key", "") or "").strip().lower()
                    if fact_key == root or fact_key.startswith(root + "."):
                        evidence.update(str(x) for x in getattr(item, "evidence_ids", ()) or ())
                        evidence.add(str(getattr(item, "id", "") or ""))
            except Exception:
                pass
        evidence.discard("")
        return evidence

    def _scrub_hard_delete(self, path: str, evidence_ids: set[str]) -> None:
        self._retire_episode_interpretations(evidence_ids, hard=True)
        for store in (self.event_ledger, self.episode_store, self.action_store):
            scrubber = getattr(store, "scrub_evidence", None)
            if callable(scrubber):
                try:
                    scrubber(evidence_ids)
                except Exception:
                    pass
        # Turn buffer là journal tạm nhưng vẫn có thể giữ câu chứa memory vừa xóa.
        with self._turn_buffer_lock:
            self._turn_buffer = [row for row in self._turn_buffer if str(row.get("id") or "") not in evidence_ids]
            self._save_turn_buffer_locked()

    def _retire_episode_interpretations(self, evidence_ids: Iterable[str], *, hard: bool = False) -> None:
        ids = set(evidence_ids)
        if not ids:
            return
        # Both writes occur under the same source lock. The derived text is removed
        # first; a crash can lose a projection, never expose a forgotten recap.
        with self.episode_store.lock:
            self.episode_rollups.invalidate_evidence(ids)
            if hard:
                self.episode_store.scrub_evidence(ids)
            else:
                self.episode_store.suppress_evidence(ids)




def _scope_from_context(context: Mapping[str, Any] | None, *, session_id: str = "") -> UserMemoryScope:
    payload = dict(context or {})
    project_id = str(payload.get("project_id") or payload.get("project") or "").strip()
    if project_id:
        return UserMemoryScope("project", project_id)
    if session_id:
        return UserMemoryScope("session", session_id)
    return UserMemoryScope()


_PROFILE_PATH_LABELS = {
    "user.name": "Tên",
    "user.nickname": "Biệt danh",
    "user.gender": "Giới tính",
    "user.birth_month": "Tháng sinh",
    "user.current_location": "Nơi ở hiện tại",
    "user.living_location": "Nơi đang sống",
    "user.hometown": "Quê quán",
    "communication.preferred_language": "Ngôn ngữ giao tiếp ưa thích",
    "communication.response_style": "Phong cách trả lời ưa thích",
    "communication.verbosity": "Mức độ chi tiết ưa thích",
    "technical.experience_level": "Mức độ kinh nghiệm kỹ thuật",
    "technical.architecture_preferences": "Kiểu kiến trúc ưa thích",
    "technical.code_comment_language": "Ngôn ngữ chú thích code",
    "workflow.delivery_preference": "Cách muốn nhận kết quả",
}


def _humanize_profile_path(path: str) -> str:
    """Đổi đường dẫn kỹ thuật thành nhãn tiếng Việt dễ đọc.

    Registry sống có thể chứa predicate mới mà code chưa từng biết. Vì vậy hàm
    này có fallback tổng quát thay vì bắt người phát triển bổ sung một bảng nhãn
    mới cho mọi loại memory. Những nhãn builtin chỉ nhằm làm câu chữ tự nhiên hơn.
    """
    normalized = str(path or "").strip().lower()
    if normalized in _PROFILE_PATH_LABELS:
        return _PROFILE_PATH_LABELS[normalized]
    leaf = normalized.rsplit(".", 1)[-1]
    words = leaf.replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else "Thông tin"


def _env_flag(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    return raw not in {"0", "false", "no", "off", "none"}


__all__ = ["LivingUserMemoryConfig", "LivingUserMemoryService", "UserTurnObservation"]
