# -*- coding: utf-8 -*-
"""
tutor_login.py — đăng nhập Google một lần cho Curiosity Tutor.

Chạy MỘT lần:
    python tutor_login.py

Nó mở cửa sổ Chromium dùng đúng profile bền vững (ERIS_TUTOR_PROFILE_DIR), điều hướng tới
gemini.google.com. Bạn đăng nhập Google trong cửa sổ đó. Khi xong, quay lại terminal và
nhấn Enter để lưu phiên và đóng. Từ đó ERIS dùng lại phiên này, không phải đăng nhập nữa.
"""

import os
import sys

sys.path.insert(0, "src")

try:
    from eris_secrets import load_env_file
    load_env_file(force=True)
except Exception:
    pass

PROFILE = os.environ.get("ERIS_TUTOR_PROFILE_DIR") or r"C:\Users\Gtvkun\Documents\eris_tutor_profile"
NAV_URL = os.environ.get("ERIS_TUTOR_NAV_URL") or "https://gemini.google.com"


def main() -> None:
    os.makedirs(PROFILE, exist_ok=True)
    from playwright.sync_api import sync_playwright

    channel = (os.environ.get("ERIS_TUTOR_BROWSER_CHANNEL") or "chrome").strip()
    # Chống phát hiện automation (Google chặn "browser may not be secure").
    launch_kwargs = dict(
        headless=False,
        ignore_default_args=["--enable-automation"],
        args=["--disable-blink-features=AutomationControlled"],
    )

    print(f"[tutor_login] profile = {PROFILE}")
    print(f"[tutor_login] channel = {channel or '(chromium bundled)'}")
    print(f"[tutor_login] mở {NAV_URL} ...")
    with sync_playwright() as p:
        try:
            if channel:
                ctx = p.chromium.launch_persistent_context(PROFILE, channel=channel, **launch_kwargs)
            else:
                ctx = p.chromium.launch_persistent_context(PROFILE, **launch_kwargs)
        except Exception as exc:
            print(f"[tutor_login] không mở được Chrome thật ({exc!r}); fallback Chromium bundled.")
            ctx = p.chromium.launch_persistent_context(PROFILE, **launch_kwargs)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(NAV_URL, wait_until="domcontentloaded")
        print("\n>>> Đăng nhập Google trong cửa sổ vừa mở. Xong thì quay lại đây.")
        try:
            input(">>> Nhấn Enter để LƯU phiên và đóng cửa sổ... ")
        except (EOFError, KeyboardInterrupt):
            pass
        try:
            ctx.close()
        except Exception:
            pass
    print("[tutor_login] Đã lưu phiên. ERIS sẽ dùng lại profile này.")


if __name__ == "__main__":
    main()
