from __future__ import annotations

"""Registry năng lực public của Eris, kèm availability runtime.

Một nguồn sự thật duy nhất cho câu hỏi "em làm được gì". Registry không chỉ
liệt kê chức năng trên giấy mà còn chụp trạng thái đang bật/tắt, vì khoe một tool
đang chết là kiểu quảng cáo rất người nhưng không cần bắt chước.
"""

from dataclasses import dataclass, replace
import hashlib
import json
import os
from typing import Iterable, Mapping

from actions.contracts import VALID_SYSTEM_ACTION_LIST


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    id: str
    public_name_vi: str
    description_vi: str
    example_phrases: tuple[str, ...] = ()
    risk_level: str = "low"
    runtime_flag: str = ""
    requires_tool: str = ""
    visible_in_ui_group: str = "desktop"
    live_available: bool = True


_OBSERVATIONAL_CAPABILITY_IDS = (
    "observe_active_app",
    "observe_window_title",
    "observe_idle_state",
    "read_uia_text",
    "semantic_screen_vision",
    "camera_view",
    "meet_participants",
    "telemetry_summary",
)


_CAPABILITY_DATA: dict[str, CapabilityDefinition] = {
    "get_local_time": CapabilityDefinition(
        id="get_local_time", public_name_vi="xem thời gian hệ thống",
        description_vi="đọc giờ/ngày hiện tại từ runtime hệ thống",
        example_phrases=("mấy giờ rồi", "hôm nay ngày mấy"),
        visible_in_ui_group="observation",
    ),
    "get_active_application": CapabilityDefinition(
        id="get_active_application", public_name_vi="xem ứng dụng đang active",
        description_vi="đọc app và tiêu đề cửa sổ từ telemetry thật; không tự suy ra nội dung file",
        example_phrases=("app nào đang active", "cửa sổ nào đang focus"),
        visible_in_ui_group="environment",
    ),
    "read_visible_ui_text": CapabilityDefinition(
        id="read_visible_ui_text", public_name_vi="đọc text UI đang hiện",
        description_vi="đọc block UIA/OCR đủ tươi, có confidence và privacy guard",
        example_phrases=("đọc chữ đang hiện", "đọc text trên màn hình"),
        visible_in_ui_group="environment",
    ),
    "inspect_runtime_log": CapabilityDefinition(
        id="inspect_runtime_log", public_name_vi="đọc log runtime",
        description_vi="đọc phần cuối log eris_run mới nhất và che khóa bí mật",
        example_phrases=("đọc log chạy", "xem log runtime"),
        visible_in_ui_group="environment",
    ),
    "read_current_error": CapabilityDefinition(
        id="read_current_error", public_name_vi="đọc lỗi hiện tại",
        description_vi="tìm traceback/error cụ thể gần nhất từ log hoặc text màn hình",
        example_phrases=("lỗi hiện tại là gì", "đọc traceback đang hiện"),
        visible_in_ui_group="environment",
    ),
    "inspect_selected_file": CapabilityDefinition(
        id="inspect_selected_file", public_name_vi="xem file đang được chọn",
        description_vi="xác định file từ bridge/path/title; chỉ đọc nội dung khi có path thật trong project",
        example_phrases=("file nào đang mở", "đọc file đang chọn"),
        visible_in_ui_group="environment",
    ),
    "get_project_status": CapabilityDefinition(
        id="get_project_status", public_name_vi="xem trạng thái project",
        description_vi="đọc Git branch và các mục staged/modified/untracked bằng lệnh read-only",
        example_phrases=("git status", "repo đang bẩn không"),
        visible_in_ui_group="environment",
    ),
    "project_list_files": CapabilityDefinition(
        id="project_list_files", public_name_vi="liệt kê file project",
        description_vi="đọc cây file trong workspace, tự lọc cache và binary",
        example_phrases=("liệt kê file project",), visible_in_ui_group="project",
    ),
    "project_read_file": CapabilityDefinition(
        id="project_read_file", public_name_vi="đọc file project",
        description_vi="đọc nội dung file source trong project kèm hash evidence",
        example_phrases=("đọc file runtime/coordinator.py",), visible_in_ui_group="project",
    ),
    "project_search_text": CapabilityDefinition(
        id="project_search_text", public_name_vi="tìm text trong project",
        description_vi="tìm text hoặc regex trong source project",
        example_phrases=("tìm chuỗi này trong project",), visible_in_ui_group="project",
    ),
    "project_find_symbol": CapabilityDefinition(
        id="project_find_symbol", public_name_vi="tìm symbol",
        description_vi="tìm class, function hoặc symbol theo tên",
        example_phrases=("tìm symbol ActionExecutor",), visible_in_ui_group="project",
    ),
    "project_git_diff": CapabilityDefinition(
        id="project_git_diff", public_name_vi="xem diff project",
        description_vi="đọc git diff hiện tại bằng evidence thật",
        example_phrases=("xem diff project",), visible_in_ui_group="project",
    ),
    "project_apply_patch": CapabilityDefinition(
        id="project_apply_patch", public_name_vi="áp patch project",
        description_vi="snapshot file rồi áp unified diff trong workspace",
        risk_level="high", example_phrases=("áp patch này",), visible_in_ui_group="project",
    ),
    "project_run_tests": CapabilityDefinition(
        id="project_run_tests", public_name_vi="chạy test project",
        description_vi="chạy test và chỉ báo đạt khi exit code bằng 0",
        risk_level="medium", example_phrases=("chạy test",), visible_in_ui_group="project",
    ),
    "project_run_command": CapabilityDefinition(
        id="project_run_command", public_name_vi="chạy lệnh project",
        description_vi="chạy command phát triển trong project root theo command policy",
        risk_level="high", example_phrases=("chạy python -m pytest",), visible_in_ui_group="project",
    ),
    "project_rollback": CapabilityDefinition(
        id="project_rollback", public_name_vi="rollback thay đổi",
        description_vi="khôi phục snapshot operation gần nhất hoặc được chỉ định",
        risk_level="high", example_phrases=("rollback thay đổi vừa rồi",), visible_in_ui_group="project",
    ),
    "project_package_patch": CapabilityDefinition(
        id="project_package_patch", public_name_vi="đóng gói patch ZIP",
        description_vi="đóng gói đúng file đã thay đổi kèm ghi chú tiếng Việt",
        risk_level="medium", example_phrases=("đóng gói patch zip",), visible_in_ui_group="project",
    ),
    "project_execute_task": CapabilityDefinition(
        id="project_execute_task", public_name_vi="tự hoàn thành tác vụ code",
        description_vi="tự inspect, lập patch, sửa, chạy test, rollback nếu lỗi và đóng gói",
        risk_level="high", example_phrases=("sửa project này đi", "làm luôn rồi chạy test"), visible_in_ui_group="project",
    ),
    "workspace_join": CapabilityDefinition(
        id="workspace_join", public_name_vi="gia nhập workspace",
        description_vi="nhận Git URL, path local hoặc ZIP rồi đăng ký dưới ErisLive",
        risk_level="medium", example_phrases=("vào repo này", "gia nhập workspace"), visible_in_ui_group="project",
    ),
    "workspace_switch": CapabilityDefinition(
        id="workspace_switch", public_name_vi="chuyển workspace",
        description_vi="chuyển project đang active sang workspace đã đăng ký",
        example_phrases=("chuyển sang workspace game",), visible_in_ui_group="project",
    ),
    "workspace_list": CapabilityDefinition(
        id="workspace_list", public_name_vi="liệt kê workspace",
        description_vi="xem các repo/project người dùng đã giao cho Eris",
        example_phrases=("liệt kê workspace",), visible_in_ui_group="project",
    ),
    "workspace_leave": CapabilityDefinition(
        id="workspace_leave", public_name_vi="rời workspace",
        description_vi="gỡ workspace khỏi registry, mặc định giữ nguyên dữ liệu",
        risk_level="medium", example_phrases=("rời workspace này",), visible_in_ui_group="project",
    ),
    "launch_app": CapabilityDefinition(
        id="launch_app", public_name_vi="mở ứng dụng",
        description_vi="mở app/chương trình có trong cấu hình runtime",
        example_phrases=("mở Chrome", "mở VS Code"),
        runtime_flag="ERIS_ACTION_LAUNCH_APP_ENABLED",
    ),
    "focus_window": CapabilityDefinition(
        id="focus_window", public_name_vi="focus cửa sổ",
        description_vi="đưa một cửa sổ/app đang mở lên trước",
        example_phrases=("focus Godot", "chuyển sang Chrome"),
        runtime_flag="ERIS_ACTION_FOCUS_WINDOW_ENABLED",
    ),
    "set_volume": CapabilityDefinition(
        id="set_volume", public_name_vi="chỉnh âm lượng",
        description_vi="tăng/giảm/mute âm lượng hệ thống",
        example_phrases=("giảm volume còn 30", "mute đi"),
        runtime_flag="ERIS_ACTION_SET_VOLUME_ENABLED",
    ),
    "play_pause_media": CapabilityDefinition(
        id="play_pause_media", public_name_vi="điều khiển media",
        description_vi="play/pause/next/previous media bằng phím hệ thống",
        example_phrases=("pause nhạc", "next bài"),
        runtime_flag="ERIS_ACTION_MEDIA_ENABLED",
    ),
    "copy_text": CapabilityDefinition(
        id="copy_text", public_name_vi="copy text",
        description_vi="đưa đoạn text vào clipboard",
        example_phrases=("copy đoạn này",),
        runtime_flag="ERIS_ACTION_COPY_TEXT_ENABLED",
    ),
    "open_url": CapabilityDefinition(
        id="open_url", public_name_vi="mở đường dẫn",
        description_vi="mở URL hợp lệ trong trình duyệt",
        example_phrases=("mở link này",),
        risk_level="medium", runtime_flag="ERIS_ACTION_OPEN_URL_ENABLED",
    ),
    "search_web": CapabilityDefinition(
        id="search_web", public_name_vi="tìm web",
        description_vi="tra cứu web khi runtime/tool tương ứng khả dụng",
        example_phrases=("search vụ này", "tìm thời sự"),
        runtime_flag="ERIS_SEARCH_WEB_ENABLED", requires_tool="search_web",
        visible_in_ui_group="knowledge",
    ),
    "get_weather": CapabilityDefinition(
        id="get_weather", public_name_vi="xem thời tiết",
        description_vi="lấy dự báo/thời tiết theo địa điểm nếu có tool",
        example_phrases=("thời tiết Hà Nội",),
        runtime_flag="ERIS_WEATHER_ENABLED", requires_tool="weather",
        visible_in_ui_group="knowledge",
    ),
    "get_now_playing": CapabilityDefinition(
        id="get_now_playing", public_name_vi="xem media đang phát",
        description_vi="đọc nhanh track/app media đang phát nếu hệ điều hành cho phép",
        example_phrases=("đang phát bài gì",),
        runtime_flag="ERIS_NOW_PLAYING_ENABLED",
    ),
    "observe_active_app": CapabilityDefinition(
        id="observe_active_app", public_name_vi="biết ứng dụng đang active",
        description_vi="nhận tên ứng dụng đang được focus từ machine runtime",
        visible_in_ui_group="observation",
    ),
    "observe_window_title": CapabilityDefinition(
        id="observe_window_title", public_name_vi="biết tiêu đề cửa sổ",
        description_vi="nhận tiêu đề cửa sổ active khi hệ điều hành cung cấp",
        visible_in_ui_group="observation",
    ),
    "observe_idle_state": CapabilityDefinition(
        id="observe_idle_state", public_name_vi="biết trạng thái idle/gõ",
        description_vi="nhận thời gian idle và tín hiệu user đang hoạt động/gõ",
        visible_in_ui_group="observation",
    ),
    "read_uia_text": CapabilityDefinition(
        id="read_uia_text", public_name_vi="đọc một phần chữ qua UI Automation",
        description_vi="đọc text control mà Windows UI Automation cho phép; không đồng nghĩa nhìn toàn màn hình",
        visible_in_ui_group="observation",
    ),
    "semantic_screen_vision": CapabilityDefinition(
        id="semantic_screen_vision", public_name_vi="hiểu nội dung ảnh màn hình",
        description_vi="phân tích semantic từ frame màn hình khi vision compressor thực sự khả dụng",
        visible_in_ui_group="observation", live_available=False,
    ),
    "camera_view": CapabilityDefinition(
        id="camera_view", public_name_vi="nhìn camera",
        description_vi="nhìn video/khuôn mặt từ camera",
        visible_in_ui_group="observation", live_available=False,
    ),
    "meet_participants": CapabilityDefinition(
        id="meet_participants", public_name_vi="nhìn người trong Meet",
        description_vi="nhận diện người/khuôn mặt trong cuộc gọi Meet",
        visible_in_ui_group="observation", live_available=False,
    ),
    "telemetry_summary": CapabilityDefinition(
        id="telemetry_summary", public_name_vi="đọc telemetry runtime",
        description_vi="đọc snapshot như active app, idle, scene và health nội bộ đã được runtime cấp",
        visible_in_ui_group="observation",
    ),
    "review_discourse_claim": CapabilityDefinition(
        id="review_discourse_claim", public_name_vi="kiểm lại claim hội thoại",
        description_vi="đọc claim public đang bị sửa và nêu đúng phần Eris đã hiểu lệch",
        example_phrases=("kiểm lại chỗ vừa hiểu sai", "rà claim vừa rồi"),
        visible_in_ui_group="cognition",
    ),
    "inspect_unresolved_questions": CapabilityDefinition(
        id="inspect_unresolved_questions", public_name_vi="xem câu hỏi còn bỏ ngỏ",
        description_vi="kiểm tra discourse focus để tìm câu hỏi hoặc correction chưa được đóng",
        example_phrases=("còn câu nào chưa trả lời",),
        visible_in_ui_group="cognition",
    ),
    "inspect_memory_candidates": CapabilityDefinition(
        id="inspect_memory_candidates", public_name_vi="kiểm tra memory candidate",
        description_vi="đếm mảnh ký ức chưa consolidation mà không coi chúng là fact",
        example_phrases=("kiểm tra mảnh ký ức còn sót",),
        visible_in_ui_group="cognition",
    ),
    "compare_recent_turns": CapabilityDefinition(
        id="compare_recent_turns", public_name_vi="so sánh lượt nói gần đây",
        description_vi="đối chiếu hai câu public gần nhất để phát hiện lặp ý",
        example_phrases=("so sánh hai câu vừa nói",),
        visible_in_ui_group="cognition",
    ),
    "inspect_social_state": CapabilityDefinition(
        id="inspect_social_state", public_name_vi="xem social state của Eris",
        description_vi="đọc warmth, irritation, play-contract và mức cáu của chính Eris",
        example_phrases=("xem trạng thái xã hội của em",),
        visible_in_ui_group="cognition",
    ),
    "detect_internal_contradictions": CapabilityDefinition(
        id="detect_internal_contradictions", public_name_vi="tìm mâu thuẫn trong lời Eris",
        description_vi="đối chiếu claim public gần đây để phát hiện cặp phủ định mâu thuẫn",
        example_phrases=("kiểm tra em có tự mâu thuẫn không",),
        visible_in_ui_group="cognition",
    ),
    "summarize_open_loops": CapabilityDefinition(
        id="summarize_open_loops", public_name_vi="tổng kết open loop nhận thức",
        description_vi="gom claim bị sửa, câu hỏi bỏ ngỏ và memory candidate chưa xử lý",
        example_phrases=("còn gì dang dở", "tổng kết open loop"),
        visible_in_ui_group="cognition",
    ),
    "inspect_capability_health": CapabilityDefinition(
        id="inspect_capability_health", public_name_vi="kiểm tra capability health",
        description_vi="đọc snapshot năng lực nào đang available hoặc unavailable",
        example_phrases=("năng lực nào đang chết",),
        visible_in_ui_group="cognition",
    ),
}


