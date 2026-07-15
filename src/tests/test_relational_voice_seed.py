from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import pytest
import requests
from hypothesis import given, strategies as st

from runtime.relational_voice_seed_adapter import (
    ChatRegister,
    CognitionStance,
    RelationalAct,
    RelationalVoiceSeedAdapter,
    RelationalVoiceSeedConfig,
    VoiceSeedScope,
    classify_chat_register,
    detect_relational_act,
    should_use_voice_seed,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeClient:
    """Returns a canned content string, or raises a configured exception."""

    def __init__(self, content: str = "", *, error: Exception | None = None):
        self.content = content
        self.error = error
        self.calls = 0

    def create_chat_completion(self, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return {"choices": [{"message": {"content": self.content}}]}


class _FakeLlmService:
    def __init__(self, *, style_client=None, client=None):
        self.style_client = style_client
        self.client = client

    def _extract_content(self, resp) -> str:
        try:
            return str(resp["choices"][0]["message"]["content"] or "")
        except Exception:
            return ""


def _http_429() -> requests.HTTPError:
    resp = requests.Response()
    resp.status_code = 429
    return requests.HTTPError("429 Too Many Requests", response=resp)


def _social_stance(act: RelationalAct = RelationalAct.AFFECTION) -> CognitionStance:
    return CognitionStance(register=ChatRegister.SOCIAL, scope=VoiceSeedScope.SOCIAL, act=act)


def _adapter(style_client=None, client=None, scope=VoiceSeedScope.SOCIAL) -> RelationalVoiceSeedAdapter:
    return RelationalVoiceSeedAdapter(
        llm_service=_FakeLlmService(style_client=style_client, client=client),
        config=RelationalVoiceSeedConfig(enabled=True, scope=scope),
    )


# ---------------------------------------------------------------------------
# detect_relational_act
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("em là gì", RelationalAct.SELF_IDENTITY),
        ("em là cái gì trên thế giới này", RelationalAct.SELF_IDENTITY),
        ("bạn là ai", RelationalAct.SELF_IDENTITY),
        ("em có thích tôi khôngggg", RelationalAct.AFFECTION),
        ("em có cảm xúc không nè", RelationalAct.HAS_FEELINGS),
        ("em không thấy buồn sao", RelationalAct.SADNESS),
        ("em còn xa cách với tôi đúng không", RelationalAct.DISTANCE),
        ("giải thích cho tôi cách dùng asyncio", RelationalAct.NONE),
        ("", RelationalAct.NONE),
    ],
)
def test_detect_relational_act(text, expected):
    assert detect_relational_act(text) is expected


def test_detect_relational_act_diacritic_insensitive():
    assert detect_relational_act("em co thich toi khong") is RelationalAct.AFFECTION


# ---------------------------------------------------------------------------
# classify_chat_register
# ---------------------------------------------------------------------------

def test_register_task_from_ti_mode_code():
    assert classify_chat_register("bất kỳ", ti_mode="chat_code") is ChatRegister.TASK


@pytest.mark.parametrize("text", ["fix lỗi này giúp tôi", "viết hàm sort", "giải thích asyncio"])
def test_register_task_from_code_heuristic(text):
    assert classify_chat_register(text) is ChatRegister.TASK


def test_register_task_from_chat_act_command():
    assert classify_chat_register("mở giúp file", chat_act_name="command_style") is ChatRegister.TASK


def test_register_task_from_insult_act():
    assert classify_chat_register("đồ ngu", chat_act_name="insult_provocation") is ChatRegister.TASK


@pytest.mark.parametrize("text", ["em là gì", "em có buồn không", "ừ hôm nay mệt quá", "chào em"])
def test_register_social_default(text):
    assert classify_chat_register(text, ti_mode="chat_general") is ChatRegister.SOCIAL


@pytest.mark.parametrize(
    "text",
    ["màn hình này là gì", "em có thấy gì ở màn hình tôi không", "em thấy nhạc youtube gì không"],
)
def test_register_task_from_perception(text):
    # Screen/vision questions must stay on the grounded path, not the persona seed.
    assert classify_chat_register(text, ti_mode="chat_general") is ChatRegister.TASK


