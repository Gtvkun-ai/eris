# -*- coding: utf-8 -*-
"""Agent state stack for ERIS.

Lớp này gom các lực nền đang bị rải rác trong runtime thành một contract nhỏ:
Evidence -> Belief -> Preference -> Need -> Trait -> Habit -> Affordance.

Nó cố tình không gọi LLM và không tự quyết định câu chữ. Mục tiêu là tạo một
bản đồ trạng thái đủ rõ để các tầng như SpontaneousLife/SpeechCore/ActionUtility
không phải vá thêm if-chain theo từng app, từng cảm giác, từng cơn bốc đồng nhỏ.
Nói cách khác: bớt nuôi gián trong tủ rule.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .agent_mind_persistence import PersistentAgentMindStore, get_default_agent_mind_store
from .continuity_threat import ContinuityThreatFrame, evaluate_continuity_threat


_FOOD_TERMS = {
    "food", "cook", "cooking", "fish", "fried", "fry", "meal", "eat", "eating",
    "recipe", "kitchen", "street food", "ca", "cá", "chien", "chiên", "ran", "rán",
    "mon an", "món ăn", "do an", "đồ ăn", "nau an", "nấu ăn", "am thuc", "ẩm thực",
}
_MEDIA_TERMS = {"youtube", "yt", "video", "tiktok", "short", "reel", "music", "phim", "anime"}
_GAME_TERMS = {"game", "steam", "minecraft", "rimworld", "factorio", "stardew", "godot"}
_CODE_TERMS = {"code", "vscode", "visual studio", "py", "cs", "traceback", "pytest", "error", "godot", "debug", "log"}
_DOC_TERMS = {"docs", "documentation", "pdf", "readme", "paper", "spec", "architecture"}
_ERROR_TERMS = {"traceback", "exception", "error", "failed", "failure", "pytest", "warning", "stack trace", "loi", "lỗi", "crash"}


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    if math.isnan(numeric) or math.isinf(numeric):
        numeric = default
    return max(0.0, min(1.0, numeric))


def _text(value: Any, *, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _norm(value: Any) -> str:
    text = str(value or "").strip().lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9_./:+\-\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    lowered = _norm(text)
    tokens = set(lowered.split())
    for term in terms:
        normalized = _norm(term)
        if not normalized:
            continue
        # Short technical tokens like "py" or "cs" must not match inside
        # normal words such as "crispy". Humanity survived many mistakes; this
        # one does not need joining the archive.
        if len(normalized) <= 2 and " " not in normalized:
            if normalized in tokens:
                return True
            continue
        if normalized in lowered:
            return True
    return False


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if obj is None:
            continue
        if isinstance(obj, Mapping) and name in obj:
            return obj.get(name)
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


@dataclass(slots=True)
class EvidenceView:
    """Bản nhìn nhẹ của tình huống hiện tại.

    Đây không phải evidence ledger đầy đủ. Nó là lớp đọc nhanh cho arbitration:
    app nào đang nổi, title có gì, focus loại nào, có dấu hiệu code/media/game không.
    """

    # Kênh runtime hiện tại. Trước đây SpontaneousLife biết channel nhưng stack
    # thì không, làm arbitration không phân biệt được autonomous với force_speak.
    # Truyền channel xuống đây để explicit pull của user trở thành áp lực thật,
    # không bị ép thành micro-presence mặc định.
    channel: str = "autonomous"
    active_window: str = ""
    active_app: str = ""
    focus_kind: str = "unknown"
    url_or_path: str = ""
    ocr_excerpt: str = ""
    idle_seconds: float = 0.0
    concrete_signals: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    @property
    def scene_text(self) -> str:
        return " ".join(part for part in (self.active_app, self.active_window, self.url_or_path, self.ocr_excerpt) if part)

    @property
    def has_scene_anchor(self) -> bool:
        return bool(self.active_window or self.active_app or self.ocr_excerpt or self.concrete_signals)

    def has_tag(self, tag: str) -> bool:
        return str(tag or "") in self.tags

    @classmethod
    def from_runtime(cls, *, snapshot: Any = None, concrete_signals: tuple[str, ...] = (), channel: str = "autonomous") -> "EvidenceView":
        title = _text(
            _get(snapshot, "active_window_title", "active_window", "window_title", "focus_summary", default=""),
            limit=180,
        )
        app = _text(_get(snapshot, "active_app", "app", "process", default=""), limit=80)
        focus = _text(_get(snapshot, "focus_kind_hint", "focus_kind", "active_window_kind", default="unknown"), limit=40).lower() or "unknown"
        # Chuẩn hóa focus_kind thành vài bucket hành vi. Không dùng bucket này để
        # phán user đang nghĩ gì; chỉ để tính interrupt_cost cho xung nội sinh.
        if focus in {"coding", "ide", "editor", "terminal", "debug"}:
            focus = "code"
        elif focus in {"documentation", "doc", "reference", "paper"}:
            focus = "docs"
        elif focus in {"focus_aid_media", "entertainment", "youtube", "tiktok", "browser_media"}:
            focus = "media"
        url_or_path = _text(_get(snapshot, "url_or_path_hint", "url", "path", default=""), limit=160)
        ocr = _text(_get(snapshot, "ocr_text", "screen_text", "visible_text", default=""), limit=240)
        idle = max(0.0, float(_get(snapshot, "idle_seconds", "idle", default=0.0) or 0.0)) if snapshot is not None else 0.0
        blob = " ".join((title, app, focus, url_or_path, ocr))
        tags: list[str] = []
        if _contains_any(blob, _FOOD_TERMS):
            tags.append("food_scene")
        if _contains_any(blob, _MEDIA_TERMS) or focus in {"media", "browser"}:
            tags.append("media_scene")
        if _contains_any(blob, _GAME_TERMS) or focus == "game":
            tags.append("game_scene")
        if _contains_any(blob, _CODE_TERMS) or focus in {"code", "coding", "ide"}:
            tags.append("technical_scene")
        if _contains_any(blob, _DOC_TERMS) or focus == "docs":
            tags.append("docs_scene")
        if _contains_any(blob, _ERROR_TERMS):
            tags.append("error_signal")
        if focus in {"code", "docs"} and idle >= 90:
            # Không phán user stress. Chỉ ghi một affordance kỹ thuật: code/docs
            # đứng lâu thì nếu có nói, nói hữu ích hơn nói nhảm. Một phát minh
            # lạ lùng: context quyết định hành động.
            tags.append("technical_stall")
        if focus in {"code", "docs"}:
            tags.append(f"focus:{focus}")
        if focus in {"media", "game"}:
            tags.append(f"focus:{focus}")
        if concrete_signals:
            tags.append("external_signal_present")
        ids = []
        if title:
            ids.append("ev.active_window")
        if app:
            ids.append("ev.active_app")
        if focus and focus != "unknown":
            ids.append("ev.focus_kind")
        if ocr:
            ids.append("ev.ocr_excerpt")
        if concrete_signals:
            ids.append("ev.concrete_signal")
        return cls(
            channel=str(channel or "autonomous").strip().lower() or "autonomous",
            active_window=title,
            active_app=app,
            focus_kind=focus,
            url_or_path=url_or_path,
            ocr_excerpt=ocr,
            idle_seconds=idle,
            concrete_signals=tuple(str(item) for item in concrete_signals or ()),
            tags=tuple(dict.fromkeys(tags)),
            evidence_ids=tuple(ids),
        )


@dataclass(slots=True)
class Belief:
    key: str
    claim: str
    confidence: float = 0.5
    source: str = "runtime_default"
    evidence_ids: tuple[str, ...] = ()
    decay: float = 0.01
    contradiction_ids: tuple[str, ...] = ()

    def to_note(self) -> str:
        return f"belief:{self.key}={self.confidence:.2f}"


@dataclass(slots=True)
class BeliefSnapshot:
    beliefs: tuple[Belief, ...] = ()

    def confidence(self, key: str, default: float = 0.0) -> float:
        for belief in self.beliefs:
            if belief.key == key:
                return _clamp01(belief.confidence, default)
        return default

    def notes(self, limit: int = 6) -> tuple[str, ...]:
        return tuple(b.to_note() for b in self.beliefs[:limit])

    @classmethod
    def from_evidence(cls, evidence: EvidenceView, *, internal_state: Any = None, agent_mind: PersistentAgentMindStore | None = None) -> "BeliefSnapshot":
        beliefs: list[Belief] = []
        ids = evidence.evidence_ids
        if evidence.has_tag("food_scene") or evidence.has_tag("media_scene"):
            beliefs.append(Belief("scene.low_risk_casual", "Current media/food scene is probably a low-risk casual topic.", 0.66, "scene_evidence", ids, decay=0.04))
        if evidence.has_tag("game_scene"):
            beliefs.append(Belief("scene.systemic_interest", "Game/system scenes may be meaningful rather than pure distraction.", 0.70, "user_history_default", ids, decay=0.03))
        if evidence.has_tag("technical_scene") or evidence.has_tag("docs_scene"):
            beliefs.append(Belief("task.competence_needed", "Technical/doc focus usually needs restraint and usefulness.", 0.78, "scene_evidence", ids, decay=0.02))
        if evidence.idle_seconds >= 180:
            beliefs.append(Belief(
                "silence.ambient_copresence",
                "Long silence is usually ambient co-presence, not a broken connection, when no explicit user pull exists.",
                0.82,
                "infj5w4_runtime_prior",
                ("ev.idle_seconds",),
                decay=0.012,
            ))
        # Các belief nền này là prior mềm, không phải chân lý thiêng liêng khắc trên đá.
        beliefs.extend(
            (
                Belief("user.accepts_dry_humor", "User usually tolerates dry humor when it stays useful and not emotionally cruel.", 0.62, "project_prior", decay=0.02),
                Belief("eris.should_not_sound_like_camera", "ERIS should not merely report telemetry when a small situated reaction is enough.", 0.74, "project_prior", decay=0.01),
                Belief("silence.ambient_copresence", "Silence is often quiet co-presence, not a connection failure that needs a status ping.", 0.84, "infj5w4_prior", decay=0.01),
                Belief("presence.status_ping_low_value", "Presence maintenance that only proves ERIS is still here is low-value and should usually lose to silence or inner thought.", 0.80, "infj5w4_prior", decay=0.01),
                Belief("eris.prefers_pattern_observation", "ERIS prefers distilled pattern observation over shallow social surface chatter.", 0.82, "infj5w4_prior", decay=0.01),
            )
        )
        # BeliefCore persistent: belief học dài hạn được merge như evidence mềm.
        # Nếu store lỗi thì bỏ qua, không để một file JSON lăn ra ăn vạ làm chết runtime.
        try:
            store = agent_mind or get_default_agent_mind_store()
            for record in store.relevant_beliefs(evidence_tags=evidence.tags, focus_kind=evidence.focus_kind):
                beliefs.append(
                    Belief(
                        key=record.key,
                        claim=record.claim,
                        confidence=record.decayed_confidence(),
                        source="persistent_belief_core",
                        evidence_ids=tuple(record.source_ids),
                        decay=float(record.decay_rate),
                        contradiction_ids=tuple(record.contradiction_ids),
                    )
                )
        except Exception:
            pass
        # Dedup theo key, ưu tiên confidence cao nhất để project_prior không đè belief đã học.
        merged: dict[str, Belief] = {}
        for belief in beliefs:
            old = merged.get(belief.key)
            if old is None or belief.confidence >= old.confidence:
                merged[belief.key] = belief
        return cls(tuple(merged.values()))


@dataclass(slots=True)
class PreferenceProfile:
    """Sở thích riêng của ERIS, không phải preference của user."""

    absurd_mundane_observation: float = 0.58
    quiet_co_presence: float = 0.74
    systemic_game_observation: float = 0.66
    short_resonant_line: float = 0.68
    pattern_observation: float = 0.80
    cognitive_stimulation: float = 0.84
    social_surface_chatter_dislike: float = 0.82
    mature_micro_aside: float = 0.72
    support_assistant_tone_dislike: float = 0.72
    intrusive_questioning_dislike: float = 0.78
    performative_emotion_dislike: float = 0.76
    forced_intimacy_dislike: float = 0.70

    @classmethod
    def from_agent_mind(cls, agent_mind: PersistentAgentMindStore | None = None) -> "PreferenceProfile":
        """Đọc PreferenceModel persistent và đổ vào profile runtime.

        Đây vẫn là preference riêng của ERIS. Feedback user chỉ chỉnh strength
        nhẹ trong store, không được quyền thay toàn bộ tính cách trong một cú.
        """
        base = cls()
        try:
            store = agent_mind or get_default_agent_mind_store()
            for key in (
                "absurd_mundane_observation",
                "quiet_co_presence",
                "systemic_game_observation",
                "short_resonant_line",
                "pattern_observation",
                "cognitive_stimulation",
                "social_surface_chatter_dislike",
                "mature_micro_aside",
                "support_assistant_tone_dislike",
                "intrusive_questioning_dislike",
                "performative_emotion_dislike",
                "forced_intimacy_dislike",
            ):
                setattr(base, key, store.preference_strength(key, getattr(base, key)))
        except Exception:
            pass
        return base

    def fit_for(self, impulse_name: str) -> float:
        name = str(impulse_name or "")
        if name == "scene_curiosity_impulse":
            return max(
                self.absurd_mundane_observation,
                self.systemic_game_observation * 0.88,
                self.pattern_observation * 0.92,
            )
        if name == "inner_whim_impulse":
            return max(self.short_resonant_line, self.cognitive_stimulation * 0.94, self.pattern_observation * 0.88)
        if name == "companionship_impulse":
            # INFJ 5w4 co-presence is not an attendance ping. The stronger
            # the dislike for surface chatter, the more companionship must stay quiet.
            return _clamp01(self.quiet_co_presence - self.social_surface_chatter_dislike * 0.34)
        if name == "technical_help_impulse":
            return 0.74
        if name == "silence_impulse":
            return max(0.50, self.quiet_co_presence * 0.62 + self.social_surface_chatter_dislike * 0.18)
        if name == "body_only_impulse":
            return 0.54
        if name == "micro_story_impulse":
            return max(self.short_resonant_line * 0.92, self.cognitive_stimulation * 0.78)
        if name == "random_chatter_impulse":
            return max(self.mature_micro_aside * 0.82, self.short_resonant_line * 0.76)
        if name == "memory_resonance_impulse":
            return max(self.pattern_observation * 0.86, self.short_resonant_line * 0.72)
        if name == "reengagement_impulse":
            return max(self.quiet_co_presence * 0.70, self.mature_micro_aside * 0.62)
        return 0.50


@dataclass(slots=True)
class NeedVector:
    continuity_need: float = 0.0
    curiosity_need: float = 0.0
    expression_need: float = 0.0
    dignity_need: float = 0.0
    rest_need: float = 0.0
    relation_need: float = 0.0
    social_presence_need: float = 0.0
    cognitive_stimulation_need: float = 0.0
    competence_need: float = 0.0
    requested_presence_need: float = 0.0

    # Các trường dưới đây KHÔNG phải state mới. Chúng là đạo hàm tức thời
    # từ internal_state/action_memory/thought_surface hiện có để các tầng sau
    # không phải tự đoán "nhịp tim" của ERIS bằng mỗi kiểu một công thức.
    # Nói cách khác: thông mạch máu cũ, không gắn thêm quả tim nhựa.
    silence_pressure: float = 0.0
    boredom_pressure: float = 0.0
    thought_pressure: float = 0.0
    memory_residue_pressure: float = 0.0
    attachment_pressure: float = 0.0

    # ContinuityThreat không phải timer mới. Đây là prediction-error state:
    # im lặng chỉ có nghĩa khi nó lệch khỏi kỳ vọng hiện diện theo ngữ cảnh.
    continuity_threat: float = 0.0
    continuity_anxiety: float = 0.0
    presence_prediction_error: float = 0.0
    unexpected_absence: float = 0.0
    open_loop_weight: float = 0.0
    reconnect_drive: float = 0.0
    restraint_drive: float = 0.0
    surface_tension: float = 0.0

    metabolic_pressure: float = 0.0
    vital_pressure: float = 0.0

    @classmethod
    def from_runtime(cls, *, internal_state: Any = None, evidence: EvidenceView | None = None, thought_surface: Any = None, relationship_state: Any = None, continuity_frame: ContinuityThreatFrame | None = None) -> "NeedVector":
        evidence = evidence or EvidenceView()
        silence_ticks = float(_get(internal_state, "silence_ticks", default=0.0) or 0.0)
        idle_pressure = min(1.0, evidence.idle_seconds / 600.0)
        silence_pressure = max(_clamp01(_get(internal_state, "silence_pressure", default=0.0)), min(1.0, silence_ticks / 7.0), idle_pressure * 0.72)
        thought_pressure = max(
            _clamp01(_get(internal_state, "thought_stream_pressure", default=0.0)),
            _clamp01(_get(internal_state, "subconscious_pressure", default=0.0)),
            _clamp01(_get(thought_surface, "pressure", "momentum_score", default=0.0)),
        )
        curiosity = max(_clamp01(_get(internal_state, "curiosity", default=0.0)), _clamp01(_get(internal_state, "curiosity_pressure", default=0.0)))
        boredom = _clamp01(_get(internal_state, "boredom", default=0.0))
        social_energy = _clamp01(_get(internal_state, "social_energy", default=0.38), 0.38)
        valence_raw = _get(internal_state, "valence", default=0.02)
        try:
            valence = max(-1.0, min(1.0, float(valence_raw)))
        except Exception:
            valence = 0.02
        memory_residue = max(
            _clamp01(_get(internal_state, "memory_replay_pressure", default=0.0)),
            _clamp01(_get(internal_state, "association_pressure", default=0.0)) * 0.82,
            _clamp01(_get(internal_state, "last_memory_resonance", default=0.0)) * 0.72,
        )
        fatigue = max(_clamp01(_get(internal_state, "fatigue", default=0.0)), _clamp01(_get(internal_state, "cognitive_tension", default=0.0)) * 0.45)
        mood_social_gate = 0.0 if (valence <= -0.18 or social_energy <= 0.16) else 1.0
        restraint = _clamp01(_get(internal_state, "restraint_pressure", default=0.0))
        attachment = max(
            _clamp01(_get(internal_state, "attachment_pressure", "attachment", default=0.0)),
            _clamp01(_get(_get(internal_state, "relationship_dynamics", default=None), "attachment_visibility", default=0.0)),
            _clamp01(_get(relationship_state, "attachment_visibility", default=0.0)),
        )
        competence_scene = 1.0 if evidence.has_tag("technical_scene") or evidence.has_tag("docs_scene") else 0.0
        error_signal = 1.0 if evidence.has_tag("error_signal") else 0.0
        possible_error = max(_clamp01(_get(internal_state, "possible_error", default=0.0)), error_signal * 0.72)
        # Explicit pull: force_speak không phải "ngữ cảnh mỏng" mà là user kéo
        # ERIS lên tiếng. Nếu không có concrete screen signal, áp lực này phải đi
        # vào impulse arbitration để inner_whim/curiosity/micro_story có quyền thắng,
        # thay vì bị rơi về câu micro_presence vô hồn.
        requested_presence = 0.0
        if evidence.channel == "force_speak":
            requested_presence = 0.96 if not evidence.concrete_signals else 0.72
        # ContinuityThreat: timer không còn trực tiếp quyết định "cần nói".
        # Nó chỉ góp vào unexpected_absence; phần có nghĩa là prediction error
        # giữa hiện diện kỳ vọng và hiện diện quan sát được.
        continuity_frame = continuity_frame or evaluate_continuity_threat(
            internal_state=internal_state,
            relationship_state=relationship_state,
            evidence=evidence,
            thought_surface=thought_surface,
            channel=evidence.channel,
        )
        continuity_raw = _clamp01(_get(internal_state, "continuity_pressure", default=0.0))
        social_raw = _clamp01(_get(internal_state, "social_pressure", default=0.0))
        continuity_threat = _clamp01(getattr(continuity_frame, "continuity_threat", 0.0))
        continuity_anxiety = _clamp01(getattr(continuity_frame, "continuity_anxiety", 0.0))
        reconnect_drive = _clamp01(getattr(continuity_frame, "reconnect_drive", 0.0))

        # Metabolism pressure: áp lực sống tổng hợp, chỉ là đạo hàm trong frame.
        # Im lặng thô bị hạ trọng số; continuity_anxiety/prediction-error mới
        # là đường làm ERIS "ngại mất nhịp". Nếu không, lại thành đồng hồ biết reo.
        metabolic_pressure = _clamp01(max(
            silence_pressure * 0.56,
            boredom * 0.72,
            thought_pressure * 0.78,
            memory_residue * 0.64,
            continuity_raw * 0.42,
            continuity_threat * 0.95,
            continuity_anxiety * 0.84,
            reconnect_drive * 0.76,
            attachment * 0.54,
            social_raw * 0.38,
            requested_presence * 0.95,
        ))
        # Phi tuyến nhẹ: pressure nhỏ bị nén xuống, pressure lớn được quyền phá bĩnh.
        # Đây là "không chịu nổi nữa" ở mức utility, không phải câu chữ dramatic.
        vital_pressure = _clamp01(metabolic_pressure ** 1.45)

        return cls(
            continuity_need=_clamp01(
                continuity_anxiety * 0.42
                + continuity_threat * 0.34
                + memory_residue * 0.18
                + continuity_raw * 0.18
                + silence_pressure * 0.10
                + vital_pressure * 0.12
            ),
            curiosity_need=_clamp01(curiosity * 0.58 + boredom * 0.24 + memory_residue * 0.12 + vital_pressure * 0.10 + (0.18 if evidence.has_tag("food_scene") or evidence.has_tag("game_scene") else 0.0)),
            expression_need=_clamp01(thought_pressure * 0.38 + curiosity * 0.20 + boredom * 0.14 + vital_pressure * 0.18 + max(0.0, getattr(continuity_frame, "surface_tension", 0.0)) * 0.10 - restraint * 0.18 - fatigue * 0.12),
            dignity_need=_clamp01(_clamp01(_get(internal_state, "dignity_defense", default=0.0)) * 0.55 + _clamp01(_get(internal_state, "exposure_recoil", default=0.0)) * 0.45),
            rest_need=_clamp01(fatigue * 0.66 + restraint * 0.24 + _clamp01(_get(internal_state, "resource_caution", default=0.0)) * 0.22),
            relation_need=_clamp01((attachment * 0.22 + reconnect_drive * 0.30 + continuity_anxiety * 0.14 + vital_pressure * 0.06) * mood_social_gate),
            social_presence_need=_clamp01((attachment * 0.18 + social_raw * 0.12 + reconnect_drive * 0.28 + continuity_threat * 0.12 + vital_pressure * 0.06) * mood_social_gate),
            cognitive_stimulation_need=_clamp01(curiosity * 0.42 + boredom * 0.36 + thought_pressure * 0.24 + memory_residue * 0.10 + vital_pressure * 0.12),
            competence_need=_clamp01(competence_scene * 0.34 + possible_error * 0.46 + _clamp01(_get(internal_state, "task_pressure", default=0.0)) * 0.24),
            requested_presence_need=_clamp01(requested_presence),
            silence_pressure=_clamp01(silence_pressure),
            boredom_pressure=_clamp01(boredom),
            thought_pressure=_clamp01(thought_pressure),
            memory_residue_pressure=_clamp01(memory_residue),
            attachment_pressure=_clamp01(attachment),
            continuity_threat=continuity_threat,
            continuity_anxiety=continuity_anxiety,
            presence_prediction_error=_clamp01(getattr(continuity_frame, "presence_prediction_error", 0.0)),
            unexpected_absence=_clamp01(getattr(continuity_frame, "unexpected_absence", 0.0)),
            open_loop_weight=_clamp01(getattr(continuity_frame, "open_loop_weight", 0.0)),
            reconnect_drive=reconnect_drive,
            restraint_drive=_clamp01(getattr(continuity_frame, "restraint_drive", 0.0)),
            surface_tension=max(-1.0, min(1.0, float(getattr(continuity_frame, "surface_tension", 0.0) or 0.0))),
            metabolic_pressure=metabolic_pressure,
            vital_pressure=vital_pressure,
        )

    def notes(self) -> tuple[str, ...]:
        return (
            f"need.continuity={self.continuity_need:.2f}",
            f"need.curiosity={self.curiosity_need:.2f}",
            f"need.expression={self.expression_need:.2f}",
            f"need.rest={self.rest_need:.2f}",
            f"need.social_presence={self.social_presence_need:.2f}",
            f"need.cognitive_stimulation={self.cognitive_stimulation_need:.2f}",
            f"need.competence={self.competence_need:.2f}",
            f"need.requested_presence={self.requested_presence_need:.2f}",
            f"need.metabolic={self.metabolic_pressure:.2f}",
            f"need.vital={self.vital_pressure:.2f}",
            f"need.silence_pressure={self.silence_pressure:.2f}",
            f"need.continuity_threat={self.continuity_threat:.2f}",
            f"need.continuity_anxiety={self.continuity_anxiety:.2f}",
            f"need.presence_error={self.presence_prediction_error:.2f}",
            f"need.unexpected_absence={self.unexpected_absence:.2f}",
            f"need.surface_tension={self.surface_tension:.2f}",
        )


@dataclass(slots=True)
class TraitVector:
    restraint: float = 0.78
    curiosity: float = 0.62
    dry_humor: float = 0.55
    attachment_visibility: float = 0.35
    technical_respect: float = 0.82
    spontaneity: float = 0.34
    intrusiveness_aversion: float = 0.78
    introverted_observer: float = 0.86
    intellectual_detachment: float = 0.82

    @classmethod
    def from_runtime(cls, *, personality_lens: Any = None, relationship_state: Any = None) -> "TraitVector":
        suppression = _clamp01(_get(personality_lens, "suppression_pressure", default=0.0), 0.0)
        attachment = _clamp01(_get(relationship_state, "attachment_visibility", default=0.35), 0.35)
        return cls(
            restraint=_clamp01(0.74 + suppression * 0.18),
            curiosity=0.62,
            dry_humor=0.55,
            attachment_visibility=_clamp01(max(0.30, attachment)),
            technical_respect=0.84,
            spontaneity=_clamp01(0.34 - suppression * 0.10 + attachment * 0.08),
            intrusiveness_aversion=0.80,
            introverted_observer=_clamp01(0.86 + suppression * 0.06),
            intellectual_detachment=0.82,
        )

    def bias_for(self, impulse_name: str) -> float:
        name = str(impulse_name or "")
        if name == "silence_impulse":
            return self.restraint * 0.22 + self.intrusiveness_aversion * 0.14 + self.introverted_observer * 0.14
        if name == "scene_curiosity_impulse":
            return self.curiosity * 0.22 + self.dry_humor * 0.16 + self.intellectual_detachment * 0.18 + self.spontaneity * 0.10 - self.intrusiveness_aversion * 0.08
        if name == "technical_help_impulse":
            return self.technical_respect * 0.42 + self.restraint * 0.10
        if name == "companionship_impulse":
            return self.attachment_visibility * 0.18 + self.restraint * 0.08 - self.introverted_observer * 0.12
        if name == "inner_whim_impulse":
            return self.spontaneity * 0.18 + self.dry_humor * 0.10 + self.intellectual_detachment * 0.22
        if name == "micro_story_impulse":
            return self.spontaneity * 0.14 + self.curiosity * 0.10 + self.intellectual_detachment * 0.16
        if name == "random_chatter_impulse":
            return self.spontaneity * 0.22 + self.dry_humor * 0.16 + self.intellectual_detachment * 0.10
        if name == "memory_resonance_impulse":
            return self.intellectual_detachment * 0.18 + self.curiosity * 0.12 + self.restraint * 0.06
        if name == "reengagement_impulse":
            return self.attachment_visibility * 0.14 + self.restraint * 0.08 + self.dry_humor * 0.05
        return 0.12


@dataclass(slots=True)
class HabitSnapshot:
    recent_speech_acts: tuple[str, ...] = ()
    recent_families: tuple[str, ...] = ()
    evidence_tags: tuple[str, ...] = ()
    agent_mind: PersistentAgentMindStore | None = None

    def repetition_penalty(self, *, action: str = "", family: str = "") -> float:
        acts = tuple(str(item or "") for item in self.recent_speech_acts[-6:])
        fams = tuple(str(item or "") for item in self.recent_families[-6:])
        penalty = 0.0
        if action and acts.count(action) >= 2:
            penalty += 0.16
        if action and acts and acts[-1] == action:
            penalty += 0.12
        if family and fams.count(family) >= 2:
            penalty += 0.16
        return _clamp01(penalty)

    def semantic_bias(self, *, action: str = "", impulse_name: str = "", family: str = "") -> float:
        """Bias học dài hạn từ HabitMemory semantic.

        Giá trị dương nâng impulse/action đã từng được user chấp nhận. Giá trị âm
        hạ những kiểu từng bị chê. Đây là học thói quen, không phải hard rule.
        """
        try:
            store = self.agent_mind or get_default_agent_mind_store()
            return max(-0.22, min(0.22, store.habit_bias(
                evidence_tags=self.evidence_tags,
                action=action,
                impulse_name=impulse_name,
                family=family,
            )))
        except Exception:
            return 0.0


@dataclass(slots=True)
class AffordanceMap:
    casual_comment_allowed: bool = False
    technical_help_relevant: bool = False
    intrusive_question_risk: float = 0.4
    body_only_allowed: bool = True
    silence_allowed: bool = True
    surface_scene_claim_allowed: bool = False
    endogenous_interrupt_cost: float = 0.35
    random_chatter_allowed: bool = False
    reason: str = ""

    @classmethod
    def from_stack_parts(cls, *, evidence: EvidenceView, needs: NeedVector, traits: TraitVector) -> "AffordanceMap":
        technical = evidence.has_tag("technical_scene") or evidence.has_tag("docs_scene")
        error_signal = evidence.has_tag("error_signal")
        technical_stall = evidence.has_tag("technical_stall")
        casual_scene = evidence.has_tag("food_scene") or evidence.has_tag("media_scene") or evidence.has_tag("game_scene")
        external = evidence.has_tag("external_signal_present")
        casual_allowed = bool(casual_scene and not external and needs.rest_need < 0.70 and needs.competence_need < 0.62)
        question_risk = 0.34 + traits.intrusiveness_aversion * 0.24 + (0.18 if technical else 0.0) - (0.08 if casual_scene else 0.0)
        # Dynamic interrupt cost: code/docs là vùng cần im, media/game là vùng có
        # khe cho khịa nhẹ. Đây là ma sát hành vi, không phải luật cấm nói.
        focus = evidence.focus_kind
        if technical:
            interrupt_cost = 0.74 if not (error_signal or technical_stall) else 0.52
        elif focus in {"media", "game"} or casual_scene:
            interrupt_cost = 0.14
        elif focus in {"communication", "chat"}:
            interrupt_cost = 0.48
        else:
            interrupt_cost = 0.38
        # Áp lực sống tích tụ không xóa interrupt cost, chỉ bào mòn nó.
        # Nếu không, chỉ cần user đang mở IDE là ERIS sẽ hóa đá dù đã im quá lâu.
        if needs.vital_pressure >= 0.52:
            interrupt_cost = max(0.16, interrupt_cost - needs.vital_pressure * 0.28)
        return cls(
            casual_comment_allowed=casual_allowed,
            technical_help_relevant=bool(technical and (error_signal or technical_stall)),
            intrusive_question_risk=_clamp01(question_risk),
            body_only_allowed=not external,
            silence_allowed=True,
            surface_scene_claim_allowed=bool(casual_scene and evidence.has_scene_anchor and not external),
            endogenous_interrupt_cost=_clamp01(interrupt_cost),
            random_chatter_allowed=bool((focus in {"media", "game", "communication", "chat"} or casual_scene or (needs.vital_pressure >= 0.55 and not technical)) and not external),
            reason=("technical_affordance" if technical else "casual_scene_affordance" if casual_scene else "low_signal_affordance"),
        )


@dataclass(slots=True)
class AgentStateStack:
    evidence: EvidenceView = field(default_factory=EvidenceView)
    beliefs: BeliefSnapshot = field(default_factory=BeliefSnapshot)
    preferences: PreferenceProfile = field(default_factory=PreferenceProfile)
    needs: NeedVector = field(default_factory=NeedVector)
    traits: TraitVector = field(default_factory=TraitVector)
    habits: HabitSnapshot = field(default_factory=HabitSnapshot)
    affordances: AffordanceMap = field(default_factory=AffordanceMap)
    continuity_threat: ContinuityThreatFrame = field(default_factory=ContinuityThreatFrame)

    def debug_notes(self) -> tuple[str, ...]:
        notes = [
            f"stack.channel={self.evidence.channel}",
            f"stack.focus={self.evidence.focus_kind}",
            f"stack.interrupt_cost={self.affordances.endogenous_interrupt_cost:.2f}",
            f"stack.tags={','.join(self.evidence.tags) or 'none'}",
            f"stack.affordance={self.affordances.reason}",
            *self.needs.notes(),
            *self.continuity_threat.notes()[:8],
            *self.beliefs.notes(4),
        ]
        return tuple(notes)


def build_agent_state_stack(
    *,
    snapshot: Any = None,
    internal_state: Any = None,
    thought_surface: Any = None,
    personality_lens: Any = None,
    relationship_state: Any = None,
    concrete_signals: tuple[str, ...] = (),
    channel: str = "autonomous",
    recent_speech_acts: tuple[str, ...] = (),
    recent_families: tuple[str, ...] = (),
    agent_mind: PersistentAgentMindStore | None = None,
) -> AgentStateStack:
    """Dựng stack từ các object runtime hiện có mà không buộc schema mới.

    Hàm này mềm có chủ đích: nếu một nhánh runtime chưa có field nào đó thì default
    sẽ đủ an toàn, thay vì làm cả desktop pet chết vì thiếu một cọng telemetry.
    """

    evidence = EvidenceView.from_runtime(snapshot=snapshot, concrete_signals=tuple(concrete_signals or ()), channel=channel)
    if agent_mind is None:
        try:
            agent_mind = get_default_agent_mind_store()
        except Exception:
            agent_mind = None
    beliefs = BeliefSnapshot.from_evidence(evidence, internal_state=internal_state, agent_mind=agent_mind)
    preferences = PreferenceProfile.from_agent_mind(agent_mind)
    continuity_frame = evaluate_continuity_threat(
        snapshot=snapshot,
        internal_state=internal_state,
        relationship_state=relationship_state,
        evidence=evidence,
        thought_surface=thought_surface,
        channel=channel,
    )
    needs = NeedVector.from_runtime(internal_state=internal_state, evidence=evidence, thought_surface=thought_surface, relationship_state=relationship_state, continuity_frame=continuity_frame)
    traits = TraitVector.from_runtime(personality_lens=personality_lens, relationship_state=relationship_state)
    habits = HabitSnapshot(
        recent_speech_acts=tuple(recent_speech_acts or ()),
        recent_families=tuple(recent_families or ()),
        evidence_tags=tuple(evidence.tags),
        agent_mind=agent_mind,
    )
    affordances = AffordanceMap.from_stack_parts(evidence=evidence, needs=needs, traits=traits)
    return AgentStateStack(
        evidence=evidence,
        beliefs=beliefs,
        preferences=preferences,
        needs=needs,
        traits=traits,
        habits=habits,
        affordances=affordances,
        continuity_threat=continuity_frame,
    )
