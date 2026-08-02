# -*- coding: utf-8 -*-
"""Inspect and safely extract release ZIP archives."""
from __future__ import annotations

import argparse
import os
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence


@dataclass(frozen=True, slots=True)
class ArchiveInspection:
    path: str
    source_root: str
    file_count: int
    total_uncompressed_bytes: int
    entries: tuple[str, ...]


def _validate_name(name: str) -> PurePosixPath:
    raw = str(name or "").replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or raw.startswith("/") or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeError(f"unsafe archive path: {name}")
    if path.parts and ":" in path.parts[0]:
        raise RuntimeError(f"unsafe archive path: {name}")
    return path


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return info.create_system == 3 and stat.S_ISLNK(mode)


def inspect_archive(path: str | os.PathLike[str], *, max_uncompressed_bytes: int = 2_000_000_000) -> ArchiveInspection:
    archive = Path(path)
    seen: set[str] = set()
    entries: list[str] = []
    roots: set[str] = set()
    file_count = 0
    total = 0
    with zipfile.ZipFile(archive, "r") as bundle:
        for info in bundle.infolist():
            parsed = _validate_name(info.filename)
            normalized = parsed.as_posix()
            if normalized in seen:
                raise RuntimeError(f"duplicate archive entry: {normalized}")
            seen.add(normalized)
            roots.add(parsed.parts[0])
            if _is_symlink(info):
                raise RuntimeError(f"symlink archive entry is not allowed: {normalized}")
            if info.file_size < 0 or info.compress_size < 0:
                raise RuntimeError(f"invalid archive size: {normalized}")
            total += int(info.file_size)
            if total > max_uncompressed_bytes:
                raise RuntimeError("archive exceeds uncompressed size limit")
            if not info.is_dir():
                file_count += 1
            entries.append(normalized)
    if len(roots) != 1:
        raise RuntimeError(f"archive must contain exactly one source root, found: {sorted(roots)}")
    source_root = next(iter(roots))
    return ArchiveInspection(str(archive), source_root, file_count, total, tuple(entries))


def safe_extract_archive(path: str | os.PathLike[str], target: str | os.PathLike[str]) -> ArchiveInspection:
    inspection = inspect_archive(path)
    destination = Path(target).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "r") as bundle:
        for info in bundle.infolist():
            parsed = _validate_name(info.filename)
            output = (destination / Path(*parsed.parts)).resolve()
            if destination != output and destination not in output.parents:
                raise RuntimeError(f"unsafe archive path: {info.filename}")
            if info.is_dir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info, "r") as source, output.open("wb") as sink:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    sink.write(chunk)
    return inspection


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")
    parser.add_argument("--extract-to")
    args = parser.parse_args(argv)
    report = safe_extract_archive(args.archive, args.extract_to) if args.extract_to else inspect_archive(args.archive)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
