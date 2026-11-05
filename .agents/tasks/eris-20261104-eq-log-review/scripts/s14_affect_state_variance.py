#!/usr/bin/env python
"""s14: affective_voice_state trong request Root co thay doi theo cam xuc nguoi dung khong?

Dau vao : <turns_dir>/*.json (s02; truong ctx.affective_voice_state da bi cat ~600 ky tu nhung chua cac so dau)
Dau ra  : JSON tong hop theo session (so lan doi gia tri, tuoi su kien cam xuc). Khong noi dung hoi thoai.

Chay:
    python -X utf8 s14_affect_state_variance.py <turns_dir> <out_json> [lo YYYYMMDD] [hi YYYYMMDD]
"""
import json
import re
import sys
from pathlib import Path

FIELDS = ["valence", "arousal", "curiosity", "social_energy", "attachment", "tenderness", "irritation", "fatigue",
          "delight", "sadness", "anxiety", "playfulness", "yearning", "embarrassment", "restraint"]
RX = {f: re.compile(r'\\?"%s\\?"\s*:\s*(-?[0-9.]+)' % f) for f in FIELDS}
RX_AGE = re.compile(r'\\?"affect_event_age_seconds\\?"\s*:\s*(-?[0-9.]+)')
RX_KIND = re.compile(r'\\?"affect_event_kind\\?"\s*:\s*\\?"([a-z_]+)')
RX_IMP = re.compile(r'\\?"affect_impulse_strength\\?"\s*:\s*(-?[0-9.]+)')


def main():
    turns_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    lo = sys.argv[3] if len(sys.argv) > 3 else "20261018"
    hi = sys.argv[4] if len(sys.argv) > 4 else "20261103"
    res = {}
    for p in sorted(turns_dir.glob("2026*.json")):
        sid = p.stem
        if not (lo <= sid[:8] <= hi):
            continue
        d = json.loads(p.read_text("utf-8"))
        seen_user = set()
        vals = {f: [] for f in FIELDS}
        ages, kinds, imps = [], [], []
        n_req = 0
        n_user = 0
        for e in d["executive"]:
            ctx = (e.get("ctx") or {}).get("affective_voice_state")
            if ctx is None:
                continue
            s = json.dumps(ctx, ensure_ascii=False)
            n_req += 1
            for f in FIELDS:
                m = RX[f].search(s)
                if m:
                    vals[f].append(float(m.group(1)))
            m = RX_AGE.search(s)
            if m:
                ages.append(float(m.group(1)))
            m = RX_KIND.search(s)
            if m:
                kinds.append(m.group(1))
            m = RX_IMP.search(s)
            if m:
                imps.append(float(m.group(1)))
            ev = e.get("event") or {}
            if ev.get("kind") == "user_turn" and ev.get("event_id") not in seen_user:
                seen_user.add(ev.get("event_id"))
                n_user += 1
        if n_req < 3:
            continue
        distinct = {f: len(set(round(v, 4) for v in vs)) for f, vs in vals.items() if vs}
        changed_fields = sum(1 for f, k in distinct.items() if k > 1)
        res[sid] = {
            "n_root_requests": n_req, "n_user_turns": n_user,
            "fields_parsed": len(distinct), "fields_with_any_change": changed_fields,
            "valence_distinct": distinct.get("valence"), "irritation_distinct": distinct.get("irritation"),
            "sadness_distinct": distinct.get("sadness"),
            "valence_range": [min(vals["valence"]), max(vals["valence"])] if vals["valence"] else None,
            "irritation_range": [min(vals["irritation"]), max(vals["irritation"])] if vals["irritation"] else None,
            "event_age_seconds_min": min(ages) if ages else None,
            "event_age_seconds_max": max(ages) if ages else None,
            "event_age_days_min": round(min(ages) / 86400, 1) if ages else None,
            "affect_event_kinds": sorted(set(kinds)),
            "impulse_strength_distinct": len(set(imps)) if imps else None,
        }
    summary = {
        "n_sessions": len(res),
        "sessions_with_all_fields_constant": sum(1 for r in res.values() if r["fields_with_any_change"] == 0),
        "sessions_with_event_age_min_gt_1day": sum(1 for r in res.values() if (r["event_age_seconds_min"] or 0) > 86400),
    }
    out.write_text(json.dumps({"summary": summary, "sessions": res}, ensure_ascii=False, indent=1), "utf-8")
    print("ok", summary)


if __name__ == "__main__":
    main()
