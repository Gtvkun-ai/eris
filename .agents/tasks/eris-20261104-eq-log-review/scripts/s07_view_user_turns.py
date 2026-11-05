#!/usr/bin/env python
"""s07: in cac luot user_turn (final) cua cac session -> TEMP (khong ghi vao task dir).

Dung cho cac session truoc 27/10 (chua co metadata user_input_batch nen s05 bo qua).

Chay:
    python -X utf8 s07_view_user_turns.py <joined_dir> <out_txt> <sid> [<sid> ...]
"""
import json
import sys
from pathlib import Path


def main():
    joined, out = Path(sys.argv[1]), Path(sys.argv[2])
    lines = []
    for sid in sys.argv[3:]:
        d = json.loads((joined / (sid + ".json")).read_text("utf-8"))
        lines.append("# %s" % sid)
        i = 0
        for t in d["turns"]:
            if t["event_kind"] != "user_turn" or not t["final"]:
                continue
            txt = t.get("surface_text") or t.get("say") or t.get("reason") or "(none)"
            lines.append("[%d] %s kind=%s outcome=%s ch=%s" % (i, (t.get("last_msg_local") or t["root_req_local"])[11:19], t["resp_kind"], t.get("outcome"), t.get("channel")))
            lines.append("   U: " + (t.get("user_text") or ""))
            lines.append("   E: " + str(txt))
            i += 1
    out.write_text("\n".join(lines), "utf-8")
    print("ok")


if __name__ == "__main__":
    main()
