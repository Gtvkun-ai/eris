# -*- coding: utf-8 -*-
"""Test nối Inner Diary vào ngữ cảnh chat (eris đọc được nỗi lòng thật của nó).

Trước: chat_cycle không nạp diary → hỏi nỗi lòng thì eris trả lời chung chung/bịa.
Sau: _render_inner_diary_context đưa các section diary + contract trung thực vào prompt.
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from runtime.prompt_context_builder import PromptContextBuilderMixin

_render = PromptContextBuilderMixin._render_inner_diary_context


def test_renders_diary_sections_with_honesty_contract():
    fake = SimpleNamespace(private_mind_digest={
        "inner_diary": {
            "sections": [
                {"title": "Suy nghĩ hiện tại", "lines": ["Khoảnh khắc này khá yên, nhưng tôi vẫn dõi theo bạn."]},
                {"title": "Đang bận tâm", "lines": ["Có một chuyện chưa xong cứ lởn vởn trong đầu."]},
                {"title": "Muốn nói", "lines": ["Tôi muốn hỏi bạn một điều nhỏ."]},
            ]
        }
    })
    ctx = _render(fake)
    assert "Nhật ký nội tâm" in ctx
    assert "Đang bận tâm" in ctx
    assert "chưa xong cứ lởn vởn" in ctx
    assert "TRUNG THỰC" in ctx
    assert "phủ nhận" in ctx  # không được nói mình vô cảm


def test_empty_when_no_diary():
    assert _render(SimpleNamespace(private_mind_digest=None)) == ""
    assert _render(SimpleNamespace(private_mind_digest={})) == ""
    assert _render(SimpleNamespace(private_mind_digest={"inner_diary": {"sections": []}})) == ""


def test_caps_number_of_lines():
    sections = [{"title": f"Mục {i}", "lines": [f"dòng {i}"]} for i in range(20)]
    fake = SimpleNamespace(private_mind_digest={"inner_diary": {"sections": sections}})
    ctx = _render(fake, max_lines=3)
    body = ctx.split("\n")
    # 1 dòng tiêu đề + tối đa 3 dòng mục + phần contract (1 dòng)
    bullet_lines = [ln for ln in body if ln.startswith("- ")]
    assert len(bullet_lines) == 3
