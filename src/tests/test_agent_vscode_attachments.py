from __future__ import annotations

import base64
from pathlib import Path

from runtime.agent_harness.gemini_cli_executor import GeminiCliDecisionExecutor


def test_image_attachment_becomes_openai_compatible_image_url(tmp_path: Path) -> None:
    # Chỉ test contract payload, không cần ảnh PNG hợp lệ hay gọi model thật.
    image = tmp_path / "screen.png"
    image.write_bytes(b"eris-image")

    parts = GeminiCliDecisionExecutor._image_content_parts({
        "attachments": [{
            "kind": "image",
            "path": str(image),
            "mime": "image/png",
            "name": "screen.png",
        }]
    })

    assert len(parts) == 1
    assert parts[0]["type"] == "image_url"
    url = parts[0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == b"eris-image"


def test_non_image_attachment_is_not_uploaded_to_vision_lane(tmp_path: Path) -> None:
    source = tmp_path / "main.py"
    source.write_text("print('eris')", encoding="utf-8")

    parts = GeminiCliDecisionExecutor._image_content_parts({
        "attachments": [{
            "kind": "file",
            "path": str(source),
            "mime": "text/plain",
        }]
    })

    assert parts == []
