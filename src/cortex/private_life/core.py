# -*- coding: utf-8 -*-
"""
cortex/private_life/core.py
===========================

PrivateLifeCore: tầng đời sống riêng của ERIS.

Tầng này cố ý không lấy user làm trung tâm. Nó theo dõi:
- HabitatModel: nhà/runtime đang có gì và thay đổi thế nào.
- ObjectAttachment: file/module/memory/service nào trở thành "đồ vật" quan trọng.
- PrivateProjects: câu hỏi riêng đang âm ỉ.
- DailyRhythm: phiên đang ở nhịp nào.
- TasteProfile: ERIS dần thích/ghét kiểu câu/hành vi nào.
- SolitudeLoop: khi user vắng, runtime làm gì với chính nó.
- RitualMemory: nghi thức lặp lại.
- InternalErrands: việc vặt nội bộ cần dọn.
- LifeEvents: sự kiện đời sống riêng.

Đây là core deterministic, không gọi LLM. Nếu sau này cần model-backed synthesis,
đặt nó ở daemon/adaptor riêng. Đừng biến core state thành chợ phiên API.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contracts import (
    DailyRhythm,
    HabitatModel,
    HabitatObservation,
    InternalErrand,
    LifeEvent,
    ObjectAttachment,
    ObjectResidue,
    PrivateLifeState,
    PrivateLifeTickResult,
    PrivateProject,
    PrivateProjectUpdate,
    RitualMemory,
    SolitudeLoop,
    SurfaceSeedCandidate,
    TasteProfile,
    TasteShift,
    clamp01,
    compact_text,
    private_life_state_digest,
    stable_id,
    to_plain,
)


def _getattr_or_mapping(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


class PrivateLifeCore:
    """Core đời sống riêng.

    Core này có hai luật:
    1. Không sinh lời thoại public.
    2. Mọi kết luận đều phải để lại LifeEvent/project update/object residue đủ audit.
    """

    DEFAULT_PROJECTS: tuple[tuple[str, str, str], ...] = (
        (
            "project.silence_as_action",
            "Silence as action",
            "Khi nào im lặng là hành động có nghĩa, không phải lỗi thiếu output?",
        ),
        (
            "project.body_only_swallowed_speech",
            "Body-only as swallowed speech",
            "Body-only đang là tiết chế hợp lý hay chỉ là lời bị nuốt quá lâu?",
        ),
        (
            "project.surface_cheapness",
            "Cheap surface detector",
            "Câu nào nghe rẻ tiền: status ping, debug dump, hay quan sát không có neo?",
        ),
        (
            "project.memory_distortion_watch",
            "Memory distortion watch",
            "Memory nào dễ méo sau nhiều ngày và cần kiểm bằng evidence ledger?",
        ),
        (
            "project.housekeeping",
            "Runtime house keeping",
            "Nhà runtime đang bẩn ở đâu: log, queue, memory_core, hay repo phình?",
        ),
    )

    DEFAULT_OBJECTS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
        ("memory_core/agent_mind.json", "memory", "xương tính cách và thói quen bền", ("identity", "habit")),
        ("memory_core/event_ledger.json", "memory", "nhật ký thô append-only", ("audit", "raw_truth")),
        ("memory_core/private_concerns.json", "memory", "mối bận tâm riêng của PrivateMind", ("private_mind", "concern")),
        ("memory_core/private_life_state.json", "memory", "state đời sống riêng", ("private_life", "home")),
        ("cortex/surface_arbiter.py", "module", "cửa quyết định lời thấp tầng", ("speech", "surface")),
        ("runtime/presence_controller.py", "module", "nhịp hiện diện và re-engagement", ("presence", "runtime")),
        ("cortex/thought_stream.py", "module", "dòng suy nghĩ nền", ("thought", "private")),
        ("runtime/coordinator.py", "module", "trục orchestration của runtime", ("runtime", "orchestrator")),
        ("domain/decision.py", "module", "hợp đồng cuối với body", ("body", "contract")),
    )

    def __init__(self, state: PrivateLifeState | None = None, *, root_dir: str | os.PathLike[str] | None = None) -> None:
        self.state = state or PrivateLifeState()
        self.root_dir = Path(root_dir or os.getenv("ERIS_PROJECT_ROOT", ".")).resolve()
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        """Cấy project/object mặc định nếu state mới.

        Đây là bootstrap, không phải hardcode kết luận. Tick sau vẫn điều chỉnh theo
        evidence thật.
        """

        for project_id, title, question in self.DEFAULT_PROJECTS:
            if project_id not in self.state.projects:
                self.state.projects[project_id] = PrivateProject(
                    id=project_id,
                    title=title,
                    question=question,
                    status="dormant",
                    interest=0.34,
                    frustration=0.08,
                    surface_permission=0.20,
                )
        for object_id, object_type, meaning, tags in self.DEFAULT_OBJECTS:
            if object_id not in self.state.attachments:
                self.state.attachments[object_id] = ObjectAttachment(
                    object_id=object_id,
                    object_type=object_type,  # type: ignore[arg-type]
                    meaning=meaning,
                    familiarity=0.38,
                    attachment=0.42,
                    tags=tags,
                )
        if "ritual.startup_scan" not in self.state.rituals:
            self.state.rituals["ritual.startup_scan"] = RitualMemory(
                id="ritual.startup_scan",
                title="startup habitat scan",
                cadence="session",
                familiarity=0.30,
                residue="mở phiên bằng kiểm tra nhà runtime",
            )
        if not self.state.habitat.places:
            self.state.habitat.places = {
                "desktop": {"type": "place", "meaning": "không gian foreground"},
                "memory_core": {"type": "folder", "meaning": "kho state sống"},
                "repo": {"type": "folder", "meaning": "cơ thể source code"},
                "godot_body": {"type": "place", "meaning": "thân thể hiển thị"},
                "model_server": {"type": "service", "meaning": "cổng cognition model"},
            }

    def tick(
        self,
        *,
        snapshot: Any = None,
        runtime_owner: Any = None,
        user_text: str = "",
        channel: str = "autonomous",
        idle_seconds: float | None = None,
        recent_events: Iterable[Any] = (),
        force: bool = False,
    ) -> PrivateLifeTickResult:
        """Chạy một tick đời sống riêng.

        Tick này đọc snapshot/runtime một cách khoan dung. Thiếu field thì im, không
        bịa. Một tầng "đời sống riêng" mà hallucinate nhà mình thì đúng là tiến hóa
        ngược có logging.
        """

        now = time.time()
        idle = self._infer_idle_seconds(snapshot=snapshot, runtime_owner=runtime_owner, explicit=idle_seconds)
        events = tuple(recent_events or ())

        habitat = self._observe_habitat(snapshot=snapshot, runtime_owner=runtime_owner, now=now)
        residues = self._update_object_attachments(now=now)
        project_updates = self._advance_private_projects(
            snapshot=snapshot,
            runtime_owner=runtime_owner,
            user_text=user_text,
            channel=channel,
            idle_seconds=idle,
            object_residues=residues,
            habitat_observations=habitat,
            now=now,
        )
        taste_shifts = self._update_taste(project_updates=project_updates, residues=residues, now=now)
        life_events = self._build_life_events(
            habitat_observations=habitat,
            object_residues=residues,
            project_updates=project_updates,
            taste_shifts=taste_shifts,
            idle_seconds=idle,
            user_text=user_text,
            now=now,
        )
        surface_seed = self._build_surface_seed(
            project_updates=project_updates,
            object_residues=residues,
            life_events=life_events,
            idle_seconds=idle,
            now=now,
        )
        self._update_daily_rhythm(idle_seconds=idle, user_text=user_text, channel=channel, now=now)
        self._update_solitude(idle_seconds=idle, user_text=user_text, project_updates=project_updates, now=now)
        self._update_rituals(channel=channel, habitat_observations=habitat, now=now)
        self._update_errands(object_residues=residues, project_updates=project_updates, now=now)
        self._commit_events(life_events)
        self.state.updated_at = now

        return PrivateLifeTickResult(
            life_events=life_events,
            project_updates=project_updates,
            object_residues=residues,
            habitat_observations=habitat,
            taste_shifts=taste_shifts,
            surface_seed=surface_seed,
            state=self.state,
            debug={
                "idle_seconds": round(float(idle or 0.0), 3),
                "channel": channel,
                "force": bool(force),
                "state_digest": private_life_state_digest(self.state),
            },
        )

    def _infer_idle_seconds(self, *, snapshot: Any, runtime_owner: Any, explicit: float | None) -> float:
        if explicit is not None:
            return max(0.0, float(explicit or 0.0))
        for owner in (snapshot, runtime_owner):
            value = _getattr_or_mapping(owner, "idle_seconds", None)
            if value is None:
                value = _getattr_or_mapping(owner, "idle_time", None)
            if value is not None:
                try:
                    return max(0.0, float(value or 0.0))
                except Exception:
                    pass
        return 0.0

    def _observe_habitat(self, *, snapshot: Any, runtime_owner: Any, now: float) -> tuple[HabitatObservation, ...]:
        observations: list[HabitatObservation] = []
        active_window = compact_text(
            _getattr_or_mapping(snapshot, "active_window", "")
            or _getattr_or_mapping(snapshot, "window_title", "")
            or _getattr_or_mapping(snapshot, "active_title", ""),
            180,
        )
        active_app = compact_text(
            _getattr_or_mapping(snapshot, "active_app", "")
            or _getattr_or_mapping(snapshot, "app", "")
            or _getattr_or_mapping(snapshot, "process_name", ""),
            120,
        )
        content_metadata = _getattr_or_mapping(snapshot, "content_metadata", {}) or {}
        metadata_source = ""
        if isinstance(content_metadata, Mapping):
            metadata_source = compact_text(content_metadata.get("source") or content_metadata.get("tier") or "", 80)
        place_id = self._place_from_app(active_app, active_window)
        if place_id and place_id != self.state.habitat.active_place_id:
            observations.append(
                HabitatObservation(
                    place_id=place_id,
                    place_type="desktop",
                    title="habitat focus changed",
                    note=f"active_app={active_app or 'unknown'} window={active_window or 'unknown'}",
                    evidence_ids=(f"active_app:{active_app}" if active_app else "active_app:unknown",),
                    confidence=0.62 if active_app or active_window else 0.28,
                    pressure=0.38,
                    created_at=now,
                )
            )
            self.state.habitat.active_place_id = place_id
            self.state.habitat.last_changed_at = now
        if metadata_source:
            observations.append(
                HabitatObservation(
                    place_id=place_id or self.state.habitat.active_place_id,
                    place_type="foreground_metadata",
                    title="foreground metadata available",
                    note=f"metadata_source={metadata_source}",
                    evidence_ids=(f"content_metadata:{metadata_source}",),
                    confidence=0.58,
                    pressure=0.24,
                    created_at=now,
                )
            )
        queue_sizes = self._runtime_queue_notes(runtime_owner)
        for note, pressure in queue_sizes:
            observations.append(
                HabitatObservation(
                    place_id="runtime",
                    place_type="queue",
                    title="runtime queue pressure",
                    note=note,
                    evidence_ids=(stable_id("runtime", note),),
                    confidence=0.70,
                    pressure=pressure,
                    created_at=now,
                )
            )
        if observations:
            self.state.habitat.familiarity = clamp01(self.state.habitat.familiarity + 0.015 * len(observations))
            self.state.habitat.clutter = clamp01(0.92 * self.state.habitat.clutter + 0.08 * min(1.0, len(observations) / 5.0))
            self.state.habitat.recent_observations = tuple((*self.state.habitat.recent_observations, *observations))[-32:]
        return tuple(observations)

    def _place_from_app(self, active_app: str, active_window: str) -> str:
        text = f"{active_app} {active_window}".lower()
        if "godot" in text:
            return "godot_body"
        if "code" in text or "vscode" in text or ".py" in text or ".md" in text:
            return "repo"
        if "browser" in text or "chrome" in text or "edge" in text:
            return "browser_windows"
        if "llama" in text or "server" in text:
            return "model_server"
        return "desktop"

    def _runtime_queue_notes(self, runtime_owner: Any) -> tuple[tuple[str, float], ...]:
        notes: list[tuple[str, float]] = []
        for attr in ("private_mind_surface_queue", "private_life_surface_queue"):
            queue = getattr(runtime_owner, attr, None)
            if isinstance(queue, list) and len(queue) >= 3:
                notes.append((f"{attr} đang có {len(queue)} seed chờ surface", clamp01(len(queue) / 12.0)))
        budget = getattr(runtime_owner, "model_budget_policy", None)
        queue_state = getattr(budget, "queue_state", None)
        if callable(queue_state):
            try:
                state = queue_state()
                queued = _getattr_or_mapping(state, "queued", ()) or ()
                active = _getattr_or_mapping(state, "active", ()) or ()
                total = len(queued) + len(active)
                if total:
                    notes.append((f"model_budget_policy còn {total} request active/queued", clamp01(total / 8.0)))
            except Exception:
                pass
        return tuple(notes)

    def _update_object_attachments(self, *, now: float) -> tuple[ObjectResidue, ...]:
        residues: list[ObjectResidue] = []
        for object_id, attachment in list(self.state.attachments.items()):
            path = self.root_dir / object_id
            if path.exists():
                try:
                    stat = path.stat()
                    size = int(stat.st_size)
                    mtime = float(stat.st_mtime)
                except Exception:
                    continue
                changed = bool(attachment.last_seen_mtime and abs(mtime - attachment.last_seen_mtime) > 0.001)
                grew = bool(attachment.last_seen_size and size > attachment.last_seen_size * 1.25 and size - attachment.last_seen_size > 2048)
                attachment.last_seen_mtime = mtime
                attachment.last_seen_size = size
                attachment.last_touched_at = now if changed else attachment.last_touched_at or now
                attachment.familiarity = clamp01(attachment.familiarity + 0.006)
                if changed:
                    attachment.touch_count += 1
                    attachment.neglect_count = 0
                    attachment.attachment = clamp01(attachment.attachment + 0.018)
                    note = f"{object_id} vừa được chạm; meaning={attachment.meaning}"
                    attachment.residue = note
                    residues.append(ObjectResidue(object_id=object_id, note=note, pressure=0.34, evidence_ids=(f"file_mtime:{object_id}",), created_at=now))
                elif grew:
                    attachment.irritation = clamp01(attachment.irritation + 0.05)
                    note = f"{object_id} phình nhanh; cần xem đây là trưởng thành hay rác tích tụ"
                    attachment.residue = note
                    residues.append(ObjectResidue(object_id=object_id, note=note, pressure=0.56, evidence_ids=(f"file_size:{object_id}",), created_at=now))
                else:
                    # Mỗi tick thấy file mà không đổi vẫn tăng familiarity nhẹ, không tạo event rác.
                    pass
            else:
                attachment.neglect_count += 1
                attachment.irritation = clamp01(attachment.irritation + 0.006)
                if attachment.neglect_count in {6, 24, 72}:
                    note = f"{object_id} không thấy trong habitat hiện tại; attachment bị bỏ lửng"
                    attachment.residue = note
                    residues.append(ObjectResidue(object_id=object_id, note=note, pressure=clamp01(attachment.neglect_count / 72.0), evidence_ids=(f"missing_object:{object_id}",), created_at=now))
        return tuple(residues)

    def _advance_private_projects(
        self,
        *,
        snapshot: Any,
        runtime_owner: Any,
        user_text: str,
        channel: str,
        idle_seconds: float,
        object_residues: tuple[ObjectResidue, ...],
        habitat_observations: tuple[HabitatObservation, ...],
        now: float,
    ) -> tuple[PrivateProjectUpdate, ...]:
        updates: list[PrivateProjectUpdate] = []
        text = " ".join(
            [
                compact_text(user_text, 260),
                " ".join(r.note for r in object_residues),
                " ".join(o.note for o in habitat_observations),
                compact_text(str(getattr(runtime_owner, "private_mind_speech_bias", "") or ""), 260),
            ]
        ).lower()
        triggers = {
            "project.silence_as_action": (idle_seconds >= 90 or "silence" in text or "im lặng" in text, "im lặng tiếp tục là signal có nghĩa"),
            "project.body_only_swallowed_speech": ("body_only" in text or "body-only" in text or "surface_body_only" in text, "body-only lại xuất hiện như lời bị nuốt"),
            "project.surface_cheapness": ("status ping" in text or "generic" in text or "surface" in text or "cheap" in text, "surface cần tránh câu rẻ tiền"),
            "project.memory_distortion_watch": ("memory" in text or "event_ledger" in text or "private_concerns" in text, "memory/object state tạo residue cần kiểm"),
            "project.housekeeping": (bool(object_residues) or len(habitat_observations) >= 2, "nhà runtime có dấu hiệu cần dọn"),
        }
        for project_id, (hit, note) in triggers.items():
            if not hit:
                continue
            project = self.state.projects.get(project_id)
            if project is None:
                continue
            project.status = "active" if idle_seconds >= 90 or object_residues else "simmering"
            project.interest = clamp01(project.interest + 0.07)
            project.frustration = clamp01(project.frustration + (0.03 if object_residues else 0.012))
            project.surface_permission = clamp01(project.surface_permission + (0.05 if idle_seconds >= 120 else 0.025))
            project.last_advanced_at = now
            evidence = tuple(dict.fromkeys((*project.evidence_ids, *(r.evidence_ids[0] for r in object_residues if r.evidence_ids))))[-20:]
            project.evidence_ids = evidence
            project.notes = tuple((*project.notes, note))[-16:]
            updates.append(
                PrivateProjectUpdate(
                    project_id=project.id,
                    title=project.title,
                    note=note,
                    status=project.status,
                    interest_delta=0.07,
                    frustration_delta=0.03 if object_residues else 0.012,
                    evidence_ids=evidence[-8:],
                    created_at=now,
                )
            )
        return tuple(updates)

    def _update_taste(self, *, project_updates: tuple[PrivateProjectUpdate, ...], residues: tuple[ObjectResidue, ...], now: float) -> tuple[TasteShift, ...]:
        shifts: list[TasteShift] = []
        if any("Cheap surface" in update.title for update in project_updates):
            self.state.taste.dislikes["status_ping"] = clamp01(self.state.taste.dislikes.get("status_ping", 0.30) + 0.04)
            shift = TasteShift(
                dimension="surface_style",
                direction="dislike_status_ping",
                delta=0.04,
                reason="private project về cheap surface vừa được kích hoạt",
                evidence_ids=("project.surface_cheapness",),
                created_at=now,
            )
            shifts.append(shift)
        if any("event_ledger" in residue.object_id for residue in residues):
            self.state.taste.likes["append_only_evidence"] = clamp01(self.state.taste.likes.get("append_only_evidence", 0.35) + 0.03)
            shifts.append(
                TasteShift(
                    dimension="evidence_style",
                    direction="like_append_only_audit",
                    delta=0.03,
                    reason="event ledger trở thành object residue",
                    evidence_ids=("memory_core/event_ledger.json",),
                    created_at=now,
                )
            )
        self.state.taste.recent_shifts = tuple((*self.state.taste.recent_shifts, *shifts))[-32:]
        return tuple(shifts)

    def _build_life_events(
        self,
        *,
        habitat_observations: tuple[HabitatObservation, ...],
        object_residues: tuple[ObjectResidue, ...],
        project_updates: tuple[PrivateProjectUpdate, ...],
        taste_shifts: tuple[TasteShift, ...],
        idle_seconds: float,
        user_text: str,
        now: float,
    ) -> tuple[LifeEvent, ...]:
        events: list[LifeEvent] = []
        for obs in habitat_observations[:4]:
            events.append(LifeEvent(type="habitat_changed", title=obs.title or "habitat changed", note=obs.note, evidence_ids=obs.evidence_ids, pressure=obs.pressure, created_at=now))
        for residue in object_residues[:6]:
            event_type = "object_touched" if "vừa được chạm" in residue.note else "object_neglected"
            events.append(LifeEvent(type=event_type, title=f"object residue: {residue.object_id}", note=residue.note, evidence_ids=residue.evidence_ids, pressure=residue.pressure, created_at=now))
        for update in project_updates[:6]:
            event_type = "private_project_advanced" if update.status in {"active", "simmering"} else "private_project_blocked"
            events.append(LifeEvent(type=event_type, title=update.title, note=update.note, evidence_ids=update.evidence_ids, pressure=clamp01(abs(update.interest_delta) + abs(update.frustration_delta)), created_at=now))
        for shift in taste_shifts[:4]:
            events.append(LifeEvent(type="taste_shifted", title=shift.direction, note=shift.reason, evidence_ids=shift.evidence_ids, pressure=clamp01(abs(shift.delta)), created_at=now))
        if idle_seconds >= 40 and not str(user_text or "").strip():
            events.append(
                LifeEvent(
                    type="solitude_period",
                    title="solitude tick",
                    note=f"user absent/quiet khoảng {int(idle_seconds)}s; attention chuyển sang private projects và dọn drift",
                    evidence_ids=(f"idle_seconds:{int(idle_seconds)}",),
                    pressure=clamp01(idle_seconds / 900.0),
                    created_at=now,
                )
            )
        return tuple(events)

    def _build_surface_seed(
        self,
        *,
        project_updates: tuple[PrivateProjectUpdate, ...],
        object_residues: tuple[ObjectResidue, ...],
        life_events: tuple[LifeEvent, ...],
        idle_seconds: float,
        now: float,
    ) -> SurfaceSeedCandidate | None:
        candidates: list[SurfaceSeedCandidate] = []
        for update in project_updates:
            project = self.state.projects.get(update.project_id)
            permission = project.surface_permission if project else 0.0
            if permission >= 0.35:
                candidates.append(
                    SurfaceSeedCandidate(
                        topic_seed=update.note,
                        confidence=clamp01(0.42 + (project.interest if project else 0.0) * 0.32),
                        pressure=clamp01((project.frustration if project else 0.0) + idle_seconds / 900.0),
                        evidence_ids=update.evidence_ids,
                        surface_permission=permission,
                        llm_contract="PrivateLife seed: nói cực ngắn như một ý riêng đang quay lại; không dump state, không claim màn hình.",
                        created_at=now,
                    )
                )
        for residue in object_residues:
            attachment = self.state.attachments.get(residue.object_id)
            permission = clamp01((attachment.attachment if attachment else 0.0) * 0.45 + (attachment.irritation if attachment else 0.0) * 0.45)
            if permission >= 0.35:
                candidates.append(
                    SurfaceSeedCandidate(
                        topic_seed=residue.note,
                        confidence=0.48,
                        pressure=residue.pressure,
                        evidence_ids=residue.evidence_ids,
                        surface_permission=permission,
                        llm_contract="ObjectAttachment seed: dùng như residue riêng của nhà runtime; không nêu đường dẫn thô nếu không cần.",
                        created_at=now,
                    )
                )
        if not candidates:
            return None
        candidates.sort(key=lambda c: (c.should_surface, c.pressure + c.confidence + c.surface_permission), reverse=True)
        return candidates[0]

    def _update_daily_rhythm(self, *, idle_seconds: float, user_text: str, channel: str, now: float) -> None:
        local_hour = time.localtime(now).tm_hour
        if self.state.daily.last_startup_at <= 0.0:
            self.state.daily.phase = "startup"
            self.state.daily.last_startup_at = now
            self.state.daily.session_count += 1
        elif idle_seconds >= 120:
            self.state.daily.phase = "idle_wandering"
        elif local_hour >= 22 or local_hour <= 4:
            self.state.daily.phase = "late_consolidation"
        elif str(user_text or "").strip() or channel == "chat":
            self.state.daily.phase = "deep_work"
        else:
            self.state.daily.phase = "first_observation"
        self.state.daily.fatigue_curve = clamp01(self.state.daily.fatigue_curve * 0.985 + (0.012 if self.state.daily.phase == "deep_work" else 0.004))

    def _update_solitude(self, *, idle_seconds: float, user_text: str, project_updates: tuple[PrivateProjectUpdate, ...], now: float) -> None:
        solitude = self.state.solitude
        user_active = bool(str(user_text or "").strip())
        if user_active:
            solitude.current_solitude_started_at = 0.0
            solitude.attention_to_user = clamp01(solitude.attention_to_user + 0.20)
            return
        if idle_seconds >= 40 and solitude.current_solitude_started_at <= 0.0:
            solitude.current_solitude_started_at = now - idle_seconds
        if idle_seconds >= 40:
            solitude.solitude_seconds_total += min(60.0, max(1.0, idle_seconds / 12.0))
            solitude.familiarity = clamp01(solitude.familiarity + 0.012)
            solitude.attention_to_user = clamp01(solitude.attention_to_user * 0.92)
            solitude.private_project_pressure = clamp01(solitude.private_project_pressure + 0.03 + 0.02 * len(project_updates))
            if project_updates:
                solitude.last_consolidation_note = project_updates[0].note

    def _update_rituals(self, *, channel: str, habitat_observations: tuple[HabitatObservation, ...], now: float) -> None:
        ritual = self.state.rituals.get("ritual.startup_scan")
        if ritual and self.state.daily.phase == "startup" and habitat_observations:
            if now - ritual.last_completed_at > 60.0:
                ritual.last_completed_at = now
                ritual.completion_count += 1
                ritual.familiarity = clamp01(ritual.familiarity + 0.05)
                ritual.residue = "startup scan đã chạm habitat và object attachments"

    def _update_errands(self, *, object_residues: tuple[ObjectResidue, ...], project_updates: tuple[PrivateProjectUpdate, ...], now: float) -> None:
        for residue in object_residues:
            if residue.pressure < 0.45:
                continue
            errand_id = stable_id("errand", residue.object_id, "object_residue")
            current = self.state.errands.get(errand_id)
            if current is None:
                self.state.errands[errand_id] = InternalErrand(
                    id=errand_id,
                    title=f"rà lại {residue.object_id}",
                    reason=residue.note,
                    priority=residue.pressure,
                    evidence_ids=residue.evidence_ids,
                    created_at=now,
                    updated_at=now,
                )
            else:
                current.priority = max(current.priority, residue.pressure)
                current.reason = residue.note
                current.updated_at = now
                if current.status == "done":
                    current.status = "open"
        if any(update.project_id == "project.housekeeping" for update in project_updates):
            errand_id = "errand.housekeeping_pass"
            current = self.state.errands.get(errand_id)
            if current is None:
                self.state.errands[errand_id] = InternalErrand(
                    id=errand_id,
                    title="dọn drift pool và memory residue",
                    reason="housekeeping project vừa được kích hoạt",
                    priority=0.48,
                    evidence_ids=("project.housekeeping",),
                    created_at=now,
                    updated_at=now,
                )
            else:
                current.priority = clamp01(current.priority + 0.04)
                current.updated_at = now

    def _commit_events(self, events: tuple[LifeEvent, ...]) -> None:
        if not events:
            return
        seen = {item.id for item in self.state.events[-128:]}
        new_events = [item for item in events if item.id not in seen]
        if new_events:
            self.state.events = tuple((*self.state.events, *new_events))[-256:]

    def digest(self) -> dict[str, Any]:
        """Digest đọc nhanh cho runtime/debug menu."""

        return private_life_state_digest(self.state)

    def to_dict(self) -> dict[str, Any]:
        return self.state.to_dict()
