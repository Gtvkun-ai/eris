# -*- coding: utf-8 -*-
"""Static audit for remote inference calls that bypass InferenceBroker.

PDF annotation, pages 6 and 20
------------------------------
The broker can only be a control plane if every remote inference path uses it.
This audit scans Python ASTs for common HTTP/SDK generation calls and verifies
that an enclosing function routes execution through ``GLOBAL_INFERENCE_BROKER``.
It is conservative: findings require human review, but a clean result is useful
as a CI guard against a future helper quietly opening another quota side door.
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


REMOTE_CALL_SUFFIXES = {
    "requests.post",
    "httpx.post",
    "urlopen",
    "generate_content",
    "generate_content_stream",
    "chat.completions.create",
    "responses.create",
}
BROKER_MARKERS = (
    "GLOBAL_INFERENCE_BROKER.run(",
    "GLOBAL_INFERENCE_BROKER.run_async(",
    ".run(broker_request,",
    ".run(request,",
    ".run_async(broker_request,",
    ".run_async(request,",
)
ALLOWED_NON_INFERENCE_CALLS = {
    ("runtime/elevenlabs_pool_db.py", "sync_subscription"),
    ("runtime/speech_localizer.py", "_translate_with_deepseek_api"),
    ("tools/elevenlabs_v3_m1/elevenlabs_tts_v3.py", "refresh_firebase_token"),
    ("tools/elevenlabs_v3_m1/elevenlabs_tts_v3.py", "generate_tts_v3"),
    ("vision.py", "_start_ds2api_daemons"),
}


@dataclass(slots=True)
class Finding:
    path: str
    line: int
    call: str
    enclosing_functions: list[str]
    reason: str


def _call_name(node: ast.Call) -> str:
    parts: list[str] = []
    current: Any = node.func
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def _is_remote_call(name: str) -> bool:
    return any(name == suffix or name.endswith("." + suffix) for suffix in REMOTE_CALL_SUFFIXES)


class _Visitor(ast.NodeVisitor):
    def __init__(self, source: str, path: Path) -> None:
        self.source = source
        self.path = path
        self.stack: list[ast.AST] = []
        self.findings: list[Finding] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self.stack.append(node)
        self.generic_visit(node)
        self.stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self.stack.append(node)
        self.generic_visit(node)
        self.stack.pop()

    def visit_Call(self, node: ast.Call) -> Any:
        name = _call_name(node)
        if _is_remote_call(name):
            enclosing_names = [str(getattr(item, "name", "<module>")) for item in self.stack]
            normalized_path = self.path.as_posix()
            if any((normalized_path, function_name) in ALLOWED_NON_INFERENCE_CALLS for function_name in enclosing_names):
                self.generic_visit(node)
                return
            enclosing_sources = [ast.get_source_segment(self.source, item) or "" for item in self.stack]
            safe = any(marker in text for text in enclosing_sources for marker in BROKER_MARKERS)
            # Broker-aware wrapper names are accepted only when their body also
            # contains a broker marker; naming a function _brokered_ is not a
            # security model, despite software's long romance with hopeful names.
            if not safe:
                self.findings.append(Finding(
                    path=str(self.path),
                    line=int(getattr(node, "lineno", 0) or 0),
                    call=name,
                    enclosing_functions=enclosing_names,
                    reason="no_enclosing_inference_broker_run",
                ))
        self.generic_visit(node)


def audit(root: Path) -> dict[str, Any]:
    findings: list[Finding] = []
    scanned = 0
    parse_errors: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in {".git", ".venv", "venv", "__pycache__"} for part in path.parts):
            continue
        if "tests" in path.parts or path.name == "audit_remote_inference_paths.py":
            continue
        scanned += 1
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            parse_errors.append({"path": str(path), "line": exc.lineno, "error": str(exc)})
            continue
        visitor = _Visitor(source, path.relative_to(root))
        visitor.visit(tree)
        findings.extend(visitor.findings)
    return {
        "schema": "eris.remote_inference_audit.v1",
        "root": str(root),
        "python_files_scanned": scanned,
        "unsafe_count": len(findings),
        "parse_errors": parse_errors,
        "findings": [asdict(item) for item in findings],
        "passed": not findings and not parse_errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit remote inference paths against InferenceBroker")
    parser.add_argument("--root", default=".", help="Thư mục src")
    parser.add_argument("--output", default="", help="JSON output")
    args = parser.parse_args()
    report = audit(Path(args.root).resolve())
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n", encoding="utf-8")
        print(target)
    else:
        print(rendered)
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
