"""A first complete activity slice: Python tracing, delivered through existing artifacts.

The answer key is server-owned. Browser buttons submit an ordinary user event;
only its actual text can select an answer. No client 'passed' field is trusted.
"""

from __future__ import annotations

import re
import secrets
import time
from pathlib import Path

from runtime.learning_core import KnowledgePoint, LearningPath
from runtime.learning_core.records import AssessmentAttempt, DomainSpec, digest
from runtime.workspace.artifact_protocol import build_artifact, build_bundle, write_bundle_sidecar
from .sources import text_spans

REFERENCE = (
    "range(start, stop, step) sinh các số bắt đầu ở start và không lấy stop. "
    "Nếu bỏ start thì bắt đầu từ 0. Vòng for lần lượt gán từng phần tử cho biến lặp. "
    "Với total += n, mỗi lượt cộng n vào giá trị total hiện có. "
    "Toán tử n % 2 cho phần dư khi chia n cho 2; phần dư 0 là số chẵn."
)
PYTHON_DOMAIN = DomainSpec("python-basics", "Python căn bản", "python:v1", capabilities=("choice", "short_answer"))
PRESETS = {
    "python.range": {
        "kp_id": "python:v1:range",
        "title": "Điểm dừng của range",
        "code": "print(list(range(2, 8, 2)))",
        "question": "Chưa chạy mã: bạn dự đoán dòng này in ra gì?",
        "options": ["[2, 4, 6]", "[2, 4, 6, 8]", "[0, 2, 4, 6]"],
        "correct": 0,
        "hints": [
            "Hãy xác định số bắt đầu và bước nhảy trước.",
            "Điểm stop không nằm trong dãy. Liệt kê từng giá trị nhỏ hơn 8.",
        ],
        "explanation": "Bắt đầu ở 2, mỗi lần tăng 2 và dừng trước 8: [2, 4, 6].",
    },
    "python.accumulator": {
        "kp_id": "python:v1:accumulator",
        "title": "Theo dõi biến tích lũy",
        "code": "total = 0\nfor n in range(1, 4):\n    total += n\nprint(total)",
        "question": "Giá trị cuối của total là bao nhiêu?",
        "options": ["4", "6", "10"],
        "correct": 1,
        "hints": [
            "Viết ra các giá trị mà n lần lượt nhận.",
            "total giữ kết quả của lượt trước; hãy theo dõi từng phép cộng.",
        ],
        "explanation": "n lần lượt là 1, 2, 3; total lần lượt là 1, 3, 6.",
    },
    "python.filter": {
        "kp_id": "python:v1:filter",
        "title": "Kết hợp điều kiện và vòng lặp",
        "code": "total = 0\nfor n in range(1, 6):\n    if n % 2 == 0:\n        total += n\nprint(total)",
        "question": "Không chạy mã: chương trình in ra số nào?",
        "options": ["15", "9", "6"],
        "correct": 2,
        "hints": ["Chỉ một số giá trị n đi vào nhánh if.", "Lọc những số chia hết cho 2 rồi mới cộng chúng lại."],
        "explanation": "Trong 1, 2, 3, 4, 5, chỉ 2 và 4 qua điều kiện; tổng là 6.",
    },
}

EVENT = re.compile(r"^ERIS_LEARN (answer|hint|reveal) (activity:[a-f0-9]{32}) ([a-f0-9]{32})(?: ([0-9]))?$")


