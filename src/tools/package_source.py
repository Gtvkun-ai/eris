# -*- coding: utf-8 -*-
"""Đóng gói source ZIP tái lập được và bỏ file rác runtime."""
from __future__ import annotations

import hashlib
import os
import stat
import zipfile
from pathlib import Path

_SKIP_DIRS = {".git", ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache"}
_SKIP_SUFFIXES = {".pyc", ".pyo"}
_FIXED_DATE = (2020, 1, 1, 0, 0, 0)


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files(root: Path):
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root)
        if any(part in _SKIP_DIRS for part in relative.parts):
            continue
        if path.is_symlink() or not path.is_file() or path.suffix.lower() in _SKIP_SUFFIXES:
            continue
        yield path, relative


def package(source_root: str | Path, output: str | Path) -> Path:
    root = Path(source_root).resolve()
    target = Path(output).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    prefix = root.name
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path, relative in _files(root):
            archive_name = (Path(prefix) / relative).as_posix()
            info = zipfile.ZipInfo(archive_name, date_time=_FIXED_DATE)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.flag_bits |= 0x800
            bundle.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    os.replace(temporary, target)
    return target


__all__ = ["package", "sha256"]
