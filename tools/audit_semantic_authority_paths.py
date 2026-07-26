# -*- coding: utf-8 -*-
"""Guard the semantic-authority cutover from accidental regex regressions.

PDF annotation, pages 12-13 and 20
----------------------------------
The P2 cutover is complete: public chat and post-turn observer entrypoints must
consume ``semantic_frame.v1`` and the removed lexical classifiers must not be
reintroduced as shadow, rollback or compatibility authorities.
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Finding:
    path: str
    line: int
    symbol: str
    reason: str


FORBIDDEN_IMPORT_SYMBOLS = {
    "DiscourseCortex",
    "SemanticCortex",
    "classify_social_act",
    "SocialIntentHead",
}
FORBIDDEN_LIVE_CALLS = {
    "infer_current_turn_anchor",
}
LIVE_ENTRYPOINTS = {
    "observe_completed_turn",
    "generate_public_reply",
    "run_user_turn",
}


def _call_name(node: ast.Call) -> str:
    current: Any = node.func
    parts: list[str] = []
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.function_stack: list[str] = []
        self.findings: list[Finding] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        for alias in node.names:
            if alias.name in FORBIDDEN_IMPORT_SYMBOLS:
                self.findings.append(
                    Finding(
                        path=str(self.path),
                        line=int(node.lineno),
                        symbol=alias.name,
                        reason="legacy_semantic_authority_imported_into_live_module",
                    )
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> Any:
        name = _call_name(node).split(".")[-1]
        if (
            self.function_stack
            and self.function_stack[-1] in LIVE_ENTRYPOINTS
            and name in FORBIDDEN_LIVE_CALLS
        ):
            self.findings.append(
                Finding(
                    path=str(self.path),
                    line=int(getattr(node, "lineno", 0) or 0),
                    symbol=name,
                    reason="live_entrypoint_reclassifies_raw_text",
                )
            )
        self.generic_visit(node)


def audit(root: Path) -> dict[str, Any]:
    targets = (
        Path("runtime/ai_orchestrated/orchestrator.py"),
        Path("runtime/ai_orchestrated/model_router.py"),
        Path("runtime/ai_orchestrated/observer.py"),
    )
    findings: list[Finding] = []
    parse_errors: list[dict[str, Any]] = []
    scanned: list[str] = []
    for relative in targets:
        path = root / relative
        if not path.exists():
            findings.append(Finding(str(relative), 0, "<file>", "required_live_entrypoint_missing"))
            continue
        scanned.append(str(relative))
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            parse_errors.append({"path": str(relative), "line": exc.lineno, "error": str(exc)})
            continue
        visitor = _Visitor(relative)
        visitor.visit(tree)
        findings.extend(visitor.findings)

    # Source-level invariants that are clearer than pretending every semantic
    # relationship can be inferred from AST shape.
    orchestrator = (root / "runtime/ai_orchestrated/orchestrator.py").read_text(
        encoding="utf-8", errors="replace"
    )
    router = (root / "runtime/ai_orchestrated/model_router.py").read_text(
        encoding="utf-8", errors="replace"
    )
    required_markers = {
        "orchestrator_forwards_semantic_frame": (
            orchestrator,
            'observer_state["semantic_frame"]',
        ),
        "observer_uses_frame_anchor": (
            router,
            "authority_anchor = anchor_from_semantic_frame(semantic_frame)",
        ),
        "observer_has_no_legacy_anchor_parameter": (
            router,
            "no raw-text fallback remains",
        ),
    }
    missing_markers = [
        name for name, (source, marker) in required_markers.items() if marker not in source
    ]
    for name in missing_markers:
        findings.append(Finding("<integration>", 0, name, "typed_frame_cutover_marker_missing"))

    return {
        "schema": "eris.semantic_authority_audit.v1",
        "root": str(root),
        "files_scanned": scanned,
        "unsafe_count": len(findings),
        "parse_errors": parse_errors,
        "findings": [asdict(item) for item in findings],
        "passed": not findings and not parse_errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit live semantic authority paths")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="")
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
