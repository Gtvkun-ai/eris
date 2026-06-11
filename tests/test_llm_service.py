import json
import os
import sys
import unicodedata
import unittest

import requests

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


class _SequenceClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        item = self.outputs.pop(0)
        if isinstance(item, BaseException):
            raise item
        return {"choices": [{"message": {"content": item}}]}


def _http_error(status_code: int) -> requests.HTTPError:
    resp = requests.Response()
    resp.status_code = int(status_code)
    resp.url = "http://example.test/chat/completions"
    resp._content = b"upstream error"
    return requests.HTTPError(f"{status_code} Server Error", response=resp)


class LlmServiceTests(unittest.TestCase):
    def test_screen_facts_use_dedicated_vision_client(self):
        main_client = _FakeClient(['{"facts":["remote should not be used"],"debug_trace":"remote"}'])
        vision_client = _FakeClient(['{"facts":["local mmproj fact"],"debug_trace":"local_mmproj"}'])
        service = LlmService(main_client, vision_client=vision_client)

        facts, trace = service.generate_screen_facts(screen_image_data_uri="data:image/png;base64,abc")

        self.assertEqual(facts, ["local mmproj fact"])
        self.assertEqual(trace, "local_mmproj")
        self.assertEqual(len(main_client.calls), 0)
        self.assertEqual(len(vision_client.calls), 1)

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

    def test_force_speak_without_evidence_omits_specific_memory_topics(self):
        client = _FakeClient(
            [
                (
                    '{"text":"toi o day","animation":"stand",'
                    '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                    '"debug_trace":"","next_animation":"","system_action":"","action_input":""}'
                ),
            ]
        )
        service = LlmService(client)

        service.generate_directive(
            telemetry_data="speech_evidence=<none>; current_focus_kind=general",
            ti_context=(
                "ActionPlanner decision before LLM:\n"
                "- speech_act=inner_whim\n"
                "- notes=force_speak"
            ),
            memory_context="semantic_user_memory:\n- Ngai likes game and music",
            speech_intent="user_requested",
        )

        system_prompt = client.calls[0]["messages"][0]["content"]
        user_prompt = client.calls[0]["messages"][1]["content"]
        self.assertNotIn("semantic_user_memory", system_prompt)
        self.assertNotIn("game and music", system_prompt)
        self.assertIn("force_speak_neutral_presence", user_prompt)
        self.assertIn("memory context was intentionally omitted", user_prompt)
        self.assertIn("current_focus_kind=general", user_prompt)

    def test_retry_once_on_5xx_then_succeeds(self):
        good = (
            '{"text":"ok","animation":"stand",'
            '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
            '"debug_trace":"","next_animation":"","system_action":"","action_input":""}'
        )
        client = _SequenceClient([_http_error(503), good])
        service = LlmService(client)

        out = service.generate_directive(telemetry_data="focus=general")

        payload = json.loads(out)
        self.assertEqual(payload.get("text"), "ok")
        self.assertEqual(len(client.calls), 2)

    def test_retry_once_on_5xx_then_fallback(self):
        client = _SequenceClient([_http_error(502), _http_error(502)])
        service = LlmService(client)

        out = service.generate_directive(telemetry_data="focus=general")

        payload = json.loads(out)
        self.assertEqual(payload.get("intent"), "fallback_reply")
        self.assertIn("http_5xx_fallback", payload.get("debug_trace", ""))
        self.assertEqual(len(client.calls), 2)

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

    def test_directive_repairs_empty_text_json(self):
        client = _FakeClient(
            [
                (
                    '{"text":"","animation":"stand",'
                    '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                    '"debug_trace":"empty","next_animation":"","system_action":"","action_input":""}'
                ),
                (
                    '{"text":"Tôi ở đây.","animation":"stand",'
                    '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                    '"debug_trace":"empty_repaired","next_animation":"","system_action":"","action_input":""}'
                ),
            ]
        )
        service = LlmService(client)

        raw = service.generate_directive(telemetry_data="speech_evidence=<none>", speech_intent="user_requested")

        self.assertEqual(len(client.calls), 2)
        self.assertIn('"text":"Tôi ở đây."', raw)
        self.assertIn("empty_repaired", raw)

    def test_directive_allows_empty_text_for_system_action(self):
        client = _FakeClient(
            [
                (
                    '{"text":"","animation":"stand",'
                    '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                    '"debug_trace":"action","next_animation":"","system_action":"search_web","action_input":"Gemini API"}'
                ),
            ]
        )
        service = LlmService(client)

        raw = service.generate_directive(telemetry_data="focus=general")

        self.assertEqual(len(client.calls), 1)
        self.assertIn('"system_action":"search_web"', raw)
        self.assertIn('"text":""', raw)

    def test_directive_does_not_wrap_gemini_metadata_as_spoken_text(self):
        metadata = (
            '{"candidates":[{"content":{"role":"model"},"finishReason":"MAX_TOKENS","index":0}],'
            '"usageMetadata":{"promptTokenCount":5921,"totalTokenCount":6226},'
            '"modelVersion":"gemini-2.5-flash","responseId":"abc"}'
        )
        client = _FakeClient([metadata, metadata])
        service = LlmService(client)

        raw = service.generate_directive(telemetry_data="speech_evidence=<none>", speech_intent="user_requested")

        self.assertIn('"text": "Tôi ở đây."', raw)
        self.assertNotIn("candidates", raw)
        self.assertNotIn("usageMetadata", raw)

    def test_directive_does_not_speak_markdown_json_stub(self):
        client = _FakeClient(["Here is the JSON requested:\n```json", "Here is the JSON requested:\n```json"])
        service = LlmService(client)

        raw = service.generate_directive(telemetry_data="speech_evidence=<none>", speech_intent="user_requested")

        self.assertIn('"text": "Tôi ở đây."', raw)
        self.assertNotIn("Here is the JSON", raw)

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
        self.assertIn("inner_intent=curious_question must produce one real question", normalized_user)
        self.assertIn("inner_intent=inner_whim must produce one short thought", normalized_user)
        self.assertIn("khong can noi gi", normalized_user)
        self.assertIn("ngai cu lam viec", normalized_user)

    def test_random_chatter_prompt_blocks_poetic_soft_story_family(self):
        client = _FakeClient(
            [
                (
                    '{"text":"mot cau vo dung","animation":"stand",'
                    '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                    '"debug_trace":"","next_animation":"","system_action":"","action_input":""}'
                ),
            ]
        )
        service = LlmService(client)

        service.generate_directive(
            telemetry_data="speech_evidence=<none>",
            ti_context=(
                "SpeechCore mode: pick a freeform line.\n"
                "- inner_intent=random_chatter\n"
                "- topic_seed=light_presence\n"
            ),
            speech_intent="user_requested",
        )

        user_prompt = client.calls[0]["messages"][1]["content"]
        normalized_user = _norm(user_prompt)
        self.assertIn("do not be poetic", normalized_user)
        self.assertIn("do not mention stories, listening, silence, screen, or logs", normalized_user)
        self.assertIn("prefer mundane, playful, concrete one-liners", normalized_user)
        self.assertIn("slightly absurd", normalized_user)
        self.assertIn("not emotional or dramatic", normalized_user)
        self.assertIn("cau chuyen nho", normalized_user)
        self.assertIn("dong log kho khan", normalized_user)

    def test_extracts_gemini_generate_content_response(self):
        client = _FakeClient([])
        service = LlmService(client)

        text = service._extract_content(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": (
                                        '{"text":"xin chao","animation":"stand",'
                                        '"direction":0,"target_x":-1.0,"bounce_action":"",'
                                        '"extracted_fact":"","debug_trace":"gemini",'
                                        '"next_animation":"","system_action":"","action_input":""}'
                                    )
                                }
                            ]
                        }
                    }
                ]
            }
        )

        self.assertIn('"debug_trace":"gemini"', text)

    def test_local_style_rewrite_only_changes_safe_text(self):
        main_client = _FakeClient([])
        style_client = _FakeClient(['{"text":"Ngài gọi, tôi ở đây."}'])
        service = LlmService(main_client, style_client=style_client)
        decision = type("DecisionLike", (), {"text": "Tôi ở đây khi Ngài gọi.", "debug_trace": "", "system_action": ""})()

        rewritten = service.rewrite_text_with_local_style(decision, channel="chat")

        self.assertEqual(rewritten.text, "Ngài gọi, tôi ở đây.")
        self.assertIn("local_style_rewrite", rewritten.debug_trace)
        self.assertEqual(len(style_client.calls), 1)

    def test_local_style_rewrite_rejects_new_screen_claim(self):
        main_client = _FakeClient([])
        style_client = _FakeClient(['{"text":"Tôi thấy màn hình của Ngài đang mở code."}'])
        service = LlmService(main_client, style_client=style_client)
        decision = type("DecisionLike", (), {"text": "Tôi ở đây.", "debug_trace": "", "system_action": ""})()

        rewritten = service.rewrite_text_with_local_style(decision, channel="chat")

        self.assertEqual(rewritten.text, "Tôi ở đây.")
        self.assertEqual(rewritten.debug_trace, "")


if __name__ == "__main__":
    unittest.main()
