"""Small serving-stack comparison; same role-labelled text, no production routing change."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / ".agents/tasks/eris-eq-verification"))
from probe import build

rows, _, _ = build(2)
cases = {"explicit_repair", "external_referent", "debug_requested", "playful_ear"}
tasks = [r for r in rows if r["condition"] == "clean_context" and r["case"] in cases]
tasks.sort(key=lambda x: (x["repeat"], x["case"]))
secrets = json.loads(Path("C:/Users/Gtvkun/Documents/eris/config/secrets.json").read_text("utf-8-sig"))["api_keys"]
key = secrets.get("ERIS_DS_EXECUTIVE_API_KEY") or secrets["ERIS_DS2API_API_KEY"]


def invoke(task, provider):
    prompt = "\n\n".join(f"[{m['role'].upper()}]\n{m['content']}" for m in task["payload"]["messages"])
    model = "gemini-flash" if provider == "gemini_web" else "deepseek-flash"
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
               "response_format": {"type": "json_object"}, "max_tokens": 1200,
               "thinking": {"type": "enabled"}, "reasoning_effort": "high"}
    headers = {"Content-Type": "application/json"}
    if provider == "deepseek_web":
        headers["Authorization"] = "Bearer " + key
    url = "http://127.0.0.1:" + ("8000" if provider == "gemini_web" else "5103") + "/v1/chat/completions"
    result = {"case": task["case"], "repeat": task["repeat"], "provider": provider,
              "input_text_sha256": hashlib.sha256(prompt.encode()).hexdigest()}
    started = time.monotonic()
    try:
        req = urllib.request.Request(url, json.dumps(payload, ensure_ascii=False).encode(), headers)
        with urllib.request.urlopen(req, timeout=75) as res:
            body = json.load(res)
            result["http_status"] = res.status
        msg = body["choices"][0]["message"]
        result["content"] = msg.get("content", "")
        result["reasoning_chars"] = len(msg.get("reasoning_content", "") or "")
        result["returned_model"] = body.get("model")
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["http_status"] = getattr(exc, "code", None)
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def main():
    path = HERE / "serving_model_results.jsonl"
    failures = 0
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as executor, path.open("a", encoding="utf-8") as out:
        for task in tasks:
            if failures or time.monotonic() - started > 300:
                print("Stopped bounded pilot after failure/time budget", flush=True)
                break
            futures = [executor.submit(invoke, task, provider) for provider in ("deepseek_web", "gemini_web")]
            for future in futures:
                result = future.result()
                failures += result.get("http_status") != 200
                out.write(json.dumps(result, ensure_ascii=False) + "\n")
                out.flush()
                print(result["case"], result["provider"], result["repeat"],
                      result.get("http_status"), result["elapsed_seconds"], flush=True)


if __name__ == "__main__":
    main()
