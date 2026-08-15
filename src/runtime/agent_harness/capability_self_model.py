# -*- coding: utf-8 -*-
"""Capability self-model for Eris.

This is intentionally *not* another tool registry.  The capability registry is
still the source of truth for concrete native tools; this module projects that
truth into the decisions Eris actually needs in conversation:

- instant: a small native action/observation can finish in one step;
- consult: ask the backstage Gemini agent to inspect/reason without modifying;
- long_execution: hand a multi-step goal to Gemini/LangGraph;
- clarify: multiple materially different execution paths are still open;
- conversation: no executor is needed.

Having a model of one's own reach is more useful than owning 46 tools and then
announcing that one has no connection to the computer.  We have already tried
that genre of comedy.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import re
import unicodedata
from typing import Any

from actions.capability_registry import iter_public_capabilities


@dataclass(frozen=True)
class CapabilitySelfAssessment:
    lane: str = "conversation"
    reason: str = "normal_chat"
    confidence: float = 0.5
    estimated_time: str = ""
    executor: str = "eris"
    can_modify: bool = False
    matched_capabilities: tuple[str, ...] = ()
    matched_skills: tuple[str, ...] = ()
    clarification: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["matched_capabilities"] = list(self.matched_capabilities)
        payload["matched_skills"] = list(self.matched_skills)
        return payload


def _fold(text: str) -> str:
    raw = unicodedata.normalize("NFD", str(text or "").lower())
    raw = "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")
    raw = raw.replace("đ", "d")
    return re.sub(r"\s+", " ", raw).strip()


def _contains_any(text: str, values: tuple[str, ...]) -> bool:
    return any(value in text for value in values)


_INSTANT_CUES = {
    "get_now_playing": ("dang nghe", "nghe nhac gi", "bai gi", "now playing", "media dang phat"),
    "get_active_application": ("app dang mo", "app dang dung", "cua so dang", "active app"),
    "read_visible_ui_text": ("doc chu man hinh", "chu tren man hinh", "ui text"),
    "read_current_error": ("loi hien tai", "traceback hien tai", "error hien tai"),
    "inspect_runtime_log": ("doc log", "xem log", "runtime log"),
    "inspect_selected_file": ("file dang mo", "file dang chon", "selected file"),
    "get_project_status": ("git status", "project status", "trang thai project"),
    "launch_app": ("mo chrome", "mo app", "mo ung dung", "launch"),
    "focus_window": ("focus window", "dua cua so", "chuyen sang cua so"),
    "set_volume": ("am luong", "volume", "mute"),
    "play_pause_media": ("pause nhac", "phat nhac", "next bai", "previous bai"),
    "copy_text": ("copy", "clipboard"),
    "open_url": ("mo link", "mo url", "open url"),
    "get_weather": ("thoi tiet", "weather"),
    "get_local_time": ("may gio", "gio may", "ngay may", "local time"),
}

_TECH_TARGETS = (
    "repo", "code", "source", "file", "module", "class", "function", "tool", "skill",
    "agent", "langgraph", "gemini", "router", "routing", "backend", "frontend", "godot",
    "python", "c#", "test", "bug", "loi", "panel", "ui", "runtime", "capability", "memory",
    "tts", "live2d", "git", "architecture", "kien truc",
)
_LONG_VERBS = (
    "sua", "fix", "debug", "refactor", "trien khai", "implement", "viet code", "patch",
    "chay test", "build", "compile", "toi uu", "optimize", "lam lai", "cap nhat code",
    "them chuc nang", "bo chuc nang", "lam tiep", "execute", "thuc thi",
)
_LONG_SCOPE = (
    "toan bo", "full", "end to end", "e2e", "nhieu file", "nhieu buoc", "lau dai", "dai han",
    "tu dong", "tu sua", "tu debug", "sua luon", "lam luon", "nghien cuu ky roi sua",
)
_CONSULT_VERBS = (
    "soi", "xem ky", "review", "danh gia", "kiem tra", "nghien cuu", "phan tich", "tim root cause",
    "tai sao", "vi sao", "co can", "hop ly khong", "can can", "kien truc nay",
)
_BROAD_QUALITY = (
    "ngon hon", "tot hon", "xin hon", "elegant hon", "dep hon", "thong minh hon", "toi uu hon",
    "hoan thien hon", "cai thien", "nang cap",
)
_SPECIFIC = (
    ".py", ".cs", ".gd", ".json", "src/", "runtime/", "actions/", "tests/", "traceback",
    "timeout", "latency", "khong chay", "fail", "die", "capability_", "project_", "get_", "set_",
)


class CapabilitySelfModel:
    """Small, refreshable projection of what Eris can do *now*."""

    def __init__(self, *, harness: Any = None, harness_ready: bool | None = None) -> None:
        self.harness = harness
        self._harness_ready_override = harness_ready
        self.refresh()

    def refresh(self) -> None:
        capabilities = tuple(iter_public_capabilities(include_unavailable=True))
        self._native = {cap.id: cap for cap in capabilities if cap.callable}
        discovery = getattr(self.harness, "discovery", None)
        raw_skills = list(getattr(discovery, "capabilities", []) or [])
        self._skills = {
            str(item.get("name", "") or ""): dict(item)
            for item in raw_skills
            if isinstance(item, dict) and str(item.get("name", "") or "").strip()
        }

    @property
    def harness_ready(self) -> bool:
        if self._harness_ready_override is not None:
            return bool(self._harness_ready_override)
        return self.harness is not None

    def instant_capabilities(self) -> tuple[str, ...]:
        result = []
        for cap_id in _INSTANT_CUES:
            cap = self._native.get(cap_id)
            if cap is not None and bool(getattr(cap, "live_available", False)):
                result.append(cap_id)
        return tuple(result)

    def long_skills(self) -> tuple[str, ...]:
        return tuple(sorted(self._skills)) if self.harness_ready else ()

    def prompt_summary(self) -> str:
        instant = self.instant_capabilities()
        skills = self.long_skills()
        instant_text = ", ".join(instant[:18]) if instant else "none currently healthy"
        skills_text = ", ".join(skills[:12]) if skills else "Gemini/LangGraph unavailable"
        return (
            "CAPABILITY SELF MODEL: "
            f"instant_native=[{instant_text}]; "
            f"long_executor={'gemini/langgraph' if self.harness_ready else 'unavailable'}; "
            f"long_skills=[{skills_text}]. "
            "Use native capabilities for one-step work; use Gemini/LangGraph for multi-step technical work; "
            "ask the user before execution when several materially different targets remain open."
        )

    def assess(self, user_text: str) -> CapabilitySelfAssessment:
        folded = _fold(user_text)
        if not folded:
            return CapabilitySelfAssessment()

        matched_instant: list[str] = []
        for cap_id, cues in _INSTANT_CUES.items():
            cap = self._native.get(cap_id)
            if cap is None or not bool(getattr(cap, "live_available", False)):
                continue
            if _contains_any(folded, cues):
                matched_instant.append(cap_id)
        if matched_instant:
            return CapabilitySelfAssessment(
                lane="instant",
                reason="healthy_single_step_capability",
                confidence=0.94,
                estimated_time="< 3s",
                executor="eris-native",
                can_modify=any(str(getattr(self._native[x], "effect", "")) in {"write", "control"} for x in matched_instant),
                matched_capabilities=tuple(matched_instant[:6]),
            )

        has_target = _contains_any(folded, _TECH_TARGETS)
        has_long_verb = _contains_any(folded, _LONG_VERBS)
        has_long_scope = _contains_any(folded, _LONG_SCOPE)
        has_consult = _contains_any(folded, _CONSULT_VERBS)
        broad = _contains_any(folded, _BROAD_QUALITY)
        specific = _contains_any(folded, _SPECIFIC) or bool(
            re.search(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\.(?:py|cs|gd|json|md|txt)\b", str(user_text or ""))
        )

        matched_skills = self._match_skills(folded)
        if has_target and broad and not specific and not has_long_scope:
            return CapabilitySelfAssessment(
                lane="clarify",
                reason="materially_branching_long_task",
                confidence=0.87,
                estimated_time="unknown until clarified",
                executor="eris",
                matched_skills=matched_skills,
                clarification=(
                    "Chốt nhánh chính trước khi giao Gemini: hành vi/chức năng cần đạt, kiến trúc bên trong, "
                    "hiệu năng, hay giao diện/trải nghiệm. Nếu hội thoại đã có các phương án cụ thể thì hỏi bằng "
                    "2-4 lựa chọn đó, không hỏi chung chung."
                ),
            )

        if has_target and (has_long_verb or has_long_scope):
            if not self.harness_ready:
                return CapabilitySelfAssessment(
                    lane="unavailable",
                    reason="long_executor_unavailable",
                    confidence=0.95,
                    estimated_time="unavailable",
                    executor="gemini/langgraph",
                    can_modify=True,
                    matched_skills=matched_skills,
                )
            return CapabilitySelfAssessment(
                lane="long_execution",
                reason="multi_step_technical_execution",
                confidence=0.90 if specific or has_long_scope else 0.80,
                estimated_time="minutes",
                executor="gemini/langgraph",
                can_modify=True,
                matched_skills=matched_skills,
            )

        if has_target and has_consult:
            if not self.harness_ready:
                return CapabilitySelfAssessment(
                    lane="conversation",
                    reason="consult_executor_unavailable",
                    confidence=0.72,
                    executor="eris",
                    matched_skills=matched_skills,
                )
            return CapabilitySelfAssessment(
                lane="consult",
                reason="technical_backstage_consult",
                confidence=0.80 if specific else 0.72,
                estimated_time="seconds to minutes",
                executor="gemini/langgraph",
                can_modify=False,
                matched_skills=matched_skills,
            )

        return CapabilitySelfAssessment(
            lane="conversation",
            reason="normal_chat",
            confidence=0.66,
            executor="eris",
            matched_skills=matched_skills,
        )

    def _match_skills(self, folded_query: str) -> tuple[str, ...]:
        if not self._skills:
            return ()
        query_tokens = set(re.findall(r"[a-z0-9_\-]+", folded_query))
        ranked: list[tuple[int, str]] = []
        for name, item in self._skills.items():
            haystack = _fold(" ".join([
                name,
                str(item.get("description", "") or ""),
                *[str(x) for x in item.get("keywords", []) if str(x).strip()],
            ]))
            tokens = set(re.findall(r"[a-z0-9_\-]+", haystack))
            score = len(query_tokens & tokens)
            if score:
                ranked.append((score, name))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]))
        return tuple(name for _score, name in ranked[:5])


__all__ = ["CapabilitySelfAssessment", "CapabilitySelfModel"]
