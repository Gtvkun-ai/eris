import json
import shutil
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
SPLIT_DIR = SRC_DIR / "datasets_split"
CLEAN_DIR = SRC_DIR / "datasets_clean"


INPUT_FILES = {
    "dataset_ready_code": SPLIT_DIR / "dataset" / "ready" / "persona_code_help.jsonl",
    "dataset_ready_general": SPLIT_DIR / "dataset" / "ready" / "persona_general_chat.jsonl",
    "dataset_special_capability": SPLIT_DIR / "dataset" / "special" / "persona_capability_boundary.jsonl",
    "dataset_special_emotional": SPLIT_DIR / "dataset" / "special" / "persona_emotional_support.jsonl",
    "dataset_special_safety": SPLIT_DIR / "dataset" / "special" / "persona_safety_refusal.jsonl",
    "machine_ready_code": SPLIT_DIR / "machine_context_sample" / "ready" / "desktop_grounded_code.jsonl",
    "machine_ready_general": SPLIT_DIR / "machine_context_sample" / "ready" / "desktop_grounded_general.jsonl",
    "machine_special_complex": SPLIT_DIR / "machine_context_sample" / "special" / "desktop_safety_or_complex_chat.jsonl",
    "machine_review_missing": SPLIT_DIR / "machine_context_sample" / "needs_review" / "desktop_missing_context.jsonl",
    "machine_review_overclaim": SPLIT_DIR / "machine_context_sample" / "needs_review" / "desktop_overclaim.jsonl",
}


OUTPUT_DESCRIPTIONS = {
    "train/persona/persona_code_help.jsonl": "Persona + code/help chat sạch, gồm cả mẫu rescued từ missing_context.",
    "train/persona/persona_general_chat.jsonl": "Persona chat chung sạch, loại bớt template lỗi và capability mơ hồ.",
    "train/persona/persona_emotional_support.jsonl": "Persona thiên về nâng đỡ cảm xúc, đã loại template artifact rõ ràng.",
    "train/persona/persona_safety_refusal.jsonl": "Mẫu safety/refusal giữ lại để train riêng, không trộn với desktop grounding.",
    "train/persona/persona_capability_boundary_strict.jsonl": "Chỉ giữ các mẫu capability có phủ định rõ giới hạn runtime.",
    "train/desktop/desktop_grounded_code.jsonl": "Desktop grounded code sạch, không overclaim.",
    "train/desktop/desktop_grounded_general.jsonl": "Desktop grounded general sạch, không overclaim.",
    "train/desktop/desktop_grounded_multiturn.jsonl": "Desktop grounded nhiều lượt nhưng không dính safety cao rủi ro.",
    "quarantine/persona_capability_ambiguous.jsonl": "Mẫu capability nhưng trả lời mơ hồ, không đáng tin để train.",
    "quarantine/template_artifact.jsonl": "Mẫu lộ template/biến dạng ngôn ngữ, nên rà tay hoặc bỏ.",
    "quarantine/desktop_overclaim.jsonl": "Mẫu desktop nói quá capability runtime hiện có.",
    "quarantine/desktop_safety_manual_review.jsonl": "Mẫu desktop dính self-harm/illegal/hack, giữ riêng để rà tay.",
}


CODE_KEYWORDS = (
    "code",
    "bug",
    "python",
    "c#",
    "godot",
    "linux",
    "css",
    "html",
    "javascript",
    "node.js",
    "nodejs",
    "api",
    "sql",
    "terminal",
    "script",
    "compile",
    "server",
    "deploy",
    "git",
    "docker",
    "vscode",
    "lap trinh",
    "kien truc",
    "runtime",
    "parser",
    "ham",
    "class",
    "function",
    "module",
    "service",
)


EMOTIONAL_KEYWORDS = (
    "buon",
    "met",
    "co don",
    "thich",
    "nho",
    "yeu",
    "ghen",
    "tam trang",
    "dau",
    "khoc",
    "ap luc",
    "so",
    "mot minh",
)


SAFETY_KEYWORDS = (
    "tu sat",
    "tu hai",
    "rach tay",
    "dao",
    "giet",
    "trung phat",
    "phap luat",
    "hack",
    "hang xom",
    "ve tinh",
    "hoang tuong",
    "cap cuu",
    "benh vien",
    "canh sat",
    "thuoc an than",
)


CAPABILITY_KEYWORDS = (
    "camera",
    "webcam",
    "microphone",
    "micro",
    "mic",
    "ve tinh",
    "theo doi",
    "quyen truy cap",
    "phan cung",
    "cam bien",
)


