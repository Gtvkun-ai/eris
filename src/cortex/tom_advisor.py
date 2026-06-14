# -*- coding: utf-8 -*-
"""
cortex/tom_advisor.py
=====================

Nước 3 (a)+(b) — cắm Theory-of-Mind pipeline (đang chết) vào response path, với
ngữ nghĩa MiniLM thật thay cho hash fallback.

Bối cảnh (khảo sát chiều-sâu thấu-hiểu-Ngài): ``Phase2MeaningPipeline`` (8 tầng,
có OverreadBrake, counterfactual correction) sản xuất ``MentalStateInference`` —
nhưng KHÔNG runtime nào gọi nó. Tệ hơn: ``GlobalWorkspaceEngine`` dựng
``downstream_contract`` với *field sai* cho các tầng Phase 2 (vd WorldSceneBuilder
cần ``broadcast_items`` nhưng contract chỉ cấp ``selected_evidence``), nên kể cả
nếu có ai chạy thì mọi read đều bị từ chối → scene rỗng → không inference nào. Đó
là lý do tầng ToM "sâu" thực chất là dây không dẫn điện.

Module này nối đúng:
  1. (a) ghi đè ``downstream_contract`` bằng HỢP ĐỒNG PHASE 2 ĐÚNG (các field mà
     từng tầng thật sự đọc) — không mutate frame gốc (dùng dataclasses.replace).
  2. (b) tiêm một ``SemanticHypothesisEngine`` nền MiniLM (qua EmbeddingIndex dùng
     chung) thay cho ``LexicalHashingSemanticEncoder`` hash-fallback, khi bật.
  3. chạy pipeline, rút ``MentalStateInference`` đã *surfaced* (đã qua OverreadBrake
     + SurfaceMeaningPolicy) và dựng một dòng advisory ngắn cho prompt.

Nguyên tắc: advisory là SUY ĐOÁN hỗ trợ chọn giọng, KHÔNG phải sự thật — không
đọc ra như đã biết chắc. Chỉ surface read đã qua brake (tôn trọng kỷ luật
anti-overread sẵn có). Mặc định TẮT (cờ ``ERIS_TOM_ADVISOR``); mọi lỗi trả "".
"""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

# Hợp đồng đọc ĐÚNG cho các tầng Phase 2 — đây là phần sửa lõi của (a).
# Khớp chính xác field mà mỗi tầng đọc qua FrameReadView:
#   - WorldSceneBuilder: broadcast_items, active_threads, broadcast_reason (bắt
#     buộc) + dominant_thread (tùy chọn).
#   - SocioculturalContext: social_hypotheses / selected_evidence.
#   - TheoryOfMindCore: selected_memory (history) + forbidden_assumptions (brake).
PHASE2_DOWNSTREAM_CONTRACT: dict[str, list[str]] = {
    "WorldSceneBuilder": [
        "broadcast_items",
        "active_threads",
        "dominant_thread",
        "broadcast_reason",
        "broadcast_label",
    ],
    "WorldInterpreter": ["broadcast_items", "active_threads"],
    "SocioculturalContext": ["social_hypotheses", "selected_evidence"],
    "TheoryOfMindCore": ["selected_memory", "forbidden_assumptions"],
}

# Diễn giải nhẹ category sang tiếng Việt cho dòng advisory (không bắt buộc đúng
# tuyệt đối — chỉ để prompt đọc tự nhiên).
_STATE_VI: dict[str, str] = {
    "frustrated": "đang bực/khó chịu",
    "curious": "đang tò mò",
    "playful": "đang muốn đùa",
    "anxious": "đang lo/bất an",
    "withdrawn": "đang rút lui/khép lại",
    "affectionate": "đang ấm/gần",
    "hurt": "đang tổn thương",
    "content": "đang ổn/bình thản",
}

_TRUE = {"1", "true", "yes", "on"}


def tom_advisor_enabled() -> bool:
    """Cờ bật ToM advisor. MẶC ĐỊNH TẮT."""
    try:
        from cortex.depth_flags import flag_enabled

        return flag_enabled("ERIS_TOM_ADVISOR", default=False)
    except Exception:
        return str(os.getenv("ERIS_TOM_ADVISOR", "")).strip().lower() in _TRUE


