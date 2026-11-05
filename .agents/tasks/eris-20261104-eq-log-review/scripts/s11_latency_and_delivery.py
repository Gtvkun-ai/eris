#!/usr/bin/env python
"""s11: do tre va ket qua giao cho cac luot user (tong hop; khong chua noi dung).

Dau vao : <ds_dir>/user_turns.jsonl  (do s05 tao, nam trong TEMP)
Dau ra  : JSON tong hop

Dinh nghia:
  latency_s   = t_last (tin cuoi trong batch) -> thoi diem text duoc gui cung audio_start
                (public-text sent). Vi chu truong 'text cho voice', day la thoi diem nguoi dung THAY chu.
  pre_root_s  = t_last -> request Root dau tien (evidence/context/hang doi truoc Root)
  micro_ack_s = t_last -> micro:receipt (am 'ừm' ngan) neu co trong 10 giay
  unanswered  = khong co delivery kenh chat/trigger user truoc batch ke tiep
Chay:
    python -X utf8 s11_latency_and_delivery.py <ds_dir> <out_json>
"""
import json
import statistics
import sys
from pathlib import Path

SCOPES = {
    "A_2026-11-01..03": ("20261101", "20261103"),
    "B_2026-10-27..31": ("20261027", "20261031"),
}


def pct(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    return round(s[max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))], 1)


def stats(vals):
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "mean": round(statistics.mean(vals), 1), "median": pct(vals, 0.5), "p90": pct(vals, 0.9),
            "min": round(min(vals), 1), "max": round(max(vals), 1),
            "share_gt_30s": round(sum(1 for v in vals if v > 30) / len(vals), 3),
            "share_gt_60s": round(sum(1 for v in vals if v > 60) / len(vals), 3),
            "n_gt_60s": sum(1 for v in vals if v > 60), "n_gt_120s": sum(1 for v in vals if v > 120)}


def main():
    ds, out = Path(sys.argv[1]), Path(sys.argv[2])
    rows = [json.loads(l) for l in (ds / "user_turns.jsonl").read_text("utf-8").splitlines() if l.strip()]
    res = {}
    for scope, (lo, hi) in SCOPES.items():
        rs = [r for r in rows if lo <= r["session"][:8] <= hi]
        lat = [r["latency_s"] for r in rs if r.get("latency_s") is not None]
        pre = [r["pre_root_s"] for r in rs if r.get("pre_root_s") is not None]
        micro = [r["micro_ack_s"] for r in rs if r.get("micro_ack_s") is not None]
        root_ms = [r["root_total_ms"] / 1000 for r in rs if r.get("root_total_ms")]
        surf_ms = [r["surface_ms"] / 1000 for r in rs if r.get("surface_ms")]
        unanswered = [r for r in rs if not r.get("reply")]
        errs = [r for r in rs if r.get("root_errors")]
        noreply_decision = [r for r in rs if r.get("root_kind") == "no_reply"]
        followups = [len(r.get("followups") or []) for r in rs if r.get("reply")]
        res[scope] = {
            "n_user_batches": len(rs),
            "sessions": sorted({r["session"] for r in rs}),
            "latency_to_visible_text_s": stats(lat),
            "pre_root_wait_s": stats(pre),
            "root_http_total_s": stats(root_ms),
            "surface_http_s": stats(surf_ms),
            "micro_ack_s": stats(micro),
            "n_with_micro_ack": len(micro),
            "n_unanswered_no_delivery": len(unanswered),
            "n_root_http_error_in_turn": len(errs),
            "n_root_decided_no_reply": len(noreply_decision),
            "n_multi_message_batches": sum(1 for r in rs if (r.get("n_msgs") or 1) > 1),
            "followup_messages_after_reply": {
                "n_replies": len(followups), "total_followups": sum(followups),
                "replies_with_>=1_followup": sum(1 for f in followups if f >= 1),
                "replies_with_>=2_followups": sum(1 for f in followups if f >= 2),
                "max_followups": max(followups) if followups else 0,
            },
            "slowest_5": sorted(
                [{"session": r["session"], "idx": r["idx"], "latency_s": r["latency_s"], "pre_root_s": r["pre_root_s"]}
                 for r in rs if r.get("latency_s") is not None],
                key=lambda x: -x["latency_s"])[:5],
        }
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
    print("ok")


if __name__ == "__main__":
    main()
