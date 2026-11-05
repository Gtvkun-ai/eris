#!/usr/bin/env python
"""s13: do da dang bieu cam / giong doc: Root.delivery va Surface.performance_hint.

Dau vao : <turns_dir>/*.json (s02), chua transcript => TEMP
Dau ra  : JSON tong hop (chi dem; khong chua noi dung hoi thoai ngoai nhan hint ngan)

Chay:
    python -X utf8 s13_delivery_variety.py <turns_dir> <out_json>
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

SCOPES = {"A_2026-11-01..03": ("20261101", "20261103"), "B_2026-10-24..31": ("20261024", "20261031")}
KHO = re.compile(r"\bkhô\b", re.I)
TRU = re.compile(r"(trêu|tự giễu|tự trào|giễu)", re.I)
WARM = re.compile(r"(ấm|mềm|nhẹ nhàng|dịu|đồng cảm|an ủi|lắng nghe)", re.I)


def main():
    turns_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    res = {}
    for scope, (lo, hi) in SCOPES.items():
        hints, intens, cues = Counter(), [], 0
        n_surface = 0
        deliv = []
        for p in sorted(turns_dir.glob("2026*.json")):
            sid = p.stem
            if not (lo <= sid[:8] <= hi):
                continue
            d = json.loads(p.read_text("utf-8"))
            for s in d["surface"]:
                r = s.get("resp") or {}
                if not r.get("text"):
                    continue
                n_surface += 1
                hints[str(r.get("performance_hint") or "none")] += 1
                if isinstance(r.get("performance_intensity"), (int, float)):
                    intens.append(float(r["performance_intensity"]))
                if r.get("nonverbal_cue"):
                    cues += 1
            for e in d["executive"]:
                r = e.get("resp") or {}
                if r.get("kind") == "move" and r.get("delivery"):
                    deliv.append(str(r["delivery"]))
        nd = len(deliv)
        res[scope] = {
            "n_surface_texts": n_surface,
            "performance_hint_counts": dict(hints.most_common()),
            "performance_intensity": {"n": len(intens), "min": min(intens) if intens else None, "max": max(intens) if intens else None,
                                      "mean": round(sum(intens) / len(intens), 3) if intens else None},
            "n_with_nonverbal_cue": cues,
            "n_root_delivery_strings": nd,
            "share_delivery_contains_kho": round(sum(1 for x in deliv if KHO.search(x)) / nd, 3) if nd else None,
            "share_delivery_contains_treu_or_giễu": round(sum(1 for x in deliv if TRU.search(x)) / nd, 3) if nd else None,
            "share_delivery_contains_warm_terms": round(sum(1 for x in deliv if WARM.search(x)) / nd, 3) if nd else None,
        }
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
    print("ok")


if __name__ == "__main__":
    main()
