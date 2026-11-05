# -*- coding: utf-8 -*-
"""Chiếu bằng chứng tương tác cho Root, KHÔNG chọn hành vi thay Root.

EQ ở đây là phán đoán có ngữ cảnh: runtime chỉ chuyển tiếp lời đã phát,
phản hồi thật và nhận định *có thể sai* của observer. Không đoán cảm xúc theo
bảng từ khóa, không sinh chỉ thị «buồn thì an ủi», không tạo agent/LLM mới.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence


_INVALID_DELIVERY = frozenset({
    "preparing", "pending", "queued_for_audio", "delivering",
    "failed_before_delivery", "delivery_failed", "cancelled", "unconfirmed_after_restart",
})


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _past_interaction_evidence(state: Any, *, session_id: str, limit: int = 2) -> list[dict[str, Any]]:
    """Chỉ lấy tình huống đã có phản ứng user và observer đánh giá.

    Xếp theo lần ghi nhận, KHÔNG xếp theo utility: một thành công cũ không
    có quyền áp đảo ý định mới. Không chiếu pending chưa có kết quả.
    """
    if state is None or not getattr(state, "identity_learning_enabled", True):
        return []
    identity = getattr(state, "identity", None)
    strategies = getattr(identity, "strategies", None)
    if not isinstance(strategies, Mapping):
        return []
    records: list[tuple[float, dict[str, Any]]] = []
    for strategy_name, record in strategies.items():
        for raw in tuple(getattr(record, "experiences", ()) or ()):
            if not isinstance(raw, Mapping):
                continue
            assistant_ref = _text(raw.get("assistant_ref"), 100)
            reaction_ref = _text(raw.get("reaction_ref"), 180)
            reaction_text = _text(raw.get("reaction_text"), 300)
            assistant_text = _text(raw.get("assistant_text"), 300)
            # Không chấm lời chưa phát, không học từ phỏng đoán trước khi user trả lời.
            if not assistant_ref or not reaction_ref or not reaction_text or not assistant_text:
                continue
            try:
                confidence = float(raw.get("confidence", 0.0) or 0.0)
                settled_at = float(raw.get("settled_at", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if not 0.0 <= confidence <= 1.0 or confidence < 0.62:
                continue
            source = _text(raw.get("interpretation_source"), 80)
            if source != "post_turn_observer":
                continue
            past_session = _text(raw.get("session_id"), 180)
            # Không đẩy session ID hoặc nội dung quan hệ của chủ thể khác vào prompt.
            if not past_session:
                continue
            item = {
                "strategy": _text(strategy_name, 100),
                "situation": _text(raw.get("situation"), 200),
                "goal": _text(raw.get("goal"), 160),
                "assistant_said": assistant_text,
                "user_replied": reaction_text,
                "outcome_hypothesis": _text(raw.get("outcome"), 60),
                "assessment_confidence": round(confidence, 2),
                "reaction_ref": reaction_ref,
                "scope": "same_session" if past_session == session_id else "past_session",
                "provenance": source,
            }
            records.append((settled_at, item))

    records.sort(key=lambda row: row[0], reverse=True)
    # Một trường hợp cùng phiên được ưu tiên, trường hợp còn lại xét theo
    # độ mới. Không coi một nhận định observer là sở thích vĩnh viễn.
    same = [entry for _, entry in records if entry["scope"] == "same_session"]
    candidates = ([same[0]] if same else []) + [
        entry for _, entry in records if not same or entry is not same[0]
    ]
    seen: set[str] = set()
    selected: list[dict[str, Any]] = []
    for entry in candidates:
        ref = entry["reaction_ref"]
        if ref in seen:
            continue
        selected.append(entry)
        seen.add(ref)
        if len(selected) >= limit:
            break
    return selected


def project_social_situation(
    *,
    event_kind: str,
    user_text: str,
    session_id: str,
    state: Any = None,
    handoff: Mapping[str, Any] | None = None,
    recent_history: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Projection chỉ-đọc, chỉ cho user turn, không tự suy diễn ý định.

    event.text và history đã chứa hội thoại gốc; ở đây chỉ cung cấp neo
    thời gian/provenance và vài trường hợp đã có phản ứng thật.
    """
    current = _text(user_text, 32000)
    if event_kind != "user_turn" or not current:
        return {}
    result: dict[str, Any] = {
        "schema": "eris.social_situation.evidence.v1",
        "authority": "evidence_only_root_decides",
    }
    # Dựa vào history gần nhất đã công khai, không coi bản chuẩn bị phát là lời
    # Eris đã nói. Câu không có delivery_status được ghi là chưa xác nhận.
    for line in reversed(tuple(recent_history)[-12:]):
        if not isinstance(line, Mapping) or str(line.get("role", "")).lower() != "assistant":
            continue
        delivery_status = _text(line.get("delivery_status"), 60).lower()
        if delivery_status in _INVALID_DELIVERY:
            continue
        result["previous_assistant"] = {
            "excerpt": _text(line.get("raw_content", line.get("content", "")), 240),
            "delivery_status": delivery_status or "unknown",
            "delivery_confirmed": delivery_status == "delivered",
        }
        break

    # Handoff là bộ quan sát của chính lượt hiện tại. Chặn snapshot cũ lọt
    # sang lượt mới khi callback chưa đồng bộ; các nhãn là giả thuyết, không
    # phải phán quyết về cảm xúc hay hành vi cần chọn.
    observation = handoff if isinstance(handoff, Mapping) else {}
    observed_text = _text(observation.get("last_user_text"), 520)
    if observed_text and observed_text == current[:520]:
        hypotheses = observation.get("causal_hypotheses", ())
        top = next((x for x in hypotheses if isinstance(x, Mapping)), None) if isinstance(
            hypotheses, (list, tuple)
        ) else None
        result["current_handoff"] = {
            "user_stance_observed": _text(observation.get("user_stance"), 60),
            "repair_signal": bool(observation.get("repair_needed", False)),
            "previous_assistant_ref": _text(observation.get("last_assistant_turn_ref"), 120),
            "hypothesis": {
                "kind": _text(top.get("kind"), 80),
                "summary": _text(top.get("summary"), 180),
            } if top else {},
        }

    examples = _past_interaction_evidence(state, session_id=session_id)
    if examples:
        result["past_interactions"] = examples
        result["past_interactions_scope"] = (
            "Observer's fallible interpretation of a specific exchange, "
            "not a permanent user preference or a command for this turn."
        )
    return result


__all__ = ["project_social_situation"]
