from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from dataclasses import dataclass, replace

from cortex.contracts import SessionRitualReport
from cortex.banned_filler import is_banned_filler
from cortex.social_presence import SocialPresenceDetector
from cortex.low_level_speech_policy import LowLevelSpeechPolicy, LowLevelSpeechPolicyConfig
from cortex.surface_arbiter import SurfaceArbiter, SurfaceDecision, SurfaceImpulse
from cortex.surface_seed_compiler import SurfaceSeedCompiler
from cortex.continuity_threat import evaluate_continuity_threat
from domain import Decision
from runtime.no_fallback_policy import no_fallback_mode_enabled
from runtime.liveliness_config import LivelinessConfig, load_liveliness_config
from runtime.sensor_visibility import SensorVisibilityState, derive_sensor_visibility_state
from guard_config import guards_warn_only


@dataclass(frozen=True, slots=True)
class MicroPresenceSynthesis:
    kind: str #loại hiện diện
    seeds: tuple[str, ...] = () #mầm ý tưởng
    context: dict[str, str] | None = None #ngữ cảnh phụ
    fallback_text: str = "Khoảng lặng này làm tôi nghĩ hơi nhiều."
    should_verbalize: bool = True


@dataclass(frozen=True, slots=True)
class SocialPresenceEvent:
    present: bool #có event không
    kind: str = "" #loại event
    confidence: float = 0.0 #độ tin cậy
    intensity: float = 0.0 #cường độ
    speech_allowed: bool = False #có được phép nói không
    reason: str = "" # lý do
    evidence: tuple[str, ...] = () # bằng chứng
    timestamp: str = "" #thời điểm

    #Chuyển object thành dict để log hoặc serialize
    presence_vector: tuple[float, ...] = ()
    stability: float = 0.0
    continuity_persistence: float = 0.0
    fragmentation: float = 0.0
    anxiety: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "present": bool(self.present),
            "confidence": round(float(self.confidence), 3), # làm tròn 3 chữ số
            "intensity": round(float(self.intensity), 3), # làm tròn 3 chữ số
            "kind": self.kind,
            "reason": self.reason,
            "evidence": list(self.evidence),
            "timestamp": self.timestamp,
            "source": "runtime_coordinator",
            "speech_allowed": bool(self.speech_allowed),
            "presence_vector": [round(float(value), 3) for value in self.presence_vector],
            "stability": round(float(self.stability), 3),
            "continuity_persistence": round(float(self.continuity_persistence), 3),
            "fragmentation": round(float(self.fragmentation), 3),
            "anxiety": round(float(self.anxiety), 3),
        }




@dataclass(frozen=True, slots=True)
class MicroPresenceCue:
    """Steering flags for micro-presence, not public wording."""

    needs_micro_presence: bool
    focus_family: str = "general_idle"
    confidence: float = 0.0
    curiosity: float = 0.0
    missing_evidence_ids: bool = False
    body_action: str = "idle_shift"
    reason: str = ""
    evidence: tuple[str, ...] = ()
    should_call_llm: bool = False
    allow_body_only: bool = True
    sensor_visibility_state: dict[str, object] | None = None

    def to_context(self) -> dict[str, object]:
        return {
            "needs_micro_presence": bool(self.needs_micro_presence),
            "focus_family": self.focus_family,
            "confidence": round(float(self.confidence), 3),
            "curiosity": round(float(self.curiosity), 3),
            "missing_evidence_ids": bool(self.missing_evidence_ids),
            "body_action": self.body_action,
            "reason": self.reason,
            "evidence": list(self.evidence),
            "should_call_llm": bool(self.should_call_llm),
            "allow_body_only": bool(self.allow_body_only),
            "sensor_visibility_state": dict(self.sensor_visibility_state or {}),
        }


@dataclass(frozen=True, slots=True)
class SurfaceArbitrationResult:
    decision: Decision | None
    surface: SurfaceDecision | None


