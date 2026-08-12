# -*- coding: utf-8 -*-
"""Bộ kiểm toán và dọn dẹp Living User Memory.

Phân vai cố ý rõ ràng:
- Gemma/profile model chỉ đề xuất hoặc ghi nhận memory candidate.
- Qwen embedding chỉ gom các record gần nghĩa để giảm context gửi sang critic.
- DeepSeek critic đề xuất thao tác dọn dẹp.
- Validator deterministic trong module này mới có quyền áp dụng thay đổi.

Critic không được xóa trực tiếp file JSON. Con người đã thử mô hình "AI có toàn quyền
vì prompt bảo nó cẩn thận" đủ nhiều lần rồi; kết quả thường giàu tính giáo dục.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from .models import ProfileRecord, value_fingerprint

ReviewCallable = Callable[[str, str, int], str | None]


# Các cụm này chỉ dùng để bắt open-loop đã tự tuyên bố là xong. Đây là cleanup
# deterministic, không phải suy đoán cảm xúc hay sở thích của người dùng.
_RESOLVED_MARKERS = (
    "resolved", "completed", "done", "finished", "closed",
    "đã giải quyết", "đã xong", "hoàn tất", "hoàn thành", "ổn rồi",
    "được rồi", "chắc dị dc rồi", "không còn cần", "không cần nữa",
)
_BAD_PATH_SEGMENT = re.compile(r"(?:^|\.)upr_[0-9a-f]{8,}(?:\.|$)", re.IGNORECASE)


_LIVING_CURATOR_SYSTEM = """You are the memory curator for ERIS.
Your job is to clean a canonical user profile, not to invent a nicer biography.

Hard rules:
- Output ONLY one JSON object. No markdown and no prose outside JSON.
- Use only record IDs present in the input.
- Evidence is stronger than model confidence. A confidence number written by another
  model is not proof.
- Do not alter or remove user-authority records.
- Prefer KEEP when a stable explicit preference has direct evidence.
- ARCHIVE null/empty claims, obsolete/superseded open loops, resolved temporary open loops, malformed paths, unsupported
  emotional inference, one-off scene details, and claims that merely paraphrase the
  current conversation without durable value.
- HIDE from UI any records that are purely technical state, temporary tracking, or have no reading value for the user (but might be useful for AI context). Use the "hide" action.
- REWRITE (translate/fix) values that are in English, mixed languages (Vietnamese-English), contain abbreviations, or are unaccented Vietnamese (tiếng Việt không dấu). Output natural, proper, and correctly accented Vietnamese. Keep the exact meaning. Use the "rewrite" action.
- WEAKEN uncertain inferred/observed claims instead of deleting them when evidence is
  plausible but weak.
- MERGE only records on the same path and scope that express the same durable fact.
- Do not merge contradictions. Keep the strongest evidenced record and archive/weaken
  the weaker model-generated record.
- Do not rewrite values (except for translation/fixing presentation) and do not create new records.

Allowed schema:
{
  "operations": [
    {
      "action": "keep" | "archive" | "weaken" | "merge" | "rewrite" | "hide",
      "record_ids": ["upr_..."],
      "amount": 0.0,
      "value": "translated text here (only for rewrite action)",
      "reason": "short evidence-based reason"
    }
  ]
}

For archive/keep/weaken use exactly one record ID. For merge use two or more IDs.
For weaken, amount must be between 0.05 and 0.30.
"""

_LIVING_CURATOR_USER = """Review these Living User Memory candidates.

Candidate records:
{records}

Embedding/structural clusters:
{clusters}

