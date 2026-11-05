#!/usr/bin/env python
"""s02: khoi phuc luot hoi thoai tu raw wire (C:/eris_debug/deepseek_raw) -> TEMP.

CHI DOC raw wire. Dau ra la TRANSCRIPT THO nen CHI duoc ghi vao thu muc TEMP,
khong bao gio ghi vao thu muc task (nam trong git).

Chay:
    python -X utf8 s02_extract_turns.py <out_dir_in_TEMP> [events_file_name ...]
    (khong dua ten file => xu ly moi events_2026*T*Z_pid*.jsonl tu 2026-10-11)

Moi session -> <out_dir>/<session_local_start>.json gom:
  executive: [{req_id, at_utc, event{kind,event_id,text,metadata}, step_index,
               tool_results_n, ctx{...chon loc...}, resp{kind,intent,say,delivery,
               after,reason}, usage, elapsed_ms, reasoning_len, reasoning_head}]
  surface:   [{req_id, at_utc, text, speech_text, display_language, speech_language,
               performance_hint, elapsed_ms, usage}]
  observer:  [{req_id, at_utc, parsed(selected), elapsed_ms}]
Khong ghi Self, khong ghi system prompt.
"""
import gzip
import hashlib
import json
import re
import sys
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(r"C:\eris_debug\deepseek_raw")
TZ = timezone(timedelta(hours=7))
_CACHE = OrderedDict()
_CACHE_MAX = 400

CTX_KEYS = (
    "conversation_status", "discourse_context", "engagement_context",
    "affective_voice_state", "open_loop_hints", "user_addressing_context",
    "interrupt_context", "language_hint", "speech_language_hint",
)


def _chunk(digest: str) -> bytes:
    if digest in _CACHE:
        _CACHE.move_to_end(digest)
        return _CACHE[digest]
    piece = gzip.decompress((BASE / "objects" / digest[:2] / (digest + ".gz")).read_bytes())
    if hashlib.sha256(piece).hexdigest() != digest:
        raise ValueError("chunk checksum mismatch " + digest)
    _CACHE[digest] = piece
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return piece


def restore(manifest: dict) -> bytes:
    data = b"".join(_chunk(d) for d in manifest["chunks"])
    if len(data) != manifest["byte_length"]:
        raise ValueError("length mismatch")
    if hashlib.sha256(data).hexdigest() != manifest["sha256"]:
        raise ValueError("payload checksum mismatch")
    return data


