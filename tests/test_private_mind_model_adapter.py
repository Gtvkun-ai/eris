import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from runtime.private_mind_model_adapter import PrivateMindModelAdapterConfig, RuntimePrivateMindModelAdapter
from cortex.private_mind.contracts import EvidenceDossier


def _adapter() -> RuntimePrivateMindModelAdapter:
    return RuntimePrivateMindModelAdapter()


class FakeJsonService:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create_chat_completion(self, *, messages, temperature, max_tokens, response_format):
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": response_format,
            }
        )
        content = self.responses.pop(0) if self.responses else "not json"
        return {"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 1}}


class FakeLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, message, *args):
        self.warnings.append((message, args))


def test_private_mind_json_parser_accepts_markdown_wrapped_object() -> None:
    content = """Here is the JSON:
```json
{"claim":"ok","confidence":0.7,"metadata":{"theme":"private"}}
```
No public reply."""

    parsed = _adapter()._parse_json(content)

    assert parsed["claim"] == "ok"
    assert parsed["metadata"]["theme"] == "private"


def test_private_mind_json_parser_accepts_fence_embedded_in_prose() -> None:
    content = 'prefix before fence ```json\n{"claim":"ok","confidence":0.7}\n``` suffix after fence'

    parsed = _adapter()._parse_json(content)

    assert parsed["claim"] == "ok"


def test_private_mind_json_parser_repairs_trailing_commas() -> None:
    content = '{"claim":"ok","confidence":0.7,"evidence_ids":["ev1",],"metadata":{"theme":"x",},}'

    parsed = _adapter()._parse_json(content)

    assert parsed["evidence_ids"] == ["ev1"]
    assert parsed["metadata"]["theme"] == "x"


def test_private_mind_json_parser_repairs_truncated_object() -> None:
    content = 'prefix {"dominant_judgment":"ok","confidence":0.76,"private_concern_update":{"theme":"json"'

    parsed = _adapter()._parse_json(content)

    assert parsed["dominant_judgment"] == "ok"
    assert parsed["private_concern_update"]["theme"] == "json"


def test_private_mind_json_retry_repairs_invalid_first_response() -> None:
    service = FakeJsonService(["Here is prose, not JSON.", '{"claim":"ok","confidence":0.7}'])
    adapter = RuntimePrivateMindModelAdapter(llm_service=service)

    result = adapter._tracked_chat_json([{"role": "system", "content": "Return JSON"}], max_tokens=128)

    assert result.ok is True
    assert result.parsed["claim"] == "ok"
    assert [call["temperature"] for call in service.calls] == [0.15, 0.0]
    assert service.calls[1]["messages"][0]["content"].startswith("Return only one JSON object. No markdown. No prose. No code fence.")
    assert "Here is prose" in service.calls[1]["messages"][-1]["content"]


def test_private_mind_response_schema_is_only_attached_for_gemini() -> None:
    schema = {"type": "object", "properties": {"claim": {"type": "string"}}}
    gemini = RuntimePrivateMindModelAdapter(config=PrivateMindModelAdapterConfig(provider="gemini"))
    llama = RuntimePrivateMindModelAdapter(config=PrivateMindModelAdapterConfig(provider="llama_server"))

    assert gemini._response_format(schema)["schema"] == schema
    assert llama._response_format(schema) == {"type": "json_object"}


def test_private_mind_json_cooldown_after_three_invalid_results() -> None:
    service = FakeJsonService(["not json"] * 20)
    logger = FakeLogger()
    adapter = RuntimePrivateMindModelAdapter(llm_service=service, logger=logger)

    for _ in range(3):
        result = adapter._tracked_chat_json([{"role": "system", "content": "Return JSON"}], max_tokens=128)
        assert result.ok is False
        assert result.error == "invalid_json"

    assert len(service.calls) == 6
    assert adapter.debug_status()["invalid_json_streak"] == 3
    assert adapter.debug_status()["json_cooldown_until"] > 0
    assert adapter.debug_status()["api_degraded"] is True
    assert len(logger.warnings) == 1

    skipped = adapter._tracked_chat_json([{"role": "system", "content": "Return JSON"}], max_tokens=128)

    assert skipped.ok is False
    assert skipped.error == "invalid_json_cooldown"
    assert len(service.calls) == 6
    assert len(logger.warnings) == 1


def test_private_mind_json_cooldown_skips_evaluator_without_warning_spam() -> None:
    service = FakeJsonService(["not json"] * 20)
    logger = FakeLogger()
    adapter = RuntimePrivateMindModelAdapter(llm_service=service, logger=logger)
    dossier = EvidenceDossier(dossier_id="dossier.test")
    for _ in range(3):
        adapter._tracked_chat_json([{"role": "system", "content": "Return JSON"}], max_tokens=128)
    warning_count = len(logger.warnings)

    fragment = adapter.evaluate_fragment("intent_evaluator", dossier)

    assert fragment is None
    assert len(service.calls) == 6
    assert len(logger.warnings) == warning_count
