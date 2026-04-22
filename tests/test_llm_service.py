import os
import sys
import unicodedata
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from llm.service import LlmService


def _norm(text: str) -> str:
    lowered = unicodedata.normalize("NFD", text.lower())
    lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
    lowered = lowered.replace("đ", "d")
    lowered = lowered.replace("Ä‘", "d")
    return " ".join(lowered.split())


class _FakeClient:
    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        content = self.contents.pop(0)
        return {"choices": [{"message": {"content": content}}]}


class LlmServiceTests(unittest.TestCase):
    def test_directive_includes_autonomous_behavior_prompt(self):
        client = _FakeClient(
            [
                (
                    '{"text":"mot y nghi ngan","animation":"stand",'
                    '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                    '"debug_trace":"","next_animation":"","system_action":"","action_input":""}'
                ),
            ]
        )
        service = LlmService(client)

        service.generate_directive(telemetry_data="focus=general")

        system_prompt = client.calls[0]["messages"][0]["content"]
        user_prompt = client.calls[0]["messages"][1]["content"]
        self.assertIn("autonomous mode", system_prompt.lower())
        self.assertIn("search_web", system_prompt)
        self.assertIn("khong nhu thong bao he thong", _norm(system_prompt))
        self.assertIn("doc thoai", _norm(user_prompt))

    def test_chat_reply_repairs_non_json_with_second_pass(self):
        client = _FakeClient(
            [
                "Xin chào. Tôi đang ở đây.",
                (
                    '{"text":"Xin chào. Tôi đang ở đây.","animation":"stand",'
                    '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                    '"debug_trace":"repair","next_animation":"","system_action":"","action_input":""}'
                ),
            ]
        )
        service = LlmService(client)

        raw = service.generate_chat_reply(chat_history=[], user_message="xin chào")

        self.assertEqual(len(client.calls), 2)
        self.assertIn('"animation":"stand"', raw)
        self.assertIn('"debug_trace":"repair"', raw)

    def test_directive_wraps_plain_text_into_safe_json_if_repair_fails(self):
        client = _FakeClient(
            [
                "Hãy trở lại với dự án.",
                "Văn bản thường tiếp tục không phải JSON",
            ]
        )
        service = LlmService(client)

        raw = service.generate_directive(telemetry_data="focus=general")

        self.assertEqual(len(client.calls), 2)
        self.assertIn('"text": "Hãy trở lại với dự án."', raw)
        self.assertIn('"animation": "stand"', raw)
        self.assertIn("wrapped non-JSON directive reply", raw)

    def test_extracts_embedded_json_without_repair(self):
        client = _FakeClient(
            [
                'Trước khi trả lời: {"text":"ok","animation":"stand",'
                '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                '"debug_trace":"embedded","next_animation":"","system_action":"","action_input":""}',
            ]
        )
        service = LlmService(client)

        raw = service.generate_chat_reply(chat_history=[], user_message="xin chào")

        self.assertEqual(len(client.calls), 1)
        self.assertTrue(raw.startswith("{"))
        self.assertIn('"debug_trace":"embedded"', raw)

    def test_repairs_json_with_invalid_schema_values(self):
        client = _FakeClient(
            [
                (
                    '{"text":"Sai schema","animation":"idle",'
                    '"direction":"focus","target_x":512,"bounce_action":"","extracted_fact":"",'
                    '"debug_trace":"","next_animation":"","system_action":"","action_input":""}'
                ),
                (
                    '{"text":"Sai schema","animation":"stand",'
                    '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                    '"debug_trace":"repair","next_animation":"","system_action":"","action_input":""}'
                ),
            ]
        )
        service = LlmService(client)

        raw = service.generate_directive(telemetry_data="focus=general")

        self.assertEqual(len(client.calls), 2)
        self.assertIn('"animation":"stand"', raw)
        self.assertIn('"direction":0', raw)
        self.assertIn('"target_x":-1.0', raw)

    def test_directive_adds_resource_guard_style_constraints(self):
        client = _FakeClient(
            [
                (
                    '{"text":"ngan gon","animation":"stand",'
                    '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                    '"debug_trace":"","next_animation":"","system_action":"","action_input":""}'
                ),
            ]
        )
        service = LlmService(client)

        service.generate_directive(
            telemetry_data="focus=general",
            ti_context="Mode: resource_guard.\nLy do: tai nguyen cao.",
        )

        user_prompt = client.calls[0]["messages"][1]["content"]
        self.assertIn("khong mo dau bang 'du lieu he thong'", _norm(user_prompt))
        self.assertIn("toi se bat buoc", _norm(user_prompt))

    def test_directive_prompt_discourages_overmanaged_language(self):
        client = _FakeClient(
            [
                (
                    '{"text":"ngan gon","animation":"stand",'
                    '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                    '"debug_trace":"","next_animation":"","system_action":"","action_input":""}'
                ),
            ]
        )
        service = LlmService(client)

        service.generate_directive(
            telemetry_data="focus=general",
            ti_context="Mode: steady_observe.\nLy do: quan sat.",
        )

        system_prompt = client.calls[0]["messages"][0]["content"]
        user_prompt = client.calls[0]["messages"][1]["content"]
        self.assertIn("dong bo hoa nhip do", _norm(system_prompt))
        self.assertIn("trong ba phut toi", _norm(system_prompt))
        self.assertIn("mot phan mem duy nhat", _norm(user_prompt))


if __name__ == "__main__":
    unittest.main()
