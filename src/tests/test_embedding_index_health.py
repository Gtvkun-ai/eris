# -*- coding: utf-8 -*-
"""Task 1: lỗi load embedding không được im lặng, nhưng vẫn fail-soft.

Env test thiếu torch/transformers nên EmbeddingIndex thật luôn rơi vào nhánh
load-fail. Đây chính là trạng thái cần kiểm: recall vẫn chạy (vector rỗng),
debug_status phản ánh đúng, và health signal (logger.error) chỉ phát MỘT LẦN.
"""
from __future__ import annotations

import logging

from memory.embedding_index import EmbeddingIndex


def _fresh_index() -> EmbeddingIndex:
    # model_name rác + cache_dir rỗng -> _load_model ném trong env thiếu torch.
    return EmbeddingIndex(model_name="eris-nonexistent-model-xyz", cache_dir="/eris/nonexistent-cache")


def test_load_fail_returns_empty_vector_without_raising():
    index = _fresh_index()
    # KHÔNG raise: trả tuple rỗng, vẫn cho caller chạy lexical.
    assert index.embed_document("xin chào") == ()
    assert index.embed_query("xin chào") == ()
    assert index.embed_documents(["a", "b"]) == [(), ()]


def test_debug_status_reflects_load_failure():
    index = _fresh_index()
    index.embed_document("x")
    status = index.debug_status()
    assert status["loaded"] is False
    assert status["load_error"]  # khác rỗng
    assert status["load_failed_signaled"] is True


def test_health_signal_logged_exactly_once(caplog):
    index = _fresh_index()
    with caplog.at_level(logging.ERROR, logger="memory.embedding_index"):
        index.embed_document("x")
        index.embed_document("y")
        index.embed_documents(["z", "w"])
    load_fail_errors = [
        rec for rec in caplog.records
        if rec.levelno == logging.ERROR and "model load failed" in rec.getMessage()
    ]
    assert len(load_fail_errors) == 1
    assert index.debug_status()["load_failed_signaled"] is True
