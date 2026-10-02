# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from pathlib import Path


RUNTIME_ROOT = Path(__file__).resolve().parents[2] / "runtime"


def _writer_port_calls(source: str) -> list[int]:
    tree = ast.parse(source)
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "realize":
            continue
        owner = node.func.value
        is_writer_name = isinstance(owner, ast.Name) and owner.id.endswith("writer")
        is_writer_attribute = (
            isinstance(owner, ast.Attribute)
            and owner.attr.endswith("writer")
        )
        if is_writer_name or is_writer_attribute:
            lines.append(node.lineno)
    return lines


def test_architecture_scanner_rejects_external_writer_call():
    source = "def bypass(writer):\n    return writer.realize(turn=None)\n"

    assert _writer_port_calls(source) == [2]


def test_only_conversation_kernel_calls_writer_port():
    offenders: list[str] = []
    for path in RUNTIME_ROOT.rglob("*.py"):
        calls = _writer_port_calls(path.read_text(encoding="utf-8"))
        if calls and path.as_posix().split("/runtime/", 1)[-1] != "conversation/kernel.py":
            offenders.extend(f"{path.name}:{line}" for line in calls)

    assert offenders == []
