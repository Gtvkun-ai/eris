from __future__ import annotations

"""Registry năng lực public của Eris.

Một nguồn sự thật duy nhất cho câu hỏi "em làm được gì". Router, prompt và UI
không nên mỗi nơi tự bịa một danh sách riêng; làm vậy vài tháng nữa chính Eris
cũng không biết nó có biết mở app hay chỉ đang cosplay bảng help.
"""

from dataclasses import dataclass
from typing import Iterable

from actions.contracts import VALID_SYSTEM_ACTION_LIST


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    id: str
    public_name_vi: str
    description_vi: str
    example_phrases: tuple[str, ...] = ()
    risk_level: str = "low"


_CAPABILITY_DATA: dict[str, CapabilityDefinition] = {
    "launch_app": CapabilityDefinition(
        id="launch_app",
        public_name_vi="mở ứng dụng",
        description_vi="mở app/chương trình có trong cấu hình runtime",
        example_phrases=("mở Chrome", "mở VS Code"),
    ),
    "focus_window": CapabilityDefinition(
        id="focus_window",
        public_name_vi="focus cửa sổ",
        description_vi="đưa một cửa sổ/app đang mở lên trước",
        example_phrases=("focus Godot", "chuyển sang Chrome"),
    ),
    "set_volume": CapabilityDefinition(
        id="set_volume",
        public_name_vi="chỉnh âm lượng",
        description_vi="tăng/giảm/mute âm lượng hệ thống",
        example_phrases=("giảm volume còn 30", "mute đi"),
    ),
    "play_pause_media": CapabilityDefinition(
        id="play_pause_media",
        public_name_vi="điều khiển media",
        description_vi="play/pause/next/previous media bằng phím hệ thống",
        example_phrases=("pause nhạc", "next bài"),
    ),
    "copy_text": CapabilityDefinition(
        id="copy_text",
        public_name_vi="copy text",
        description_vi="đưa đoạn text vào clipboard",
        example_phrases=("copy đoạn này",),
    ),
    "open_url": CapabilityDefinition(
        id="open_url",
        public_name_vi="mở đường dẫn",
        description_vi="mở URL hợp lệ trong trình duyệt",
        example_phrases=("mở link này",),
    ),
    "search_web": CapabilityDefinition(
        id="search_web",
        public_name_vi="tìm web",
        description_vi="tra cứu web khi runtime/tool tương ứng khả dụng",
        example_phrases=("search vụ này", "tìm thời sự"),
    ),
    "get_weather": CapabilityDefinition(
        id="get_weather",
        public_name_vi="xem thời tiết",
        description_vi="lấy dự báo/thời tiết theo địa điểm nếu có tool",
        example_phrases=("thời tiết Hà Nội",),
    ),
    "get_now_playing": CapabilityDefinition(
        id="get_now_playing",
        public_name_vi="xem media đang phát",
        description_vi="đọc nhanh track/app media đang phát nếu hệ điều hành cho phép",
        example_phrases=("đang phát bài gì",),
    ),
}


def iter_public_capabilities(action_ids: Iterable[str] | None = None) -> tuple[CapabilityDefinition, ...]:
    ids = tuple(action_ids or VALID_SYSTEM_ACTION_LIST)
    out: list[CapabilityDefinition] = []
    for action_id in ids:
        cap = _CAPABILITY_DATA.get(str(action_id))
        if cap is not None:
            out.append(cap)
    return tuple(out)


def render_capability_registry_prompt(action_ids: Iterable[str] | None = None, *, max_items: int = 8) -> str:
    caps = iter_public_capabilities(action_ids)[: max(1, int(max_items))]
    lines = ["CAPABILITY_REGISTRY: answer capability questions only from this list."]
    for cap in caps:
        examples = "; ".join(cap.example_phrases[:2])
        extra = f" Example: {examples}." if examples else ""
        lines.append(f"- {cap.id}: {cap.public_name_vi} — {cap.description_vi}.{extra}")
    lines.append("Do not add medical/legal disclaimers for a capability question unless the user asks for that domain.")
    return "\n".join(lines)


def capability_surface_keywords(action_ids: Iterable[str] | None = None) -> tuple[str, ...]:
    words: list[str] = []
    for cap in iter_public_capabilities(action_ids):
        words.extend((cap.id.replace("_", " "), cap.public_name_vi, cap.description_vi))
        words.extend(cap.example_phrases)
    # vài surface thường gặp khi model nói ngắn
    words.extend(("ứng dụng", "cửa sổ", "âm lượng", "volume", "media", "clipboard", "web", "thời tiết"))
    return tuple(dict.fromkeys(w for w in words if str(w or "").strip()))