_ACTION_ALIASES: dict[str, str] = {
    "adjust_volume": "set_volume",
    "change_volume": "set_volume",
    "volume": "set_volume",
    "volume_up": "set_volume",
    "volume_down": "set_volume",
    "get_time": "get_local_time",
    "show_time": "get_local_time",
    "current_time": "get_local_time",
    "time_now": "get_local_time",
}


def canonicalize_action_id(action_id: str) -> str:
    """Map alias về schema chuẩn trước parser/executor.

    Action lạ được trả nguyên dạng để validation reject rõ, không âm thầm đoán.
    """
    clean = str(action_id or "").strip().lower()
    return _ACTION_ALIASES.get(clean, clean)


def singing_capability_enabled() -> bool:
    """Singing/SVS là capability riêng, mặc định tắt; TTS không giả làm máy hát."""
    try:
        from runtime.rollout_control import feature_enabled
        return feature_enabled("singing_capability")
    except Exception:
        return os.environ.get("ERIS_SINGING_CAPABILITY", "0").strip().lower() in {"1", "true", "yes", "on"}


def iter_public_capabilities(
    action_ids: Iterable[str] | None = None,
    *,
    runtime_flags: Mapping[str, bool] | None = None,
    include_unavailable: bool = True,
) -> tuple[CapabilityDefinition, ...]:
    ids = tuple(action_ids or VALID_SYSTEM_ACTION_LIST)
    if action_ids is None:
        # Giữ các năng lực quan sát ở phần đầu snapshot như bản cũ. Cognitive
        # capabilities được xếp sau để max_items nhỏ không vô tình đẩy camera/
        # Meet ra khỏi prompt và làm Eris quên luôn giới hạn cảm biến của mình.
        cognitive = tuple(
            item for item in ids
            if (_CAPABILITY_DATA.get(str(item)) is not None
                and _CAPABILITY_DATA[str(item)].visible_in_ui_group == "cognition")
        )
        environment = tuple(
            item for item in ids
            if (_CAPABILITY_DATA.get(str(item)) is not None
                and _CAPABILITY_DATA[str(item)].visible_in_ui_group == "environment")
        )
        project = tuple(
            item for item in ids
            if (_CAPABILITY_DATA.get(str(item)) is not None
                and _CAPABILITY_DATA[str(item)].visible_in_ui_group == "project")
        )
        project_primary = tuple(item for item in project if item == "project_execute_task")
        project_secondary = tuple(item for item in project if item != "project_execute_task")
        deferred = set((*cognitive, *environment, *project))
        regular = tuple(item for item in ids if item not in deferred)
        # Giữ toàn bộ giới hạn cảm biến (camera/Meet/UIA) trong snapshot nhỏ,
        # rồi mới xếp environment/cognition. Một capability mới không được đẩy
        # mất lời thú nhận "tôi không nhìn được Meet" khỏi prompt.
        ids = (*project_primary, *regular, *_OBSERVATIONAL_CAPABILITY_IDS, *project_secondary, *environment, *cognitive)
    else:
        ids = (*ids, *_OBSERVATIONAL_CAPABILITY_IDS)
    ids = tuple(dict.fromkeys(ids))
    out: list[CapabilityDefinition] = []
    for action_id in ids:
        cap = _CAPABILITY_DATA.get(str(action_id))
        if cap is None:
            continue
        resolved = replace(cap, live_available=_resolve_available(cap, runtime_flags=runtime_flags))
        if include_unavailable or resolved.live_available:
            out.append(resolved)
    return tuple(out)


