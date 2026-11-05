#!/usr/bin/env python
"""s01: kiem ke eris_observability.jsonl (chi doc, stream, khong in gia tri).

Chay:
    python -X utf8 s01_inventory_obs.py <out_json>

Chi ghi tong hop: so dong, khoang thoi gian, dem theo ngay (UTC+7), dem theo
(signal,name), tap khoa tags/fields theo name. Khong ghi gia tri truong.
"""
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

SRC = r"C:\Users\Gtvkun\Documents\eris\logs\eris_observability.jsonl"
TZ = timezone(timedelta(hours=7))


def main(out_path: str) -> None:
    total = 0
    bad = 0
    ts_min = None
    ts_max = None
    per_day = Counter()
    per_name = Counter()
    field_keys = defaultdict(set)
    tag_keys = defaultdict(set)
    trace_ids_per_day = defaultdict(set)
    with open(SRC, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            total += 1
            try:
                d = json.loads(line)
            except Exception:
                bad += 1
                continue
            ts = d.get("timestamp")
            if isinstance(ts, (int, float)):
                ts_min = ts if ts_min is None else min(ts_min, ts)
                ts_max = ts if ts_max is None else max(ts_max, ts)
                day = datetime.fromtimestamp(ts, TZ).strftime("%Y-%m-%d")
                per_day[day] += 1
                tid = d.get("trace_id")
                if tid and len(trace_ids_per_day[day]) < 100000:
                    trace_ids_per_day[day].add(tid)
            key = "%s|%s" % (d.get("signal"), d.get("name"))
            per_name[key] += 1
            fl = d.get("fields")
            if isinstance(fl, dict):
                field_keys[key].update(fl.keys())
            tg = d.get("tags")
            if isinstance(tg, dict):
                tag_keys[key].update(tg.keys())
    res = {
        "source": SRC,
        "total_lines": total,
        "json_errors": bad,
        "ts_min": datetime.fromtimestamp(ts_min, TZ).isoformat() if ts_min else None,
        "ts_max": datetime.fromtimestamp(ts_max, TZ).isoformat() if ts_max else None,
        "per_day": dict(sorted(per_day.items())),
        "distinct_trace_ids_per_day": {k: len(v) for k, v in sorted(trace_ids_per_day.items())},
        "per_name": dict(per_name.most_common()),
        "field_keys": {k: sorted(v) for k, v in field_keys.items()},
        "tag_keys": {k: sorted(v) for k, v in tag_keys.items()},
    }
    with open(out_path, "w", encoding="utf-8") as g:
        json.dump(res, g, ensure_ascii=False, indent=1)
    print("ok total=%d bad=%d" % (total, bad))


if __name__ == "__main__":
    main(sys.argv[1])
