"""Paired removal of two initiative-bias spans; never edits runtime or executes tools."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / ".agents/tasks/eris-eq-verification"))
from probe import RAW, restore, case_payload, request


def remove_bias(payload):
    result = deepcopy(payload)
    text = result["messages"][0]["content"]
    removed = []
    for start, stop in [
        ("Khi mạch còn mở và thật sự còn điều muốn nói,", "Chính cá tính và cảm nhận ngữ cảnh"),
        ("Khi event là autonomous_signal, opening_signal hoặc continuation:", "Không tạo floor, beat,")
    ]:
        assert text.count(start) == 1 and text.count(stop) == 1
        left = text.index(start)
        right = text.index(stop, left)
        removed.append(text[left:right])
        text = text[:left] + text[right:]
    result["messages"][0]["content"] = text
    assert result["messages"][1:] == payload["messages"][1:]
    assert {k: v for k, v in result.items() if k != "messages"} == {k: v for k, v in payload.items() if k != "messages"}
    return result, removed


def main():
    specifications = [
        ("opening_old_council", "events_20261103T145411Z_pid5836.jsonl", "fa4008034180447ba443c59d39e08a44"),
        ("timer_after_unanswered", "events_20261103T080642Z_pid21944.jsonl", "9016925fee7d4e509e78f28aff86d4e6"),
        ("venting", "events_20261103T145411Z_pid5836.jsonl", "d88568e2807e48a1ac4f11bfdc0481ae"),
        ("explicit_repair", "events_20261103T145411Z_pid5836.jsonl", "93677379697e4e409966c1468de1aaa3"),
    ]
    cases = []
    for case, name, ident in specifications:
        rows = [json.loads(line) for line in (RAW / name).read_text("utf-8").splitlines()]
        row = next(r for r in rows if r.get("event") == "request" and r["request_id"] == ident)
        cases.append((case, restore(row["raw_request_ref"])))
    cases.append(("explicit_initiative_request", case_payload(cases[-1][1], [],
        "Eris tự mở chuyện đi, chọn một chuyện cụ thể mà bạn thấy thú vị rồi bắt đầu luôn nhé.")))
    tasks = []
    manifest = []
    for case, baseline in cases:
        altered, removed = remove_bias(baseline)
        manifest.append({"case": case, "removed_spans": removed,
                         "other_messages_sha256": hashlib.sha256(json.dumps(baseline["messages"][1:],ensure_ascii=False).encode()).hexdigest()})
        for repeat in (1, 2, 3):
            for condition, payload in [("baseline", baseline), ("initiative_bias_removed", altered)]:
                tasks.append({"case": case, "condition": condition, "repeat": repeat, "payload": payload})
    random.Random(20261105).shuffle(tasks)
    (HERE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
    (HERE / "plan.json").write_text(json.dumps([{k: v for k,v in t.items() if k != "payload"} for t in tasks],indent=2),"utf-8")
    credentials = json.loads(Path("C:/Users/Gtvkun/Documents/eris/config/secrets.json").read_text("utf-8-sig"))["api_keys"]
    os.environ["ERIS_EQ_PROBE_API_KEY"] = credentials.get("ERIS_DS_EXECUTIVE_API_KEY") or credentials["ERIS_DS2API_API_KEY"]
    with ThreadPoolExecutor(max_workers=2) as executor, (HERE / "results.jsonl").open("w", encoding="utf-8") as out:
        futures = [executor.submit(request, task, "http://127.0.0.1:5103/v1/chat/completions") for task in tasks]
        for future in as_completed(futures):
            r = future.result()
            out.write(json.dumps(r,ensure_ascii=False) + "\n")
            out.flush()
            print(r["case"],r["condition"],r["repeat"],r.get("http_status",r.get("error_type")),flush=True)


if __name__ == "__main__":
    main()
