from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _normalize_messages(raw_messages: Any) -> list[dict[str, str]] | None:
    if not isinstance(raw_messages, list):
        return None
    messages: list[dict[str, str]] = []
    for message in raw_messages:
        if not isinstance(message, Mapping):
            return None
        role = message.get("role")
        if not isinstance(role, str) or not role:
            return None
        if "content" not in message:
            return None
        messages.append({"role": role, "content": _stringify(message.get("content"))})
    return messages or None


def _context_lines(row: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    machine_context = row.get("machine_context")
    if isinstance(machine_context, Mapping) and machine_context:
        lines.append("Machine context observed:")
        lines.append(json.dumps(machine_context, ensure_ascii=False, sort_keys=True))

    action_context = row.get("action_context")
    if isinstance(action_context, Mapping) and action_context:
        lines.append("Action execution context:")
        lines.append(json.dumps(action_context, ensure_ascii=False, sort_keys=True))
    return lines


def _messages_with_context(messages: list[dict[str, str]], row: Mapping[str, Any]) -> list[dict[str, str]]:
    context = _context_lines(row)
    if not context:
        return messages
    system_context = {"role": "system", "content": "\n".join(context)}
    if messages and messages[0]["role"] == "system":
        merged = dict(messages[0])
        merged["content"] = f"{merged['content']}\n\n{system_context['content']}"
        return [merged, *messages[1:]]
    return [system_context, *messages]


def build_text_dataset(dataset_path: Path | str, tokenizer: Any) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Load JSONL chat rows and render them through a tokenizer chat template.

    Invalid rows are skipped with a compact report. Context fields accept mixed
    primitive/list/dict shapes and are serialized deterministically so training
    examples do not explode just because someone put a dict where a sentence was
    expected, a shocking act in data engineering apparently.
    """
    path = Path(dataset_path)
    dataset: list[dict[str, str]] = []
    report: dict[str, Any] = {
        "total_rows": 0,
        "loaded_rows": 0,
        "skipped_rows": 0,
        "examples": [],
    }

    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            report["total_rows"] += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                report["skipped_rows"] += 1
                report["examples"].append({"line": line_no, "error": f"json:{exc.msg}"})
                continue
            if not isinstance(row, Mapping):
                report["skipped_rows"] += 1
                report["examples"].append({"line": line_no, "error": "row_not_object"})
                continue
            messages = _normalize_messages(row.get("conversations"))
            if messages is None:
                report["skipped_rows"] += 1
                report["examples"].append({"line": line_no, "error": "invalid_conversations"})
                continue
            rendered_messages = _messages_with_context(messages, row)
            text = tokenizer.apply_chat_template(
                rendered_messages,
                tokenize=False,
                add_generation_prompt=False,
            )
            dataset.append({"text": text})
            report["loaded_rows"] += 1

    return dataset, report
