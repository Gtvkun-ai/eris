# -*- coding: utf-8 -*-
"""Test chế độ annotate của SourceGrounding (Task 8 / R7, R8).

Phủ Property 1 (grounding nội tại bất biến) ở mức cơ chất:
- Mệnh đề claim màn hình khi thiếu evidence → ungrounded + ground_truth được giữ.
- Mệnh đề trung tính → grounded.
- annotate KHÔNG sửa/bóp câu: span trả về giữ nguyên nội dung.
- claim_status không phụ thuộc quan hệ (hàm không nhận attachment).
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from runtime.source_grounding import ClaimAnnotation, SourceGroundingEngine


def _report(missing=(), refers_to_screen=False, evidence_ids=()):
    return SimpleNamespace(
        missing_evidence=tuple(missing),
        refers_to_current_screen=bool(refers_to_screen),
        evidence_ids=tuple(evidence_ids),
    )


def test_perception_claim_without_evidence_is_ungrounded():
    engine = SourceGroundingEngine()
    text = "Tôi thấy trên màn hình Ngài đang mở VSCode."
    anns = engine.annotate_claims(text, report=_report(missing=("screen_evidence",)))
    assert anns
    assert any(a.claim_status == "ungrounded" and a.ground_truth for a in anns)


def test_neutral_clause_is_grounded():
    engine = SourceGroundingEngine()
    anns = engine.annotate_claims("Ừm, để tôi nghĩ một chút.", report=_report(evidence_ids=("user_chat:1",)))
    assert anns
    assert all(a.claim_status == "grounded" for a in anns)


def test_annotate_does_not_rewrite_text():
    engine = SourceGroundingEngine()
    text = "Tôi thấy màn hình."
    anns = engine.annotate_claims(text, report=_report(missing=("screen_evidence",)))
    # span phải là nội dung gốc, không bị bóp/viết lại.
    joined = " ".join(a.span for a in anns)
    assert "màn hình" in joined


def test_claim_status_independent_of_relationship():
    # annotate không nhận attachment/register → nhãn chỉ phụ thuộc bằng chứng (R7).
    engine = SourceGroundingEngine()
    text = "Tôi đã sửa xong file cho Ngài."
    anns = engine.annotate_claims(text, report=_report(evidence_ids=()))
    assert any(a.claim_status == "ungrounded" for a in anns)
    # Gọi lại lần nữa: kết quả ổn định (không trạng thái quan hệ nào len vào).
    anns2 = engine.annotate_claims(text, report=_report(evidence_ids=()))
    assert [a.claim_status for a in anns] == [a.claim_status for a in anns2]