def render_capability_registry_prompt(
    action_ids: Iterable[str] | None = None,
    *,
    max_items: int = 8,
    runtime_flags: Mapping[str, bool] | None = None,
) -> str:
    caps = iter_public_capabilities(action_ids, runtime_flags=runtime_flags)[: max(1, int(max_items))]
    lines = [
        "CAPABILITY_REGISTRY: answer capability questions only from this runtime snapshot.",
        f"- snapshot_id={capability_snapshot_id(action_ids, runtime_flags=runtime_flags)}",
    ]
    for cap in caps:
        examples = "; ".join(cap.example_phrases[:2])
        extra = f" Example: {examples}." if examples else ""
        status = "available" if cap.live_available else "unavailable_now"
        reason = _runtime_reason(cap.id) if runtime_flags is None else ""
        reason_part = f"; reason={reason}" if reason else ""
        tool = f"; tool={cap.requires_tool}" if cap.requires_tool else ""
        lines.append(
            f"- {cap.id}: {cap.public_name_vi} — {cap.description_vi}; status={status}{reason_part}; "
            f"risk={cap.risk_level}{tool}.{extra}"
        )
    lines.append(
        "State unavailable capabilities honestly. Do not claim a tool is live when status=unavailable_now. "
        "Do not add medical/legal disclaimers for a capability question unless the user asks for that domain."
    )
    return "\n".join(lines)


