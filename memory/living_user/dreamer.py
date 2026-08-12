# -*- coding: utf-8 -*-
"""Dreaming/consolidation cho living user profile.

Dreamer không chạy sau mọi turn. Nó đọc episode, semantic facts và profile hiện
có, rồi đề xuất một tập patch nhỏ. Patch vẫn phải qua validator/store.
"""
from __future__ import annotations
from core.di import resolve_dependency

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .extractor import UserProfileModelAdapter
from .models import DreamReport, ProfileOperation, UserEpisode, UserMemoryScope, clamp01
from .store import UserProfileStore


@dataclass(slots=True)
class UserProfileDreamConfig:
    min_episode_importance: float = 0.42
    max_episodes: int = 12
    max_operations: int = 18
    min_model_confidence: float = 0.64


class UserProfileDreamer:
    def __init__(
        self,
        store: UserProfileStore,
        *,
        model_adapter: UserProfileModelAdapter | None = None,
        config: UserProfileDreamConfig | None = None,
    ) -> None:
        self.store = store
        self.model_adapter = model_adapter
        self.config = resolve_dependency(config, lambda: UserProfileDreamConfig())

    def consolidate(
        self,
        episodes: Iterable[UserEpisode],
        *,
        semantic_operations: Iterable[ProfileOperation] = (),
        reason: str = "idle",
        scope: UserMemoryScope | None = None,
    ) -> DreamReport:
        chosen = [x for x in episodes if x.importance >= self.config.min_episode_importance]
        chosen = sorted(chosen, key=lambda x: (x.importance, x.ended_at), reverse=True)[: self.config.max_episodes]
        ops = list(semantic_operations)
        ops.extend(self._deterministic_episode_ops(chosen, scope=scope))
        ops.extend(self._model_ops(chosen, reason=reason, scope=scope))
        ops = _dedupe(ops)[: self.config.max_operations]
        if not ops:
            return DreamReport(episode_ids=tuple(x.id for x in chosen), diagnostics=("no_profile_operations",))
        result = self.store.apply(ops, checkpoint_reason=f"dream:{reason}")
        return DreamReport(
            applied=len(result.record_ids),
            rejected=len(result.rejected),
            operations=tuple(ops),
            episode_ids=tuple(x.id for x in chosen),
            diagnostics=tuple(result.rejected),
        )

    def _deterministic_episode_ops(self, episodes: list[UserEpisode], *, scope: UserMemoryScope | None) -> list[ProfileOperation]:
        out: list[ProfileOperation] = []
        for episode in episodes:
            effective_scope = scope or episode.scope
            for signal in episode.user_signals:
                path, value = _signal_to_path(signal)
                if not path:
                    continue
                out.append(ProfileOperation(
                    op="reinforce",
                    path=path,
                    value=value,
                    confidence=clamp01(0.62 + episode.importance * 0.22),
                    explicitness="observed",
                    scope=effective_scope,
                    cardinality="multi" if path.endswith("rules") or path.endswith("patterns") else "single",
                    evidence_ids=episode.evidence_ids,
                    reason=f"Pattern lặp lại trong episode: {episode.title}",
                    source="dream_deterministic",
                    metadata={"episode_id": episode.id},
                ))
            for loop in episode.open_loops[:4]:
                out.append(ProfileOperation(
                    op="reinforce",
                    path="goals.open_loops",
                    value=loop,
                    confidence=clamp01(0.55 + episode.importance * 0.25),
                    explicitness="observed",
                    scope=effective_scope,
                    cardinality="multi",
                    evidence_ids=episode.evidence_ids,
                    reason="Việc người dùng để mở ở cuối episode.",
                    source="dream_deterministic",
                    metadata={"episode_id": episode.id, "expires_at": episode.ended_at + 60 * 60 * 24 * 45},
                ))
        return out

    def _model_ops(self, episodes: list[UserEpisode], *, reason: str, scope: UserMemoryScope | None) -> list[ProfileOperation]:
        if self.model_adapter is None or not episodes:
            return []
        payload = {
            "reason": reason,
            "episodes": [x.to_dict() for x in episodes],
            "existing_profile": self.store.snapshot(limit=160),
            "scope": (scope or UserMemoryScope()).to_dict(),
            "instructions": [
                "Chỉ tạo pattern hữu ích cho tương tác tương lai.",
                "Phân biệt explicit/observed/inferred.",
                "Không suy diễn thuộc tính nhạy cảm.",
                "Dùng update/supersede khi thông tin đã thay đổi.",
                "Không chép nguyên văn cả cuộc trò chuyện vào profile.",
            ],
        }
        try:
            response = self.model_adapter.propose_profile_operations(payload)
        except Exception:
            return []
        rows = response.get("operations") if isinstance(response, Mapping) else None
        if not isinstance(rows, list):
            return []
        out: list[ProfileOperation] = []
        evidence_union = tuple(dict.fromkeys(eid for episode in episodes for eid in episode.evidence_ids))
        for row in rows[: self.config.max_operations]:
            if not isinstance(row, Mapping):
                continue
            op = ProfileOperation.from_dict({
                **dict(row),
                "evidence_ids": list(row.get("evidence_ids") or evidence_union),
                "scope": row.get("scope") or (scope or UserMemoryScope()).to_dict(),
                "source": row.get("source") or "dream_model",
            })
            if op.confidence < self.config.min_model_confidence:
                continue
            if op.sensitivity == "sensitive" and op.explicitness != "explicit":
                continue
            out.append(op)
        return out


def _signal_to_path(signal: str) -> tuple[str, str]:
    lowered = signal.lower()
    if "chú thích" in lowered:
        return "technical.code_comment_language", "vi"
    if "file hoàn chỉnh" in lowered:
        return "workflow.delivery_preference", "ưu tiên file hoàn chỉnh có thể dùng ngay"
    if "máy móc" in lowered:
        return "communication.negative_feedback_patterns", "tránh public wording máy móc"
    if "kiến trúc" in lowered or "vá tay" in lowered:
        return "technical.architecture_preferences", "ưu tiên kiến trúc mở, ít hard-code và nợ kỹ thuật rõ ràng"
    if "phân tích kỹ" in lowered:
        return "communication.response_rules", "phân tích kỹ trước khi triển khai thay đổi lớn"
    return "", ""


def _dedupe(ops: Iterable[ProfileOperation]) -> list[ProfileOperation]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[ProfileOperation] = []
    for op in ops:
        key = (op.op, op.path, repr(op.value), op.scope.identity)
        if key in seen:
            continue
        seen.add(key)
        out.append(op)
    return out


__all__ = ["UserProfileDreamConfig", "UserProfileDreamer"]
