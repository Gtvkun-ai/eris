# -*- coding: utf-8 -*-
"""Production authority cho ERIS Cognitive Pipeline V3.

V3 từng chỉ viết kế hoạch vào prompt rồi đứng nhìn legacy runtime quyết định. File
này trao quyền ở đúng chỗ cuối cùng: sau wording/guard nhưng trước body/commit.
Nó không viết lại văn phong. Nó chỉ giới hạn action space theo Agency,
Permission, SpeechOpportunity và Modality đã được tính trước.
"""

from __future__ import annotations

from dataclasses import replace
import json
import os
from typing import Any

from domain import Decision


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return max(0.0, min(1.0, default))


class V3AuthorityController:
    """Áp canonical decision lên Decision production mà không làm vỡ hot path."""

    BODY_MAP = {
        "none": ("", ""),
        "face_user": ("face_user", "pose"),
        "look_at_focus": ("look_at_focus", "pose"),
        "step_closer": ("step_closer", "walk_to"),
        "step_back": ("step_back", "walk"),
        "idle_shift": ("idle_shift", "pose"),
        "stillness": ("stillness", "pose"),
        "turn_away_softly": ("look_away", "pose"),
        "approach_focus": ("look_at_focus", "walk_to"),
        "withdraw": ("look_away", "walk"),
    }

    def enabled(self) -> bool:
        raw = os.getenv("ERIS_V3_AUTHORITY")
        if raw is None:
            return True
        return raw.strip().lower() not in {"0", "false", "no", "off", "n"}

    def project_to_legacy(self, v3_frame: Any, legacy_frame: Any) -> dict[str, Any]:
        """Gắn projection canonical lên frame cũ để downstream có một nguồn audit."""
        if v3_frame is None or legacy_frame is None:
            return {}
        agency = _get(v3_frame, "agency", None)
        permission = _get(v3_frame, "permission", None)
        opportunity = _get(v3_frame, "speech_opportunity", None)
        body = _get(v3_frame, "body_plan", None)
        modality = _get(v3_frame, "modality", None)
        knowledge = (_get(v3_frame, "metadata", {}) or {}).get("knowledge_acquisition")
        projection = {
            "authoritative": self.enabled(),
            "frame_id": str(_get(v3_frame, "frame_id", "") or ""),
            "agency_intent": str(_get(agency, "intent", "observe") or "observe"),
            "speech_allowed": bool(_get(opportunity, "speech_allowed", False)),
            "speech_mode": str(_get(opportunity, "mode", "silence") or "silence"),
            "public_sayable": bool(_get(permission, "public_sayable", True)),
            "allowed_tease": bool(_get(permission, "allowed_tease", False)),
            "allowed_search": bool(_get(permission, "allowed_search", False)),
            "max_intensity": _clamp(_get(permission, "max_intensity", 0.5), 0.5),
            "body_action": str(_get(body, "action", "none") or "none"),
            "system_action": str(_get(modality, "system_action", "") or ""),
            "knowledge": knowledge.to_dict() if callable(getattr(knowledge, "to_dict", None)) else knowledge,
        }
        try:
            legacy_frame.v3_authority = projection
        except Exception:
            pass
        try:
            legacy_frame.v3_knowledge = knowledge
        except Exception:
            pass
        try:
            speech_core = _get(legacy_frame, "speech_core", None)
            if speech_core is not None and hasattr(speech_core, "should_speak"):
                speech_core.should_speak = bool(projection["speech_allowed"] and projection["public_sayable"])
        except Exception:
            pass
        return projection

    def apply_to_decision(
        self,
        decision: Decision,
        *,
        legacy_frame: Any = None,
        v3_frame: Any = None,
        channel: str = "",
    ) -> Decision:
        if not self.enabled() or decision is None:
            return decision
        if v3_frame is None and legacy_frame is not None:
            v3_frame = _get(legacy_frame, "v3_cognitive_frame", None)
        if v3_frame is None:
            return decision

        repaired = replace(decision)
        agency = _get(v3_frame, "agency", None)
        permission = _get(v3_frame, "permission", None)
        opportunity = _get(v3_frame, "speech_opportunity", None)
        speech = _get(v3_frame, "speech_plan", None)
        body = _get(v3_frame, "body_plan", None)
        modality = _get(v3_frame, "modality", None)
        metadata = _get(v3_frame, "metadata", {}) or {}
        knowledge = metadata.get("knowledge_acquisition")

        agency_intent = str(_get(agency, "intent", "speak") or "speak")
        public_sayable = bool(_get(permission, "public_sayable", True))
        speech_allowed = bool(_get(opportunity, "speech_allowed", True))
        max_intensity = _clamp(_get(permission, "max_intensity", 0.5), 0.5)
        reasons: list[str] = []

        # Tombstone cho frame/model cũ. ``search_web`` từng được planner gắn chỉ
        # vì thấy chữ "hôm nay", rồi lỗi credential ghi đè toàn bộ chat. Giờ action
        # đó bị loại khỏi runtime; nếu còn sót trong cache thì chỉ bỏ action, giữ lời.
        if str(getattr(repaired, "system_action", "") or "").strip() == "search_web":
            repaired.system_action = ""
            repaired.action_input = ""
            reasons.append("retired_search_web_cleared")

        # Knowledge action là quyết định canonical, không phải gợi ý trang trí.
        knowledge_action = str(_get(knowledge, "system_action", "") or _get(modality, "system_action", "") or "")
        knowledge_deferred = bool(_get(knowledge, "deferred", False))
        knowledge_succeeded = bool(_get(knowledge, "succeeded", False))
        if knowledge_action and knowledge_deferred and not knowledge_succeeded:
            if knowledge_action == "search_web":
                reasons.append("retired_search_web_ignored")
            else:
                repaired.system_action = knowledge_action
                repaired.action_input = str(_get(knowledge, "query", "") or _get(v3_frame, "user_text", "") or "")
                reasons.append(f"system_action={knowledge_action}")

        # Permission/agency quyết định có được surface speech hay không.
        if not public_sayable or not speech_allowed or agency_intent in {"stay_silent", "body_only", "observe", "withdraw"}:
            repaired.text = ""
            repaired.should_speak = False
            if agency_intent == "body_only":
                repaired.intent = repaired.intent or "body_only"
            reasons.append("speech_suppressed")
        elif agency_intent in {"speak", "ask", "repair", "search"}:
            repaired.should_speak = bool(str(repaired.text or "").strip())

        # Body plan đi vào protocol thật. Không ghi đè motion cụ thể do action/tool
        # đã chọn, trừ khi Decision chưa có gì.
        body_action = str(_get(body, "action", "none") or "none")
        stage_motion, motion_intent = self.BODY_MAP.get(body_action, (body_action, "pose"))
        if stage_motion and not str(getattr(repaired, "stage_motion", "") or "").strip():
            repaired.stage_motion = stage_motion
        if motion_intent and not str(getattr(repaired, "motion_intent", "") or "").strip():
            repaired.motion_intent = motion_intent
        if body_action in {"stillness", "idle_shift", "face_user", "look_at_focus", "turn_away_softly"} and not repaired.animation:
            repaired.animation = "stand"
        if body_action != "none":
            reasons.append(f"body={body_action}")

        # Tease bị permission từ chối thì bỏ cue/delivery mang tính tease; core text
        # không bị rewrite thành support-bot như thời guard cũ.
        if not bool(_get(permission, "allowed_tease", False)):
            if str(getattr(repaired, "delivery_hint", "") or "").lower() in {"dry_tease", "soft_tease", "mischief", "playful_tease"}:
                repaired.delivery_hint = "restrained" if max_intensity < 0.45 else "focused"
                reasons.append("tease_clamped")
            if str(getattr(repaired, "nonverbal_cue", "") or "").lower() in {"scoff_soft", "smirk", "laugh_tease"}:
                repaired.nonverbal_cue = ""

        # Cường độ canonical giới hạn confidence/cue, không phá nội dung đúng.
        if max_intensity < 0.35:
            repaired.confidence = min(float(getattr(repaired, "confidence", 0.5) or 0.5), 0.65)
            if repaired.stage_motion in {"step_closer", "lean_in_small"}:
                repaired.stage_motion = "stillness"
            reasons.append(f"intensity={max_intensity:.2f}")

        # Guard body/speech contradiction đã tính ở ModalitySync.
        contradiction = _clamp(_get(modality, "contradiction_risk", 0.0), 0.0)
        if contradiction >= 0.70:
            repaired.stage_motion = "stillness"
            repaired.motion_intent = "pose"
            reasons.append(f"modality_repair={contradiction:.2f}")

        tag = f"v3_authority:{agency_intent}"
        current_tags = list(getattr(repaired, "reasoning_tags", ()) or ())
        if tag not in current_tags:
            current_tags.append(tag)
        repaired.reasoning_tags = tuple(current_tags[-16:])
        marker = "v3_authority=" + (",".join(reasons) if reasons else "pass")
        trace = str(getattr(repaired, "debug_trace", "") or "").strip()
        repaired.debug_trace = f"{trace} | {marker}".strip(" |")[:1200]
        if not repaired.parse_mode:
            repaired.parse_mode = "v3_authority"

        audit = {
            "channel": channel,
            "agency_intent": agency_intent,
            "speech_allowed": speech_allowed,
            "public_sayable": public_sayable,
            "body_action": body_action,
            "system_action": repaired.system_action,
            "max_intensity": max_intensity,
            "reasons": reasons,
        }
        try:
            legacy_frame.v3_authority = {**dict(_get(legacy_frame, "v3_authority", {}) or {}), **audit}
        except Exception:
            pass
        metadata["authority_applied"] = audit
        try:
            v3_frame.metadata = metadata
        except Exception:
            pass
        return repaired


__all__ = ["V3AuthorityController"]
