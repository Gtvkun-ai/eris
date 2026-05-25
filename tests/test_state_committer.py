import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from core.evidence import EvidenceItem
from runtime.cognitive_frame_recorder import CognitiveFrameRecorderMixin
from runtime.state_committer import StateCommitter


class FakeMemoryCore:
    def __init__(self):
        self.requests = []

    def commit(self, request, *, frame=None):
        self.requests.append((request, frame))
        return SimpleNamespace(outcome="accepted", target=getattr(request, "target", None))


def request(**overrides):
    payload = {
        "target": "semantic_memory",
        "content": "User prefers direct technical answers.",
        "confidence": 0.82,
        "evidence_ids": ["ev1"],
        "permission_required": True,
        "storage_permission": True,
        "decay_policy": "normal",
        "reason": "unit test",
    }
    payload.update(overrides)
    return payload


def frame(*, permission=None, evidence=()):
    return SimpleNamespace(
        frame_id="frame-1",
        permission=permission or SimpleNamespace(memory_storable=True, raw_evidence_storable=True),
        evidence=list(evidence),
        debug_notes=[],
        audit_mutations=[],
    )


def get_field(value, name, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


class StateCommitterTests(unittest.TestCase):
    def test_storage_permission_false_rejects_and_does_not_commit(self):
        core = FakeMemoryCore()
        report = StateCommitter(core).commit_requests(
            [request(storage_permission=False)],
            frame=frame(),
        )

        self.assertEqual(report.rejected, 1)
        self.assertEqual(core.requests, [])
        self.assertEqual(report.decisions[0].issues[0].code, "storage_permission_denied")

    def test_low_confidence_rejects_or_commits_as_tentative(self):
        core = FakeMemoryCore()
        committer = StateCommitter(core)

        rejected = committer.commit_requests(
            [request(confidence=0.20)],
            frame=frame(),
        )
        tentative = committer.commit_requests(
            [request(content="A weak but potentially useful fact.", confidence=0.40)],
            frame=frame(),
        )

        self.assertEqual(rejected.rejected, 1)
        self.assertEqual(rejected.decisions[0].issues[0].code, "confidence_too_low")
        self.assertEqual(tentative.tentative, 1)
        self.assertEqual(tentative.committed, 1)
        committed_request = core.requests[-1][0]
        self.assertEqual(get_field(committed_request, "metadata", {})["commit_status"], "tentative")
        self.assertEqual(get_field(committed_request, "decay_policy"), "fast")

    def test_missing_evidence_rejects_except_active_state_or_session_only(self):
        core = FakeMemoryCore()
        committer = StateCommitter(core)

        missing = committer.commit_requests(
            [request(evidence_ids=[])],
            frame=frame(),
        )
        active_state = committer.commit_requests(
            [
                request(
                    target="active_state",
                    content="current task snapshot",
                    evidence_ids=[],
                )
            ],
            frame=frame(),
        )
        session_only = committer.commit_requests(
            [
                request(
                    content="session-local weak note",
                    evidence_ids=[],
                    decay_policy="session_only",
                )
            ],
            frame=frame(),
        )

        self.assertEqual(missing.rejected, 1)
        self.assertEqual(missing.decisions[0].issues[0].code, "missing_evidence_ids")
        self.assertEqual(active_state.committed, 1)
        self.assertEqual(session_only.committed, 1)

    def test_user_correction_reroutes_to_repair_memory(self):
        core = FakeMemoryCore()
        report = StateCommitter(core).commit_requests(
            [
                request(
                    target="semantic_memory",
                    content="wrong_assumption: ERIS inferred the wrong task\nuser_correction: khong phai, sua file test",
                    reason="user correction after assistant misread",
                    tags=["user_correction"],
                    confidence=0.70,
                )
            ],
            frame=frame(),
        )

        self.assertEqual(report.committed, 1)
        self.assertEqual(report.decisions[0].final_target, "repair_memory")
        committed_request = core.requests[0][0]
        self.assertEqual(get_field(committed_request, "target"), "repair_memory")
        self.assertTrue(get_field(committed_request, "metadata", {}).get("user_correction"))

    def test_private_raw_evidence_rejects_without_raw_storage_permission(self):
        evidence = EvidenceItem(
            id="ev_private",
            source_signal_id="raw1",
            source="vision",
            claim="raw private OCR text",
            timestamp=1.0,
            confidence=0.9,
            reliability=0.9,
            raw_or_inferred="raw",
            privacy_level="sensitive",
        )
        core = FakeMemoryCore()
        report = StateCommitter(core).commit_requests(
            [request(evidence_ids=["ev_private"])],
            frame=frame(
                permission=SimpleNamespace(memory_storable=True, raw_evidence_storable=False),
                evidence=[evidence],
            ),
        )

        self.assertEqual(report.rejected, 1)
        self.assertEqual(core.requests, [])
        self.assertEqual(report.decisions[0].issues[0].code, "private_raw_evidence_not_allowed")

    def test_semantic_extracted_fact_rejects_when_source_grounding_is_ungrounded(self):
        core = FakeMemoryCore()
        report = StateCommitter(core).commit_requests(
            [
                request(
                    content={
                        "fact": "The file confirms the parser is broken.",
                        "source": "decision_extracted_fact",
                    },
                    metadata={
                        "semantic_source": "decision_extracted_fact",
                        "source_grounded": False,
                        "grounding_source": "uploaded_file",
                        "grounding_missing_evidence": ["file_evidence"],
                    },
                )
            ],
            frame=SimpleNamespace(
                frame_id="frame-1",
                permission=SimpleNamespace(memory_storable=True, raw_evidence_storable=True),
                evidence=[],
                debug_notes=[],
                audit_mutations=[],
                source_grounding=SimpleNamespace(
                    preempt_mode="filename_only",
                    missing_evidence=("file_evidence",),
                ),
            ),
        )

        self.assertEqual(report.rejected, 1)
        self.assertEqual(core.requests, [])
        self.assertEqual(report.decisions[0].issues[0].code, "semantic_fact_ungrounded")

    def test_recorder_commits_through_state_committer_not_memory_core_directly(self):
        class FakeCommitter:
            def __init__(self):
                self.frames = []

            def commit(self, value):
                self.frames.append(value)
                return SimpleNamespace(requested=0, rejected=0, errors=0)

        class PoisonMemoryCore:
            def __getattr__(self, name):
                raise AssertionError(f"memory_core was accessed directly: {name}")

        class Recorder(CognitiveFrameRecorderMixin):
            pass

        recorder = Recorder()
        recorder.state_committer = FakeCommitter()
        recorder.memory_core = PoisonMemoryCore()
        recorder.logger = SimpleNamespace(warning=lambda *args, **kwargs: None, info=lambda *args, **kwargs: None)
        fake_frame = SimpleNamespace(cycle_id="frame-1")

        result = recorder._commit_frame_through_state_committer(fake_frame)

        self.assertIsNotNone(result)
        self.assertEqual(recorder.state_committer.frames, [fake_frame])

    def test_recorder_finalize_runs_outcome_self_observation_before_commit(self):
        events = []

        class FakeOutcomeObserver:
            def observe(self, frame):
                events.append("outcome")
                frame.outcome = SimpleNamespace(action_success=1.0)
                return frame.outcome

        class FakeSelfObserver:
            def reflect(self, frame, *, outcome=None):
                events.append("self_observation")
                frame.self_observation = SimpleNamespace(should_create_repair_memory=True)
                return frame.self_observation

            def append_repair_commit_request(self, frame, *, report=None, evidence_ids=None):
                events.append("repair_memory")
                frame.commit_requests.append(
                    request(
                        target="repair_memory",
                        content="self observation repair",
                        confidence=0.80,
                        evidence_ids=evidence_ids or ["ev1"],
                        permission_required=False,
                    )
                )
                return frame.commit_requests[-1]

        class Recorder(CognitiveFrameRecorderMixin):
            def _remember_cognitive_frame(self, frame):
                events.append("state_commit_request")
                self._append_commit_requests(
                    frame,
                    [
                        request(
                            target="event_ledger",
                            content={"cycle_id": frame.cycle_id, "outcome": "ok"},
                            confidence=1.0,
                            permission_required=False,
                        )
                    ],
                )

            def _commit_frame_through_state_committer(self, frame):
                events.append("state_commit")
                self.committed_requests = list(frame.commit_requests)
                return SimpleNamespace(committed=len(frame.commit_requests), requested=len(frame.commit_requests), rejected=0, errors=0)

        recorder = Recorder()
        recorder.outcome_observer = FakeOutcomeObserver()
        recorder.self_observer = FakeSelfObserver()
        recorder.semantic_repeat_guard = SimpleNamespace(remember=lambda *args, **kwargs: None)
        recorder.cognitive_frames = []
        recorder.recent_meaning_families = ()
        recorder._preview_text = lambda text, limit=1000: str(text)[:limit]
        recorder.logger = SimpleNamespace(warning=lambda *args, **kwargs: None, info=lambda *args, **kwargs: None)

        fake_frame = SimpleNamespace(
            cycle_id="frame-1",
            channel="chat",
            started_at=1.0,
            final_decision={"text": "ok"},
            meaning_layer=SimpleNamespace(semantic_family=""),
            broadcast=SimpleNamespace(label="test", score=0.7, items=(), content=None),
            speech_core=SimpleNamespace(speech_source="test", utterance_type="reply"),
            appraisal=SimpleNamespace(stance="grounded"),
            action_plan=SimpleNamespace(speech_intent="user_requested", speech_act="answer"),
            evidence=[],
            percepts=(),
            commit_requests=[],
        )

        recorder._finalize_cognitive_frame(fake_frame)

        self.assertEqual(
            events,
            ["outcome", "self_observation", "repair_memory", "state_commit_request", "state_commit"],
        )
        self.assertIsNotNone(fake_frame.outcome)
        self.assertIsNotNone(fake_frame.self_observation)
        self.assertEqual([get_field(item, "target") for item in recorder.committed_requests], ["repair_memory", "event_ledger"])


if __name__ == "__main__":
    unittest.main()
