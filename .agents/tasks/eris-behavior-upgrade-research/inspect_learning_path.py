"""Inspect existing files only; write a compact research receipt beside this script."""
import ast
import gzip
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PORTABLE = Path("C:/Users/Gtvkun/Documents/eris")
RAW = Path("C:/eris_debug/deepseek_raw")
INDEX = RAW / "events_20261103T145411Z_pid5836.jsonl"


def restore(manifest):
    pieces = []
    for digest in manifest["chunks"]:
        piece = gzip.decompress((RAW / "objects" / digest[:2] / (digest + ".gz")).read_bytes())
        assert hashlib.sha256(piece).hexdigest() == digest
        pieces.append(piece)
    body = b"".join(pieces)
    assert hashlib.sha256(body).hexdigest() == manifest["sha256"]
    assert len(body) == manifest["byte_length"]
    return json.loads(body)


observer_inputs = []
for number, line in enumerate(INDEX.read_text("utf-8").splitlines(), 1):
    event = json.loads(line)
    if event.get("event") != "request" or event.get("worker_role") != "observer":
        continue
    body = restore(event["raw_request_ref"])
    for message in body["messages"]:
        if message.get("role") != "user":
            continue
        try:
            payload = json.loads(message["content"])
        except (ValueError, TypeError):
            continue
        state = payload.get("current_state_summary", {})
        identity = state.get("identity", {})
        observer_inputs.append({
            "index_line": number,
            "at_utc": event["at_utc"],
            "request_id": event["request_id"],
            "event_kind": payload.get("event_kind"),
            "identity_learning_enabled": state.get("identity_learning_enabled"),
            "pending_strategies": identity.get("pending_strategies"),
            "strategies_count": len(identity.get("strategies", {})),
            "mechanical_outcomes_count": len(payload.get("mechanical_outcomes", [])),
        })

symbols = ("from_pending_strategy", "add_pending_strategy", "PendingStrategyUse")
calls = []
parse_failures = []
for path in (REPO / "src").rglob("*.py"):
    if "tests" in path.relative_to(REPO).parts:
        continue
    try:
        tree = ast.parse(path.read_text("utf-8-sig"))
    except (SyntaxError, UnicodeError) as exc:
        parse_failures.append({"file": str(path.relative_to(REPO)), "error": type(exc).__name__})
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        if name in symbols:
            calls.append({"file": str(path.relative_to(REPO)), "line": node.lineno, "symbol": name})

hashes = []
for relative in (
    "src/runtime/conversation/observation_bridge.py",
    "src/runtime/observer_private_runtime.py",
    "src/runtime/ai_orchestrated/identity_reducer.py",
    "src/runtime/ai_orchestrated/contracts.py",
    "src/runtime/conversation/root_prompt_contract.py",
    "src/runtime/ai_orchestrated/observer.py",
):
    dev = hashlib.sha256((REPO / relative).read_bytes()).hexdigest()
    portable = hashlib.sha256((PORTABLE / relative).read_bytes()).hexdigest()
    hashes.append({"file": relative, "dev_sha256": dev, "portable_sha256": portable, "match": dev == portable})

receipt = {"source_index": str(INDEX), "observer_requests": observer_inputs,
           "production_calls": calls, "ast_parse_failures": parse_failures, "hashes": hashes}
Path(__file__).with_name("learning-path-evidence.json").write_text(
    json.dumps(receipt, ensure_ascii=False, indent=2), "utf-8"
)
print(json.dumps(receipt, ensure_ascii=False, indent=2))
