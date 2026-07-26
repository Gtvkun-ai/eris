# -*- coding: utf-8 -*-
"""Verify ERIS source or a release archive with bounded, safe extraction."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_BASENAMES = {".env", ".coverage", "secrets.json", "secrets_manifest.json"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".log"}


@dataclass(frozen=True, slots=True)
class ArchiveInspection:
    file_count: int
    uncompressed_bytes: int
    compressed_bytes: int
    source_root: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run(command: list[str], *, cwd: Path) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def _coverage_floor(root: Path) -> float:
    manifest = json.loads((root / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    return float((manifest.get("quality") or {}).get("runtime_coverage_floor_percent", 0.0))


def verify_tree(root: Path) -> dict[str, Any]:
    compile_targets = [
        "actions", "core", "cortex", "domain", "llm", "memory", "runtime",
        "screen", "settings", "telemetry", "transport", "tests", "tools",
    ]
    run([sys.executable, "-m", "compileall", "-q", *compile_targets], cwd=root)
    run([sys.executable, "tools/check_architecture.py"], cwd=root)
    run([sys.executable, "tools/audit_exception_boundaries.py", "--check"], cwd=root)
    run([sys.executable, "tools/check_release_manifest.py"], cwd=root)
    coverage_floor = _coverage_floor(root)
    coverage_json = root / ".verify_coverage.json"
    coverage_data = root / ".coverage"
    try:
        run(
            [
                sys.executable, "-m", "pytest",
                "--cov=runtime", "--cov-branch",
                f"--cov-report=json:{coverage_json}",
                f"--cov-fail-under={coverage_floor}", "-q",
            ],
            cwd=root,
        )
        payload = json.loads(coverage_json.read_text(encoding="utf-8"))
        percent = float((payload.get("totals") or {}).get("percent_covered", 0.0))
        print(f"runtime_coverage={percent:.2f}% floor={coverage_floor:.2f}%")
        return {"runtime_coverage": round(percent, 2), "coverage_floor": coverage_floor}
    finally:
        coverage_json.unlink(missing_ok=True)
        coverage_data.unlink(missing_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_archive(
    archive: Path,
    *,
    max_files: int = 10000,
    max_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024,
    max_compression_ratio: float = 250.0,
) -> ArchiveInspection:
    seen: set[str] = set()
    roots: set[str] = set()
    total_uncompressed = 0
    total_compressed = 0
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        if len(infos) > max_files:
            raise RuntimeError(f"archive file count exceeds limit: {len(infos)} > {max_files}")
        for info in infos:
            raw_name = info.filename
            if "\\" in raw_name or raw_name.startswith(("/", "\\")):
                raise RuntimeError(f"unsafe archive path: {raw_name}")
            path = PurePosixPath(raw_name)
            if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
                raise RuntimeError(f"unsafe archive path: {raw_name}")
            normalized = path.as_posix()
            if normalized in seen:
                raise RuntimeError(f"duplicate archive entry: {normalized}")
            seen.add(normalized)
            roots.add(path.parts[0])
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise RuntimeError(f"archive symlink is forbidden: {normalized}")
            if info.flag_bits & 0x1:
                raise RuntimeError(f"encrypted archive entry is forbidden: {normalized}")
            basename = path.name.lower()
            suffix = Path(basename).suffix.lower()
            if (
                "__pycache__" in {part.lower() for part in path.parts}
                or basename in FORBIDDEN_BASENAMES
                or suffix in FORBIDDEN_SUFFIXES
            ):
                raise RuntimeError(f"archive contains forbidden file: {normalized}")
            total_uncompressed += max(0, int(info.file_size))
            total_compressed += max(0, int(info.compress_size))
            if total_uncompressed > max_uncompressed_bytes:
                raise RuntimeError("archive uncompressed size exceeds limit")
            if info.file_size > 0:
                ratio = info.file_size / max(1, info.compress_size)
                if ratio > max_compression_ratio:
                    raise RuntimeError(f"suspicious compression ratio for {normalized}: {ratio:.1f}")
    if len(roots) != 1:
        raise RuntimeError("archive must contain exactly one source root")
    return ArchiveInspection(
        file_count=len(seen),
        uncompressed_bytes=total_uncompressed,
        compressed_bytes=total_compressed,
        source_root=next(iter(roots)),
    )


def safe_extract_archive(archive: Path, target: Path) -> ArchiveInspection:
    inspection = inspect_archive(archive)
    target = target.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            relative = PurePosixPath(info.filename)
            destination = target.joinpath(*relative.parts).resolve()
            if target != destination and target not in destination.parents:
                raise RuntimeError(f"archive path escapes target: {info.filename}")
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info, "r") as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    return inspection


def verify_archive(archive: Path) -> dict[str, Any]:
    archive = archive.resolve()
    with tempfile.TemporaryDirectory(prefix="eris_release_verify_") as tmp:
        target = Path(tmp)
        inspection = safe_extract_archive(archive, target)
        source_root = target / inspection.source_root
        tree = verify_tree(source_root)
        return {
            "archive": str(archive),
            "sha256": sha256(archive),
            "inspection": inspection.to_dict(),
            "tree": tree,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--archive", type=Path, help="Create and verify this archive after verifying source")
    group.add_argument("--verify-existing", type=Path, help="Verify an existing archive only")
    parser.add_argument("--json-summary", type=Path, help="Write a machine-readable verification summary")
    args = parser.parse_args()

    summary: dict[str, Any]
    if args.verify_existing:
        summary = verify_archive(args.verify_existing)
    else:
        source = verify_tree(ROOT)
        summary = {"source": source}
        if args.archive:
            archive = args.archive.resolve()
            archive.unlink(missing_ok=True)
            run([sys.executable, "tools/package_source.py", str(archive), "--root", str(ROOT)], cwd=ROOT)
            summary["release"] = verify_archive(archive)
    if args.json_summary:
        args.json_summary.parent.mkdir(parents=True, exist_ok=True)
        args.json_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