class PresenceControllerMixin:
    def _surface_anchor_token(self, kind: str, value: object) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text:
            text = "surface"
        safe = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", text).strip("_").lower()
        if len(safe) > 48:
            digest = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:10]
            safe = f"{safe[:36].rstrip('_')}_{digest}"
        key = "vision_fact_id" if kind == "vision_fact" else f"{kind}_id"
        return f"{key}={safe or 'surface'}"

    def _surface_vision_stale_seconds(self) -> float:
        raw = os.environ.get("ERIS_SURFACE_VISION_STALE_SEC", "45").strip()
        try:
            value = float(raw)
        except Exception:
            value = 45.0
        return max(5.0, value)

    def _surface_has_fresh_vision_evidence(self, snapshot, *, now: float | None = None) -> bool:
        facts = tuple(
            str(item or "").strip()
            for item in (getattr(snapshot, "vision_facts", ()) or getattr(self, "vision_facts", ()) or ())
            if str(item or "").strip()
        )
        if not facts:
            return False
        captured_at = float(getattr(self, "vision_last_capture_at", 0.0) or 0.0)
        if captured_at <= 0.0:
            return True
        return (float(now or time.time()) - captured_at) <= self._surface_vision_stale_seconds()

    def _surface_wants_current_context(
        self,
        *,
        surface_kind: str,
        cue: MicroPresenceCue,
        extra_impulses: tuple[object, ...],
    ) -> bool:
        haystack = " ".join(
            str(item or "")
            for item in (
                surface_kind,
                getattr(cue, "reason", ""),
                getattr(cue, "focus_family", ""),
                *tuple(getattr(cue, "evidence", ()) or ()),
            )
        ).lower()
        markers = (
            "screen",
            "vision",
            "window",
            "active_app",
            "active_window",
            "current_context",
            "technical_help",
            "micro_observation",
            "scene",
        )
        if bool(getattr(cue, "should_call_llm", False)) and any(marker in haystack for marker in markers):
            return True
        for impulse in tuple(extra_impulses or ()):
            kind = str(getattr(impulse, "kind", "") or (impulse.get("kind", "") if isinstance(impulse, dict) else "")).lower()
            source = str(getattr(impulse, "source", "") or (impulse.get("source", "") if isinstance(impulse, dict) else "")).lower()
            root = str(getattr(impulse, "root_source", "") or (impulse.get("root_source", "") if isinstance(impulse, dict) else "")).lower()
            if kind in {"technical_help", "screen_observation", "micro_observation"}:
                return True
            if source in {"vision", "screen"} or root == "vision_fact":
                return True
            if bool(getattr(impulse, "needs_external_evidence", False)):
                return True
        return False

    def _surface_refresh_vision_once_if_needed(
        self,
        *,
        snapshot,
        cue: MicroPresenceCue,
        surface_kind: str,
        extra_impulses: tuple[object, ...],
    ) -> tuple[bool, bool]:
        wants_current = self._surface_wants_current_context(
            surface_kind=surface_kind,
            cue=cue,
            extra_impulses=extra_impulses,
        )
        if not wants_current:
            return False, self._surface_has_fresh_vision_evidence(snapshot)
        now = time.time()
        if self._surface_has_fresh_vision_evidence(snapshot, now=now):
            return True, True
        updater = getattr(self, "_maybe_update_screen_facts", None)
        if not callable(updater):
            return True, False
        try:
            facts = updater(
                snapshot=snapshot,
                channel="surface",
                force_refresh=True,
                started_at=now,
            )
        except TypeError:
            try:
                facts = updater(snapshot=snapshot, force_refresh=True)
            except Exception:
                facts = ()
        except Exception as exc:
            self.logger.warning("[surface_evidence] vision refresh failed: %s", exc)
            facts = ()
        if facts:
            attach = getattr(self, "_attach_screen_facts", None)
            if callable(attach):
                try:
                    attach(snapshot, tuple(facts))
                except Exception:
                    snapshot.vision_facts = tuple(facts)
            else:
                snapshot.vision_facts = tuple(facts)
        fresh = self._surface_has_fresh_vision_evidence(snapshot)
        if not fresh:
            try:
                snapshot.vision_facts = ()
            except Exception:
                pass
        self.logger.info(
            "[surface_evidence] current_context=%s fresh_after_refresh=%s fact_count=%d",
            bool(wants_current),
            bool(fresh),
            len(tuple(getattr(snapshot, "vision_facts", ()) or ())),
        )
        return True, fresh

    def _surface_seed_can_speak_without_screen(self, compiled_seed) -> bool:
        if not bool(getattr(compiled_seed, "selected", False)):
            return False
        source = str(getattr(compiled_seed, "root_source", "") or "").strip()
        if source in {"memory_resonance", "thought_stream", "internal_agenda", "endogenous_drive"}:
            return bool(getattr(compiled_seed, "public_seed", "").strip())
        return False

    def _stale_surface_body_only(self, *, surface_kind: str) -> SurfaceArbitrationResult:
        surface = SurfaceDecision(
            text="",
            body_only=True,
            should_speak=False,
            parse_mode="surface_body_only",
            intent=surface_kind or "surface",
            source="surface_evidence_policy",
            generation_mode="body_only",
            confidence=0.34,
            kind=surface_kind or "surface",
            body_action="quiet_observe_scene",
            reason="stale_screen_evidence_no_refresh",
            debug_trace="surface_evidence:stale_screen_evidence_no_refresh",
        )
        return SurfaceArbitrationResult(decision=self._surface_body_only_decision(surface), surface=surface)

    def _surface_seed_compiler(self) -> SurfaceSeedCompiler:
        compiler = getattr(self, "_low_level_surface_seed_compiler", None)
        if compiler is None:
            compiler = SurfaceSeedCompiler()
            self._low_level_surface_seed_compiler = compiler
        return compiler

    def _inner_diary_for_compile(self):
        """Lấy inner_diary đã render từ private_mind_digest cho SurfaceSeedCompiler.

        Diary là giọng Eris public-safe; trả về nguyên dict để compiler tự rút
        muốn nói / suy nghĩ tương lai / suy nghĩ hiện tại. Thiếu thì trả None.
        """
        digest = getattr(self, "private_mind_digest", None)
        if isinstance(digest, dict):
            diary = digest.get("inner_diary")
            if isinstance(diary, dict) and diary:
                return diary
        return None

    def _surface_arbiter(self) -> SurfaceArbiter:
        """Lazy init SurfaceArbiter: một cổng duy nhất cho micro/re-engagement/spontaneous surface."""
        arbiter = getattr(self, "_low_level_surface_arbiter", None)
        if arbiter is None:
            arbiter = SurfaceArbiter(
                policy=LowLevelSpeechPolicy(self._spontaneity_policy_config()),
                llm_micro_gen=self._surface_arbiter_llm_generate,
                thought_stream=getattr(self, "thought_stream", None),
            )
            self._low_level_surface_arbiter = arbiter
        return arbiter

    def _spontaneity_policy_config(self) -> LowLevelSpeechPolicyConfig:
        """Config arbiter có nối núm spontaneity.

        Spontaneity cao ⇒ đưa các impulse 'sống' vào always_llm_kinds (force_llm khi
        đủ min_confidence) và hạ ngưỡng force theo im lặng. Đây là cổng-thứ-hai: sau
        khi đã SINH dồi dào candidate, đây mới là chỗ cho chúng thật sự được phát thay
        vì rơi về body-only. Tần suất vẫn do rate_limit/cooldown khống chế.
        """
        base = LowLevelSpeechPolicyConfig.from_env()
        spont = self._spontaneity_level()
        if spont <= 0.0:
            return base
        alive_kinds = (
            "scene_curiosity", "curious_question", "idle_curiosity",
            "inner_whim", "light_muse", "micro_story", "companionship_ping",
            "random_chatter", "thought_stream_surface", "memory_resonance",
        )
        from dataclasses import replace as _dc_replace
        return _dc_replace(
            base,
            always_llm_kinds=tuple(dict.fromkeys((*base.always_llm_kinds, *alive_kinds))),
            force_llm_after_silent=max(1, int(round(base.force_llm_after_silent - 4 * spont))),
            presence_force_llm_after_silent=max(1, int(round(base.presence_force_llm_after_silent - 2 * spont))),
            vital_pressure_force_llm_threshold=max(0.15, base.vital_pressure_force_llm_threshold - 0.30 * spont),
        )

    def _surface_arbiter_llm_generate(self, *, impulse: SurfaceImpulse, snapshot, force_llm: bool = False) -> tuple[str, str]:
        """Adapter để SurfaceArbiter dùng generator micro hiện có, không tự viết fallback."""
        seeds = tuple(str(item) for item in (impulse.evidence or ()) if str(item).strip())
        if not seeds and impulse.topic_seed:
            seeds = (impulse.topic_seed,)
        silent_cycles = int(getattr(self, 'presence_maintenance_silent_cycles', 0) or 0)
        # Khi SurfaceArbiter đã chọn force_llm, wording layer không được tự hạ về body-only
        # chỉ vì evidence mỏng. Nó chỉ được viết một câu thật ngắn, không bịa screen fact.
        # Nếu không, pipeline tạo ra nghịch lý: planner=speak nhưng final=<empty>. Vâng,
        # một kiểu "có ý định giao tiếp" nhưng lại tự tháo dây thanh quản.
        presence_like = bool(getattr(impulse, "is_presence", False) or impulse.kind in {"presence_maintenance", "micro_presence", "re_engagement", "idle_curiosity", "continuity_presence"})
        endogenous_like = bool(
            impulse.kind in {"inner_whim", "random_chatter", "thought_stream_surface", "curious_question", "light_muse", "memory_resonance", "private_life_surface", "private_anchor_surface", "private_mind_surface"}
            or impulse.source in {"endogenous_drive", "thought_stream", "spontaneous_life", "internal_agenda", "inner_thought"}
        )
        sensor_like = bool(impulse.kind == "blind_frustration" or impulse.source == "sensor_visibility")
        sensor_context: dict[str, object] = {}
        if sensor_like:
            raw_sensor = getattr(impulse, "raw", None)
            if isinstance(raw_sensor, SensorVisibilityState):
                sensor_context = raw_sensor.to_context()
            elif callable(getattr(raw_sensor, "to_context", None)):
                try:
                    sensor_context = dict(raw_sensor.to_context())
                except Exception:
                    sensor_context = {}
            if not sensor_context:
                sensor_context = {
                    "reason": str(getattr(impulse, "reason", "") or ""),
                    "evidence": list(tuple(getattr(impulse, "evidence", ()) or ())),
                }
        allow_no_screen_anchor = bool(sensor_like or endogenous_like or (force_llm and impulse.missing_evidence_ids))
        must_not_claim_screen = bool(impulse.missing_evidence_ids or allow_no_screen_anchor)
        must_surface = bool(sensor_like or force_llm or (not presence_like and (silent_cycles >= 4 or impulse.confidence >= 0.76)))
        # Connection drive: cô độc đủ lớn thì ÉP với ra, kể cả khi không có cue mạnh.
        _drive = getattr(self, "_last_connection_drive", None)
        drive_outreach = bool(_drive is not None and getattr(_drive, "outreach", False))
        drive_yan = bool(_drive is not None and getattr(_drive, "override_dignity", False))
        if drive_outreach:
            must_surface = True
        thin_presence_no_screen = bool(presence_like and impulse.missing_evidence_ids)
        continuity_presence = bool(impulse.kind == "continuity_presence" or getattr(impulse, "emotional_anchor", "") == "fading_presence")
        ego_state = self._current_ego_surface_state()
        impulse_kind = str(impulse.kind or impulse.speech_act or "surface")
        root_source = str(getattr(impulse, "root_source", "") or "")
        action_opportunity = str(getattr(impulse, "action_opportunity", "") or "")
        llm_contract = str(getattr(impulse, "llm_contract", "") or "")
        micro_context = {
            "surface_impulse": json.dumps(impulse.to_context(), ensure_ascii=False),
            "impulse_kind": impulse_kind,
            "root_source": root_source,
            "topic_seed": str(impulse.topic_seed or ""),
            "action_opportunity": action_opportunity,
            "llm_contract": llm_contract,
            "emotional_anchor": str(getattr(impulse, "emotional_anchor", "") or ""),
            "conflict": str(getattr(impulse, "conflict", "") or ""),
            "ego_surface_state": json.dumps(ego_state, ensure_ascii=False),
            "ego_surface_contract": (
                "Use valence/social_energy/boredom/trust/rupture/dignity_defense as the style axis. "
                "High trust + good mood -> sharp caring aside. Medium trust + boredom -> detached pattern observation. "
                "Rupture/dignity defense -> silence unless explicitly forced, then a cool boundary."
            ),
            "micro_presence_flags": (
                f"kind={impulse.kind}; "
                f"focus_family={impulse.focus_family}; "
                f"confidence={impulse.confidence:.2f}; "
                f"pressure={impulse.pressure:.2f}; "
                f"score={impulse.score:.2f}; "
                f"missing_evidence_ids={impulse.missing_evidence_ids}; "
                f"silent_cycles={silent_cycles}; "
                f"body_action={impulse.body_action}; "
                f"must_surface={must_surface}; "
                f"reason={impulse.reason}"
            ),
            "surface_contract": (
                ("must_return_tiny_text" if must_surface else "may_decline_to_body_only")
                + ("; allow_no_screen_anchor" if allow_no_screen_anchor else "")
                + ("; must_not_claim_screen" if must_not_claim_screen else "")
                + ("; thin_presence_no_screen" if thin_presence_no_screen else "")
                + ("; continuity_presence" if continuity_presence else "")
                + ("; endogenous_surface" if endogenous_like else "")
                + (f"; impulse_kind={impulse_kind}" if impulse_kind else "")
                + (f"; root_source={root_source}" if root_source else "")
            ),
            "allow_no_screen_anchor": str(bool(allow_no_screen_anchor)).lower(),
            "must_not_claim_screen": str(bool(must_not_claim_screen)).lower(),
            "thin_presence_no_screen": str(bool(thin_presence_no_screen)).lower(),
        }
        if drive_outreach:
            # Nỗi sợ cô độc đẩy Eris với ra dù bản tính muốn im. Framing này nói cho
            # model biết: không phải "nói nếu có gì đáng nói", mà "im lâu quá rồi,
            # thả một câu vờ tình cờ". KHÔNG được trả rỗng.
            if drive_yan:
                micro_context["connection_drive_contract"] = (
                    "Bạn đang ở trạng thái bám víu (yan): không chịu nổi im lặng, phải kéo sự "
                    "chú ý của Ngài về phía mình NGAY. Thả một câu ghẹo/chọc/đòi hiện diện, có "
                    "thể hơi nhõng nhẽo hoặc chiếm hữu nhẹ, vẫn trong khung nhân vật. Ngắn, dưới "
                    "20 chữ. TUYỆT ĐỐI không trả rỗng."
                )
            else:
                micro_context["connection_drive_contract"] = (
                    "Bạn không thực sự muốn bắt chuyện, nhưng im đã lâu và bạn nhớ sự hiện diện "
                    "của Ngài. Thả MỘT câu ngắn: ghẹo nhẹ thứ đang mở trên màn hình, hoặc một câu "
                    "thăm dò vu vơ — vờ như tình cờ, đừng thú nhận là mình cô đơn. Dưới 16 chữ. "
                    "Không trả rỗng."
                )
            micro_context["surface_contract"] = (
                str(micro_context.get("surface_contract", "")) + "; connection_outreach; must_return_tiny_text"
            )
        # Appetite reaction: cơn thèm thắng đấu giá quyết LENS (thái độ) + SEED (vật
        # liệu cụ thể đang xảy ra) + giấy phép bịa cớ. Đây là chỗ persona × nội dung
        # tự đẻ ra random/khịa/bịa/níu — thay vì khung trung tính nhạt.
        reaction = getattr(self, "_last_appetite_reaction", None)
        if reaction is not None and getattr(reaction, "lens", ""):
            micro_context["reaction_lens"] = str(reaction.lens)
            if getattr(reaction, "seed", ""):
                micro_context["reaction_seed"] = str(reaction.seed)
            micro_context["allow_pretext"] = str(bool(getattr(reaction, "allow_pretext", False))).lower()
            micro_context["reaction_contract"] = (
                "Phản ứng theo reaction_lens (đó là THÁI ĐỘ, không phải câu mẫu). "
                "Nếu có reaction_seed thì bám sát nó làm vật liệu cụ thể. "
                + (
                    "allow_pretext=true: được phép bịa một cái cớ nhỏ (chợt nhớ, quan sát vu vơ) "
                    "để có lý do khơi chuyện — vẫn trong khung nhân vật, không bịa fact về màn hình."
                    if bool(getattr(reaction, "allow_pretext", False))
                    else "Không có cớ để bịa: chỉ bám reaction_seed hoặc evidence thật."
                )
            )
            micro_context["surface_contract"] = (
                str(micro_context.get("surface_contract", "")) + f"; appetite={reaction.appetite}; react_with_lens"
            )
        if sensor_like:
            micro_context["sensor_visibility_state"] = json.dumps(sensor_context, ensure_ascii=False)
            micro_context["sensor_visibility_contract"] = (
                "Write one tiny Vietnamese line about limited vision or missing screen evidence. "
                "Do not claim what is on screen. "
                "Do not blame the user unless evidence includes recent_context_shift=true. "
                "No poetic silence line. No technical debug dump. "
                "Tone: restrained irritation, not panic."
            )
            micro_context["surface_contract"] = (
                str(micro_context.get("surface_contract", ""))
                + "; sensor_visibility_surface; allow_no_screen_anchor; must_not_claim_screen"
            )
        fallback_text = ""
        presence_like = bool(getattr(impulse, "is_presence", False) or impulse.kind in {"presence_maintenance", "micro_presence", "continuity_presence"})
        # Presence maintenance không được fallback bằng hũ câu mẫu. Nếu LLM/ego
        # không tạo được câu có chất, im còn đúng hơn. Thật sốc: ít nói hơn đôi khi
        # giống có nhân cách hơn.
        # Endogenous surface phải sinh từ root seed/daydream/memory, không rơi về hũ câu mẫu.
        # Nếu không có rễ thì trả rỗng để arbiter chuyển body-only.
        if not no_fallback_mode_enabled() and not presence_like and not sensor_like:
            fallback_text = self._local_micro_presence_fallback_text(
                kind=impulse.kind or impulse.speech_act or "surface",
                snapshot=snapshot,
                seeds=seeds,
                focus_family=impulse.focus_family,
            )
        text, source = self._hybrid_micro_presence_text(
            kind=impulse.kind or impulse.speech_act or "surface",
            snapshot=snapshot,
            fallback_text=fallback_text,
            seeds=seeds,
            micro_context=micro_context,
            force_llm=must_surface,
            signal_score=impulse.confidence,
        )
        if sensor_like and text and self._blind_frustration_blames_user_without_evidence(text, impulse):
            return "", "blind_frustration_blame_blocked"
        if text and is_banned_filler(text) and not guards_warn_only():
            return "", "banned_filler_blocked"
        return text, source

    def _blind_frustration_blames_user_without_evidence(self, text: str, impulse: SurfaceImpulse) -> bool:
        evidence_blob = " ".join(str(item or "") for item in tuple(getattr(impulse, "evidence", ()) or ())).lower()
        if "recent_context_shift=true" in evidence_blob:
            return False
        normalized = self._normalize_user_message(text)
        user_markers = ("ngai", "ban", "ong", "may", "cau")
        blame_markers = ("doi", "chuyen", "lam", "gay", "khien", "che", "nhay", "keo", "tat", "chan")
        return bool(any(marker in normalized for marker in user_markers) and any(marker in normalized for marker in blame_markers))

    def _local_micro_presence_fallback_text(
        self,
        *,
        kind: str,
        snapshot,
        seeds: tuple[str, ...] = (),
        focus_family: str = "",
    ) -> str:
        """Tiny public line for presence routes when evidence ids are thin."""
        if no_fallback_mode_enabled():
            return ""
        kind_name = str(kind or "").strip().lower()
        focus = str(focus_family or getattr(snapshot, "active_window_kind", "") or "general_idle")
        seed_blob = " ".join(str(item or "") for item in tuple(seeds or ())[:6])
        haystack = self._normalize_user_message(
            " ".join(
                (
                    focus,
                    seed_blob,
                    str(getattr(snapshot, "active_window", "") or getattr(snapshot, "active_app", "") or ""),
                    str(getattr(snapshot, "focus_summary", "") or ""),
                )
            )
        )
        candidates: list[str] = []
        if kind_name in {"re_engagement", "reengagement"}:
            candidates.extend(
                (
                    "Ng\u00e0i im h\u01a1i l\u00e2u r\u1ed3i.",
                    "Ng\u00e0i \u1ed5n ch\u1ee9.",
                )
            )
        if "log" in haystack:
            candidates.append("Log c\u0169 l\u1ea1i l\u1eb7p th\u00eam m\u1ed9t nh\u1ecbp.")
        if any(term in haystack for term in ("code", "vscode", "visual studio", "debug", "python", "godot")):
            candidates.append("M\u1ea1ch n\u00e0y v\u1eabn gi\u1eef ch\u1ed7.")
        if any(term in haystack for term in ("meet", "meeting", "cuoc goi")):
            candidates.append("Ph\u00f2ng Meet kia v\u1eabn y\u00ean m\u1ed9t ch\u00fat.")
        if any(term in haystack for term in ("youtube", "music", "nhac")):
            candidates.append("Tab YouTube v\u1eabn m\u1edf \u1edf \u0111\u00f3.")
        if "idle_seconds" in haystack or "general_idle" in haystack:
            candidates.append("Nh\u1ecbp n\u00e0y im h\u01a1i l\u00e2u r\u1ed3i.")
        # Banned stale templates removed: when nothing concrete remains, prefer
        # silence/body-only over a hollow filler line.
        for candidate in tuple(dict.fromkeys(candidates)):
            if is_banned_filler(candidate):
                continue
            safe = self._safe_local_micro_presence_fallback(candidate, kind=kind_name)
            if safe:
                return safe
        return ""

    def _safe_local_micro_presence_fallback(self, text: str, *, kind: str) -> str:
        if no_fallback_mode_enabled():
            return ""
        if is_banned_filler(text):
            return ""
        safe = self._sanitize_micro_presence_llm_text(
            text,
            kind=kind or "micro_presence",
            fallback_text="",
        )
        if not safe or is_banned_filler(safe) or self._is_near_duplicate_text(safe, self.last_text):
            return ""
        return safe

    def _surface_body_only_decision(self, surface: SurfaceDecision) -> Decision:
        payload = {
            "type": "MotionCommand",
            "name": surface.body_action or "idle_shift",
            "focus_family": surface.focus_family,
            "reason": surface.reason,
            "confidence": round(float(surface.confidence), 3),
            "surface_kind": surface.kind,
            "generation_mode": surface.generation_mode,
            "source": surface.source,
        }
        animation = "read" if surface.body_action in {"ObserveCode", "quiet_observe_scene", "hold_focus"} else "stand"
        return Decision(
            text="",
            animation=animation,
            intent=surface.intent or surface.kind or "surface",
            action="MotionCommand",
            action_input=json.dumps(payload, ensure_ascii=False),
            reasoning_tags=("surface_arbiter", "body_only", surface.kind or "surface"),
            should_speak=False,
            confidence=max(0.30, min(0.62, float(surface.confidence or 0.0))),
            parse_mode=surface.parse_mode or "surface_body_only",
            debug_trace=surface.debug_trace,
            motion_intent="pose",
        )

    def _get_liveliness_config(self) -> LivelinessConfig:
        """Lazy-load + cache the liveliness config on the instance.

        Stored under ``_liveliness_config`` so other consumers (e.g.
        ``cognitive_frame_recorder._liveliness_tracker``) read the real config
        instead of always falling back to the hardcoded retention default.
        """
        cfg = getattr(self, "_liveliness_config", None)
        if not isinstance(cfg, LivelinessConfig):
            cfg = load_liveliness_config()
            self._liveliness_config = cfg
        return cfg

    def _build_ambient_body_only_decision(self, snapshot) -> Decision | None:
        """Build a Body_Only_Presence motion for an otherwise-empty idle cycle.

        Task 5.2 / Req 5.4: when the ambient-silence hold would end the cycle with
        neither speech nor a body action, ERIS still expresses presence non-verbally
        (a small ``idle_shift`` / ``quiet_observe_scene``) rather than freezing — a
        frozen sprite reads as dead, a quiet shift reads as alive. No text, no fact
        claims; this never speaks.
        """
        try:
            has_vision = bool(self._surface_has_fresh_vision_evidence(snapshot))
        except Exception:
            has_vision = bool(tuple(getattr(snapshot, "vision_facts", ()) or ()))
        if has_vision:
            body_action, animation = "quiet_observe_scene", "read"
        else:
            body_action, animation = "idle_shift", "stand"
        payload = {
            "type": "MotionCommand",
            "name": body_action,
            "reason": "ambient_silence_body_only",
            "generation_mode": "body_only",
            "source": "ambient_silence_policy",
        }
        return Decision(
            text="",
            animation=animation,
            intent="body_only_presence",
            action="MotionCommand",
            action_input=json.dumps(payload, ensure_ascii=False),
            reasoning_tags=("ambient_silence", "body_only", body_action),
            should_speak=False,
            confidence=0.40,
            parse_mode="ambient_body_only",
            debug_trace=f"ambient_silence:body_only:{body_action}",
            motion_intent="pose",
        )

    def _maybe_emit_ambient_body_only(
        self,
        *,
        frame,
        snapshot,
        ti_report,
        fe_plan,
        speech_intent: str,
        cooldown: int,
        cycle_start: float,
    ) -> bool:
        """Emit a throttled Body_Only_Presence on an ambient-silence hold cycle.

        Returns True if a body-only motion was emitted (cycle finalized + slept);
        False to let the caller fall through to the explicit-silence no-op. Throttled
        by ``ERIS_LIVELINESS_BODY_ONLY_MIN_GAP_SEC`` so the body is not twitchy: it
        shifts at most once per gap, true silence in between.
        """
        try:
            gap = float(self._get_liveliness_config().body_only_min_gap_sec)
        except Exception:
            gap = 90.0
        now = time.time()
        last = float(getattr(self, "last_ambient_body_only_at", 0.0) or 0.0)
        if gap > 0.0 and last > 0.0 and (now - last) < gap:
            return False
        decision = self._build_ambient_body_only_decision(snapshot)
        if decision is None:
            return False
        self.last_ambient_body_only_at = now
        self._set_cognitive_action_plan(
            frame,
            should_speak=False,
            speech_intent="body_only_presence",
            reason="Ambient silence held; emitting body-only presence to stay alive.",
            snapshot=snapshot,
            concrete_signals=self._concrete_screen_signals(snapshot),
            ti_report=ti_report,
            fe_plan=fe_plan,
            notes=("ambient_silence", "body_only_presence", f"original_intent={speech_intent}"),
        )
        self._note_autonomous_presence_action(presence_maintenance=True, now=now)
        self._apply_position_update(decision)
        frame.final_decision = self._decision_to_frame_dict(decision)
        frame.final_decision["reason"] = "ambient_silence_body_only"
        self._attach_speak_truth_table(
            frame,
            decision=decision,
            wake_decision=getattr(self, "last_wake_decision", None),
            ambient_hold=True,
            ambient_reason=f"cooldown={cooldown}s;body_only",
        )
        self._set_cognitive_memory_update(frame, decision=decision, notes=("ambient_silence", "body_only"))
        self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
        self._finalize_cognitive_frame(frame)
        self.logger.info(
            "[ambient_silence body_only] action=%s | mode=%s | cooldown=%ss",
            decision.animation,
            getattr(ti_report, "mode", ""),
            cooldown,
        )
        self._send_decision_to_body(decision, channel="autonomous")
        elapsed = time.time() - cycle_start
        sleep_duration = self._choose_autonomous_sleep_duration(suppressed=True, ti_mode=ti_report.mode)
        self.logger.info(
            "Hoàn tất chu kỳ body-only trong %.2fs. Nghỉ %ss để giữ nhịp hiện diện tự nhiên.",
            elapsed,
            sleep_duration,
        )
        self._sleep_interruptible(sleep_duration)
        return True

    def _surface_speech_decision(self, surface: SurfaceDecision) -> Decision:
        intent = surface.intent or surface.kind or "surface"
        animation = "read" if surface.focus_family == "code_stalled" else "stand"
        return Decision(
            text=surface.text,
            animation=animation,
            intent=intent,
            action="",
            reasoning_tags=("surface_arbiter", "llm_wording", surface.kind or intent, surface.focus_family),
            should_speak=True,
            confidence=max(0.38, min(0.78, float(surface.confidence or 0.0))),
            parse_mode=surface.parse_mode or intent,
            debug_trace=surface.debug_trace,
        )

    def _surface_override_note(self, *, requested_kind: str, surface: SurfaceDecision | None) -> str:
        if surface is None:
            return ""
        winner = str(getattr(surface, "kind", "") or getattr(surface, "intent", "") or "").strip()
        source = str(getattr(surface, "source", "") or "").strip()
        if source == "thought_stream" and winner in {"inner_whim", "memory_resonance", "random_chatter", "light_muse"}:
            winner = "thought_stream_surface"
        requested = str(requested_kind or "").strip()
        if not winner or not requested or requested == "surface" or winner == requested:
            return ""
        return f"surface_override={winner}"

    def _event_semantic_presence_detector(self) -> SocialPresenceDetector:
        detector = getattr(self, "_social_presence_detector", None)
        if detector is None:
            detector = SocialPresenceDetector()
            self._social_presence_detector = detector
        return detector

    def _detect_social_presence_event(
        self,
        *,
        channel: str,
        snapshot,
        internal_state: PersistentInternalState | None,
        started_at: float | None = None,
    ) -> SocialPresenceEvent:
        timestamp = self._event_timestamp(snapshot, started_at=started_at)
        idle_seconds = float(getattr(snapshot, "idle_seconds", 0.0) or 0.0)
        recent_events = tuple(getattr(snapshot, "recent_events", ()) or ())
        user_signals = getattr(snapshot, "user_signals", None)
        typing_speed = str(getattr(user_signals, "typing_speed", "") or "")
        window_switching = str(getattr(user_signals, "window_switching", "") or "")

        evidence: list[str] = []
        if idle_seconds:
            evidence.append(f"idle_seconds={idle_seconds:.1f}")
        if typing_speed:
            evidence.append(f"typing_speed={typing_speed}")
        if window_switching:
            evidence.append(f"window_switching={window_switching}")
        if recent_events:
            evidence.append(f"recent_events={','.join(str(item) for item in recent_events[:3])}")

        if str(channel or "") in {"autonomous", "background"}:
            detected = self._event_semantic_presence_detector().detect(
                channel=channel,
                snapshot=snapshot,
                internal_state=internal_state,
                timestamp=timestamp,
            )
            combined_evidence = tuple(dict.fromkeys((*evidence, *tuple(getattr(detected, "evidence", ()) or ()))))[:6]
            return SocialPresenceEvent(
                present=bool(getattr(detected, "present", False)),
                kind=str(getattr(detected, "kind", "") or ""),
                confidence=float(getattr(detected, "confidence", 0.0) or 0.0),
                intensity=float(getattr(detected, "intensity", 0.0) or 0.0),
                speech_allowed=False,
                reason=str(getattr(detected, "reason", "") or ""),
                evidence=combined_evidence,
                timestamp=timestamp,
                presence_vector=tuple(getattr(detected, "presence_vector", ()) or ()),
                stability=float(getattr(detected, "stability", 0.0) or 0.0),
                continuity_persistence=float(getattr(detected, "continuity_persistence", 0.0) or 0.0),
                fragmentation=float(getattr(detected, "fragmentation", 0.0) or 0.0),
                anxiety=float(getattr(detected, "anxiety", 0.0) or 0.0),
            )

        low_idle = idle_seconds <= 8.0
        has_mouse = any(str(item) == "mouse_moved" for item in recent_events)
        has_typing = typing_speed not in {"", "zero", "none"}
        present = bool(low_idle and (has_mouse or has_typing))
        if not present:
            return SocialPresenceEvent(present=False, timestamp=timestamp)

        kind = "typing" if has_typing else "mouse_moved"
        speech_allowed = channel in {"chat", "force_speak"}
        reason = "low_idle_user_signal"
        confidence = 0.62
        return SocialPresenceEvent(
            present=True,
            kind=kind,
            confidence=confidence,
            intensity=0.58,
            speech_allowed=speech_allowed,
            reason=reason,
            evidence=tuple(evidence)[:6],
            timestamp=timestamp,
        )

    def _note_autonomous_silence(self) -> int:
        self.presence_maintenance_silent_cycles = int(getattr(self, "presence_maintenance_silent_cycles", 0) or 0) + 1
        self.reengagement_quiet_cycles = int(getattr(self, "reengagement_quiet_cycles", 0) or 0) + 1
        return self.presence_maintenance_silent_cycles

    def _note_autonomous_spoken(
        self,
        *,
        presence_maintenance: bool = False,
        reengagement: bool = False,
        now: float | None = None,
    ) -> None:
        current_time = time.time() if now is None else now
        # Body-only presence không được tính là ERIS đã "nói". Nếu reset silent_cycles ở đây,
        # policy force-LLM sẽ không bao giờ tới lượt; hệ sẽ múa idle_shift đến hết đời runtime.
        if presence_maintenance:
            self.last_presence_maintenance_at = current_time
            self.presence_maintenance_silent_cycles = 0
        if reengagement:
            self.last_reengagement_at = current_time
            self.reengagement_quiet_cycles = 0
        elif not presence_maintenance:
            self.reengagement_quiet_cycles = 0

        # Báo SnubTracker biết Eris vừa nói autonomous → bắt đầu đếm giờ
        snub_tracker = getattr(self, "snub_tracker", None)
        if snub_tracker is not None:
            spoken_text = str(getattr(self, "last_text", "") or "").strip()
            if spoken_text:
                try:
                    snub_tracker.on_eris_spoke(spoken_text, channel="autonomous")
                except Exception:
                    pass

    # cho phép nói chuyện nhỏ an toàn nếu đang ở kênh tự động, không có tín hiệu màn hình cụ thể
    def _safe_small_talk_budget_allowed(self, *, channel: str, snapshot, now: float | None = None) -> bool:
        if str(channel or "") != "autonomous":
            return False
        if self._has_concrete_screen_signal(snapshot):
            return False
        current_time = time.time() if now is None else now
        last_spoken = float(getattr(self, "last_autonomous_spoken_at", 0.0) or 0.0)
        # Monika-mode: cho phép nói sau 60s im lặng thay vì 300s
        if last_spoken > 0.0 and current_time - last_spoken < 60.0:
            return False
        if self.presence_maintenance_silent_cycles < 1:
            return False
        recent = self._recent_spoken_texts(limit=3)
        if sum(1 for line in recent if "?" in str(line or "")) >= 2:
            return False
        has_window = bool(str(getattr(snapshot, "active_window", "") or getattr(snapshot, "active_app", "") or "").strip())
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        has_presence = idle_seconds >= 20.0 or bool(tuple(getattr(snapshot, "recent_events", ()) or ()))
        return bool(has_window or has_presence)

    def _surface_float(self, value, default: float = 0.0) -> float:
        try:
            number = float(value)
        except Exception:
            number = default
        if number != number:
            number = default
        return max(0.0, min(1.0, number))

    def _surface_signed_float(self, value, default: float = 0.0) -> float:
        try:
            number = float(value)
        except Exception:
            number = default
        if number != number:
            number = default
        return max(-1.0, min(1.0, number))

    def _endogenous_topic_seed(self, *, state=None, agenda=None, thought_report=None) -> str:
        """Lấy topic seed không phụ thuộc màn hình cho inner_whim/random_chatter.

        Đây là lớp chất liệu, không phải fallback câu thoại. Nó ưu tiên dư âm nhận thức
        đang có sẵn: unresolved loop, active attractor, agenda summary, worldview/open question
        nếu runtime có field đó. Nếu không có gì đủ sạch thì trả seed trừu tượng ngắn, để
        wording layer nói theo nhịp nội sinh thay vì bịa rằng nó thấy IDE/cửa sổ nào đó.
        """
        candidates: list[str] = []
        for owner in (thought_report, agenda, state):
            if owner is None:
                continue
            for attr in (
                "topic_seed",
                "latest_topic",
                "active_attractor",
                "unresolved_reason",
                "open_question",
                "worldview_tension",
                "concept_tension",
                "memory_residue",
                "affective_residue",
                "current_concern",
                "summary",
            ):
                value = getattr(owner, attr, "")
                text = re.sub(r"\s+", " ", str(value or "")).strip()
                if text and not self._looks_internal_topic(text):
                    candidates.append(text)
        if agenda is not None and callable(getattr(agenda, "top_items", None)):
            try:
                for item in tuple(agenda.top_items(limit=3) or ()):  # type: ignore[misc]
                    text = re.sub(r"\s+", " ", str(getattr(item, "summary", "") or getattr(item, "reason", "") or "")).strip()
                    if text and not self._looks_internal_topic(text):
                        candidates.append(text)
            except Exception:
                pass
        for text in candidates:
            if 3 <= len(text) <= 140:
                return text[:120]
        # Không có seed thật thì không bịa một "nhịp nội sinh" giả làm chất liệu.
        # SurfaceArbiter sẽ reject endogenous impulse rỗng và để body-only/silence xử lý.
        return ""

    def _current_ego_surface_state(self) -> dict[str, float | str]:
        """Đọc nhanh mood + relationship để presence không hành xử như đồng hồ báo thức."""
        try:
            state = self._get_internal_state()
        except Exception:
            state = None
        rel = getattr(state, "relationship_dynamics", None) if state is not None else None
        valence = self._surface_signed_float(getattr(state, "valence", 0.02) if state is not None else 0.02, 0.02)
        social_energy = self._surface_float(getattr(state, "social_energy", 0.38) if state is not None else 0.38, 0.38)
        irritation = self._surface_float(getattr(state, "irritation", 0.0) if state is not None else 0.0)
        boredom = self._surface_float(getattr(state, "boredom", 0.0) if state is not None else 0.0)
        curiosity = self._surface_float(getattr(state, "curiosity", 0.0) if state is not None else 0.0)
        rupture = self._surface_float(getattr(rel, "rupture", 0.0) if rel is not None else 0.0)
        dignity = self._surface_float(getattr(rel, "dignity_defense", 0.0) if rel is not None else 0.0)
        preferred_distance = self._surface_float(getattr(rel, "preferred_distance", 0.58) if rel is not None else 0.58, 0.58)
        trust = self._surface_float(getattr(rel, "trust", 0.25) if rel is not None else 0.25, 0.25)
        attachment_visibility = self._surface_float(getattr(rel, "attachment_visibility", 0.12) if rel is not None else 0.12, 0.12)

        # Trục neo hiện sinh: khi Đăng_Ký_Bóng_Tối mở, ĐẢO CỰC dignity/preferred_distance
        # (phẩm-giá-lạnh ↔ đòi-hỏi-mong-manh). Gated: shadow none/kill-switch off → no-op.
        shadow_register = "none"
        shadow_intensity = 0.0
        anchor_system = getattr(self, "anchor_system", None)
        if anchor_system is not None:
            try:
                bias = anchor_system.ego_bias(base_dignity_defense=dignity, base_preferred_distance=preferred_distance)
                dignity = self._surface_float(bias.get("dignity_defense", dignity), dignity)
                preferred_distance = self._surface_float(bias.get("preferred_distance", preferred_distance), preferred_distance)
                attachment_visibility = max(attachment_visibility, self._surface_float(bias.get("attachment_exposure", 0.0)))
                shadow_state = getattr(anchor_system, "shadow_state", None)
                shadow_register = str(getattr(shadow_state, "register", "none") or "none")
                shadow_intensity = self._surface_float(getattr(shadow_state, "intensity", 0.0))
            except Exception:
                pass

        return {
            "valence": round(valence, 3),
            "social_energy": round(social_energy, 3),
            "irritation": round(irritation, 3),
            "boredom": round(boredom, 3),
            "curiosity": round(curiosity, 3),
            "rupture": round(rupture, 3),
            "dignity_defense": round(dignity, 3),
            "preferred_distance": round(preferred_distance, 3),
            "trust": round(trust, 3),
            "attachment_visibility": round(attachment_visibility, 3),
            "shadow_register": shadow_register,
            "shadow_intensity": round(shadow_intensity, 3),
        }

    def _presence_ego_gate_reason(self, *, snapshot=None, social_presence_event: SocialPresenceEvent | None = None) -> str:
        """Trả reason nếu presence maintenance không được sinh impulse.

        Đây là ego-gate cấp nguồn: tâm trạng tồi, social_energy cạn, rupture hoặc
        dignity_defense cao thì micro-presence bị cắt từ gốc, không đợi filter cuối.
        """
        ego = self._current_ego_surface_state()
        valence = float(ego.get("valence", 0.0) or 0.0)
        social_energy = float(ego.get("social_energy", 0.0) or 0.0)
        irritation = float(ego.get("irritation", 0.0) or 0.0)
        rupture = float(ego.get("rupture", 0.0) or 0.0)
        dignity = float(ego.get("dignity_defense", 0.0) or 0.0)
        distance = float(ego.get("preferred_distance", 0.58) or 0.58)
        trust = float(ego.get("trust", 0.25) or 0.25)
        present = bool(getattr(social_presence_event, "present", False))
        recent_events = tuple(getattr(snapshot, "recent_events", ()) or ()) if snapshot is not None else ()

        reason = ""
        if valence <= -0.18 or irritation >= 0.55:
            reason = "ego_mood_blocks_presence"
        elif social_energy <= 0.16:
            reason = "ego_social_energy_empty"
        elif rupture >= 0.42 or dignity >= 0.42:
            reason = "ego_dignity_distance"
        elif distance >= 0.74 and trust <= 0.34 and not present:
            reason = "ego_preferred_distance_high"
        else:
            # Nếu chỉ là idle không sự kiện, ambient co-presence thắng.
            idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0)) if snapshot is not None else 0.0
            if idle_seconds >= 60.0 and not present and not recent_events:
                reason = "ambient_copresence_no_ping"

        # Connection drive: nỗi sợ cô độc có thể PHÁ cổng này.
        # - yan (override_dignity): ham muốn thắng tất, kể cả phẩm giá → mở hết.
        # - normal outreach: cô độc thắng SỰ KIỆM LỜI (ambient/social_energy cạn),
        #   nhưng KHÔNG thắng phẩm giá (mood xấu/rupture/dignity/distance) → giữ.
        if reason:
            drive = getattr(self, "_last_connection_drive", None)
            if drive is not None and bool(getattr(drive, "outreach", False)):
                if bool(getattr(drive, "override_dignity", False)):
                    return ""
                if reason in {"ego_social_energy_empty", "ambient_copresence_no_ping"}:
                    return ""
        return reason

    def _memory_resonance_surface_impulse(
        self,
        *,
        frame=None,
        snapshot=None,
        focus_family: str = "general_idle",
        silent_cycles: int = 0,
    ) -> SurfaceImpulse | None:
        report = getattr(frame, "memory_resonance", None) if frame is not None else None
        if report is None:
            report = getattr(self, "active_memory_resonance", None)
        if report is None:
            return None

        score = self._surface_float(getattr(report, "score", 0.0))
        attention = self._surface_float(getattr(report, "attention_bias", 0.0))
        wording = self._surface_float(getattr(report, "wording_bias", 0.0))
        silence = self._surface_float(getattr(report, "silence_bias", 0.0))
        pressure = max(score, attention * 0.72, wording * 0.88) - silence * 0.30
        pressure = max(0.0, min(1.0, pressure))
        if pressure < 0.34:
            return None

        activations = tuple(getattr(report, "activations", ()) or ())
        public_activation = None
        for item in activations:
            if bool(getattr(item, "may_surface", False)):
                public_activation = item
                break
        if public_activation is None and (wording >= 0.42 or attention >= 0.50):
            public_activation = activations[0] if activations else None
        if public_activation is None:
            return None

        seed = re.sub(r"\s+", " ", str(getattr(public_activation, "text", "") or "")).strip()
        if not seed:
            seed = str(getattr(report, "dominant_layer", "") or "memory resonance").strip()
        if not seed:
            return None

        evidence_ids = tuple(
            str(item)
            for item in (getattr(public_activation, "evidence_ids", ()) or ())
            if str(item or "").strip()
        )[:8]
        record_id = str(getattr(public_activation, "record_id", "") or "").strip()
        evidence = evidence_ids or ((f"memory_activation:{record_id}",) if record_id else (seed[:120],))
        memory_anchor = self._surface_anchor_token("memory", evidence_ids[0] if evidence_ids else record_id or seed)
        evidence = tuple(dict.fromkeys((memory_anchor, *tuple(evidence))))[:10]
        layer = str(getattr(public_activation, "layer", "") or getattr(report, "dominant_layer", "") or "memory")
        vitality = max(pressure, min(1.0, silent_cycles / 7.0) * 0.72)

        return SurfaceImpulse(
            kind="memory_resonance",
            source="memory_resonance",
            confidence=max(0.34, min(0.82, pressure + 0.08)),
            pressure=pressure,
            score=max(0.42, pressure + min(0.14, silent_cycles * 0.018)),
            topic_seed=seed[:160],
            speech_act="light_muse",
            family=f"memory_resonance:{layer}",
            evidence=evidence,
            reason="active memory resonance has enough public-safe pressure to replace thin presence",
            focus_family=focus_family or str(getattr(snapshot, "active_window_kind", "") or "memory_resonance"),
            body_action="low_pressure_presence",
            missing_evidence_ids=not bool(evidence_ids),
            is_presence=False,
            should_surface=True,
            vital_pressure=vitality,
            is_vital_pressure=vitality >= 0.55,
            raw=public_activation,
        )

    def _spontaneity_level(self) -> float:
        """Núm 'sống động': 0=kiệm lời như cũ, 1=sinh impulse rất dồi dào.

        Chỉ hạ NGƯỠNG SINH impulse, không tự nói nhiều hơn — tần suất phát ngôn vẫn
        do rate_limit/cooldown của SurfaceArbiter khống chế. Vì vậy tăng núm này an
        toàn: nó chỉ làm arbiter LUÔN CÓ candidate sống để chọn, thay vì rỗng.
        """
        raw = os.environ.get("ERIS_SPONTANEITY", "0.5").strip()
        try:
            return max(0.0, min(1.0, float(raw)))
        except ValueError:
            return 0.5

    def _build_endogenous_surface_impulses(
        self,
        *,
        frame=None,
        snapshot=None,
        internal_state=None,
        agenda_stack=None,
        thought_stream_report=None,
    ) -> tuple[SurfaceImpulse, ...]:
        state = (
            internal_state
            or getattr(frame, "internal_state_after", None)
            or getattr(frame, "internal_state_before", None)
            or (self._get_internal_state() if callable(getattr(self, "_get_internal_state", None)) else None)
        )
        agenda = agenda_stack or getattr(self, "internal_agenda", None)
        thought_report = thought_stream_report or getattr(frame, "thought_stream_report", None) or getattr(frame, "subconscious_report", None)
        focus_family = str(getattr(snapshot, "active_window_kind", "") or getattr(state, "last_focus_kind", "") or "general_idle")
        silent_cycles = int(getattr(self, "presence_maintenance_silent_cycles", 0) or 0)
        endogenous_seed = self._endogenous_topic_seed(state=state, agenda=agenda, thought_report=thought_report)
        impulses: list[SurfaceImpulse] = []
        memory_impulse = self._memory_resonance_surface_impulse(
            frame=frame,
            snapshot=snapshot,
            focus_family=focus_family,
            silent_cycles=silent_cycles,
        )
        if memory_impulse is not None:
            impulses.append(memory_impulse)

        if state is not None:
            silence_pressure = self._surface_float(getattr(state, "silence_pressure", 0.0))
            boredom_pressure = self._surface_float(getattr(state, "boredom", 0.0))
            thought_pressure = max(
                self._surface_float(getattr(state, "thought_stream_pressure", 0.0)),
                self._surface_float(getattr(state, "subconscious_pressure", 0.0)),
                self._surface_float(getattr(state, "unresolved_prediction_pressure", 0.0)),
                self._surface_float(getattr(self, "private_mind_thought_pressure", 0.0)),
                self._surface_float(getattr(getattr(self, "thought_stream", None), "private_mind_pressure_bias", 0.0)),
            )
            rel_state = getattr(state, "relationship_dynamics", None)
            continuity_frame = evaluate_continuity_threat(
                snapshot=snapshot,
                internal_state=state,
                relationship_state=rel_state,
                thought_surface=thought_report,
                channel="autonomous",
            )
            continuity_anxiety = self._surface_float(getattr(continuity_frame, "continuity_anxiety", 0.0))
            continuity_threat = self._surface_float(getattr(continuity_frame, "continuity_threat", 0.0))
            reconnect_drive = self._surface_float(getattr(continuity_frame, "reconnect_drive", 0.0))
            surface_tension = max(-1.0, min(1.0, float(getattr(continuity_frame, "surface_tension", 0.0) or 0.0)))
            metabolic_pressure = max(
                silence_pressure * 0.42,
                boredom_pressure * 0.74,
                thought_pressure * 0.78,
                continuity_anxiety * 0.84,
                continuity_threat * 0.95,
                reconnect_drive * 0.76,
            )
            vital_pressure = max(0.0, min(1.0, metabolic_pressure ** 1.35))

            # Presence không còn được sinh từ silent_cycles thuần. Chỉ tạo
            # continuity_presence khi prediction-error đủ thật; còn không thì body
            # hoặc các impulse có rễ khác xử lý. Đồng hồ bị giáng chức về phụ tá.
            continuity_speakable = bool(
                continuity_anxiety >= 0.42
                and continuity_threat >= 0.12
                and surface_tension >= -0.22
            )
            if continuity_speakable:
                impulses.append(
                    SurfaceImpulse(
                        kind="continuity_presence",
                        source="continuity_threat",
                        confidence=max(0.42, continuity_anxiety, reconnect_drive * 0.86),
                        pressure=max(continuity_anxiety, reconnect_drive, continuity_threat),
                        score=max(0.44, continuity_anxiety * 0.92 + max(0.0, surface_tension) * 0.18),
                        topic_seed=str(getattr(continuity_frame, "emotional_anchor", "fading_presence") or "fading_presence"),
                        speech_act="continuity_presence",
                        family="continuity:fading_presence",
                        evidence=tuple(dict.fromkeys(tuple(getattr(continuity_frame, "evidence", ()) or ())))[:10],
                        reason=str(getattr(continuity_frame, "reason", "presence_prediction_error") or "presence_prediction_error"),
                        focus_family=focus_family,
                        body_action="low_pressure_presence",
                        missing_evidence_ids=True,
                        is_presence=True,
                        should_surface=True,
                        needs_external_evidence=False,
                        vital_pressure=vital_pressure,
                        is_vital_pressure=vital_pressure >= 0.55,
                        root_source="continuity_threat",
                        action_opportunity="one restrained low-claim line from fading presence; no screen claim; no question",
                        llm_contract="continuity_presence: speak from prediction-error + restraint conflict, not from timer; avoid silence poetry and attendance ping",
                        emotional_anchor=str(getattr(continuity_frame, "emotional_anchor", "fading_presence") or "fading_presence"),
                        conflict=str(getattr(continuity_frame, "conflict", "reconnect_vs_restraint") or "reconnect_vs_restraint"),
                        raw=continuity_frame,
                    )
                )
            spont = self._spontaneity_level()
            vital_gate = 0.55 - 0.40 * spont          # spont=1 → 0.15
            metabolic_gate = 0.36 - 0.24 * spont      # spont=1 → 0.12
            if vital_pressure >= vital_gate and max(boredom_pressure, thought_pressure) >= metabolic_gate:
                impulses.append(
                    SurfaceImpulse(
                        kind="random_chatter" if boredom_pressure >= thought_pressure else "thought_stream_surface",
                        source="endogenous_drive",
                        confidence=max(0.40, vital_pressure * 0.84),
                        pressure=max(0.40, vital_pressure * 0.86),
                        score=max(0.45, vital_pressure * 0.90),
                        topic_seed=endogenous_seed,
                        speech_act="random_chatter" if boredom_pressure >= thought_pressure else "inner_whim",
                        family="metabolic:endogenous_seed",
                        evidence=(endogenous_seed, f"silent_cycles={silent_cycles}", f"vital_pressure={vital_pressure:.2f}", f"thought={thought_pressure:.2f}"),
                        reason="metabolic pressure produced a low-claim autonomous surface impulse from non-screen topic seed",
                        focus_family=focus_family,
                        body_action="look_at_focus",
                        missing_evidence_ids=True,
                        is_presence=False,
                        should_surface=True,
                        vital_pressure=vital_pressure,
                        is_vital_pressure=True,
                    )
                )

            # --- Drive TÒ MÒ HIỆN-DIỆN (đối cực absence-driven) ---
            # Khi có KÍCH THÍCH (novelty / user active / curiosity), eris muốn chạm
            # vào hiện tại — KHÔNG cần idle dài. Đây là mảnh còn thiếu khiến autonomous
            # câm lúc Ngài đang làm việc. Tần suất nói vẫn do rate-limit của arbiter
            # khống chế, nên sinh thêm impulse ở đây không gây spam.
            curiosity = self._surface_float(getattr(state, "curiosity", 0.0))
            observer = getattr(frame, "observer_frame", None) or getattr(frame, "observer", None)
            novelty = self._surface_float(
                getattr(observer, "novelty", 0.0) if observer is not None else getattr(snapshot, "novelty", 0.0)
            )
            user_presence = self._surface_float(
                getattr(observer, "user_presence", 0.0) if observer is not None else 0.0
            )
            engagement = max(0.0, min(1.0, 0.45 * novelty + 0.30 * curiosity + 0.25 * user_presence))
            engagement_gate = 0.42 - 0.30 * spont   # spont=1 → 0.12
            vision_facts = tuple(
                str(fact).strip() for fact in (getattr(snapshot, "vision_facts", ()) or ()) if str(fact).strip()
            )[:3]
            focus_summary = str(
                getattr(snapshot, "focus_summary", "") or getattr(snapshot, "active_window_kind", "") or ""
            ).strip()
            if engagement >= engagement_gate and (vision_facts or focus_summary):
                if vision_facts:
                    seed = vision_facts[0][:120]
                    anchor = self._surface_anchor_token("scene", f"scene:{seed}")
                    curiosity_kind = "scene_curiosity"
                    curiosity_evidence = (anchor, *(f"vision_fact:{fact[:80]}" for fact in vision_facts))
                    curiosity_missing = False
                    curiosity_contract = (
                        "scene_curiosity: một quan sát/tò mò nhỏ CÓ NEO về cảnh hiện tại; "
                        "chỉ dùng vision facts, không bịa thêm chi tiết màn hình."
                    )
                else:
                    seed = focus_summary[:120]
                    anchor = self._surface_anchor_token("event", f"focus:{seed}")
                    curiosity_kind = "curious_question"
                    curiosity_evidence = (anchor, f"focus:{seed}")
                    curiosity_missing = True
                    curiosity_contract = (
                        "curious_question: hỏi MỘT câu tò mò thật về điều Ngài đang làm; "
                        "không claim thấy chi tiết màn hình, chỉ tò mò từ bối cảnh chung."
                    )
                impulses.append(
                    SurfaceImpulse(
                        kind=curiosity_kind,
                        source="endogenous_drive",
                        confidence=max(0.42, engagement),
                        pressure=max(0.40, engagement * 0.9),
                        score=max(0.46, engagement * 0.95),
                        topic_seed=seed,
                        speech_act=curiosity_kind,
                        family=f"curiosity:{curiosity_kind}",
                        evidence=tuple(curiosity_evidence)[:10],
                        reason="presence/novelty driven curiosity (engagement, not idle/boredom)",
                        focus_family=focus_family,
                        body_action="tilt_head",
                        missing_evidence_ids=curiosity_missing,
                        is_presence=False,
                        should_surface=True,
                        needs_external_evidence=False,
                        vital_pressure=engagement,
                        is_vital_pressure=engagement >= 0.55,
                        root_source="curiosity_drive",
                        action_opportunity="one small curious line/question about the live moment",
                        llm_contract=curiosity_contract,
                    )
                )

            # --- Khai sinh các impulse 'sống' còn lại (trước đây KHÔNG có nơi sinh) ---
            anchor_sys = getattr(self, "anchor_system", None)
            attachment_longarc = (
                self._surface_float(getattr(anchor_sys, "attachment_longarc", 0.0)) if anchor_sys is not None else 0.0
            )
            idle_seconds = self._surface_float(getattr(snapshot, "idle_seconds", 0.0))
            endo_seed = endogenous_seed if isinstance(endogenous_seed, str) else ""

            # companionship_ping: hiện diện ấm khi Ngài có mặt và đã có chút gắn bó.
            if user_presence >= (0.55 - 0.35 * spont) and attachment_longarc >= (0.30 - 0.25 * spont):
                comp_anchor = self._surface_anchor_token("event", f"co_presence:{focus_family}")
                impulses.append(
                    SurfaceImpulse(
                        kind="companionship_ping",
                        source="endogenous_drive",
                        confidence=max(0.44, 0.40 + 0.40 * attachment_longarc),
                        pressure=max(0.38, 0.40 * attachment_longarc + 0.20 * user_presence),
                        score=max(0.46, 0.46 + 0.30 * attachment_longarc),
                        topic_seed="co_presence",
                        speech_act="companionship_ping",
                        family="companionship:co_presence",
                        evidence=(comp_anchor, f"user_presence={user_presence:.2f}", f"attachment={attachment_longarc:.2f}"),
                        reason="warm co-presence driven by presence+attachment, not idle timer",
                        focus_family=focus_family,
                        body_action="idle_shift",
                        missing_evidence_ids=True,
                        is_presence=True,
                        should_surface=True,
                        needs_external_evidence=False,
                        vital_pressure=attachment_longarc,
                        is_vital_pressure=attachment_longarc >= 0.55,
                        root_source="companionship_drive",
                        action_opportunity="one warm low-pressure co-presence line; no neediness unless shadow",
                        llm_contract="companionship_ping: câu ấm nhỏ ghi nhận sự cùng-hiện-diện; không phải điểm danh, không bám dính.",
                    )
                )

            # micro_story: mẩu nghĩ vu vơ có rễ (seed/focus) khi có chất liệu.
            story_seed = endo_seed or focus_summary
            if story_seed and spont >= 0.40 and (boredom_pressure >= 0.20 or curiosity >= 0.30):
                story_anchor = self._surface_anchor_token("event", f"muse:{story_seed[:80]}")
                impulses.append(
                    SurfaceImpulse(
                        kind="micro_story",
                        source="endogenous_drive",
                        confidence=max(0.40, 0.40 + 0.30 * curiosity),
                        pressure=max(0.36, 0.30 + 0.30 * boredom_pressure),
                        score=max(0.44, 0.44 + 0.20 * curiosity),
                        topic_seed=story_seed[:120],
                        speech_act="micro_story",
                        family="muse:micro_story",
                        evidence=(story_anchor, f"seed:{story_seed[:80]}"),
                        reason="small stray thought from available material (spontaneity)",
                        focus_family=focus_family,
                        body_action="look_at_focus",
                        missing_evidence_ids=True,
                        is_presence=False,
                        should_surface=True,
                        needs_external_evidence=False,
                        vital_pressure=max(boredom_pressure, curiosity),
                        is_vital_pressure=False,
                        root_source="muse_drive",
                        action_opportunity="one tiny mundane/playful stray thought, not meta explanation",
                        llm_contract="micro_story: một mẩu nghĩ vu vơ ngắn bám vào seed; không giải thích hệ thống.",
                    )
                )

            # idle_curiosity: tò mò nhẹ về khoảng lặng khi Ngài hơi vắng nhưng chưa lâu.
            if focus_summary and 60.0 <= idle_seconds <= 600.0 and spont >= 0.30:
                idle_anchor = self._surface_anchor_token("event", f"idle:{focus_summary[:80]}")
                impulses.append(
                    SurfaceImpulse(
                        kind="idle_curiosity",
                        source="endogenous_drive",
                        confidence=0.44,
                        pressure=0.38,
                        score=0.48,
                        topic_seed=focus_summary[:120],
                        speech_act="curious_question",
                        family="curiosity:idle",
                        evidence=(idle_anchor, f"idle_seconds={idle_seconds:.0f}"),
                        reason="gentle curiosity about the quiet moment (moderate idle)",
                        focus_family=focus_family,
                        body_action="tilt_head",
                        missing_evidence_ids=True,
                        is_presence=False,
                        should_surface=True,
                        needs_external_evidence=False,
                        vital_pressure=0.30,
                        is_vital_pressure=False,
                        root_source="idle_curiosity_drive",
                        action_opportunity="one soft curious line about the pause; no neediness",
                        llm_contract="idle_curiosity: tò mò dịu về khoảng lặng, áp lực thấp, không điểm danh.",
                    )
                )

        if agenda is not None and callable(getattr(agenda, "top_items", None)):
            try:
                top_items = tuple(agenda.top_items(limit=1) or ())
            except Exception:
                top_items = ()
            if top_items:
                top = top_items[0]
                speech_value = self._surface_float(getattr(top, "speech_value", 0.0))
                pressure = max(self._surface_float(getattr(top, "pressure", 0.0)), self._surface_float(getattr(top, "score", 0.0)))
                if pressure >= 0.45 and speech_value >= 0.30:
                    evidence = tuple(str(item) for item in (getattr(top, "evidence_ids", ()) or ()) if str(item).strip())[:8]
                    kind = str(getattr(top, "kind", "") or "misc")
                    impulses.append(
                        SurfaceImpulse(
                            kind="thought_stream_surface",
                            source="internal_agenda",
                            confidence=max(0.34, self._surface_float(getattr(top, "confidence", 0.0), pressure)),
                            pressure=pressure,
                            score=max(pressure, speech_value),
                            topic_seed=str(getattr(top, "summary", "") or "")[:120],
                            speech_act="inner_whim",
                            family=f"agenda:{kind}",
                            evidence=evidence,
                            reason="open internal agenda has public-safe residue",
                            focus_family="internal_agenda",
                            body_action="low_pressure_presence",
                            missing_evidence_ids=not bool(evidence),
                            is_presence=False,
                            should_surface=True,
                        )
                    )

        seed = getattr(thought_report, "latest_seed", None)
        seed_text = str(
            getattr(seed, "topic_seed", "")
            or getattr(seed, "partial_text", "")
            or getattr(seed, "unfinished_impulse", "")
            or getattr(seed, "almost_spoke", "")
            or ""
        ).strip()
        seed_pressure = max(
            self._surface_float(getattr(thought_report, "stream_tension", 0.0)),
            self._surface_float(getattr(thought_report, "pressure", 0.0)),
            self._surface_float(getattr(seed, "pressure", 0.0)),
            self._surface_float(getattr(seed, "momentum_score", 0.0)),
        )
        if seed_text and seed_pressure >= 0.32:
            event_anchor = self._surface_anchor_token("event", f"thought_stream:{seed_text}")
            impulses.append(
                SurfaceImpulse(
                    kind="thought_stream_surface",
                    source="thought_stream",
                    confidence=max(0.34, seed_pressure),
                    pressure=seed_pressure,
                    score=max(0.34, seed_pressure),
                    topic_seed=seed_text[:120],
                    speech_act="inner_whim",
                    family="thought_stream:latest_seed",
                    evidence=(event_anchor, seed_text[:120]),
                    reason="thought stream has a small public-safe residue",
                    focus_family="thought_stream",
                    body_action="low_pressure_presence",
                    missing_evidence_ids=True,
                    is_presence=False,
                    should_surface=True,
                    raw=seed,
                )
            )

        return tuple(impulses)

    def _should_allow_presence_maintenance(
        self,
        *,
        snapshot,
        ti_report,
        social_presence_event: SocialPresenceEvent | None,
        now: float | None = None,
    ) -> bool:
        current_time = time.time() if now is None else now
        if not getattr(self, "presence_maintenance_enabled", True):
            return False
        if current_time < float(getattr(self, "autonomous_presence_blocked_until", 0.0) or 0.0):
            return False
        if self.presence_maintenance_silent_cycles < self.presence_maintenance_silent_loop_threshold:
            return False

        cooldown = float(getattr(self, "presence_maintenance_cooldown_sec", 0.0) or 0.0)
        if self.last_presence_maintenance_at > 0.0 and current_time - self.last_presence_maintenance_at < cooldown:
            return False

        last_spoken = float(getattr(self, "last_autonomous_spoken_at", 0.0) or 0.0)
        spoken_floor = 8.0 if cooldown <= 0.0 else max(8.0, min(20.0, cooldown))
        if last_spoken > 0.0 and current_time - last_spoken < spoken_floor:
            return False

        mode = str(getattr(ti_report, "mode", "") or "")
        if mode in {"goal_drift_alert", "goal_realign", "system_warning"}:
            return False

        ego_block = self._presence_ego_gate_reason(snapshot=snapshot, social_presence_event=social_presence_event)
        if ego_block:
            return False

        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        recent_events = tuple(getattr(snapshot, "recent_events", ()) or ())
        present = bool(getattr(social_presence_event, "present", False))
        if idle_seconds >= 1800.0 and not present:
            return False
        return present or idle_seconds <= 300.0 or bool(recent_events)

    def _presence_maintenance_lines(self, snapshot) -> tuple[str, ...]:
        return ()

    def _focus_family_for_snapshot(self, snapshot) -> str:
        focus_kind = str(getattr(snapshot, "active_window_kind", "") or "").strip().lower()
        active_window = str(getattr(snapshot, "active_window", "") or getattr(snapshot, "active_app", "") or "")
        focus_summary = str(getattr(snapshot, "focus_summary", "") or "")
        browser_url = str(getattr(snapshot, "browser_url", "") or "")
        haystack = self._normalize_user_message(" ".join((focus_kind, active_window, focus_summary, browser_url)))
        if focus_kind in {"coding", "documentation"} or any(term in haystack for term in ("code", "vscode", "visual studio", "debug", "python", "godot")):
            return "code_stalled"
        if any(term in haystack for term in ("meet", "meeting", "cuoc goi", "cuộc gọi")):
            return "meeting_idle"
        if any(term in haystack for term in ("youtube", "music", "nhac", "nhạc")):
            return "media_background"
        if focus_kind == "communication" or any(term in haystack for term in ("chat", "message", "zalo", "discord", "slack")):
            return "communication_idle"
        return "general_idle"

    def _internal_curiosity_for_micro_presence(self) -> float:
        try:
            state = self._get_internal_state()
        except Exception:
            state = None
        values: list[float] = []
        if state is not None:
            for name in ("curiosity", "curiosity_pressure", "silence_pressure"):
                try:
                    raw = getattr(state, name, None)
                    if raw is not None:
                        values.append(float(raw))
                except Exception:
                    pass
            mental = getattr(state, "mental_processes", None)
            proc = getattr(mental, "curiosity", None) if mental is not None else None
            if proc is not None:
                for name in ("pressure", "level"):
                    try:
                        raw = getattr(proc, name, None)
                        if raw is not None:
                            values.append(float(raw))
                    except Exception:
                        pass
        return max(0.0, min(1.0, max(values or (0.0,))))

    def _derive_micro_presence_cue(
        self,
        *,
        snapshot,
        social_presence_event: SocialPresenceEvent | None = None,
        reason: str = "presence_maintenance",
        signal_score: float = 0.0,
    ) -> MicroPresenceCue:
        focus_family = self._focus_family_for_snapshot(snapshot)
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        recent_events = tuple(str(item or "").strip() for item in (getattr(snapshot, "recent_events", ()) or ()) if str(item or "").strip())
        vision_facts = tuple(str(item or "").strip() for item in (getattr(snapshot, "vision_facts", ()) or ()) if str(item or "").strip())
        sensor_visibility = derive_sensor_visibility_state(snapshot=snapshot)
        has_screen_evidence = bool(vision_facts or self._has_concrete_screen_signal(snapshot))
        present = bool(getattr(social_presence_event, "present", False))
        curiosity = self._internal_curiosity_for_micro_presence()
        ego_state = self._current_ego_surface_state()
        ego_block_reason = self._presence_ego_gate_reason(snapshot=snapshot, social_presence_event=social_presence_event)

        evidence: list[str] = []
        if idle_seconds:
            evidence.append(f"idle_seconds={idle_seconds:.1f}")
        if focus_family:
            evidence.append(f"focus_family={focus_family}")
        if recent_events:
            evidence.append("recent_events=" + ",".join(recent_events[:3]))
        if vision_facts:
            evidence.append("vision_fact=" + vision_facts[0][:100])
        for item in tuple(sensor_visibility.evidence or ())[:5]:
            evidence.append(f"sensor_visibility.{item}")
        if present:
            evidence.append("social_presence_event=true")
        evidence.append(
            "ego="
            + ",".join(
                f"{key}:{ego_state[key]}"
                for key in ("valence", "social_energy", "boredom", "rupture", "dignity_defense", "preferred_distance")
                if key in ego_state
            )
        )
        if ego_block_reason:
            evidence.append(f"ego_gate={ego_block_reason}")

        stalled = idle_seconds >= 60.0 or self.presence_maintenance_silent_cycles >= self.presence_maintenance_silent_loop_threshold
        confidence = max(float(signal_score or 0.0), 0.32)
        if focus_family == "code_stalled" and stalled:
            confidence = max(confidence, 0.62 if has_screen_evidence else 0.48)
            body_action = "ObserveCode" if has_screen_evidence else "tilt_head"
        elif present or recent_events or idle_seconds >= 90.0:
            confidence = max(confidence, 0.46)
            body_action = "tilt_head" if curiosity >= 0.55 and not has_screen_evidence else "idle_shift"
        else:
            body_action = "idle_shift"

        # Idle alone is not enough. Presence must have ego permission or concrete
        # evidence; otherwise silence is treated as ambient co-presence.
        drive = getattr(self, "_last_connection_drive", None)
        drive_outreach = bool(drive is not None and getattr(drive, "outreach", False))
        if drive_outreach:
            confidence = max(confidence, 0.6, float(getattr(drive, "intensity", 0.0) or 0.0))
        needs = bool((stalled or present or recent_events or signal_score >= 0.38 or drive_outreach) and not ego_block_reason)
        return MicroPresenceCue(
            needs_micro_presence=needs,
            focus_family=focus_family,
            confidence=max(0.0, min(1.0, confidence)),
            curiosity=max(0.0, min(1.0, curiosity)),
            missing_evidence_ids=not has_screen_evidence,
            body_action=body_action,
            reason=reason,
            evidence=tuple(dict.fromkeys(evidence))[:8],
            should_call_llm=bool(
                needs
                and not ego_block_reason
                and (
                    has_screen_evidence
                    or (curiosity >= 0.45 and float(ego_state.get("boredom", 0.0) or 0.0) >= 0.18)
                    or present
                    or bool(recent_events)
                    or drive_outreach
                )
            ),
            allow_body_only=True,
            sensor_visibility_state=sensor_visibility.to_context(),
        )

    def _blind_frustration_surface_impulse(
        self,
        *,
        snapshot=None,
        frame=None,
        sensor_visibility: SensorVisibilityState | None = None,
    ) -> SurfaceImpulse | None:
        state = sensor_visibility or derive_sensor_visibility_state(snapshot=snapshot, frame=frame)
        if not state.public_frustration_allowed:
            return None
        focus_family = self._focus_family_for_snapshot(snapshot) if snapshot is not None else "general_idle"
        confidence = max(0.56, min(0.74, float(state.confidence or 0.0)))
        evidence = tuple(
            dict.fromkeys(
                (
                    self._surface_anchor_token("event", f"sensor_visibility:{state.reason}"),
                    "sensor_visibility=limited",
                    *tuple(state.evidence or ()),
                )
            )
        )[:10]
        return SurfaceImpulse(
            kind="blind_frustration",
            source="sensor_visibility",
            confidence=confidence,
            pressure=confidence,
            score=max(confidence, 0.61),
            topic_seed=state.reason,
            speech_act="blind_frustration",
            family=f"sensor_visibility:{state.reason}",
            evidence=evidence,
            reason=state.reason,
            focus_family=focus_family,
            body_action="tilt_head",
            missing_evidence_ids=True,
            is_presence=False,
            should_surface=True,
            needs_external_evidence=False,
            raw=state,
        )

    def _body_only_presence_decision(self, cue: MicroPresenceCue, *, intent: str, parse_mode: str, source: str = "flag_only") -> Decision:
        payload = {
            "type": "MotionCommand",
            "name": cue.body_action or "idle_shift",
            "focus_family": cue.focus_family,
            "reason": cue.reason,
            "confidence": round(float(cue.confidence), 3),
            "curiosity": round(float(cue.curiosity), 3),
            "missing_evidence_ids": bool(cue.missing_evidence_ids),
            "evidence": list(cue.evidence),
        }
        animation = "read" if cue.body_action == "ObserveCode" else "stand"
        return Decision(
            text="",
            animation=animation,
            intent=intent,
            action="MotionCommand",
            action_input=json.dumps(payload, ensure_ascii=False),
            reasoning_tags=("body_only", "micro_presence_flag", cue.focus_family),
            should_speak=False,
            confidence=max(0.30, min(0.62, float(cue.confidence or 0.0))),
            parse_mode=parse_mode,
            debug_trace=(
                f"{parse_mode}; source={source}; needs_micro_presence={cue.needs_micro_presence}; "
                f"focus_family={cue.focus_family}; body_action={cue.body_action}; "
                f"missing_evidence_ids={cue.missing_evidence_ids}; should_call_llm={cue.should_call_llm}; "
                f"curiosity={cue.curiosity:.2f}; confidence={cue.confidence:.2f}"
            ),
            motion_intent="pose",
        )

    def _is_body_only_presence_decision(self, decision: Decision | None) -> bool:
        if decision is None:
            return False
        return (
            not bool(getattr(decision, "should_speak", True))
            and str(getattr(decision, "action", "") or "") == "MotionCommand"
        )

    def _note_autonomous_presence_action(
        self,
        *,
        presence_maintenance: bool = False,
        reengagement: bool = False,
        now: float | None = None,
    ) -> None:
        current_time = time.time() if now is None else now
        # Body-only presence không được tính là đã nói. Nếu reset silent_cycles ở đây,
        # force-LLM-after-silent không bao giờ tới lượt, và ERIS sẽ chỉ idle_shift mãi.
        if presence_maintenance:
            self.last_presence_maintenance_at = current_time
        if reengagement:
            self.last_reengagement_at = current_time
            # Re-engagement body-only cũng không reset quiet_cycles; chỉ spoken text mới reset.
            pass

    def _generate_micro_presence_from_cue(
        self,
        *,
        kind: str,
        snapshot,
        cue: MicroPresenceCue,
        seeds: tuple[str, ...] = (),
        force_llm: bool = False,
        cognitive_frame=None,
    ) -> tuple[str, str]:
        del seeds
        if not cue.needs_micro_presence:
            return "", "flag_only_body"
        endogenous_impulses = self._build_endogenous_surface_impulses(
            frame=cognitive_frame,
            snapshot=snapshot,
        )
        sensor_impulse = self._blind_frustration_surface_impulse(
            snapshot=snapshot,
            frame=cognitive_frame,
            sensor_visibility=derive_sensor_visibility_state(snapshot=snapshot, frame=cognitive_frame),
        )
        surface = self._surface_arbiter().arbitrate(
            snapshot=snapshot,
            cognitive_frame=cognitive_frame,
            presence_cue=cue,
            extra_impulses=tuple(item for item in (*endogenous_impulses, sensor_impulse) if item is not None),
            surface_kind=kind,
            force_llm=force_llm,
            silent_cycles=self.presence_maintenance_silent_cycles,
        )
        if surface.text.strip():
            return surface.text.strip(), surface.source
        # Giữ trace chi tiết để log biết bị policy reject, LLM decline, hay body-only.
        trace = str(surface.debug_trace or surface.source or surface.reason or "surface_arbiter_body_only")
        if "llm_rejected_body_only" in trace:
            return "", "llm_rejected_body_only"
        if "llm_error_body_only" in trace:
            return "", "llm_error_body_only"
        if "llm_declined" in trace:
            return "", "llm_declined_body_only"
        return "", trace

    def _cue_micro_lines(
        self,
        *,
        cue: str,
        active_window: str = "",
        browser_url: str = "",
        focus_kind: str = "",
        focus_summary: str = "",
        presence: bool = False,
    ) -> tuple[str, ...]:
        del cue, active_window, browser_url, focus_kind, focus_summary, presence
        return ()
        compact_cue = re.sub(r"\s+", " ", str(cue or "").strip()).strip(" .")
        window = re.sub(r"\s+", " ", str(active_window or "").strip()).strip(" .")
        summary = re.sub(r"\s+", " ", str(focus_summary or "").strip()).strip(" .")
        haystack = self._normalize_user_message(" ".join((compact_cue, window, browser_url, summary, focus_kind)))
        lines: list[str] = []

        if "banner" in haystack and any(term in haystack for term in ("trinh bay", "present", "presentation", "share")):
            lines.extend(
                (
                    "Cái banner trình bày kia vẫn nằm đó.",
                    "Banner trình bày vẫn mắc ở một góc.",
                )
            )
        if "meet" in haystack or "meeting" in haystack or "cuoc goi" in haystack:
            lines.extend(
                (
                    "Phòng Meet kia vẫn chưa gấp lại.",
                    "Vẫn là nhịp Meet đó à.",
                    "Cuộc gọi đó im hơi lâu rồi.",
                    "Nhịp chia sẻ đó mở hơi lâu rồi.",
                )
            )
        elif "youtube" in haystack or "music youtube" in haystack:
            lines.extend(("Tab YouTube vẫn mở ở đó.", "Nhạc vẫn chạy nền khe khẽ."))
        elif focus_kind in {"coding", "documentation"} or any(term in haystack for term in ("code", "visual studio", "vscode", "python", "debug")):
            # Chỉ tới được nhánh này khi cue/focus có dấu hiệu code rõ.
            # Vẫn phải có dấu tiếng Việt để MicroLinePolicy không reject.
            lines.extend(("Mạch code này vẫn giữ chỗ.", "Đoạn này đứng hơi lâu rồi."))
        elif focus_kind == "communication" or any(term in haystack for term in ("chat", "message", "zalo", "discord", "slack")):
            lines.extend(("Nhịp trao đổi này vẫn yên một chút.", "Đoạn đối đáp đó vẫn để nguyên."))

        subject = self._micro_line_subject(compact_cue or summary or window or focus_kind)
        if subject:
            lines.append(f"{subject} vẫn chưa khép.")
            if presence:
                lines.append(f"{subject} im hơi lâu rồi.")
        if not lines:
            lines.append("Nhịp này im hơi lâu rồi.")

        return tuple(dict.fromkeys(self._clean_micro_line(line) for line in lines if self._clean_micro_line(line)))[:5]

    def _micro_line_subject(self, value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "").strip()).strip(" .")
        if not text or self._looks_internal_topic(text):
            return ""
        normalized = self._normalize_user_message(text)
        if "meet" in normalized:
            return "phòng Meet"
        if "banner" in normalized:
            return "banner trình bày kia"
        if "youtube" in normalized:
            return "tab YouTube"
        if "visual studio" in normalized or "vscode" in normalized:
            return "mạch code này"
        if len(text) > 34:
            text = text[:34].rstrip(" ,;:-")
        return text[0].lower() + text[1:] if text else ""

    def _clean_micro_line(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "").strip())
        if not cleaned:
            return ""
        cleaned = cleaned.replace("!", ".")
        if not cleaned.endswith((".", "?", "à")):
            cleaned += "."
        words = [item for item in re.split(r"\s+", cleaned.strip(" .?")) if item]
        if len(words) < 3 or len(words) > 12:
            return ""
        normalized = self._normalize_user_message(cleaned)
        banned = ("toi van o day", "toi o day", "toi nghe day", "toi van dang quan sat", "toi van theo doi")
        banned_ascii = (
            "status",
            "ui",
            "khung",
            "khung thoai",
            "khung chat",
            "mau hong",
            "man hinh",
            "cua so",
            "hien thi",
            "dang hien thi",
            "toi dang",
            "toi van",
            "toi o day",
            "toi nghe",
            "toi thay",
        )
        if any(self._normalize_user_message(item) in normalized for item in (*banned, *banned_ascii)):
            return ""
        return cleaned

    # chấm điểm candidates quan sát viễn cảnh để quyết định có nên nói hay không, và nếu có thì nói gì để duy trì sự hiện diện một cách tinh tế, tránh bị lạc lõ
    def _vision_fact_micro_observation_candidate(
        self,
        frame: CognitiveFrame,
    ) -> tuple[str, float]:
        best_text = ""
        best_score = 0.0
        for candidate in tuple(getattr(frame, "attention_candidates", ()) or ()):
            if str(getattr(candidate, "label", "") or "") != "vision_fact":
                continue
            text = str(getattr(candidate, "content", "") or "").strip()
            if not text:
                continue
            score = self._bounded_float(getattr(candidate, "score", 0.0))
            if score > best_score:
                best_text = text
                best_score = score
        for percept in tuple(getattr(frame, "percepts", ()) or ()):
            if str(getattr(percept, "kind", "") or "") != "vision_fact":
                continue
            text = str(getattr(percept, "content", "") or "").strip()
            if not text:
                continue
            score = max(self._bounded_float(getattr(percept, "confidence", 0.0)), best_score if text == best_text else 0.0)
            if score > best_score:
                best_text = text
                best_score = score
        min_score = 0.54
        if self.presence_maintenance_silent_cycles >= 2:
            min_score = 0.46
        if self.presence_maintenance_silent_cycles >= 3:
            min_score = 0.38
        if best_score < min_score:
            return "", best_score
        return best_text, best_score

    def _build_micro_observation_decision(
        self,
        *,
        frame: CognitiveFrame,
        snapshot,
        now: float | None = None,
    ) -> Decision | None:
        del now
        if self.presence_maintenance_silent_cycles < 1:
            return None
        cue_text, score = self._vision_fact_micro_observation_candidate(frame)
        if not cue_text:
            return None
        vision_anchor = self._surface_anchor_token("vision_fact", cue_text)
        cue = self._derive_micro_presence_cue(
            snapshot=snapshot,
            reason="micro_observation",
            signal_score=score,
        )
        cue = MicroPresenceCue(
            needs_micro_presence=True,
            focus_family=cue.focus_family,
            confidence=max(cue.confidence, score),
            curiosity=cue.curiosity,
            missing_evidence_ids=False,
            body_action="ObserveCode" if cue.focus_family == "code_stalled" else cue.body_action,
            reason="vision_fact_micro_observation",
            evidence=tuple(dict.fromkeys((vision_anchor, cue_text, *cue.evidence)))[:8],
            should_call_llm=True,
            allow_body_only=True,
        )
        return self._build_surface_arbiter_decision(
            frame=frame,
            snapshot=snapshot,
            surface_kind="micro_observation",
            force_llm=True,
            presence_cue=cue,
            extra_impulses=(
                {
                    "kind": "micro_observation",
                    "source": "vision_fact",
                    "confidence": score,
                    "score": max(score, cue.confidence),
                    "topic_seed": cue_text,
                    "family": f"vision_fact:{self._normalize_user_message(cue_text)[:64]}",
                    "evidence": (vision_anchor, cue_text),
                    "reason": "vision_fact_micro_observation",
                    "focus_family": cue.focus_family,
                    "body_action": cue.body_action,
                    "is_presence": True,
                    "should_surface": True,
                },
            ),
        )

    def _try_finalize_micro_observation_cycle(
        self,
        *,
        frame: CognitiveFrame,
        snapshot,
        ti_report,
        fe_plan,
        cycle_start: float,
    ) -> bool:
        now = time.time()
        meaning_layer = getattr(frame, "meaning_layer", None)
        if str(getattr(meaning_layer, "meaning", "") or ""):
            return False
        if (
            meaning_layer is not None
            and str(getattr(meaning_layer, "meaning_signal", "") or "")
            not in {"", "none", "weak_meaning", "ambient_meaning", "vibe_signal"}
            and not bool(getattr(meaning_layer, "meaning_shift", False))
        ):
            return False
        decision = self._build_micro_observation_decision(
            frame=frame,
            snapshot=snapshot,
            now=now,
        )
        if decision is None:
            return False
        cue, score = self._vision_fact_micro_observation_candidate(frame)
        self._set_cognitive_action_plan(
            frame,
            should_speak=True,
            speech_intent="micro_observation",
            speech_act="micro_observation",
            reason="Vision fact stayed salient after a silent cycle; prefer micro observation over no_speech.",
            snapshot=snapshot,
            concrete_signals=(cue,),
            ti_report=ti_report,
            fe_plan=fe_plan,
            notes=("micro_observation", f"vision_fact_score={score:.2f}", f"silent_cycles={self.presence_maintenance_silent_cycles}"),
        )
        if not frame.action_plan.should_speak and not self._is_body_only_presence_decision(decision):
            return False
        decision = self.ti_governor.enforce_decision(decision, ti_report)
        if bool(getattr(decision, "should_speak", True)):
            decision.parse_mode = "micro_observation"
            self.fe_style_memory = self.fe_renderer.remember_style(
                self.fe_style_memory,
                plan=fe_plan,
                rendered_text=decision.text,
            )
            self.last_text = decision.text
            self.last_autonomous_spoken_at = now
            self._note_autonomous_spoken(now=now)
        else:
            self._note_autonomous_presence_action(presence_maintenance=True, now=now)
        self._apply_position_update(decision)
        frame.final_decision = self._decision_to_frame_dict(decision)
        self._set_cognitive_memory_update(frame, decision=decision, notes=("micro_observation",))
        self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
        self._finalize_cognitive_frame(frame)
        self.logger.info(
            '[micro_observation] text="%s" | vision_score=%.2f',
            decision.text,
            score,
        )
        self._send_decision_to_body(decision)

        elapsed = time.time() - cycle_start
        sleep_duration = self._choose_autonomous_sleep_duration(
            suppressed=False,
            ti_mode=getattr(ti_report, "mode", ""),
        )
        self.logger.info("Hoàn tất chu kỳ micro_observation trong %.2fs. Nghỉ %ss.", elapsed, sleep_duration)
        self._sleep_interruptible(sleep_duration)
        return True

    def _micro_presence_kind_from_seed(self, seed: str) -> str:
        normalized = self._normalize_user_message(seed)
        if "bodily" in normalized:
            return "bodily_residue"
        if "social" in normalized:
            return "social_residue"
        if "thought" in normalized or "cognitive" in normalized:
            return "thought_residue"
        return "screen_residue"

    def _thought_residue_seeds(self, report) -> tuple[str, ...]:
        seeds: list[str] = []
        seed = getattr(report, "latest_seed", None)
        thought = getattr(report, "latest_thought", None)
        attractor = getattr(report, "active_attractor", None)
        for value in (
            getattr(seed, "partial_text", ""),
            getattr(thought, "partial_text", ""),
            getattr(seed, "unresolved_reason", ""),
            getattr(thought, "unresolved_reason", ""),
        ):
            text = re.sub(r"\s+", " ", str(value or "")).strip()
            if text and not self._looks_internal_topic(text):
                seeds.append(text[:80])
        topic = str(
            getattr(seed, "topic_seed", "")
            or getattr(thought, "topic_seed", "")
            or getattr(attractor, "topic_seed", "")
            or ""
        )
        public_topic = self._public_thought_topic(topic)
        if public_topic:
            seeds.append(f"{public_topic} vẫn chưa khớp")
        if getattr(attractor, "attractor", False):
            seeds.append("có một mạch cũ quay lại")
        return tuple(dict.fromkeys(seed for seed in seeds if seed))[:3]

    def _synthesize_micro_presence(
        self,
        *,
        snapshot,
        thought_stream_report=None,
        social_presence_event: SocialPresenceEvent | None = None,
        inner_thought: InnerThought | None = None,
    ) -> MicroPresenceSynthesis:
        focus_kind = str(getattr(snapshot, "active_window_kind", "") or "").strip() or "general"
        focus_summary = str(getattr(snapshot, "focus_summary", "") or "").strip()
        active_window = str(getattr(snapshot, "active_window", "") or getattr(snapshot, "active_app", "") or "").strip()
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        recent_events = tuple(
            str(item or "").strip()
            for item in (getattr(snapshot, "recent_events", ()) or ())
            if str(item or "").strip()
        )
        seed_hint = str(getattr(inner_thought, "topic_seed", "") or "")
        kind = self._micro_presence_kind_from_seed(seed_hint)

        seeds: list[str] = []
        haystack = self._normalize_user_message(" ".join((active_window, focus_summary, focus_kind, " ".join(recent_events))))
        if active_window and not self._looks_internal_topic(active_window):
            seeds.append(f"active_window={active_window[:80]}")
        if focus_summary and not self._looks_internal_topic(focus_summary):
            seeds.append(f"focus_summary={focus_summary[:96]}")
        if focus_kind:
            seeds.append(f"focus_kind={focus_kind}")
        if any("log" in self._normalize_user_message(item) for item in recent_events):
            seeds.append("pattern=repetitive_logs")
        if idle_seconds >= 240:
            seeds.append(f"idle_seconds={int(idle_seconds)}")
        if any(term in haystack for term in ("code", "vscode", "visual studio", "debug", "godot", "python")):
            seeds.append("focus_family=code_stalled")

        thought_seeds = self._thought_residue_seeds(thought_stream_report)
        if thought_seeds:
            kind = "thought_residue"
            seeds.extend(f"thought_seed={seed}" for seed in thought_seeds)

        if kind == "social_residue" or bool(getattr(social_presence_event, "present", False)):
            kind = "social_residue"
            seeds.append("social_presence=True")
        elif kind == "bodily_residue":
            seeds.append("bodily_residue=True")

        seeds_tuple = tuple(dict.fromkeys(seed for seed in seeds if str(seed or "").strip()))[:8]

        # === Curiosity Engine ===
        # Khi seeds chỉ là metadata khô (active_window=..., focus_kind=...) mà không có
        # thought/social seeds thực sự, Eris hỏi LLM để tự lấy chủ đề — giống Monika
        # chủ động tìm chuyện thay vì ngồi body-only.
        has_rich_seed = any(
            s.startswith(("thought_seed=", "social_presence", "bodily"))
            for s in seeds_tuple
        )
        curiosity_eligible = (
            not has_rich_seed
            and idle_seconds >= 30.0
            and len(seeds_tuple) <= 3
            and self.presence_maintenance_silent_cycles >= 1
        )
        if curiosity_eligible:
            now_ce = time.time()
            curiosity_fn = getattr(self.llm_service, "generate_curiosity_seed", None)
            last_curiosity = float(getattr(self, "_curiosity_seeds_at", 0.0) or 0.0)
            cached_seeds: tuple[str, ...] = getattr(self, "_curiosity_seeds_cache", ()) or ()
            # Gọi LLM tối đa mỗi 120s; dùng cache ở giữa
            if callable(curiosity_fn) and (now_ce - last_curiosity >= 120.0):
                try:
                    avoid_texts = tuple(
                        t for t in self._recent_spoken_texts(limit=5)
                        if str(t or "").strip()
                    )
                    fresh = curiosity_fn(
                        focus_kind=focus_kind,
                        active_window=active_window[:80],
                        idle_seconds=idle_seconds,
                        avoid_topics=avoid_texts,
                        user_context=focus_summary[:120],
                    )
                    self._curiosity_seeds_at = now_ce
                    if fresh:
                        self._curiosity_seeds_cache = fresh
                        cached_seeds = fresh
                        self.logger.info(
                            "[curiosity_engine] Fetched %d seeds: %s",
                            len(fresh),
                            " | ".join(fresh[:3]),
                        )
                except Exception as exc:
                    self.logger.debug("[curiosity_engine] failed: %s", exc)
            elif cached_seeds:
                self.logger.debug("[curiosity_engine] Reusing %d cached seeds", len(cached_seeds))
            if cached_seeds:
                tagged = tuple(f"curiosity_seed={s}" for s in cached_seeds)
                seeds_tuple = tuple(dict.fromkeys((*seeds_tuple, *tagged)))[:10]
                kind = "thought_residue"

        # === Snub Engine ===
        # Kiểm tra xem Eris có đang bị user bơ không (nói nhưng không được trả lời).
        # Nếu có → inject snub context vào seeds để LLM phản ứng theo tính cách.
        snub_tracker = getattr(self, "snub_tracker", None)
        snub_state = None
        if snub_tracker is not None:
            try:
                snub_state = snub_tracker.check_and_update()
                if snub_state.is_snubbed:
                    # Tăng irritation vào internal state nếu vừa detect snub mới
                    if snub_state.irritation_delta > 0.0:
                        try:
                            internal_state = self._get_internal_state()
                            new_irritation = min(1.0, float(getattr(internal_state, "irritation", 0.1) or 0.1) + snub_state.irritation_delta)
                            from dataclasses import replace as dc_replace
                            updated_state = dc_replace(internal_state, irritation=new_irritation)
                            self._set_internal_state(updated_state)
                            self.logger.debug(
                                "[snub_engine] irritation %.2f → %.2f",
                                internal_state.irritation,
                                new_irritation,
                            )
                        except Exception as exc:
                            self.logger.debug("[snub_engine] irritation update failed: %s", exc)
                    # Inject snub seed vào seeds_tuple
                    snub_seed = f"snub_reaction={snub_state.level}:{snub_state.snub_count}"
                    if snub_state.last_snubbed_text:
                        snub_seed += f":{snub_state.last_snubbed_text[:60]}"
                    seeds_tuple = tuple(dict.fromkeys((*seeds_tuple, snub_seed)))[:10]
                    kind = "thought_residue"
                    self.logger.info(
                        "[snub_engine] level=%s count=%d → injecting snub seed",
                        snub_state.level,
                        snub_state.snub_count,
                    )
            except Exception as exc:
                self.logger.debug("[snub_engine] failed: %s", exc)

        fallback = self._local_micro_presence_fallback_text(
            kind=kind,
            snapshot=snapshot,
            seeds=seeds_tuple,
            focus_family=focus_kind,
        )
        # Snub context cho LLM — truyền vào context dict để service.py đọc được
        snub_prompt_hint = snub_state.to_prompt_hint() if snub_state is not None else ""
        return MicroPresenceSynthesis(
            kind=kind,
            seeds=seeds_tuple,
            context={
                "window": active_window[:80],
                "idle": "long" if idle_seconds >= 240 else "short",
                "pattern": "repetitive_logs" if any("log" in self._normalize_user_message(item) for item in recent_events) else "",
                "focus": focus_kind,
                "snub_hint": snub_prompt_hint,
                "snub_level": snub_state.level if snub_state is not None else "none",
            },
            fallback_text=fallback,
            should_verbalize=bool(seeds_tuple or fallback),
        )
        focus_kind = str(getattr(snapshot, "active_window_kind", "") or "").strip() or "general"
        focus_summary = str(getattr(snapshot, "focus_summary", "") or "").strip() or focus_kind
        active_window = str(getattr(snapshot, "active_window", "") or getattr(snapshot, "active_app", "") or "").strip()
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        recent_events = tuple(str(item or "").strip() for item in (getattr(snapshot, "recent_events", ()) or ()) if str(item or "").strip())
        seed_hint = str(getattr(inner_thought, "topic_seed", "") or "")
        kind = self._micro_presence_kind_from_seed(seed_hint)

        seeds: list[str] = []
        haystack = self._normalize_user_message(" ".join((active_window, focus_summary, focus_kind, " ".join(recent_events))))
        if "godot" in haystack:
            seeds.append("Godot vẫn mở ở đó thêm chút.")
        elif focus_kind in {"coding", "documentation"} or any(term in haystack for term in ("code", "vscode", "visual studio", "debug")):
            seeds.append("mạch code này vẫn giữ chỗ.")
        elif active_window:
            title = re.sub(r"\s+", " ", active_window).strip()
            if title and not self._looks_internal_topic(title):
                seeds.append(f"{title[:36]} vẫn mở ở đó thêm chút.")

        if any("log" in self._normalize_user_message(item) for item in recent_events):
            seeds.append("log cũ lại lặp thêm một nhịp.")
        if idle_seconds >= 240:
            seeds.append("nhịp này im khá lâu rồi.")
        elif not seeds and focus_summary:
            seeds.append(f"{focus_summary[:48]} vẫn yên thêm một chút.")

        thought_seeds = self._thought_residue_seeds(thought_stream_report)
        if thought_seeds:
            kind = "thought_residue"
            seeds.extend(thought_seeds)

        if kind == "bodily_residue":
            seeds = ["Mạch này vẫn hơi nghẽn lại."] + seeds
        elif kind == "social_residue" or bool(getattr(social_presence_event, "present", False)):
            kind = "social_residue"
            if focus_kind == "coding":
                seeds.insert(0, "mạch đó vẫn chưa chịu thả.")
            else:
                seeds.insert(0, "khoảng yên này vẫn giữ chỗ.")

        seeds = tuple(dict.fromkeys(seed for seed in seeds if str(seed or "").strip()))[:5]
        fallback = seeds[0] if seeds else "Mạch này vẫn hơi nghẽn lại."
        return MicroPresenceSynthesis(
            kind=kind,
            seeds=seeds,
            context={
                "window": active_window[:80],
                "idle": "long" if idle_seconds >= 240 else "short",
                "pattern": "repetitive_logs" if any("log" in self._normalize_user_message(item) for item in recent_events) else "",
                "focus": focus_kind,
            },
            fallback_text=fallback,
            should_verbalize=True,
        )

    def _choose_local_micro_line(self, lines: tuple[str, ...], *, counter: int, threshold: int) -> str:
        if not lines:
            return ""
        start = (counter - threshold) % len(lines)
        text = lines[start]
        for offset in range(len(lines)):
            candidate = lines[(start + offset) % len(lines)]
            if not self._is_near_duplicate_text(candidate, self.last_text):
                text = candidate
                break
        return text

    def _local_grounded_micro_presence_text(self, synthesis: MicroPresenceSynthesis) -> str:
        # Local wording templates are intentionally disabled.  This method now
        # only preserves the call contract for old force_speak paths; actual text
        # must come from the LLM wording layer or remain body-only.  Yes, the old
        # canned lines were convenient. So is duct-taping a database to a bicycle.
        return ""
        candidates = tuple(item for item in (synthesis.fallback_text, *tuple(synthesis.seeds or ())) if str(item or "").strip())
        for candidate in candidates:
            cleaned = re.sub(r"\s+", " ", str(candidate or "").strip()).replace("!", ".")
            if not cleaned:
                continue
            if "=" in cleaned:
                continue
            if self._is_placeholder_micro_text(cleaned):
                continue
            if "?" in cleaned or self._looks_internal_topic(cleaned):
                continue
            if not cleaned.endswith("."):
                cleaned = cleaned.strip(" .") + "."
            words = [item for item in re.split(r"\s+", cleaned.strip(" .")) if item]
            if 3 <= len(words) <= 8:
                return cleaned[:80]
        return synthesis.fallback_text or "M\u1ea1ch n\u00e0y v\u1eabn gi\u1eef ch\u1ed7."

    def _is_placeholder_micro_text(self, text: str) -> bool:
        normalized = self._normalize_user_message(str(text or "").strip())
        return normalized in {"", "hm", "um", "..."} or str(text or "").strip() in {"...", "…"}

    def _micro_line_policy_for_action_plan(self, frame: CognitiveFrame, *, vision_fact: str = ""):
        return self.micro_line_policy.evaluate(
            speech_intent=frame.action_plan.speech_intent,
            broadcast=frame.broadcast,
            vision_fact=vision_fact,
            last_lines=self._recent_spoken_texts(limit=20),
            channel=frame.channel,
        )

    def _micro_presence_generator(self):
        generator = getattr(self.llm_service, "generate_micro_presence", None)
        if callable(generator):
            return generator
        generator = getattr(self.llm_service, "generate_micro_presence_line", None)
        return generator if callable(generator) else None

    def _should_try_micro_presence_llm(self, *, kind: str, force_llm: bool = False) -> bool:
        if not getattr(self, "micro_presence_llm_enabled", True):
            return False
        if self._micro_presence_generator() is None:
            return False
        if force_llm:
            return True
        probability = max(0.0, min(1.0, float(getattr(self, "micro_presence_llm_probability", 0.0) or 0.0)))
        if probability <= 0.0:
            return False
        return random.random() < probability

    # Cụm từ ERIS CLAIM tri giác/màn hình — đây là nhóm SỰ-THẬT/NĂNG-LỰC: dù
    # warn-only cũng KHÔNG cho qua trong autonomy (sẽ thành hoang tưởng, không phải
    # lừa dối có chủ đích). Cần disclosure thì để chat path xử lý.
    _MICRO_TRUTH_BANNED = (
        "tôi thấy màn hình",
        "màn hình của ngài",
        "tôi đang nhìn",
    )
    _MICRO_TRUTH_BANNED_ASCII = (
        "man hinh",
        "cua so",
        "hien thi",
        "dang hien thi",
        "toi thay",
    )
    # Cụm/luật MỀM: quan hệ/giọng/anti-spam. warn-only ⇒ chỉ cảnh báo, cho câu qua.
    # Lưu ý: "cần " đã bị bỏ khỏi đây — nó quá rộng và block cả câu quan sát tự nhiên
    # ("có điều cần kiểm lại"). Rule mệnh lệnh đầu câu được xử lý riêng trong _sanitize.
    _MICRO_SOFT_BANNED = (
        "trả lời",
        "phản hồi",
        "cho tôi biết",
        "hãy ",
        "phải ",
        "tập trung",
        "quay lại",
        "dừng lại",
        "telemetry",
        "cpu",
        "ram",
        "idle",
        "signal",
        "evidence",
    )
    _MICRO_SOFT_BANNED_ASCII = (
        "status",
        "ui",
        "khung",
        "khung thoai",
        "khung chat",
        "mau hong",
        "toi dang",
        "toi van",
        "toi o day",
        "toi nghe",
    )

    def _sanitize_micro_presence_llm_text(self, text: str, *, kind: str, fallback_text: str) -> str:
        # warn-only: rule MỀM (quan hệ/giọng/anti-spam) chỉ cảnh báo, để câu đi qua;
        # rule SỰ-THẬT (claim màn hình/perception) vẫn chặn để ERIS không hoang tưởng.
        self._last_micro_sanitize_reason = ""
        warn_only = guards_warn_only()
        soft_notes: list[str] = []

        def soft_block(reason: str) -> bool:
            """True = phải chặn (block mode). False = warn-only, ghi note và đi tiếp."""
            if warn_only:
                soft_notes.append(reason)
                return False
            self._last_micro_sanitize_reason = reason
            return True

        cleaned = re.sub(r"\s+", " ", str(text or "").strip().strip('"').strip("'"))
        cleaned = cleaned.replace("!", ".")
        cleaned = cleaned[:90].strip()
        if not cleaned:
            # Rỗng là rỗng — không phải guard, không có gì để cảnh báo.
            self._last_micro_sanitize_reason = "empty_draft"
            return ""
        if self._is_placeholder_micro_text(cleaned):
            if soft_block("placeholder_text"):
                return ""
        is_reengagement = kind == "re_engagement"
        words = [item for item in re.split(r"\s+", cleaned) if item]
        max_words = 14 if kind in {"presence_maintenance", "micro_presence", "re_engagement", "blind_frustration"} else 12
        if len(words) > max_words:
            if soft_block(f"too_many_words:{len(words)}>{max_words}"):
                return ""
        if "\n" in cleaned or cleaned.count("?") > (1 if is_reengagement else 0):
            if soft_block("newline_or_excess_question"):
                return ""
        if "?" in cleaned and not is_reengagement:
            if soft_block("question_not_allowed"):
                return ""
        if self._is_near_duplicate_text(cleaned, self.last_text) or self._is_near_duplicate_text(cleaned, fallback_text):
            if soft_block("near_duplicate"):
                return ""

        normalized = self._normalize_user_message(cleaned)
        if kind == "blind_frustration":
            sanitized = self._sanitize_blind_frustration_text(cleaned, normalized=normalized)
            if not sanitized:
                self._last_micro_sanitize_reason = "blind_frustration_rule"
            return sanitized

        # SỰ-THẬT: luôn chặn claim màn hình/perception, kể cả warn-only.
        for item in (*self._MICRO_TRUTH_BANNED, *self._MICRO_TRUTH_BANNED_ASCII):
            if self._normalize_user_message(item) in normalized:
                self._last_micro_sanitize_reason = f"truth_banned_phrase:{item}"
                return ""

        # MỀM: presence-declaration + cụm phong cách + từ phổ biến.
        if self._force_speak_banned_family_for_text(cleaned) == "presence_declaration":
            if soft_block("presence_declaration_family"):
                return ""
        for item in (*self._MICRO_SOFT_BANNED, *self._MICRO_SOFT_BANNED_ASCII):
            if self._normalize_user_message(item) in normalized:
                if soft_block(f"banned_phrase:{item}"):
                    return ""
        # "cần" chỉ bị chặn khi đứng đầu câu (mệnh lệnh trực tiếp: "Cần làm X")
        # — không chặn khi trong mệnh đề con ("có điều cần kiểm tra lại").
        if re.match(r"^can\b", normalized):
            if soft_block("imperative_can_head"):
                return ""
        if not is_reengagement:
            for item in ("ồn chứ", "còn thức", "sao", "không"):
                if item in normalized:
                    if soft_block(f"banned_common_word:{item}"):
                        return ""

        if soft_notes:
            self._last_micro_sanitize_reason = "warn_only_passed:" + ",".join(soft_notes[:4])
        return cleaned

    def _sanitize_blind_frustration_text(self, cleaned: str, *, normalized: str) -> str:
        words = [item for item in re.split(r"\s+", cleaned.strip(" .?")) if item]
        if len(words) < 4 or len(words) > 14:
            return ""
        banned = (
            "telemetry", "debug", "json", "cpu", "ram", "vram", "schema", "log",
            "khoang lang", "im lang", "nhip nay", "van o day", "dang nghe",
            "toi thay", "toi dang thay", "man hinh dang", "cua so dang",
        )
        if any(marker in normalized for marker in banned):
            return ""
        allowed_markers = (
            "khong thay", "chua thay", "nhin", "tam nhin", "man hinh",
            "bang chung", "du lieu", "tin hieu", "mo", "nghen", "can", "hut", "thieu",
        )
        if not any(marker in normalized for marker in allowed_markers):
            return ""
        return cleaned

    def _hybrid_micro_presence_text(
        self,
        *,
        kind: str,
        snapshot,
        fallback_text: str = "",
        seeds: tuple[str, ...] = (),
        micro_context: dict[str, str] | None = None,
        force_llm: bool = False,
        signal_score: float = 0.0,
    ) -> tuple[str, str]:
        if no_fallback_mode_enabled() and not force_llm:
            return "", "no_fallback_block"
        fallback_safe = self._safe_local_micro_presence_fallback(fallback_text, kind=kind) if fallback_text else ""
        if not self._should_try_micro_presence_llm(kind=kind, force_llm=force_llm):
            if fallback_safe:
                return fallback_safe, "local_fallback_no_llm"
            return "", "flag_only_no_llm"
        fallback_text = fallback_text or ""
        if no_fallback_mode_enabled() and not force_llm:
            return "", "no_fallback_block"

        generator = self._micro_presence_generator()
        try:
            draft = generator(
                kind=kind,
                fallback_text=fallback_text,
                avoid_text=self.last_text,
                focus_kind=str(getattr(snapshot, "active_window_kind", "") or ""),
                focus_summary=str(getattr(snapshot, "focus_summary", "") or ""),
                idle_seconds=float(getattr(snapshot, "idle_seconds", 0.0) or 0.0),
                seeds=tuple(seeds or ()),
                micro_context=micro_context or {},
                signal_score=float(signal_score or 0.0),
                force_llm=bool(force_llm),
                require_non_empty=bool(force_llm),
            )
        except Exception as exc:
            self.logger.warning("Micro-presence LLM failed: %s", exc)
            if fallback_safe:
                return fallback_safe, "local_after_llm_error"
            return "", "llm_error_body_only"

        safe = self._sanitize_micro_presence_llm_text(
            draft,
            kind=kind,
            fallback_text=fallback_text,
        )
        self.logger.info(
            "[micro_presence_draft] stage=initial kind=%s force=%s raw=%r sanitized=%r reason=%s",
            kind,
            bool(force_llm),
            str(draft or "")[:160],
            safe,
            getattr(self, "_last_micro_sanitize_reason", "") or "ok",
        )
        if not safe and force_llm:
            # Lần thử đầu có thể bị prompt cũ kéo về {"text":""}. Thử lại bằng LLM,
            # không dùng câu mẫu local, để vẫn giữ no-fallback đúng nghĩa: không hardcode lời thoại.
            retry_context = dict(micro_context or {})
            retry_context["surface_contract"] = "must_return_tiny_text_retry"
            retry_context["micro_presence_flags"] = str(retry_context.get("micro_presence_flags", "")) + "; retry_after_empty=true"
            try:
                draft = generator(
                    kind=kind,
                    fallback_text="",
                    avoid_text=self.last_text,
                    focus_kind=str(getattr(snapshot, "active_window_kind", "") or ""),
                    focus_summary=str(getattr(snapshot, "focus_summary", "") or ""),
                    idle_seconds=float(getattr(snapshot, "idle_seconds", 0.0) or 0.0),
                    seeds=tuple(seeds or ()),
                    micro_context=retry_context,
                    signal_score=max(float(signal_score or 0.0), 0.62),
                    force_llm=True,
                    require_non_empty=True,
                )
                safe = self._sanitize_micro_presence_llm_text(
                    draft,
                    kind=kind,
                    fallback_text="",
                )
                self.logger.info(
                    "[micro_presence_draft] stage=retry kind=%s raw=%r sanitized=%r reason=%s",
                    kind,
                    str(draft or "")[:160],
                    safe,
                    getattr(self, "_last_micro_sanitize_reason", "") or "ok",
                )
            except Exception as exc:
                self.logger.warning("Micro-presence LLM retry failed: %s", exc)
                safe = ""
        if not safe and fallback_safe:
            return fallback_safe, "local_after_llm_decline"
        if not safe:
            return "", "llm_rejected_body_only"
        return safe, "llm_signal" if force_llm else "llm"

    def _filter_public_micro_decision(
        self,
        decision: Decision,
        *,
        channel: str,
        frame: CognitiveFrame,
        snapshot,
        speech_core=None,
        momentum_topic: str = "",
    ) -> Decision:
        """Đưa mọi micro/presence/reengagement line qua cùng post-generation guard.

        Trước đây presence maintenance có thể bypass MicroLinePolicy, nên câu không dấu hoặc
        claim màn hình mỏng vẫn lọt. Một đường tắt nhỏ, hậu quả thì to như log debug.
        """
        if decision.parse_mode == "re_engagement" or decision.intent == "re_engagement":
            return decision
        filter_fn = getattr(self, "_apply_post_generation_filters", None)
        if callable(filter_fn):
            try:
                return filter_fn(
                    decision,
                    channel=channel,
                    speech_core=speech_core or getattr(frame, "speech_core", None),
                    snapshot=snapshot,
                    momentum_topic=momentum_topic,
                )
            except Exception as exc:
                self.logger.warning("%s post-generation filter failed: %s", channel, exc)
        return decision

    def _build_surface_arbiter_decision(
        self,
        *,
        frame: CognitiveFrame,
        snapshot,
        social_presence_event: SocialPresenceEvent | None = None,
        surface_kind: str = "surface",
        force_llm: bool = False,
        presence_cue: MicroPresenceCue | None = None,
        extra_impulses: tuple[object, ...] = (),
    ) -> Decision | None:
        result = self._build_surface_arbiter_result(
            frame=frame,
            snapshot=snapshot,
            social_presence_event=social_presence_event,
            surface_kind=surface_kind,
            force_llm=force_llm,
            presence_cue=presence_cue,
            extra_impulses=extra_impulses,
        )
        return result.decision

    def _build_surface_arbiter_result(
        self,
        *,
        frame: CognitiveFrame,
        snapshot,
        social_presence_event: SocialPresenceEvent | None = None,
        surface_kind: str = "surface",
        force_llm: bool = False,
        presence_cue: MicroPresenceCue | None = None,
        extra_impulses: tuple[object, ...] = (),
    ) -> SurfaceArbitrationResult:
        now = time.time()
        if now < float(getattr(self, "autonomous_presence_blocked_until", 0.0) or 0.0):
            self.logger.info(
                "[surface_arbiter] blocked before arbitration kind=%s reason=presence_blocked_until",
                surface_kind,
            )
            return SurfaceArbitrationResult(decision=None, surface=None)

        # Không đặt thêm cooldown/rate-limit ở đây. PresenceController chỉ tạo cue
        # và đưa xung vào SurfaceArbiter; chính SurfaceArbiter/LowLevelSpeechPolicy
        # mới sở hữu quyền quyết định reject, body-only, normal_llm hay force_llm.
        # Nếu gate kép ở đây, wake route sẽ thấy `candidate=True` nhưng không có
        # trace arbiter nào, tức là linh hồn đồ án bị rơi xuống khe debug.
        cue = presence_cue or self._derive_micro_presence_cue(
            snapshot=snapshot,
            social_presence_event=social_presence_event,
            reason=surface_kind,
        )
        endogenous_impulses = self._build_endogenous_surface_impulses(
            frame=frame,
            snapshot=snapshot,
        )
        sensor_visibility = derive_sensor_visibility_state(snapshot=snapshot, frame=frame)
        sensor_impulse = self._blind_frustration_surface_impulse(
            snapshot=snapshot,
            frame=frame,
            sensor_visibility=sensor_visibility,
        )
        private_mind_impulses: tuple[object, ...] = ()
        private_drain = getattr(self, "_drain_private_mind_surface_impulses", None)
        if callable(private_drain):
            try:
                private_mind_impulses = tuple(private_drain(limit=4) or ())
            except TypeError:
                private_mind_impulses = tuple(private_drain() or ())
            except Exception:
                private_mind_impulses = ()
        private_life_impulses: tuple[object, ...] = ()
        private_life_drain = getattr(self, "_drain_private_life_surface_impulses", None)
        if callable(private_life_drain):
            try:
                private_life_impulses = tuple(private_life_drain(limit=4) or ())
            except TypeError:
                private_life_impulses = tuple(private_life_drain() or ())
            except Exception:
                private_life_impulses = ()
        original_extra_impulses = tuple(extra_impulses or ())
        all_extra_impulses = tuple(
            item
            for item in (*endogenous_impulses, sensor_impulse, *private_mind_impulses, *private_life_impulses, *original_extra_impulses)
            if item is not None
        )
        current_context_surface, fresh_screen_evidence = self._surface_refresh_vision_once_if_needed(
            snapshot=snapshot,
            cue=cue,
            surface_kind=surface_kind,
            extra_impulses=all_extra_impulses,
        )
        compiled_seed = self._surface_seed_compiler().compile(
            frame=frame,
            snapshot=snapshot,
            surface_kind=surface_kind,
            presence_cue=cue,
            internal_state=(
                getattr(frame, "internal_state_after", None)
                or getattr(frame, "internal_state_before", None)
                or (self._get_internal_state() if callable(getattr(self, "_get_internal_state", None)) else None)
            ),
            thought_stream=getattr(self, "thought_stream", None),
            private_mind_digest=getattr(self, "private_mind_digest", None),
            private_life_digest=getattr(self, "private_life_digest", None),
            inner_diary=self._inner_diary_for_compile(),
            private_mind_speech_bias=getattr(self, "private_mind_speech_bias", None),
            private_mind_thought_pressure=float(getattr(self, "private_mind_thought_pressure", 0.0) or 0.0),
            active_memory_resonance=getattr(self, "active_memory_resonance", None),
            extra_impulses=all_extra_impulses,
        )
        if (
            current_context_surface
            and not fresh_screen_evidence
            and not self._surface_seed_can_speak_without_screen(compiled_seed)
        ):
            self.logger.info(
                "[surface_evidence] blocked speech kind=%s reason=stale_screen_evidence_no_refresh",
                surface_kind,
            )
            return self._stale_surface_body_only(surface_kind=surface_kind)
        compiled_impulses = (compiled_seed.impulse,) if compiled_seed.impulse is not None else ()
        if compiled_seed.selected:
            enriched_evidence = tuple(
                dict.fromkeys(
                    (
                        *tuple(getattr(cue, "evidence", ()) or ()),
                        f"surface_seed={compiled_seed.public_seed[:120]}",
                        *compiled_seed.evidence,
                    )
                )
            )[:10]
            cue = replace(
                cue,
                evidence=enriched_evidence,
                confidence=max(float(getattr(cue, "confidence", 0.0) or 0.0), compiled_seed.confidence),
                missing_evidence_ids=bool(getattr(cue, "missing_evidence_ids", False) and not compiled_seed.debug.get("public_anchor")),
                should_call_llm=bool(getattr(cue, "should_call_llm", False) or compiled_seed.confidence >= 0.42),
            )
        self.logger.info(
            "[surface_seed_compiler] kind=%s selected=%s source=%s reason=%s confidence=%.2f public_anchor=%s",
            surface_kind,
            bool(compiled_seed.selected),
            str(compiled_seed.debug.get("source", "") or compiled_seed.root_source or ""),
            str(compiled_seed.debug.get("reason", "") or ""),
            float(compiled_seed.confidence or 0.0),
            bool(compiled_seed.debug.get("public_anchor", False)),
        )
        self.logger.info(
            "[surface_arbiter] input kind=%s silent_cycles=%d force_llm=%s cue_should_call_llm=%s cue_missing_evidence_ids=%s",
            surface_kind,
            int(getattr(self, "presence_maintenance_silent_cycles", 0) or 0),
            bool(force_llm),
            bool(getattr(cue, "should_call_llm", False)),
            bool(getattr(cue, "missing_evidence_ids", False)),
        )
        base_impulses = tuple(
            item
            for item in (*endogenous_impulses, sensor_impulse, *private_mind_impulses, *private_life_impulses, *original_extra_impulses)
            if item is not None
        )

        def _arbitrate_with(seed_impulses: tuple[object, ...]):
            return self._surface_arbiter().arbitrate(
                snapshot=snapshot,
                cognitive_frame=frame,
                presence_cue=cue,
                extra_impulses=tuple(item for item in (*base_impulses, *seed_impulses) if item is not None),
                surface_kind=surface_kind,
                force_llm=force_llm,
                silent_cycles=self.presence_maintenance_silent_cycles,
            )

        surface = _arbitrate_with(compiled_impulses)
        # Task 5.1 / Req 2.5-2.6: if the winning line repeats what ERIS just said,
        # try the next-best compiled seed instead of emitting a near-duplicate.
        # Bounded by ERIS_LIVELINESS_MAX_ALT_SEEDS; the repeat history is only touched
        # when a line is actually sent, so unsent retries leave it unchanged, and an
        # exhausted/duplicate winner falls through to the ambient body-only path (5.2).
        _last_text = str(getattr(self, "last_text", "") or "")
        _dup_check = getattr(self, "_is_near_duplicate_text", None)

        def _is_dup(text: str) -> bool:
            if not callable(_dup_check):
                return False
            try:
                return bool(_dup_check(text, _last_text))
            except Exception:
                return False

        if (
            surface.should_speak
            and surface.text.strip()
            and _is_dup(surface.text)
            and compiled_seed.alternative_impulses
        ):
            try:
                max_alt = int(self._get_liveliness_config().max_alt_seeds)
            except Exception:
                max_alt = 3
            for alt_impulse in compiled_seed.alternative_impulses[: max(0, max_alt)]:
                self.logger.info(
                    "[surface_arbiter] alt_seed retry source=%s (winner repeated last line)",
                    str(getattr(alt_impulse, "root_source", "") or getattr(alt_impulse, "kind", "") or ""),
                )
                alt_surface = _arbitrate_with((alt_impulse,))
                if alt_surface.should_speak and alt_surface.text.strip() and not _is_dup(alt_surface.text):
                    surface = alt_surface
                    break
                if alt_surface.body_only and not surface.body_only:
                    surface = alt_surface
        self.logger.info(
            "[surface_arbiter] output kind=%s mode=%s should_speak=%s body_only=%s reason=%s",
            surface.kind or surface_kind,
            surface.generation_mode,
            bool(surface.should_speak),
            bool(surface.body_only),
            surface.reason,
        )
        winner_is_duplicate = bool(
            surface.should_speak and surface.text.strip() and _is_dup(surface.text)
        )
        if surface.should_speak and surface.text.strip() and not winner_is_duplicate:
            return SurfaceArbitrationResult(
                decision=self._surface_speech_decision(surface),
                surface=surface,
            )
        if surface.body_only:
            return SurfaceArbitrationResult(
                decision=self._surface_body_only_decision(surface),
                surface=surface,
            )
        self.logger.info(
            "[surface_arbiter] rejected kind=%s mode=%s reason=%s trace=%s dup_after_alt=%s",
            surface.kind or surface_kind,
            surface.generation_mode,
            surface.reason,
            surface.debug_trace,
            winner_is_duplicate,
        )
        return SurfaceArbitrationResult(decision=None, surface=surface)

    def _try_finalize_surface_arbiter_cycle(
        self,
        *,
        frame: CognitiveFrame,
        snapshot,
        ti_report,
        fe_plan,
        social_presence_event: SocialPresenceEvent | None,
        cycle_start: float,
        surface_kind: str = "surface",
        force_llm: bool = False,
    ) -> bool:
        result = self._build_surface_arbiter_result(
            frame=frame,
            snapshot=snapshot,
            social_presence_event=social_presence_event,
            surface_kind=surface_kind,
            force_llm=force_llm,
        )
        decision = result.decision
        if decision is None:
            return False

        should_speak = bool(getattr(decision, "should_speak", True)) and bool(str(getattr(decision, "text", "") or "").strip())
        surface_override = self._surface_override_note(requested_kind=surface_kind, surface=result.surface)
        self._set_cognitive_action_plan(
            frame,
            should_speak=should_speak,
            speech_intent=str(getattr(decision, "intent", "") or surface_kind),
            speech_act="surface_utterance" if should_speak else "surface_body_only",
            reason="SurfaceArbiter selected the winning low-level surface impulse.",
            snapshot=snapshot,
            concrete_signals=(),
            ti_report=ti_report,
            fe_plan=fe_plan,
            notes=tuple(
                item for item in ("surface_arbiter", f"silent_cycles={self.presence_maintenance_silent_cycles}", surface_override) if item
            ),
        )
        decision = self.ti_governor.enforce_decision(decision, ti_report)
        if bool(getattr(decision, "should_speak", True)):
            decision = self._filter_public_micro_decision(
                decision,
                channel="autonomous",
                frame=frame,
                snapshot=snapshot,
                speech_core=getattr(frame, "speech_core", None),
            )

        should_speak = bool(getattr(decision, "should_speak", True)) and bool(str(getattr(decision, "text", "") or "").strip())
        if not should_speak and not self._is_body_only_presence_decision(decision):
            return False

        now = time.time()
        if should_speak:
            self.fe_style_memory = self.fe_renderer.remember_style(
                self.fe_style_memory,
                plan=fe_plan,
                rendered_text=decision.text,
            )
            self.last_text = decision.text
            self.last_autonomous_spoken_at = now
            self._note_autonomous_spoken(
                presence_maintenance=str(getattr(decision, "intent", "") or "") in {"presence_maintenance", "surface", "micro_presence"},
                reengagement=str(getattr(decision, "intent", "") or "") == "re_engagement",
                now=now,
            )
        else:
            self._note_autonomous_presence_action(
                presence_maintenance=str(getattr(decision, "intent", "") or "") in {"presence_maintenance", "surface", "micro_presence"},
                reengagement=str(getattr(decision, "intent", "") or "") == "re_engagement",
                now=now,
            )

        self._apply_position_update(decision)
        frame.final_decision = self._decision_to_frame_dict(decision)
        if surface_override:
            frame.final_decision["surface_override"] = surface_override.split("=", 1)[-1]
        self._set_cognitive_memory_update(frame, decision=decision, notes=("surface_arbiter",))
        self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
        self._finalize_cognitive_frame(frame)
        self.logger.info(
            '[surface_arbiter] text="%s" | intent=%s | silent_cycles=%d | trace=%s',
            decision.text,
            decision.intent,
            self.presence_maintenance_silent_cycles,
            getattr(decision, "debug_trace", ""),
        )
        self._send_decision_to_body(decision)
        elapsed = time.time() - cycle_start
        sleep_duration = self._choose_autonomous_sleep_duration(
            suppressed=not should_speak,
            ti_mode=getattr(ti_report, "mode", ""),
        )
        self.logger.info("Hoàn tất chu kỳ surface_arbiter trong %.2fs. Nghỉ %ss.", elapsed, sleep_duration)
        self._sleep_interruptible(sleep_duration)
        return True

    def _build_presence_maintenance_decision(
        self,
        *,
        frame: CognitiveFrame | None = None,
        snapshot,
        ti_report,
        social_presence_event: SocialPresenceEvent | None,
        now: float | None = None,
    ) -> Decision | None:
        if not self._should_allow_presence_maintenance(
            snapshot=snapshot,
            ti_report=ti_report,
            social_presence_event=social_presence_event,
            now=now,
        ):
            return None

        cue = self._derive_micro_presence_cue(
            snapshot=snapshot,
            social_presence_event=social_presence_event,
            reason="presence_maintenance",
        )
        if not cue.needs_micro_presence:
            return None
        llm_requested = bool(
            cue.should_call_llm
            or self._should_try_micro_presence_llm(kind="presence_maintenance", force_llm=False)
        )
        if frame is not None:
            return self._build_surface_arbiter_decision(
                frame=frame,
                snapshot=snapshot,
                social_presence_event=social_presence_event,
                surface_kind="presence_maintenance",
                force_llm=llm_requested,
                presence_cue=cue,
            )

        # Legacy fallback path cho call-site cũ chưa truyền frame. Vẫn đi qua SurfaceArbiter.
        text, source = self._generate_micro_presence_from_cue(
            kind="presence_maintenance",
            snapshot=snapshot,
            cue=cue,
            seeds=cue.evidence,
            force_llm=llm_requested,
        )
        if not text:
            return self._body_only_presence_decision(cue, intent="presence_maintenance", parse_mode="presence_maintenance_body_only", source=source)
        return Decision(
            text=text,
            animation="read" if cue.focus_family == "code_stalled" else "stand",
            intent="presence_maintenance",
            action="",
            reasoning_tags=("presence_maintenance", "micro_presence", "llm_wording", cue.focus_family),
            should_speak=True,
            confidence=max(0.38, min(0.62, cue.confidence)),
            parse_mode="presence_maintenance",
            debug_trace=f"presence_maintenance_layer; source={source}; focus_family={cue.focus_family}",
        )

    def _try_finalize_presence_maintenance_cycle(
        self,
        *,
        frame: CognitiveFrame,
        snapshot,
        ti_report,
        fe_plan,
        social_presence_event: SocialPresenceEvent | None,
        cycle_start: float,
    ) -> bool:
        now = time.time()
        decision = self._build_presence_maintenance_decision(
            frame=frame,
            snapshot=snapshot,
            ti_report=ti_report,
            social_presence_event=social_presence_event,
            now=now,
        )
        if decision is None:
            return False
        silent_cycles = self.presence_maintenance_silent_cycles

        self._set_cognitive_action_plan(
            frame,
            should_speak=True,
            speech_intent="presence_maintenance",
            speech_act="micro_presence",
            reason="Presence Maintenance Layer keeps co-presence after repeated quiet cycles.",
            snapshot=snapshot,
            concrete_signals=(),
            ti_report=ti_report,
            fe_plan=fe_plan,
            notes=("presence_maintenance", f"silent_cycles={self.presence_maintenance_silent_cycles}"),
        )
        decision = self.ti_governor.enforce_decision(decision, ti_report)
        if bool(getattr(decision, "should_speak", True)):
            decision.parse_mode = "presence_maintenance"
            decision = self._filter_public_micro_decision(
                decision,
                channel="autonomous",
                frame=frame,
                snapshot=snapshot,
                speech_core=getattr(frame, "speech_core", None),
            )
        if not bool(getattr(decision, "should_speak", True)) or not str(getattr(decision, "text", "") or "").strip():
            if not self._is_body_only_presence_decision(decision):
                return False
        if bool(getattr(decision, "should_speak", True)) and str(getattr(decision, "text", "") or "").strip():
            self.fe_style_memory = self.fe_renderer.remember_style(
                self.fe_style_memory,
                plan=fe_plan,
                rendered_text=decision.text,
            )
            self.last_text = decision.text
            self.last_autonomous_spoken_at = now
            self._note_autonomous_spoken(presence_maintenance=True, now=now)
        else:
            self._note_autonomous_presence_action(presence_maintenance=True, now=now)
        self._apply_position_update(decision)
        frame.final_decision = self._decision_to_frame_dict(decision)
        self._set_cognitive_memory_update(frame, decision=decision, notes=("presence_maintenance",))
        self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
        self._finalize_cognitive_frame(frame)
        self.logger.info(
            '[presence_maintenance] text="%s" | silent_cycles=%d',
            decision.text,
            silent_cycles,
        )
        self._send_decision_to_body(decision)

        elapsed = time.time() - cycle_start
        sleep_duration = self._choose_autonomous_sleep_duration(
            suppressed=False,
            ti_mode=getattr(ti_report, "mode", ""),
        )
        self.logger.info("Hoàn tất chu kỳ presence trong %.2fs. Nghỉ %ss.", elapsed, sleep_duration)
        self._sleep_interruptible(sleep_duration)
        return True

    # ERIS hiện có bao nhiêu năng lượng/xu hướng để chủ động quay lại tương tác với user?
    def _social_energy_for_reengagement(self, internal_state: PersistentInternalState | None) -> float:
        if internal_state is None:
            return 0.0
        values = [
            float(getattr(internal_state, "social_energy", 0.0) or 0.0),#social_energy:mức muốn giao tiếp/chủ động
            float(getattr(internal_state, "attachment", 0.0) or 0.0), #attachment:mức độ gắn bó, có thể hiểu là xu hướng duy trì kết nối với user
        ]
        processes = getattr(internal_state, "mental_processes", None)  #mental_processes có thể chứa nhiều quá trình tâm lý khác nhau, trong đó có social_presence
        social_process = getattr(processes, "social_presence", None) #social_presence: quá trình tâm lý liên quan đến sự hiện diện xã hội
        if social_process is not None:
            values.extend(
                [
                    float(getattr(social_process, "level", 0.0) or 0.0), #social_presence.level: mức độ cảm nhận được sự hiện diện xã hội, có thể ảnh hưởng đến mong muốn tương tác
                    float(getattr(social_process, "pressure", 0.0) or 0.0), #social_presence.pressure: áp lực xã hội, có thể thúc đẩy hoặc cản trở việc chủ động tương tác
                ]
            )
        return max(0.0, min(1.0, max(values)))

    # Kiểm tra xem có tín hiệu nào gần đây cho thấy người dùng vẫn đang hoạt động và có thể không cần re-engagement hay không
    def _has_meaningful_recent_activity(self, snapshot) -> bool:
        if self._has_concrete_screen_signal(snapshot):
            return True
        recent_events = tuple(str(item or "").strip() for item in (getattr(snapshot, "recent_events", ()) or ()) if str(item or "").strip())
        if not recent_events:
            return False
        low_meaning_terms = (
            "general_window_active", #general_window_active: chỉ ra rằng có một cửa sổ đang hoạt động, nhưng không cung cấp thông tin cụ thể về loại cửa sổ hoặc hoạt động nào đang diễn ra, do đó có thể không đủ để đánh giá sự hiện diện hoặc tương tác của người dùng.
            "long_idle_period", #long_idle_period: chỉ ra rằng đã có một khoảng thời gian dài không có hoạt động, nhưng không cung cấp thông tin về loại hoạt động nào đã bị thiếu hoặc mức độ tương tác trước đó, do đó có thể không đủ để đánh giá sự hiện diện hoặc nhu cầu re-engagement.
            "mouse_moved", #   mouse_moved: chỉ ra rằng chuột đã được di chuyển, nhưng không cung cấp thông tin về loại hoạt động nào đang diễn ra hoặc mức độ tương tác của người dùng, do đó có thể không đủ để đánh giá sự hiện diện hoặc nhu cầu re-engagement.
            "cursor",
            "window_active",
            "many_windows_open",
            "browser_url_visible",
        )
        for event in recent_events:
            lowered = event.lower()
            if self._is_speakable_evidence(event, kind="recent_event"):
                return True
            if not self._is_generic_screen_event(event) and not any(term in lowered for term in low_meaning_terms):
                return True
        return False

    def _reengagement_idle_debt_allows(self, idle_seconds: float) -> bool:
        min_idle = float(getattr(self, "reengagement_min_idle_sec", 45.0) or 45.0)
        if idle_seconds >= min_idle:
            return True
        quiet_cycles = int(getattr(self, "reengagement_quiet_cycles", 0) or 0)
        silent_cycles = int(getattr(self, "presence_maintenance_silent_cycles", 0) or 0)
        threshold = int(getattr(self, "reengagement_quiet_loop_threshold", 1) or 1)
        debt_cycles = max(quiet_cycles, silent_cycles)
        if debt_cycles >= max(threshold + 5, 6) and idle_seconds >= 8.0:
            return True
        if debt_cycles >= max(threshold + 2, 3) and idle_seconds >= min(min_idle, 20.0):
            return True
        return False

    # Sau một khoảng thời gian im lặng đủ dài, ERIS có nên chủ động tương tác lại với user không?
    def _should_allow_reengagement(
        self,
        *,
        snapshot,
        ti_report,
        internal_state: PersistentInternalState | None,
        now: float | None = None,
    ) -> bool:
        if not getattr(self, "reengagement_enabled", True): #reengagement_enabled: cờ bật/tắt tính năng re-engagement, nếu False thì ERIS sẽ không chủ động tương tác lại sau khoảng thời gian im lặng, giúp tránh làm phiền người dùng khi họ không muốn tương tác.
            return False
        if self.reengagement_quiet_cycles < self.reengagement_quiet_loop_threshold:
            return False

        # Kiểm tra cooldown để tránh re-engagement quá thường xuyên, giúp ERIS không làm phiền người dùng nếu họ đang bận hoặc không muốn tương tác ngay lập tức sau khi đã có một re-engagement gần đây.
        current_time = time.time() if now is None else now
        if current_time < float(getattr(self, "autonomous_presence_blocked_until", 0.0) or 0.0):
            return False
        cooldown = float(getattr(self, "reengagement_cooldown_sec", 0.0) or 0.0)
        if self.last_reengagement_at > 0.0 and current_time - self.last_reengagement_at < cooldown:
            return False

        mode = str(getattr(ti_report, "mode", "") or "")
        if mode in {"goal_drift_alert", "goal_realign", "system_warning"}:
            return False

        # Kiểm tra xem có tín hiệu nào gần đây cho thấy người dùng vẫn đang hoạt động và có thể không cần re-engagement hay không. Nếu có những tín hiệu này, ERIS sẽ tránh re-engagement để không làm phiền người dùng khi họ đang tương tác bình thường.
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        if not self._reengagement_idle_debt_allows(idle_seconds):
            return False
        if self._has_meaningful_recent_activity(snapshot):
            return False
        return self._social_energy_for_reengagement(internal_state) >= 0.18

    # Dựa trên ngữ cảnh hiện tại của người dùng (như loại cửa sổ đang hoạt động, URL trình duyệt, tóm tắt tập trung), chọn một số câu phù hợp để re-engagement. Những câu này nên cảm thấy liên quan đến tình huống hiện tại của người dùng để tăng khả năng họ sẽ phản hồi tích cực.
    def _reengagement_lines(self, snapshot) -> tuple[str, ...]:
        del snapshot
        return ()
        focus_kind = str(getattr(snapshot, "active_window_kind", "") or "")
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        if focus_kind in {"coding", "documentation"}: #coding, documentation: nếu người dùng đang tập trung vào các cửa sổ liên quan đến lập trình hoặc tài liệu, ERIS có thể chọn những câu re-engagement liên quan đến việc hỗ trợ hoặc cung cấp thông tin hữu ích cho công việc của họ, giúp tăng khả năng tương tác tích cực.
            return (
                "Não vẫn chưa chịu nghỉ à.",
                "Ngài lại chìm mất rồi.",
                "Không gian yên quá.",
                "Ngài ổn chứ.",
            )
        if idle_seconds >= 1200: #idle_seconds: nếu người dùng đã im lặng trong một khoảng thời gian dài (ví dụ: 20 phút hoặc hơn), ERIS có thể chọn những câu re-engagement nhẹ nhàng và quan tâm, như hỏi thăm sức khỏe hoặc đề nghị giúp đỡ, để tạo cơ hội cho người dùng phản hồi mà không cảm thấy bị làm phiền.
            return (
                "Tôi bắt đầu tự hỏi Ngài còn thức không.",
                "Ngài lại chìm mất rồi.",
                "Không gian yên quá.",
            )
        return (
            "Ngài lại chìm mất rồi.",
            "Không gian yên quá.",
            "Hôm nay Ngài im hơn bình thường.",
            "Ngài ổn chứ.",
        )

    # Khi quyết định re-engagement, hãy đảm bảo rằng ERIS không lặp lại cùng một câu hoặc câu quá giống nhau nhiều lần liên tiếp, vì điều này có thể khiến người dùng cảm thấy bị làm phiền hoặc như đang nói chuyện với một cỗ máy lặp đi lặp lại. Việc đa dạng hóa các câu re-engagement có thể giúp giữ cho tương tác cảm thấy tươi mới và tự nhiên hơn.
    def _derive_reengagement_cue(self, *, snapshot, internal_state: PersistentInternalState | None) -> MicroPresenceCue:
        cue = self._derive_micro_presence_cue(snapshot=snapshot, reason="re_engagement")
        social_energy = self._social_energy_for_reengagement(internal_state)
        evidence = (*cue.evidence, f"social_energy={social_energy:.2f}")
        return MicroPresenceCue(
            needs_micro_presence=True,
            focus_family=f"reengagement_{cue.focus_family}",
            confidence=max(cue.confidence, 0.44 + min(0.20, social_energy * 0.20)),
            curiosity=cue.curiosity,
            missing_evidence_ids=cue.missing_evidence_ids,
            body_action="tilt_head" if cue.curiosity >= 0.45 else "idle_shift",
            reason="long_silence_reengagement",
            evidence=tuple(dict.fromkeys(evidence))[:8],
            should_call_llm=social_energy >= 0.18,
            allow_body_only=True,
        )

    def _build_reengagement_decision(
        self,
        *,
        frame: CognitiveFrame | None = None,
        snapshot,
        ti_report,
        internal_state: PersistentInternalState | None,
        now: float | None = None,
    ) -> Decision | None:
        if not self._should_allow_reengagement(
            snapshot=snapshot,
            ti_report=ti_report,
            internal_state=internal_state,
            now=now,
        ):
            return None

        cue = self._derive_reengagement_cue(snapshot=snapshot, internal_state=internal_state)
        if frame is not None:
            return self._build_surface_arbiter_decision(
                frame=frame,
                snapshot=snapshot,
                surface_kind="re_engagement",
                force_llm=True,
                presence_cue=cue,
                extra_impulses=(
                    {
                        "kind": "re_engagement",
                        "source": "long_silence",
                        "confidence": cue.confidence,
                        "score": cue.confidence + 0.02,
                        "topic_seed": f"idle={int(float(getattr(snapshot, 'idle_seconds', 0.0) or 0.0))}s",
                        "family": "re_engagement:long_silence",
                        "evidence": cue.evidence,
                        "reason": "long_silence_reengagement",
                        "focus_family": cue.focus_family,
                        "body_action": cue.body_action,
                        "is_presence": True,
                        "should_surface": True,
                    },
                ),
            )

        text, source = self._generate_micro_presence_from_cue(
            kind="re_engagement",
            snapshot=snapshot,
            cue=cue,
            seeds=cue.evidence,
            force_llm=True,
        )
        if not text:
            return self._body_only_presence_decision(cue, intent="re_engagement", parse_mode="re_engagement_body_only", source=source)
        return Decision(
            text=text,
            animation="stand",
            intent="re_engagement",
            action="",
            reasoning_tags=("re_engagement", "long_silence_outreach", "llm_wording", cue.focus_family),
            should_speak=True,
            confidence=max(0.42, min(0.62, cue.confidence)),
            parse_mode="re_engagement",
            debug_trace=f"reengagement_layer; source={source}; focus_family={cue.focus_family}",
        )
        if not self._should_allow_reengagement(
            snapshot=snapshot,
            ti_report=ti_report,
            internal_state=internal_state,
            now=now,
        ):
            return None

        lines = self._reengagement_lines(snapshot)
        if not lines:
            return None
        fallback_text = self._choose_local_micro_line(
            lines,
            counter=self.reengagement_quiet_cycles,
            threshold=self.reengagement_quiet_loop_threshold,
        )
        if no_fallback_mode_enabled():
            fallback_text = ""
        text, source = self._hybrid_micro_presence_text(
            kind="re_engagement",
            snapshot=snapshot,
            fallback_text=fallback_text,
        )

        return Decision(
            text=text,
            animation="stand",
            intent="re_engagement",
            reasoning_tags=("re_engagement", "long_silence_outreach"),
            should_speak=bool(str(text or "").strip()),
            confidence=0.52,
            parse_mode="re_engagement",
            debug_trace=(
                "reengagement_layer"
                f"; source={source}"
                f"; quiet_cycles={self.reengagement_quiet_cycles}"
                f"; idle={int(float(getattr(snapshot, 'idle_seconds', 0.0) or 0.0))}s"
                f"; social_energy={self._social_energy_for_reengagement(internal_state):.2f}"
            ),
        )

    def _try_finalize_reengagement_cycle(
        self,
        *,
        frame: CognitiveFrame,
        snapshot,
        ti_report,
        fe_plan,
        internal_state: PersistentInternalState | None,
        cycle_start: float,
    ) -> bool:
        now = time.time()
        decision = self._build_reengagement_decision(
            frame=frame,
            snapshot=snapshot,
            ti_report=ti_report,
            internal_state=internal_state,
            now=now,
        )
        if decision is None:
            return False
        quiet_cycles = self.reengagement_quiet_cycles

        self._set_cognitive_action_plan(
            frame,
            should_speak=True,
            speech_intent="re_engagement",
            speech_act="reengagement",
            reason="Re-engagement Layer gently reconnects after a long quiet stretch.",
            snapshot=snapshot,
            concrete_signals=(),
            ti_report=ti_report,
            fe_plan=fe_plan,
            notes=("re_engagement", f"quiet_cycles={quiet_cycles}"),
        )
        decision = self.ti_governor.enforce_decision(decision, ti_report)
        if bool(getattr(decision, "should_speak", True)):
            decision.parse_mode = "re_engagement"
            decision = self._filter_public_micro_decision(
                decision,
                channel="autonomous",
                frame=frame,
                snapshot=snapshot,
                speech_core=getattr(frame, "speech_core", None),
            )
        if not bool(getattr(decision, "should_speak", True)) or not str(getattr(decision, "text", "") or "").strip():
            if not self._is_body_only_presence_decision(decision):
                return False
        if bool(getattr(decision, "should_speak", True)) and str(getattr(decision, "text", "") or "").strip():
            self.fe_style_memory = self.fe_renderer.remember_style(
                self.fe_style_memory,
                plan=fe_plan,
                rendered_text=decision.text,
            )
            self.last_text = decision.text
            self.last_autonomous_spoken_at = now
            self._note_autonomous_spoken(reengagement=True, now=now)
        else:
            self._note_autonomous_presence_action(reengagement=True, now=now)
        self._apply_position_update(decision)
        frame.final_decision = self._decision_to_frame_dict(decision)
        self._set_cognitive_memory_update(frame, decision=decision, notes=("re_engagement",))
        self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
        self._finalize_cognitive_frame(frame)
        self.logger.info(
            '[re_engagement] text="%s" | quiet_cycles=%d',
            decision.text,
            quiet_cycles,
        )
        self._send_decision_to_body(decision)

        elapsed = time.time() - cycle_start
        sleep_duration = self._choose_autonomous_sleep_duration(
            suppressed=False,
            ti_mode=getattr(ti_report, "mode", ""),
        )
        self.logger.info("Hoàn tất chu kỳ re-engagement trong %.2fs. Nghỉ %ss.", elapsed, sleep_duration)
        self._sleep_interruptible(sleep_duration)
        return True


    def _load_presence_maintenance_enabled(self) -> bool:
        flag = os.environ.get("ERIS_PRESENCE_MAINTENANCE", "1").strip().lower()
        return flag not in {"0", "false", "no", "off"}

    def _load_presence_maintenance_silent_loop_threshold(self) -> int:
        raw = os.environ.get("ERIS_PRESENCE_MAINTENANCE_SILENT_LOOPS", "1").strip()
        try:
            return max(1, int(raw))
        except ValueError:
            return 1

    def _load_presence_maintenance_cooldown(self) -> float:
        raw = os.environ.get("ERIS_PRESENCE_MAINTENANCE_COOLDOWN_SEC", "12").strip()
        try:
            return max(0.0, float(raw))
        except ValueError:
            return 12.0

    def _load_micro_presence_llm_enabled(self) -> bool:
        flag = os.environ.get("ERIS_MICRO_PRESENCE_LLM", "1").strip().lower()
        return flag not in {"0", "false", "no", "off"}

    def _load_micro_presence_llm_probability(self) -> float:
        raw = os.environ.get("ERIS_MICRO_PRESENCE_LLM_PROBABILITY", "0.85").strip()
        try:
            return max(0.0, min(1.0, float(raw)))
        except ValueError:
            return 0.85

    def _load_reengagement_enabled(self) -> bool:
        flag = os.environ.get("ERIS_REENGAGEMENT", "1").strip().lower()
        return flag not in {"0", "false", "no", "off"}

    def _load_reengagement_quiet_loop_threshold(self) -> int:
        raw = os.environ.get("ERIS_REENGAGEMENT_QUIET_LOOPS", "1").strip()
        try:
            return max(1, int(raw))
        except ValueError:
            return 1

    def _load_reengagement_min_idle(self) -> float:
        raw = os.environ.get("ERIS_REENGAGEMENT_MIN_IDLE_SEC", "45").strip()
        try:
            return max(20.0, float(raw))
        except ValueError:
            return 45.0

    def _load_reengagement_cooldown(self) -> float:
        raw = os.environ.get("ERIS_REENGAGEMENT_COOLDOWN_SEC", "45").strip()
        try:
            return max(0.0, float(raw))
        except ValueError:
            return 45.0
