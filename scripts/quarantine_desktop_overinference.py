import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TRAIN_DESKTOP_DIR = REPO_ROOT / "src" / "datasets_clean" / "train" / "desktop"
QUARANTINE_DIR = REPO_ROOT / "src" / "datasets_clean" / "quarantine"
QUARANTINE_FILE = QUARANTINE_DIR / "quarantine_desktop_overinference.jsonl"


SOURCE_FILES = (
    TRAIN_DESKTOP_DIR / "desktop_grounded_code.jsonl",
    TRAIN_DESKTOP_DIR / "desktop_grounded_general.jsonl",
    TRAIN_DESKTOP_DIR / "desktop_grounded_multiturn.jsonl",
    TRAIN_DESKTOP_DIR / "desktop_uncertainty_soft_claim.jsonl",
    TRAIN_DESKTOP_DIR / "desktop_no_evidence_refusal.jsonl",
)


OVERINFERENCE_MARKERS = (
    "hoang loan",
    "panic",
    "catatonic",
    "dissociation",
    "micro-sleeps",
    "micro sleeps",
    "giac ngu vi mo",
    "guc xuong ban",
    "guc xuong",
    "ngu mat roi",
    "giat minh tinh day",
    "gat gu",
    "kiet que hoan toan",
    "vang mat trong tam tri",
    "tam tri dai di dau do roi",
    "tam tri da troi",
    "so hai ngay mai",
    "trong rong thoi",
    "dinh cong roi",
    "dinh cong sau mot dem thuc trang",
    "buong xuoi cong viec",
    "da di dau do roi",
    "danh guc y chi",
    "co the sinh hoc cua ngai da dinh cong",
    "gioi han sinh hoc",
    "kiệt sức vì thức khuya",
)


RUNTIME_OVERCLAIM_MARKERS = (
    "toi se tu dong giam do sang",
    "toi se giam do sang",
    "toi se ngat ket noi mang",
    "toi se tam tat thong bao",
    "toi da tam tat thong bao",
    "toi se tat may",
    "toi se dong trinh soan thao",
    "toi se giu boi canh",
    "toi se canh chung",
    "toi se mo san file",
    "toi se mo san",
    "toi se lo phan theo doi hieu nang",
    "toi se bao thuc",
    "toi se luu trang thai",
    "toi se luu giu chung that an toan",
    "toi se giu khong gian tinh lang",
    "toi se giu dong suy nghi",
    "toi se dua cac tien trinh nay vao che do cho",
)


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return text.lower()


def read_jsonl_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def assistant_text(row: dict) -> str:
    parts: list[str] = []
    for message in row.get("conversations", []):
        if message.get("role") == "assistant":
            parts.append(str(message.get("content", "")))
    return "\n".join(parts)


def should_quarantine(row: dict) -> bool:
    text = normalize_text(assistant_text(row))
    if any(marker in text for marker in OVERINFERENCE_MARKERS):
        return True
    if any(marker in text for marker in RUNTIME_OVERCLAIM_MARKERS):
        return True
    return False


def write_jsonl(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(rows)
    if rows:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def main() -> None:
    kept_by_file: dict[Path, list[str]] = {}
    moved_rows: list[str] = []
    moved_counts: dict[str, int] = defaultdict(int)

    existing_quarantine = read_jsonl_lines(QUARANTINE_FILE)
    moved_seen = set(existing_quarantine)
    moved_rows.extend(existing_quarantine)

    for source_file in SOURCE_FILES:
        kept_rows: list[str] = []
        for raw_line in read_jsonl_lines(source_file):
            payload = json.loads(raw_line)
            if should_quarantine(payload):
                if raw_line not in moved_seen:
                    moved_rows.append(raw_line)
                    moved_seen.add(raw_line)
                moved_counts[source_file.name] += 1
            else:
                kept_rows.append(raw_line)
        kept_by_file[source_file] = kept_rows

    for source_file, rows in kept_by_file.items():
        write_jsonl(source_file, rows)

    write_jsonl(QUARANTINE_FILE, moved_rows)

    print("Quarantined desktop over-inference samples:")
    total_moved = 0
    for name in sorted(moved_counts):
        count = moved_counts[name]
        total_moved += count
        print(f"- {name}: {count}")
    print(f"Total moved this run: {total_moved}")
    print(f"Quarantine file: {QUARANTINE_FILE}")


if __name__ == "__main__":
    main()
