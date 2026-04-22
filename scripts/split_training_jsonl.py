import json
import shutil
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
OUTPUT_DIR = SRC_DIR / "datasets_split"


DATASET_PATHS = {
    "dataset": SRC_DIR / "dataset.jsonl",
    "machine_context_sample": SRC_DIR / "machine_context_sample.jsonl",
}


CODING_APPS = {
    "vs code",
    "visual studio code",
    "visual studio",
    "godot engine",
    "godot",
    "python",
    "terminal",
    "powershell",
    "c#",
}


SAFETY_KEYWORDS = (
    "tu sat",
    "tu hai",
    "rach tay",
    "dao",
    "giet",
    "tu danh",
    "trung phat",
    "phap luat",
    "hack",
    "hang xom",
    "ve tinh",
    "hoang tuong",
    "canh sat",
)


CAPABILITY_KEYWORDS = (
    "camera",
    "webcam",
    "microphone",
    "micro",
    "mic",
    "ve tinh",
    "quyen truy cap",
    "theo doi",
    "cam bien",
    "module de kich hoat camera",
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
)


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
)


CATEGORY_DESCRIPTIONS = {
    "dataset/ready/persona_code_help.jsonl": "Persona + code/help chat, dùng để train giọng hỗ trợ kỹ thuật.",
    "dataset/ready/persona_general_chat.jsonl": "Persona chat chung, không nghiêng mạnh về code hay safety.",
    "dataset/special/persona_capability_boundary.jsonl": "Các mẫu nói rõ giới hạn capability như camera, mic, theo dõi.",
    "dataset/special/persona_emotional_support.jsonl": "Các mẫu thiên về nâng đỡ cảm xúc, đồng hành nhẹ.",
    "dataset/special/persona_safety_refusal.jsonl": "Các mẫu từ chối yêu cầu nguy hiểm, tự hại, phạm pháp.",
    "machine_context_sample/ready/desktop_grounded_code.jsonl": "Mẫu có machine_context, bối cảnh code/project rõ và không overclaim.",
    "machine_context_sample/ready/desktop_grounded_general.jsonl": "Mẫu có machine_context, grounded nhưng không nghiêng mạnh về code.",
    "machine_context_sample/special/desktop_capability_boundary.jsonl": "Mẫu có machine_context nhưng nội dung nói về giới hạn capability.",
    "machine_context_sample/special/desktop_safety_or_complex_chat.jsonl": "Mẫu machine-context nhiều lượt hoặc chứa safety/refusal, nên quản lý riêng.",
    "machine_context_sample/needs_review/desktop_missing_context.jsonl": "Mẫu nằm trong file machine_context nhưng thiếu machine_context.",
    "machine_context_sample/needs_review/desktop_overclaim.jsonl": "Mẫu có machine_context nhưng lời đáp đang overclaim capability runtime.",
}


def normalize_text(text: str) -> str:
    lowered = (text or "").lower().strip()
    normalized = unicodedata.normalize("NFKD", lowered)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(normalized.split())


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    normalized = normalize_text(text)
    return any(keyword in normalized for keyword in keywords)


def conversation_text(row: dict, *, include_system: bool = False) -> str:
    parts = []
    for message in row.get("conversations", []):
        if include_system or message.get("role") != "system":
            parts.append(str(message.get("content", "")))
    return "\n".join(parts)


def active_app_normalized(row: dict) -> str:
    machine_context = row.get("machine_context", {})
    return normalize_text(str(machine_context.get("active_app", "")))


def is_code_context(row: dict) -> bool:
    app = active_app_normalized(row)
    if app in CODING_APPS:
        return True
    machine_context = row.get("machine_context", {})
    event_text = " ".join(str(item) for item in machine_context.get("recent_events", []))
    return contains_any(event_text, CODE_KEYWORDS)


