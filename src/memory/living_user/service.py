# -*- coding: utf-8 -*-
"""Facade cấp cao cho living user memory.

Runtime chỉ nên gọi service này, thay vì tự mở profile store, episode store rồi
trộn business rule vào chat cycle. Một facade có ích là facade làm giảm quyền của
caller, không phải chỉ đổi tên sáu method rồi thêm logo kiến trúc.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .action_memory import ActionMemoryStore, GoalRecord, CommitmentRecord, WorkflowRecord
from .clarification import MemoryClarificationPolicy
from .context_compiler import ProfileContextCompiler, ProfileContextCompilerConfig
from .dreamer import UserProfileDreamer
from .episode_builder import UserEpisodeBuilder
from .episode_store import UserEpisodeStore
from .extractor import UserProfileExtractor, UserProfileModelAdapter
from .models import DreamReport, ProfileContextPacket, ProfileOperation, UserEpisode, UserMemoryScope
from .sources import MemoryExplanation, MemorySourceTracker
from .store import ApplyResult, UserProfileStore, UserProfileStoreConfig
from .trace import MemoryReplayDebugger, MemoryTraceJournal


@dataclass(slots=True)
class LivingUserMemoryConfig:
    enabled: bool = True
    auto_observe_turns: bool = True
    auto_sync_semantic: bool = True
    auto_dream_on_maintenance: bool = True
    context_token_budget: int = 900
    profile_filename: str = "living_user_profile.json"
    episode_filename: str = "living_user_episodes.json"
    action_filename: str = "living_user_actions.json"
    trace_filename: str = "living_user_trace.jsonl"

    @classmethod
    def from_env(cls) -> "LivingUserMemoryConfig":
        return cls(
            enabled=_env_flag("ERIS_LIVING_USER_MODEL_ENABLED", True),
            auto_observe_turns=_env_flag("ERIS_LIVING_USER_AUTO_OBSERVE", True),
            auto_sync_semantic=_env_flag("ERIS_LIVING_USER_SYNC_SEMANTIC", True),
            auto_dream_on_maintenance=_env_flag("ERIS_LIVING_USER_AUTO_DREAM", True),
            context_token_budget=max(200, int(os.getenv("ERIS_LIVING_USER_CONTEXT_TOKENS", "900") or 900)),
        )


@dataclass(slots=True)
class UserTurnObservation:
    applied: int = 0
    rejected: int = 0
    operations: tuple[ProfileOperation, ...] = ()
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
    ) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.config = config or LivingUserMemoryConfig.from_env()
        self.semantic_store = semantic_store
        self.episodic_store = episodic_store
        self.event_ledger = event_ledger
        self.embedding_index = embedding_index
        self.model_adapter = model_adapter
        self.profile_store = UserProfileStore(self.base_dir / self.config.profile_filename, config=profile_store_config)
        self.episode_store = UserEpisodeStore(self.base_dir / self.config.episode_filename)
        self.action_store = ActionMemoryStore(self.base_dir / self.config.action_filename)
        self.trace_journal = MemoryTraceJournal(self.base_dir / self.config.trace_filename)
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
    ) -> None:
        """Ghi lượt vào journal ngắn để episode builder có đủ hai phía hội thoại."""
        if not self.config.enabled:
            return
        clean = " ".join(str(text or "").split())
        if not clean or role not in {"user", "assistant", "eris"}:
            return
        sid = str(session_id or self._active_session_id or "runtime_session").strip()
        action_scope = _scope_from_context(context, session_id=sid)
        action_result = self.action_store.observe_turn(role, clean, evidence_id=str(turn_id or f"turn_{uuid.uuid4().hex[:16]}"), scope=action_scope)
        self.trace_journal.append("conversation_turn", {
            "role": role, "session_id": sid, "action_ids": action_result,
            "project_id": action_scope.key if action_scope.kind == "project" else "",
        })
        with self._turn_buffer_lock:
            if self._active_session_id and sid != self._active_session_id and self._turn_buffer:
                self._flush_buffer_locked(run_dream=True)
            self._active_session_id = sid
            self._turn_buffer.append({
                "id": str(turn_id or f"turn_{uuid.uuid4().hex[:16]}"),
                "role": "assistant" if role == "eris" else role,
                "text": clean[:1800],
                "timestamp": time.time(),
                "context": dict(context or {}),
            })
            self._turn_buffer = self._turn_buffer[-48:]
            self._save_turn_buffer_locked()
            # Phiên dài được checkpoint thành episode giữa chừng, nhưng giữ vài
            # lượt cuối để mạch tiếp theo không bị cắt cụt.
            if len(self._turn_buffer) >= 28 and role in {"assistant", "eris"}:
                self._flush_buffer_locked(run_dream=False, keep_tail=4)

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

    def observe_turn(
        self,
        user_text: str,
        *,
        evidence_ids: Iterable[str],
        context: Mapping[str, Any] | None = None,
    ) -> UserTurnObservation:
        if not self.config.enabled or not self.config.auto_observe_turns:
            return UserTurnObservation(diagnostics=("living_user_disabled",))
        ops = self.extractor.from_turn(
            user_text,
            evidence_ids=evidence_ids,
            context=context,
            existing_profile=self.profile_store.snapshot(limit=100),
        )
        result = self.profile_store.apply(ops, checkpoint_reason="observe_user_turn")
        self.trace_journal.append("observe_turn", {
            "applied": len(result.record_ids), "rejected_count": len(result.rejected),
            "operation_count": len(ops), "paths": [op.path for op in ops],
            "operations": [op.to_dict() for op in ops],
        })
        return UserTurnObservation(
            applied=len(result.record_ids),
            rejected=len(result.rejected),
            operations=ops,
            diagnostics=result.rejected,
        )

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
        return self.profile_store.apply(ops, checkpoint_reason="semantic_sync")

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

    def compile_context(
        self,
        query: str,
        *,
        project_id: str = "",
        session_id: str = "",
        domain: str | None = None,
        token_budget: int | None = None,
        include_sensitive: bool = False,
    ) -> ProfileContextPacket:
        scope = UserMemoryScope("project", project_id) if project_id else (UserMemoryScope("session", session_id) if session_id else UserMemoryScope())
        packet = self.context_compiler.compile(
            query,
            scope=scope,
            domain=domain,
            token_budget=token_budget,
            include_sensitive=include_sensitive,
        )
        self.trace_journal.append("compile_context", {
            "query": query[:500], "domain": packet.domain,
            "selected_paths": [item.path for item in packet.items],
            "use_modes": {item.path: item.use_mode for item in packet.items},
            "episode_ids": [episode.id for episode in packet.episodes],
            "goal_ids": [goal.id for goal in getattr(packet.action_context, "goals", ())],
            "workflow_ids": [flow.id for flow in getattr(packet.action_context, "workflows", ())],
        })
        return packet

    def summary(self, *, include_sensitive: bool = False, limit: int = 60) -> dict[str, Any]:
        records = self.profile_store.snapshot(include_sensitive=include_sensitive, limit=limit)
        episodes = [x.to_dict() for x in self.episode_store.recent(limit=8)]
        return {
            "profile": records,
            "recent_episodes": episodes,
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

    def explain(self, path: str, *, project_id: str = "") -> tuple[MemoryExplanation, ...]:
        scope = UserMemoryScope("project", project_id) if project_id else None
        return tuple(self.sources.explain(record) for record in self.profile_store.get(path, scope=scope))

    def forget(self, path_or_prefix: str, *, project_id: str = "", hard: bool = False) -> int:
        scope = UserMemoryScope("project", project_id) if project_id else None
        changed = self.profile_store.forget(path_or_prefix, scope=scope, hard=hard, reason="user_request")
        if hard:
            self.trace_journal.scrub_prefix(path_or_prefix)
            # Không ghi lại path vừa được yêu cầu xóa. Audit "đã xóa" là đủ.
            self.trace_journal.append("forget", {"path": "<hard-deleted>", "changed": changed, "hard": True})
        else:
            self.trace_journal.append("forget", {"path": path_or_prefix, "changed": changed, "hard": False})
        return changed

    def correct(
        self,
        path: str,
        value: Any,
        *,
        evidence_ids: Iterable[str],
        project_id: str = "",
    ) -> ApplyResult:
        scope = UserMemoryScope("project", project_id) if project_id else UserMemoryScope()
        result = self.profile_store.correct(path, value, evidence_ids=evidence_ids, scope=scope)
        self.trace_journal.append("correct", {"path": path, "changed": len(result.record_ids), "rejected_count": len(result.rejected)})
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
            return self.extractor.from_semantic_items(loader(), scope=scope)
        except Exception:
            return ()



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
