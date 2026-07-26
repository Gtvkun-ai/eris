# -*- coding: utf-8 -*-
"""Architecture audit cho Cortex V2 hot path."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ArchitectureAudit:
    cycles: tuple[tuple[str, ...], ...]
    forbidden_imports: tuple[str, ...]
    package_root_reexports: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not (self.cycles or self.forbidden_imports or self.package_root_reexports)


def _module(root: Path, path: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(root: Path, path: Path, module: str) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    parts = module.split(".")
    package = parts if path.name == "__init__.py" else parts[:-1]
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: max(0, len(package) - node.level + 1)]
            else:
                base = []
            if node.module:
                base.extend(node.module.split("."))
            name = ".".join(base)
            if name:
                result.append(name)
    return tuple(result)


def _tarjan(graph: dict[str, set[str]]) -> tuple[tuple[str, ...], ...]:
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for child in graph.get(node, ()):
            if child not in indices:
                visit(child)
                lowlinks[node] = min(lowlinks[node], lowlinks[child])
            elif child in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[child])
        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while stack:
                child = stack.pop()
                on_stack.remove(child)
                component.append(child)
                if child == node:
                    break
            if len(component) > 1:
                components.append(tuple(sorted(component)))

    for node in graph:
        if node not in indices:
            visit(node)
    return tuple(sorted(components))


def audit(root: Path) -> ArchitectureAudit:
    root = root.resolve()
    paths = [
        *root.joinpath("core", "cognition").glob("*.py"),
        *root.joinpath("runtime", "cognition").rglob("*.py"),
    ]
    files = {_module(root, path): path for path in paths if path.is_file()}
    graph: dict[str, set[str]] = {module: set() for module in files}
    forbidden: list[str] = []
    for module, path in files.items():
        for imported in _imports(root, path, module):
            matches = [
                candidate
                for candidate in files
                if imported == candidate or imported.startswith(candidate + ".")
            ]
            if matches:
                graph[module].add(max(matches, key=len))
            if module.startswith("core.cognition") and imported.startswith(("runtime", "cortex", "memory", "llm")):
                forbidden.append(f"{module}->{imported}")
            if module.startswith("runtime.cognition") and imported.startswith("cortex"):
                forbidden.append(f"{module}->{imported}")

    root_init = root / "cortex" / "__init__.py"
    reexports: list[str] = []
    if root_init.exists():
        tree = ast.parse(root_init.read_text(encoding="utf-8-sig"), filename=str(root_init))
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                reexports.append(ast.unparse(node))
    return ArchitectureAudit(
        cycles=_tarjan(graph),
        forbidden_imports=tuple(sorted(set(forbidden))),
        package_root_reexports=tuple(reexports),
    )


def main(argv: Iterable[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = audit(Path(args.root))
    print(f"cycles: {len(result.cycles)}")
    print(f"forbidden imports: {len(result.forbidden_imports)}")
    print(f"cortex root reexports: {len(result.package_root_reexports)}")
    for category in (result.cycles, result.forbidden_imports, result.package_root_reexports):
        for item in category:
            print(f"- {item}")
    return 0 if result.clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
