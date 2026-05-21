from __future__ import annotations

"""
ni.py - semantic Ni for ERIS
===========================

This version intentionally removes the old productivity-scoring behavior.

Old disease:
    focus_kind + keyword + idle -> similarity -> drift -> guard

New behavior:
    semantic probe + active goal context -> orientation signal
    orientation signal -> GoalDriftReport compatibility adapter

Key design rules:
    - YouTube is not automatically avoidance.
    - Entertainment is not automatically off-goal.
    - Idle is posture/ambiguity, not guilt.
    - Ni may suggest intervention pressure, but it does not become the police.
    - Active goal context, if available, is read as background continuity,
      not as permission to nag.

Drop this file in src/cortex/ni.py and add orientation_context.py next to it.
If coordinator can pass goal_state/goal_context later, use the optional args.
If not, the file still works with the old public API. Backward compatibility:
the thing we endure so future humans can suffer slightly less.
"""

import json
import os
import time
from typing import Mapping

try:
    from .contracts import GoalDriftReport, TelemetrySnapshot
except ImportError:  # Useful for isolated tests outside the package.
    from contracts import GoalDriftReport, TelemetrySnapshot  # type: ignore

try:
    from .orientation_context import (
        GoalRelationLabel,
        OrientationInterpreter,
        OrientationSignal,
        SemanticContextProbe,
        clamp,
        clamp01,
        clean_text,
        normalize,
    )
except ImportError:  # Useful when Ngài runs this file in a flat scratch dir.
    from orientation_context import (  # type: ignore
        GoalRelationLabel,
        OrientationInterpreter,
        OrientationSignal,
        SemanticContextProbe,
        clamp,
        clamp01,
        clean_text,
        normalize,
    )


DEFAULT_FOCUS_BIAS: dict[str, dict[str, float]] = {
    # Neutral by default. Focus kind is evidence, not a morality table.
    "coding": {"bias": 0.0, "scale": 1.0},
    "documentation": {"bias": 0.0, "scale": 1.0},
    "communication": {"bias": 0.0, "scale": 1.0},
    "system": {"bias": 0.0, "scale": 1.0},
    "focus_aid_media": {"bias": 0.0, "scale": 1.0},
    "general": {"bias": 0.0, "scale": 1.0},
    "entertainment": {"bias": 0.0, "scale": 1.0},
}


def _load_focus_bias_table() -> dict[str, dict[str, float]]:
    """Load legacy calibration but disarm moral bias.

    Existing ni_focus_config.json may still contain old productivity bias.
    Keep only tiny calibration ranges:
        bias  in [-0.03, 0.03]
        scale in [0.90, 1.10]
    """

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    config_path = os.path.join(project_root, "ni_focus_config.json")

    table: dict[str, dict[str, float]] = {kind: cfg.copy() for kind, cfg in DEFAULT_FOCUS_BIAS.items()}
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return table

    if not isinstance(data, dict):
        return table

    for kind, cfg in data.items():
        if not isinstance(cfg, dict):
            continue
        try:
            bias = float(cfg.get("bias", 0.0) or 0.0)
        except (TypeError, ValueError):
            bias = 0.0
        try:
            scale = float(cfg.get("scale", 1.0) or 1.0)
        except (TypeError, ValueError):
            scale = 1.0
        table[str(kind)] = {
            "bias": max(-0.03, min(0.03, bias)),
            "scale": max(0.90, min(1.10, scale)),
        }
    return table


FOCUS_BIAS_TABLE = _load_focus_bias_table()


