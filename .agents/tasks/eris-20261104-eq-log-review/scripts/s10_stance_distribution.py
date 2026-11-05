#!/usr/bin/env python
"""s10: phan bo nhan stance cua ConversationHandoff (heuristic tu khoa) tren cac luot user.

Nguon: dong log '[conversation handoff v12] reason=user_turn ... stance=...' (da parse o s03).
Khong chua noi dung hoi thoai.

Chay:
    python -X utf8 s10_stance_distribution.py <joined_dir> <out_json>
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main():
    joined, out = Path(sys.argv[1]), Path(sys.argv[2])
    by_scope = defaultdict(Counter)
    repair = defaultdict(Counter)
    selfc = defaultdict(list)
    for p in sorted(joined.glob("2026*.json")):
        sid = p.stem
        if sid < "20261011":
            continue
        scope = "A_2026-11-01..03" if "20261101" <= sid[:8] <= "20261103" else ("B_2026-10-11..31" if sid[:8] <= "20261031" else "other")
        d = json.loads(p.read_text("utf-8"))
        for h in d["handoff"]:
            if h["reason"] != "user_turn":
                continue
            by_scope[scope][h["stance"]] += 1
            repair[scope][h["repair"]] += 1
            selfc[scope].append(h["self_cause"])
    res = {}
    for k in by_scope:
        n = sum(by_scope[k].values())
        res[k] = {"n_user_turn_handoffs": n, "stance": dict(by_scope[k].most_common()),
                  "repair_needed": {str(a): b for a, b in repair[k].items()},
                  "self_cause_nonzero": sum(1 for x in selfc[k] if x > 0)}
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
    print("ok")


if __name__ == "__main__":
    main()
