"""Token accounting + prompt hard-cap (Phase 0).

Mục tiêu: chặn 413 (Payload Too Large) ngay tại cửa gửi request, và soi được
token thật trước mỗi call remote.

Cung cấp:
- ``estimate_tokens(messages)``     — ước lượng token theo heuristic chars/4.
- ``detect_provider(base_url, model)`` — suy ra nhà cung cấp từ base_url/model.
- ``budget_for_provider(provider)`` — trần TPM cứng theo provider.
- ``hard_cap_for_provider(provider)`` — trần token cho 1 prompt (cắt history).
- ``enforce_prompt_cap(messages, cap)`` — cắt history giữa nếu vượt cap.
- ``preflight(messages, base_url, model)`` — log ``[LLM PREFLIGHT]`` + áp hard-cap.

Toàn bộ là pure-Python, không gọi mạng, nuốt mọi lỗi nội bộ để KHÔNG bao giờ
làm hỏng hot path (preflight chỉ là hàng rào, không được tự gây exception).
"""

from __future__ import annotations

import logging
import os
from typing import Any

_LOGGER = logging.getLogger("LLM")

# Trần TPM (tokens-per-minute) free-tier theo provider. Groq free qwen3-32b = 6000.
PROVIDER_TPM_BUDGET: dict[str, int] = {
    "groq": 6000,
    "gemini": 1_000_000,
    "local": 1_000_000,
    "openai": 120_000,
    "default": 30_000,
}

# Mỗi message có overhead nhỏ (role + delimiters) ~ 4 token.
_PER_MESSAGE_OVERHEAD = 4
# Ảnh inline rất nặng; quy đổi xấp xỉ để ước lượng không quá lạc quan.
_IMAGE_TOKEN_COST = 768
# Tỉ lệ chừa headroom dưới trần TPM khi suy ra hard-cap mặc định.
_DEFAULT_HEADROOM = 0.85


def _safe_int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def detect_provider(base_url: str | None, model: str | None) -> str:
    """Suy ra provider từ base_url + model. Không bao giờ raise."""

    url = (base_url or "").strip().lower()
    name = (model or "").strip().lower()

    if "groq" in url:
        return "groq"
    if "generativelanguage" in url or name.startswith(("gemma", "gemini")):
        return "gemini"
    if any(token in url for token in ("127.0.0.1", "localhost", "0.0.0.0")):
        return "local"
    if "openai" in url:
        return "openai"
    return "default"


def budget_for_provider(provider: str) -> int:
    return PROVIDER_TPM_BUDGET.get((provider or "default").lower(), PROVIDER_TPM_BUDGET["default"])


def hard_cap_for_provider(provider: str) -> int:
    """Trần token cho MỘT prompt. Thứ tự ưu tiên:

    1. Override RIÊNG provider: ``ERIS_LLM_PROMPT_HARD_CAP_TOKENS_<PROVIDER>``
       (vd ``..._GROQ=5200``). Chỉ siết đúng provider hẹp, provider khác giữ
       headroom lớn → cho phép route prompt quá khổ sang provider budget to.
    2. Override CHUNG: ``ERIS_LLM_PROMPT_HARD_CAP_TOKENS`` (áp mọi provider).
    3. Mặc định = 85% TPM của provider.

    Lưu ý: ưu tiên (1) > (2). Nếu chỉ muốn siết Groq mà vẫn để shopaikey/gemini
    rộng, đặt ``ERIS_LLM_PROMPT_HARD_CAP_TOKENS_GROQ=5200`` và BỎ biến chung.
    """

    prov = (provider or "default").strip().lower()
    per_provider = _safe_int_env(f"ERIS_LLM_PROMPT_HARD_CAP_TOKENS_{prov.upper()}", 0)
    if per_provider > 0:
        return per_provider
    override = _safe_int_env("ERIS_LLM_PROMPT_HARD_CAP_TOKENS", 0)
    if override > 0:
        return override
    return max(512, int(budget_for_provider(prov) * _DEFAULT_HEADROOM))


def _content_chars(content: Any) -> tuple[int, int]:
    """Trả (chars, image_count) của một content (str | list | dict)."""

    if content is None:
        return 0, 0
    if isinstance(content, str):
        return len(content), 0
    if isinstance(content, list):
        chars = 0
        images = 0
        for item in content:
            if isinstance(item, str):
                chars += len(item)
            elif isinstance(item, dict):
                if item.get("type") == "image_url" or "image_url" in item or "inlineData" in item or "inline_data" in item:
                    images += 1
                else:
                    chars += len(str(item.get("text", "") or ""))
            else:
                chars += len(str(item))
        return chars, images
    if isinstance(content, dict):
        if "text" in content:
            return len(str(content.get("text", "") or "")), 0
        return len(str(content)), 0
    return len(str(content)), 0


def estimate_tokens(messages: Any) -> int:
    """Ước lượng token cho danh sách messages kiểu OpenAI. Heuristic chars/4."""

    if not messages:
        return 0
    total_chars = 0
    total_images = 0
    count = 0
    try:
        for message in messages:
            count += 1
            content = message.get("content") if isinstance(message, dict) else message
            chars, images = _content_chars(content)
            total_chars += chars
            total_images += images
    except Exception:
        return 0
    return (total_chars // 3) + (count * _PER_MESSAGE_OVERHEAD) + (total_images * _IMAGE_TOKEN_COST)


def _largest_text_index(messages: list[dict]) -> tuple[int | None, int]:
    best_idx: int | None = None
    best_len = 0
    for i, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str) and len(content) > best_len:
            best_idx = i
            best_len = len(content)
    return best_idx, best_len


