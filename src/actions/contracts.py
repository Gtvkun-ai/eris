from dataclasses import dataclass, field

# Các hằng số và lớp dữ liệu liên quan đến các hành động và quyết định trong hệ thống.

VALID_SYSTEM_ACTION_LIST = (
    "get_now_playing",
    "focus_window",
    "open_url",
    "set_volume",
    "play_pause_media",
    "copy_text",
    "launch_app",
    "search_web",
    "get_weather",
)

VALID_SYSTEM_ACTIONS = set(VALID_SYSTEM_ACTION_LIST)


@dataclass(slots=True)
class ActionExecutionResult:
    action_name: str
    action_input: str = ""
    success: bool = False
    message: str = ""
    data: dict[str, str] = field(default_factory=dict)
