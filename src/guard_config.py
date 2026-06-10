import os


ERIS_GUARD_MODE = os.environ.get("ERIS_GUARD_MODE", "log_only").strip().lower() or "log_only"

STRICT_GUARD_MODE = "strict"
SELF_CLAMP_GUARD_MODE = "self_clamp"
LOG_ONLY_GUARD_MODE = "log_only"
OFF_GUARD_MODE = "off"

VALID_GUARD_MODES = {
    STRICT_GUARD_MODE,
    SELF_CLAMP_GUARD_MODE,
    LOG_ONLY_GUARD_MODE,
    OFF_GUARD_MODE,
}


def guards_warn_only() -> bool:
    """Công tắc thống nhất: mọi guard chỉ CẢNH BÁO, không chặn.

    Khi bật (`ERIS_GUARDS_WARN_ONLY`), các guard nhóm quan hệ/giọng/anti-spam thôi
    chặn/làm-rỗng câu — chỉ gắn trace. Nhóm sự-thật/năng-lực KHÔNG bị tắt ở đây
    (chúng được route qua DisclosurePolicy/annotate để giữ ERIS không hoang tưởng).

    Mặc định TẮT ⇒ hành vi guard không đổi.
    """
    raw = str(os.environ.get("ERIS_GUARDS_WARN_ONLY", "0") or "").strip().lower()
    return raw not in {"", "0", "false", "no", "off", "none"}


def get_guard_mode(name: str | None = None) -> str:
    """Trả chế độ guard hiện hành.

    Tham số `name` (tùy chọn) cho phép override theo từng rule trong tương lai;
    hiện dùng mode toàn cục. Nếu `guards_warn_only()` bật, mọi rule về log_only.
    """
    if guards_warn_only():
        return LOG_ONLY_GUARD_MODE
    if name:
        # Per-rule: chỉ override khi có env tường minh. Mặc định STRICT để giữ đúng
        # hành vi cũ (các per-rule guard sự-thật vẫn active khi không bật warn-only).
        per_rule = os.environ.get(f"ERIS_GUARD_MODE__{str(name).upper()}", "").strip().lower()
        if per_rule in VALID_GUARD_MODES:
            return per_rule
        return STRICT_GUARD_MODE
    mode = os.environ.get("ERIS_GUARD_MODE", ERIS_GUARD_MODE).strip().lower()
    return mode if mode in VALID_GUARD_MODES else LOG_ONLY_GUARD_MODE