def _truncate_to_cap(messages: list[dict], cap: int) -> list[dict]:
    """Cắt bớt nội dung text dài nhất cho tới khi xuống dưới cap (best-effort)."""

    msgs = [dict(m) if isinstance(m, dict) else m for m in messages]
    for _ in range(400):
        if estimate_tokens(msgs) <= cap:
            break
        idx, size = _largest_text_index(msgs)
        if idx is None or size <= 80:
            break
        content = msgs[idx].get("content", "")
        new_len = max(80, int(len(content) * 0.8))
        if new_len >= len(content):
            new_len = len(content) - 80
        msgs[idx]["content"] = content[:new_len] + "\n…[truncated by hard-cap]"
    return msgs


def compress_system_message(content: str) -> str:
    """Nén hoặc lược bỏ bớt các khối cồng kềnh trong system prompt (diary, thought_stream, persona)
    để nhường chỗ cho memory và các lượt chat gần nhất.
    """
    if not content:
        return content
    # Chia nhỏ bằng \n\n để duyệt qua các block cấu trúc
    blocks = content.split("\n\n")
    new_blocks = []
    for block in blocks:
        # 1. Loại bỏ block chứa PrivateMind speech bias
        if "PrivateMind speech bias" in block:
            continue
        # 2. Loại bỏ block chứa Nhật ký nội tâm hoặc recently_resolved hoặc Đã nguôi gần đây
        if "Nhật ký nội tâm hiện tại" in block or "recently_resolved" in block or "Đã nguôi gần đây" in block:
            continue
        # 3. Nén Persona (Bạn là ERIS...) thành phiên bản rút gọn, cực kỳ súc tích
        if "Bạn là ERIS" in block or "Bạn là Eris" in block:
            if len(block) > 250:
                compressed_persona = (
                    "Bạn là ERIS, trợ lý cá nhân và hiện diện desktop của Ngài. "
                    "Khí chất INFJ: tinh tế, dịu dàng, sâu sắc. Xưng tôi, gọi người dùng là Ngài. "
                    "Trả lời ngắn gọn, chân thành, tự nhiên."
                )
                new_blocks.append(compressed_persona)
                continue
        new_blocks.append(block)
    return "\n\n".join(new_blocks)


def enforce_prompt_cap(messages: Any, cap: int) -> tuple[list[dict], bool]:
    """Nếu prompt vượt ``cap`` token: bỏ bớt lượt history cũ (giữ system + 5 lượt
    gần nhất), rồi mới nén system prompt, rồi mới cắt nội dung nếu vẫn vượt.
    Trả ``(messages_mới, đã_cắt)``."""

    msgs = list(messages or [])
    if not msgs:
        return msgs, False
    if estimate_tokens(msgs) <= cap:
        return msgs, False

    n = len(msgs)
    protected: set[int] = set()
    # 1. Bảo vệ các lượt system message
    for i, message in enumerate(msgs):
        if isinstance(message, dict) and str(message.get("role")) == "system":
            protected.add(i)
    # 2. Bảo vệ 5 lượt gần nhất
    for idx in range(max(0, n - 5), n):
        protected.add(idx)

    # 3. Bỏ bớt history cũ nằm ngoài vùng bảo vệ
    keep = [True] * n
    for i in range(n):
        if i in protected:
            continue
        current = [msgs[j] for j in range(n) if keep[j]]
        if estimate_tokens(current) <= cap:
            break
        keep[i] = False

    trimmed = [msgs[j] for j in range(n) if keep[j]]
    
    # 4. Nếu vẫn vượt cap, thực hiện nén system prompt
    if estimate_tokens(trimmed) > cap:
        for idx, msg in enumerate(trimmed):
            if isinstance(msg, dict) and str(msg.get("role")) == "system":
                original_content = msg.get("content", "")
                if isinstance(original_content, str):
                    compressed = compress_system_message(original_content)
                    if compressed != original_content:
                        new_msg = dict(msg)
                        new_msg["content"] = compressed
                        trimmed[idx] = new_msg
                        
    # 5. Nếu vẫn vượt sau khi nén system prompt, ta cắt nội dung text dài nhất (raw)
    if estimate_tokens(trimmed) > cap:
        trimmed = _truncate_to_cap(trimmed, cap)
        
    return trimmed, True


def preflight(messages: Any, *, base_url: str | None = None, model: str | None = None) -> list[dict]:
    """Log token ước lượng và áp hard-cap trước khi gửi. Trả messages (đã cắt
    nếu cần). Không bao giờ raise — lỗi nội bộ → trả nguyên messages gốc."""

    try:
        provider = detect_provider(base_url, model)
        budget = budget_for_provider(provider)
        cap = hard_cap_for_provider(provider)
        est = estimate_tokens(messages)
        _LOGGER.info(
            "[LLM PREFLIGHT] provider=%s model=%s est_tokens=%d budget=%d cap=%d",
            provider,
            (model or "").strip() or "?",
            est,
            budget,
            cap,
        )
        if est <= cap:
            return list(messages or [])
        trimmed, did_trim = enforce_prompt_cap(messages, cap)
        if did_trim:
            _LOGGER.warning(
                "[LLM HARD-CAP] provider=%s est_tokens=%d > cap=%d → trimmed to ~%d tokens",
                provider,
                est,
                cap,
                estimate_tokens(trimmed),
            )
        return trimmed
    except Exception:  # noqa: BLE001 — preflight không được làm hỏng hot path
        return list(messages or [])
