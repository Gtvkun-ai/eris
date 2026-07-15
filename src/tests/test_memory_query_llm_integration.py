import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from llm.client import LlamaServerClient
from memory.memory_query_llm_parser import MemoryQueryLLMParser
from runtime.memory_recall_adapter import MemoryRecallAdapter, _RuntimeMemoryQueryLLMClient
from runtime.session_turn_ledger import SessionTurnLedger


class _FakeMemoryQueryClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def complete_json(self, *, system: str, user: str, schema: dict):
        self.calls.append(
            {
                "system": system,
                "user": user,
                "schema": schema,
            }
        )
        item = self.outputs.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class _FakeLocalLlamaClient(LlamaServerClient):
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []
        self.base_url = "http://127.0.0.1:8080/v1"
        self.timeout = 180
        self.model_name = "local-test"

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        item = self.outputs.pop(0)
        if isinstance(item, BaseException):
            raise item
        return {"choices": [{"message": {"content": item}}]}


class MemoryQueryLLMParserTests(unittest.TestCase):
    def test_parse_salvages_json_wrapped_in_extra_text(self):
        parser = MemoryQueryLLMParser(
            client=_FakeMemoryQueryClient(
                [
                    'preface {"intent":"recall_turn","target":{"role":"assistant","act":"answer","ordinal":3,"recent":false},"relation":{"type":"answer_to","anchor":{"role":"user","act":"question","ordinal":3,"recent":false}},"surface":"exact","confidence":0.86,"ambiguity":0.12} trailing'
                ]
            )
        )

        result = parser.parse("cau tra loi cua em cho cau hoi thu 3 la gi")

        self.assertIsNotNone(result)
        self.assertEqual(result.intent.value, "recall_turn")
        self.assertEqual(result.target.role.value, "assistant")
        self.assertEqual(result.target.act.value, "answer")
        self.assertEqual(result.relation.relation.value, "answer_to")
        self.assertEqual(result.relation.anchor.ordinal, 3)
        self.assertEqual(result.surface.value, "exact")

    def test_parse_returns_none_for_invalid_json(self):
        parser = MemoryQueryLLMParser(client=_FakeMemoryQueryClient(["not json at all"]))

        result = parser.parse("em noi gi")

        self.assertIsNone(result)


class RuntimeMemoryQueryLLMClientTests(unittest.TestCase):
    def test_from_service_requires_opt_in_and_local_llama_client(self):
        local_service = SimpleNamespace(client=_FakeLocalLlamaClient(['{"confidence":0.8}']))
        remote_service = SimpleNamespace(client=SimpleNamespace(create_chat_completion=lambda **kwargs: {}))

        with patch.dict(os.environ, {}, clear=False):
            self.assertIsNone(_RuntimeMemoryQueryLLMClient.from_service(local_service))

        with patch.dict(os.environ, {"ERIS_MEMORY_QUERY_LLM_ENABLED": "1"}, clear=False):
            self.assertIsNotNone(_RuntimeMemoryQueryLLMClient.from_service(local_service))
            self.assertIsNone(_RuntimeMemoryQueryLLMClient.from_service(remote_service))

    def test_complete_json_applies_timeout_and_confidence_floor(self):
        client = _FakeLocalLlamaClient(
            ['{"intent":"recall_turn","target":{"role":"assistant","act":"answer","recent":true},"relation":{"type":"self"},"surface":"gist","confidence":0.30,"ambiguity":0.70}']
        )
        runtime_client = _RuntimeMemoryQueryLLMClient(
            service=SimpleNamespace(client=client),
            timeout_seconds=1.75,
            max_tokens=111,
            min_confidence=0.45,
        )

        raw = runtime_client.complete_json(
            system="system",
            user="em noi gi",
            schema={"type": "object"},
        )

        self.assertEqual(raw, "")
        self.assertEqual(client.calls[0]["timeout"], 1.75)
        self.assertEqual(client.calls[0]["max_tokens"], 111)


class MemoryRecallAdapterLLMIntegrationTests(unittest.TestCase):
    def _build_ledger(self) -> SessionTurnLedger:
        ledger = SessionTurnLedger()
        ledger.record_user("ban ten gi", timestamp=1.0)
        ledger.record_assistant("Toi la ERIS.", timestamp=2.0, meta={"intent": "answer"})
        ledger.record_user("toi ten la Tin", timestamp=3.0)
        ledger.record_assistant("Toi da nho ten ban.", timestamp=4.0, meta={"intent": "answer"})
        return ledger

    def test_low_ambiguity_recall_does_not_call_llm(self):
        ledger = self._build_ledger()
        local_client = _FakeLocalLlamaClient(
            ['{"intent":"recall_fact","target":{"role":"user","act":"fact_disclosure","fact_key":"user.name","recent":true},"relation":{"type":"self"},"surface":"exact","confidence":0.91,"ambiguity":0.10}']
        )
        service = SimpleNamespace(client=local_client)

        with patch.dict(os.environ, {"ERIS_MEMORY_QUERY_LLM_ENABLED": "1"}, clear=False):
            adapter = MemoryRecallAdapter(
                ledger=ledger,
                llm_service=service,
                semantic_lookup=lambda kind: "Tin" if "name" in kind.value else None,
            )
            decision = adapter.try_answer("toi ten gi")

        self.assertIsNotNone(decision)
        self.assertIn("Tin", decision.text)
        self.assertEqual(local_client.calls, [])

    def test_ambiguous_recall_calls_llm_and_returns_none_on_timeout_when_base_parser_is_still_ambiguous(self):
        ledger = self._build_ledger()
        local_client = _FakeLocalLlamaClient([TimeoutError("memory parser timeout")])
        service = SimpleNamespace(client=local_client)

        with patch.dict(os.environ, {"ERIS_MEMORY_QUERY_LLM_ENABLED": "1"}, clear=False):
            adapter = MemoryRecallAdapter(
                ledger=ledger,
                llm_service=service,
                semantic_lookup=lambda kind: "Tin" if "name" in kind.value else None,
            )
            decision = adapter.try_answer("nho lai cai em vua dap")

        self.assertIsNone(decision)
        self.assertEqual(len(local_client.calls), 1)


if __name__ == "__main__":
    unittest.main()