def capability_surface_keywords(action_ids: Iterable[str] | None = None) -> tuple[str, ...]:
    words: list[str] = []
    for cap in iter_public_capabilities(action_ids):
        words.extend((cap.id.replace("_", " "), cap.public_name_vi, cap.description_vi))
        words.extend(cap.example_phrases)
    words.extend((
        "ứng dụng", "cửa sổ", "âm lượng", "volume", "media", "clipboard", "web", "thời tiết",
        "thời gian", "giờ", "telemetry", "runtime", "idle", "UI Automation", "OCR", "màn hình", "Meet", "camera",
        "claim", "câu hỏi bỏ ngỏ", "memory candidate", "social state", "mâu thuẫn", "open loop",
        "project", "source", "symbol", "diff", "patch", "test", "rollback", "đóng gói zip",
        "workspace", "gia nhập repo", "chuyển workspace", "ErisLive",
    ))
    return tuple(dict.fromkeys(w for w in words if str(w or "").strip()))


def capability_snapshot_id(
    action_ids: Iterable[str] | None = None,
    *,
    runtime_flags: Mapping[str, bool] | None = None,
) -> str:
    payload = [
        {
            "id": cap.id,
            "available": cap.live_available,
            "risk": cap.risk_level,
            "tool": cap.requires_tool,
            "reason": _runtime_reason(cap.id) if runtime_flags is None else "",
        }
        for cap in iter_public_capabilities(action_ids, runtime_flags=runtime_flags)
    ]
    if runtime_flags is None:
        try:
            from actions.capability_runtime import capability_runtime_revision

            payload.append({"runtime_revision": capability_runtime_revision()})
        except Exception:
            pass
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def live_capability_ids(
    action_ids: Iterable[str] | None = None,
    *,
    runtime_flags: Mapping[str, bool] | None = None,
) -> tuple[str, ...]:
    return tuple(
        cap.id for cap in iter_public_capabilities(
            action_ids, runtime_flags=runtime_flags, include_unavailable=False
        )
    )


