import json
import os
import re
import time

from dataclasses import dataclass, field
from typing import Any

from cortex.internal_state import PersistentInternalState
'''
Working memory: những gì vừa xảy ra (tối đa 6 items)
Episodic memory: các sự kiện được nhớ rõ (tối đa 80 items)
Semantic memory: những sự thật ổn định, những gì người dùng yêu thích (tối đa 20 items)
Norm memory: những kiểu hành vi chuẩn để so sánh với hiện tại
'''

def _now_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def _compact_text(text: str, *, limit: int = 240) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) > limit:
        return compact[: limit - 3].rstrip() + "..."
    return compact


def _dedupe_key(text: str) -> str:
    lowered = str(text or "").strip().lower()
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered


@dataclass(slots=True)
class WorkingMemoryItem:
    timestamp: str # khi nào xảy ra, định dạng ISO 8601
    cycle_id: str # một ID để liên kết seen/said/outcome trong cùng một chu kỳ tương tác
    channel: str # từ đâu đến đâu, ví dụ "user->agent" hoặc "agent->user"
    summary: str #tóm tắt ngắn
    outcome: str = "" # kết quả
    salience: float = 0.0 # độ quan trọng

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "cycle_id": self.cycle_id,
            "channel": self.channel,
            "summary": self.summary,
            "outcome": self.outcome,
            "salience": round(float(self.salience), 3),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkingMemoryItem":
        return cls(
            timestamp=str(data.get("timestamp", "") or ""),
            cycle_id=str(data.get("cycle_id", "") or ""),
            channel=str(data.get("channel", "") or ""),
            summary=str(data.get("summary", "") or ""),
            outcome=str(data.get("outcome", "") or ""),
            salience=float(data.get("salience", 0.0) or 0.0),
        )


@dataclass(slots=True)
class EpisodicMemoryItem:
    timestamp: str
    cycle_id: str
    channel: str
    seen: tuple[str, ...] = ()
    said: str = ""
    outcome: str = ""
    tags: tuple[str, ...] = ()
    salience: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "cycle_id": self.cycle_id,
            "channel": self.channel,
            "seen": list(self.seen),
            "said": self.said,
            "outcome": self.outcome,
            "tags": list(self.tags),
            "salience": round(float(self.salience), 3),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EpisodicMemoryItem":
        return cls(
            timestamp=str(data.get("timestamp", "") or ""),
            cycle_id=str(data.get("cycle_id", "") or ""),
            channel=str(data.get("channel", "") or ""),
            seen=tuple(str(item) for item in (data.get("seen") or ()) if str(item or "").strip()),
            said=str(data.get("said", "") or ""),
            outcome=str(data.get("outcome", "") or ""),
            tags=tuple(str(item) for item in (data.get("tags") or ()) if str(item or "").strip()),
            salience=float(data.get("salience", 0.0) or 0.0),
        )

    def summary(self) -> str:
        seen_text = " | ".join(self.seen[:2])
        parts = [part for part in (seen_text, self.said, self.outcome) if part]
        return _compact_text(" -> ".join(parts), limit=260)


@dataclass(slots=True)
class SemanticMemoryItem:
    text: str
    source: str = "runtime"
    confidence: float = 0.75
    observations: int = 1
    first_seen_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "source": self.source,
            "confidence": round(float(self.confidence), 3),
            "observations": int(self.observations),
            "first_seen_at": self.first_seen_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SemanticMemoryItem":
        return cls(
            text=str(data.get("text", "") or ""),
            source=str(data.get("source", "") or "runtime"),
            confidence=float(data.get("confidence", 0.75) or 0.75),
            observations=int(data.get("observations", 1) or 1),
            first_seen_at=str(data.get("first_seen_at", "") or ""),
            updated_at=str(data.get("updated_at", "") or ""),
        )


