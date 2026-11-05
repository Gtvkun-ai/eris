#!/usr/bin/env python
"""s03: ghep luot Root/Surface (tu s02) voi run log text -> TEMP.

Dau ra chua TRANSCRIPT THO => chi ghi vao TEMP.

Chay:
    python -X utf8 s03_join_turns.py <turns_dir> <joined_dir>

Voi moi session co file <turns_dir>/<sid>.json va run log tuong ung
(C:/Users/Gtvkun/Documents/eris/logs/eris_run_<sid_gan_nhat>.txt) xuat
<joined_dir>/<sid>.json gom:
  turns: moi buoc quyet dinh cuoi cua Root (move / no_reply) cho moi su kien
  deliveries: thoi diem public-text sent, audio start/done, micro receipt
  loglines: cac dong WARNING/ERROR va cac marker (fallback, contract-repair...)
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=7))
LOGS = Path(r"C:\Users\Gtvkun\Documents\eris\logs")

LINE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3}) (.*)$")
HDR = re.compile(r"Bat dau\s*:\s*(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})")
RE_SENT = re.compile(r"\[public-text\] sent turn=(\S+) reason=(\w+) chars=(\d+)")
RE_ASTART = re.compile(r"recv=audio_playback_started turn=(\S+)")
RE_ADONE = re.compile(r"recv=audio_playback_done turn=(\S+)")
RE_TRACE = re.compile(
    r"\[public trace\] trace=(\S+) channel=(\w+) semantic=(\w+) trigger=(\w+) goal=(.*?) proposal=(\S+) "
    r"authority=(\S+) nervous=(.*?) commit=(\d) tts=(\S+) outcome=(\S+)")
RE_ROOTAGENT = re.compile(r"\[root-agent\] step=(\d+) event_kind=(\w+) action=(\w+)")
RE_ROOTINPUT = re.compile(r"\[root-input\] messages=(\d+) wait_seconds=([\d.]+) revision=(\d+)")
RE_EVID = re.compile(r"\[chat-stage\] evidence_ms=(\d+) memory_recall_ms=(\d+)")
RE_CTX = re.compile(r"\[chat-stage\] context_ms=(\d+) memory_context_ms=(\d+)")
RE_HANDOFF = re.compile(r"\[conversation handoff v12\] reason=(\w+) rev=(\d+) stance=(\S+) repair=(\d) self_cause=([\d.]+)")
RE_TRAJ = re.compile(r"\[conversation trajectory v76\] reason=(\w+) rev=(\d+) topic=(\S+) depth=(\d+) momentum=([\d.]+) energy=([\d.]+) life=(\S+) pub=(\d+) priv=(\d+) mode=(\w+) awaiting=(\d) focus=(.*)$")
RE_OBS = re.compile(r"\[post observer\] turn=(\d+) status=(\w+) act=(.*?) meaning=(.*?) conf=([\d.]+) repair=(\w+) traits=(\d+) frame=(\S+) strategy=(\S+) source=(\S+) latency=(\d+)ms")
RE_WRITER = re.compile(r"\[character-v03\] writer_candidate run=(\S+) generation=(\d+) attempt=(\S+) stage=(\w+) status=(\w+) code=(\S+) duration_ms=(\d+)")
RE_LVL = re.compile(r"\]\[(WARNING|ERROR|CRITICAL)\] (.*)$")
RE_ENTER = re.compile(r"Entered chat mode; pending user input")
RE_MICRO = re.compile(r"turn=micro:receipt:(\d+)")
RE_PREEMPT = re.compile(r"(preempt|interrupt|cancel|stale|discard|superseded)", re.I)
RE_FALLBACK = re.compile(r"(fallback|writer_failed|prepare[_ ]reject|localizer|contract-repair|degraded|filler)", re.I)


def find_runlog(sid: str):
    """Tim run log co gio bat dau gan sid (sai lech <= 10 giay)."""
    want = datetime.strptime(sid, "%Y%m%d_%H%M%S")
    best = None
    for p in LOGS.glob("eris_run_*.txt"):
        m = re.match(r"eris_run_(\d{8}_\d{6})\.txt", p.name)
        if not m:
            continue
        t = datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
        d = abs((t - want).total_seconds())
        if d <= 20 and (best is None or d < best[0]):
            best = (d, p)
    return best[1] if best else None


def parse_runlog(path: Path):
    text = path.read_text("utf-8", errors="replace").splitlines()
    base = None
    for ln in text[:12]:
        m = HDR.search(ln)
        if m:
            base = datetime(*map(int, m.groups()), tzinfo=TZ)
            break
    if base is None:
        raise ValueError("no header date " + str(path))
    day = base.replace(hour=0, minute=0, second=0, microsecond=0)
    last_tod = -1.0
    ev = []
    for ln in text:
        m = LINE.match(ln)
        if not m:
            continue
        hh, mm, ss, ms, rest = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5)
        tod = hh * 3600 + mm * 60 + ss + ms / 1000
        if tod + 600 < last_tod:  # sang ngay moi
            day = day + timedelta(days=1)
        last_tod = max(last_tod, tod) if tod >= last_tod - 600 else tod
        t = day + timedelta(hours=hh, minutes=mm, seconds=ss, milliseconds=ms)
        ev.append((t, rest))
    return base, ev


def iso(t):
    return t.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] if t else None


def to_dt(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=TZ) if s else None


def build(sid: str, turns_dir: Path, out_dir: Path):
    sess = json.loads((turns_dir / (sid + ".json")).read_text("utf-8"))
    rl = find_runlog(sid)
    deliveries, micro, lines = {}, [], []
    stage = []  # evidence/context timings theo thoi gian
    handoff, traj, obs, writer, enters, rootinput = [], [], [], [], [], []
    if rl:
        base, ev = parse_runlog(rl)
        for t, rest in ev:
            m = RE_SENT.search(rest)
            if m:
                d = deliveries.setdefault(m.group(1), {})
                d.update(sent=iso(t), sent_reason=m.group(2), chars=int(m.group(3)))
            m = RE_TRACE.search(rest)
            if m:
                d = deliveries.setdefault(m.group(1), {})
                d.update(trace_at=iso(t), channel=m.group(2), semantic=m.group(3), trigger=m.group(4),
                         goal=m.group(5), tts=m.group(10), outcome=m.group(11), commit=int(m.group(9)))
            m = RE_ASTART.search(rest)
            if m:
                tid = m.group(1)
                if tid.startswith("micro:receipt"):
                    micro.append({"at": iso(t), "turn": tid, "kind": "start"})
                else:
                    deliveries.setdefault(tid, {}).setdefault("audio_start", iso(t))
                    # live2d cat turn id => khop theo tien to
                    for k, d in deliveries.items():
                        if k.startswith(tid) or tid.startswith(k[:30]):
                            d.setdefault("audio_start_live2d", iso(t))
            m = RE_ADONE.search(rest)
            if m:
                tid = m.group(1)
                if tid.startswith("micro:receipt"):
                    micro.append({"at": iso(t), "turn": tid, "kind": "done"})
                else:
                    for k, d in deliveries.items():
                        if k.startswith(tid) or tid.startswith(k[:30]):
                            d.setdefault("audio_done_live2d", iso(t))
            m = RE_EVID.search(rest)
            if m:
                stage.append({"at": iso(t), "evidence_ms": int(m.group(1)), "memory_recall_ms": int(m.group(2))})
            m = RE_CTX.search(rest)
            if m:
                stage.append({"at": iso(t), "context_ms": int(m.group(1)), "memory_context_ms": int(m.group(2))})
            m = RE_HANDOFF.search(rest)
            if m:
                handoff.append({"at": iso(t), "reason": m.group(1), "stance": m.group(3), "repair": int(m.group(4)), "self_cause": float(m.group(5))})
            m = RE_TRAJ.search(rest)
            if m:
                traj.append({"at": iso(t), "reason": m.group(1), "mode": m.group(10), "energy": float(m.group(6)), "momentum": float(m.group(5)), "focus": m.group(12)[:300]})
            m = RE_OBS.search(rest)
            if m:
                obs.append({"at": iso(t), "turn": int(m.group(1)), "status": m.group(2), "act": m.group(3), "meaning": m.group(4), "conf": float(m.group(5)), "repair": m.group(6), "frame": m.group(8), "strategy": m.group(9), "latency_ms": int(m.group(11))})
            m = RE_WRITER.search(rest)
            if m:
                writer.append({"at": iso(t), "status": m.group(5), "code": m.group(6), "duration_ms": int(m.group(7))})
            m = RE_ROOTINPUT.search(rest)
            if m:
                rootinput.append({"at": iso(t), "messages": int(m.group(1)), "wait_seconds": float(m.group(2)), "revision": int(m.group(3))})
            if RE_ENTER.search(rest):
                enters.append(iso(t))
            m = RE_LVL.search(rest)
            if m:
                lines.append({"at": iso(t), "level": m.group(1), "msg": m.group(2)[:240]})
            elif RE_FALLBACK.search(rest) and "[Loop]" in rest and "writer_candidate" not in rest:
                lines.append({"at": iso(t), "level": "NOTE", "msg": rest[:240]})
    # Root decisions
    turns = []
    n = 0
    for e in sess["executive"]:
        evt = e.get("event") or {}
        kind = evt.get("kind")
        resp = e.get("resp") or {}
        rk = resp.get("kind")
        if kind is None:
            continue
        final = rk in ("move", "no_reply") or (not e.get("resp_is_json") and bool(resp.get("_raw")))
        meta = evt.get("metadata") or {}
        batch = meta.get("user_input_batch") or {}
        first_ts = batch.get("first_message_at")
        last_ts = batch.get("last_message_at")
        row = {
            "session": sid, "event_kind": kind, "event_id": evt.get("event_id"), "step_index": e.get("step_index"),
            "final": final, "resp_kind": rk if e.get("resp_is_json") else "prose_recovery",
            "user_text": evt.get("text") if kind == "user_turn" else None,
            "n_msgs": batch.get("message_count"), "wait_seconds": batch.get("wait_seconds"),
            "msg_ts": batch.get("message_timestamps"),
            "first_msg_local": iso(datetime.fromtimestamp(first_ts, TZ)) if first_ts else None,
            "last_msg_local": iso(datetime.fromtimestamp(last_ts, TZ)) if last_ts else None,
            "root_req_local": e.get("req_local"), "root_resp_local": e.get("resp_local"),
            "root_elapsed_ms": e.get("elapsed_ms"), "usage": e.get("usage"), "opts": e.get("opts"),
            "reasoning_len": e.get("reasoning_len"), "reasoning_head": e.get("reasoning_head"),
            "intent": resp.get("intent"), "say": resp.get("say") if e.get("resp_is_json") else resp.get("_raw"),
            "delivery_hint": resp.get("delivery"), "after": resp.get("after"), "reason": resp.get("reason"),
            "meta_keys": sorted(meta.keys()) if isinstance(meta, dict) else None,
            "meta_small": {k: v for k, v in meta.items() if k in ("reason", "chat_mode", "open_loop_count", "has_recent_history", "seconds_since_user", "seconds_since_assistant", "source", "channel")},
            "ctx": e.get("ctx"),
        }
        turns.append(row)
    # surface -> gan voi Root move truoc do (theo thoi gian)
    surf = sorted(sess["surface"], key=lambda s: s.get("req_local") or "")
    moves = [t for t in turns if t["final"] and t["resp_kind"] in ("move", "prose_recovery")]
    moves.sort(key=lambda t: t["root_resp_local"])
    used = set()
    for s in surf:
        sreq = s.get("req_local")
        cand = None
        for mv in moves:
            if id(mv) in used:
                continue
            if mv["root_resp_local"] <= (s.get("req_local") or "") and (cand is None or mv["root_resp_local"] > cand["root_resp_local"]):
                # lay move gan nhat truoc surface request, chua duoc ghep
                cand = mv
        if cand is not None:
            used.add(id(cand))
            r = s.get("resp") or {}
            cand["surface_text"] = r.get("text")
            cand["surface_speech_text_present"] = bool(r.get("speech_text"))
            cand["surface_perf_hint"] = r.get("performance_hint")
            cand["surface_elapsed_ms"] = s.get("elapsed_ms")
            cand["surface_resp_local"] = s.get("resp_local")
            cand["surface_lang"] = [r.get("display_language"), r.get("speech_language")]
            cand["surface_should_speak"] = r.get("should_speak")
    # gan delivery: theo intent == goal (uu tien), sau do theo chars
    dl = []
    for k, d in deliveries.items():
        dd = dict(d)
        dd["id"] = k
        dl.append(dd)
    dl.sort(key=lambda d: d.get("sent") or d.get("trace_at") or "")
    for mv in moves:
        intent = (mv.get("intent") or "").strip()
        best = None
        for d in dl:
            if d.get("matched"):
                continue
            ref = d.get("sent") or d.get("trace_at")
            if not ref or ref < mv["root_resp_local"]:
                continue
            g = (d.get("goal") or "").strip()
            if intent and g and (g == intent or g.startswith(intent[:50]) or intent.startswith(g[:50])):
                best = d
                break
        if best is None:
            txt = mv.get("surface_text") or mv.get("say") or ""
            for d in dl:
                if d.get("matched"):
                    continue
                ref = d.get("sent") or d.get("trace_at")
                if not ref or ref < mv["root_resp_local"]:
                    continue
                if d.get("chars") == len(txt) and d.get("sent"):
                    delta = (to_dt(ref) - to_dt(mv["root_resp_local"])).total_seconds()
                    if delta < 240:
                        best = d
                        break
        if best is not None:
            best["matched"] = True
            mv["delivery_id"] = best["id"]
            mv["channel"] = best.get("channel")
            mv["public_sent_local"] = best.get("sent")
            mv["audio_start_local"] = best.get("audio_start_live2d") or best.get("audio_start")
            mv["audio_done_local"] = best.get("audio_done_live2d")
            mv["tts"] = best.get("tts")
            mv["outcome"] = best.get("outcome")
            mv["chars_sent"] = best.get("chars")
    out = {
        "session": sid, "runlog": rl.name if rl else None, "turns": turns,
        "deliveries": dl, "micro": micro, "stage": stage, "handoff": handoff, "trajectory": traj,
        "observer": obs, "writer": writer, "enters": enters, "rootinput": rootinput, "lines": lines,
        "observer_wire": sess.get("observer"),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / (sid + ".json")).write_text(json.dumps(out, ensure_ascii=False), "utf-8")
    finals = [t for t in turns if t["final"]]
    return {"session": sid, "runlog": rl.name if rl else None, "turns": len(turns), "finals": len(finals),
            "user_turn_finals": sum(1 for t in finals if t["event_kind"] == "user_turn"),
            "delivered_moves": sum(1 for t in moves if t.get("delivery_id")), "moves": len(moves),
            "deliveries": len(dl)}


def main():
    turns_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    summ = []
    for p in sorted(turns_dir.glob("2026*.json")):
        sid = p.stem
        try:
            summ.append(build(sid, turns_dir, out_dir))
        except Exception as e:  # noqa: BLE001
            summ.append({"session": sid, "fatal": repr(e)[:300]})
    (out_dir / "_join_summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), "utf-8")
    print("joined %d" % len(summ))


if __name__ == "__main__":
    main()
