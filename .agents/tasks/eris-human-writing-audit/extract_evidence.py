"""Read-only RAW reconstruction; export dialogue and selected context, no reasoning."""
import gzip
import hashlib
import json
from pathlib import Path

BASE = Path("C:/eris_debug/deepseek_raw")
NAMES = [
    "events_20261103T080642Z_pid21944.jsonl",
    "events_20261103T092914Z_pid10272.jsonl",
    "events_20261103T145411Z_pid5836.jsonl",
]


def restore(manifest):
    parts = []
    for digest in manifest["chunks"]:
        piece = gzip.decompress(
            (BASE / "objects" / digest[:2] / (digest + ".gz")).read_bytes()
        )
        assert hashlib.sha256(piece).hexdigest() == digest
        parts.append(piece)
    data = b"".join(parts)
    assert len(data) == manifest["byte_length"]
    assert hashlib.sha256(data).hexdigest() == manifest["sha256"]
    return json.loads(data)


sessions = []
for name in NAMES:
    rows = [json.loads(line) for line in (BASE / name).read_text("utf-8").splitlines()]
    responses = []
    selected_requests = []
    for line_number, event in enumerate(rows, 1):
        if event.get("event") == "response" and event.get("worker_role") in (
            "executive", "surface"
        ):
            body = restore(event["raw_response_ref"])
            if "choices" not in body:
                continue
            content = body["choices"][0].get("message", {}).get("content")
            try:
                dialogue = json.loads(content)
            except (ValueError, TypeError):
                dialogue = {"literal_dialogue": content}
            responses.append({
                "index_line": line_number,
                "request_id": event["request_id"],
                "at_utc": event["at_utc"],
                "role": event["worker_role"],
                "dialogue": dialogue,
            })
        if (name == NAMES[-1] and event.get("event") == "request"
                and event.get("worker_role") == "executive"
                and event["at_utc"].split("T")[1][:8] in (
                    "14:59:51", "15:03:46", "15:04:53"
                )):
            body = restore(event["raw_request_ref"])
            envelope = json.loads(body["messages"][-1]["content"])
            context = envelope["runtime_context"]
            # Field paths are found structurally, without exporting the whole prompt.
            relevant = {}

            def visit(value, path=""):
                if isinstance(value, list):
                    for index, item in enumerate(value):
                        visit(item, f"{path}[{index}]")
                if isinstance(value, str) and value.lstrip().startswith("{"):
                    try:
                        visit(json.loads(value), path + "[json]")
                    except ValueError:
                        pass
                if isinstance(value, dict):
                    for key, item in value.items():
                        subpath = f"{path}.{key}" if path else key
                        if key in ("conversation_status", "discourse"):
                            relevant[subpath] = item
                        elif key == "active_goal_text" and isinstance(item, str):
                            relevant[subpath] = item
                        else:
                            visit(item, subpath)

            visit(context)
            selected_requests.append({
                "index_line": line_number,
                "request_id": event["request_id"],
                "at_utc": event["at_utc"],
                "event": envelope["event"],
                "selected_context": relevant,
            })
    sessions.append({"source_index": str(BASE / name), "responses": responses,
                     "selected_requests": selected_requests})

destination = Path(__file__).with_name("evidence.json")
destination.write_text(json.dumps(sessions, ensure_ascii=False, indent=2), "utf-8")
for session in sessions:
    surface = [r for r in session["responses"] if r["role"] == "surface"]
    print(Path(session["source_index"]).name, "surface responses:", len(surface))
for request in sessions[-1]["selected_requests"]:
    print(request["at_utc"], json.dumps(request["selected_context"], ensure_ascii=False))
last_root = None
matches = 0
for response in sessions[-1]["responses"]:
    if response["role"] == "executive":
        if response["dialogue"].get("kind") == "move":
            last_root = response["dialogue"]["say"]
    elif response["role"] == "surface":
        assert response["dialogue"]["text"] == last_root
        matches += 1
print("Latest session: exact Root.say / surface.text matches:", matches)
