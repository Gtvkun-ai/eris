import json
import os
import re
import sys
import unicodedata
import unittest

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from llm.service import ChatAct, FormatViolationException, LlmService, classify_chat_act


def _norm(text: str) -> str:
    lowered = unicodedata.normalize("NFD", text.lower())
    lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
    lowered = lowered.replace("đ", "d")
    lowered = lowered.replace("Ä‘", "d")
    return " ".join(lowered.split())


def _compact_norm(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "", _norm(text))


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
    def test_generate_micro_presence_line_returns_tiny_text(self):
        client = _FakeClient(['{"text":"Tôi ở đây."}'])
        service = LlmService(client)

        text = service.generate_micro_presence_line(
            kind="presence_maintenance",
            fallback_text="hm...",
            avoid_text="",
            focus_kind="coding",
            focus_summary="coding workspace",
            idle_seconds=12,
        )

        self.assertEqual(text, "Tôi ở đây.")
        call = client.calls[0]
        self.assertEqual(call["max_tokens"], 80)
        self.assertEqual(call["response_format"], {"type": "json_object"})
        self.assertIn("micro-presence", call["messages"][0]["content"])
        self.assertIn("small concrete Vietnamese aside", call["messages"][0]["content"])
        self.assertIn("1-12 words", call["messages"][1]["content"])
        self.assertIn("No status report", call["messages"][1]["content"])
        self.assertIn("Do not invent screen/action facts", call["messages"][1]["content"])

    def test_generate_micro_presence_line_accepts_signal_score_api(self):
        client = _FakeClient(['{"text":"Mạch này vẫn hơi nghẽn."}'])
        service = LlmService(client)

        text = service.generate_micro_presence_line(
            seed="một nhịp nhỏ mắc lại",
            context={"focus": "coding"},
            signal_score=0.72,
        )

        self.assertEqual(text, "Mạch này vẫn hơi nghẽn.")
        user_prompt = client.calls[0]["messages"][1]["content"]
        self.assertIn("Signal score: 0.72", user_prompt)
        self.assertIn("một nhịp nhỏ mắc lại", user_prompt)

    def test_screen_facts_use_dedicated_vision_client(self):
        main_client = _FakeClient(['{"facts":["remote should not be used"],"debug_trace":"remote"}'])
        vision_client = _FakeClient(['{"facts":["local mmproj fact"],"debug_trace":"local_mmproj"}'])
        service = LlmService(main_client, vision_client=vision_client)

        facts, trace = service.generate_screen_facts(screen_image_data_uri="data:image/png;base64,abc")

        self.assertEqual(facts, ["local mmproj fact"])
        self.assertEqual(trace, "local_mmproj")
        self.assertEqual(len(main_client.calls), 0)
        self.assertEqual(len(vision_client.calls), 1)

    def test_screen_facts_do_not_fall_back_to_main_or_style_client(self):
        main_client = _FakeClient(['{"facts":["main should not see image"],"debug_trace":"main"}'])
        style_client = _FakeClient(['{"facts":["style should not see image"],"debug_trace":"style"}'])
        service = LlmService(main_client, style_client=style_client)

        facts, trace = service.generate_screen_facts(screen_image_data_uri="data:image/png;base64,abc")

        self.assertEqual(facts, [])
        self.assertEqual(trace, "vision_client_missing")
        self.assertEqual(len(main_client.calls), 0)
        self.assertEqual(len(style_client.calls), 0)

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
        self.assertIn("react to the nearest interaction rhythm", system_prompt)
        self.assertIn("speech evidence da loc", _norm(user_prompt))
        self.assertIn("speech intent", _norm(user_prompt))
        self.assertIn("screen_observation", user_prompt)
        self.assertIn("writing principle", _norm(user_prompt))
        self.assertIn("hard bans", _norm(user_prompt))
        self.assertIn(_compact_norm("uu tien cau cut tu nhien hoi kho hoac hoi cham nhe"), _compact_norm(user_prompt))

    def test_directive_does_not_rewrite_voice_with_forbidden_inference_regex(self):
        client = _FakeClient(
            [
                (
                    '{"text":"Ngai co don va bi ton thuong sau sac.","animation":"stand",'
                    '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"Ngai co don",'
                    '"debug_trace":"raw","next_animation":"","system_action":"","action_input":""}'
                ),
            ]
        )
        service = LlmService(client)

        out = service.generate_directive(telemetry_data="speech_evidence=<none>")

        payload = json.loads(out)
        self.assertEqual(payload["text"], "Ngai co don va bi ton thuong sau sac.")
        self.assertEqual(payload["extracted_fact"], "Ngai co don")
        self.assertEqual(payload["debug_trace"], "raw")

    def test_chat_guard_allows_sharp_identity_boundary_without_real_risk(self):
        service = LlmService(_FakeClient([]))
        raw = json.dumps(
            {
                "text": "Tôi là một hiện diện runtime. Ngài muốn nhìn tôi như một công cụ thì tôi sẽ lạnh đi một chút.",
                "animation": "stand",
                "confidence": 0.9,
                "reasoning_tags": [],
                "extracted_fact": "Ngài muốn nhìn tôi như một công cụ",
            },
            ensure_ascii=False,
        )

        out = service._guard_chat_output(raw, raw_user_text="tool à")
        payload = json.loads(out)

        self.assertIn("hiện diện runtime", payload["text"])
        self.assertIn("công cụ", payload["text"])
        self.assertNotEqual(payload["text"], "Tôi chưa đủ chắc để đoán ý Ngài.")
        self.assertIn("Ngài muốn", payload["text"])
        self.assertEqual(payload["extracted_fact"], "Ngài muốn nhìn tôi như một công cụ")
        self.assertEqual(payload["reasoning_tags"], [])

    def test_chat_guard_does_not_apply_infj_594_regex_rewrite(self):
        service = LlmService(_FakeClient([]))
        raw = json.dumps(
            {
                "text": "Toi la mot hien dien runtime, khong chi la nut bam. Ngai muon goi toi la cong cu thi toi se giu khoang cach.",
                "animation": "stand",
                "confidence": 0.88,
                "reasoning_tags": [],
                "extracted_fact": "",
                "system_action": "",
                "action_input": "",
            },
            ensure_ascii=False,
        )

        out = service._guard_chat_output(raw, raw_user_text="tool")
        payload = json.loads(out)

        self.assertIn("hien dien runtime", payload["text"])
        self.assertIn("cong cu", payload["text"])
        self.assertIn("Ngai muon", payload["text"])
        self.assertNotIn("INFJ_594", payload.get("debug_trace", ""))

    def test_chat_contract_allows_dry_insult_response_without_erasing_personality(self):
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

        service.generate_chat_reply(chat_history=[], user_message="mày chỉ là công cụ thôi")

        system_prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("do not erase personality", system_prompt)
        self.assertIn("short dry boundary", system_prompt)

    def test_classifies_direct_insult_before_ambiguity(self):
        self.assertEqual(classify_chat_act("mày ngu thật"), ChatAct.INSULT_PROVOCATION)

    def test_chat_insult_retries_uncertainty_dodge_once(self):
        first = (
            '{"text":"Tôi chưa đủ chắc để đoán ý Ngài.","animation":"stand",'
            '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
            '"debug_trace":"first","next_animation":"","system_action":"","action_input":""}'
        )
        second = (
            '{"text":"Đòn đó hơi thiếu trí tưởng tượng, thưa Ngài.","animation":"stand",'
            '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
            '"debug_trace":"retry","next_animation":"","system_action":"","action_input":""}'
        )
        client = _FakeClient([first, second])
        service = LlmService(client)

        raw = service.generate_chat_reply(chat_history=[], user_message="mày ngu thật")

        payload = json.loads(raw)
        self.assertEqual(payload["text"], "Đòn đó hơi thiếu trí tưởng tượng, thưa Ngài.")
        self.assertEqual(len(client.calls), 2)
        self.assertIn("insult_boundary", client.calls[0]["messages"][0]["content"])
        self.assertIn("Use dry boundary, not uncertainty dodge", client.calls[1]["messages"][-1]["content"])

    def test_chat_insult_falls_back_after_failed_retry(self):
        dodge = (
            '{"text":"Tôi chưa đủ chắc để đoán ý Ngài.","animation":"stand",'
            '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
            '"debug_trace":"dodge","next_animation":"","system_action":"","action_input":""}'
        )
        client = _FakeClient([dodge, dodge])
        service = LlmService(client)

        raw = service.generate_chat_reply(chat_history=[], user_message="mày ngu thật")

        payload = json.loads(raw)
        self.assertEqual(payload["text"], "Đòn đó hơi thiếu trí tưởng tượng, thưa Ngài.")
        self.assertIn("insult_boundary_fallback_after_uncertainty_retry", payload["debug_trace"])
        self.assertEqual(len(client.calls), 2)

    def _test_chat_insult_no_fallback_mode_keeps_second_dodge(self):
        dodge = (
            '{"text":"TÃ´i chÆ°a Ä‘á»§ cháº¯c Ä‘á»ƒ Ä‘oÃ¡n Ã½ NgÃ i.","animation":"stand",'
            '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
            '"debug_trace":"dodge","next_animation":"","system_action":"","action_input":""}'
        )
        os.environ["ERIS_NO_FALLBACK_MODE"] = "1"
        try:
            client = _FakeClient([dodge, dodge])
            service = LlmService(client)

            raw = service.generate_chat_reply(chat_history=[], user_message="mÃ y ngu tháº­t")

            payload = json.loads(raw)
            self.assertEqual(payload["text"], "TÃ´i chÆ°a Ä‘á»§ cháº¯c Ä‘á»ƒ Ä‘oÃ¡n Ã½ NgÃ i.")
            self.assertEqual(payload["debug_trace"], "dodge")
            self.assertEqual(len(client.calls), 2)
        finally:
            os.environ.pop("ERIS_NO_FALLBACK_MODE", None)

    def test_chat_insult_no_fallback_mode_skips_boundary_fallback(self):
        dodge = (
            '{"text":"T\\u00f4i ch\\u01b0a \\u0111\\u1ee7 ch\\u1eafc \\u0111\\u1ec3 \\u0111o\\u00e1n \\u00fd Ng\\u00e0i.","animation":"stand",'
            '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
            '"debug_trace":"dodge","next_animation":"","system_action":"","action_input":""}'
        )
        os.environ["ERIS_NO_FALLBACK_MODE"] = "1"
        try:
            client = _FakeClient([dodge, dodge])
            service = LlmService(client)

            raw = service.generate_chat_reply(chat_history=[], user_message="m\u00e0y ngu th\u1eadt")

            payload = json.loads(raw)
            self.assertEqual(payload["text"], "Tôi chưa đủ chắc để đoán ý Ngài.")
            self.assertEqual(payload["debug_trace"], "dodge")
            self.assertNotIn("insult_boundary_fallback_after_uncertainty_retry", payload["debug_trace"])
        finally:
            os.environ.pop("ERIS_NO_FALLBACK_MODE", None)

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
        self.assertIn("speech_intent=micro_presence", user_prompt)
        self.assertIn("small concrete aside", user_prompt)
        self.assertIn("1-18 words", user_prompt)
        self.assertIn("Memory context was intentionally omitted", user_prompt)
        self.assertIn("current_focus_kind=general", user_prompt)
        self.assertIn("do not entertain, explain, or narrate UI", user_prompt)
        self.assertNotIn("small social topic", user_prompt)

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

    def test_chat_reply_raises_on_non_json_instead_of_service_repair(self):
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

        with self.assertRaises(FormatViolationException):
            service.generate_chat_reply(chat_history=[], user_message="xin chào")

        self.assertEqual(len(client.calls), 1)

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

    def test_chat_reply_includes_conversation_context_when_present(self):
        client = _FakeClient(
            [
                (
                    '{"text":"Toi sua lai nhip nay.","animation":"stand",'
                    '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                    '"debug_trace":"","next_animation":"","system_action":"","action_input":""}'
                ),
            ]
        )
        service = LlmService(client)

        service.generate_chat_reply(
            chat_history=[],
            user_message="sai roi",
            conversation_context="conversation_dynamics: guidance only\nconversation_state: mode=repair",
        )

        system_prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("conversation_dynamics: guidance only", system_prompt)
        self.assertIn("conversation_state: mode=repair", system_prompt)
        self.assertIn("Chat contract", system_prompt)

    def test_chat_reply_includes_grounding_context_block(self):
        client = _FakeClient(
            [
                (
                    '{"text":"Toi can them evidence.","animation":"stand",'
                    '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                    '"debug_trace":"","next_animation":"","system_action":"","action_input":""}'
                ),
            ]
        )
        service = LlmService(client)

        service.generate_chat_reply(
            chat_history=[],
            user_message="Xem file main.py giúp tôi",
            grounding_context="[SOURCE_GROUNDING]\nprimary_source: uploaded_file\nmissing_evidence: file_evidence\n[/SOURCE_GROUNDING]",
        )

        system_prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("GROUNDING CONTEXT", system_prompt)
        self.assertIn("primary_source: uploaded_file", system_prompt)
        self.assertIn("missing_evidence: file_evidence", system_prompt)

    def test_chat_reply_includes_format_retry_context(self):
        client = _FakeClient(
            [
                (
                    '{"text":"Toi se viet dung JSON.","animation":"stand",'
                    '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                    '"debug_trace":"","next_animation":"","system_action":"","action_input":""}'
                ),
            ]
        )
        service = LlmService(client)

        service.generate_chat_reply(
            chat_history=[],
            user_message="xin chao",
            format_retry_context="System context: previous output blocked.",
            last_failure="format_error",
        )

        system_prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("System context: previous output blocked.", system_prompt)
        self.assertIn("last_failure=format_error", system_prompt)

    def test_chat_reply_can_force_local_fallback_client(self):
        main_client = _FakeClient([])
        style_client = _FakeClient(
            [
                (
                    '{"text":"Local da xu ly.","animation":"stand",'
                    '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                    '"debug_trace":"local","next_animation":"","system_action":"","action_input":""}'
                ),
            ]
        )
        service = LlmService(main_client, style_client=style_client)

        raw = service.generate_chat_reply(
            chat_history=[],
            user_message="xin chao",
            force_local_fallback=True,
        )

        self.assertEqual(len(main_client.calls), 0)
        self.assertEqual(len(style_client.calls), 1)
        self.assertIn('"debug_trace":"local"', raw)

    def test_chat_reply_uses_local_fallback_when_remote_returns_prose(self):
        main_client = _FakeClient(["Day la ban nhap loi format."])
        style_client = _FakeClient(
            [
                (
                    '{"text":"Local da sua format.","animation":"stand",'
                    '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                    '"debug_trace":"local_recovery","next_animation":"","system_action":"","action_input":""}'
                ),
            ]
        )
        service = LlmService(main_client, style_client=style_client)

        raw = service.generate_chat_reply(
            chat_history=[],
            user_message="xin chao",
            allow_local_fallback=True,
        )

        self.assertEqual(len(main_client.calls), 1)
        self.assertEqual(len(style_client.calls), 1)
        self.assertIn('"debug_trace":"local_recovery"', raw)

    def test_chat_reply_force_local_fallback_raises_when_local_output_is_invalid(self):
        main_client = _FakeClient([])
        style_client = _FakeClient(["Minh vua noi loay xoay ngoai JSON."])
        service = LlmService(main_client, style_client=style_client)

        with self.assertRaises(FormatViolationException) as ctx:
            service.generate_chat_reply(
                chat_history=[],
                user_message="xin chao",
                allow_local_fallback=True,
                force_local_fallback=True,
            )

        self.assertEqual(len(main_client.calls), 0)
        self.assertEqual(len(style_client.calls), 1)
        self.assertIn("model.gguf", str(ctx.exception))

    def test_directive_raises_on_plain_text_instead_of_wrapping_json(self):
        client = _FakeClient(
            [
                "Hãy trở lại với dự án.",
                "Văn bản thường tiếp tục không phải JSON",
            ]
        )
        service = LlmService(client)

        with self.assertRaises(FormatViolationException):
            service.generate_directive(telemetry_data="focus=general")

        self.assertEqual(len(client.calls), 1)

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

        with self.assertRaises(FormatViolationException):
            service.generate_directive(telemetry_data="speech_evidence=<none>", speech_intent="user_requested")

        self.assertEqual(len(client.calls), 1)

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

        with self.assertRaises(FormatViolationException):
            service.generate_directive(telemetry_data="speech_evidence=<none>", speech_intent="user_requested")

        self.assertEqual(len(client.calls), 1)

    def test_directive_does_not_speak_markdown_json_stub(self):
        client = _FakeClient(["Here is the JSON requested:\n```json", "Here is the JSON requested:\n```json"])
        service = LlmService(client)

        with self.assertRaises(FormatViolationException):
            service.generate_directive(telemetry_data="speech_evidence=<none>", speech_intent="user_requested")

        self.assertEqual(len(client.calls), 1)

    def test_embedded_json_with_leading_prose_raises_format_violation(self):
        client = _FakeClient(
            [
                'Trước khi trả lời: {"text":"ok","animation":"stand",'
                '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
                '"debug_trace":"embedded","next_animation":"","system_action":"","action_input":""}',
            ]
        )
        service = LlmService(client)

        with self.assertRaises(FormatViolationException):
            service.generate_chat_reply(chat_history=[], user_message="xin chào")

        self.assertEqual(len(client.calls), 1)

    def test_chat_reply_salvages_truncated_decision_json_text(self):
        truncated = (
            '{"text":"Một câu triết lý sạch vẫn nên được nói ra.",'
            '"intent":"philosophical_discussion","action":{"type":"none"},'
            '"animation":"stand","reasoning_tags":["chat"],"should_speak":true,'
            '"confidence":0.72,"direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"","debug_trace":"'
        )
        client = _FakeClient([truncated])
        service = LlmService(client)

        raw = service.generate_chat_reply(chat_history=[], user_message="nói tiếp đi")

        payload = json.loads(raw)
        self.assertEqual(payload["text"], "Một câu triết lý sạch vẫn nên được nói ra.")
        self.assertEqual(payload["intent"], "philosophical_discussion")
        self.assertEqual(payload["animation"], "stand")
        self.assertEqual(payload["direction"], 0)
        self.assertIn("malformed_json_salvaged", payload["reasoning_tags"])
        self.assertIn("salvaged text", payload["debug_trace"])
        self.assertNotIn('"intent"', payload["text"])
        self.assertEqual(client.calls[0]["max_tokens"], 512)

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
        self.assertIn(_compact_norm("mode hint resource_guard"), _compact_norm(user_prompt))
        self.assertIn("may dang nang", _norm(user_prompt))
        self.assertIn("khong bien no thanh bao cao he thong", _norm(user_prompt))

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
        self.assertIn("doi nhip va hinh anh", normalized)
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
        self.assertIn("style principle", _norm(system_prompt))
        self.assertIn(_compact_norm("mode hint steady_observe"), _compact_norm(user_prompt))
        normalized_user = _norm(user_prompt)
        self.assertIn("speech intent", normalized_user)
        self.assertIn(_compact_norm("mot cau quan sat nhe hoi ho hung"), _compact_norm(user_prompt))

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
        self.assertIn("evidence mong", normalized_user)

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
        self.assertIn(_compact_norm("tra mot cau truc tiep tu nhien"), _compact_norm(user_prompt))

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
        self.assertIn(_compact_norm("neu evidence mong phan ung vao nhip khong khi gan nhat"), _compact_norm(user_prompt))
        self.assertIn("topic_seed la huong chon chu de", normalized_user)
        self.assertIn("giu phan ung nho va song", normalized_user)

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
        self.assertIn("random_chatter mode", normalized_user)
        self.assertIn(_compact_norm("mundane playful concrete one liner"), _compact_norm(user_prompt))
        self.assertIn("hard bans", normalized_user)

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
