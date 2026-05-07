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
        self.assertIn("dung tu tao chu de rieng", _norm(user_prompt))
        self.assertIn("machine context chi la nen tham khao", _norm(system_prompt))
        self.assertIn("speech evidence da loc", _norm(user_prompt))
        self.assertIn("khong phai telemetry tho", _norm(user_prompt))
        self.assertIn("speech intent", _norm(user_prompt))
        self.assertIn("screen_observation", user_prompt)
        self.assertIn("tranh mo cau bang viec mo ta app", _norm(user_prompt))

    def test_directive_includes_appraisal_context_as_preverbal_state(self):
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
            appraisal_context=(
                "expressive/appraisal state: pre-verbal attitude only, "
                "not an inner feeling claim."
            ),
        )

        system_prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("expressive/appraisal state", system_prompt)
        self.assertIn("pre-verbal attitude", system_prompt)
        self.assertIn("not an inner feeling claim", system_prompt)

    def test_directive_includes_persistent_internal_state_context(self):
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
            internal_state_context="persistent_internal_state: runtime continuity only, not current screen evidence.",
        )

        system_prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("persistent_internal_state", system_prompt)
        self.assertIn("not current screen evidence", system_prompt)

    def test_directive_includes_typed_memory_context(self):
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
            memory_context="norm_memory:\n- deviation: active_app current=YouTube baseline=VS Code",
        )

        system_prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("Memory context for continuity", system_prompt)
        self.assertIn("norm_memory", system_prompt)
        self.assertIn("Do not treat memory as current screen evidence", system_prompt)

    def test_directive_includes_action_plan_context(self):
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
            ti_context=(
                "Mode: steady_observe.\n"
                "ActionPlanner decision before LLM:\n"
                "- should_speak=true\n"
                "- speech_act=telemetry_comment\n"
                "- reason_to_speak=Concrete signal is available before LLM\n"
                "- risk_flags=none"
            ),
            speech_intent="screen_observation",
        )

        user_prompt = client.calls[0]["messages"][1]["content"]
        self.assertIn("Action plan bắt buộc", user_prompt)
        self.assertIn("speech_act=telemetry_comment", user_prompt)
        self.assertIn("reason_to_speak=Concrete signal is available before LLM", user_prompt)

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

    def test_chat_reply_can_attach_screen_image(self):
        client = _FakeClient(
            [
                (
                    '{"text":"Toi thay mot trinh duyet.","animation":"stand",'
                    '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                    '"debug_trace":"","next_animation":"","system_action":"","action_input":""}'
                ),
            ]
        )
        service = LlmService(client)

        service.generate_chat_reply(
            chat_history=[],
            user_message="ban thay man hinh khong",
            screen_image_data_uri="data:image/jpeg;base64,abc",
        )

        content = client.calls[0]["messages"][-1]["content"]
        self.assertIsInstance(content, list)
        self.assertEqual(content[0]["type"], "image_url")
        self.assertEqual(content[0]["image_url"]["url"], "data:image/jpeg;base64,abc")
        self.assertIn("screenshot", content[1]["text"].lower())

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

    def test_coerces_json_with_missing_required_fields_without_repair(self):
        client = _FakeClient(
            [
                (
                    '{"text":"Sai schema","animation":"idle",'
                    '"direction":"focus","target_x":512}'
                ),
            ]
        )
        service = LlmService(client)

        raw = service.generate_directive(telemetry_data="focus=general")

        self.assertEqual(len(client.calls), 1)
        self.assertIn('"animation": "stand"', raw)
        self.assertIn('"direction": 0', raw)
        self.assertIn('"target_x": -1.0', raw)
        self.assertNotIn("wrapped non-JSON directive reply", raw)
        self.assertIn("sanitized decision-like JSON", raw)

    def test_coerces_partial_decision_json_without_wrapping_it_inside_text(self):
        partial_decision = (
            '{"text":"Một câu ngắn đã được đặt ở tầng ngoài cùng.",'
            '"animation":"","direction":0,"target_x":0.5,"bounce_action":"","extracted_fact":""}'
        )
        client = _FakeClient([partial_decision])
        service = LlmService(client)

        raw = service.generate_directive(telemetry_data="focus=general")

        self.assertEqual(len(client.calls), 1)
        self.assertIn('"text": "Một câu ngắn đã được đặt ở tầng ngoài cùng."', raw)
        self.assertIn('"animation": "stand"', raw)
        self.assertIn('"target_x": -1.0', raw)
        self.assertNotIn('"{ \\"text\\"', raw)
        self.assertNotIn("wrapped non-JSON directive reply", raw)

    def test_coerces_decision_json_with_spaced_field_names_without_wrapping(self):
        client = _FakeClient(
            [
                (
                    '{"text":"Co ve moi thu dang chay kha on."," animation":"sit",'
                    '" direction":0," target_x":0.5," bounce_action":"",'
                    '" extracted_fact":""," debug_trace":""," next_animation":"",'
                    '" system_action":""," action_input":""}'
                ),
            ]
        )
        service = LlmService(client)

        raw = service.generate_directive(telemetry_data="focus=general")

        self.assertEqual(len(client.calls), 1)
        self.assertIn('"text": "Co ve moi thu dang chay kha on."', raw)
        self.assertIn('"animation": "sit"', raw)
        self.assertIn('"target_x": -1.0', raw)
        self.assertNotIn('" animation"', raw)
        self.assertNotIn("wrapped non-JSON directive reply", raw)
        self.assertIn("sanitized decision-like JSON", raw)

    def test_sanitizes_decision_like_json_without_fallback_wrapping(self):
        invalid_but_decision_like = (
            '{"text":"Co ve Ngai dang phan tan mot chut.","animation":"subtle_sigh",'
            '"direction":"soft","target_x":0.5,"bounce_action":null,'
            '"extracted_fact":["attention drift"],"debug_trace":["fragmented focus"],'
            '"next_animation":null,"system_action":"","action_input":"none"}'
        )
        client = _FakeClient([invalid_but_decision_like])
        service = LlmService(client)

        raw = service.generate_directive(telemetry_data="focus=general")

        self.assertEqual(len(client.calls), 1)
        self.assertIn('"text": "Co ve Ngai dang phan tan mot chut."', raw)
        self.assertIn('"animation": "stand"', raw)
        self.assertIn('"direction": 0', raw)
        self.assertIn('"target_x": -1.0', raw)
        self.assertIn('"extracted_fact": "attention drift"', raw)
        self.assertIn('"action_input": ""', raw)
        self.assertNotIn("wrapped non-JSON directive reply", raw)
        self.assertIn("sanitized decision-like JSON", raw)

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
        self.assertIn("khong dung an du lung lo", _norm(user_prompt))
        self.assertIn("may dang nang", _norm(user_prompt))

    def test_directive_prompt_can_exclude_recent_text(self):
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
            avoid_text="Cửa sổ mở ra thì không ai biết nó sẽ đóng lại lúc nào.",
        )

        user_prompt = client.calls[0]["messages"][1]["content"]
        normalized = _norm(user_prompt)
        self.assertIn("cau gan nhat can tranh lap lai", normalized)
        self.assertIn("khong duoc lap lai y", normalized)
        self.assertIn("cua so mo ra", normalized)

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
        normalized_user = _norm(user_prompt)
        self.assertIn("khong triet ly", normalized_user)
        self.assertIn("speech intent", normalized_user)
        self.assertIn("chi neu dieu co trong speech_evidence da loc", normalized_user)

    def test_directive_prompt_does_not_seed_background_motion_claim(self):
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
            ni_context="drift_level=cao",
            ti_context="Mode: steady_observe.",
        )

        user_prompt = client.calls[0]["messages"][1]["content"]
        normalized_user = _norm(user_prompt)
        self.assertNotIn("chuyen dong nen", normalized_user)
        self.assertNotIn("nen canh", normalized_user)
        self.assertIn("thieu screen_facts", normalized_user)

    def test_directive_prompt_uses_requested_speech_intent(self):
        client = _FakeClient(
            [
                (
                    '{"text":"toi nghe","animation":"stand",'
                    '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                    '"debug_trace":"","next_animation":"","system_action":"","action_input":""}'
                ),
            ]
        )
        service = LlmService(client)

        service.generate_directive(
            telemetry_data="focus=general",
            speech_intent="user_requested",
        )

        user_prompt = client.calls[0]["messages"][1]["content"]
        normalized_user = _norm(user_prompt)
        self.assertIn("speech_intent=user_requested", normalized_user)
        self.assertIn("ngai vua yeu cau noi ngay", normalized_user)

    def test_inner_thought_prompt_overrides_no_telemetry_refusal(self):
        client = _FakeClient(
            [
                (
                    '{"text":"toi hoi mot cau khac","animation":"stand",'
                    '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                    '"debug_trace":"","next_animation":"","system_action":"","action_input":""}'
                ),
            ]
        )
        service = LlmService(client)

        service.generate_directive(
            telemetry_data="speech_evidence=<none>",
            ti_context=(
                "Mode: steady_observe.\n"
                "SpeechCore mode: pick a freeform line.\n"
                "- topic_seed=small_curiosity\n"
            ),
            speech_intent="user_requested",
        )

        user_prompt = client.calls[0]["messages"][1]["content"]
        normalized_user = _norm(user_prompt)
        self.assertIn("speech_intent=inner_thought", normalized_user)
        self.assertIn("thieu telemetry khong co nghia la thieu chu de", normalized_user)
        self.assertIn("duoc tu mo chu de xa hoi ngan", normalized_user)
        self.assertIn("khong tra loi bang", normalized_user)
        self.assertIn("ngai muon toi noi gi", normalized_user)


if __name__ == "__main__":
    unittest.main()
