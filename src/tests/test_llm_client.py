import os
import sys
import unittest
from unittest.mock import patch

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from llm.client import GeminiClient, LlamaServerClient, OpenAICompatibleClient


class OpenAICompatibleClientTests(unittest.TestCase):
    def test_json_object_response_format_appends_json_instruction_to_last_message(self):
        calls = []

        def fake_post(url, headers, json, timeout):
            calls.append(json)
            return _FakeResponse(payload={"choices": [{"message": {"content": "{}"}}]})

        with patch("llm.client.requests.post", side_effect=fake_post):
            client = OpenAICompatibleClient("https://api.test.com/v1", "test-key", "gpt-4o-mini")
            
            # Case 1: Message does not contain "json"
            client.create_chat_completion(
                messages=[{"role": "system", "content": "You are a helper."}, {"role": "user", "content": "Hello world"}],
                temperature=0.0,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                max_tokens=32,
                response_format={"type": "json_object"},
            )
            self.assertEqual(len(calls), 1)
            last_message_content = calls[0]["messages"][-1]["content"]
            self.assertIn("Return the output in json format.", last_message_content)

            # Case 2: Message already contains "json" (lowercase)
            calls.clear()
            client.create_chat_completion(
                messages=[{"role": "user", "content": "Give me a json string of facts."}],
                temperature=0.0,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                max_tokens=32,
                response_format={"type": "json_object"},
            )
            self.assertEqual(len(calls), 1)
            last_message_content = calls[0]["messages"][-1]["content"]
            self.assertNotIn("Return the output in json format.", last_message_content)

            # Case 3: Message contains "JSON" (uppercase)
            calls.clear()
            client.create_chat_completion(
                messages=[{"role": "user", "content": "Output in JSON"}],
                temperature=0.0,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                max_tokens=32,
                response_format={"type": "json_object"},
            )
            self.assertEqual(len(calls), 1)
            last_message_content = calls[0]["messages"][-1]["content"]
            # It should realize it contains JSON case-insensitively, so it should NOT append!
            self.assertNotIn("Return the output in json format.", last_message_content)


class _FakeResponse:
    def __init__(self, *, status_code=200, payload=None, text="", reason="OK", url="http://test"):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.reason = reason
        self.url = url

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"{self.status_code} Client Error: {self.reason} for url: {self.url}",
                response=self,
            )


class LlamaServerClientTests(unittest.TestCase):
    def test_retries_without_grammar_when_local_server_rejects_structured_payload(self):
        calls = []

        def fake_get(*args, **kwargs):
            return _FakeResponse(payload={"data": [{"id": "local-test"}]})

        def fake_post(url, *, json, timeout):
            calls.append(json)
            if len(calls) == 1:
                return _FakeResponse(
                    status_code=400,
                    text='{"error":"grammar and response_format conflict"}',
                    reason="Bad Request",
                    url=url,
                )
            return _FakeResponse(payload={"choices": [{"message": {"content": "ok"}}]})

        with patch("llm.client.requests.get", side_effect=fake_get), patch(
            "llm.client.requests.post", side_effect=fake_post
        ):
            client = LlamaServerClient("http://127.0.0.1:8080/v1")
            response = client.create_chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.0,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                max_tokens=8,
                response_format={"type": "json_object"},
                grammar="root ::= \"ok\"",
            )

        self.assertEqual(response["choices"][0]["message"]["content"], "ok")
        self.assertIn("grammar", calls[0])
        self.assertNotIn("grammar", calls[1])
        self.assertIn("response_format", calls[1])

    def test_http_error_includes_llama_server_body_after_retries_fail(self):
        def fake_get(*args, **kwargs):
            return _FakeResponse(payload={"data": [{"id": "local-test"}]})

        def fake_post(url, *, json, timeout):
            return _FakeResponse(
                status_code=400,
                text='{"error":"unsupported request"}',
                reason="Bad Request",
                url=url,
            )

        with patch("llm.client.requests.get", side_effect=fake_get), patch(
            "llm.client.requests.post", side_effect=fake_post
        ):
            client = LlamaServerClient("http://127.0.0.1:8080/v1")
            with self.assertRaises(requests.HTTPError) as ctx:
                client.create_chat_completion(
                    messages=[{"role": "user", "content": "hi"}],
                    temperature=0.0,
                    frequency_penalty=0.0,
                    presence_penalty=0.0,
                    max_tokens=8,
                    response_format={"type": "json_object"},
                    grammar="root ::= \"ok\"",
                )

        self.assertIn("unsupported request", str(ctx.exception))


class GeminiClientTests(unittest.TestCase):
    def test_json_object_response_format_maps_to_gemini_schema_payload(self):
        calls = []

        def fake_post(url, *, headers, json, timeout):
            calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return _FakeResponse(payload={"candidates": [{"content": {"parts": [{"text": '{"ok":true}'}]}}]})

        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        }
        with patch("llm.client.requests.post", side_effect=fake_post):
            client = GeminiClient("https://generativelanguage.googleapis.com/v1beta", "test-key", "gemini-2.5-flash")
            response = client.create_chat_completion(
                messages=[{"role": "system", "content": "Return JSON"}, {"role": "user", "content": "hi"}],
                temperature=0.0,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                max_tokens=32,
                response_format={"type": "json_object", "schema": schema},
            )

        self.assertIn("candidates", response)
        generation_config = calls[0]["json"]["generationConfig"]
        self.assertEqual(generation_config["responseMimeType"], "application/json")
        self.assertEqual(generation_config["responseSchema"], schema)
        self.assertEqual(generation_config["thinkingConfig"], {"thinkingBudget": 1024})

        # Verify that passing reasoning_effort="none" explicitly sets thinkingBudget to 0
        calls.clear()
        with patch("llm.client.requests.post", side_effect=fake_post):
            client.create_chat_completion(
                messages=[{"role": "system", "content": "Return JSON"}, {"role": "user", "content": "hi"}],
                temperature=0.0,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                max_tokens=32,
                response_format={"type": "json_object", "schema": schema},
                reasoning_effort="none",
            )
        generation_config_none = calls[0]["json"]["generationConfig"]
        self.assertEqual(generation_config_none["thinkingConfig"], {"thinkingBudget": 0})


class GemmaPayloadHygieneTests(unittest.TestCase):
    def _capture_payload(self, model_name, response_format=None):
        captured = {}

        def fake_post(url, *, headers, json, timeout):
            captured["json"] = json
            return _FakeResponse(payload={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})

        with patch("llm.client.requests.post", side_effect=fake_post):
            client = GeminiClient("https://generativelanguage.googleapis.com/v1beta", "k", model_name)
            client.create_chat_completion(
                messages=[{"role": "system", "content": "S"}, {"role": "user", "content": "hi"}],
                temperature=0.0,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                max_tokens=16,
                response_format=response_format,
            )
        return captured["json"]

    def test_gemma_drops_safety_settings_and_structured_output(self):
        payload = self._capture_payload("gemma-4-26b-a4b-it", response_format={"type": "json_object"})
        self.assertNotIn("safetySettings", payload)
        self.assertNotIn("systemInstruction", payload)  # folded into user turn
        self.assertNotIn("responseMimeType", payload["generationConfig"])
        self.assertNotIn("responseSchema", payload["generationConfig"])

    def test_real_gemini_keeps_safety_settings(self):
        payload = self._capture_payload("gemini-2.5-flash", response_format={"type": "json_object"})
        self.assertIn("safetySettings", payload)
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")


if __name__ == "__main__":
    unittest.main()
