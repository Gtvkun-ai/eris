"""State primitives for the coordinator-centric runtime.

V105 tách state ra khỏi runtime để Main không còn là một vòng lặp vô danh sống
chỉ trong một HTTP request. ``CoordinatorMemory`` có thể được serialize vào
``Session.metadata`` và nạp lại ở turn sau. Raw file contents không bị nhét hết
vào session; chỉ evidence digest / repo model được giữ lâu dài, còn chi tiết có
thể được Main đọc lại khi cần xác minh.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


@dataclass
class Evidence:
    """Một mẩu bằng chứng dùng để ground claim của Main."""

    id: str
    kind: str
    source: str
    summary: str
    detail: str = ""
    revision: str = ""
    created_at: float = field(default_factory=time.time)
    persistent: bool = False

    def prompt_line(self, *, max_detail: int = 2600) -> str:
        detail = self.detail
        if len(detail) > max_detail:
            detail = detail[:max_detail] + "\n…[truncated in prompt; source remains available]"
        freshness = "persistent" if self.persistent else "current-turn"
        revision = self.revision or "unknown"
        return (
            f"[{self.id}] {self.kind} {self.source} ({freshness}, rev={revision})\n"
            f"Summary: {self.summary}\n"
            f"Detail:\n{detail}"
        )

    def digest(self, *, detail_chars: int = 1200) -> dict[str, Any]:
        """Bản nhẹ để lưu session lâu dài, không copy toàn bộ source file."""
        return {
            "id": self.id,
            "kind": self.kind,
            "source": self.source,
            "summary": self.summary,
            "detail": self.detail[:detail_chars],
            "revision": self.revision,
            "created_at": self.created_at,
        }

    @classmethod
    def from_digest(cls, raw: dict[str, Any]) -> "Evidence":
        return cls(
            id=str(raw.get("id") or ""),
            kind=str(raw.get("kind") or "memory"),
            source=str(raw.get("source") or "memory"),
            summary=str(raw.get("summary") or ""),
            detail=str(raw.get("detail") or ""),
            revision=str(raw.get("revision") or ""),
            created_at=float(raw.get("created_at") or time.time()),
            persistent=True,
        )


@dataclass
class ClaimRecord:
    """Claim đã được specialist/Main hình thành và evidence đỡ phía sau."""

    id: str
    statement: str
    confidence: float = 0.0
    evidence_ids: list[str] = field(default_factory=list)
    status: str = "working"  # working | supported | rejected | stale
    source: str = "main"
    updated_at: float = field(default_factory=time.time)


@dataclass
class Frontier:
    """Một biên điều tra chưa khép lại trong repo graph."""

    id: str
    topic: str
    source: str = "main"
    status: str = "open"  # open | active | resolved | abandoned
    priority: float = 0.5
    evidence_ids: list[str] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)


@dataclass
class InvestigationGraph:
    """Repo-understanding graph nhỏ gọn, persistent qua nhiều user turn."""

    claims: dict[str, ClaimRecord] = field(default_factory=dict)
    frontiers: dict[str, Frontier] = field(default_factory=dict)
    _claim_seq: int = 0
    _frontier_seq: int = 0

    def add_claim(
        self,
        statement: str,
        *,
        confidence: float = 0.0,
        evidence_ids: Iterable[str] = (),
        status: str = "working",
        source: str = "main",
    ) -> ClaimRecord:
        statement = statement.strip()
        refs = list(dict.fromkeys(str(x) for x in evidence_ids if str(x)))
        # Main/subagents có thể cùng rediscover một fact. Merge theo statement
        # thay vì làm graph phình ra chỉ vì cùng claim được nhắc lại nhiều turn.
        for item in self.claims.values():
            if item.statement.casefold() == statement.casefold():
                item.confidence = max(item.confidence, max(0.0, min(1.0, float(confidence))))
                item.evidence_ids = list(dict.fromkeys([*item.evidence_ids, *refs]))
                if status == "supported" or item.status in {"stale", "working"}:
                    item.status = status
                item.source = source or item.source
                item.updated_at = time.time()
                return item
        self._claim_seq += 1
        item = ClaimRecord(
            id=f"c{self._claim_seq}",
            statement=statement,
            confidence=max(0.0, min(1.0, float(confidence))),
            evidence_ids=refs,
            status=status,
            source=source,
        )
        self.claims[item.id] = item
        return item

    def add_frontier(
        self,
        topic: str,
        *,
        source: str = "main",
        priority: float = 0.5,
        evidence_ids: Iterable[str] = (),
    ) -> Frontier:
        topic = topic.strip()
        if not topic:
            raise ValueError("frontier topic must not be empty")
        # Tránh nhân đôi cùng một frontier chỉ vì nhiều specialist cùng chỉ tới nó.
        for item in self.frontiers.values():
            if item.topic.casefold() == topic.casefold() and item.status in {"open", "active"}:
                item.priority = max(item.priority, float(priority))
                item.evidence_ids = list(dict.fromkeys([*item.evidence_ids, *[str(x) for x in evidence_ids]]))
                item.updated_at = time.time()
                return item
        self._frontier_seq += 1
        item = Frontier(
            id=f"f{self._frontier_seq}",
            topic=topic,
            source=source,
            priority=max(0.0, min(1.0, float(priority))),
            evidence_ids=list(dict.fromkeys(str(x) for x in evidence_ids if str(x))),
        )
        self.frontiers[item.id] = item
        return item

    def mark_frontier(self, frontier_id: str, status: str) -> None:
        item = self.frontiers.get(frontier_id)
        if item is not None:
            item.status = status
            item.updated_at = time.time()

    def stale_claims(self) -> None:
        for claim in self.claims.values():
            if claim.status == "supported":
                claim.status = "stale"
                claim.updated_at = time.time()

    def prompt_text(self) -> str:
        claim_lines = [
            f"- {c.id} [{c.status}] conf={c.confidence:.2f}: {c.statement} evidence={c.evidence_ids}"
            for c in self.claims.values()
        ]
        frontier_lines = [
            f"- {f.id} [{f.status}] p={f.priority:.2f}: {f.topic} evidence={f.evidence_ids}"
            for f in sorted(self.frontiers.values(), key=lambda x: x.priority, reverse=True)
        ]
        return (
            "INVESTIGATION CLAIMS:\n" + ("\n".join(claim_lines) or "(none)")
            + "\n\nOPEN/KNOWN FRONTIERS:\n" + ("\n".join(frontier_lines) or "(none)")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims": {k: asdict(v) for k, v in self.claims.items()},
            "frontiers": {k: asdict(v) for k, v in self.frontiers.items()},
            "claim_seq": self._claim_seq,
            "frontier_seq": self._frontier_seq,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "InvestigationGraph":
        raw = raw or {}
        graph = cls()
        for key, value in (raw.get("claims") or {}).items():
            if isinstance(value, dict):
                graph.claims[str(key)] = ClaimRecord(**value)
        for key, value in (raw.get("frontiers") or {}).items():
            if isinstance(value, dict):
                graph.frontiers[str(key)] = Frontier(**value)
        graph._claim_seq = int(raw.get("claim_seq") or len(graph.claims))
        graph._frontier_seq = int(raw.get("frontier_seq") or len(graph.frontiers))
        return graph


@dataclass
class CoordinatorMemory:
    """State lâu dài của Main, serializable vào session và workspace store."""

    schema_version: int = 2
    updated_at: float = field(default_factory=time.time)
    next_evidence_seq: int = 0
    workspace_signature: str = ""
    workspace_map: dict[str, Any] = field(default_factory=dict)
    evidence_digest: list[dict[str, Any]] = field(default_factory=list)
    graph: InvestigationGraph = field(default_factory=InvestigationGraph)
    turn_summaries: list[dict[str, Any]] = field(default_factory=list)

    def touch(self) -> None:
        self.updated_at = time.time()

    def allocate_evidence_id(self) -> str:
        self.next_evidence_seq += 1
        self.touch()
        return f"e{self.next_evidence_seq}"

    def remember_evidence(self, item: Evidence) -> None:
        # Replace theo id để cùng evidence không bị append lại mỗi lần export.
        for idx, existing in enumerate(self.evidence_digest):
            if existing.get("id") == item.id:
                self.evidence_digest[idx] = item.digest()
                self.touch()
                return
        self.evidence_digest.append(item.digest())
        self.touch()

    def remember_turn(self, goal: str, answer: str, grounded_in: list[str]) -> None:
        self.turn_summaries.append({
            "goal": goal[:1200],
            "answer": answer[:2400],
            "grounded_in": list(grounded_in),
            "revision": self.workspace_signature,
            "ts": time.time(),
        })
        self.touch()


    def copy(self) -> "CoordinatorMemory":
        """Deep-enough copy through the stable serialized form."""
        return CoordinatorMemory.from_dict(self.to_dict())

    @staticmethod
    def _evidence_fingerprint(raw: dict[str, Any]) -> str:
        payload = {
            "kind": str(raw.get("kind") or ""),
            "source": str(raw.get("source") or ""),
            "summary": str(raw.get("summary") or ""),
            "detail": str(raw.get("detail") or ""),
            "revision": str(raw.get("revision") or ""),
        }
        return stable_json(payload)

    def merge_from(self, other: "CoordinatorMemory") -> None:
        """Merge another session/workspace memory without losing evidence refs.

        Evidence ids were historically sequential (e1, e2, ...), so two chat
        sessions can legitimately create the same id for different evidence.
        Conflicts are re-numbered and claim/frontier references are remapped.
        """
        self_updated_before = self.updated_at
        other_updated = other.updated_at
        existing_by_fp = {self._evidence_fingerprint(x): str(x.get("id") or "") for x in self.evidence_digest}
        used_ids = {str(x.get("id") or "") for x in self.evidence_digest}
        id_map: dict[str, str] = {}

        for raw in other.evidence_digest:
            if not isinstance(raw, dict):
                continue
            incoming_id = str(raw.get("id") or "")
            fp = self._evidence_fingerprint(raw)
            if fp in existing_by_fp:
                id_map[incoming_id] = existing_by_fp[fp]
                continue
            target_id = incoming_id
            if not target_id or target_id in used_ids:
                target_id = self.allocate_evidence_id()
            elif target_id.startswith("e") and target_id[1:].isdigit():
                self.next_evidence_seq = max(self.next_evidence_seq, int(target_id[1:]))
            copied = dict(raw)
            copied["id"] = target_id
            self.evidence_digest.append(copied)
            used_ids.add(target_id)
            existing_by_fp[fp] = target_id
            id_map[incoming_id] = target_id

        for claim in other.graph.claims.values():
            refs = [id_map.get(x, x) for x in claim.evidence_ids]
            previous = next(
                (x for x in self.graph.claims.values() if x.statement.casefold() == claim.statement.casefold()),
                None,
            )
            previous_updated = getattr(previous, "updated_at", 0.0) if previous is not None else 0.0
            merged = self.graph.add_claim(
                claim.statement,
                confidence=claim.confidence,
                evidence_ids=refs,
                status=claim.status,
                source=claim.source,
            )
            if getattr(claim, "updated_at", 0.0) >= previous_updated:
                merged.status = claim.status
                merged.source = claim.source
                merged.updated_at = getattr(claim, "updated_at", merged.updated_at)

        for frontier in other.graph.frontiers.values():
            refs = [id_map.get(x, x) for x in frontier.evidence_ids]
            previous = next(
                (x for x in self.graph.frontiers.values() if x.topic.casefold() == frontier.topic.casefold()),
                None,
            )
            previous_updated = getattr(previous, "updated_at", 0.0) if previous is not None else 0.0
            merged = self.graph.add_frontier(
                frontier.topic,
                source=frontier.source,
                priority=frontier.priority,
                evidence_ids=refs,
            )
            # Preserve terminal state when the incoming copy is newer than the
            # version that existed before add_frontier touched its timestamp.
            if getattr(frontier, "updated_at", 0.0) >= previous_updated:
                merged.status = frontier.status
                merged.updated_at = getattr(frontier, "updated_at", merged.updated_at)

        seen_turns = {
            (str(x.get("goal") or ""), str(x.get("answer") or ""), float(x.get("ts") or 0.0))
            for x in self.turn_summaries if isinstance(x, dict)
        }
        for turn in other.turn_summaries:
            if not isinstance(turn, dict):
                continue
            key = (str(turn.get("goal") or ""), str(turn.get("answer") or ""), float(turn.get("ts") or 0.0))
            if key not in seen_turns:
                self.turn_summaries.append(dict(turn))
                seen_turns.add(key)

        if other_updated >= self_updated_before:
            if other.workspace_signature:
                self.workspace_signature = other.workspace_signature
            if other.workspace_map:
                self.workspace_map = dict(other.workspace_map)
        elif not self.workspace_map and other.workspace_map:
            self.workspace_map = dict(other.workspace_map)

        self.updated_at = max(self.updated_at, other_updated, time.time())

    def compact(
        self,
        *,
        max_evidence: int = 640,
        max_turns: int = 80,
        max_claims: int = 240,
        max_frontiers: int = 160,
    ) -> None:
        """Bound disk growth without throwing away the current knowledge frontier."""
        def _newest(records: dict[str, Any], limit: int, preferred: set[str]) -> dict[str, Any]:
            values = list(records.values())
            values.sort(
                key=lambda x: (
                    1 if getattr(x, "status", "") in preferred else 0,
                    float(getattr(x, "priority", 0.0)),
                    float(getattr(x, "updated_at", 0.0)),
                ),
                reverse=True,
            )
            return {x.id: x for x in values[:limit]}

        # Bound graph first. Open/working knowledge wins, then recently refreshed
        # supported/stale material. Resolved historical clutter naturally ages out.
        self.graph.claims = _newest(
            self.graph.claims, max_claims, {"working", "supported"}
        )
        self.graph.frontiers = _newest(
            self.graph.frontiers, max_frontiers, {"open", "active"}
        )

        protected: set[str] = set()
        for claim in self.graph.claims.values():
            if claim.status != "rejected":
                protected.update(claim.evidence_ids)
        for frontier in self.graph.frontiers.values():
            if frontier.status in {"open", "active"}:
                protected.update(frontier.evidence_ids)

        by_newest = sorted(
            [x for x in self.evidence_digest if isinstance(x, dict)],
            key=lambda x: float(x.get("created_at") or 0.0),
            reverse=True,
        )
        # Referenced evidence is a soft-cap exception: dropping it would leave a
        # durable claim with dangling grounding. Unreferenced evidence obeys quota.
        newest_budget = max(0, max_evidence - len(protected))
        newest_unprotected = [
            str(x.get("id") or "") for x in by_newest
            if str(x.get("id") or "") not in protected
        ][:newest_budget]
        keep_ids = protected | set(newest_unprotected)
        self.evidence_digest = [
            x for x in self.evidence_digest
            if str(x.get("id") or "") in keep_ids
        ]

        self.turn_summaries = sorted(
            [x for x in self.turn_summaries if isinstance(x, dict)],
            key=lambda x: float(x.get("ts") or 0.0),
        )[-max_turns:]
        self.touch()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "next_evidence_seq": self.next_evidence_seq,
            "workspace_signature": self.workspace_signature,
            "workspace_map": self.workspace_map,
            "evidence_digest": self.evidence_digest,
            "graph": self.graph.to_dict(),
            "turn_summaries": self.turn_summaries,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "CoordinatorMemory":
        if not isinstance(raw, dict):
            return cls()
        memory = cls(
            schema_version=max(2, int(raw.get("schema_version") or 1)),
            updated_at=float(raw.get("updated_at") or 0.0),
            next_evidence_seq=int(raw.get("next_evidence_seq") or 0),
            workspace_signature=str(raw.get("workspace_signature") or ""),
            workspace_map=dict(raw.get("workspace_map") or {}),
            evidence_digest=[x for x in (raw.get("evidence_digest") or []) if isinstance(x, dict)],
            graph=InvestigationGraph.from_dict(raw.get("graph")),
            turn_summaries=[x for x in (raw.get("turn_summaries") or []) if isinstance(x, dict)],
        )
        # Migration an toàn nếu sequence cũ thấp hơn ids đang tồn tại.
        for item in memory.evidence_digest:
            raw_id = str(item.get("id") or "")
            if raw_id.startswith("e") and raw_id[1:].isdigit():
                memory.next_evidence_seq = max(memory.next_evidence_seq, int(raw_id[1:]))
        return memory


@dataclass
class ResearchJob:
    goal: str
    hint_paths: list[str] = field(default_factory=list)
    search_terms: list[str] = field(default_factory=list)
    label: str = "research"
    priority: float = 0.5


@dataclass
class ResearchReport:
    job_id: str
    label: str
    summary: str
    claims: list[dict[str, Any]] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    new_frontiers: list[str] = field(default_factory=list)
    files_read: list[str] = field(default_factory=list)


@dataclass
class CoordinatorState:
    """State của một request, nhưng dùng chung ``CoordinatorMemory`` lâu dài."""

    goal: str
    memory: CoordinatorMemory
    conversation_messages: list[dict[str, str]] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    reports: list[ResearchReport] = field(default_factory=list)
    active_research: dict[str, str] = field(default_factory=dict)
    visited_files: set[str] = field(default_factory=set)
    searches: set[tuple[str, str]] = field(default_factory=set)
    turn: int = 0
    started_at: float = field(default_factory=time.monotonic)
    workspace_revision: str = ""
    prior_revision_matches: bool = False

    def __post_init__(self) -> None:
        # Nạp digest cũ để Main nhớ những gì đã biết. Đây không phải raw source;
        # khi revision thay đổi, claim cũ bị đánh dấu stale và phải refresh.
        self.evidence.extend(Evidence.from_digest(x) for x in self.memory.evidence_digest)

    def add_evidence(self, kind: str, source: str, summary: str, detail: str = "") -> Evidence:
        item = Evidence(
            id=self.memory.allocate_evidence_id(),
            kind=kind,
            source=source,
            summary=summary,
            detail=detail,
            revision=self.workspace_revision,
            persistent=False,
        )
        self.evidence.append(item)
        self.memory.remember_evidence(item)
        return item

    def evidence_ids(self, *, valid_for_repo_claim: bool = False) -> set[str]:
        if not valid_for_repo_claim:
            return {e.id for e in self.evidence}
        # Generic metadata (status/map/delegation/guards) proves that a workspace
        # exists, not a detailed implementation claim. Final repo conclusions
        # need content-bearing evidence such as source reads/searches/diffs/tests.
        content_kinds = {
            "file", "search", "git_diff", "command", "write", "delete",
            "subagent_file", "subagent_search", "subagent_git_diff",
            "subagent_report",
        }
        valid: set[str] = set()
        for item in self.evidence:
            if item.kind not in content_kinds:
                continue
            if not item.persistent:
                valid.add(item.id)
            elif self.prior_revision_matches and item.revision == self.workspace_revision:
                valid.add(item.id)
        return valid

    def compact_prompt(self, max_chars: int) -> str:
        header = [
            f"USER GOAL:\n{self.goal}",
            f"COORDINATOR TURN: {self.turn}",
            f"WORKSPACE REVISION: {self.workspace_revision or 'unknown'}",
            f"PRIOR MEMORY REVISION MATCHES: {self.prior_revision_matches}",
            f"EVIDENCE COUNT: {len(self.evidence)}",
            f"SUBAGENT REPORTS THIS REQUEST: {len(self.reports)}",
            f"ACTIVE BACKGROUND RESEARCH: {self.active_research or 'none'}",
            self.memory.graph.prompt_text(),
        ]

        if self.memory.turn_summaries:
            history = [
                "WORKSPACE LONG-TERM HISTORY (orientation only; prior assistant answers are not source evidence):"
            ]
            chars = 0
            for turn in reversed(self.memory.turn_summaries):
                goal = str(turn.get("goal") or "")[:700]
                answer = str(turn.get("answer") or "")[:900]
                revision = str(turn.get("revision") or "unknown")
                line = f"- rev={revision} | user: {goal} | Main: {answer}"
                if len(history) > 1 and chars + len(line) > max_chars // 6:
                    break
                history.append(line)
                chars += len(line)
            header.append("\n".join([history[0], *reversed(history[1:])]))

        if self.conversation_messages:
            history = ["RECENT SESSION CONVERSATION:"]
            chars = 0
            for msg in reversed(self.conversation_messages):
                line = f"{msg.get('role','?')}: {str(msg.get('content',''))[:4000]}"
                if history and chars + len(line) > max_chars // 5:
                    break
                history.append(line)
                chars += len(line)
            header.append("\n".join([history[0], *reversed(history[1:])]))

        blocks: list[str] = []
        used = sum(len(x) for x in header)
        for item in reversed(self.evidence):
            block = item.prompt_line()
            if blocks and used + len(block) > max_chars:
                break
            blocks.append(block)
            used += len(block)
        blocks.reverse()

        if self.reports:
            report_lines = ["PRIVATE SUBAGENT REPORTS (summaries only):"]
            report_chars = 0
            for report in reversed(self.reports):
                line = (
                    f"- {report.label}/{report.job_id}: {report.summary[:1200]} "
                    f"| evidence={report.evidence_ids} | frontier={report.new_frontiers}"
                )
                if report_chars + len(line) > max_chars // 3:
                    break
                report_lines.append(line)
                report_chars += len(line)
            header.append("\n".join([report_lines[0], *reversed(report_lines[1:])]))

        omitted = max(0, len(self.evidence) - len(blocks))
        if omitted:
            header.append(
                f"NOTE: {omitted} older evidence item(s) are compacted out of this transport prompt; "
                "they still exist in persistent Main memory. Re-read/re-search exact source when needed."
            )
        return "\n\n".join([*header, *blocks])

    def export_memory(self) -> dict[str, Any]:
        return self.memory.to_dict()


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