class NiEngine:
    """Reads direction-of-meaning and converts it to GoalDriftReport.

    Public methods keep the old signature and add optional goal context:
        evaluate_autonomous(..., goal_state=None, goal_context=None)
        evaluate_chat(..., goal_state=None, goal_context=None)

    goal_state can be the new GoalPersistenceState. goal_context can be a dict or
    a render_ni_context string. This makes the integration path cheap instead of
    requiring a ceremony, because apparently software architecture must survive
    actual usage.
    """

    def __init__(self) -> None:
        self._interpreter = OrientationInterpreter()

    def evaluate_autonomous(
        self,
        *,
        snapshot: TelemetrySnapshot,
        long_term_memory: list[str],
        last_text: str,
        goal_state: object = None,
        goal_context: object = None,
    ) -> GoalDriftReport:
        recent_signals = long_term_memory[-8:]
        probe = self._build_probe(
            snapshot=snapshot,
            recent_signals=recent_signals,
            current_text=last_text or "",
            goal_state=goal_state,
            goal_context=goal_context,
        )
        return self._analyze(probe=probe)

    def evaluate_chat(
        self,
        *,
        snapshot: TelemetrySnapshot,
        long_term_memory: list[str],
        user_text: str,
        goal_state: object = None,
        goal_context: object = None,
    ) -> GoalDriftReport:
        recent_signals = long_term_memory[-8:]
        probe = self._build_probe(
            snapshot=snapshot,
            recent_signals=recent_signals,
            current_text=user_text or "",
            goal_state=goal_state,
            goal_context=goal_context,
        )
        return self._analyze(probe=probe)

    def _build_probe(
        self,
        *,
        snapshot: TelemetrySnapshot,
        recent_signals: list[str],
        current_text: str,
        goal_state: object = None,
        goal_context: object = None,
    ) -> SemanticContextProbe:
        goal_info = self._extract_goal_context(goal_state=goal_state, goal_context=goal_context)
        return SemanticContextProbe(
            focus_kind=getattr(snapshot, "active_window_kind", "") or "general",
            focus_text=getattr(snapshot, "focus_summary", "") or "",
            window_text=getattr(snapshot, "active_window", "") or "",
            browsing_text=" ".join(
                part
                for part in (
                    getattr(snapshot, "browser_url", "") or "",
                    " ".join((getattr(snapshot, "browser_tabs", None) or [])[:6]),
                )
                if part
            ),
            memory_text=" ".join(recent_signals),
            current_text=current_text or "",
            idle_seconds=float(getattr(snapshot, "idle_seconds", 0.0) or 0.0),
            open_window_count=len(getattr(snapshot, "open_windows", None) or []),
            active_goal_strength=goal_info["strength"],
            active_goal_type=goal_info["goal_type"],
            active_goal_intervention_permission=goal_info["intervention_permission"],
            active_goal_summary=goal_info["summary"],
        )

    def _extract_goal_context(self, *, goal_state: object = None, goal_context: object = None) -> dict[str, object]:
        """Read active goal data from either object, dict, or compact text.

        The new GoalPersistenceState exposes render_ni_context() and fields such
        as intervention_permission. If the old state is passed, this still reads
        strength/urgency/summary and treats intervention permission cautiously.
        """

        data: dict[str, object] = {
            "summary": "",
            "goal_type": "",
            "strength": 0.0,
            "intervention_permission": 0.0,
        }

        if goal_state is not None:
            active = bool(getattr(goal_state, "active", False))
            if active:
                data["summary"] = clean_text(getattr(goal_state, "summary", ""), limit=180)
                data["goal_type"] = clean_text(getattr(goal_state, "goal_type", ""), limit=80)
                data["strength"] = clamp01(getattr(goal_state, "strength", 0.0))
                # Old state has no intervention_permission. Default to low, not zero, so active
                # technical goals are visible but not naggy.
                data["intervention_permission"] = clamp01(getattr(goal_state, "intervention_permission", 0.22))

        if isinstance(goal_context, Mapping):
            if bool(goal_context.get("active", False)) or goal_context.get("summary"):
                data["summary"] = clean_text(goal_context.get("summary") or data["summary"], limit=180)
                data["goal_type"] = clean_text(goal_context.get("goal_type") or goal_context.get("type") or data["goal_type"], limit=80)
                data["strength"] = clamp01(goal_context.get("strength", data["strength"]))
                data["intervention_permission"] = clamp01(goal_context.get("intervention_permission", data["intervention_permission"]))

        elif isinstance(goal_context, str) and goal_context.strip():
            parsed = self._parse_goal_context_text(goal_context)
            for key, value in parsed.items():
                if value not in ("", 0.0, None):
                    data[key] = value

        return data

    def _parse_goal_context_text(self, text: str) -> dict[str, object]:
        """Parse render_ni_context() text from GoalPersistenceState.

        Expected style:
            goal_signal: active=1; type=concrete_task; strength=0.72; ...
        """

        result: dict[str, object] = {
            "summary": "",
            "goal_type": "",
            "strength": 0.0,
            "intervention_permission": 0.0,
        }
        raw = str(text or "")
        norm = normalize(raw)
        if "active=1" not in norm and "active=true" not in norm:
            return result

        pairs: dict[str, str] = {}
        for part in raw.replace("\n", ";").split(";"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            pairs[normalize(key).strip(" -:")] = value.strip()

        result["summary"] = clean_text(pairs.get("summary", ""), limit=180)
        result["goal_type"] = clean_text(pairs.get("type") or pairs.get("goal_type") or "", limit=80)
        result["strength"] = clamp01(pairs.get("strength", 0.0))
        result["intervention_permission"] = clamp01(pairs.get("intervention_permission", 0.0))
        return result

    def _analyze(self, *, probe: SemanticContextProbe) -> GoalDriftReport:
        orientation = self._interpreter.estimate_orientation(probe)
        coherence = self._adjust_coherence(orientation.orientation_coherence, focus_kind=probe.focus_kind)
        conflict = clamp01(orientation.goal_conflict_score)
        drift_level = self._label_drift(conflict)

        should_raise_guard = (
            orientation.intervention_pressure >= 0.68
            and orientation.confidence >= 0.58
            and orientation.relation.label == GoalRelationLabel.CONFLICTING.value
        )

        signal_channels = {
            **dict(orientation.channels),
            "coherence": coherence,
            "goal_conflict": conflict,
            "intervention_pressure": orientation.intervention_pressure,
        }
        self._log_orientation_sample(
            focus_kind=probe.focus_kind,
            orientation=orientation,
            should_raise_guard=should_raise_guard,
            channels=signal_channels,
        )

        return GoalDriftReport(
            similarity=coherence,
            drift_score=conflict,
            drift_level=drift_level,
            confidence=orientation.confidence,
            should_raise_guard=should_raise_guard,
            reason_span=orientation.reason_span,
            prompt_context=self._build_prompt_context(
                orientation=orientation,
                drift_score=conflict,
                drift_level=drift_level,
                should_raise_guard=should_raise_guard,
            ),
            evidence=orientation.evidence,
            vector_method="ni_orientation_semantic_shared_v2",
        )

    def _adjust_coherence(self, coherence: float, *, focus_kind: str) -> float:
        config = FOCUS_BIAS_TABLE.get(focus_kind, {"bias": 0.0, "scale": 1.0})
        try:
            bias = float(config.get("bias", 0.0) or 0.0)
        except (TypeError, ValueError):
            bias = 0.0
        try:
            scale = float(config.get("scale", 1.0) or 1.0)
        except (TypeError, ValueError):
            scale = 1.0
        return clamp(float(coherence) * scale + bias, 0.0, 1.0)

    def _label_drift(self, drift_score: float) -> str:
        # Compatibility labels. Semantics changed: drift_score means goal_conflict, not productivity loss.
        if drift_score >= 0.75:
            return "nghiêm trọng"
        if drift_score >= 0.55:
            return "cao"
        if drift_score >= 0.35:
            return "vừa"
        return "thấp"

    def _build_prompt_context(
        self,
        *,
        orientation: OrientationSignal,
        drift_score: float,
        drift_level: str,
        should_raise_guard: bool,
    ) -> str:
        guard = 1 if should_raise_guard else 0
        guidance = self._build_guidance(orientation=orientation, should_raise_guard=should_raise_guard)
        lines = [
            (
                "Ni: "
                f"orientation={orientation.intent.label} "
                f"relation={orientation.relation.label} "
                f"coherence={orientation.orientation_coherence:.2f} "
                f"drift={drift_score:.2f}({drift_level}) "
                f"intervention={orientation.intervention_pressure:.2f} "
                f"conf={orientation.confidence:.2f} "
                f"guard={guard}."
            ),
            f"Reason: {orientation.reason_span}.",
            f"Guidance: {guidance}",
        ]
        if orientation.evidence:
            lines.append(f"Bám vào: {' | '.join(orientation.evidence[:7])}.")
        return "\n".join(lines)

    def _build_guidance(self, *, orientation: OrientationSignal, should_raise_guard: bool) -> str:
        intent = orientation.intent.label
        relation = orientation.relation.label
        if should_raise_guard:
            return (
                "có thể neo lại rất nhẹ; không mắng, không chấm điểm đạo đức, "
                "chỉ can thiệp nếu câu cuối thật sự cần."
            )
        if intent in {"research", "technical_focus", "system_waiting"}:
            return "đọc như mạch học/làm; không phạt media nếu nó hỗ trợ research."
        if intent == "supportive_background":
            return "coi như nền hỗ trợ; ưu tiên im lặng hoặc hiện diện rất nhỏ."
        if intent in {"recovery", "play_or_recovery"} and relation != GoalRelationLabel.CONFLICTING.value:
            return "nghỉ/chơi không tự động là lệch; tránh giọng productivity coach."
        if relation == GoalRelationLabel.UNKNOWN.value:
            return "không đủ chắc; giảm suy diễn, không raise guard từ surface pattern."
        return "giữ quan sát mềm; Ni cung cấp hướng, không ép can thiệp."

    # ------------------------------------------------------------------
    # Legacy private adapters so old tests/private callers fail less loudly.
    # ------------------------------------------------------------------

    def _estimate_attention_signal(self, *, snapshot: TelemetrySnapshot, channels: dict[str, str]) -> tuple[float, dict[str, float], list[str]]:
        probe = SemanticContextProbe(
            focus_kind=getattr(snapshot, "active_window_kind", "") or "general",
            focus_text=channels.get("focus", ""),
            window_text=channels.get("window", ""),
            browsing_text=channels.get("browsing", ""),
            memory_text=channels.get("memory", ""),
            current_text=channels.get("current", ""),
            idle_seconds=float(getattr(snapshot, "idle_seconds", 0.0) or 0.0),
            open_window_count=len(getattr(snapshot, "open_windows", None) or []),
        )
        orientation = self._interpreter.estimate_orientation(probe)
        return orientation.orientation_coherence, dict(orientation.channels), list(orientation.evidence)

    def _focus_kind_baseline(self, focus_kind: str) -> float:
        return 0.50

    def _focus_text_adjustment(self, normalized: str, *, focus_kind: str) -> float:
        return 0.0

    def _idle_adjustment(self, idle_seconds: float, *, focus_kind: str) -> float:
        return 0.0

    def _window_sprawl_adjustment(self, open_window_count: int, *, focus_kind: str) -> float:
        return 0.0

    def _adjust_similarity(self, raw_similarity: float, *, focus_kind: str) -> float:
        return self._adjust_coherence(raw_similarity, focus_kind=focus_kind)

    def _estimate_confidence(self, *, snapshot: TelemetrySnapshot, channels: dict[str, str], signal_channels: dict[str, float], drift_score: float) -> float:
        # This is only for legacy callers. Real confidence comes from OrientationInterpreter.
        probe = SemanticContextProbe(
            focus_kind=getattr(snapshot, "active_window_kind", "") or "general",
            focus_text=channels.get("focus", ""),
            window_text=channels.get("window", ""),
            browsing_text=channels.get("browsing", ""),
            memory_text=channels.get("memory", ""),
            current_text=channels.get("current", ""),
            idle_seconds=float(getattr(snapshot, "idle_seconds", 0.0) or 0.0),
            open_window_count=len(getattr(snapshot, "open_windows", None) or []),
        )
        return self._interpreter.estimate_orientation(probe).confidence

    def _log_orientation_sample(
        self,
        *,
        focus_kind: str,
        orientation: OrientationSignal,
        should_raise_guard: bool,
        channels: Mapping[str, float],
    ) -> None:
        try:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            log_path = os.path.join(project_root, "ni_drift_samples.jsonl")
            payload = {
                "focus_kind": focus_kind or "unknown",
                "intent": orientation.intent.label,
                "intent_confidence": float(orientation.intent.confidence),
                "relation": orientation.relation.label,
                "relation_confidence": float(orientation.relation.confidence),
                "orientation_coherence": float(orientation.orientation_coherence),
                "drift_score": float(orientation.goal_conflict_score),
                "intervention_pressure": float(orientation.intervention_pressure),
                "confidence": float(orientation.confidence),
                "should_raise_guard": bool(should_raise_guard),
                "reason_span": orientation.reason_span,
                "channels": {str(name): float(score) for name, score in (channels or {}).items()},
                "evidence": list(orientation.evidence[:14]),
            }
            with open(log_path, "a", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.write("\n")
        except Exception:
            return

    def _log_drift_sample(self, *, focus_kind: str, raw_similarity: float, drift_score: float, should_raise_guard: bool, channels: dict[str, float]) -> None:
        try:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            log_path = os.path.join(project_root, "ni_drift_samples.jsonl")
            payload = {
                "focus_kind": focus_kind or "unknown",
                "orientation_coherence": float(raw_similarity),
                "drift_score": float(drift_score),
                "should_raise_guard": bool(should_raise_guard),
                "channels": {str(name): float(score) for name, score in (channels or {}).items()},
                "legacy_log": True,
            }
            with open(log_path, "a", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.write("\n")
        except Exception:
            return


class NiStateMachine:
    """Temporal smoothing over semantic goal conflict.

    Entertainment/play/recovery does not get downgraded by category. The state
    follows repeated semantic conflict and guard flags only.
    """

    def __init__(
        self,
        *,
        window_seconds: float = 600.0,
        borderline_threshold: float = 0.35,
        off_goal_threshold: float = 0.65,
        max_recent: int = 120,
    ) -> None:
        self.window_seconds = float(window_seconds)
        self.borderline_threshold = float(borderline_threshold)
        self.off_goal_threshold = float(off_goal_threshold)
        self.max_recent = int(max_recent)
        self._recent_scores: list[tuple[float, float]] = []
        self._recent_guard_flags: list[tuple[float, bool]] = []
        self.current_state: str = "ON_GOAL"
        self.streak_length: int = 0

    def update(self, *, snapshot: TelemetrySnapshot, report: GoalDriftReport) -> dict[str, object]:
        now = time.time()
        cutoff = now - self.window_seconds

        self._recent_scores.append((now, float(report.drift_score or 0.0)))
        self._recent_scores = [(t, s) for (t, s) in self._recent_scores if t >= cutoff][-self.max_recent :]

        self._recent_guard_flags.append((now, bool(getattr(report, "should_raise_guard", False))))
        self._recent_guard_flags = [(t, g) for (t, g) in self._recent_guard_flags if t >= cutoff][-self.max_recent :]

        recent_values = [s for (_t, s) in self._recent_scores[-5:]]
        avg_recent = sum(recent_values) / len(recent_values) if recent_values else float(report.drift_score or 0.0)
        recent_guard_count = sum(1 for (_t, flag) in self._recent_guard_flags[-5:] if flag)

        if avg_recent >= self.off_goal_threshold or recent_guard_count >= 3:
            state = "OFF_GOAL"
        elif avg_recent >= self.borderline_threshold or bool(getattr(report, "should_raise_guard", False)):
            state = "BORDERLINE"
        else:
            state = "ON_GOAL"

        if state == self.current_state:
            self.streak_length += 1
        else:
            self.current_state = state
            self.streak_length = 1

        return {
            "discrete_state": self.current_state,
            "streak_length": self.streak_length,
            "average_recent_drift": avg_recent,
            "recent_guard_count": recent_guard_count,
            "samples_in_window": len(self._recent_scores),
            "semantic_note": "drift means goal_conflict, not entertainment/productivity penalty",
        }
