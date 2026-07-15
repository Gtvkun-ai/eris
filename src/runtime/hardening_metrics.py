# -*- coding: utf-8 -*-
"""Các metric đúng tên trong báo cáo hardening.

Module dùng lazy import để telemetry không trở thành dependency bắt buộc. Mọi
hàm đều fail-safe; một dashboard hỏng không có quyền làm Eris câm, vì nhân loại
đã có đủ hệ thống ngã chỉ vì logger rồi.
"""

from __future__ import annotations

from typing import Any, Iterable


def _obs():
    try:
        from runtime.observability import GLOBAL_OBSERVABILITY
        return GLOBAL_OBSERVABILITY
    except Exception:
        return None


def record_director_semantic_gate(
    *, accepted: bool, reason: str, score: float, threshold: float,
    backend: str = "unknown", degraded: bool = False,
) -> None:
    obs = _obs()
    if obs is None:
        return
    try:
        tags = {
            "accepted": str(bool(accepted)).lower(),
            "reason": reason,
            "backend": backend or "unknown",
            "degraded": str(bool(degraded)).lower(),
        }
        obs.increment("director_semantic_gate_total", tags=tags)
        obs.observe("director_semantic_score", float(score), tags={"accepted": tags["accepted"], "backend": tags["backend"]})
        if degraded:
            obs.increment("director_semantic_backend_degraded_total", tags={"backend": tags["backend"]})
        if not accepted:
            obs.increment("director_semantic_reject_rate", tags={"reason": reason})
        obs.log(
            "director_semantic_gate",
            tags={"reason": reason, "backend": backend or "unknown"},
            fields={"accepted": accepted, "score": score, "threshold": threshold, "degraded": degraded},
        )
    except Exception:
        pass


def record_action_confirmation(result: Any) -> None:
    obs = _obs()
    if obs is None:
        return
    try:
        mode = str(getattr(result, "public_mode", "unknown") or "unknown")
        action = str(getattr(result, "action_name", "unknown") or "unknown")
        obs.increment("action_confirmation_total", tags={"action": action, "mode": mode})
        if bool(getattr(result, "success", False)) and not bool(getattr(result, "observed", False)):
            obs.increment("action_dispatch_only_total", tags={"action": action})
        # Đây là invariant runtime: public assert khi chưa observed phải luôn bằng 0.
        if mode == "observed_success" and not bool(getattr(result, "observed", False)):
            obs.increment("false_success_action_rate", tags={"action": action})
        obs.log("action_confirmation", tags={"action": action, "mode": mode}, fields=getattr(result, "to_public_meta", lambda: {})())
    except Exception:
        pass


def record_surface_sanitizer(*, surface: str, blocked_kinds: Iterable[str]) -> None:
    kinds = tuple(dict.fromkeys(str(item) for item in blocked_kinds if str(item)))
    if not kinds:
        return
    obs = _obs()
    if obs is None:
        return
    try:
        obs.increment("surface_leak_block_rate", value=float(len(kinds)), tags={"surface": surface})
        for kind in kinds:
            obs.increment("surface_leak_block_total", tags={"surface": surface, "kind": kind})
    except Exception:
        pass


def record_memory_provenance(*, mode: str, reason: str, source: str, confidence: float) -> None:
    obs = _obs()
    if obs is None:
        return
    try:
        obs.increment("memory_provenance_total", tags={"mode": mode, "reason": reason, "source": source})
        obs.observe("memory_provenance_confidence", confidence, tags={"mode": mode})
        if mode == "assert" and reason in {"weak_or_missing_provenance", "contested_claim_ttl"}:
            obs.increment("memory_assert_without_provenance_rate", tags={"reason": reason})
    except Exception:
        pass


def record_repair_state(*, active: bool, exhausted: bool, turns_left: int, event: str) -> None:
    obs = _obs()
    if obs is None:
        return
    try:
        obs.increment("repair_state_event_total", tags={"event": event, "active": str(active).lower(), "exhausted": str(exhausted).lower()})
        obs.gauge("repair_state_turns_left", float(turns_left))
        if exhausted:
            obs.increment("repair_loop_rate", tags={"event": event})
    except Exception:
        pass


