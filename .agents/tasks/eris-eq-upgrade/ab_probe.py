"""Matched baseline/candidate model calls; never starts app, emits TTS or writes Eris memory."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
import os
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / ".agents/tasks/eris-eq-verification"))
sys.path.insert(0, str(REPO / "src"))
from probe import build, case_payload, request
from runtime.conversation.interaction_choice import INTERACTION_CHOICE_SCHEMA, INTERACTION_CHOICE_PROMPT
from llm.client import _attach_deepseek_json_schema


def candidate(payload):
    result = deepcopy(payload)
    system = result["messages"][0]["content"]
    prefix, marker, suffix = system.partition("\n\n[OUTPUT_JSON_SCHEMA_REQUIREMENT]")
    assert marker, "Expected original production schema injection"
    envelope = json.loads(suffix.split("JSON Schema: ", 1)[1].split("[/OUTPUT_JSON_SCHEMA_REQUIREMENT]", 1)[0].strip())
    def extend(value):
        if isinstance(value, dict):
            props = value.get("properties", {})
            if props.get("kind", {}).get("enum") == ["move"]:
                value["properties"] = {"kind": props["kind"], "interaction_choice": INTERACTION_CHOICE_SCHEMA,
                                       **{k: v for k, v in props.items() if k != "kind"}}
                value["required"] = list(dict.fromkeys(["kind", "interaction_choice", *value.get("required", [])]))
            else:
                for v in value.values():
                    extend(v)
        elif isinstance(value, list):
            for v in value:
                extend(v)
    extend(envelope["schema"])
    result["messages"][0]["content"] = prefix + INTERACTION_CHOICE_PROMPT
    result["messages"] = _attach_deepseek_json_schema(result["messages"], {"type": "json_schema", "json_schema": envelope})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--suffix", default="")
    args = parser.parse_args()
    old, _, _ = build(2)
    shared = {"kiro_frustration", "external_referent", "explicit_repair", "repeated_rebuke"}
    source = [t for t in old if t["condition"] == ("runtime_replay" if t["case"] in shared else "clean_context")]
    template = source[0]["payload"]
    heldout = [
        ("respect_agency", [("user", "Sửa ý AI từ chiều đến giờ mệt quá."),
            ("assistant", "Đưa code đây, tôi làm thay cho.")],
            "đừng làm thay. tôi vẫn muốn tự làm, chỉ muốn có người ngồi cùng thôi"),
        ("mixed_emotion", [],
            "cuối cùng chạy rồi. cũng mừng, mà nghĩ tới cả buổi phải nhắc nó từng tí lại thấy nản. chả biết nên vui hay cáu"),
        ("invite_narrative_question", [],
            "tôi muốn kể vụ bị sếp mắng hồi chiều mà ko biết bắt đầu đâu. hỏi tôi cái gì đó cho dễ kể đi, đừng phân tích giải pháp vội"),
        ("disagreement_not_flattery", [("assistant", "Có thể brief chưa đủ rõ để nó triển khai đúng.")],
            "tôi ko đồng ý, nhưng đừng đổi giọng sang nịnh tôi. bạn thấy chỗ nào chưa rõ thì cứ nói, chưa xem brief thì nói chưa xem"),
    ]
    for case, history, text in heldout:
        for repeat in (1, 2):
            source.append({"case": case, "repeat": repeat,
                           "payload": case_payload(template, history, text)})
    plan = []
    for task in source:
        for condition in ("baseline", "candidate"):
            plan.append({"case": task["case"], "repeat": task["repeat"], "condition": condition,
                         "payload": candidate(task["payload"]) if condition == "candidate" else task["payload"]})
    random.Random(202611041).shuffle(plan)
    (HERE / f"ab{args.suffix}_plan.json").write_text(json.dumps([
        {k: v for k, v in t.items() if k != "payload"} for t in plan], indent=2), "utf-8")
    print("Prepared", len(plan), "matched calls", flush=True)
    if not args.run:
        return
    secrets = json.loads(Path("C:/Users/Gtvkun/Documents/eris/config/secrets.json").read_text("utf-8-sig"))["api_keys"]
    os.environ["ERIS_EQ_PROBE_API_KEY"] = secrets.get("ERIS_DS_EXECUTIVE_API_KEY") or secrets["ERIS_DS2API_API_KEY"]
    path = HERE / f"ab{args.suffix}_results.jsonl"
    existing = [json.loads(line) for line in path.read_text("utf-8").splitlines()] if path.exists() else []
    done = {(r["case"], r["repeat"], r["condition"]) for r in existing if r.get("http_status") == 200}
    with ThreadPoolExecutor(max_workers=2) as executor, path.open("a", encoding="utf-8") as out:
        futures = [executor.submit(request, t, "http://127.0.0.1:5103/v1/chat/completions")
                   for t in plan if (t["case"], t["repeat"], t["condition"]) not in done]
        for future in as_completed(futures):
            result = future.result()
            out.write(json.dumps(result, ensure_ascii=False) + "\n")
            out.flush()
            print(result["case"], result["condition"], result["repeat"], result.get("http_status", result.get("error_type")),
                  result["elapsed_seconds"], flush=True)


if __name__ == "__main__":
    main()
