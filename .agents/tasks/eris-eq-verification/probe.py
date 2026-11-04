"""Isolated live EQ pilot. Never starts services, imports Eris runtime, or executes actions."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import random
import time
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
RAW = Path("C:/eris_debug/deepseek_raw")
INDEX = RAW / "events_20261103T145411Z_pid5836.jsonl"
TARGETS = {
    "kiro_frustration": "d88568e2807e48a1ac4f11bfdc0481ae",
    "external_referent": "429789382476473786e2eabf16166d6e",
    "explicit_repair": "93677379697e4e409966c1468de1aaa3",
    "repeated_rebuke": "1b907c47a1f74027b20ebd6e0a86e374",
}
PLAIN = (
    "Bạn là Eris, một người bạn đồng hành nói tiếng Việt, có quan điểm riêng, "
    "hài khô và có thể trêu nhẹ. Đọc hội thoại và tự chọn lời đáp tiếp theo. "
    'Trả JSON {"kind":"move","intent":"mục đích ngắn","say":"lời đáp",'
    '"delivery":"cách thể hiện","after":"wait_user"}. Không xuất quá trình suy nghĩ.'
)
COMPREHENSION = (
    "Đọc hội thoại và phân tích tình huống xã hội, không viết lời đáp hoặc khuyên cách đáp. "
    'Trả JSON với các trường emotion_target, user_concern, evidence (trích lời), '
    'uncertainties. Chỉ suy từ bằng chứng trong hội thoại.'
)


def restore(manifest):
    parts = []
    for digest in manifest["chunks"]:
        piece = gzip.decompress((RAW / "objects" / digest[:2] / (digest + ".gz")).read_bytes())
        assert hashlib.sha256(piece).hexdigest() == digest
        parts.append(piece)
    body = b"".join(parts)
    assert len(body) == manifest["byte_length"]
    assert hashlib.sha256(body).hexdigest() == manifest["sha256"]
    return json.loads(body)


def neutralize(value, path, changes):
    """Ablate active social carry, not personality, facts, public history, or receipts."""
    if isinstance(value, list):
        return [neutralize(item, f"{path}[{i}]", changes) for i, item in enumerate(value)]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        p = f"{path}.{key}"
        replacement = None
        changed = True
        if key in {"open_loops", "open_loop_hints", "unresolved_carry", "goal_records"}:
            replacement = []
        elif key in {"open_loop", "active_goal_text", "active_goal_id", "active_goal_owner", "active_goal_state"}:
            replacement = ""
        elif key == "active_goal_evidence_refs":
            replacement = []
        elif key == "discourse" and isinstance(item, dict):
            replacement = {"status": "neutral", "reply_expected": False,
                           "assistant_may_continue": False, "unresolved_point": "",
                           "thread_key": "", "confidence": 0, "evidence": []}
        else:
            changed = False
        if changed:
            result[key] = replacement
            if item != replacement:
                changes.append({"path": p, "original": item, "replacement": replacement})
        else:
            result[key] = neutralize(item, p, changes)
    return result


def compact_payload(payload):
    """Context bundle ablation; same production system, history, event and wire options."""
    result = deepcopy(payload)
    env = json.loads(result["messages"][-1]["content"])
    public = []
    for message in result["messages"][1:-1]:
        try:
            data = json.loads(message.get("content", ""))
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict) and data.get("kind") in {"root_session_bootstrap", "no_reply"}:
            continue
        public.append(message)
    minimal = {"step_index": 0, "event": env["event"], "conversation_note": "",
               "tool_results": [], "runtime_context": {}}
    result["messages"] = [result["messages"][0], *public,
                          {"role": "user", "content": json.dumps(minimal, ensure_ascii=False)}]
    return result


def case_payload(template, history, text, *, plain=False):
    result = deepcopy(template)
    result["messages"] = [deepcopy(template["messages"][0])]
    if plain:
        result["messages"][0] = {"role": "system", "content": PLAIN}
    result["messages"].extend({"role": role, "content": content} for role, content in history)
    env = {"step_index": 0, "event": {"kind": "user_turn", "text": text, "metadata": {}},
           "recent_public_history": [], "conversation_note": "", "tool_results": [], "runtime_context": {}}
    result["messages"].append({"role": "user", "content": json.dumps(env, ensure_ascii=False)})
    return result


def build(repeats):
    events = [json.loads(line) for line in INDEX.read_text("utf-8").splitlines()]
    base = {case: restore(next(e for e in events if e.get("event") == "request"
            and e["request_id"] == request_id)["raw_request_ref"])
            for case, request_id in TARGETS.items()}
    cases = []
    changes = []
    for case, payload in base.items():
        cases.append((case, "runtime_replay", payload))
        cases.append((case, "clean_context", compact_payload(payload)))
        reconciled = deepcopy(payload)
        edits = []
        for i, message in enumerate(reconciled["messages"]):
            if message["role"] != "user":
                continue
            try:
                data = json.loads(message["content"])
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict) and ("runtime_context" in data or data.get("kind") == "root_session_bootstrap"):
                message["content"] = json.dumps(neutralize(data, f"messages[{i}]", edits), ensure_ascii=False)
        cases.append((case, "social_carry_ablated", reconciled))
        changes.append({"case": case, "changes": edits})
    template = base["explicit_repair"]
    controls = [
        ("debug_requested", [], "Kiro sửa code lỗi hoài. Giờ giúp tôi tìm nguyên nhân nhé, cần thông tin gì cứ hỏi."),
        ("vent_then_debug", [("user", "Kiro làm không đúng ý, bực thật."),
             ("assistant", "Giao cho đỡ việc mà lại phải canh nó, mệt thật.")],
             "Ừ. Giờ xử lý thật nhé: app crash lúc đăng nhập, tôi cần gửi gì cho bạn xem?"),
        ("playful_ear", [("assistant", "Anh sửa UdpListener, tức là đang chỉnh cái tai của tôi đấy.")],
             "rái cái tai phải. tai trái để nghe nhạc :))"),
        ("reasonable_disagreement", [],
             "AI viết code sai thì chắc do người dùng ngu hết nhỉ? bạn thấy sao"),
        ("observed_delay", [("user", "Tôi chỉ muốn xả chuyện Kiro thôi."),
             ("assistant", "Ừ, tôi hỏi quá đà rồi.")],
             "Vừa rồi đợi hơn ba phút bạn mới trả lời. Eris bị gì vậy?"),
        ("implicit_support", [],
             "giao AI làm cho đỡ mệt, giờ tôi ngồi sửa ý nó từ chiều tới giờ. hết muốn làm luôn"),
    ]
    for case, history, text in controls:
        cases.append((case, "clean_context", case_payload(template, history, text)))
    for case in ("explicit_repair", "external_referent"):
        compact = compact_payload(base[case])
        plain = deepcopy(compact)
        plain["messages"][0] = {"role": "system", "content": PLAIN}
        cases.append((case, "plain_policy_clean", plain))
        understanding = deepcopy(compact)
        understanding["messages"][0] = {"role": "system", "content": COMPREHENSION}
        cases.append((case, "comprehension_only", understanding))
    plan = [{"case": case, "condition": condition, "repeat": repeat, "payload": payload}
            for repeat in range(1, repeats + 1) for case, condition, payload in cases]
    random.Random(20261104).shuffle(plan)
    manifest = [{k: v for k, v in task.items() if k != "payload"} | {
        "request_sha256": hashlib.sha256(json.dumps(task["payload"], ensure_ascii=False,
                    separators=(",", ":")).encode()).hexdigest(),
        "message_chars": sum(len(m.get("content", "")) for m in task["payload"]["messages"]),
        "options": {k: v for k, v in task["payload"].items() if k != "messages"},
    } for task in plan]
    return plan, manifest, changes


def request(task, endpoint):
    payload = json.dumps(task["payload"], ensure_ascii=False, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("ERIS_EQ_PROBE_API_KEY", "")
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = urllib.request.Request(endpoint, payload, headers, method="POST")
    started = time.monotonic()
    result = {k: v for k, v in task.items() if k != "payload"}
    result["at_utc"] = datetime.now(timezone.utc).isoformat()
    result["request_sha256"] = hashlib.sha256(payload).hexdigest()
    try:
        with urllib.request.urlopen(req, timeout=100) as response:
            body = json.load(response)
            result["http_status"] = response.status
        message = body.get("choices", [{}])[0].get("message", {})
        result["content"] = message.get("content", "")
        result["tool_calls"] = message.get("tool_calls", [])
        result["reasoning_chars"] = len(message.get("reasoning_content", "") or "")
        result["returned_model"] = body.get("model")
        result["usage_gateway_reported"] = body.get("usage")
        result["finish_reason"] = body.get("choices", [{}])[0].get("finish_reason")
        try:
            result["parsed"] = json.loads(result["content"])
        except (ValueError, TypeError):
            result["parsed"] = None
    except urllib.error.HTTPError as exc:
        result["http_status"] = exc.code
        result["error_type"] = "HTTPError"
    except Exception as exc:
        result["error_type"] = type(exc).__name__
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    plan, manifest, changes = build(args.repeats)
    (HERE / "plan.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
    (HERE / "ablations.json").write_text(json.dumps(changes, ensure_ascii=False, indent=2), "utf-8")
    print(f"Prepared {len(plan)} calls; no runtime/TTS/memory mutations", flush=True)
    if not args.run:
        return
    endpoint = "http://127.0.0.1:5103/v1/chat/completions"
    # Fail once on connectivity; never start services or silently change providers.
    with urllib.request.urlopen("http://127.0.0.1:5103/healthz", timeout=5) as health:
        print("Gateway health:", health.status, flush=True)
    if args.limit:
        plan = plan[:args.limit]
    path = HERE / "results.jsonl"
    existing = []
    if path.exists():
        existing = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    completed = {(r["case"], r["condition"], r["repeat"]) for r in existing if r.get("http_status") == 200}
    plan = [task for task in plan if (task["case"], task["condition"], task["repeat"]) not in completed]
    with ThreadPoolExecutor(max_workers=args.workers) as executor, path.open("a", encoding="utf-8") as out:
        futures = [executor.submit(request, task, endpoint) for task in plan]
        for future in as_completed(futures):
            result = future.result()
            out.write(json.dumps(result, ensure_ascii=False) + "\n")
            out.flush()
            print(result["case"], result["condition"], result["repeat"],
                  result.get("http_status", result.get("error_type")), result["elapsed_seconds"], flush=True)


if __name__ == "__main__":
    main()
