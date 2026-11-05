#!/usr/bin/env python
"""s04: dung transcript doc duoc tu du lieu da ghep (s03) -> TEMP (khong ghi vao task dir).

Chay:
    python -X utf8 s04_render_transcript.py <joined_dir> <out_dir> <sid> [<sid> ...]

Moi dong: [thoi-gian] KIND (n_msgs) latency | USER: ... | ROOT.intent / ROOT.say / SURFACE.text (neu khac)
Thoi gian tre = tu last_msg_local (tin cuoi trong batch) -> public_sent_local (text hien cung audio_start).
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=7))


def dt(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=TZ) if s else None


def main():
    joined, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    for sid in sys.argv[3:]:
        d = json.loads((joined / (sid + ".json")).read_text("utf-8"))
        lines = ["# session %s runlog=%s" % (sid, d["runlog"])]
        handoff_iter = iter(d["handoff"])
        for t in d["turns"]:
            if not t["final"]:
                lines.append("   (intermediate step %s kind=%s event=%s)" % (t["step_index"], t["resp_kind"], t["event_kind"]))
                continue
            ref = t.get("first_msg_local") or t["root_req_local"]
            lat = None
            if t.get("public_sent_local") and t.get("last_msg_local"):
                lat = (dt(t["public_sent_local"]) - dt(t["last_msg_local"])).total_seconds()
            elif t.get("public_sent_local"):
                lat = (dt(t["public_sent_local"]) - dt(t["root_req_local"])).total_seconds()
            hdr = "[%s] %s msgs=%s" % ((t.get("last_msg_local") or t["root_req_local"])[11:19], t["event_kind"], t.get("n_msgs"))
            if lat is not None:
                hdr += " lat_to_public=%.1fs" % lat
            hdr += " resp=%s after=%s ch=%s outcome=%s" % (t["resp_kind"], t.get("after"), t.get("channel"), t.get("outcome"))
            lines.append(hdr)
            if t["event_kind"] == "user_turn":
                lines.append("   USER: " + (t.get("user_text") or ""))
            if t.get("intent"):
                lines.append("   INTENT: " + t["intent"])
            if t.get("say"):
                lines.append("   SAY: " + str(t["say"]))
            if t.get("reason"):
                lines.append("   REASON: " + str(t["reason"]))
            if t.get("delivery_hint"):
                lines.append("   DELIVERY: " + str(t["delivery_hint"]))
            st = t.get("surface_text")
            if st is not None and st != t.get("say"):
                lines.append("   SURFACE(!=say): " + st)
            lines.append("   usage=%s root_ms=%s" % (t.get("usage"), t.get("root_elapsed_ms")))
        (out / (sid + ".txt")).write_text("\n".join(lines), "utf-8")
    print("rendered %d" % len(sys.argv[3:]))


if __name__ == "__main__":
    main()
