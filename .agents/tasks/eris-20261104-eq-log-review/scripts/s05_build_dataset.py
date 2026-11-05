#!/usr/bin/env python
"""s05: dung bang "luot user" va bang "phat ngon Eris" tu du lieu da ghep (s03).

Dau ra chua transcript => chi ghi vao TEMP.

Chay:
    python -X utf8 s05_build_dataset.py <joined_dir> <out_dir> [sid ...]
    (khong dua sid => moi session co user_turn hoac delivery)

Ra:
  <out_dir>/user_turns.jsonl   mot dong / luot user (batch tin) trong 1 session
  <out_dir>/utterances.jsonl   mot dong / loi Eris da phat (chat + autonomous + continuation)
  <out_dir>/session_stats.json thong ke theo session (loi 429, circuit breaker, writer_failed...)
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=7))


def dt(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=TZ) if s else None


def secs(a, b):
    if not a or not b:
        return None
    return round((dt(b) - dt(a)).total_seconds(), 2)


def norm_text(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def load_turns_raw(turns_dir: Path, sid: str):
    p = turns_dir / (sid + ".json")
    return json.loads(p.read_text("utf-8")) if p.exists() else None


def main():
    joined, out = Path(sys.argv[1]), Path(sys.argv[2])
    turns_dir = joined.parent / "turns"
    sids = sys.argv[3:]
    out.mkdir(parents=True, exist_ok=True)
    if not sids:
        sids = sorted(p.stem for p in joined.glob("2026*.json"))
    user_rows, utt_rows, sess_stats = [], [], {}
    for sid in sids:
        d = json.loads((joined / (sid + ".json")).read_text("utf-8"))
        raw = load_turns_raw(turns_dir, sid) or {"executive": [], "surface": []}
        # ---------- phat ngon: ghep text cho tung delivery --------------
        texts = []  # (time_local, text, source)
        for s in raw["surface"]:
            r = s.get("resp") or {}
            if r.get("text"):
                texts.append((s["resp_local"], r["text"], "surface", r))
        for t in d["turns"]:
            if t.get("final") and t.get("resp_kind") == "move" and t.get("say"):
                texts.append((t["root_resp_local"], t["say"], "root_say", None))
            if t.get("final") and t.get("resp_kind") == "prose_recovery" and t.get("say"):
                texts.append((t["root_resp_local"], t["say"], "root_prose", None))
        used = set()
        deliv = [x for x in d["deliveries"] if x.get("sent") and x.get("chars") is not None]
        deliv.sort(key=lambda x: x["sent"])
        for x in deliv:
            cand = None
            for i, (tm, tx, src, rr) in enumerate(texts):
                if i in used:
                    continue
                if tm <= x["sent"] and len(tx) == x["chars"] and (dt(x["sent"]) - dt(tm)).total_seconds() < 300:
                    # uu tien surface
                    if cand is None or (src == "surface" and cand[1][2] != "surface") or tm > cand[1][0]:
                        cand = (i, (tm, tx, src, rr))
            if cand:
                used.add(cand[0])
                x["text"] = cand[1][1]
                x["text_source"] = cand[1][2]
                x["resp_local"] = cand[1][0]
                x["perf"] = (cand[1][3] or {}).get("performance_hint")
            else:
                x["text"] = None
                x["text_source"] = "unmatched"
        # ---------- luot user ---------------------------------------
        by_event = {}
        for e in raw["executive"]:
            ev = e.get("event") or {}
            if ev.get("kind") != "user_turn":
                continue
            b = (ev.get("metadata") or {}).get("user_input_batch") or {}
            key = (ev.get("event_id"), b.get("first_message_at"))
            by_event.setdefault(key, []).append(e)
        batches = []
        for (eid, first_ts), rows in by_event.items():
            ev0 = rows[0].get("event") or {}
            b = (ev0.get("metadata") or {}).get("user_input_batch") or {}
            ts = b.get("message_timestamps") or ([first_ts] if first_ts else [])
            if not ts:
                continue
            batches.append({
                "event_id": eid, "text": ev0.get("text") or "", "n_msgs": b.get("message_count") or 1,
                "t_first": datetime.fromtimestamp(min(ts), TZ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "t_last": datetime.fromtimestamp(max(ts), TZ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "wait_seconds": b.get("wait_seconds"),
                "rows": sorted(rows, key=lambda r: r["req_local"]),
            })
        batches.sort(key=lambda x: x["t_last"])
        # bo batch bi thay the boi batch sau co t_first <= t_last cua batch truoc
        merged = []
        for bt in batches:
            if merged and bt["t_first"] <= merged[-1]["t_last"]:
                merged[-1] = bt
            else:
                merged.append(bt)
        batches = merged
        micro_starts = [m["at"] for m in d["micro"] if m["kind"] == "start"]
        handoff = d["handoff"]
        for i, bt in enumerate(batches):
            t_last = bt["t_last"]
            nxt = batches[i + 1]["t_first"] if i + 1 < len(batches) else None
            rows = bt["rows"]
            finals = [r for r in rows if (r.get("resp_is_json") and (r.get("resp") or {}).get("kind") in ("move", "no_reply"))]
            last_row = rows[-1]
            err_rows = [r for r in rows if r.get("http_status") not in (200, None)]
            rk = None
            fin = finals[-1] if finals else None
            if fin:
                rk = (fin.get("resp") or {}).get("kind")
            # tra loi: delivery kenh chat dau tien sau t_last, truoc batch ke
            reply = None
            for x in deliv:
                if x.get("channel") == "chat" and x["sent"] >= t_last and (nxt is None or x["sent"] < nxt):
                    reply = x
                    break
            if reply is None:
                # co the Root tra loi ma kenh gan nhan khac => lay delivery trigger=user
                for x in deliv:
                    if x.get("trigger") == "user" and x["sent"] >= t_last and (nxt is None or x["sent"] < nxt):
                        reply = x
                        break
            micro = next((m for m in micro_starts if m >= t_last and (dt(m) - dt(t_last)).total_seconds() < 10), None)
            # follow-up: delivery khac (autonomous/continuation) giua reply va batch ke
            follow = []
            if reply:
                for x in deliv:
                    if x is reply:
                        continue
                    if x["sent"] > reply["sent"] and (nxt is None or x["sent"] < nxt) and x.get("channel") != "chat":
                        follow.append({"sent": x["sent"], "chars": x.get("chars"), "channel": x.get("channel"), "text": x.get("text")})
            ho = None
            for h in handoff:
                if h["reason"] == "user_turn" and h["at"] >= t_last and (dt(h["at"]) - dt(t_last)).total_seconds() < 5:
                    ho = h
                    break
            first_req = rows[0]["req_local"]
            root_calls = len(rows)
            root_total_ms = sum(int(r.get("elapsed_ms") or 0) for r in rows)
            surf_ms = None
            if reply and reply.get("resp_local"):
                for s in raw["surface"]:
                    if s["resp_local"] == reply["resp_local"]:
                        surf_ms = s.get("elapsed_ms")
                        break
            user_rows.append({
                "session": sid, "idx": i, "event_id": bt["event_id"], "user_text": bt["text"], "n_msgs": bt["n_msgs"],
                "t_first": bt["t_first"], "t_last": t_last, "wait_seconds": bt["wait_seconds"],
                "root_kind": rk, "root_calls": root_calls, "root_http": [r.get("http_status") for r in rows],
                "root_errors": len(err_rows), "root_total_ms": root_total_ms,
                "root_intent": (fin.get("resp") or {}).get("intent") if fin else None,
                "root_after": (fin.get("resp") or {}).get("after") if fin else None,
                "root_reason": (fin.get("resp") or {}).get("reason") if fin else None,
                "first_root_req": first_req,
                "reply": reply and {k: reply.get(k) for k in ("id", "channel", "trigger", "sent", "chars", "text", "text_source", "tts", "outcome", "goal", "audio_start_live2d", "audio_done_live2d")},
                "reply_prompt_tokens": (fin.get("usage") or {}).get("prompt") if fin else None,
                "latency_s": secs(t_last, reply["sent"]) if reply else None,
                "pre_root_s": secs(t_last, first_req),
                "micro_ack_s": secs(t_last, micro) if micro else None,
                "surface_ms": surf_ms,
                "followups": follow,
                "handoff": ho,
                "next_user_after_s": secs(t_last, nxt) if nxt else None,
            })
        # ---------- phat ngon ----------------------------------------
        user_times = [b["t_last"] for b in batches]
        for x in deliv:
            utt_rows.append({
                "session": sid, "id": x["id"], "channel": x.get("channel"), "trigger": x.get("trigger"), "sent": x["sent"],
                "chars": x.get("chars"), "text": x.get("text"), "text_source": x.get("text_source"), "tts": x.get("tts"),
                "outcome": x.get("outcome"), "goal": x.get("goal"), "perf": x.get("perf"),
            })
        # ---------- thong ke loi theo session -------------------------
        cats = {"http_429": 0, "http_401": 0, "circuit_breaker": 0, "writer_failed": 0, "no_public_commit": 0,
                "observer_failed": 0, "curator_deferred": 0, "fallback_chain": 0, "contract_repair": 0, "other_warn": 0}
        for l in d["lines"]:
            m = l["msg"]
            if "429" in m and "Too Many" in m:
                cats["http_429"] += 1
            elif "401" in m and "Unauthorized" in m:
                cats["http_401"] += 1
            elif "circuit breaker" in m:
                cats["circuit_breaker"] += 1
            elif "writer_failed" in m:
                cats["writer_failed"] += 1
            elif "no_public_commit" in m:
                cats["no_public_commit"] += 1
            elif "post observer] failed" in m or "[observer] inference_failed" in m:
                cats["observer_failed"] += 1
            elif "curator_deferred" in m:
                cats["curator_deferred"] += 1
            elif "FALLBACK CHAIN" in m:
                cats["fallback_chain"] += 1
            elif "contract-repair" in m:
                cats["contract_repair"] += 1
            elif l["level"] in ("WARNING", "ERROR", "CRITICAL"):
                cats["other_warn"] += 1
        sess_stats[sid] = {"runlog": d["runlog"], "n_user_batches": len(batches), "n_deliveries": len(deliv), "warn_cats": cats}
    with (out / "user_turns.jsonl").open("w", encoding="utf-8") as f:
        for r in user_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (out / "utterances.jsonl").open("w", encoding="utf-8") as f:
        for r in utt_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / "session_stats.json").write_text(json.dumps(sess_stats, ensure_ascii=False, indent=1), "utf-8")
    print("user_turns=%d utterances=%d sessions=%d" % (len(user_rows), len(utt_rows), len(sess_stats)))


if __name__ == "__main__":
    main()