Return safe operations for records that need action. Omit records that should simply remain unchanged.
"""


@dataclass(slots=True)
class LivingUserCuratorConfig:
    """Cấu hình dọn profile; đọc env để runtime có thể chỉnh mà không sửa code."""

    max_review_records: int = 40
    max_clusters: int = 10
    duplicate_cosine: float = 0.86
    stale_days: float = 90.0
    history_snapshots: int = 8
    review_max_age_sec: float = 24 * 3600.0

    @classmethod
    def from_env(cls) -> "LivingUserCuratorConfig":
        return cls(
            max_review_records=max(8, _env_int("ERIS_MEMORY_GC_LIVING_LIMIT", 40)),
            max_clusters=max(2, _env_int("ERIS_MEMORY_GC_LIVING_CLUSTER_LIMIT", 10)),
            duplicate_cosine=min(0.99, max(0.50, _env_float("ERIS_MEMORY_GC_LIVING_DUPLICATE_COSINE", 0.86))),
            stale_days=max(7.0, _env_float("ERIS_MEMORY_GC_LIVING_STALE_DAYS", 90.0)),
            history_snapshots=max(2, _env_int("ERIS_LIVING_USER_HISTORY_SNAPSHOTS", 8)),
            review_max_age_sec=max(600.0, _env_float("ERIS_MEMORY_GC_LIVING_REVIEW_MAX_AGE_SEC", 24 * 3600.0)),
        )


@dataclass(slots=True)
class LivingUserCuratorResult:
    reviewed: int = 0
    proposed: int = 0
    applied: int = 0
    archived: int = 0
    weakened: int = 0
    merged: int = 0
    rewritten: int = 0
    hidden: int = 0
    protected: int = 0
    history_removed: int = 0
    skipped_reason: str = ""
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class LivingUserMemoryCurator:
    """Qwen gom cụm, DeepSeek đề xuất, validator deterministic áp dụng."""

    def __init__(
        self,
        living_user: Any,
        *,
        reviewer: ReviewCallable | None,
        embedding_index: Any | None = None,
        config: LivingUserCuratorConfig | None = None,
    ) -> None:
        self.living_user = living_user
        self.reviewer = reviewer
        self.embedding_index = embedding_index or getattr(living_user, "embedding_index", None)
        self.config = config or LivingUserCuratorConfig.from_env()

    def run(self) -> LivingUserCuratorResult:
        result = LivingUserCuratorResult()
        store = getattr(self.living_user, "profile_store", None)
        if store is None or not callable(getattr(store, "all", None)):
            result.skipped_reason = "no_profile_store"
            return result

        records = list(store.all(include_inactive=True))
        active = [r for r in records if r.status in {"active", "disputed"}]
        if not active:
            result.skipped_reason = "empty_profile"
            result.history_removed = self._compact_history(store)
            return result

        protected_ids = self._protected_record_ids(active)
        result.protected = len(protected_ids)

        # Bước 1: dọn những lỗi cấu trúc chắc chắn, không đốt token critic cho null.
        deterministic = self._deterministic_operations(active, protected_ids)
        if deterministic:
            applied = store.apply_curator_operations(
                deterministic,
                protected_record_ids=protected_ids,
                checkpoint_reason="living_user_deterministic_gc",
            )
            self._accumulate_apply_result(result, applied)
            # Reload projection sau mutation để critic không đánh giá record vừa archive.
            active = [r for r in store.all(include_inactive=True) if r.status in {"active", "disputed"}]

        candidates = self._select_candidates(active, protected_ids)
        clusters = self._build_clusters(active, candidates)
        candidate_ids = {r.id for r in candidates}
        for cluster in clusters:
            candidate_ids.update(cluster)

        # Không có gì đáng ngờ thì chỉ compact undo history. Critic cũng cần nghỉ,
        # dù hiện tại nó có vẻ rảnh hơn phần còn lại của hệ thống.
        if not candidate_ids:
            result.skipped_reason = "no_candidates"
            result.history_removed = self._compact_history(store)
            return result

        selected = [r for r in active if r.id in candidate_ids][: self.config.max_review_records]
        result.reviewed = len(selected)
        if not selected:
            result.skipped_reason = "no_selected_records"
            result.history_removed = self._compact_history(store)
            return result
        if self.reviewer is None:
            result.skipped_reason = "no_critic_reviewer"
            result.history_removed = self._compact_history(store)
            return result

        prompt = _LIVING_CURATOR_USER.format(
            records=self._format_records(selected, protected_ids),
            clusters=self._format_clusters(clusters, selected),
        )
        raw = self.reviewer(_LIVING_CURATOR_SYSTEM, prompt, 2200)
        if not raw:
            result.warnings.append("critic_no_response")
            result.history_removed = self._compact_history(store)
            return result

        operations = self._parse_operations(raw)
        result.proposed = len(operations)
        safe_ops = self._validate_operations(
            operations,
            records={r.id: r for r in active},
            protected_ids=protected_ids,
            cluster_sets=[set(x) for x in clusters],
        )
        if safe_ops:
            applied = store.apply_curator_operations(
                safe_ops,
                protected_record_ids=protected_ids,
                checkpoint_reason="deepseek_critic_living_user_gc",
            )
            self._accumulate_apply_result(result, applied)
        elif operations:
            result.notes.append("critic_operations_rejected_by_validator")

        result.history_removed = self._compact_history(store)
        return result

    # ------------------------------------------------------------------
    # Candidate selection
    # ------------------------------------------------------------------

    def _deterministic_operations(
        self,
        records: Sequence[ProfileRecord],
        protected_ids: set[str],
    ) -> list[dict[str, Any]]:
        operations: list[dict[str, Any]] = []
        for record in records:
            if record.id in protected_ids:
                continue
            value = _value_text(record.value)
            reason = ""
            if record.value is None or not value:
                reason = "Giá trị null/rỗng không mang thông tin có thể truy hồi."
            elif record.path.startswith("open_loops.") and _contains_resolved_marker(value):
                reason = "Open loop tự mô tả là đã hoàn tất nên phải archive."
            if reason:
                operations.append({"action": "archive", "record_ids": [record.id], "reason": reason})
        return operations

    def _select_candidates(
        self,
        records: Sequence[ProfileRecord],
        protected_ids: set[str],
    ) -> list[ProfileRecord]:
        now = time.time()
        stale_before = now - self.config.stale_days * 86400.0
        by_path_scope: dict[tuple[str, str], list[ProfileRecord]] = {}
        for record in records:
            by_path_scope.setdefault((record.path, record.scope.identity), []).append(record)

        ranked: list[tuple[int, float, ProfileRecord]] = []
        for record in records:
            if record.id in protected_ids:
                continue
            suspicion = 0
            value = _value_text(record.value)
            if _BAD_PATH_SEGMENT.search(record.path):
                suspicion += 10
            if record.status == "disputed":
                suspicion += 8
            if len(by_path_scope.get((record.path, record.scope.identity), ())) > 1:
                suspicion += 7
            if record.source in {"profile_model", "dream_model", "legacy_user_model_import"}:
                suspicion += 3
            if record.explicitness == "inferred":
                suspicion += 3
            elif record.explicitness == "observed":
                suspicion += 1
            if not record.evidence_ids:
                suspicion += 8
            if len(value) > 700:
                suspicion += 4
            if record.updated_at < stale_before and record.explicitness != "explicit":
                suspicion += 3
            if record.confidence >= 0.98 and record.source in {"profile_model", "dream_model"}:
                suspicion += 2
            if record.path.startswith(("needs.", "relationship.")) and record.source in {"profile_model", "dream_model"}:
                suspicion += 2
            if suspicion > 0:
                ranked.append((suspicion, record.updated_at, record))

        ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return [row[2] for row in ranked[: self.config.max_review_records]]

    def _build_clusters(
        self,
        records: Sequence[ProfileRecord],
        candidates: Sequence[ProfileRecord],
    ) -> list[list[str]]:
        clusters: list[list[str]] = []
        seen: set[frozenset[str]] = set()

        # Cụm cấu trúc: cùng path + scope luôn đáng cho critic xem cùng nhau.
        grouped: dict[tuple[str, str], list[ProfileRecord]] = {}
        for record in records:
            grouped.setdefault((record.path, record.scope.identity), []).append(record)
        for group in grouped.values():
            if len(group) < 2:
                continue
            ids = [r.id for r in sorted(group, key=lambda x: x.trust_weight, reverse=True)]
            key = frozenset(ids)
            if key not in seen:
                clusters.append(ids)
                seen.add(key)

        # Cụm embedding: Qwen chỉ làm nhiệm vụ tìm hàng xóm gần nghĩa. Không có
        # embedding thì hệ thống vẫn dọn bằng rule/path, không giả vờ cosine tồn tại.
        pool_by_id: dict[str, ProfileRecord] = {}
        for record in (*candidates, *records):
            pool_by_id.setdefault(record.id, record)
        pool = list(pool_by_id.values())[: max(self.config.max_review_records * 2, 48)]
        vectors = self._embed_records(pool)
        if vectors:
            for i, left in enumerate(pool):
                near = [left.id]
                for j in range(i + 1, len(pool)):
                    right = pool[j]
                    if left.scope.identity != right.scope.identity:
                        continue
                    # Chỉ gom hàng xóm có cùng root hoặc cùng path. Hai câu tình cảm
                    # và một sở thích cờ vua không được cưới nhau vì vector thấy thơ.
                    if _path_root(left.path) != _path_root(right.path) and left.path != right.path:
                        continue
                    score = _cosine(vectors[i], vectors[j])
                    if score >= self.config.duplicate_cosine:
                        near.append(right.id)
                if len(near) >= 2:
                    key = frozenset(near)
                    if key not in seen:
                        clusters.append(near)
                        seen.add(key)
                if len(clusters) >= self.config.max_clusters:
                    break

        return clusters[: self.config.max_clusters]

    def _embed_records(self, records: Sequence[ProfileRecord]) -> list[Sequence[float]]:
        index = self.embedding_index
        embed_many = getattr(index, "embed_documents", None)
        if index is None or not callable(embed_many) or not records:
            return []
        try:
            vectors = embed_many([_record_text(record) for record in records])
            if len(vectors) != len(records):
                return []
            return [tuple(float(x) for x in vector) for vector in vectors]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Authority, validation và apply accounting
    # ------------------------------------------------------------------

    def _protected_record_ids(self, records: Iterable[ProfileRecord]) -> set[str]:
        protected: set[str] = set()
        ledger = getattr(self.living_user, "authority_ledger", None)
        latest_rule = getattr(ledger, "latest_rule", None)
        for record in records:
            if any(str(eid).startswith("authority:") for eid in record.evidence_ids):
                protected.add(record.id)
                continue
            if record.source.startswith("user_authority") or record.source == "behavior_rule":
                protected.add(record.id)
                continue
            if callable(latest_rule):
                try:
                    event = latest_rule(record.path, record.scope)
                except Exception:
                    event = None
                if event is not None and getattr(event, "action", "") in {"correct", "confirm", "move_scope"}:
                    protected.add(record.id)
        return protected

    def _validate_operations(
        self,
        operations: Sequence[Mapping[str, Any]],
        *,
        records: Mapping[str, ProfileRecord],
        protected_ids: set[str],
        cluster_sets: Sequence[set[str]],
    ) -> list[dict[str, Any]]:
        safe: list[dict[str, Any]] = []
        touched: set[str] = set()
        for row in operations:
            action = str(row.get("action") or "").strip().lower()
            ids = [str(x) for x in row.get("record_ids", ()) if str(x) in records]
            ids = list(dict.fromkeys(ids))
            if action not in {"keep", "archive", "weaken", "merge", "rewrite", "hide"} or not ids:
                continue
            if any(record_id in protected_ids for record_id in ids):
                continue
            if any(record_id in touched for record_id in ids):
                continue
            reason = " ".join(str(row.get("reason") or "").split())[:260]
            if action in {"keep", "archive", "weaken"} and len(ids) != 1:
                continue
            if action == "keep":
                touched.update(ids)
                continue
            if action == "archive":
                record = records[ids[0]]
                # Không cho critic archive rule deterministic.
                if record.source == "behavior_rule":
                    continue
                safe.append({"action": "archive", "record_ids": ids, "reason": reason or "DeepSeek critic đề xuất archive."})
            elif action == "weaken":
                amount = min(0.30, max(0.05, _as_float(row.get("amount"), 0.12)))
                safe.append({"action": "weaken", "record_ids": ids, "amount": amount, "reason": reason or "Evidence chưa đủ mạnh."})
            elif action == "merge":
                if len(ids) < 2:
                    continue
                selected = [records[x] for x in ids]
                same_path = len({r.path for r in selected}) == 1
                same_scope = len({r.scope.identity for record in selected}) == 1
                same_value = len({value_fingerprint(r.value) for r in selected}) == 1
                clustered = any(set(ids).issubset(cluster) for cluster in cluster_sets)
                if not same_path or not same_scope or not (same_value or clustered):
                    continue
                safe.append({"action": "merge", "record_ids": ids, "reason": reason or "Các record trùng nghĩa trên cùng path/scope."})
            elif action == "rewrite":
                if len(ids) != 1:
                    continue
                value = row.get("value")
                if not value or not isinstance(value, str):
                    continue
                safe.append({"action": "rewrite", "record_ids": ids, "value": value[:1000], "reason": reason or "Sửa lỗi diễn đạt/Dịch sang tiếng Việt."})
            elif action == "hide":
                if len(ids) != 1:
                    continue
                safe.append({"action": "hide", "record_ids": ids, "reason": reason or "Ẩn khỏi UI vì không có giá trị đọc."})
            touched.update(ids)
        return safe

    @staticmethod
    def _accumulate_apply_result(result: LivingUserCuratorResult, applied: Any) -> None:
        details = dict(getattr(applied, "details", {}) or {})
        result.applied += int(details.get("applied", 0) or 0)
        result.archived += int(details.get("archived", 0) or 0)
        result.weakened += int(details.get("weakened", 0) or 0)
        result.merged += int(details.get("merged", 0) or 0)
        result.rewritten += int(details.get("rewritten", 0) or 0)
        result.hidden += int(details.get("hidden", 0) or 0)
        rejected = tuple(getattr(applied, "rejected", ()) or ())
        if rejected:
            result.notes.append(f"validator_rejected:{len(rejected)}")

    def _compact_history(self, store: Any) -> int:
        compact = getattr(store, "compact_history", None)
        if not callable(compact):
            return 0
        try:
            return int(compact(max_snapshots=self.config.history_snapshots) or 0)
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Prompt/JSON helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_records(records: Sequence[ProfileRecord], protected_ids: set[str]) -> str:
        rows: list[str] = []
        for record in records:
            payload = {
                "id": record.id,
                "path": record.path,
                "value": record.value,
                "status": record.status,
                "scope": record.scope.identity,
                "cardinality": record.cardinality,
                "confidence": round(record.confidence, 3),
                "explicitness": record.explicitness,
                "recurrence": record.recurrence,
                "source": record.source,
                "evidence_ids": list(record.evidence_ids[:12]),
                "updated_at": record.updated_at,
                "protected": record.id in protected_ids,
                "reason": str(record.metadata.get("reason") or "")[:240],
            }
            rows.append(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))
        return "\n".join(rows)

    @staticmethod
    def _format_clusters(clusters: Sequence[Sequence[str]], records: Sequence[ProfileRecord]) -> str:
        allowed = {r.id for r in records}
        rows = []
        for index, cluster in enumerate(clusters, start=1):
            ids = [record_id for record_id in cluster if record_id in allowed]
            if len(ids) >= 2:
                rows.append(f"cluster_{index}: {', '.join(ids)}")
        return "\n".join(rows) or "(none)"

    @staticmethod
    def _parse_operations(raw: str) -> list[dict[str, Any]]:
        text = str(raw or "").strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start < 0 or end <= start:
            return []
        try:
            payload = json.loads(text[start:end])
        except Exception:
            return []
        rows = payload.get("operations", []) if isinstance(payload, Mapping) else []
        return [dict(row) for row in rows if isinstance(row, Mapping)]


def _record_text(record: ProfileRecord) -> str:
    return f"{record.path}: {_value_text(record.value)}"


def _value_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split()).strip()
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value).strip()


def _contains_resolved_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _RESOLVED_MARKERS)


def _path_root(path: str) -> str:
    return str(path or "").split(".", 1)[0]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or len(left) != len(right):
        return -1.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left <= 1e-12 or norm_right <= 1e-12:
        return -1.0
    return dot / (norm_left * norm_right)


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except Exception:
        return int(default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except Exception:
        return float(default)


__all__ = [
    "LivingUserCuratorConfig",
    "LivingUserCuratorResult",
    "LivingUserMemoryCurator",
]
