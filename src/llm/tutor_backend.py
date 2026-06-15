# -*- coding: utf-8 -*-
"""
llm/tutor_backend.py
====================

Backend gia sư: trừu tượng + bản hiện thực tự động hóa trình duyệt thật (Playwright,
headed) điều khiển gemini.google.com qua một hồ sơ Google đăng nhập sẵn.

- `TutorBackend`: giao diện `ask()` / `close()`.
- `FakeTutorBackend`: dùng cho test (trả answer cố định, giả lập timeout/captcha/empty).
- `GeminiWebBackend`: Playwright headed. Để test được phần parse/timeout/captcha mà không
  lên mạng, nó nhận `page_session_factory` — một callable trả về context manager cho một
  "phiên trang" (PageSession). Thiếu factory ⇒ tự dựng phiên Playwright thật.

KHÔNG log cookie/email/HTML trang đăng nhập. Tắt Master_Switch ⇒ không mở trình duyệt,
không truy cập mạng.
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable, Optional, Protocol, runtime_checkable

try:  # pragma: no cover
    from cortex.tutor.contracts import TutorAnswer, TutorQuestion
    from cortex.tutor.config import TutorConfig
except Exception:  # pragma: no cover
    from src.cortex.tutor.contracts import TutorAnswer, TutorQuestion  # type: ignore
    from src.cortex.tutor.config import TutorConfig  # type: ignore


StageCb = Optional[Callable[[str], None]]


class CaptchaOrExpired(Exception):
    """Gia sư web yêu cầu captcha/đăng nhập lại — không thể tự vượt."""


class SelectorMiss(Exception):
    """Không tìm thấy selector cần thiết trên trang."""


@runtime_checkable
class TutorBackend(Protocol):
    def ask(self, question: TutorQuestion, *, on_stage: StageCb = None) -> TutorAnswer: ...
    def close(self) -> None: ...


# =============================================================================
# Fake backend cho test
# =============================================================================

class FakeTutorBackend:
    """Backend giả: trả answer cố định, có thể giả lập lỗi. KHÔNG đụng mạng."""

    def __init__(
        self,
        *,
        answer_text: str = "",
        citations: tuple[str, ...] = (),
        raise_exc: Optional[BaseException] = None,
        fail_reason: Optional[str] = None,
    ) -> None:
        self.answer_text = answer_text
        self.citations = citations
        self.raise_exc = raise_exc
        self.fail_reason = fail_reason
        self.stages_seen: list[str] = []
        self.closed = False
        self.ask_calls = 0

    def ask(self, question: TutorQuestion, *, on_stage: StageCb = None) -> TutorAnswer:
        self.ask_calls += 1

        def emit(stage: str) -> None:
            self.stages_seen.append(stage)
            if on_stage:
                on_stage(stage)

        emit("opening")
        if self.raise_exc is not None:
            raise self.raise_exc
        emit("asking")
        emit("reading")
        if self.fail_reason is not None:
            return TutorAnswer(ok=False, fail_reason=self.fail_reason)  # type: ignore[arg-type]
        ok = bool(self.answer_text)
        return TutorAnswer(
            text=self.answer_text,
            citations=self.citations,
            ok=ok,
            fail_reason=None if ok else "empty_answer",
        )

    def close(self) -> None:
        self.closed = True


# =============================================================================
# Gemini web backend (Playwright headed)
# =============================================================================

@runtime_checkable
class PageSession(Protocol):
    """Phiên trang trừu tượng để GeminiWebBackend không bám cứng Playwright (test được)."""

    def goto(self, url: str) -> None: ...
    def is_blocked(self) -> bool: ...               # captcha / màn đăng nhập
    def submit_question(self, text: str, *, delay_min_ms: int, delay_max_ms: int) -> None: ...
    def read_answer(self, *, stable_window_s: float, deadline: float) -> str: ...
    def citations(self) -> tuple[str, ...]: ...


class GeminiWebBackend:
    """Tự động hóa gemini.google.com bằng trình duyệt thật."""

    def __init__(
        self,
        config: Optional[TutorConfig] = None,
        logger: Any = None,
        *,
        page_session_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.config = (config or TutorConfig()).normalized()
        self.logger = logger
        self._factory = page_session_factory
        self._opened = False

    def ask(self, question: TutorQuestion, *, on_stage: StageCb = None) -> TutorAnswer:
        if not self.config.enabled:
            # Master_Switch tắt ⇒ tuyệt đối không mở trình duyệt / không truy cập mạng.
            return TutorAnswer(ok=False, fail_reason="network_error")

        def emit(stage: str) -> None:
            if on_stage:
                on_stage(stage)

        deadline = time.time() + self.config.episode_timeout_s
        factory = self._factory or self._default_factory
        session_cm = factory()
        emit("opening")
        try:
            with session_cm as session:
                self._opened = True
                session.goto(self.config.nav_url)
                if session.is_blocked():
                    raise CaptchaOrExpired("captcha hoặc phiên đăng nhập hết hạn")
                emit("asking")
                session.submit_question(
                    question.text,
                    delay_min_ms=self.config.type_delay_ms_min,
                    delay_max_ms=self.config.type_delay_ms_max,
                )
                emit("reading")
                text = session.read_answer(
                    stable_window_s=self.config.answer_stable_window_s,
                    deadline=deadline,
                )
                citations = ()
                try:
                    citations = tuple(session.citations() or ())
                except Exception:
                    citations = ()
        except CaptchaOrExpired:
            return TutorAnswer(ok=False, fail_reason="captcha_or_expired")
        except SelectorMiss:
            return TutorAnswer(ok=False, fail_reason="selector_miss")
        except TimeoutError:
            return TutorAnswer(ok=False, fail_reason="timeout")
        except Exception:
            return TutorAnswer(ok=False, fail_reason="network_error")

        text = str(text or "").strip()
        if not text:
            return TutorAnswer(ok=False, fail_reason="empty_answer")
        return TutorAnswer(text=text, citations=citations, ok=True)

    def close(self) -> None:
        self._opened = False

    # ------------------------------------------------------------------
    # Phiên Playwright thật — chỉ dựng khi không có factory (không test online).
    # ------------------------------------------------------------------

    def _default_factory(self):  # pragma: no cover - cần Playwright + mạng + login
        config = self.config

        class _PlaywrightSession:
            def __init__(self) -> None:
                self._pw = None
                self._ctx = None
                self._page = None

            def __enter__(self):
                from playwright.sync_api import sync_playwright  # type: ignore

                self._pw = sync_playwright().start()
                # Chống phát hiện automation: bỏ cờ --enable-automation, tắt
                # AutomationControlled. Ưu tiên Chrome thật (channel) — Google tin hơn.
                browser_args = [
                    "--disable-blink-features=AutomationControlled",
                    f"--window-position={config.window_x},{config.window_y}",
                    f"--window-size={config.window_width},{config.window_height}",
                ]
                if config.app_mode:
                    # App window: bỏ thanh địa chỉ/tab cho gọn ("trang trí").
                    browser_args.append(f"--app={config.nav_url}")
                launch_kwargs = dict(
                    headless=False,
                    viewport={"width": config.window_width, "height": config.window_height},
                    ignore_default_args=["--enable-automation"],
                    args=browser_args,
                )
                channel = (config.browser_channel or "").strip()
                try:
                    if channel:
                        self._ctx = self._pw.chromium.launch_persistent_context(
                            config.profile_dir, channel=channel, **launch_kwargs
                        )
                    else:
                        self._ctx = self._pw.chromium.launch_persistent_context(
                            config.profile_dir, **launch_kwargs
                        )
                except Exception:
                    # Fallback: Chromium bundled nếu Chrome thật không khả dụng.
                    self._ctx = self._pw.chromium.launch_persistent_context(
                        config.profile_dir, **launch_kwargs
                    )
                # App-mode: dùng page sẵn có (đã mở nav_url) để không tạo tab thừa.
                pages = list(getattr(self._ctx, "pages", []) or [])
                self._page = pages[0] if (config.app_mode and pages) else self._ctx.new_page()
                return self

            def __exit__(self, *exc):
                for closer in (getattr(self._ctx, "close", None), getattr(self._pw, "stop", None)):
                    try:
                        if callable(closer):
                            closer()
                    except Exception:
                        pass
                return False

            def goto(self, url: str) -> None:
                self._page.goto(url, wait_until="domcontentloaded")

            def is_blocked(self) -> bool:
                marker = config.sel_login_marker
                if not marker:
                    return False
                try:
                    return self._page.locator(marker).count() > 0
                except Exception:
                    return False

            def submit_question(self, text: str, *, delay_min_ms: int, delay_max_ms: int) -> None:
                box = self._page.locator(config.sel_input).first
                box.click()
                for ch in text:
                    if ch == "\r":
                        continue
                    if ch == "\n":
                        # Enter trong ô Gemini = GỬI luôn → câu hỏi nhiều dòng sẽ bị
                        # cắt và submit dở. Shift+Enter để xuống dòng mà không gửi.
                        self._page.keyboard.press("Shift+Enter")
                        continue
                    box.type(ch, delay=random.randint(delay_min_ms, delay_max_ms))
                time.sleep(random.uniform(0.3, 0.9))
                try:
                    self._page.locator(config.sel_send).first.click(timeout=3000)
                except Exception:
                    self._page.keyboard.press("Enter")

            def read_answer(self, *, stable_window_s: float, deadline: float) -> str:
                last = ""
                stable_since = None
                while time.time() < deadline:
                    try:
                        nodes = self._page.locator(config.sel_response)
                        current = nodes.last.inner_text(timeout=2000) if nodes.count() else ""
                    except Exception:
                        current = last
                    if current and current == last:
                        if stable_since is None:
                            stable_since = time.time()
                        elif time.time() - stable_since >= stable_window_s:
                            return current
                    else:
                        stable_since = None
                        last = current
                    time.sleep(0.4)
                raise TimeoutError("đọc câu trả lời vượt deadline")

            def citations(self) -> tuple[str, ...]:
                return ()

        return _PlaywrightSession()


__all__ = [
    "TutorBackend",
    "FakeTutorBackend",
    "GeminiWebBackend",
    "PageSession",
    "CaptchaOrExpired",
    "SelectorMiss",
]
