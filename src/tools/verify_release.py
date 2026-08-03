# -*- coding: utf-8 -*-
"""Kiểm tra và giải nén ZIP source mà không tin tên entry do người dùng cấp."""
from __future__ import annotations

import os
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class ArchiveInspection:
    source_root: str
    file_count: int
    total_uncompressed_bytes: int


def _safe_parts(name: str) -> tuple[str, ...]:
    normalized = str(name or "").replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeError(f"unsafe archive path: {name}")
    return tuple(path.parts)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def inspect_archive(path: str | Path) -> ArchiveInspection:
    archive = Path(path)
    roots: set[str] = set()
    seen: set[str] = set()
    files = 0
    total = 0
    with zipfile.ZipFile(archive, "r") as bundle:
        for info in bundle.infolist():
            parts = _safe_parts(info.filename)
            canonical = "/".join(parts)
            if canonical in seen:
                raise RuntimeError(f"duplicate archive entry: {canonical}")
            seen.add(canonical)
            roots.add(parts[0])
            if _is_symlink(info):
                raise RuntimeError(f"symlink archive entry is not allowed: {canonical}")
            if not info.is_dir():
                files += 1
                total += max(0, int(info.file_size))
    if len(roots) != 1:
        raise RuntimeError("archive must contain exactly one source root")
    return ArchiveInspection(source_root=next(iter(roots)), file_count=files, total_uncompressed_bytes=total)


def safe_extract_archive(path: str | Path, target: str | Path) -> ArchiveInspection:
    inspection = inspect_archive(path)
    destination = Path(target).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "r") as bundle:
        for info in bundle.infolist():
            parts = _safe_parts(info.filename)
            output = destination.joinpath(*parts).resolve()
            if os.path.commonpath((str(destination), str(output))) != str(destination):
                raise RuntimeError(f"unsafe archive path: {info.filename}")
            if info.is_dir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info, "r") as source, output.open("wb") as sink:
                while chunk := source.read(1024 * 1024):
                    sink.write(chunk)
    return inspection


__all__ = ["ArchiveInspection", "inspect_archive", "safe_extract_archive"]