def record_tts_fallback(*, provider: str, locale: str, expected_locale: str, success: bool, reason: str) -> None:
    obs = _obs()
    if obs is None:
        return
    try:
        same = str(locale or "").lower().split("-")[0] == str(expected_locale or "").lower().split("-")[0]
        obs.increment("tts_fallback_total", tags={"provider": provider, "same_language": str(same).lower(), "success": str(success).lower(), "reason": reason})
        if success and same:
            obs.increment("tts_fallback_same_language_rate", tags={"provider": provider})
        if success and not same:
            obs.increment("tts_locale_switch_rate", tags={"provider": provider, "expected": expected_locale, "actual": locale})
    except Exception:
        pass


def record_token_request(*, provider: str, lane: str, prompt_tokens: int, output_tokens: int) -> None:
    obs = _obs()
    if obs is None:
        return
    try:
        tags = {"provider": provider or "unknown", "lane": lane or "unknown"}
        obs.observe("avg_prompt_tokens_by_lane", float(max(0, prompt_tokens)), tags=tags)
        obs.observe("output_tokens_by_lane", float(max(0, output_tokens)), tags=tags)
    except Exception:
        pass



def record_lane_budget_plan(
    *,
    provider: str,
    lane: str,
    allowed: bool,
    reason: str,
    requested_prompt: int,
    prompt_limit: int,
    requested_output: int,
    output_limit: int,
    optional: bool,
) -> None:
    obs = _obs()
    if obs is None:
        return
    try:
        tags = {
            "provider": provider or "unknown",
            "lane": lane or "unknown",
            "allowed": str(bool(allowed)).lower(),
            "optional": str(bool(optional)).lower(),
            "reason": reason or "unknown",
        }
        obs.increment("lane_budget_plan_total", tags=tags)
        if not allowed:
            obs.increment("lane_budget_shed_total", tags={"provider": tags["provider"], "lane": tags["lane"]})
        if prompt_limit < requested_prompt or output_limit < requested_output:
            obs.increment("lane_budget_clamp_total", tags={"provider": tags["provider"], "lane": tags["lane"]})
        obs.log(
            "lane_budget_plan",
            tags=tags,
            fields={
                "requested_prompt": requested_prompt,
                "prompt_limit": prompt_limit,
                "requested_output": requested_output,
                "output_limit": output_limit,
            },
        )
    except Exception:
        pass

def record_provider_rate_limit(*, provider: str, lane: str, retry_after_s: float) -> None:
    obs = _obs()
    if obs is None:
        return
    try:
        tags = {"provider": provider or "unknown", "lane": lane or "unknown"}
        obs.increment("429_per_provider_per_lane", tags=tags)
        obs.observe("retry_after_seconds", float(max(0.0, retry_after_s)), tags=tags)
    except Exception:
        pass


def record_constrained_rerun(*, outcome: str, reasons: Iterable[str] = ()) -> None:
    obs = _obs()
    if obs is None:
        return
    try:
        normalized = str(outcome or "unknown").lower()
        if normalized in {"failed", "fallback", "exception", "rejected"}:
            obs.increment("constrained_rerun_fail_rate", tags={"outcome": normalized})
        obs.log("hardening_constrained_rerun", tags={"outcome": normalized}, fields={"reasons": list(reasons)[:12]})
    except Exception:
        pass


def record_user_correction_after_action(*, action: str, strategy: str = "") -> None:
    obs = _obs()
    if obs is None:
        return
    try:
        obs.increment(
            "user_correction_after_action_rate",
            tags={"action": action or "unknown", "strategy": strategy or "unknown"},
        )
    except Exception:
        pass


def record_tts_breaker(*, state: str, event: str, provider: str, locale: str, kind: str = "") -> None:
    obs = _obs()
    if obs is None:
        return
    try:
        obs.increment("tts_breaker_event_total", tags={"state": state, "event": event, "provider": provider, "locale": locale, "kind": kind or "none"})
        if state == "open":
            obs.increment("tts_breaker_open_count", tags={"provider": provider, "locale": locale})
    except Exception:
        pass


__all__ = [
    "record_action_confirmation",
    "record_director_semantic_gate",
    "record_constrained_rerun",
    "record_lane_budget_plan",
    "record_memory_provenance",
    "record_provider_rate_limit",
    "record_repair_state",
    "record_surface_sanitizer",
    "record_token_request",
    "record_tts_breaker",
    "record_tts_fallback",
    "record_user_correction_after_action",
]
