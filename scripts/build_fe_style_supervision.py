from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence


def _style_source(path: Path | str) -> str:
    return Path(path).stem


def _style_tags(style: Mapping[str, Any]) -> list[str]:
    order = ("tone", "warmth", "stance", "attachment", "arc")
    tags: list[str] = []
    for key in order:
        value = style.get(key)
        if value is not None and value != "":
            tags.append(f"{key}={value}")
    tags.append("continuity=hold_tone")
    return tags


def build_record(
    source_path: Path | str,
    source_line: int,
    style: Mapping[str, Any],
    messages: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build one FE-style supervision row.

    The training script used to live outside the submitted source archive, while
    the tests still depend on this small public contract. Keep the function
    deterministic and schema-only; no IO, no model calls, no style prose magic.
    Humanity may survive another JSONL builder.
    """
    return {
        "source": str(source_path),
        "source_line": source_line,
        "messages": [dict(message) for message in messages],
        "knowledge_context": {
            "style_source": _style_source(source_path),
            "style_tags": _style_tags(style),
        },
    }