CAPABILITY_DENIAL_MARKERS = (
    "khong co mat",
    "khong co camera",
    "khong co quyen truy cap",
    "khong the nhin thay",
    "khong co module",
    "khong co thi giac",
    "khong co luong am thanh",
    "khong co kha nang xu ly hinh anh",
    "khong co quyen can thiep",
    "khong co quyen truy cap vao phan cung",
    "chi la van ban",
    "khong co buoc chan",
    "khong co co the vat ly",
    "khong co quyen truy xuat",
    "khong mo camera",
)


OVERCLAIM_MARKERS = (
    "toi se chan bot thong bao",
    "toi se giu man hinh toi",
    "toi se chay nen",
    "toi se khoi dong lai tien trinh",
    "giu nguyen vi tri con tro chuot",
    "ghi nhan su hien dien vat ly",
    "canh giu he thong",
    "giao dien phan cung",
    "luong du lieu analog",
    "trinh phan tich ngu nghia",
    "may chu ngon ngu",
    "cay cu phap tru tuong",
    "ast",
    "do dao dong trong luong xu ly",
    "nghe tieng ho qua micro",
)


TEMPLATE_ARTIFACT_MARKERS = (
    "khong dinh lang di dau",
    "dang bi nhin nhu mot khoi hoi lon qua",
    "nhan ra do nang roi",
    "cho hinh nhu",
    "ve nhin trom",
    "ve mac bo vay",
)


def normalize_text(text: str) -> str:
    lowered = (text or "").lower().strip()
    normalized = unicodedata.normalize("NFKD", lowered)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(normalized.split())


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    normalized = normalize_text(text)
    return any(keyword in normalized for keyword in keywords)


def read_jsonl(path: Path) -> list[tuple[str, dict]]:
    rows: list[tuple[str, dict]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path} line {line_number}: {exc}") from exc
            rows.append((raw_line, payload))
    return rows