@dataclass(slots=True)
class RelationshipMemoryItem:
    text: str
    pattern: str = "relationship_reflection"
    source: str = "runtime"
    confidence: float = 0.68
    observations: int = 1
    first_seen_at: str = ""
    updated_at: str = ""
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "pattern": self.pattern,
            "source": self.source,
            "confidence": round(float(self.confidence), 3),
            "observations": int(self.observations),
            "first_seen_at": self.first_seen_at,
            "updated_at": self.updated_at,
            "evidence": list(self.evidence),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RelationshipMemoryItem":
        return cls(
            text=str(data.get("text", "") or ""),
            pattern=str(data.get("pattern", "") or "relationship_reflection"),
            source=str(data.get("source", "") or "runtime"),
            confidence=float(data.get("confidence", 0.68) or 0.68),
            observations=int(data.get("observations", 1) or 1),
            first_seen_at=str(data.get("first_seen_at", "") or ""),
            updated_at=str(data.get("updated_at", "") or ""),
            evidence=tuple(str(item) for item in (data.get("evidence") or ()) if str(item or "").strip()),
        )


@dataclass(slots=True)
class NormMemory:
    observations: int = 0
    feature_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    last_seen_at: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observations": int(self.observations),
            "feature_counts": {
                str(feature): {str(value): int(count) for value, count in values.items()}
                for feature, values in self.feature_counts.items()
            },
            "last_seen_at": {str(key): str(value) for key, value in self.last_seen_at.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NormMemory":
        raw_counts = data.get("feature_counts") or {}
        feature_counts: dict[str, dict[str, int]] = {}
        if isinstance(raw_counts, dict):
            for feature, values in raw_counts.items():
                if not isinstance(values, dict):
                    continue
                feature_counts[str(feature)] = {
                    str(value): int(count)
                    for value, count in values.items()
                    if str(value or "").strip()
                }
        last_seen = data.get("last_seen_at") or {}
        if not isinstance(last_seen, dict):
            last_seen = {}
        return cls(
            observations=int(data.get("observations", 0) or 0),
            feature_counts=feature_counts,
            last_seen_at={str(key): str(value) for key, value in last_seen.items()},
        )

#Khi hiện tại khác so với chuẩn.
@dataclass(slots=True)
class NormDeviation:
    feature: str
    current: str
    baseline: str
    current_count: int
    baseline_count: int
    total: int
    score: float

    def to_event_text(self) -> str:
        return (
            f"{self.feature}={self.current} differs from norm "
            f"{self.baseline} ({self.current_count}/{self.total} vs {self.baseline_count}/{self.total})"
        )

    def to_prompt_line(self) -> str:
        return (
            f"{self.feature}: current={self.current}, baseline={self.baseline}, "
            f"deviation={self.score:.2f}"
        )


@dataclass(slots=True)
class MemoryState:
    version: int = 4
    working: list[WorkingMemoryItem] = field(default_factory=list)
    episodic: list[EpisodicMemoryItem] = field(default_factory=list)
    semantic: list[SemanticMemoryItem] = field(default_factory=list)
    relationship: list[RelationshipMemoryItem] = field(default_factory=list)
    norm: NormMemory = field(default_factory=NormMemory)
    internal_state: PersistentInternalState = field(default_factory=PersistentInternalState)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "working": [item.to_dict() for item in self.working],
            "episodic": [item.to_dict() for item in self.episodic],
            "semantic": [item.to_dict() for item in self.semantic],
            "relationship": [item.to_dict() for item in self.relationship],
            "norm": self.norm.to_dict(),
            "internal_state": self.internal_state.to_dict(),
        }


