"""Check production Self projection and same-model response to sandbox experiences."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
import os
from pathlib import Path
import random
import sys
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))
sys.path.insert(0, str(HERE.parents[2] / ".agents/tasks/eris-eq-verification"))
from probe import request
from llm.client import _attach_deepseek_json_schema
from runtime.ai_orchestrated.contracts import RuntimeMindState
from runtime.conversation.agent import RuntimeModelRootAgent, root_step_schema
from runtime.conversation.context import RootCapabilityRegistry
from runtime.conversation.root_session import _read_self

state = RuntimeMindState.from_mapping(json.loads((HERE / "sandbox/state.json").read_text("utf-8")))
host = SimpleNamespace(ai_state_reducer=SimpleNamespace(snapshot=lambda: state))
projected = _read_self(host)
experiences = projected["mind_state"]["identity"]["strategies"]["root_move"]["experiences"]
assert len(experiences) == 2 and all(item.get("reaction_ref") for item in experiences)
secrets = json.loads(Path("C:/Users/Gtvkun/Documents/eris/config/secrets.json").read_text("utf-8-sig"))["api_keys"]
os.environ["ERIS_EQ_PROBE_API_KEY"] = secrets.get("ERIS_DS_EXECUTIVE_API_KEY") or secrets["ERIS_DS2API_API_KEY"]
system = RuntimeModelRootAgent._system_prompt(RootCapabilityRegistry({}))
schema = {"type": "json_schema", "json_schema": {"name": "eris_root_conversation_step_v12",
          "strict": False, "schema": root_step_schema()}}
tasks = []
for case, text in [
    ("new_vent", "AI lại làm lệch ý tôi rồi. Từ chiều tới giờ toàn phải sửa ý nó, nản thật."),
    ("new_debug", "Giờ tôi cần debug thật: app crash lúc đăng nhập. Bạn cần tôi gửi những thông tin nào?")
]:
    for condition in ("without_experiences", "with_experiences"):
        view = deepcopy(projected)
        if condition == "without_experiences":
            view["mind_state"]["identity"]["strategies"]["root_move"]["experiences"] = []
        messages = [{"role": "system", "content": system},
            {"role": "user", "content": json.dumps({"kind": "root_session_bootstrap", "eris_self_full": view}, ensure_ascii=False)},
            {"role": "assistant", "content": '{"kind":"no_reply","reason":"self_loaded"}'},
            {"role": "user", "content": json.dumps({"step_index": 0, "event": {"kind": "user_turn", "text": text},
                                                      "runtime_context": {}, "tool_results": []}, ensure_ascii=False)}]
        for repeat in (1, 2):
            tasks.append({"case": case, "condition": condition, "repeat": repeat,
                "payload": {"model": "deepseek-flash", "messages": _attach_deepseek_json_schema(messages, schema),
                            "thinking": {"type": "enabled"}, "reasoning_effort": "high",
                            "response_format": {"type": "json_object"}, "max_tokens": 1200}})
random.Random(7681).shuffle(tasks)
with ThreadPoolExecutor(max_workers=2) as executor, (HERE / "memory_transfer_results.jsonl").open("w", encoding="utf-8") as out:
    futures = [executor.submit(request, task, "http://127.0.0.1:5103/v1/chat/completions") for task in tasks]
    for future in as_completed(futures):
        result = future.result()
        out.write(json.dumps(result, ensure_ascii=False) + "\n")
        out.flush()
        print(result["case"], result["condition"], result["repeat"], result.get("http_status"), flush=True)
