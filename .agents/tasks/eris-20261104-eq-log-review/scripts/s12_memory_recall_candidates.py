#!/usr/bin/env python
"""s12: liet ke cac phat ngon Eris co dau hieu NHAC LAI thong tin cu (heuristic regex) -> TEMP.

Dau ra chua transcript => chi ghi vao TEMP. Cac muc duoc phan loai TAY o buoc sau.

Chay:
    python -X utf8 s12_memory_recall_candidates.py <joined_dir> <out_txt> <lo YYYYMMDD> <hi YYYYMMDD>
"""
import json
import re
import sys
from pathlib import Path

CUES = re.compile(
    r"(hôm qua|tối qua|lúc nãy|vừa rồi|lần trước|mấy hôm|hôm nọ|lúc trước|phiên (?:vừa|trước)|trước (?:khi|cú) restart|"
    r"anh (?:từng|đã) (?:nói|bảo|kể)|bạn (?:từng|đã) (?:nói|bảo|kể)|tôi nhớ|nhớ (?:anh|bạn)|như anh (?:nói|bảo)|"
    r"hỏi trễ|chuyện cũ|lâu rồi|đang (?:mở|ngồi|xem|dùng|làm)\b|vẫn (?:đang )?(?:ngồi|mở|kẹt)|mấy chục lượt|"
    r"council|Gemini|Kiro|PokeMMO|Brave|Antigravity|IDE|tab |cửa sổ)", re.I)


def main():
    joined, out = Path(sys.argv[1]), Path(sys.argv[2])
    lo, hi = sys.argv[3], sys.argv[4]
    lines = []
    n = 0
    for p in sorted(joined.glob("2026*.json")):
        sid = p.stem
        if not (lo <= sid[:8] <= hi):
            continue
        d = json.loads(p.read_text("utf-8"))
        for t in d["turns"]:
            if not t["final"] or t["resp_kind"] not in ("move", "prose_recovery"):
                continue
            txt = t.get("surface_text") or t.get("say") or ""
            m = CUES.findall(txt)
            if m:
                n += 1
                lines.append("[%s %s %s outcome=%s] cues=%s" % (sid, (t.get("last_msg_local") or t["root_req_local"])[11:19], t["event_kind"], t.get("outcome"), sorted(set(x.lower() for x in m))[:6]))
                lines.append("    " + txt[:420])
    out.write_text("\n".join(lines), "utf-8")
    print("n=", n)


if __name__ == "__main__":
    main()
