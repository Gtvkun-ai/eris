# -*- coding: utf-8 -*-
"""Biên dịch user profile thành context packet theo đúng query hiện tại."""
from __future__ import annotations
from core.di import resolve_dependency

import math
import re
import time
from dataclasses import dataclass
from typing import Any, Iterable

from memory.semantic_memory import normalize_text
from memory.memory_admission import MemoryAdmissionPolicy

from .action_memory import ActionMemoryStore
from .clarification import MemoryClarificationPolicy
from .episode_store import UserEpisodeStore
from .models import ProfileContextItem, ProfileContextPacket, ProfileRecord, UserMemoryScope, compact_text
from .store import UserProfileStore


@dataclass(slots=True)
class ProfileContextCompilerConfig:
    max_items: int = 14
    max_episodes: int = 4
    min_score: float = 0.18
    include_inferred_above: float = 0.78
    default_token_budget: int = 900


class ProfileContextCompiler:
    """Chọn đúng phần profile cho từng nhiệm vụ.

    Toàn bộ profile không bao giờ được nhét vào prompt. Context compiler đánh điểm
    theo domain, scope, query relevance, độ chắc chắn và độ mới. Điều này vừa giảm
    token vừa tránh lời đáp bị ám bởi một sở thích không liên quan từ sáu tháng trước.
    """

    def __init__(
        self,
        profile_store: UserProfileStore,
        episode_store: UserEpisodeStore,
        *,
        embedding_index: Any | None = None,
        action_store: ActionMemoryStore | None = None,
        clarification_policy: MemoryClarificationPolicy | None = None,
        config: ProfileContextCompilerConfig | None = None,
        admission_policy: MemoryAdmissionPolicy | None = None,
    ) -> None:
        self.profile_store = profile_store
        self.episode_store = episode_store
        self.embedding_index = embedding_index
        self.action_store = action_store
        self.clarification_policy = resolve_dependency(clarification_policy, lambda: MemoryClarificationPolicy())
        self.config = resolve_dependency(config, lambda: ProfileContextCompilerConfig())
        self.admission_policy = resolve_dependency(admission_policy, lambda: MemoryAdmissionPolicy())

    def compile(
        self,
        query: str,
        *,
        scope: UserMemoryScope | None = None,
        domain: str | None = None,
        token_budget: int | None = None,
        include_sensitive: bool = False,
    ) -> ProfileContextPacket:
        active_scope = scope or UserMemoryScope()
        resolved_domain = domain or infer_domain(query)
        budget = max(160, int(token_budget or self.config.default_token_budget))
        # V41: profile cũng phải qua admission trước relevance. Một record model suy đoán
        # không được vào prompt chỉ vì path khớp query. Explicit user memory vẫn có
        # quyền ưu tiên cao nhất; observed/inferred cần evidence thật.
        records: list[ProfileRecord] = []
        admission_rejected: list[str] = []
        for record in self.profile_store.all():
            if not record.scope.matches(active_scope):
                continue
            if not include_sensitive and record.sensitivity in {"private", "sensitive"}:
                admission_rejected.append(f"{record.path}:sensitive")
                continue
            decision = self.admission_policy.decide_profile_record(record)
            if not decision.admitted:
                admission_rejected.append(f"{record.path}:{decision.reason}")
                continue
            records.append(record)
        q_vec = self._query_vector(query)
        # Batch hóa recall: gom hết document candidate rồi gọi embed_documents MỘT
        # LẦN (qua _dense_similarities) thay vì embed_document từng cái trong _score.
        if q_vec:
            docs = [f"{record.path}: {record.value}" for record in records]
            dense_scores = self._dense_similarities(q_vec, docs)
        else:
            dense_scores = [0.0] * len(records)
        scored: list[tuple[float, ProfileRecord, str]] = []
        for i, record in enumerate(records):
            dense = dense_scores[i] if q_vec else 0.0
            score, reason = self._score(record, query=query, domain=resolved_domain, dense=dense, active_scope=active_scope)
            if score >= self.config.min_score:
                scored.append((score, record, reason))
        scored.sort(key=lambda x: x[0], reverse=True)

        items: list[ProfileContextItem] = []
        clarifications: list[str] = []
        estimated_tokens = 0
        for score, record, reason in scored[: self.config.max_items * 2]:
            family = self.profile_store.get(record.path, scope=record.scope, include_inactive=True)
            decision = self.clarification_policy.decide(family)
            if decision.mode == "omit":
                continue
            text = f"{record.path}: {record.value}"
            cost = max(8, len(text) // 4)
            if items and estimated_tokens + cost > int(budget * 0.68):
                break
            items.append(ProfileContextItem(
                path=record.path,
                value=record.value,
                score=score,
                reason=reason,
                evidence_ids=record.evidence_ids,
                scope=record.scope,
                explicitness=record.explicitness,
                use_mode=decision.mode,
                uncertainty_note=decision.message,
            ))
            if decision.message:
                clarifications.append(decision.message)
            estimated_tokens += cost
            if len(items) >= self.config.max_items:
                break

        episodes = self.episode_store.search(
            query,
            limit=self.config.max_episodes,
            scope=active_scope,
            embedding_index=self.embedding_index,
        )
        # Nếu query quá chung, chỉ lấy episode gần đây có việc đang mở.
        if not normalize_text(query):
            episodes = tuple(x for x in self.episode_store.recent(limit=self.config.max_episodes, scope=active_scope) if x.open_loops or x.importance >= 0.72)
        action_context = self.action_store.context(query, scope=active_scope) if self.action_store is not None else None
        return ProfileContextPacket(
            query=query,
            domain=resolved_domain,
            items=tuple(items),
            episodes=episodes,
            action_context=action_context,
            clarifications=tuple(dict.fromkeys(clarifications)),
            token_budget=budget,
            diagnostics=(
                f"profile_candidates={len(records)}",
                f"selected={len(items)}",
                f"admission_rejected={len(admission_rejected)}",
                f"domain={resolved_domain}",
                *(f"reject:{row}" for row in admission_rejected[:8]),
            ),
        )

    def _score(
        self,
        record: ProfileRecord,
        *,
        query: str,
        domain: str,
        dense: float,
        active_scope: UserMemoryScope,
    ) -> tuple[float, str]:
        path_domain = record.path.split(".", 1)[0]
        domain_score = 1.0 if path_domain == domain else _domain_affinity(domain, record.path)
        lexical = _lexical_similarity(query, f"{record.path} {record.value}")
        scope_score = 1.0 if record.scope.identity == active_scope.identity else (0.78 if record.scope.kind == "global" else 0.0)
        recency = _recency(record.last_confirmed_at)
        trust = record.trust_weight
        # Explicit profile có ích ngay cả khi query không trùng từ, nhưng domain vẫn
        # phải phù hợp. Dense/lexical chỉ hỗ trợ, không được quyền đè bằng chứng.
        score = trust * 0.34 + domain_score * 0.23 + lexical * 0.18 + dense * 0.13 + scope_score * 0.08 + recency * 0.04
        reason = f"trust={trust:.2f}, domain={domain_score:.2f}, lexical={lexical:.2f}, dense={dense:.2f}"
        return max(0.0, min(1.0, score)), reason

    def _query_vector(self, query: str) -> tuple[float, ...] | None:
        if not query or self.embedding_index is None:
            return None
        embed = getattr(self.embedding_index, "embed_query", None)
        if not callable(embed):
            return None
        try:
            return tuple(float(x) for x in embed(query))
        except Exception:
            return None

    def _dense_similarities(self, query_vector: tuple[float, ...], documents: list[str]) -> list[float]:
        """Batch dense similarity: gọi embed_documents MỘT LẦN cho cả list document.

        Giữ nguyên công thức cosine của ``_dense_similarity`` (chỉ đổi cách lấy vector
        từ từng-cái sang gom-một-lần). Fallback: embedding_index None, không có
        embed_documents callable, embed lỗi, hoặc độ dài vector không khớp số document
        → tất cả 0.0 (recall dùng lexical, KHÔNG crash). Cache vẫn nằm trong
        EmbeddingIndex.embed_documents (_encode_with_cache), nên document cũ vẫn cache-hit.
        """
        if not documents:
            return []
        embed_many = getattr(self.embedding_index, "embed_documents", None)
        if self.embedding_index is None or not callable(embed_many):
            return [0.0] * len(documents)
        try:
            vectors = embed_many(documents)
            # Giữ len() TRONG biên fail-soft: provider trả None/giá trị không
            # len() được thì rơi về lexical thay vì raise làm sập recall.
            if len(vectors) != len(documents):
                return [0.0] * len(documents)
            # Vật chất hoá trước khi tính cosine để một row hỏng cũng bị bắt ở đây.
            return [self._cosine_vec(query_vector, vector) for vector in vectors]
        except Exception:
            return [0.0] * len(documents)

    def _cosine_vec(self, query_vector: tuple[float, ...], raw_vector: Iterable[float]) -> float:
        try:
            vector = tuple(float(x) for x in raw_vector)
        except Exception:
            return 0.0
        if not vector or len(vector) != len(query_vector):
            return 0.0
        dot = sum(a * b for a, b in zip(query_vector, vector))
        na = math.sqrt(sum(a * a for a in query_vector))
        nb = math.sqrt(sum(b * b for b in vector))
        return max(0.0, dot / (na * nb)) if na and nb else 0.0

    def _dense_similarity(self, query_vector: tuple[float, ...], document: str) -> float:
        """Dense similarity cho một document (giữ cho tương thích/caller cũ)."""
        embed = getattr(self.embedding_index, "embed_document", None)
        if not callable(embed):
            return 0.0
        try:
            vector = embed(document)
        except Exception:
            return 0.0
        return self._cosine_vec(query_vector, vector)


def infer_domain(query: str) -> str:
    norm = normalize_text(query)
    groups = {
        "technical": ("code", "python", "bug", "loi", "kien truc", "embedding", "model", "api", "memory", "source", "refactor"),
        "workflow": ("file", "gui", "artifact", "ban giao", "patch", "zip", "tai"),
        "communication": ("tra loi", "noi", "viet", "giong", "tone", "ngan", "dai", "tu nhien"),
        "goals": ("muon", "du dinh", "ke hoach", "tiep theo", "muc tieu", "lam tiep"),
        "projects": ("du an", "project", "eris", "repo"),
        "identity": ("toi la ai", "ten", "gioi tinh", "que", "song o"),
        "health": ("suc khoe", "benh", "thuoc", "dau", "ngu"),
    }
    for domain, cues in groups.items():
        if any(cue in norm for cue in cues):
            return domain
    return "general"


def _domain_affinity(domain: str, path: str) -> float:
    root = path.split(".", 1)[0]
    affinities = {
        "technical": {"workflow": 0.55, "communication": 0.48, "projects": 0.72},
        "workflow": {"technical": 0.62, "communication": 0.48, "projects": 0.64},
        "communication": {"workflow": 0.42, "technical": 0.36},
        "goals": {"projects": 0.74, "workflow": 0.48},
        "projects": {"technical": 0.72, "goals": 0.76, "workflow": 0.52},
        "identity": {"communication": 0.30},
        "general": {"communication": 0.48, "workflow": 0.38, "goals": 0.44, "projects": 0.42, "identity": 0.44},
    }
    return affinities.get(domain, {}).get(root, 0.12)


def _lexical_similarity(query: str, text: str) -> float:
    q = set(normalize_text(query).split())
    d = set(normalize_text(text).split())
    if not q or not d:
        return 0.0
    return len(q & d) / max(1, len(q))


def _recency(timestamp: float) -> float:
    age_days = max(0.0, (time.time() - float(timestamp or 0.0)) / 86400.0)
    return 1.0 / (1.0 + age_days / 45.0)


__all__ = ["ProfileContextCompiler", "ProfileContextCompilerConfig", "infer_domain"]
