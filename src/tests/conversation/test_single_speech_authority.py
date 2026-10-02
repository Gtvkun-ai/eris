# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from pathlib import Path


RUNTIME_ROOT = Path(__file__).resolve().parents[2] / "runtime"
LEGACY_WRITER_METHODS = {
    "generate_public_reply",
    "generate_autonomous_reply",
    "realize_surface_speech",
}
TEMPORARY_WRITER_MIGRATION_ALLOWLIST = {
    "ai_orchestrated/orchestrator.py",
    "ai_orchestrated/self_turn_pipeline.py",
}


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


def _legacy_writer_calls(source: str) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    return [
        (node.lineno, node.func.attr)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in LEGACY_WRITER_METHODS
    ]


def test_architecture_scanner_rejects_external_writer_call():
    source = "def bypass(writer):\n    return writer.realize(turn=None)\n"

    assert _writer_port_calls(source) == [2]


def test_architecture_scanner_rejects_legacy_writer_entry():
    source = "def bypass(router):\n    return router.generate_public_reply(user_text='x')\n"

    assert _legacy_writer_calls(source) == [(2, "generate_public_reply")]


def test_only_conversation_kernel_calls_writer_port():
    offenders: list[str] = []
    for path in RUNTIME_ROOT.rglob("*.py"):
        calls = _writer_port_calls(path.read_text(encoding="utf-8"))
        if calls and path.as_posix().split("/runtime/", 1)[-1] != "conversation/kernel.py":
            offenders.extend(f"{path.name}:{line}" for line in calls)

    assert offenders == []


def test_legacy_writer_calls_are_confined_to_adapter_or_named_migration_sites():
    offenders: list[str] = []
    observed_migration_sites: set[str] = set()
    for path in RUNTIME_ROOT.rglob("*.py"):
        calls = _legacy_writer_calls(path.read_text(encoding="utf-8"))
        if not calls:
            continue
        relative = path.relative_to(RUNTIME_ROOT).as_posix()
        if relative == "conversation/runtime_writer.py":
            continue
        if relative in TEMPORARY_WRITER_MIGRATION_ALLOWLIST:
            observed_migration_sites.add(relative)
            continue
        offenders.extend(f"{relative}:{line}:{method}" for line, method in calls)

    assert offenders == []
    assert observed_migration_sites == TEMPORARY_WRITER_MIGRATION_ALLOWLIST