def capability_definition(capability_id: str) -> CapabilityDefinition | None:
    return _CAPABILITY_DATA.get(str(capability_id or "").strip())


def _resolved_runtime_flags(runtime_flags: Mapping[str, bool] | None) -> Mapping[str, bool] | None:
    if runtime_flags is not None:
        return runtime_flags
    try:
        from actions.capability_runtime import runtime_capability_flags

        flags = runtime_capability_flags()
        return flags or None
    except Exception:
        return None


def _runtime_reason(capability_id: str) -> str:
    try:
        from actions.capability_runtime import capability_runtime_reason

        return capability_runtime_reason(capability_id)
    except Exception:
        return ""


def _resolve_available(cap: CapabilityDefinition, *, runtime_flags: Mapping[str, bool] | None) -> bool:
    flags = _resolved_runtime_flags(runtime_flags)
    if flags is not None:
        if cap.id in flags:
            return bool(flags[cap.id])
        if cap.runtime_flag and cap.runtime_flag in flags:
            return bool(flags[cap.runtime_flag])
    if not cap.runtime_flag:
        return bool(cap.live_available)
    raw = os.getenv(cap.runtime_flag)
    if raw is None or str(raw).strip() == "":
        return bool(cap.live_available)
    return str(raw).strip().lower() not in {"0", "false", "off", "no"}


__all__ = [
    "CapabilityDefinition",
    "iter_public_capabilities",
    "render_capability_registry_prompt",
    "capability_surface_keywords",
    "capability_snapshot_id",
    "live_capability_ids",
    "capability_definition",
    "canonicalize_action_id",
    "singing_capability_enabled",
    "_OBSERVATIONAL_CAPABILITY_IDS",
]
