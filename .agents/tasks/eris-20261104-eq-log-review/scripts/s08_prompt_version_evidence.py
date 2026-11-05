#!/usr/bin/env python
"""s08: bang chung phien ban tu CHINH system prompt Root da gui len model (raw wire).

Voi moi session: lay request Root dau tien, doi chieu system prompt voi cac marker:
  - EXP_MARK: cau chi co trong ROOT_SYSTEM_CORE cua nang cap EQ 04/11
              ("identity.strategies[*].experiences")
  - GUIDE_MARK: "read_tool_guide" (tool guides, ~30/10-02/11)
  - BATCH_MARK: "kind=batch"
va do kich thuoc message (system, Self bootstrap, event cuoi). Khong ghi noi dung.

Chay:
    python -X utf8 s08_prompt_version_evidence.py <out_json> [sid_prefix ...]
"""
import gzip
import hashlib
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(r"C:\eris_debug\deepseek_raw")
TZ = timezone(timedelta(hours=7))
MARKS = {
    "EXP_MARK(eq-0411)": "identity.strategies[*].experiences",
    "GUIDE_MARK(read_tool_guide)": "read_tool_guide",
    "BATCH_MARK(kind=batch)": "kind=batch",
    "INTERACTION_CHOICE_PROMPT(eq-0411,off)": "interaction_choice",
    "ghi_so_confusion_rule": "confusion_signal",
}


def restore(m):
    parts = []
    for d in m["chunks"]:
        p = gzip.decompress((BASE / "objects" / d[:2] / (d + ".gz")).read_bytes())
        if hashlib.sha256(p).hexdigest() != d:
            raise ValueError("chunk")
        parts.append(p)
    data = b"".join(parts)
    if hashlib.sha256(data).hexdigest() != m["sha256"]:
        raise ValueError("payload")
    return data


def main():
    out = Path(sys.argv[1])
    prefixes = sys.argv[2:]
    res = []
    for p in sorted(BASE.glob("events_2026*T*Z_pid*.jsonl")):
        if p.name.startswith("events_gateway") or p.name < "events_20261011":
            continue
        m = re.match(r"events_(\d{8}T\d{6}Z)_pid(\d+)\.jsonl", p.name)
        start = datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(TZ)
        sid = start.strftime("%Y%m%d_%H%M%S")
        if prefixes and not any(sid.startswith(x) for x in prefixes):
            continue
        row = None
        for line in p.read_text("utf-8").splitlines():
            r = json.loads(line)
            if r.get("event") == "request" and r.get("worker_role") == "executive":
                try:
                    body = json.loads(restore(r["raw_request_ref"]))
                except Exception as e:  # noqa: BLE001
                    row = {"sid": sid, "err": repr(e)[:80]}
                    break
                msgs = body.get("messages") or []
                system = msgs[0]["content"] if msgs and msgs[0].get("role") == "system" else ""
                sys_hash = hashlib.sha256(system.encode("utf-8")).hexdigest()[:12]
                row = {
                    "sid": sid, "first_req_local": start.strftime("%H:%M:%S"),
                    "system_chars": len(system), "system_sha12": sys_hash,
                    "n_messages": len(msgs), "lens": [len(m_["content"]) if isinstance(m_.get("content"), str) else None for m_ in msgs[:6]],
                    "marks": {k: (v in system) for k, v in MARKS.items()},
                    "opts": {k: body.get(k) for k in ("thinking", "reasoning_effort", "max_tokens")},
                }
                break
        if row:
            res.append(row)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
    print("sessions", len(res))


if __name__ == "__main__":
    main()
