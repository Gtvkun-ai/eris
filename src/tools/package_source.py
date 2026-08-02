# -*- coding: utf-8 -*-
"""Create deterministic source ZIP archives."""
from __future__ import annotations

import argparse
import hashlib
import os
import zipfile
from pathlib import Path
from typing import Iterable, Sequence

_FIXED_TIME = (1980, 1, 1, 0, 0, 0)
_DEFAULT_EXCLUDES = {"__pycache__", ".pytest_cache", ".git", ".mypy_cache", ".ruff_cache"}


def sha256(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if any(part in _DEFAULT_EXCLUDES for part in path.parts):
            continue
        if path.is_file() and not path.is_symlink():
            yield path


def package(source_root: str | os.PathLike[str], destination: str | os.PathLike[str]) -> Path:
    root = Path(source_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = root.name
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in _files(root):
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(f"{prefix}/{relative}", date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o100644 & 0xFFFF) << 16
            info.flag_bits |= 0x800
            bundle.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("destination")
    args = parser.parse_args(argv)
    output = package(args.source, args.destination)
    print(f"{output}\t{sha256(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
