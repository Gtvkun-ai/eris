from __future__ import annotations

import json
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
PERSONA_DIR = ROOT_DIR / "src" / "datasets_clean" / "train" / "persona"
OUTPUT_PATH = ROOT_DIR / "src" / "datasets_clean" / "train" / "fe" / "fe_style_supervision.jsonl"

STYLE_DEFAULTS = {
    "persona_general_chat.jsonl": {
        "tone": "cold_soft",
        "warmth": "mid",
        "stance": "grounded",
        "attachment": "guarded",
        "arc": "quiet_observation",
    },
    "persona_emotional_support.jsonl": {
        "tone": "cold_soft",
        "warmth": "high",
        "stance": "comforting",
        "attachment": "guarded",
        "arc": "guarded_attachment",
    },
    "persona_code_help.jsonl": {
        "tone": "cold_soft",
        "warmth": "mid",
        "stance": "technical",
        "attachment": "guarded",
        "arc": "technical_guardianship",
    },
}


def iter_persona_rows():
    for file_name, style in STYLE_DEFAULTS.items():
        source_path = PERSONA_DIR / file_name
        with source_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                payload = json.loads(stripped)
                conversations = payload.get("conversations")
                if not isinstance(conversations, list) or not conversations:
                    continue
                yield source_path, line_number, style, conversations


def build_record(source_path: Path, line_number: int, style: dict[str, str], conversations: list[dict]) -> dict:
    style_tags = [
        f"tone={style['tone']}",
        f"warmth={style['warmth']}",
        f"stance={style['stance']}",
        f"attachment={style['attachment']}",
        f"arc={style['arc']}",
        "continuity=hold_tone",
    ]
    return {
        "source_file": source_path.name,
        "source_line": line_number,
        "knowledge_context": {
            "style_tags": style_tags,
            "style_source": source_path.stem,
        },
        "conversations": conversations,
    }


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    rows_written = 0
    with OUTPUT_PATH.open("w", encoding="utf-8") as handle:
        for source_path, line_number, style, conversations in iter_persona_rows():
            record = build_record(source_path, line_number, style, conversations)
            json.dump(record, handle, ensure_ascii=False)
            handle.write("\n")
            rows_written += 1

    print(f"Wrote {rows_written} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