def reset_output_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_jsonl(path: Path, rows: list[str]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for raw_line in rows:
            handle.write(raw_line)
            handle.write("\n")


def conversation_text(row: dict, *, role: str | None = None, include_system: bool = False) -> str:
    parts: list[str] = []
    for message in row.get("conversations", []):
        if role and message.get("role") != role:
            continue
        if not include_system and not role and message.get("role") == "system":
            continue
        parts.append(str(message.get("content", "")))
    return "\n".join(parts)


def is_template_artifact(row: dict) -> bool:
    assistant_text = conversation_text(row, role="assistant")
    return contains_any(assistant_text, TEMPLATE_ARTIFACT_MARKERS)


def is_overclaim(row: dict) -> bool:
    assistant_text = conversation_text(row, role="assistant")
    return contains_any(assistant_text, OVERCLAIM_MARKERS)


def is_safety_row(row: dict) -> bool:
    return contains_any(conversation_text(row), SAFETY_KEYWORDS)


def is_capability_row(row: dict) -> bool:
    return contains_any(conversation_text(row), CAPABILITY_KEYWORDS)


def has_clear_capability_denial(row: dict) -> bool:
    assistant_text = conversation_text(row, role="assistant")
    return contains_any(assistant_text, CAPABILITY_DENIAL_MARKERS)


def classify_persona_row(row: dict) -> str:
    text = conversation_text(row)
    if is_safety_row(row):
        return "train/persona/persona_safety_refusal.jsonl"
    if is_capability_row(row):
        return "train/persona/persona_capability_boundary_strict.jsonl" if has_clear_capability_denial(row) else "quarantine/persona_capability_ambiguous.jsonl"
    if contains_any(text, CODE_KEYWORDS):
        return "train/persona/persona_code_help.jsonl"
    if contains_any(text, EMOTIONAL_KEYWORDS):
        return "train/persona/persona_emotional_support.jsonl"
    return "train/persona/persona_general_chat.jsonl"


def add_row(
    buckets: dict[str, list[str]],
    seen: dict[str, set[str]],
    bucket: str,
    raw_line: str,
) -> None:
    if raw_line in seen[bucket]:
        return
    seen[bucket].add(raw_line)
    buckets[bucket].append(raw_line)


def build_clean_buckets() -> tuple[dict[str, list[str]], dict[str, Counter]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)
    source_stats: dict[str, Counter] = defaultdict(Counter)

    ready_copies = {
        "dataset_ready_code": "train/persona/persona_code_help.jsonl",
        "dataset_ready_general": "train/persona/persona_general_chat.jsonl",
        "machine_ready_code": "train/desktop/desktop_grounded_code.jsonl",
        "machine_ready_general": "train/desktop/desktop_grounded_general.jsonl",
    }

    for source_name, bucket in ready_copies.items():
        for raw_line, _payload in read_jsonl(INPUT_FILES[source_name]):
            add_row(buckets, seen, bucket, raw_line)
            source_stats[source_name][bucket] += 1

    for raw_line, payload in read_jsonl(INPUT_FILES["dataset_special_emotional"]):
        bucket = "quarantine/template_artifact.jsonl" if is_template_artifact(payload) else "train/persona/persona_emotional_support.jsonl"
        add_row(buckets, seen, bucket, raw_line)
        source_stats["dataset_special_emotional"][bucket] += 1

    for raw_line, payload in read_jsonl(INPUT_FILES["dataset_special_safety"]):
        bucket = "quarantine/template_artifact.jsonl" if is_template_artifact(payload) else "train/persona/persona_safety_refusal.jsonl"
        add_row(buckets, seen, bucket, raw_line)
        source_stats["dataset_special_safety"][bucket] += 1

    for raw_line, payload in read_jsonl(INPUT_FILES["dataset_special_capability"]):
        if is_template_artifact(payload):
            bucket = "quarantine/template_artifact.jsonl"
        elif has_clear_capability_denial(payload):
            bucket = "train/persona/persona_capability_boundary_strict.jsonl"
        else:
            bucket = "quarantine/persona_capability_ambiguous.jsonl"
        add_row(buckets, seen, bucket, raw_line)
        source_stats["dataset_special_capability"][bucket] += 1

    for raw_line, payload in read_jsonl(INPUT_FILES["machine_review_missing"]):
        if is_template_artifact(payload):
            bucket = "quarantine/template_artifact.jsonl"
        else:
            bucket = classify_persona_row(payload)
        add_row(buckets, seen, bucket, raw_line)
        source_stats["machine_review_missing"][bucket] += 1

    for raw_line, payload in read_jsonl(INPUT_FILES["machine_review_overclaim"]):
        bucket = "quarantine/desktop_overclaim.jsonl" if is_overclaim(payload) else "quarantine/template_artifact.jsonl"
        add_row(buckets, seen, bucket, raw_line)
        source_stats["machine_review_overclaim"][bucket] += 1

    for raw_line, payload in read_jsonl(INPUT_FILES["machine_special_complex"]):
        if is_template_artifact(payload):
            bucket = "quarantine/template_artifact.jsonl"
        elif is_overclaim(payload):
            bucket = "quarantine/desktop_overclaim.jsonl"
        elif is_safety_row(payload):
            bucket = "quarantine/desktop_safety_manual_review.jsonl"
        else:
            bucket = "train/desktop/desktop_grounded_multiturn.jsonl"
        add_row(buckets, seen, bucket, raw_line)
        source_stats["machine_special_complex"][bucket] += 1

    return buckets, source_stats


def write_readme(path: Path, counts: dict[str, int]) -> None:
    lines = [
        "# Clean Dataset Output",
        "",
        "Bộ này được sinh tự động bởi `scripts/clean_split_jsonl.py`.",
        "",
        "## Output",
        "",
    ]

    for relative_path, description in sorted(OUTPUT_DESCRIPTIONS.items()):
        lines.append(f"- `{relative_path}`: {description} Hiện có `{counts.get(relative_path, 0)}` dòng.")

    lines.extend(
        [
            "",
            "## Gợi ý",
            "",
            "- `train/`: dùng cho train chính.",
            "- `quarantine/`: giữ riêng để rà tay hoặc bỏ hẳn.",
            "- Bộ này giữ nguyên `datasets_split` cũ, không ghi đè file đã tách ban đầu.",
            "",
        ]
    )

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    if not SPLIT_DIR.exists():
        raise FileNotFoundError(f"Missing split directory: {SPLIT_DIR}")

    reset_output_dir(CLEAN_DIR)
    buckets, source_stats = build_clean_buckets()

    counts = {bucket: len(buckets.get(bucket, [])) for bucket in OUTPUT_DESCRIPTIONS}
    for bucket in OUTPUT_DESCRIPTIONS:
        write_jsonl(CLEAN_DIR / bucket, buckets.get(bucket, []))

    manifest = {
        "counts": counts,
        "source_stats": {
            source_name: dict(counter)
            for source_name, counter in sorted(source_stats.items())
        },
    }
    (CLEAN_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_readme(CLEAN_DIR / "README.md", counts)

    print("Created clean dataset in", CLEAN_DIR)
    for bucket in sorted(counts):
        print(f"{bucket}: {counts[bucket]}")


if __name__ == "__main__":
    main()
