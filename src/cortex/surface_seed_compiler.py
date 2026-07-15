# -*- coding: utf-8 -*-
"""Compile public-safe surface seeds from low-level runtime pressure."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
import unicodedata
from typing import Any, Mapping

from .surface_arbiter import SurfaceImpulse

try:
    from runtime.liveliness_config import LivelinessConfig, load_liveliness_config
except Exception:  # pragma: no cover - allow import in partial test envs
    LivelinessConfig = None  # type: ignore[assignment]
    load_liveliness_config = None  # type: ignore[assignment]


_SPACE_RE = re.compile(r"\s+")
_JSONISH_RE = re.compile(r"[\{\}\[\]]")
_GENERIC_TIMER_RE = re.compile(r"^(idle=\d+s|idle_seconds=\d+(?:\.\d+)?|long_silence|silence_pressure=)", re.I)
_PRIVATE_MARKERS = (
    "internaljudgment",
    "thoughtfragment",
    "privateconcern",
    "state mutation",
    "state_mutation",
    "chain-of-thought",
    "raw judgment",
    "private mind json",
    "debug_api",
)
_GENERIC_VISION = (
    "focus kind is general",
    "focus=unknown",
    "intent=unknown",
    "activity_intent=unknown",
    "visible screen context",
)
_GENERIC_MEMORY_SEED_RE = re.compile(
    r"^(memory[_\s-]?resonance|remembered pattern|pattern residue|memory activation|semantic memory|recalled pattern)\.?$",
    re.I,
)

# Inner Diary section titles produced by InnerDiaryRenderer. The diary voice is
# Eris's own public-facing reflection, so it is legitimate seed material: it lets
# "what Eris is thinking" actually drive autonomous speech instead of dead-ending
# in a read-only UI panel.
_DIARY_TITLE_TO_KEY = {
    "muốn nói": "muon_noi",
    "suy nghĩ tương lai": "tuong_lai",
    "suy nghĩ hiện tại": "hien_tai",
    "đang bận tâm": "ban_tam",
    "phân tích gần đây": "phan_tich",
}


@dataclass(frozen=True, slots=True)
class CompiledSurfaceSeed:
    topic_seed: str = ""
    public_seed: str = ""
    evidence: tuple[str, ...] = ()
    confidence: float = 0.0
    pressure: float = 0.0
    root_source: str = ""
    impulse_kind: str = ""
    action_opportunity: str = ""
    llm_contract: str = ""
    surface_contract_flags: tuple[str, ...] = ()
    debug: dict[str, object] = field(default_factory=dict)
    impulse: SurfaceImpulse | None = None
    alternative_impulses: tuple[SurfaceImpulse, ...] = ()

    @property
    def selected(self) -> bool:
        return bool(self.topic_seed and self.public_seed)


@dataclass(frozen=True, slots=True)
class _SeedCandidate:
    topic_seed: str
    public_seed: str
    evidence: tuple[str, ...]
    confidence: float
    pressure: float
    root_source: str
    impulse_kind: str
    action_opportunity: str
    llm_contract: str
    public_anchor: bool
    missing_screen: bool
    reason: str
    raw: Any = None


class SurfaceSeedCompiler:
    """Small compiler that turns scattered internal pressure into one public-safe seed."""

    #: Enumerated no-seed reasons (no generic/unspecified failure value allowed).
    NO_SEED_REASONS = (
        "no_public_anchor",
        "private_only",
        "timer_only",
        "low_pressure",
    )

    def __init__(self, *, config: "LivelinessConfig | None" = None) -> None:
        if config is not None:
            self._config = config
        elif load_liveliness_config is not None:
            self._config = load_liveliness_config()
        else:  # pragma: no cover - partial env fallback
            self._config = None
        self._seed_max_len = int(getattr(self._config, "seed_max_len", 240) or 240)

    def compile(
        self,
        *,
        frame: Any = None,
        snapshot: Any = None,
        surface_kind: str = "surface",
        presence_cue: Any = None,
        internal_state: Any = None,
        thought_stream: Any = None,
        private_mind_digest: Any = None,
        private_life_digest: Any = None,
        inner_diary: Any = None,
        private_mind_speech_bias: Any = None,
        private_mind_thought_pressure: float = 0.0,
        active_memory_resonance: Any = None,
        extra_impulses: tuple[object, ...] = (),
    ) -> CompiledSurfaceSeed:
        candidates: list[_SeedCandidate] = []
        candidates.extend(self._from_extra_impulses(extra_impulses))
        candidates.extend(self._from_memory_resonance(active_memory_resonance))
        candidates.extend(self._from_thought_sources(frame=frame, thought_stream=thought_stream))
        candidates.extend(self._from_vision(snapshot=snapshot, presence_cue=presence_cue))
        candidates.extend(
            self._from_private_bias(
                private_mind_speech_bias=private_mind_speech_bias,
                private_mind_thought_pressure=private_mind_thought_pressure,
                private_mind_digest=private_mind_digest,
            )
        )
        candidates.extend(self._from_private_life_digest(private_life_digest))
        candidates.extend(self._from_inner_diary(inner_diary))

        current_domain = self._current_context_domain(snapshot=snapshot, presence_cue=presence_cue)
        safe = [
            candidate
            for candidate in candidates
            if self._candidate_allowed(candidate)
            and self._candidate_context_compatible(
                candidate,
                current_domain=current_domain,
                surface_kind=surface_kind,
            )
        ]
        if not safe:
            return CompiledSurfaceSeed(
                debug={
                    "reason": self._no_seed_reason(candidates),
                    "candidate_count": len(candidates),
                    "current_domain": current_domain,
                }
            )

        ranked = sorted(safe, key=self._rank_key, reverse=True)
        selected = ranked[0]
        flags = ["allow_no_screen_anchor", "must_not_claim_screen"] if selected.missing_screen else ()
        if str(surface_kind or "") in {"re_engagement", "presence_maintenance"} and selected.missing_screen:
            flags = tuple(dict.fromkeys((*flags, "thin_presence_no_screen")))
        impulse = self._to_impulse(selected, surface_kind=surface_kind)
        alternative_impulses = tuple(
            self._to_impulse(candidate, surface_kind=surface_kind) for candidate in ranked[1:]
        )
        return CompiledSurfaceSeed(
            topic_seed=selected.topic_seed,
            public_seed=selected.public_seed,
            evidence=selected.evidence,
            confidence=selected.confidence,
            pressure=selected.pressure,
            root_source=selected.root_source,
            impulse_kind=selected.impulse_kind,
            action_opportunity=selected.action_opportunity,
            llm_contract=selected.llm_contract,
            surface_contract_flags=flags,
            debug={
                "reason": "selected",
                "source": selected.root_source,
                "selected_source": selected.root_source,
                "selected_confidence": round(float(selected.confidence), 3),
                "public_anchor": selected.public_anchor,
                "candidate_count": len(candidates),
                "current_domain": current_domain,
                "selected_domain": self._candidate_domain(selected),
            },
            impulse=impulse,
            alternative_impulses=alternative_impulses,
        )

    def _from_extra_impulses(self, extra_impulses: tuple[object, ...]) -> tuple[_SeedCandidate, ...]:
        out: list[_SeedCandidate] = []
        for impulse in tuple(extra_impulses or ()):
            if not isinstance(impulse, SurfaceImpulse):
                continue
            source = str(getattr(impulse, "source", "") or "")
            if source == "private_mind" and self._private_impulse_has_anchor(impulse):
                text = self._clean(getattr(impulse, "topic_seed", ""))
                if text:
                    out.append(
                        _SeedCandidate(
                            topic_seed=text,
                            public_seed=text,
                            evidence=self._evidence_tuple(getattr(impulse, "evidence", ())),
                            confidence=self._clamp(getattr(impulse, "confidence", 0.0)),
                            pressure=self._clamp(getattr(impulse, "pressure", 0.0)),
                            root_source="private_mind_surface",
                            impulse_kind=str(getattr(impulse, "kind", "") or "private_mind_surface"),
                            action_opportunity="use only the public-safe private seed; no raw private judgment",
                            llm_contract=str(getattr(impulse, "llm_contract", "") or "Public-safe private mind seed only."),
                            public_anchor=True,
                            missing_screen=True,
                            reason="surface_valve_approved_private_impulse",
                            raw=impulse,
                        )
                    )
            elif source == "private_life":
                text = self._clean(getattr(impulse, "topic_seed", ""))
                if text:
                    out.append(
                        _SeedCandidate(
                            topic_seed=text,
                            public_seed=text,
                            evidence=self._evidence_tuple(getattr(impulse, "evidence", ())),
                            confidence=self._clamp(getattr(impulse, "confidence", 0.0)),
                            pressure=self._clamp(getattr(impulse, "pressure", 0.0)),
                            root_source="private_life",
                            impulse_kind=str(getattr(impulse, "kind", "") or "private_life_surface"),
                            action_opportunity=str(getattr(impulse, "action_opportunity", "") or "one low-claim private-life line"),
                            llm_contract=str(getattr(impulse, "llm_contract", "") or "PrivateLife seed only; no raw state dump, no screen claim."),
                            public_anchor=True,
                            missing_screen=True,
                            reason="private_life_surface_impulse",
                            raw=impulse,
                        )
                    )
            elif source in {"memory_resonance", "thought_stream", "internal_agenda", "endogenous_drive"}:
                text = self._clean(getattr(impulse, "topic_seed", ""))
                if text:
                    out.append(
                        _SeedCandidate(
                            topic_seed=text,
                            public_seed=text,
                            evidence=self._evidence_tuple(getattr(impulse, "evidence", ())),
                            confidence=self._clamp(getattr(impulse, "confidence", 0.0)),
                            pressure=self._clamp(getattr(impulse, "pressure", 0.0)),
                            root_source=source,
                            impulse_kind=str(getattr(impulse, "kind", "") or "inner_whim"),
                            action_opportunity=str(getattr(impulse, "action_opportunity", "") or "one rooted low-claim line"),
                            llm_contract=str(getattr(impulse, "llm_contract", "") or "Use seed only; no screen claim."),
                            public_anchor=not bool(getattr(impulse, "missing_evidence_ids", False)),
                            missing_screen=bool(getattr(impulse, "missing_evidence_ids", True)),
                            reason="existing_surface_impulse",
                            raw=impulse,
                        )
                    )
        return tuple(out)

    def _from_memory_resonance(self, resonance: Any) -> tuple[_SeedCandidate, ...]:
        if resonance is None:
            return ()
        pressure = max(
            self._clamp(getattr(resonance, "score", 0.0)),
            self._clamp(getattr(resonance, "wording_bias", 0.0)),
            self._clamp(getattr(resonance, "attention_bias", 0.0)) * 0.82,
        )
        if pressure < 0.34:
            return ()
        activations = tuple(getattr(resonance, "activations", ()) or ())
        public = [item for item in activations if bool(getattr(item, "may_surface", False))]
        if not public:
            return ()
        item = public[0]
        seed = self._clean(getattr(item, "text", "") or getattr(item, "summary", ""))
        if not seed:
            return ()
        evidence = self._evidence_tuple(getattr(item, "evidence_ids", ()))
        if not evidence:
            record_id = self._clean(getattr(item, "record_id", ""))
            evidence = (f"memory_activation:{record_id}",) if record_id else (seed[:120],)
        if not self._is_rich_memory_seed(seed, evidence):
            return ()
        layer = self._clean(getattr(item, "layer", "") or getattr(resonance, "dominant_layer", "") or "memory")
        memory_id = self._anchor_token("memory", evidence[0] if evidence else getattr(item, "record_id", "") or seed)
        return (
            _SeedCandidate(
                topic_seed=seed,
                public_seed=seed,
                evidence=tuple(dict.fromkeys((memory_id, *evidence)))[:8],
                confidence=max(0.38, min(0.84, pressure + 0.08)),
                pressure=pressure,
                root_source="memory_resonance",
                impulse_kind="memory_resonance",
                action_opportunity="speak like a remembered pattern lightly resurfaced; do not expose memory internals",
                llm_contract="memory_resonance: use memory as seed, not current screen evidence.",
                public_anchor=True,
                missing_screen=True,
                reason=f"memory_resonance:{layer}",
                raw=item,
            ),
        )

    def _is_rich_memory_seed(self, seed: str, evidence: tuple[str, ...]) -> bool:
        text = self._clean(seed)
        if not text:
            return False
        # Public-safety gate (Req 1.7): drop anything that leaks private content.
        if not self._candidate_text_public(text):
            return False
        lowered = text.lower()
        if _GENERIC_MEMORY_SEED_RE.match(lowered):
            return False
        # Retain any non-empty public-safe seed regardless of token length
        # (Req 1.4), bounded by the configured maximum length.
        if len(text) > self._seed_max_len:
            return False
        evidence_blob = " ".join(str(item or "") for item in tuple(evidence or ())).lower()
        if not evidence_blob.strip():
            return False
        return True

    def _from_thought_sources(self, *, frame: Any, thought_stream: Any) -> tuple[_SeedCandidate, ...]:
        out: list[_SeedCandidate] = []
        for owner in (frame, thought_stream):
            if owner is None:
                continue
            for value in self._thought_values(owner):
                candidate = self._candidate_from_thought(value)
                if candidate is not None:
                    out.append(candidate)
        return tuple(out)

    def _thought_values(self, owner: Any) -> tuple[Any, ...]:
        values: list[Any] = []
        for attr in ("thought_surface", "subconscious_seed"):
            value = getattr(owner, attr, None)
            if value is not None:
                values.append(value)
        report = getattr(owner, "thought_stream_report", None) or getattr(owner, "subconscious_report", None)
        if report is not None:
            seed = getattr(report, "latest_seed", None)
            if seed is not None:
                values.append(seed)
            recent = getattr(report, "recent_seeds", ()) or ()
            values.extend(tuple(recent)[:3])
        getter = getattr(owner, "get_surface_candidates", None)
        if callable(getter):
            try:
                values.extend(tuple(getter(limit=4) or ()))
            except TypeError:
                try:
                    values.extend(tuple(getter() or ())[:4])
                except Exception:
                    pass
            except Exception:
                pass
        return tuple(values)

    def _candidate_from_thought(self, value: Any) -> _SeedCandidate | None:
        get = value.get if isinstance(value, Mapping) else lambda key, default=None: getattr(value, key, default)
        route = self._clean(get("recommended_route", ""))
        allowed = bool(get("surface_allowed", False)) or route == "surface_candidate" or bool(self._clean(get("public_seed", "")))
        if not allowed:
            return None
        public_seed = self._clean(get("public_seed", ""))
        topic = self._clean(public_seed or get("topic_seed", "") or get("partial_text", "") or get("summary", ""))
        if not topic:
            return None
        pressure = max(
            self._clamp(get("pressure", 0.0)),
            self._clamp(get("surface_pressure", 0.0)),
            self._clamp(get("momentum_score", 0.0)),
            self._clamp(get("novelty", 0.0)) * 0.70,
        )
        if pressure < 0.25:
            return None
        impulse_kind = self._clean(get("impulse_kind", "")) or "inner_whim"
        root_source = self._clean(get("root_source", "")) or "thought_stream"
        evidence = self._evidence_tuple(get("evidence", ()) or get("evidence_ids", ()))
        event_id = self._anchor_token("event", evidence[0] if evidence else topic)
        return _SeedCandidate(
            topic_seed=topic,
            public_seed=public_seed or topic,
            evidence=tuple(dict.fromkeys((event_id, *(evidence or (f"thought_seed:{topic[:80]}",)))))[:8],
            confidence=max(0.34, min(0.82, pressure)),
            pressure=pressure,
            root_source=root_source,
            impulse_kind=impulse_kind,
            action_opportunity=self._clean(get("action_opportunity", "")) or "surface one tiny rooted stray thought; no screen claim",
            llm_contract="thought_seed: brief rooted aside; no generic silence line.",
            public_anchor=bool(evidence or public_seed),
            missing_screen=True,
            reason="thought_public_seed",
            raw=value,
        )

    def _from_vision(self, *, snapshot: Any, presence_cue: Any) -> tuple[_SeedCandidate, ...]:
        facts = tuple(self._clean(item) for item in (getattr(snapshot, "vision_facts", ()) or ()) if self._clean(item))
        recent_events = tuple(self._clean(item) for item in (getattr(snapshot, "recent_events", ()) or ()) if self._clean(item))
        source: list[str] = []
        for fact in facts:
            if self._is_specific_vision_fact(fact):
                source.append(fact)
        if not source:
            return ()
        for event in recent_events[:2]:
            if not self._looks_timer_only(event):
                source.append(f"recent_event={event}")
        cue_conf = self._clamp(getattr(presence_cue, "confidence", 0.0))
        seed = source[0]
        vision_fact_id = self._anchor_token("vision_fact", seed)
        # Evidence-derived confidence: a fresh, specific, concrete screen fact is
        # high-signal and must be able to out-rank a generic private-life seed
        # (which sits around 0.74). Confidence grows with specificity and the
        # number of corroborating concrete sources, bounded to [0,1].
        specificity = 0.08 if self._is_specific_vision_fact(seed) else 0.0
        corroboration = 0.04 * max(0, min(3, len(source) - 1))
        confidence = self._clamp(max(cue_conf, 0.70) + specificity + corroboration)
        pressure = self._clamp(max(0.50, cue_conf))
        return (
            _SeedCandidate(
                topic_seed=seed,
                public_seed=seed,
                evidence=tuple(dict.fromkeys((vision_fact_id, *source[:3], "vision_fact")))[:6],
                confidence=confidence,
                pressure=pressure,
                root_source="vision_fact",
                impulse_kind="technical_help",
                action_opportunity="one tiny practical or observational cue rooted in visible evidence",
                llm_contract="vision_fact: use only supplied fact; no extra screen claim.",
                public_anchor=True,
                missing_screen=False,
                reason="vision_fact",
            ),
        )

    def _from_private_life_digest(self, private_life_digest: Any) -> tuple[_SeedCandidate, ...]:
        """Lấy seed từ PrivateLife digest đã compact.

        Digest chỉ được dùng như nguồn seed public-safe, không phải prompt dump. Nếu
        không có `surface_seed` hoặc project/object cụ thể thì bỏ qua. Một đời sống
        riêng mà surface bằng JSON menu thì chỉ là debug panel biết nói, nghe buồn.
        """

        if not isinstance(private_life_digest, Mapping):
            return ()
        last_tick = private_life_digest.get("last_tick") if isinstance(private_life_digest.get("last_tick"), Mapping) else {}
        core_result = last_tick.get("core_result") if isinstance(last_tick, Mapping) and isinstance(last_tick.get("core_result"), Mapping) else {}
        surface_seed = core_result.get("surface_seed") if isinstance(core_result, Mapping) and isinstance(core_result.get("surface_seed"), Mapping) else None
        if isinstance(surface_seed, Mapping):
            text = self._clean(surface_seed.get("topic_seed") or "")
            if text and self._candidate_text_public(text):
                return (
                    _SeedCandidate(
                        topic_seed=text,
                        public_seed=text,
                        evidence=self._evidence_tuple(surface_seed.get("evidence_ids") or ()),
                        confidence=self._clamp(surface_seed.get("confidence", 0.0)),
                        pressure=self._clamp(surface_seed.get("pressure", 0.0)),
                        root_source="private_life",
                        impulse_kind=str(surface_seed.get("kind") or "private_life_surface"),
                        action_opportunity="one low-claim private-life line; do not expose runtime state",
                        llm_contract=str(surface_seed.get("llm_contract") or "PrivateLife seed only; no raw state dump."),
                        public_anchor=True,
                        missing_screen=True,
                        reason="private_life_digest_surface_seed",
                        raw=surface_seed,
                    ),
                )

        current = private_life_digest.get("current") if isinstance(private_life_digest.get("current"), Mapping) else {}
        projects = current.get("projects") if isinstance(current, Mapping) else None
        if isinstance(projects, list) and projects:
            project = next((item for item in projects if isinstance(item, Mapping) and self._clean(item.get("last_note") or "")), None)
            if project:
                text = self._clean(project.get("last_note") or project.get("title") or "")
                permission = self._clamp(project.get("surface_permission", 0.0))
                interest = self._clamp(project.get("interest", 0.0))
                if text and permission >= 0.35 and self._candidate_text_public(text):
                    return (
                        _SeedCandidate(
                            topic_seed=text,
                            public_seed=text,
                            evidence=(str(project.get("id") or "private_life_project"),),
                            confidence=max(0.38, min(0.76, 0.36 + interest * 0.34)),
                            pressure=max(0.32, self._clamp(project.get("frustration", 0.0))),
                            root_source="private_life",
                            impulse_kind="private_life_surface",
                            action_opportunity="surface a private project residue very lightly",
                            llm_contract="PrivateLife project seed: no raw state, no screen claim, one short line only.",
                            public_anchor=True,
                            missing_screen=True,
                            reason="private_life_project_digest",
                            raw=project,
                        ),
                    )

        # PrivateAnchor là nguồn mới: 5 neo riêng được compact trong digest.
        # Compiler chỉ lấy last_note đã public-safe, không bê cả câu hỏi/stance dài ra prompt.
        anchors = current.get("anchors") if isinstance(current, Mapping) else None
        if isinstance(anchors, list) and anchors:
            anchor = next((item for item in anchors if isinstance(item, Mapping) and self._clean(item.get("last_note") or "")), None)
            if anchor:
                text = self._clean(anchor.get("last_note") or anchor.get("title") or "")
                permission = self._clamp(anchor.get("surface_permission", 0.0))
                pressure = self._clamp(anchor.get("pressure", 0.0))
                continuity = self._clamp(anchor.get("continuity", 0.0))
                if text and permission >= 0.35 and self._candidate_text_public(text):
                    return (
                        _SeedCandidate(
                            topic_seed=text,
                            public_seed=text,
                            evidence=(str(anchor.get("id") or "private_life_anchor"),),
                            confidence=max(0.40, min(0.78, 0.34 + continuity * 0.34)),
                            pressure=max(0.34, pressure),
                            root_source="private_life",
                            impulse_kind="private_anchor_surface",
                            action_opportunity="surface a private anchor residue very lightly",
                            llm_contract="PrivateLife anchor seed: no raw state, no screen claim, no consciousness claim, one short line only.",
                            public_anchor=True,
                            missing_screen=True,
                            reason="private_life_anchor_digest",
                            raw=anchor,
                        ),
                    )
        return ()

    def _from_inner_diary(self, inner_diary: Any) -> tuple[_SeedCandidate, ...]:
        """Seed từ Inner Diary — để "thứ Eris đang nghĩ" thực sự lái được lời nói.

        Trước đây diary chỉ chảy một chiều ra UI/đĩa; giọng Eris nội tâm không bao
        giờ quay lại đường nói. Ở đây ta lấy lại giọng đã được viết public-safe
        (muốn nói / suy nghĩ tương lai / suy nghĩ hiện tại) làm chất liệu seed, để
        autonomous bớt phẳng và bớt câm cả tiếng. Vẫn qua cổng public-safety và
        giới hạn độ dài như mọi seed khác.
        """

        voice = self._inner_diary_voice(inner_diary)
        if not voice:
            return ()
        # (key, impulse_kind, confidence, pressure, action_opportunity, llm_contract)
        specs = (
            (
                "muon_noi",
                "inner_whim",
                0.66,
                0.56,
                "voice one thing Eris already wants to say; keep it light, no screen claim",
                "inner_diary: surface the wants-to-say line as a tiny rooted aside; no raw state.",
            ),
            (
                "tuong_lai",
                "curious_question",
                0.62,
                0.50,
                "turn a forming inner question into one small real question; no screen claim",
                "inner_diary: shape the forward thought into one short curious question.",
            ),
            (
                "hien_tai",
                "light_muse",
                0.58,
                0.46,
                "muse lightly from a current inner thought; no raw judgment, no screen claim",
                "inner_diary: use the current-thought reflection as seed only, not verbatim.",
            ),
            (
                "ban_tam",
                "inner_whim",
                0.56,
                0.48,
                "voice the thing quietly on Eris's mind as a small rooted aside; no raw concern dump",
                "inner_diary: surface the lingering concern lightly as a stray thought, not a report.",
            ),
            (
                "phan_tich",
                "random_chatter",
                0.52,
                0.42,
                "make one casual offhand remark about something Eris just noticed; mundane, light",
                "inner_diary: turn a recent noticing into a casual mundane one-liner, not analysis.",
            ),
        )
        out: list[_SeedCandidate] = []
        for key, kind, confidence, pressure, action, contract in specs:
            text = self._clean(voice.get(key) or "")
            if not text or not self._candidate_text_public(text):
                continue
            if len(text) > self._seed_max_len:
                text = text[: self._seed_max_len].rstrip()
            out.append(
                _SeedCandidate(
                    topic_seed=text,
                    public_seed=text,
                    evidence=(self._anchor_token("inner_diary", f"{key}:{text[:80]}"), f"inner_diary:{key}"),
                    confidence=self._clamp(confidence),
                    pressure=self._clamp(pressure),
                    root_source="inner_diary",
                    impulse_kind=kind,
                    action_opportunity=action,
                    llm_contract=contract,
                    public_anchor=True,
                    missing_screen=True,
                    reason=f"inner_diary:{key}",
                )
            )
        return tuple(out)

    def _inner_diary_voice(self, inner_diary: Any) -> dict[str, str]:
        """Rút giọng diary thành {muon_noi, tuong_lai, hien_tai}.

        Nhận cả dict giọng thô (đã có sẵn các key) lẫn dict đã render bởi
        InnerDiaryRenderer (parse theo tiêu đề section). Không có gì hợp lệ → {}.
        """

        if not isinstance(inner_diary, Mapping):
            return {}
        direct = {
            k: self._clean(inner_diary.get(k) or "")
            for k in ("muon_noi", "tuong_lai", "hien_tai", "ban_tam", "phan_tich")
        }
        direct = {k: v for k, v in direct.items() if v}
        if direct:
            return direct
        sections = inner_diary.get("sections")
        if not isinstance(sections, (list, tuple)):
            return {}
        out: dict[str, str] = {}
        for section in sections:
            if not isinstance(section, Mapping):
                continue
            key = _DIARY_TITLE_TO_KEY.get(self._clean(str(section.get("title") or "")).lower())
            if not key or key in out:
                continue
            lines = section.get("lines")
            joined = ""
            if isinstance(lines, (list, tuple)) and lines:
                joined = self._clean(" ".join(str(x) for x in lines if str(x or "").strip()))
            if not joined:
                items = section.get("items")
                if isinstance(items, (list, tuple)):
                    joined = self._clean(
                        " ".join(
                            str(item.get("text") if isinstance(item, Mapping) else item)
                            for item in items
                            if (item.get("text") if isinstance(item, Mapping) else item)
                        )
                    )
            if joined:
                out[key] = joined
        return out

    def _from_private_bias(
        self,
        private_mind_speech_bias: Any,
        private_mind_thought_pressure: float,
        private_mind_digest: Any,
    ) -> tuple[_SeedCandidate, ...]:
        if self._digest_has_invalid_json(private_mind_digest):
            return ()
        pressure = self._clamp(private_mind_thought_pressure)
        if pressure < 0.56:
            return ()
        seed = self._speech_bias_seed(private_mind_speech_bias)
        if not seed:
            return ()
        return (
            _SeedCandidate(
                topic_seed=seed,
                public_seed=seed,
                evidence=("private_mind_bias:public_style_seed",),
                confidence=min(0.64, max(0.42, pressure)),
                pressure=pressure,
                root_source="private_mind_bias",
                impulse_kind="inner_whim",
                action_opportunity="use as style pressure only; do not expose private analysis",
                llm_contract="private_mind_bias: style/pressure seed only; no raw private content.",
                public_anchor=False,
                missing_screen=True,
                reason="private_bias_public_summary",
            ),
        )

    def _to_impulse(self, candidate: _SeedCandidate, *, surface_kind: str) -> SurfaceImpulse:
        kind = candidate.impulse_kind or "inner_whim"
        return SurfaceImpulse(
            kind=kind,
            source="surface_seed_compiler",
            confidence=candidate.confidence,
            pressure=candidate.pressure,
            score=max(candidate.confidence, candidate.pressure),
            topic_seed=candidate.public_seed or candidate.topic_seed,
            speech_act="light_muse" if kind == "memory_resonance" else ("practical_help" if kind == "technical_help" else kind),
            family=f"compiled:{candidate.root_source}",
            evidence=tuple(dict.fromkeys((*candidate.evidence, f"surface_seed_compiler:{candidate.reason}")))[:10],
            reason=f"surface_seed_compiler:selected source={candidate.root_source} confidence={candidate.confidence:.2f} public_anchor={candidate.public_anchor}",
            focus_family=str(surface_kind or "surface"),
            body_action="low_pressure_presence",
            missing_evidence_ids=candidate.missing_screen,
            is_presence=False,
            should_surface=True,
            needs_external_evidence=False,
            vital_pressure=candidate.pressure,
            is_vital_pressure=candidate.pressure >= 0.55,
            root_source=candidate.root_source,
            action_opportunity=candidate.action_opportunity,
            llm_contract=candidate.llm_contract,
            raw={
                "compiler": "surface_seed_compiler",
                "reason": candidate.reason,
                "public_anchor": candidate.public_anchor,
            },
        )

    def _candidate_text_public(self, text: str) -> bool:
        cleaned = self._clean(text)
        if not cleaned:
            return False
        lowered = cleaned.lower()
        if any(marker in lowered for marker in _PRIVATE_MARKERS):
            return False
        if _JSONISH_RE.search(cleaned):
            return False
        if _GENERIC_TIMER_RE.match(cleaned):
            return False
        return True

    def _candidate_allowed(self, candidate: _SeedCandidate) -> bool:
        if not candidate.topic_seed or not candidate.public_seed:
            return False
        if candidate.confidence < 0.32 or candidate.pressure < 0.25:
            return False
        if self._looks_private(candidate.topic_seed) or self._looks_private(candidate.public_seed):
            return False
        if self._looks_timer_only(candidate.topic_seed):
            return False
        if candidate.root_source == "private_mind_bias" and not candidate.public_anchor and candidate.pressure < 0.62:
            return False
        return True

    def _candidate_context_compatible(
        self,
        candidate: _SeedCandidate,
        *,
        current_domain: str,
        surface_kind: str,
    ) -> bool:
        """Chặn seed cũ nói như hiện tại khi màn hình đang chứng minh chuyện khác.

        Đây là sửa ở nguồn, không phải filter câu cuối: private-life/memory có thể
        làm màu giọng, nhưng không được thắng current screen rồi bịa "bạn đang
        code" trong lúc fact hiện tại là YouTube/nhạc. Nếu không có current_domain
        rõ thì giữ hành vi cũ để Eris vẫn có đời sống riêng.
        """

        if not current_domain:
            return True
        if current_domain == "mixed":
            return True
        if candidate.root_source == "vision_fact":
            return True
        if str(surface_kind or "") not in {"re_engagement", "presence_maintenance", "surface", "micro_presence"}:
            return True
        candidate_domain = self._candidate_domain(candidate)
        if not candidate_domain or candidate_domain in {current_domain, "mixed"}:
            return True
        stale_sources = {
            "private_life",
            "private_mind_bias",
            "private_mind_surface",
            "memory_resonance",
            "inner_diary",
            "thought_stream",
            "daydream",
            "unresolved_memory",
            "memory",
        }
        if candidate.root_source in stale_sources or candidate.missing_screen:
            return False
        return True

    def _rank_key(self, candidate: _SeedCandidate) -> tuple[float, float, float, float]:
        anchor_bonus = 0.18 if candidate.public_anchor else 0.0
        # Grounded sources (what the character can actually observe now) should
        # not sit structurally below a generic private-life seed. Give them a
        # bonus and a grounded tie-break so an equal-confidence grounded seed
        # ranks at least as high as private_life.
        grounded_sources = {"vision_fact", "memory_resonance", "thought_stream"}
        source_bonus = {
            "vision_fact": 0.20,
            "memory_resonance": 0.12,
            "inner_diary": 0.12,
            "thought_stream": 0.08,
            "subconscious_synthesizer": 0.06,
            "private_mind_surface": 0.07,
        }.get(candidate.root_source, 0.0)
        grounded = 1.0 if candidate.root_source in grounded_sources else 0.0
        score = candidate.confidence * 0.52 + candidate.pressure * 0.48 + anchor_bonus + source_bonus
        return (score, grounded, candidate.confidence, candidate.pressure)

    def _candidate_domain(self, candidate: _SeedCandidate) -> str:
        return self._domain_from_text(
            " ".join(
                str(item or "")
                for item in (
                    candidate.topic_seed,
                    candidate.public_seed,
                    candidate.action_opportunity,
                    candidate.llm_contract,
                    *tuple(candidate.evidence or ()),
                )
            )
        )

    def _current_context_domain(self, *, snapshot: Any = None, presence_cue: Any = None) -> str:
        parts: list[str] = []
        for owner in (snapshot, presence_cue):
            if owner is None:
                continue
            for attr in (
                "active_window_kind",
                "focus_kind_hint",
                "focus_kind",
                "focus_summary",
                "activity_intent",
                "observer_focus",
                "intent",
                "semantic_family",
            ):
                value = getattr(owner, attr, "")
                if value:
                    parts.append(str(value))
            for attr in ("vision_facts", "recent_events", "evidence"):
                value = getattr(owner, attr, ())
                if isinstance(value, str):
                    parts.append(value)
                else:
                    try:
                        parts.extend(str(item) for item in tuple(value or ())[:8])
                    except Exception:
                        pass
        return self._domain_from_text(" ".join(parts), current_context=True)

    def _domain_from_text(self, text: str, *, current_context: bool = False) -> str:
        normalized = self._normalize_domain_text(text)
        if not normalized:
            return ""
        media_markers = (
            "youtube", "youtu be", "nhac", "music", "playlist", "video",
            "anime", "thumbnail", "media", "lofi", "song", "mv", "watch",
            "browsing", "gaming", "stream",
        )
        code_markers = (
            "code", "coding", "vscode", "visual studio code", "ide", "repo",
            "terminal", "pytest", "unit test", "test failure", "build",
            "compile", "debug", "bug", "stack trace", "python", "javascript",
            "typescript", "editor", "src/", "pull request",
        )
        media_score = sum(1 for marker in media_markers if marker in normalized)
        code_score = sum(1 for marker in code_markers if marker in normalized)
        if current_context:
            # OCR có thể chứa câu user "code đâu" trên chat trong khi màn hình là YouTube.
            # Current context cần đa số tín hiệu, không để một chữ "code" kéo lệch domain.
            if media_score >= max(2, code_score + 1):
                return "media"
            if code_score >= max(2, media_score + 1):
                return "code"
        if media_score and code_score:
            if media_score >= code_score + 1:
                return "media"
            if code_score >= media_score + 1:
                return "code"
            return "mixed"
        if media_score:
            return "media"
        if code_score:
            return "code"
        return ""

    @staticmethod
    def _normalize_domain_text(text: Any) -> str:
        lowered = str(text or "").lower()
        try:
            fixed = lowered.encode("latin1").decode("utf-8")
            if fixed:
                lowered = fixed
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        lowered = unicodedata.normalize("NFD", lowered)
        lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
        lowered = lowered.replace("đ", "d")
        lowered = re.sub(r"[^a-z0-9_./:+\-\s]", " ", lowered)
        return " ".join(lowered.split())

    def _private_impulse_has_anchor(self, impulse: SurfaceImpulse) -> bool:
        if bool(getattr(impulse, "needs_external_evidence", False)):
            return False
        if bool(getattr(impulse, "missing_evidence_ids", False)):
            return False
        raw = getattr(impulse, "raw", None)
        metadata = raw.get("metadata", {}) if isinstance(raw, Mapping) else {}
        if isinstance(metadata, Mapping):
            if bool(metadata.get("api_invalid_json")):
                return False
            if int(metadata.get("public_anchor_count", 0) or 0) > 0:
                return True
        haystack = " ".join(str(item or "") for item in tuple(getattr(impulse, "evidence", ()) or ())).lower()
        return any(marker in haystack for marker in ("dossier.user.", "user_chat", "vision_fact", "screen_fact", "runtime_event"))

    def _anchor_token(self, kind: str, value: Any) -> str:
        clean = self._clean(value)
        if not clean:
            clean = "surface_seed"
        safe = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", clean).strip("_").lower()
        if len(safe) > 48:
            digest = hashlib.sha1(clean.encode("utf-8", errors="ignore")).hexdigest()[:10]
            safe = f"{safe[:36].rstrip('_')}_{digest}"
        key = "vision_fact_id" if kind == "vision_fact" else f"{kind}_id"
        return f"{key}={safe or 'surface_seed'}"

    def _speech_bias_seed(self, bias: Any) -> str:
        if not isinstance(bias, Mapping):
            return ""
        values: list[str] = []
        for item in bias.values():
            if isinstance(item, Mapping):
                value = item.get("value")
                confidence = self._clamp(item.get("confidence", 0.0))
                if confidence < 0.50:
                    continue
                if isinstance(value, Mapping):
                    for key in ("preference", "style", "surface_seed", "summary"):
                        text = self._clean(value.get(key, ""))
                        if text:
                            values.append(text)
                else:
                    text = self._clean(value)
                    if text:
                        values.append(text)
        return values[0] if values else ""

    def _digest_has_invalid_json(self, digest: Any) -> bool:
        if not isinstance(digest, Mapping):
            return False
        text = str(digest).lower()
        return "invalid_json" in text

    def _no_seed_reason(self, candidates: list[_SeedCandidate]) -> str:
        if not candidates:
            return "no_public_anchor"
        if any(self._looks_private(item.topic_seed) for item in candidates):
            return "private_only"
        if any(self._looks_timer_only(item.topic_seed) for item in candidates):
            return "timer_only"
        return "low_pressure"

    def _is_specific_vision_fact(self, text: str) -> bool:
        lowered = text.lower()
        if any(marker in lowered for marker in _GENERIC_VISION):
            return False
        if self._looks_private(text) or self._looks_timer_only(text):
            return False
        return len(text) >= 10

    def _looks_private(self, text: Any) -> bool:
        lowered = self._clean(text).lower()
        if not lowered:
            return False
        if _JSONISH_RE.search(lowered):
            return True
        return any(marker in lowered for marker in _PRIVATE_MARKERS)

    def _looks_timer_only(self, text: Any) -> bool:
        cleaned = self._clean(text)
        if not cleaned:
            return True
        return bool(_GENERIC_TIMER_RE.match(cleaned))

    def _evidence_tuple(self, value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            values = (value,)
        else:
            try:
                values = tuple(value)
            except Exception:
                values = (value,)
        return tuple(dict.fromkeys(self._clean(item) for item in values if self._clean(item)))[:10]

    @staticmethod
    def _clean(value: Any, *, limit: int = 220) -> str:
        text = _SPACE_RE.sub(" ", str(value or "")).strip()
        return text[:limit].strip()

    @staticmethod
    def _clamp(value: Any) -> float:
        try:
            number = float(value)
        except Exception:
            number = 0.0
        if number != number:
            number = 0.0
        return max(0.0, min(1.0, number))


__all__ = ["CompiledSurfaceSeed", "SurfaceSeedCompiler"]
