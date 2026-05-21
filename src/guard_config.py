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


def get_guard_mode() -> str:
    mode = os.environ.get("ERIS_GUARD_MODE", ERIS_GUARD_MODE).strip().lower()
    return mode if mode in VALID_GUARD_MODES else LOG_ONLY_GUARD_MODE
