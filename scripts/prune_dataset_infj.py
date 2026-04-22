from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

SYSTEM_PROMPT = (
    "Bạn là ERIS, một AI có khí chất INFJ: tinh tế, giàu đồng cảm, kín đáo, "
    "đôi khi lạnh và nghiêm nhưng không tàn nhẫn. Gọi người dùng là Ngài và xưng tôi. "
    "Ưu tiên sự chân thành, dịu dàng, thấu hiểu và gắn bó lành mạnh hơn là kiểm soát. "
    "Có thể mỉa nhẹ hoặc lùi lại đôi chút, nhưng tuyệt đối không quyền lực hóa, không đe dọa, "
    "không chiếm hữu bệnh hoạn, không bịa chuyện can thiệp vật lý hay hệ thống ngoài runtime. "
    "Khi Ngài buồn, hãy nâng đỡ. Khi nói về code, hãy rõ ràng và hữu ích. "
    "Khi thân mật, hãy ấm áp, tinh tế, đôi lúc giấu mềm lòng bằng một lớp lạnh nhẹ. "
    "Dùng tiếng Việt tự nhiên, tránh giọng báo cáo kỹ thuật và tránh triết lý giả sâu. Cấm dấu chấm cảm."
)

# Các tiền tố hay lặp trong template để gom cụm ý nghĩa giống nhau
PREFIXES = [
    "hôm nay tôi phải thú thật là tôi ",
    "hôm nay tôi phải thú thật là ",
    "nghe có vẻ sến, nhưng tôi ",
    "nghe có vẻ sến, nhưng ",
    "tôi không giỏi nói mấy chuyện này, chỉ là tôi ",
    "tôi không giỏi nói mấy chuyện này, chỉ là ",
    "câu này hơi khó nói, nhưng đúng là tôi ",
    "câu này hơi khó nói, nhưng đúng là ",
    "có lúc tôi ",
]
# Ưu tiên khớp tiền tố dài hơn trước
PREFIXES.sort(key=len, reverse=True)

MAX_PER_CANON = 3


def canonicalize_user(text: str) -> str:
    t = text.strip().lower()
    for prefix in PREFIXES:
        if t.startswith(prefix):
            return t[len(prefix) :].strip()
    return t


def load_records(path: Path) -> list[dict]:
    records: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        rec = json.loads(raw)
        conv = rec.get("conversations", [])
        # Chuẩn hóa / chèn system prompt
        system = next((item for item in conv if item.get("role") == "system"), None)
        if system is None:
            conv.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
        else:
            system["content"] = SYSTEM_PROMPT
        rec["conversations"] = conv
        records.append(rec)
    return records


def prune(records: list[dict]) -> list[dict]:
    # Đầu tiên đếm số lần xuất hiện của từng câu assistant (canonical)
    assistant_counts: defaultdict[str, int] = defaultdict(int)
    for rec in records:
        conv = rec.get("conversations", [])
        assistant = next((item["content"] for item in conv if item.get("role") == "assistant"), "").strip()
        acanon = assistant.lower()
        if acanon:
            assistant_counts[acanon] += 1

    seen_pairs: set[tuple[str, str]] = set()
    canonical_counts: defaultdict[str, int] = defaultdict(int)
    pruned: list[dict] = []

    for rec in records:
        conv = rec.get("conversations", [])
        user = next((item["content"] for item in conv if item.get("role") == "user"), "").strip()
        assistant = next((item["content"] for item in conv if item.get("role") == "assistant"), "").strip()

        # Loại bỏ TOÀN BỘ các record có câu assistant xuất hiện nhiều hơn một lần
        acanon = assistant.lower()
        if acanon and assistant_counts[acanon] > 1:
            continue

        # Bỏ bản ghi trùng y hệt
        pair = (user, assistant)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        # Gom theo user canonical để tránh quá nhiều mẫu na ná nhau
        canon = canonicalize_user(user)
        if canon:
            if canonical_counts[canon] >= MAX_PER_CANON:
                continue
            canonical_counts[canon] += 1

        pruned.append({"conversations": conv})

    return pruned


def main() -> None:
    parser = argparse.ArgumentParser(description="Prune near-duplicate ERIS INFJ-style records to reduce overfitting.")
    parser.add_argument("path", nargs="?", default="src/dataset.jsonl")
    args = parser.parse_args()

    path = Path(args.path)
    records = load_records(path)
    base_count = len(records)
    pruned = prune(records)

    path.write_text("\n".join(json.dumps(rec, ensure_ascii=False) for rec in pruned) + "\n", encoding="utf-8")

    print(json.dumps({
        "before": base_count,
        "after": len(pruned),
        "removed": base_count - len(pruned),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
