# -*- coding: utf-8 -*-
"""Format kết quả action theo bằng chứng thực thi, không theo sự tự tin của câu."""

from __future__ import annotations

from actions.contracts import ActionExecutionResult, ActionExecutionStatus


def public_action_text(result: ActionExecutionResult) -> str:
    if not result.success or result.status == ActionExecutionStatus.FAILED:
        return result.message or "Action chưa thực thi được."

    action = result.action_name
    # Side-effect chỉ được dùng wording khẳng định khi observer đã xác nhận.
    # Hiện set_volume/open_url chủ yếu mới có dispatch evidence, nên nhánh này
    # dành cho implementation observer hiện tại hoặc adapter cắm thêm sau này.
    if result.observed:
        return result.message or f"Action {action} đã được xác nhận hoàn tất."

    if action == "get_local_time":
        return result.message
    if action == "get_now_playing":
        title = result.data.get("title", "")
        artist = result.data.get("artist", "")
        if title and artist:
            return f"Tôi thấy bài đang phát là {title} của {artist}."
        if title:
            return f"Tôi thấy bài đang phát là {title}."
        return result.message
    if action == "search_web":
        return (result.data.get("answer", "") or result.message or "").strip()
    if action == "get_weather":
        return result.message

    # Nhóm side-effect chỉ có dispatch evidence. Không được nâng thành "đã xong".
    if action == "set_volume":
        level = result.data.get("level", result.action_input or "mức yêu cầu")
        return f"Tôi đã gửi yêu cầu chỉnh âm lượng về khoảng {level} phần trăm."
    if action == "open_url":
        return f"Tôi đã gửi yêu cầu mở {result.data.get('url', result.action_input)}."
    if action == "focus_window":
        target = result.data.get("matched_title", result.action_input)
        return f"Tôi đã gửi yêu cầu đưa cửa sổ {target} lên trước."
    if action == "play_pause_media":
        return "Tôi đã gửi phím điều khiển media."
    if action == "copy_text":
        return "Tôi đã gửi yêu cầu ghi nội dung vào clipboard."
    if action == "launch_app":
        target = result.data.get("command", result.action_input)
        return f"Tôi đã gửi yêu cầu mở {target}."
    return result.message or "Tôi đã gửi yêu cầu thực thi action."


__all__ = ["public_action_text"]
