# -*- coding: utf-8 -*-
"""Static reachability audit cho package ``cortex``.

Mọi module Python bên ngoài ``cortex`` được xem là production/test entry point.
Audit theo import graph tĩnh, literal ``importlib.import_module`` và parent package.
Nó cố ý bảo thủ: false-positive reachable còn đỡ hơn xóa nhầm module runtime chỉ
vì một dynamic import được viết quá nghệ thuật.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class AuditResult:
    cortex_modules: tuple[str, ...]
    reachable_modules: tuple[str, ...]
    unreachable_modules: tuple[str, ...]


def _module_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _parent_packages(name: str) -> tuple[str, ...]:
    parts = name.split(".")
    return tuple(".".join(parts[:index]) for index in range(1, len(parts)))


def _resolve_from(module: str, path: Path, node: ast.ImportFrom) -> str:
    parts = module.split(".") if module else []
    package = parts if path.name == "__init__.py" else parts[:-1]
    if node.level:
        keep = max(0, len(package) - node.level + 1)
        base = package[:keep]
    else:
        base = []
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def _literal_imports(module: str, path: Path) -> tuple[str, ...]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return ()
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(module, path, node)
            if base:
                names.append(base)
                names.extend(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
        elif isinstance(node, ast.Call):
            func = node.func
            is_import_module = isinstance(func, ast.Attribute) and func.attr == "import_module"
            is_dunder_import = isinstance(func, ast.Name) and func.id == "__import__"
            if (is_import_module or is_dunder_import) and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    names.append(first.value)
    return tuple(names)


def audit(root: Path, *, production_only: bool = True) -> AuditResult:
    root = root.resolve()
    files: dict[str, Path] = {}
    for path in root.rglob("*.py"):
        if any(part in {"__pycache__", ".venv", "venv", ".git"} for part in path.parts):
            continue
        files[_module_name(root, path)] = path

    graph: dict[str, set[str]] = {module: set() for module in files}
    for module, path in files.items():
        for imported in _literal_imports(module, path):
            candidates = (imported, *_parent_packages(imported))
            for candidate in candidates:
                if candidate in files:
                    graph[module].add(candidate)
            parts = imported.split(".")
            for index in range(len(parts), 0, -1):
                candidate = ".".join(parts[:index])
                if candidate in files:
                    graph[module].add(candidate)
                    break

    roots = {
        module
        for module, path in files.items()
        if not (module == "cortex" or module.startswith("cortex."))
        and (not production_only or not ({"tests", "tools"} & set(path.relative_to(root).parts)))
    }
    reachable = set(roots)
    stack = list(roots)
    while stack:
        module = stack.pop()
        for dependency in graph.get(module, ()):
            if dependency not in reachable:
                reachable.add(dependency)
                stack.append(dependency)

    cortex_modules = tuple(sorted(module for module in files if module == "cortex" or module.startswith("cortex.")))
    reachable_cortex = tuple(module for module in cortex_modules if module in reachable)
    unreachable = tuple(module for module in cortex_modules if module not in reachable)
    return AuditResult(cortex_modules, reachable_cortex, unreachable)


def _format(result: AuditResult) -> str:
    lines = [
        f"cortex modules: {len(result.cortex_modules)}",
        f"reachable: {len(result.reachable_modules)}",
        f"unreachable: {len(result.unreachable_modules)}",
    ]
    lines.extend(f"- {module}" for module in result.unreachable_modules)
    return "\n".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--fail-on-unreachable", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = audit(Path(args.root))
    print(_format(result))
    return 1 if args.fail_on_unreachable and result.unreachable_modules else 0


if __name__ == "__main__":
    raise SystemExit(main())
