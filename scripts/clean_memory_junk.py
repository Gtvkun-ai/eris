# -*- coding: utf-8 -*-
"""Dọn rác nội sinh trong memory_core.

Nguyên tắc:
- Gộp các dòng trùng liên tiếp ở thought_stream / anchor_journal (giữ 1, cộng revisit).
- Xoá các private_concern là vòng lặp "áp lực về chính áp lực" (pegged + theme tự sinh).
- Clamp lại pressure/recurrence runaway của concern còn giữ.
- Xoá file .tmp rơi vãi.
Mọi file đều backup .bak trước khi ghi đè.
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MC = ROOT / "memory_core"

LOOP_PHRASES = ("áp lực tâm lý", "mâu thuẫn nội tâm", "giảm áp lực", "áp lực tâm lý-và")


def backup(p: Path):
    if p.exists():
        shutil.copy2(p, p.with_suffix(p.suffix + ".bak"))


def read_jsonl(p: Path):
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def write_jsonl(p: Path, rows):
    with p.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def clean_thought_stream():
    p = MC / "thought_stream.jsonl"
    rows = read_jsonl(p)
    out = []
    for r in rows:
        txt = (r.get("text") or "").strip().casefold()
        if out and (out[-1].get("text") or "").strip().casefold() == txt:
            out[-1]["revisit_count"] = int(out[-1].get("revisit_count") or 0) + 1
            out[-1]["last_revisit_at"] = r.get("ts", out[-1].get("last_revisit_at", 0.0))
            continue
        out.append(r)
    backup(p)
    write_jsonl(p, out)
    print(f"thought_stream.jsonl: {len(rows)} -> {len(out)} (gộp {len(rows) - len(out)} dòng trùng)")


def clean_anchor_journal():
    p = MC / "anchor_journal.jsonl"
    rows = read_jsonl(p)

    def sig(x):
        um = x.get("user_model", {}) or {}
        sh = x.get("shadow", {}) or {}
        at = x.get("attachment", {}) or {}
        dec = x.get("deception", {}) or {}
        return (
            um.get("belief_count"),
            round(float(at.get("longarc") or 0), 3),
            sh.get("register"),
            round(float(sh.get("intensity") or 0), 3),
            int(dec.get("count") or 0),
        )

    out = []
    prev = object()
    for r in rows:
        s = sig(r)
        if s == prev:
            continue
        out.append(r)
        prev = s
    backup(p)
    write_jsonl(p, out)
    print(f"anchor_journal.jsonl: {len(rows)} -> {len(out)} (bỏ {len(rows) - len(out)} snapshot trùng liên tiếp)")


def clean_concerns():
    p = MC / "private_concerns.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    concerns = data.get("concerns", [])
    kept = []
    dropped = []
    for c in concerns:
        theme = str(c.get("theme") or "").casefold()
        pressure = float(c.get("pressure") or 0.0)
        is_loop = any(ph in theme for ph in LOOP_PHRASES)
        if pressure >= 0.85 and is_loop:
            dropped.append(c)
            continue
        # Clamp runaway cho concern giữ lại.
        if float(c.get("pressure") or 0.0) > 0.70:
            c["pressure"] = 0.70
        if int(c.get("recurrence") or 0) > 60:
            c["recurrence"] = 60
        kept.append(c)
    data["concerns"] = kept
    backup(p)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"private_concerns.json: {len(concerns)} -> {len(kept)} (xoá {len(dropped)} concern vòng-lặp áp lực)")
    for c in dropped:
        print(f"   - dropped p={float(c.get('pressure') or 0):.2f} rec={c.get('recurrence')} {str(c.get('theme'))[:60]!r}")


def remove_tmp():
    n = 0
    for f in MC.glob("*.tmp"):
        f.unlink()
        n += 1
        print(f"xoá tmp: {f.name}")
    if n == 0:
        print("không có file .tmp")


if __name__ == "__main__":
    clean_thought_stream()
    clean_anchor_journal()
    clean_concerns()
    remove_tmp()