def tracing_variant(preset, seed):
    item = dict(PRESETS[preset])
    if preset == "python.range":
        start, step = 1 + seed % 7, 1 + (seed // 7) % 4
        stop = start + 3 * step
        values = list(range(start, stop, step))
        item.update(
            code=f"print(list(range({start}, {stop}, {step})))",
            options=[str(values), str(values + [stop]), str([start - step] + values)],
            explanation=f"Bắt đầu ở {start}, tăng {step} mỗi lần và dừng trước {stop}: {values}.",
            hints=[
                "Tìm giá trị bắt đầu và bước nhảy.",
                "Điểm stop không nằm trong dãy; liệt kê từng giá trị trước nó.",
            ],
        )
    elif preset == "python.accumulator":
        end = 3 + seed % 7
        total = end * (end + 1) // 2
        item.update(
            code=f"total = 0\nfor n in range(1, {end + 1}):\n    total += n\nprint(total)",
            options=[str(total), str(end), str(total + end + 1)],
            explanation=f"n lần lượt từ 1 tới {end}; cộng từng giá trị vào total được {total}.",
        )
    else:
        end = 6 + seed % 9
        even = sum(n for n in range(1, end + 1) if n % 2 == 0)
        total = end * (end + 1) // 2
        item.update(
            code=f"total = 0\nfor n in range(1, {end + 1}):\n    if n % 2 == 0:\n        total += n\nprint(total)",
            options=[str(even), str(total), str(total - even)],
            explanation=f"Chỉ cộng các số chẵn từ 1 tới {end}; kết quả là {even}.",
        )
    rotation = seed % 3
    item["options"] = item["options"][rotation:] + item["options"][:rotation]
    item["correct"] = (-rotation) % 3
    return item


class LearningActivities:
    def __init__(self, learning, *, workspace=None):
        self.learning = learning
        self.store = learning._store
        self.workspace = workspace

    def readiness(self):
        # These are tracing questions, not arbitrary Python execution.
        return {
            "choice": True,
            "short_answer": True,
            "python_exec": False,
            "math_input": False,
            "graph_manipulation": False,
        }

    def create(self, *, event, preset="python.range", now=None):
        if preset not in PRESETS:
            raise ValueError("unsupported_activity_preset")
        now = time.time() if now is None else float(now)
        self.learning.register_domain(PYTHON_DOMAIN)
        path = LearningPath(
            "python-basics:v1",
            "Python căn bản",
            "Đọc và dự đoán mã Python",
            tuple(KnowledgePoint(p["kp_id"], p["title"], "procedure") for p in PRESETS.values()),
            source="eris_auto",
            domain_id=PYTHON_DOMAIN.domain_id,
        )
        existing = self.store.load_path(path.path_id)
        if existing is None:
            self.learning.register_path(path, now=now)
        source_id = "eris-python-reference-v1"
        spans = text_spans(
            domain_id=PYTHON_DOMAIN.domain_id,
            source_id=source_id,
            text=REFERENCE,
            origin="https://docs.python.org/3/tutorial/controlflow.html#the-range-function",
            source_kind="model_summary",
            now=0.0,
        )
        self.learning.import_source_spans(spans)
        activity_id = "activity:" + digest([event.session_id, event.event_id, preset])[:32]
        existing_activity = self.store.load_activity(activity_id)
        if existing_activity:
            return existing_activity
        # An explicit activity request may switch to its path; no activation on read.
        self.learning.activate_path(path.path_id)
        seed = int(digest([event.event_id, preset])[:8], 16)
        item = tracing_variant(preset, seed)
        previous = self.store.latest_activity(preset)
        if previous and previous["code"] == item["code"]:
            item = tracing_variant(preset, seed + 1)
        item.update(
            activity_id=activity_id,
            preset=preset,
            path_id=path.path_id,
            base_revision=self.store.path_revision(path.path_id),
            session_id=event.session_id,
            generation=int(event.generation),
            nonce=secrets.token_hex(16),
            delivered=False,
            closed=False,
            created_at=now,
            expires_at=now + 86400,
            source_refs=[s.span_id for s in spans],
            hint_count=0,
        )
        self.store.save_activity(item)
        return item

    def bundle(self, item):
        code = item["code"]
        source = item["question"] + "\n\n" + chr(96) * 3 + "python\n" + code + "\n" + chr(96) * 3
        source += "\n\nHãy chọn đáp án bên dưới. Bạn có thể xin gợi ý trước khi nộp bài."
        public = {
            "activity_id": item["activity_id"],
            "nonce": item["nonce"],
            "revision": item["base_revision"],
            "options": item["options"],
        }
        turn_id = "job:" + item["activity_id"]
        artifact = build_artifact(
            turn_id=turn_id,
            source="tutor_activity",
            kind="document",
            content={"format": "markdown", "source": source, "activity": public},
            stable_key=item["activity_id"],
            title=item["title"],
        )
        bundle = build_bundle(turn_id, [artifact], stable_key=item["activity_id"])
        import os

        workspace = self.workspace or os.getenv("ERIS_ARTIFACT_WORKSPACE", "logs/eris_artifacts")
        write_bundle_sidecar(bundle, Path(workspace))
        return bundle["intent_id"]

    @staticmethod
    def command(item, action, answer=None):
        return f"ERIS_LEARN {action} {item['activity_id']} {item['nonce']}" + (
            f" {answer}" if answer is not None else ""
        )

    def mark_delivered(self, activity_id, *, receipt):
        item = self.store.load_activity(activity_id)
        if (
            not item
            or not receipt.successful
            or receipt.session_id != item["session_id"]
            or receipt.generation != item["generation"]
        ):
            return False
        item["delivered"] = True
        self.store.save_activity(item)
        self.store.register_assistance(activity_id, item["kp_id"])
        return True

    def handle_event(self, event, *, now=None):
        match = EVENT.fullmatch(str(event.text or "").strip())
        if match is None:
            # Intake may coalesce several real button messages with newlines.
            # Ignore a help request that has not been delivered yet when a
            # later answer was submitted; never extract commands from prose.
            lines = [line.strip() for line in str(event.text or "").splitlines() if line.strip()]
            batch = [EVENT.fullmatch(line) for line in lines]
            if batch and all(batch) and len({(entry.group(2), entry.group(3)) for entry in batch}) == 1:
                answers = [entry for entry in batch if entry.group(1) == "answer"]
                match = answers[-1] if answers else batch[-1]
        if match is None:
            raise ValueError("expected_actual_activity_user_event")
        action, activity_id, nonce, answer = match.groups()
        item = self.store.load_activity(activity_id)
        now = time.time() if now is None else float(now)
        if not item or not secrets.compare_digest(item["nonce"], nonce):
            raise ValueError("unknown_activity")
        if item["session_id"] != event.session_id or not item["delivered"]:
            raise ValueError("activity_not_delivered_in_this_session")
        if now > item["expires_at"] or self.store.path_revision(item["path_id"]) != item["base_revision"]:
            raise ValueError("activity_expired_or_stale")
        attempt_id = "attempt:" + digest(activity_id)[:32]
        previous = self.store.load_attempt(attempt_id)
        if previous:
            return {"status": "completed", "duplicate": True, "attempt": previous.to_dict()}
        if item["closed"]:
            raise ValueError("activity_closed")
        if action != "answer":
            hints = item["hints"]
            index = min(item["hint_count"], len(hints) - 1)
            return {
                "status": "completed",
                "activity_id": activity_id,
                "help_kind": "answer_revealed" if action == "reveal" else "hinted",
                "help_event_id": "help:" + digest(event.event_id)[:32],
                "hint_count": item["hint_count"] + 1,
                "instruction": item["explanation"] if action == "reveal" else hints[index],
            }
        if answer is None or not 0 <= int(answer) < len(item["options"]):
            raise ValueError("invalid_activity_answer")
        correct = int(answer) == item["correct"]
        help_state = self.store.assistance_for(activity_id)
        attempt = AssessmentAttempt(
            attempt_id,
            item["kp_id"],
            "correct" if correct else "incorrect",
            "quiz_correct" if correct else "quiz_incorrect",
            strength=1.0 if correct else 0.0,
            interaction_id=activity_id,
            turn_id=event.event_id,
            path_id=item["path_id"],
            item_id=item["preset"] + ":" + digest(item["code"])[:16],
            item_family_id=item["preset"],
            activity_id=activity_id,
            assistance=help_state["assistance"],
            hint_count=help_state.get("hint_count", 0),
            answer_revealed=help_state["assistance"] == "answer_revealed",
            rubric_version="python-tracing-v1",
            assessor_version="choice-key-v1",
            source_refs=tuple(item["source_refs"]),
            recorded_at=now,
            answer_ref="choice:" + answer,
            error_code="" if correct else "trace-step",
        )
        committed = self.learning.record_attempt(attempt)
        item["closed"] = True
        self.store.save_activity(item)
        return {
            "status": "completed",
            "committed": committed,
            "attempt": attempt.to_dict(),
            "feedback": item["explanation"],
            "next_step": "independent_variant" if help_state["assistance"] != "independent" else "continue",
            "retention": self.learning.retention_snapshot(item["kp_id"]),
        }

    def commit_help(self, data):
        item = self.store.load_activity(data["activity_id"])
        if item is None or item["closed"]:
            return False
        state = self.store.record_assistance(
            item["activity_id"],
            event_id=data["help_event_id"],
            assistance=data["help_kind"],
            hint_count=data["hint_count"],
        )
        item["hint_count"] = state.get("hint_count", 0)
        self.store.save_activity(item)
        return True