def real_embeddings_enabled() -> bool:
    """Cờ dùng MiniLM thật cho meaning pipeline. MẶC ĐỊNH TẮT (fallback hash)."""
    try:
        from cortex.depth_flags import flag_enabled

        return flag_enabled("ERIS_MEANING_REAL_EMBEDDINGS", default=False)
    except Exception:
        return str(os.getenv("ERIS_MEANING_REAL_EMBEDDINGS", "")).strip().lower() in _TRUE


def build_real_semantic_engine() -> Any | None:
    """(b) — dựng SemanticHypothesisEngine nền MiniLM qua EmbeddingIndex dùng chung.

    None khi tắt cờ / thiếu model / lỗi → pipeline tự dùng fallback xác định.
    """
    if not real_embeddings_enabled():
        return None
    try:
        from memory.embedding_index import get_shared_embedding_index

        index = get_shared_embedding_index()
        if index is None:
            return None
        from cortex.semantic_encoder import ProviderBackedSemanticEncoder
        from cortex.semantic_hypothesis import SemanticHypothesisEngine

        encoder = ProviderBackedSemanticEncoder(index.embed_events, model_id="minilm_shared")
        return SemanticHypothesisEngine(encoder)
    except Exception:
        return None


def _frame_with_phase2_contract(ws_frame: Any) -> Any | None:
    """Bản sao của WorkspaceFrame với downstream_contract ĐÚNG cho Phase 2.

    Không mutate frame gốc (frame runtime vẫn giữ contract cũ cho consumer cũ)."""
    try:
        return replace(ws_frame, downstream_contract=dict(PHASE2_DOWNSTREAM_CONTRACT))
    except Exception:
        return None


def _extract_workspace(obj: Any) -> Any | None:
    """Lấy WorkspaceFrame từ một WorkspaceFrame trực tiếp hoặc một CognitiveFrame.

    Nhận diện WorkspaceFrame bằng duck-typing (có broadcast_items +
    downstream_contract). Với CognitiveFrame runtime, thử slot ``workspace``.
    """
    if obj is None:
        return None
    if hasattr(obj, "broadcast_items") and hasattr(obj, "downstream_contract"):
        return obj
    ws = getattr(obj, "workspace", None)
    if ws is not None and hasattr(ws, "broadcast_items"):
        return ws
    getter = getattr(obj, "get_slot", None)
    if callable(getter):
        try:
            slot = getter("workspace")
            val = getattr(slot, "value", slot)
            if val is not None and hasattr(val, "broadcast_items"):
                return val
        except Exception:
            return None
    return None


def _render_advisory(result: Any) -> str:
    """Rút MentalStateInference đã surfaced thành một dòng advisory ngắn. "" nếu không có."""
    surfaced = list(getattr(result, "surfaced", ()) or ())
    best = None
    best_conf = -1.0
    for ev in surfaced:
        if str(getattr(ev, "kind", "")) != "mental_state":
            continue
        conf = float(getattr(ev, "confidence", 0.0) or 0.0)
        if conf > best_conf:
            best_conf = conf
            best = ev
    if best is None:
        return ""
    conclusion = getattr(best, "conclusion", None)
    category = str(getattr(conclusion, "category", "") or "").strip()
    if not category:
        return ""
    vi = _STATE_VI.get(category, category)
    return (
        f"tom_read: Ngài có thể {vi} (độ tin ~{max(0.0, best_conf):.2f}). "
        "Đây là SUY ĐOÁN hỗ trợ chọn giọng, KHÔNG phải sự thật — đừng nói thẳng ra "
        "như đã biết chắc; chỉ để điều chỉnh khoảng cách và độ ấm."
    )


def advise_from_workspace(ws_frame: Any) -> str:
    """Chạy Phase 2 trên một WorkspaceFrame (contract đã sửa) → dòng advisory."""
    if ws_frame is None:
        return ""
    frame = _frame_with_phase2_contract(ws_frame)
    if frame is None:
        return ""
    try:
        from cortex.meaning import Phase2MeaningPipeline

        pipeline = Phase2MeaningPipeline(semantic_engine=build_real_semantic_engine())
        result = pipeline.run(frame)
    except Exception:
        return ""
    try:
        return _render_advisory(result)
    except Exception:
        return ""


def advise(frame_or_ws: Any) -> str:
    """Entry cho runtime: gate cờ, lấy WorkspaceFrame, trả advisory. "" khi tắt/lỗi."""
    if not tom_advisor_enabled():
        return ""
    ws = _extract_workspace(frame_or_ws)
    if ws is None:
        return ""
    return advise_from_workspace(ws)
