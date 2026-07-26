# -*- coding: utf-8 -*-
"""Create a clean, reproducible ERIS source archive."""
from __future__ import annotations

import argparse
import hashlib
import os
import zipfile
from pathlib import Path


EXCLUDED_DIRS = {
    ".git", ".idea", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv",
    "__pycache__", "build", "cache", "dist", "htmlcov", "logs", "runtime_state",
    "secret_versions", "state", "venv",
}
EXCLUDED_NAMES = {
    ".coverage", ".env", "coverage.xml", "secrets.json", "secrets_manifest.json",
}
EXCLUDED_SUFFIXES = {".log", ".pyc", ".pyo", ".tmp"}
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def should_include(relative: Path) -> bool:
    if any(part in EXCLUDED_DIRS for part in relative.parts[:-1]):
        return False
    if relative.name in EXCLUDED_NAMES:
        return False
    if relative.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    return True


def _zip_info(archive_name: str, *, executable: bool) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(archive_name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    mode = 0o755 if executable else 0o644
    info.external_attr = (mode & 0xFFFF) << 16
    info.flag_bits |= 0x800  # UTF-8 names.
    return info


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package(root: Path, output: Path) -> tuple[int, int]:
    root = root.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    files = 0
    bytes_written = 0
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
            if path.is_symlink() or not path.is_file() or path.resolve() == output:
                continue
            relative = path.relative_to(root)
            if not should_include(relative):
                continue
            data = path.read_bytes()
            archive_name = (Path(root.name) / relative).as_posix()
            executable = bool(path.stat().st_mode & 0o111)
            archive.writestr(
                _zip_info(archive_name, executable=executable),
                data,
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
            files += 1
            bytes_written += len(data)
    return files, bytes_written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Destination .zip file")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    files, size = package(args.root, args.output)
    print(
        f"packaged_files={files} source_bytes={size} output={args.output.resolve()} "
        f"sha256={sha256(args.output)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
