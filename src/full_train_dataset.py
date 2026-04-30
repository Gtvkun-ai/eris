from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from datasets import Dataset

MACHINE_CONTEXT_INTRO = (
    "Machine context observed from the users device. "
    "Use it as soft situational awareness, not as an order."
)
KNOWLEDGE_CONTEXT_INTRO = (
    "External knowledge curated for this training example. "
    "Use it as support, not as license to invent facts outside the provided evidence."
)
ACTION_CONTEXT_INTRO = (
    "Action execution context from the runtime. "
    "Only claim what this result confirms."
)
DATASET_DECODE_ENCODINGS = ("utf-8", "utf-8-sig", "cp1258", "cp1252", "latin-1")


def find_dataset_path(candidates: Iterable[Path | str] | None = None) -> Path:
    candidates = candidates or (Path("dataset.jsonl"), Path("src/dataset.jsonl"))
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return path
    raise FileNotFoundError(
        "Khong tim thay dataset.jsonl o cwd hien tai hoac trong thu muc src."
    )


def _normalize_context(context: Any) -> dict[str, Any] | None:
    if context is None:
        return None
    if isinstance(context, dict):
        return context or None
    return {"value": context}


def _render_context_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, list):
        rendered_items = []
        for item in value:
            if isinstance(item, (dict, list)):
                rendered_items.append(
                    json.dumps(item, ensure_ascii=False, sort_keys=True)
                )
            else:
                rendered_items.append(str(item))
        return ", ".join(rendered_items)
    return str(value)


def context_to_system_message(
    context: Any,
    intro_line: str,
) -> dict[str, str] | None:
    context_dict = _normalize_context(context)
    if not context_dict:
        return None

    lines = [intro_line]
    for key, value in context_dict.items():
        lines.append(f"- {key}: {_render_context_value(value)}")
    return {"role": "system", "content": "\n".join(lines)}


def machine_context_to_system_message(
    machine_context: Any,
) -> dict[str, str] | None:
    return context_to_system_message(machine_context, MACHINE_CONTEXT_INTRO)


def knowledge_context_to_system_message(
    knowledge_context: Any,
) -> dict[str, str] | None:
    return context_to_system_message(knowledge_context, KNOWLEDGE_CONTEXT_INTRO)


def action_context_to_system_message(
    action_context: Any,
) -> dict[str, str] | None:
    return context_to_system_message(action_context, ACTION_CONTEXT_INTRO)


def normalize_conversations(conversations: Any) -> list[dict[str, str]]:
    if not isinstance(conversations, list) or not conversations:
        raise ValueError("conversations phai la mot list khong rong")

    normalized: list[dict[str, str]] = []
    for index, message in enumerate(conversations):
        if not isinstance(message, dict):
            raise ValueError(f"conversations[{index}] khong phai object")

        role = message.get("role")
        content = message.get("content")
        if role is None or content is None:
            raise ValueError(
                f"conversations[{index}] thieu role hoac content"
            )

        if not isinstance(role, str):
            role = str(role)
        if not isinstance(content, str):
            if isinstance(content, (dict, list)):
                content = json.dumps(content, ensure_ascii=False, sort_keys=True)
            else:
                content = str(content)

        normalized.append({"role": role, "content": content})

    return normalized


def build_messages(
    conversations: Any,
    machine_context: Any = None,
    action_context: Any = None,
    knowledge_context: Any = None,
) -> list[dict[str, str]]:
    merged = list(normalize_conversations(conversations))
    context_messages = [
        message
        for message in (
            machine_context_to_system_message(machine_context),
            knowledge_context_to_system_message(knowledge_context),
            action_context_to_system_message(action_context),
        )
        if message is not None
    ]
    if context_messages:
        insert_at = 1 if merged and merged[0].get("role") == "system" else 0
        merged = merged[:insert_at] + context_messages + merged[insert_at:]
    return merged


def _decode_jsonl_line(raw_line: bytes) -> tuple[str, str]:
    for encoding in DATASET_DECODE_ENCODINGS:
        try:
            return raw_line.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError(
        "utf-8",
        raw_line,
        0,
        min(1, len(raw_line)),
        "Khong giai ma duoc dong du lieu bang cac encoding da thu",
    )


def build_text_dataset(
    dataset_path: Path | str,
    tokenizer: Any,
    *,
    max_error_examples: int = 5,
) -> tuple[Dataset, dict[str, Any]]:
    dataset_path = Path(dataset_path)
    texts: list[str] = []
    error_examples: list[dict[str, Any]] = []
    encoding_counts: dict[str, int] = {}
    total_rows = 0
    skipped_rows = 0

    with dataset_path.open("rb") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            stripped_line = raw_line.strip()
            if not stripped_line:
                continue

            total_rows += 1
            try:
                line, used_encoding = _decode_jsonl_line(stripped_line)
                sample = json.loads(line)
                merged_messages = build_messages(
                    sample.get("conversations"),
                    machine_context=sample.get("machine_context"),
                    action_context=sample.get("action_context"),
                    knowledge_context=sample.get("knowledge_context"),
                )
                text = tokenizer.apply_chat_template(
                    merged_messages,
                    tokenize=False,
                    add_generation_prompt=False,
                )
                encoding_counts[used_encoding] = (
                    encoding_counts.get(used_encoding, 0) + 1
                )
            except Exception as exc:
                skipped_rows += 1
                if len(error_examples) < max_error_examples:
                    error_examples.append(
                        {
                            "line": line_number,
                            "reason": str(exc),
                            "preview": stripped_line[:200].decode(
                                "latin-1", errors="replace"
                            ),
                        }
                    )
                continue

            texts.append(text)

    if not texts:
        raise ValueError(
            "Khong tao duoc dong train nao. Hay kiem tra lai dataset.jsonl."
        )

    report = {
        "dataset_path": str(dataset_path),
        "total_rows": total_rows,
        "loaded_rows": len(texts),
        "skipped_rows": skipped_rows,
        "encoding_counts": encoding_counts,
        "examples": error_examples,
    }
    return Dataset.from_dict({"text": texts}), report