# ---------------------------------------------------------------------------
# should_use_voice_seed truth table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "register, scope, act, expected",
    [
        (ChatRegister.SOCIAL, VoiceSeedScope.OFF, RelationalAct.AFFECTION, False),
        (ChatRegister.TASK, VoiceSeedScope.OFF, RelationalAct.NONE, False),
        (ChatRegister.SOCIAL, VoiceSeedScope.RELATIONAL, RelationalAct.NONE, False),
        (ChatRegister.SOCIAL, VoiceSeedScope.RELATIONAL, RelationalAct.AFFECTION, True),
        (ChatRegister.TASK, VoiceSeedScope.RELATIONAL, RelationalAct.AFFECTION, True),
        (ChatRegister.SOCIAL, VoiceSeedScope.SOCIAL, RelationalAct.NONE, True),
        (ChatRegister.TASK, VoiceSeedScope.SOCIAL, RelationalAct.AFFECTION, False),
        (ChatRegister.TASK, VoiceSeedScope.ALWAYS, RelationalAct.NONE, True),
        (ChatRegister.SOCIAL, VoiceSeedScope.ALWAYS, RelationalAct.NONE, True),
    ],
)
def test_should_use_voice_seed_table(register, scope, act, expected):
    assert should_use_voice_seed(register, scope, act) is expected


@given(
    register=st.sampled_from(list(ChatRegister)),
    scope=st.sampled_from(list(VoiceSeedScope)),
    act=st.sampled_from(list(RelationalAct)),
)
def test_should_use_voice_seed_property(register, scope, act):
    result = should_use_voice_seed(register, scope, act)
    if scope is VoiceSeedScope.OFF:
        assert result is False
    elif scope is VoiceSeedScope.ALWAYS:
        assert result is True
    elif scope is VoiceSeedScope.SOCIAL:
        assert result is (register is ChatRegister.SOCIAL)
    else:  # RELATIONAL
        assert result is (act is not RelationalAct.NONE)


# ---------------------------------------------------------------------------
# _join anti-repeat
# ---------------------------------------------------------------------------

def test_join_normal():
    a = _adapter()
    assert a._join("Tôi quen có bạn ở đây.", "Gọi đó là gì thì tùy bạn.") == \
        "Tôi quen có bạn ở đây. Gọi đó là gì thì tùy bạn."


def test_join_drops_leading_echo():
    a = _adapter()
    out = a._join("Tôi quen có bạn ở đây.", "Tôi quen có bạn ở đây. Gọi đó là gì thì tùy bạn.")
    assert out.count("Tôi quen có bạn ở đây") == 1
    assert out.startswith("Tôi quen có bạn ở đây")


def test_join_pure_echo_returns_seed():
    a = _adapter()
    assert a._join("Tôi quen có bạn ở đây.", "Tôi quen có bạn ở đây.") == "Tôi quen có bạn ở đây."


def test_join_whitespace_collapsed():
    a = _adapter()
    assert a._join("  Ừ.  ", "  câu đó lạnh thật.  ") == "Ừ. câu đó lạnh thật."


# ---------------------------------------------------------------------------
# try_answer — degrade ladder + contract
# ---------------------------------------------------------------------------

def test_try_answer_normal_join():
    seed = _FakeClient("Tôi quen có bạn ở đây.")
    cont = _FakeClient("Gọi đó là gì thì tùy bạn.")
    a = _adapter(style_client=seed, client=cont)
    d = a.try_answer("em có thích tôi không", stance=_social_stance())
    assert d is not None
    assert d.text == "Tôi quen có bạn ở đây. Gọi đó là gì thì tùy bạn."
    assert d.parse_mode == "relational_voice_seed"
    assert d.extracted_fact == ""
    assert "voice_seed_mode:joined" in d.reasoning_tags
    assert seed.calls == 1 and cont.calls == 1  # one call each (P2)


