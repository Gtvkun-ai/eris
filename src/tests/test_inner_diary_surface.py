# -*- coding: utf-8 -*-
"""Test nối Inner Diary → autonomous (gồm random_chatter mới).

Diary trước chỉ chảy 3 kênh (muon_noi/tuong_lai/hien_tai). Giờ thêm:
- ban_tam → inner_whim
- phan_tich → random_chatter
Để diary 'sống' và random_chatter có chất liệu thật, không cần vital_pressure cao.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.surface_seed_compiler import SurfaceSeedCompiler


def _kinds(candidates):
    return {getattr(c, "impulse_kind", "") for c in candidates}


def test_direct_voice_keys_produce_all_channels():
    compiler = SurfaceSeedCompiler()
    voice = {
        "muon_noi": "Tôi muốn nói một điều nhỏ.",
        "tuong_lai": "Không biết lát nữa sẽ ra sao.",
        "hien_tai": "Khoảnh khắc này khá yên.",
        "ban_tam": "Có một chuyện cứ vương trong đầu tôi.",
        "phan_tich": "Tôi vừa để ý một khuôn mẫu nhỏ.",
    }
    cands = compiler._from_inner_diary(voice)
    kinds = _kinds(cands)
    assert "random_chatter" in kinds   # từ phan_tich
    assert "inner_whim" in kinds        # muon_noi + ban_tam
    assert "curious_question" in kinds  # tuong_lai
    assert "light_muse" in kinds        # hien_tai


def test_rendered_sections_feed_random_chatter():
    compiler = SurfaceSeedCompiler()
    rendered = {
        "sections": [
            {"title": "Phân tích gần đây", "lines": ["Tôi để ý nhịp gõ phím chậm lại."]},
            {"title": "Đang bận tâm", "lines": ["Có điều gì đó chưa xong cứ lởn vởn."]},
        ]
    }
    cands = compiler._from_inner_diary(rendered)
    kinds = _kinds(cands)
    assert "random_chatter" in kinds
    assert "inner_whim" in kinds


def test_empty_diary_yields_nothing():
    compiler = SurfaceSeedCompiler()
    assert compiler._from_inner_diary({}) == ()
    assert compiler._from_inner_diary(None) == ()
