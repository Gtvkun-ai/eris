from __future__ import annotations

import os
import sys
from types import MethodType, SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from runtime.presence_controller import PresenceControllerMixin


def _make_stub():
    stub = SimpleNamespace()
    stub.last_text = ""
    # Minimal helper stubs used by the fallback path.
    stub._normalize_user_message = MethodType(lambda self, t: str(t or "").lower(), stub)
    stub._sanitize_micro_presence_llm_text = MethodType(
        lambda self, text, kind, fallback_text="": str(text or "").strip(), stub
    )
    stub._is_near_duplicate_text = MethodType(lambda self, a, b: False, stub)
    # Bind the real methods under test.
    stub._safe_local_micro_presence_fallback = MethodType(
        PresenceControllerMixin._safe_local_micro_presence_fallback, stub
    )
    stub._local_micro_presence_fallback_text = MethodType(
        PresenceControllerMixin._local_micro_presence_fallback_text, stub
    )
    return stub


def test_safe_fallback_rejects_banned_line() -> None:
    stub = _make_stub()
    assert stub._safe_local_micro_presence_fallback("Khoảng yên này vẫn giữ chỗ.", kind="micro_presence") == ""
    assert stub._safe_local_micro_presence_fallback("Nhịp này vẫn yên thêm chút.", kind="micro_presence") == ""


def test_safe_fallback_allows_grounded_line() -> None:
    stub = _make_stub()
    out = stub._safe_local_micro_presence_fallback("Cái panel kia vẫn mở năm file.", kind="micro_presence")
    assert out == "Cái panel kia vẫn mở năm file."


def test_coding_fallback_does_not_emit_banned_line() -> None:
    stub = _make_stub()
    snapshot = SimpleNamespace(
        active_window="debug session - vscode",
        active_window_kind="coding",
        focus_summary="debugging",
        recent_events=(),
    )
    out = stub._local_micro_presence_fallback_text(
        kind="presence_maintenance", snapshot=snapshot, seeds=("code",), focus_family="coding"
    )
    # The only candidate the coding branch produces is a banned stale template,
    # so the filter must yield silence rather than the banned line.
    from cortex.banned_filler import is_banned_filler

    assert not is_banned_filler(out)
