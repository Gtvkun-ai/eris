#!/usr/bin/env python
"""s06: tong hop telemetry lien quan EQ tu eris_observability.jsonl (stream, chi doc).

Khong ghi noi dung hoi thoai. Chi so dem / phan vi theo ngay (UTC+7).

Chay:
    python -X utf8 s06_obs_aggregate.py <out_json> [YYYY-MM-DD tu] [YYYY-MM-DD den]
"""
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

SRC = r"C:\Users\Gtvkun\Documents\eris\logs\eris_observability.jsonl"
TZ = timezone(timedelta(hours=7))
WANT = {
    "user_turn_latency_ms", "ttft_ms", "chat_orchestrator_latency_ms", "conversation_run_failed",
    "observer_failure_total", "observer_discard_total", "observer_completed_total", "observer_latency_ms",
    "rate_limit_429_total", "tts_fallback_total", "public_writer_fallback", "public_writer_wording_retry",
    "semantic_frame_v1", "self_turn", "output_tokens_by_lane", "input_tokens_by_lane", "broker_rejected_total",
    "user_turn_broker_scope_duration_ms", "remote_calls_per_user_turn", "abstain_total",
}


def pct(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return round(s[k], 1)


def main():
    out_path = sys.argv[1]
    d0 = sys.argv[2] if len(sys.argv) > 2 else "2026-10-24"
    d1 = sys.argv[3] if len(sys.argv) > 3 else "2026-11-04"
    lat = defaultdict(list)           # day -> [ms]
    lat_cat = defaultdict(list)       # (day,category) -> [ms]
    ttft = defaultdict(list)
    fails = Counter()                 # (day, reason_short)
    obs_fail = Counter()
    obs_disc = Counter()
    obs_done = Counter()
    obs_lat = defaultdict(list)
    r429 = Counter()
    tts_fb = Counter()
    wf = Counter()
    sf = Counter()                    # (day, user_act, target, relation)
    selft = Counter()                 # (day, result, turn_kind, speech_act)
    selft_gate = Counter()
    n_lines = 0
    with open(SRC, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            # loc nhanh theo ten (dinh dang khoang trang JSON khong co dinh)
            hit = False
            head = line[:260]
            for w in WANT:
                if w in head:
                    hit = True
                    break
            if not hit:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            ts = d.get("timestamp")
            n = d.get("name")
            if n not in WANT or not isinstance(ts, (int, float)):
                continue
            day = datetime.fromtimestamp(ts, TZ).strftime("%Y-%m-%d")
            if day < d0 or day > d1:
                continue
            n_lines += 1
            tags = d.get("tags") or {}
            fl = d.get("fields") or {}
            v = d.get("value")
            if n == "user_turn_latency_ms":
                lat[day].append(float(v))
                lat_cat[(day, tags.get("turn_category", "?") + "|" + tags.get("channel", "?"))].append(float(v))
            elif n == "ttft_ms":
                ttft[day].append(float(v))
            elif n == "conversation_run_failed":
                r = str(tags.get("reason", ""))
                r = r.split(":")[0] + ":" + (r.split(":")[1].split("=")[0] if ":" in r else "")
                fails[(day, tags.get("status", "?") + "|" + r)] += 1
            elif n == "observer_failure_total":
                obs_fail[(day, tags.get("event_kind", "?") + "|" + tags.get("status", "?"))] += 1
            elif n == "observer_discard_total":
                obs_disc[(day, tags.get("event_kind", "?") + "|" + tags.get("reason", "?") + "|" + tags.get("stage", "?"))] += 1
            elif n == "observer_completed_total":
                obs_done[(day, tags.get("event_kind", "?") + "|" + tags.get("status", "?"))] += 1
            elif n == "observer_latency_ms":
                obs_lat[day].append(float(v))
            elif n == "rate_limit_429_total":
                r429[(day, tags.get("lane", "?") + "|" + tags.get("provider", "?"))] += 1
            elif n == "tts_fallback_total":
                tts_fb[(day, "%s|%s|%s" % (tags.get("provider"), tags.get("success"), tags.get("reason")))] += 1
            elif n == "public_writer_fallback":
                wf[(day, tags.get("kind", "?"))] += 1
            elif n == "semantic_frame_v1":
                sf[(day, tags.get("user_act", "?"), tags.get("target", "?"), tags.get("relation", "?"))] += 1
            elif n == "self_turn":
                selft[(day, tags.get("result", "?"), tags.get("turn_kind", "?"), tags.get("speech_act", "?"))] += 1
                selft_gate[(day, str(fl.get("gate_reason", "?")))] += 1

    def summ(dd):
        return {k: {"n": len(v), "median": pct(v, 0.5), "p90": pct(v, 0.9), "max": round(max(v), 1), "min": round(min(v), 1)}
                for k, v in sorted(dd.items())}

    def flat(c):
        res = defaultdict(dict)
        for k, v in c.items():
            res[k[0]][" | ".join(k[1:])] = v
        return {k: dict(sorted(v.items(), key=lambda kv: -kv[1])) for k, v in sorted(res.items())}

    res = {
        "source": SRC, "range": [d0, d1], "rows_used": n_lines,
        "user_turn_latency_ms_by_day": summ(lat),
        "user_turn_latency_ms_by_day_category": {"%s %s" % k: x for k, x in summ(lat_cat).items()},
        "ttft_ms_by_day": summ(ttft),
        "conversation_run_failed": flat(fails),
        "observer_failure_total": flat(obs_fail),
        "observer_discard_total": flat(obs_disc),
        "observer_completed_total": flat(obs_done),
        "observer_latency_ms_by_day": summ(obs_lat),
        "rate_limit_429_total": flat(r429),
        "tts_fallback_total": flat(tts_fb),
        "public_writer_fallback": flat(wf),
        "semantic_frame_v1": flat(sf),
        "self_turn": flat(selft),
        "self_turn_gate_reason": flat(selft_gate),
    }
    with open(out_path, "w", encoding="utf-8") as g:
        json.dump(res, g, ensure_ascii=False, indent=1)
    print("ok rows=%d" % n_lines)


if __name__ == "__main__":
    main()