class MemoryStore:
    def __init__(
        self,
        path: str,
        max_items: int = 20,
        *,
        max_working_items: int = 6,
        max_episodic_items: int = 80,
        max_semantic_items: int | None = None,
        max_relationship_items: int = 16,
        max_norm_values_per_feature: int = 12,
    ):
        self.path = path
        self.max_items = max_items
        self.max_working_items = max_working_items
        self.max_episodic_items = max_episodic_items
        self.max_semantic_items = max_semantic_items or max_items
        self.max_relationship_items = max_relationship_items
        self.max_norm_values_per_feature = max_norm_values_per_feature

    def load(self) -> list[str]:
        return [item.text for item in self.load_state().semantic if item.text]

    def load_state(self) -> MemoryState:
        if not os.path.isfile(self.path) or os.path.getsize(self.path) <= 0:
            return MemoryState()
        with open(self.path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return self._state_from_json(data)

    def save(self, items: list[str]) -> None:
        state = MemoryState()
        now = _now_timestamp()
        for item in items or []:
            fact = _compact_text(str(item or ""), limit=220)
            if not fact:
                continue
            state.semantic.append(
                SemanticMemoryItem(
                    text=fact,
                    source="legacy_save",
                    first_seen_at=now,
                    updated_at=now,
                )
            )
        self.save_state(state)

    def save_state(self, state: MemoryState) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(state.to_dict(), handle, ensure_ascii=False, indent=4)

    def append_fact(self, current_items: list[str], fact: str) -> list[str]:
        state = self.load_state()
        state = self.remember_semantic_fact(state, fact, source="decision_extracted_fact")
        self.save_state(state)
        return self.recall_texts(state)

    def remember_semantic_fact(
        #Thêm hoặc cập nhật một sự thật.
        self,
        state: MemoryState,
        fact: str,
        *,
        source: str = "runtime",
        confidence: float = 0.75,
        timestamp: str | None = None,
    ) -> MemoryState:
        text = _compact_text(fact, limit=220)
        if not text:
            return state

        now = timestamp or _now_timestamp()
        key = _dedupe_key(text)
        for item in state.semantic:
            if _dedupe_key(item.text) == key:
                item.observations += 1
                item.confidence = min(0.98, max(float(item.confidence), confidence) + 0.02)
                item.updated_at = now
                return state

        state.semantic.append(
            SemanticMemoryItem(
                text=text,
                source=source,
                confidence=confidence,
                observations=1,
                first_seen_at=now,
                updated_at=now,
            )
        )
        state.semantic = state.semantic[-self.max_semantic_items :]
        return state

    # Ghi nhận một chu kỳ hoàn chỉnh: người dùng thấy cái gì, ERIS nói gì, kết quả thế nào.
    def remember_relationship_reflection(
        self,
        state: MemoryState,
        reflection: str,
        *,
        pattern: str = "relationship_reflection",
        source: str = "runtime_reflection",
        confidence: float = 0.68,
        timestamp: str | None = None,
        evidence: tuple[str, ...] = (),
    ) -> MemoryState:
        text = _compact_text(reflection, limit=240)
        if not text:
            return state

        now = timestamp or _now_timestamp()
        key = _dedupe_key(text)
        clean_evidence = tuple(
            dict.fromkeys(
                _compact_text(item, limit=120)
                for item in (evidence or ())
                if _compact_text(item, limit=120)
            )
        )[:4]
        for item in state.relationship:
            if _dedupe_key(item.text) == key:
                item.observations += 1
                item.confidence = min(0.98, max(float(item.confidence), confidence) + 0.03)
                item.updated_at = now
                if clean_evidence:
                    item.evidence = tuple(dict.fromkeys((*item.evidence, *clean_evidence)))[-4:]
                return state

        state.relationship.append(
            RelationshipMemoryItem(
                text=text,
                pattern=_compact_text(pattern, limit=80) or "relationship_reflection",
                source=source,
                confidence=confidence,
                observations=1,
                first_seen_at=now,
                updated_at=now,
                evidence=clean_evidence,
            )
        )
        state.relationship = state.relationship[-self.max_relationship_items :]
        return state

    def remember_cycle(
        self,
        state: MemoryState,
        *,
        cycle_id: str,
        channel: str,
        timestamp: str,
        seen: tuple[str, ...] = (),
        said: str = "",
        outcome: str = "",
        salience: float = 0.0,
        tags: tuple[str, ...] = (),
        semantic_fact: str = "",
        system_action: str = "",
    ) -> MemoryState:
        clean_seen = tuple(
            dict.fromkeys(
                _compact_text(item, limit=160)
                for item in (seen or ())
                if _compact_text(item, limit=160)
            )
        )[:4]
        clean_said = _compact_text(said, limit=180)
        clean_outcome = _compact_text(outcome, limit=120)
        clean_tags = tuple(dict.fromkeys(str(tag) for tag in (tags or ()) if str(tag or "").strip()))[:6]

        summary_parts = [part for part in (channel, " | ".join(clean_seen[:2]), clean_said, clean_outcome) if part]
        state.working.append(
            WorkingMemoryItem(
                timestamp=timestamp or _now_timestamp(),
                cycle_id=cycle_id,
                channel=channel,
                summary=_compact_text(" -> ".join(summary_parts), limit=260),
                outcome=clean_outcome,
                salience=salience,
            )
        )
        state.working = state.working[-self.max_working_items :]

        should_keep_episode = bool(clean_said or clean_seen or semantic_fact or system_action or salience >= 0.5)
        if should_keep_episode:
            episode_tags = clean_tags
            if system_action:
                episode_tags = (*episode_tags, f"action:{system_action}")
            state.episodic.append(
                EpisodicMemoryItem(
                    timestamp=timestamp or _now_timestamp(),
                    cycle_id=cycle_id,
                    channel=channel,
                    seen=clean_seen,
                    said=clean_said,
                    outcome=clean_outcome,
                    tags=episode_tags,
                    salience=salience,
                )
            )
            state.episodic = state.episodic[-self.max_episodic_items :]

        if semantic_fact:
            state = self.remember_semantic_fact(
                state,
                semantic_fact,
                source="decision_extracted_fact",
                timestamp=timestamp,
            )
        return state

    #Ghi nhận snapshot hiện tại để xây dựng chuẩn.
    def update_norms(
        self,
        state: MemoryState,
        snapshot,
        *,
        timestamp: str | None = None,
    ) -> MemoryState:
        features = self._snapshot_features(snapshot)
        if not features:
            return state

        now = timestamp or _now_timestamp()
        state.norm.observations += 1
        for feature, value in features.items():
            values = state.norm.feature_counts.setdefault(feature, {})
            values[value] = int(values.get(value, 0)) + 1
            state.norm.last_seen_at[f"{feature}:{value}"] = now
            state.norm.feature_counts[feature] = self._trim_feature_counts(values)
        return state

    #So sánh snapshot hiện tại với chuẩn, trả về những điều bất thường.
    def compare_to_norms(
        self,
        state: MemoryState,
        snapshot,
        *,
        min_observations: int = 4, #Cần tối thiểu 4 quan sát
        max_items: int = 3, # Baseline quá hiếm (< 3 lần hoặc < 34%): bỏ qua
    ) -> tuple[NormDeviation, ...]:
        total = int(state.norm.observations or 0)
        if total < min_observations:
            return ()

        deviations: list[NormDeviation] = []
        current_features = self._snapshot_features(snapshot)
        for feature, current in current_features.items():
            counts = state.norm.feature_counts.get(feature) or {}
            if not counts:
                continue
            baseline, baseline_count = max(counts.items(), key=lambda item: item[1])
            current_count = int(counts.get(current, 0))
            baseline_ratio = baseline_count / max(1, total)
            current_ratio = current_count / max(1, total)
            if current == baseline:
                continue
            if baseline_count < 3 or baseline_ratio < 0.34:
                continue
            if current_count > max(1, int(total * 0.18)):
                continue
            score = max(0.0, min(1.0, baseline_ratio - current_ratio))
            if score <= 0.18:
                continue
            deviations.append(
                NormDeviation(
                    feature=feature,
                    current=current,
                    baseline=baseline,
                    current_count=current_count,
                    baseline_count=baseline_count,
                    total=total,
                    score=score,
                )
            )

        deviations.sort(key=lambda item: item.score, reverse=True)
        return tuple(deviations[:max_items])

    def recall_texts(
        self,
        state: MemoryState,
        *,
        snapshot=None,
        max_items: int | None = None,
    ) -> list[str]:
        limit = max_items or self.max_items
        recalled: list[str] = []

        for item in state.semantic[-8:]:
            if item.text:
                recalled.append(f"semantic/user: {item.text}")

        for item in state.relationship[-6:]:
            if item.text:
                recalled.append(f"relationship/{item.pattern}: {item.text}")

        for item in state.episodic[-5:]:
            summary = item.summary()
            if summary:
                recalled.append(f"episodic: {summary}")

        for item in state.working[-3:]:
            if item.summary:
                recalled.append(f"working: {item.summary}")

        norm_line = self._render_norm_baseline_line(state)
        if norm_line:
            recalled.append(f"norm: {norm_line}")
        for deviation in self.compare_to_norms(state, snapshot) if snapshot is not None else ():
            recalled.append(f"norm_deviation: {deviation.to_event_text()}")

        return recalled[-limit:]

    def render_context(self, state: MemoryState, *, snapshot=None) -> str:
        sections: list[str] = []

        working = [item.summary for item in state.working[-4:] if item.summary]
        if working:
            sections.append("working_memory:\n" + "\n".join(f"- {item}" for item in working))

        episodes = [item.summary() for item in state.episodic[-4:] if item.summary()]
        if episodes:
            sections.append("episodic_memory:\n" + "\n".join(f"- {item}" for item in episodes))

        semantic = [item.text for item in state.semantic[-6:] if item.text]
        if semantic:
            sections.append("semantic_user_memory:\n" + "\n".join(f"- {item}" for item in semantic))

        relationship = [item for item in state.relationship[-6:] if item.text]
        if relationship:
            sections.append(
                "relationship_memory:\n"
                + "\n".join(
                    f"- {item.text} (pattern={item.pattern}, observations={item.observations})"
                    for item in relationship
                )
            )

        norm_lines: list[str] = []
        baseline = self._render_norm_baseline_line(state)
        if baseline:
            norm_lines.append(f"- baseline: {baseline}")
        if snapshot is not None:
            deviations = self.compare_to_norms(state, snapshot)
            for deviation in deviations:
                norm_lines.append(f"- deviation: {deviation.to_prompt_line()}")
        if norm_lines:
            sections.append("norm_memory:\n" + "\n".join(norm_lines))

        if not sections:
            return ""
        return (
            "Memory is split by type. Working memory is only recent cycles; episodic memory is what was seen/said/outcome; "
            "semantic_user_memory is stable facts/preferences; relationship_memory is ERIS' reflected interaction rhythm with the user, not current screen evidence; "
            "norm_memory is the user's baseline for comparing the current scene.\n"
            + "\n\n".join(sections)
        )

    def _state_from_json(self, data: Any) -> MemoryState:
        if isinstance(data, list):
            state = MemoryState()
            now = _now_timestamp()
            seen: set[str] = set()
            for item in data:
                text = _compact_text(str(item or ""), limit=220)
                key = _dedupe_key(text)
                if not text or key in seen:
                    continue
                seen.add(key)
                state.semantic.append(
                    SemanticMemoryItem(
                        text=text,
                        source="legacy_long_term_memory",
                        first_seen_at=now,
                        updated_at=now,
                    )
                )
            state.semantic = state.semantic[-self.max_semantic_items :]
            return state

        if not isinstance(data, dict):
            return MemoryState()

        working = [
            WorkingMemoryItem.from_dict(item)
            for item in (data.get("working") or [])
            if isinstance(item, dict)
        ]
        episodic = [
            EpisodicMemoryItem.from_dict(item)
            for item in (data.get("episodic") or [])
            if isinstance(item, dict)
        ]
        semantic = [
            SemanticMemoryItem.from_dict(item)
            for item in (data.get("semantic") or [])
            if isinstance(item, dict)
        ]
        relationship = [
            RelationshipMemoryItem.from_dict(item)
            for item in (data.get("relationship") or data.get("reflections") or [])
            if isinstance(item, dict)
        ]
        norm = NormMemory.from_dict(data.get("norm") or {})
        internal_state = PersistentInternalState.from_dict(data.get("internal_state") or {})
        return MemoryState(
            version=max(4, int(data.get("version", 2) or 2)),
            working=working[-self.max_working_items :],
            episodic=episodic[-self.max_episodic_items :],
            semantic=semantic[-self.max_semantic_items :],
            relationship=relationship[-self.max_relationship_items :],
            norm=norm,
            internal_state=internal_state,
        )

    def _snapshot_features(self, snapshot) -> dict[str, str]:
        if snapshot is None:
            return {}

        user_signals = getattr(snapshot, "user_signals", None)
        focus_pattern = str(getattr(user_signals, "focus_pattern", "") or "").strip()
        active_app = str(getattr(snapshot, "active_app", "") or getattr(snapshot, "active_window", "") or "").strip()
        active_app = self._normalize_app_name(active_app)
        features = {
            "active_window_kind": str(getattr(snapshot, "active_window_kind", "") or "unknown").strip() or "unknown",
            "active_app": active_app or "unknown",
            "focus_summary": _compact_text(str(getattr(snapshot, "focus_summary", "") or "unknown"), limit=80),
            "idle_bucket": self._bucket_idle_seconds(float(getattr(snapshot, "idle_seconds", 0.0) or 0.0)),
            "window_spread": self._bucket_window_spread(
                getattr(snapshot, "open_windows", ()) or (),
                getattr(snapshot, "browser_tabs", ()) or (),
            ),
        }
        if focus_pattern:
            features["focus_pattern"] = focus_pattern
        return {key: value for key, value in features.items() if value}

    def _trim_feature_counts(self, values: dict[str, int]) -> dict[str, int]:
        kept = sorted(values.items(), key=lambda item: item[1], reverse=True)[: self.max_norm_values_per_feature]
        return {key: int(value) for key, value in kept}

    def _render_norm_baseline_line(self, state: MemoryState) -> str:
        total = int(state.norm.observations or 0)
        if total <= 0:
            return ""

        parts: list[str] = []
        for feature in ("active_window_kind", "active_app", "focus_summary", "idle_bucket", "window_spread", "focus_pattern"):
            counts = state.norm.feature_counts.get(feature) or {}
            if not counts:
                continue
            value, count = max(counts.items(), key=lambda item: item[1])
            ratio = count / max(1, total)
            if count >= 2:
                parts.append(f"{feature} usually {value} ({ratio:.0%})")
        if not parts:
            return ""
        return "; ".join(parts[:4])

    def _normalize_app_name(self, title: str) -> str:
        text = _compact_text(title, limit=120).lower()
        if not text:
            return ""
        known = (
            "visual studio code",
            "godot",
            "brave",
            "chrome",
            "edge",
            "zalo",
            "discord",
            "spotify",
            "youtube",
            "task manager",
            "terminal",
            "powershell",
        )
        for name in known:
            if name in text:
                return name
        cleaned = re.split(r"\s[-|]\s", text, maxsplit=1)[-1]
        return _compact_text(cleaned or text, limit=64)

    def _bucket_idle_seconds(self, idle_seconds: float) -> str:
        if idle_seconds >= 720:
            return "very_long_idle"
        if idle_seconds >= 300:
            return "long_idle"
        if idle_seconds >= 90:
            return "medium_idle"
        if idle_seconds >= 15:
            return "short_idle"
        return "active"

    def _bucket_window_spread(self, open_windows: tuple[str, ...], browser_tabs: tuple[str, ...]) -> str:
        spread = max(len(open_windows or ()), len(browser_tabs or ()))
        if spread >= 10:
            return "very_high"
        if spread >= 7:
            return "high"
        if spread >= 4:
            return "medium"
        if spread >= 2:
            return "low"
        return "single"
