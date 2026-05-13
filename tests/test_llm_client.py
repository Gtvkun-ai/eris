import os
import sys
import unittest
from unittest.mock import patch

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from llm.client import LlamaServerClient


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


if __name__ == "__main__":
    unittest.main()