def local(at_utc: str) -> str:
    return datetime.fromisoformat(at_utc).astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def parse_json_loose(s):
    if not isinstance(s, str):
        return None
    try:
        return json.loads(s)
    except Exception:
        pass
    m = re.search(r"\{.*\}", s, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def shrink(v, limit=600):
    s = json.dumps(v, ensure_ascii=False)
    return v if len(s) <= limit else {"_truncated": s[:limit]}


def process(name: str, out_dir: Path) -> dict:
    rows = [json.loads(l) for l in (BASE / name).read_text("utf-8").splitlines() if l.strip()]
    req = {}
    exe, sur, obs, others = [], [], [], []
    errors = []
    for r in rows:
        if r.get("event") == "request":
            req[r["request_id"]] = r
    for r in rows:
        ev = r.get("event")
        role = r.get("worker_role")
        try:
            if ev == "response" and role in ("executive", "surface", "observer"):
                rq = req.get(r["request_id"], {})
                body = json.loads(restore(r["raw_response_ref"]))
                ch = (body.get("choices") or [{}])[0]
                msg = ch.get("message", {})
                content = msg.get("content")
                usage = body.get("usage") or {}
                rc = msg.get("reasoning_content")
                base = {
                    "req_id": r["request_id"],
                    "req_at_utc": rq.get("at_utc"),
                    "resp_at_utc": r.get("at_utc"),
                    "req_local": local(rq["at_utc"]) if rq.get("at_utc") else None,
                    "resp_local": local(r["at_utc"]),
                    "elapsed_ms": r.get("elapsed_ms"),
                    "http_status": r.get("http_status"),
                    "lane": r.get("lane"),
                    "finish": ch.get("finish_reason"),
                    "usage": {
                        "prompt": usage.get("prompt_tokens"),
                        "completion": usage.get("completion_tokens"),
                        "reasoning": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                    },
                }
                parsed = parse_json_loose(content)
                if role == "executive":
                    envelope = None
                    ctx = {}
                    step_index = None
                    tool_n = None
                    opts = {}
                    if rq.get("raw_request_ref"):
                        rb = json.loads(restore(rq["raw_request_ref"]))
                        opts = {k: rb.get(k) for k in ("thinking", "reasoning_effort", "max_tokens", "temperature")}
                        last = rb["messages"][-1]["content"]
                        envelope = parse_json_loose(last)
                        if isinstance(envelope, dict):
                            step_index = envelope.get("step_index")
                            tr = envelope.get("tool_results")
                            tool_n = len(tr) if isinstance(tr, (list, dict)) else None
                            rcx = envelope.get("runtime_context")
                            if isinstance(rcx, dict):
                                for k in CTX_KEYS:
                                    if k in rcx:
                                        ctx[k] = shrink(rcx[k])
                                ctx["_keys"] = sorted(rcx.keys())
                                for k in ("learner_continuity", "conversation_move_receipts", "grounding_context"):
                                    if k in rcx:
                                        ctx["_len_" + k] = len(json.dumps(rcx[k], ensure_ascii=False))
                            ctx["_n_messages"] = len(rb["messages"])
                    evt = (envelope or {}).get("event") if isinstance(envelope, dict) else None
                    row = dict(base)
                    row.update({
                        "event": evt,
                        "step_index": step_index,
                        "tool_results_n": tool_n,
                        "opts": opts,
                        "ctx": ctx,
                        "resp": parsed if isinstance(parsed, dict) else {"_raw": (content or "")[:1500]},
                        "resp_is_json": isinstance(parsed, dict),
                        "reasoning_len": len(rc) if isinstance(rc, str) else None,
                        "reasoning_head": (rc or "")[:1800] if isinstance(rc, str) else None,
                        "content_len": len(content) if isinstance(content, str) else None,
                    })
                    exe.append(row)
                elif role == "surface":
                    row = dict(base)
                    row["resp"] = parsed if isinstance(parsed, dict) else {"_raw": (content or "")[:1500]}
                    sur.append(row)
                else:
                    row = dict(base)
                    keep = {}
                    if isinstance(parsed, dict):
                        for k in ("event_kind", "user_act", "relationship_meaning", "continuity",
                                  "repair_needed", "assistant_fault_probability", "memory_worthy",
                                  "confidence", "ambiguity", "appraisal", "consequence", "discourse",
                                  "relational_delta", "rupture_delta", "playful_safety_delta"):
                            if k in parsed:
                                keep[k] = parsed[k]
                    row["resp"] = keep
                    obs.append(row)
            elif ev not in ("request", "response", "observer_diagnostic"):
                others.append({k: r.get(k) for k in ("event", "at_utc", "worker_role")})
        except Exception as e:  # noqa: BLE001
            errors.append({"event": ev, "role": role, "req": r.get("request_id"), "err": repr(e)[:200]})
    m = re.match(r"events_(\d{8}T\d{6}Z)_pid(\d+)\.jsonl", name)
    start_utc = datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    sid = start_utc.astimezone(TZ).strftime("%Y%m%d_%H%M%S")
    res = {
        "source": name, "session_local_start": sid, "pid": int(m.group(2)),
        "executive": exe, "surface": sur, "observer": obs, "other_events": others[:20],
        "errors": errors,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / (sid + ".json")).write_text(json.dumps(res, ensure_ascii=False), "utf-8")
    kinds = {}
    for e in exe:
        k = ((e.get("event") or {}).get("kind")) or "?"
        kinds[k] = kinds.get(k, 0) + 1
    return {"session": sid, "rows": len(rows), "exec": len(exe), "surface": len(sur), "observer": len(obs),
            "event_kinds": kinds, "errors": len(errors)}


def main():
    out_dir = Path(sys.argv[1])
    names = sys.argv[2:]
    if not names:
        names = sorted(p.name for p in BASE.glob("events_2026*T*Z_pid*.jsonl")
                       if not p.name.startswith("events_gateway") and p.name >= "events_20261011")
    summary = []
    for n in names:
        try:
            summary.append(process(n, out_dir))
        except Exception as e:  # noqa: BLE001
            summary.append({"source": n, "fatal": repr(e)[:300]})
    (out_dir / "_extract_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
    print("done sessions=%d" % len(summary))


if __name__ == "__main__":
    main()
