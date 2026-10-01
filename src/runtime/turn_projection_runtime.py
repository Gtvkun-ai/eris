# -*- coding: utf-8 -*-
"""Projection turn-taking từ root AgentLoop ra UI/Live2D.

Module này **không quyết định** Eris có giữ lượt hay nhường lượt. Quyết định đó
đã nằm trong ``TurnProjection`` do root AgentLoop sinh. Adapter chỉ chuyển exact
projection thành event public-safe cho stage.

Boundary bắt buộc:
- Không suy ra floor từ độ dài text, voice mode, continuation_mode hay số beat.
- Không chèn lời, dấu ba chấm, filler hay continuation text.
- Không tự đổi HOLD <-> YIELD. Nếu projection sai contract, validator phải trả
  lỗi về AgentLoop để agent tự re-plan.
"""
from __future__ import annotations

from typing import Any

from runtime.agent_loop.contracts import TurnProjection


def emit_turn_projection(
    owner: Any,
    projection: TurnProjection,
    *,
    turn_id: str = "",
    session_id: str = "",
    reason: str = "agent_turn_projection",
) -> bool:
    """Mirror exact agent-owned projection sang ``eris.stage``.

    Event này chỉ chứa state turn-taking public-safe. Không chứa cognitive plan,
    chain-of-thought, planned thread hay nội dung private.
    """

    emit = getattr(owner, "_emit_stage_protocol_state", None)
    if not callable(emit):
        return False
    data = projection.to_dict()
    data.update(
        {
            "turn_id": str(turn_id or "")[:180],
            "session_id": str(session_id or "")[:180],
            "owner": "turn_agent_loop",
        }
    )
    try:
        emit("turn_projection", reason=reason, data=data)
        return True
    except Exception:
        return False


__all__ = ["emit_turn_projection"]