def test_try_answer_seed_only_on_llama_429():
    seed = _FakeClient("Tôi quen có bạn ở đây.")
    cont = _FakeClient(error=_http_429())
    a = _adapter(style_client=seed, client=cont)
    d = a.try_answer("em có thích tôi không", stance=_social_stance())
    assert d is not None
    assert d.text == "Tôi quen có bạn ở đây."
    assert "voice_seed_mode:seed_only" in d.reasoning_tags
    assert "rate_limited" in d.debug_trace


@pytest.mark.parametrize("err", [requests.Timeout("slow"), RuntimeError("x")])
def test_try_answer_seed_only_on_llama_failure(err):
    seed = _FakeClient("Có lẽ tôi quá quen với sự im lặng.")
    cont = _FakeClient(error=err)
    a = _adapter(style_client=seed, client=cont)
    d = a.try_answer("em không thấy buồn sao", stance=_social_stance(RelationalAct.SADNESS))
    assert d is not None and d.text == "Có lẽ tôi quá quen với sự im lặng."
    assert "voice_seed_mode:seed_only" in d.reasoning_tags


def test_try_answer_seed_only_on_dirty_tail():
    seed = _FakeClient("Tôi quen có bạn ở đây.")
    cont = _FakeClient("tôi chỉ cố gắng hỗ trợ và giúp đỡ bạn.")
    a = _adapter(style_client=seed, client=cont)
    d = a.try_answer("em có thích tôi không", stance=_social_stance())
    assert d is not None and d.text == "Tôi quen có bạn ở đây."
    assert "voice_seed_mode:seed_only" in d.reasoning_tags


def test_try_answer_fall_through_on_gemma_429():
    seed = _FakeClient(error=_http_429())
    cont = _FakeClient("never reached")
    a = _adapter(style_client=seed, client=cont)
    assert a.try_answer("em có thích tôi không", stance=_social_stance()) is None
    assert cont.calls == 0


def test_try_answer_fall_through_on_dirty_seed():
    seed = _FakeClient("tôi không thể thích hay không thích, nhưng tôi có thể hỗ trợ.")
    cont = _FakeClient("tail")
    a = _adapter(style_client=seed, client=cont)
    assert a.try_answer("em có thích tôi không", stance=_social_stance()) is None
    assert cont.calls == 0


def test_try_answer_gate_denies_task_register():
    seed = _FakeClient("seed")
    a = _adapter(style_client=seed, client=_FakeClient("tail"))
    stance = CognitionStance(register=ChatRegister.TASK, scope=VoiceSeedScope.SOCIAL, act=RelationalAct.NONE)
    assert a.try_answer("fix lỗi này", stance=stance) is None
    assert seed.calls == 0


def test_try_answer_scope_off_denies():
    seed = _FakeClient("seed")
    a = _adapter(style_client=seed, client=_FakeClient("tail"), scope=VoiceSeedScope.OFF)
    stance = CognitionStance(register=ChatRegister.SOCIAL, scope=VoiceSeedScope.OFF, act=RelationalAct.AFFECTION)
    assert a.try_answer("em có thích tôi không", stance=stance) is None
    assert seed.calls == 0


def test_try_answer_never_raises_and_falls_through():
    class _Boom:
        def create_chat_completion(self, **kwargs):
            raise ValueError("unexpected")

    a = _adapter(style_client=_Boom(), client=_FakeClient("tail"))
    assert a.try_answer("em có thích tôi không", stance=_social_stance()) is None


def test_try_answer_seed_only_when_no_llama_client():
    seed = _FakeClient("Tôi quen có bạn ở đây.")
    a = _adapter(style_client=seed, client=None)
    d = a.try_answer("em có thích tôi không", stance=_social_stance())
    assert d is not None and d.text == "Tôi quen có bạn ở đây."


def test_try_answer_never_returns_empty_text():
    seed = _FakeClient("")  # empty seed -> fall through
    a = _adapter(style_client=seed, client=_FakeClient("tail"))
    d = a.try_answer("em có thích tôi không", stance=_social_stance())
    assert d is None  # empty seed falls through; never an empty Decision


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