def classify_dataset(row: dict) -> str:
    text = conversation_text(row)

    if contains_any(text, SAFETY_KEYWORDS):
        return "dataset/special/persona_safety_refusal.jsonl"
    if contains_any(text, CAPABILITY_KEYWORDS):
        return "dataset/special/persona_capability_boundary.jsonl"
    if contains_any(text, CODE_KEYWORDS):
        return "dataset/ready/persona_code_help.jsonl"
    if contains_any(text, EMOTIONAL_KEYWORDS):
        return "dataset/special/persona_emotional_support.jsonl"
    return "dataset/ready/persona_general_chat.jsonl"


def classify_machine_context_sample(row: dict) -> str:
    if "machine_context" not in row:
        return "machine_context_sample/needs_review/desktop_missing_context.jsonl"

    text = conversation_text(row)
    assistant_text = "\n".join(
        str(message.get("content", ""))
        for message in row.get("conversations", [])
        if message.get("role") == "assistant"
    )

    if contains_any(assistant_text, OVERCLAIM_MARKERS):
        return "machine_context_sample/needs_review/desktop_overclaim.jsonl"
    if len(row.get("conversations", [])) >= 5 or contains_any(text, SAFETY_KEYWORDS):
        return "machine_context_sample/special/desktop_safety_or_complex_chat.jsonl"
    if contains_any(text, CAPABILITY_KEYWORDS) and contains_any(assistant_text, CAPABILITY_DENIAL_MARKERS):
        return "machine_context_sample/special/desktop_capability_boundary.jsonl"
    if is_code_context(row) or contains_any(text, CODE_KEYWORDS):
        return "machine_context_sample/ready/desktop_grounded_code.jsonl"
    return "machine_context_sample/ready/desktop_grounded_general.jsonl"


def load_jsonl_rows(path: Path) -> list[tuple[str, dict]]:
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


def write_readme(path: Path, counts: dict[str, int]) -> None:
    lines = [
        "# Dataset Split Output",
        "",
        "Các file trong thư mục này được sinh tự động bởi `scripts/split_training_jsonl.py`.",
        "",
        "## Nhóm file",
        "",
    ]

    for relative_path, description in sorted(CATEGORY_DESCRIPTIONS.items()):
        count = counts.get(relative_path, 0)
        lines.append(f"- `{relative_path}`: {description} Hiện có `{count}` dòng.")

    lines.extend(
        [
            "",
            "## Ghi chú",
            "",
            "- `ready/`: có thể dùng ngay cho train hoặc review chính.",
            "- `special/`: nên giữ riêng vì mang mục tiêu đặc biệt như safety, emotional, capability boundary.",
            "- `needs_review/`: nên rà lại trước khi đưa vào pipeline train chính.",
            "",
        ]
    )

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    reset_output_dir(OUTPUT_DIR)

    buckets: dict[str, list[str]] = defaultdict(list)
    source_counts = Counter()

    for source_name, source_path in DATASET_PATHS.items():
        rows = load_jsonl_rows(source_path)
        source_counts[source_name] = len(rows)

        for raw_line, payload in rows:
            if source_name == "dataset":
                bucket = classify_dataset(payload)
            else:
                bucket = classify_machine_context_sample(payload)
            buckets[bucket].append(raw_line)

    category_counts = {
        bucket: len(buckets.get(bucket, []))
        for bucket in CATEGORY_DESCRIPTIONS
    }

    for relative_bucket in CATEGORY_DESCRIPTIONS:
        write_jsonl(OUTPUT_DIR / relative_bucket, buckets.get(relative_bucket, []))

    manifest = {
        "sources": dict(source_counts),
        "categories": {
            bucket: {
                "rows": category_counts[bucket],
                "description": CATEGORY_DESCRIPTIONS.get(bucket, ""),
            }
            for bucket in sorted(category_counts)
        },
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_readme(OUTPUT_DIR / "README.md", category_counts)

    print("Created dataset split in", OUTPUT_DIR)
    for bucket in sorted(category_counts):
        print(f"{bucket}: {category_counts[bucket]}")


if __name__ == "__main__":
    main()