def test_config_scope_from_env(monkeypatch):
    monkeypatch.setenv("ERIS_VOICE_SEED_SCOPE", "always")
    assert RelationalVoiceSeedConfig.from_env().scope is VoiceSeedScope.ALWAYS
    monkeypatch.setenv("ERIS_VOICE_SEED_SCOPE", "garbage")
    assert RelationalVoiceSeedConfig.from_env().scope is VoiceSeedScope.SOCIAL
    monkeypatch.delenv("ERIS_VOICE_SEED_SCOPE", raising=False)
    assert RelationalVoiceSeedConfig.from_env().scope is VoiceSeedScope.SOCIAL


# ---------------------------------------------------------------------------
# Property: try_answer is total (None or non-empty Decision; never raises)
# ---------------------------------------------------------------------------

_BEHAVIORS = ["clean", "429", "timeout", "empty", "dirty"]


def _client_for(behavior: str, content: str) -> _FakeClient:
    if behavior == "429":
        return _FakeClient(error=_http_429())
    if behavior == "timeout":
        return _FakeClient(error=requests.Timeout("slow"))
    if behavior == "empty":
        return _FakeClient("")
    if behavior == "dirty":
        return _FakeClient("tôi chỉ cố gắng hỗ trợ và giúp đỡ.")
    return _FakeClient(content)


@given(seed_b=st.sampled_from(_BEHAVIORS), cont_b=st.sampled_from(_BEHAVIORS))
def test_try_answer_total(seed_b, cont_b):
    seed = _client_for(seed_b, "Tôi quen có bạn ở đây.")
    cont = _client_for(cont_b, "Gọi đó là gì thì tùy bạn.")
    a = _adapter(style_client=seed, client=cont)
    d = a.try_answer("em có thích tôi không", stance=_social_stance())
    assert d is None or (d.text and d.text.strip())
    assert seed.calls <= 1 and cont.calls <= 1  # P2


# ---------------------------------------------------------------------------
# Cost / latency observability (roadmap item 5)
# ---------------------------------------------------------------------------

class _CapturingLogger:
    def __init__(self):
        self.infos: list[str] = []

    def info(self, fmt, *args):
        try:
            self.infos.append(fmt % args if args else str(fmt))
        except Exception:
            self.infos.append(str(fmt))

    def warning(self, *a, **k):
        pass


def test_voice_seed_logs_cost_summary_on_joined_turn() -> None:
    logger = _CapturingLogger()
    adapter = RelationalVoiceSeedAdapter(
        llm_service=_FakeLlmService(
            style_client=_FakeClient("Tôi quen có bạn ở đây."),
            client=_FakeClient("Gọi đó là gì thì tùy bạn."),
        ),
        config=RelationalVoiceSeedConfig(enabled=True, scope=VoiceSeedScope.SOCIAL),
        logger=logger,
    )
    decision = adapter.try_answer("em có thích tôi không", stance=_social_stance())
    assert decision is not None
    cost_lines = [line for line in logger.infos if "[voice_seed]" in line]
    assert cost_lines, "expected a [voice_seed] cost/latency summary line"
    assert "mode=joined" in cost_lines[-1]
    assert "scope=social" in cost_lines[-1]
    # The realized per-call timing is threaded into the decision trace too.
    assert "cont=ok" in (decision.debug_trace or "")


def test_voice_seed_logs_cost_summary_on_seed_only_turn() -> None:
    logger = _CapturingLogger()
    adapter = RelationalVoiceSeedAdapter(
        llm_service=_FakeLlmService(
            style_client=_FakeClient("Tôi quen có bạn ở đây."),
            client=_FakeClient(error=_http_429()),
        ),
        config=RelationalVoiceSeedConfig(enabled=True, scope=VoiceSeedScope.SOCIAL),
        logger=logger,
    )
    decision = adapter.try_answer("em có thích tôi không", stance=_social_stance())
    assert decision is not None
    cost_lines = [line for line in logger.infos if "[voice_seed]" in line]
    assert cost_lines and "mode=seed_only" in cost_lines[-1]
